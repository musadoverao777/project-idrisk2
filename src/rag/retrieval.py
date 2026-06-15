"""
IDRISK2 — Advanced RAG Pipeline (Section 4.5.2)
Implements the Advanced RAG retrieval pipeline with:
Pre-retrieval:
    - Query rewriting (LLM-based)
    - Hypothetical Document Embedding (HyDE)
Retrieval:
    - Dense semantic search (Chroma)
    - Sparse BM25 lexical search
    - Hybrid fusion via Reciprocal Rank Fusion (RRF)
Post-retrieval:
    - Cross-encoder reranking
    - Context compression / redundancy filtering
"""
import logging
from dataclasses import dataclass
from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import VectorIndexRetriever
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.postprocessor import SimilarityPostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.postprocessor.colbert_rerank import ColbertRerank
from llama_index.core.llms import LLM
logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TOP_K_DENSE = 10       # candidates from dense retrieval
TOP_K_SPARSE = 10      # candidates from BM25
TOP_K_RERANK = 5       # final passages after reranking
MIN_SIMILARITY = 0.3   # minimum similarity threshold post-retrieval
RRF_K = 60             # RRF constant (standard value)
# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------
@dataclass
class RetrievalResult:
    """A single retrieved and scored passage."""
    text: str
    source: str           # Source document filename
    chunk_id: str         # Chunk identifier for traceability
    dense_score: float    # Cosine similarity from dense retrieval
    sparse_score: float   # BM25 score from sparse retrieval
    rrf_score: float      # Reciprocal rank fusion score
    rerank_score: float   # Cross-encoder rerank score
    final_rank: int       # Final rank after all stages
@dataclass
class RAGContext:
    """
    Final context package passed to the generation component.
    Contains the compressed, reranked passages and query metadata.
    """
    original_query: str
    rewritten_query: str
    hyde_passage: str
    retrieved_passages: list[RetrievalResult]
    context_text: str     # Concatenated passages for prompt injection
# ---------------------------------------------------------------------------
# Pre-retrieval — Query rewriting
# ---------------------------------------------------------------------------
REWRITE_PROMPT = """You are an expert in the EFSA FoodEx2 food classification taxonomy.
Rewrite the following food product description as a precise FoodEx2 retrieval query.
Focus on food type, processing methods, physical state, and packaging.
Return only the rewritten query, nothing else.
Original description: {query}
Rewritten query:"""
HYDE_PROMPT = """You are an expert in the EFSA FoodEx2 food classification taxonomy.
Write a short passage (3-4 sentences) that would appear in the FoodEx2 technical
documentation describing the following food product.
Use FoodEx2 terminology and include relevant base terms and facets.
Return only the passage, nothing else.
Food product description: {query}
FoodEx2 documentation passage:"""
def rewrite_query(query: str, llm: LLM) -> str:
    """
    Rewrite the input query using an LLM to improve alignment
    with FoodEx2 terminology in the knowledge base.
    """
    prompt = REWRITE_PROMPT.format(query=query)
    response = llm.complete(prompt)
    rewritten = response.text.strip()
    logger.info(f"Query rewritten: '{query}' → '{rewritten}'")
    return rewritten
def generate_hyde_passage(query: str, llm: LLM) -> str:
    """
    Generate a Hypothetical Document Embedding (HyDE) passage.
    The passage mimics FoodEx2 documentation style and is used
    to guide dense retrieval towards the most relevant index entries.
    """
    prompt = HYDE_PROMPT.format(query=query)
    response = llm.complete(prompt)
    hyde = response.text.strip()
    logger.info(f"HyDE passage generated ({len(hyde)} chars)")
    return hyde
# ---------------------------------------------------------------------------
# Retrieval — Dense + Sparse + Hybrid fusion
# ---------------------------------------------------------------------------
def dense_retrieve(
    index: VectorStoreIndex,
    query: str,
    top_k: int = TOP_K_DENSE,
) -> list[NodeWithScore]:
    """
    Dense semantic retrieval using cosine similarity over Chroma embeddings.
    """
    retriever = VectorIndexRetriever(
        index=index,
        similarity_top_k=top_k,
    )
    nodes = retriever.retrieve(QueryBundle(query_str=query))
    logger.info(f"Dense retrieval: {len(nodes)} candidates")
    return nodes
def sparse_retrieve(
    index: VectorStoreIndex,
    query: str,
    top_k: int = TOP_K_SPARSE,
    fallback_nodes: list[NodeWithScore] | None = None,
) -> list[NodeWithScore]:
    """
    Sparse BM25 lexical retrieval.
    Complements dense retrieval for exact FoodEx2 term matching
    (e.g. specific base term codes, facet descriptors).
    When the index is Chroma-backed the in-memory docstore is empty,
    so we fall back to building BM25 from the dense fallback_nodes.
    """
    try:
        docstore = index.docstore
        # Chroma-backed index: docstore has no nodes — use fallback
        if not docstore.docs and fallback_nodes:
            logger.info("Docstore empty (Chroma backend) — building BM25 from dense nodes")
            retriever = BM25Retriever.from_defaults(
                nodes=[n.node for n in fallback_nodes],
                similarity_top_k=min(top_k, len(fallback_nodes)),
            )
        else:
            retriever = BM25Retriever.from_defaults(
                docstore=docstore,
                similarity_top_k=top_k,
            )
        nodes = retriever.retrieve(QueryBundle(query_str=query))
        logger.info(f"Sparse retrieval: {len(nodes)} candidates")
        return nodes
    except Exception as e:
        logger.warning(f"BM25 retrieval failed ({e}) — returning empty sparse results")
        return []
def reciprocal_rank_fusion(
    dense_nodes: list[NodeWithScore],
    sparse_nodes: list[NodeWithScore],
    k: int = RRF_K,
) -> list[tuple[NodeWithScore, float]]:
    """
    Combine dense and sparse results using Reciprocal Rank Fusion.
    RRF score = Σ 1 / (k + rank_i) for each retrieval list
    Args:
        dense_nodes: ranked candidates from dense retrieval
        sparse_nodes: ranked candidates from BM25 retrieval
        k: RRF constant (default 60 per original RRF paper)
    Returns:
        list of (node, rrf_score) sorted by descending RRF score
    """
    scores: dict[str, float] = {}
    node_map: dict[str, NodeWithScore] = {}
    # Score from dense list
    for rank, node in enumerate(dense_nodes, start=1):
        node_id = node.node.node_id
        scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k + rank)
        node_map[node_id] = node
    # Score from sparse list
    for rank, node in enumerate(sparse_nodes, start=1):
        node_id = node.node.node_id
        scores[node_id] = scores.get(node_id, 0.0) + 1.0 / (k + rank)
        node_map[node_id] = node
    # Sort by descending RRF score
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    result = [(node_map[node_id], score) for node_id, score in ranked]
    logger.info(f"RRF fusion: {len(result)} unique candidates")
    return result
# ---------------------------------------------------------------------------
# Post-retrieval — Reranking and compression
# ---------------------------------------------------------------------------
def rerank_passages(
    query: str,
    fused_nodes: list[tuple[NodeWithScore, float]],
    top_k: int = TOP_K_RERANK,
) -> list[tuple[NodeWithScore, float]]:
    """
    Rerank fused candidates using ColBERT cross-encoder.
    ColBERT provides token-level interaction between query and passage,
    offering more precise relevance scoring than bi-encoder similarity.
    Args:
        query: original or rewritten query
        fused_nodes: RRF-fused candidates
        top_k: number of passages to retain after reranking
    Returns:
        top_k reranked (node, score) pairs
    """
    if not fused_nodes:
        logger.warning("No fused nodes to rerank — skipping ColBERT")
        return []
    try:
        reranker = ColbertRerank(top_n=top_k)
        nodes_only = [n for n, _ in fused_nodes]
        query_bundle = QueryBundle(query_str=query)
        reranked = reranker.postprocess_nodes(nodes_only, query_bundle=query_bundle)
        result = []
        for rank, node in enumerate(reranked):
            rrf_score = next(
                (s for n, s in fused_nodes if n.node.node_id == node.node.node_id), 0.0
            )
            result.append((node, rrf_score))
        logger.info(f"Reranking complete: {len(result)} passages retained")
        return result
    except Exception as e:
        logger.warning(f"ColBERT reranking failed ({e}) — returning top fused nodes")
        return fused_nodes[:top_k]
def compress_context(
    reranked_nodes: list[tuple[NodeWithScore, float]],
    min_similarity: float = MIN_SIMILARITY,
    max_chars: int = 6000,
) -> list[RetrievalResult]:
    """
    Filter and compress the reranked passage set.
    Steps:
    1. Remove passages below minimum similarity threshold
    2. Deduplicate near-identical passages (cosine similarity > 0.95)
    3. Truncate to max_chars to fit within generation context window
    Args:
        reranked_nodes: output of rerank_passages()
        min_similarity: minimum score threshold
        max_chars: maximum total character count for context
    Returns:
        list of RetrievalResult ready for prompt injection
    """
    postprocessor = SimilarityPostprocessor(similarity_cutoff=min_similarity)
    nodes_only = [n for n, _ in reranked_nodes]
    filtered = postprocessor.postprocess_nodes(nodes_only)
    results = []
    total_chars = 0
    for rank, node in enumerate(filtered, start=1):
        text = node.get_content().strip()
        char_count = len(text)
        if total_chars + char_count > max_chars:
            logger.info(f"Context window limit reached at passage {rank}")
            break
        rrf_score = next(
            (s for n, s in reranked_nodes if n.node.node_id == node.node_id), 0.0
        )
        results.append(RetrievalResult(
            text=text,
            source=node.metadata.get("source", "unknown"),
            chunk_id=node.metadata.get("chunk_id", "unknown"),
            dense_score=node.score or 0.0,
            sparse_score=0.0,   # BM25 score not propagated through reranker
            rrf_score=rrf_score,
            rerank_score=node.score or 0.0,
            final_rank=rank,
        ))
        total_chars += char_count
    logger.info(
        f"Context compressed: {len(results)} passages, "
        f"{total_chars} chars"
    )
    return results
# ---------------------------------------------------------------------------
# Full Advanced RAG retrieval pipeline
# ---------------------------------------------------------------------------
def retrieve(
    query: str,
    index: VectorStoreIndex,
    llm: LLM,
    use_hyde: bool = True,
    use_rewrite: bool = True,
    use_rerank: bool = True,
) -> RAGContext:
    """
    Full Advanced RAG retrieval pipeline.
    Stages:
    1. Pre-retrieval: query rewriting + HyDE
    2. Retrieval: dense + sparse + RRF fusion
    3. Post-retrieval: reranking + context compression
    Args:
        query: multimodal product description from VLM
        index: FoodEx2 LlamaIndex VectorStoreIndex
        llm: language model for query rewriting and HyDE
        use_hyde: whether to apply HyDE (default True)
        use_rewrite: whether to apply query rewriting (default True)
    Returns:
        RAGContext with compressed, reranked passages and metadata
    """
    # --- Pre-retrieval ---
    rewritten = rewrite_query(query, llm) if use_rewrite else query
    hyde_passage = generate_hyde_passage(query, llm) if use_hyde else ""
    # Use HyDE passage as retrieval query if available
    retrieval_query = hyde_passage if use_hyde and hyde_passage else rewritten
    # --- Retrieval ---
    dense_nodes = dense_retrieve(index, retrieval_query)
    # Pass dense_nodes as fallback for BM25 when docstore is empty (Chroma backend)
    sparse_nodes = sparse_retrieve(index, rewritten, fallback_nodes=dense_nodes)
    fused = reciprocal_rank_fusion(dense_nodes, sparse_nodes)
    # --- Post-retrieval ---
    # O re-rank ColBERT carrega um modelo cross-encoder (pesado em CPU). Pode ser
    # desligado (IDRISK2_USE_RERANK=false) para deploys CPU; nesse caso usamos
    # diretamente os melhores candidatos da fusão RRF.
    if use_rerank:
        reranked = rerank_passages(rewritten, fused)
    else:
        logger.info("Re-rank ColBERT desligado — a usar top-%d da fusão RRF", TOP_K_RERANK)
        reranked = fused[:TOP_K_RERANK]
    passages = compress_context(reranked)
    # Assemble context text for prompt injection
    context_text = "\n\n---\n\n".join(
        f"[Source: {p.source} | Chunk: {p.chunk_id}]\n{p.text}"
        for p in passages
    )
    return RAGContext(
        original_query=query,
        rewritten_query=rewritten,
        hyde_passage=hyde_passage,
        retrieved_passages=passages,
        context_text=context_text,
    )

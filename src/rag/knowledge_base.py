"""
IDRISK2 — Knowledge Base Construction (Section 4.5.1)
Builds and manages the FoodEx2 knowledge base for the RAG pipeline.
Handles:
- Loading EFSA FoodEx2 documents (PDF + text)
- Semantic chunking preserving hierarchical structure
- Embedding with sentence-transformers
- Indexing into Chroma vector store via LlamaIndex
- Knowledge base versioning and integrity verification
"""
import hashlib
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
from llama_index.core import (
    SimpleDirectoryReader,
    VectorStoreIndex,
    StorageContext,
    Settings,
)
from llama_index.core.node_parser import (
    SentenceSplitter,
    SemanticSplitterNodeParser,
)
from llama_index.core.schema import Document, TextNode
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.chroma import ChromaVectorStore
import chromadb
from .foodex2_xlsx_loader import load_foodex2_terms
logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Embedding model — multilingual, strong on technical regulatory text
EMBEDDING_MODEL = "BAAI/bge-m3"
# Chunking parameters
CHUNK_SIZE = 512          # tokens per chunk
CHUNK_OVERLAP = 64        # overlap to preserve context across boundaries
# Chroma collection name
COLLECTION_NAME = "foodex2_kb"
# Metadata keys
META_SOURCE = "source"
META_SECTION = "section"
META_VERSION = "foodex2_version"
META_CHUNK_ID = "chunk_id"
# Pattern used to auto-detect the FoodEx2 taxonomy XLSX in docs_dir.
# Matches files like 'efs39414e-sup-0002-appendix b.xlsx'.
TAXONOMY_FILE_GLOB = "*appendix*.xlsx"
# ---------------------------------------------------------------------------
# Document loading
# ---------------------------------------------------------------------------
def _detect_taxonomy_xlsx(docs_dir: str) -> Optional[Path]:
    """
    Look inside docs_dir for the FoodEx2 taxonomy XLSX export.
    Returns the path to the largest match (the Appendix B file is the
    main taxonomy and is typically much larger than auxiliary sheets),
    or None if no XLSX is found.
    """
    docs_path = Path(docs_dir)
    candidates = sorted(docs_path.rglob(TAXONOMY_FILE_GLOB))
    if not candidates:
        return None
    # Pick the largest file — the Appendix B taxonomy is the heavyweight.
    chosen = max(candidates, key=lambda p: p.stat().st_size)
    logger.info(f"Detected FoodEx2 taxonomy XLSX: {chosen.name}")
    return chosen
def _preflight_taxonomy(xlsx_path: Path) -> None:
    """
    Fail fast on missing dependencies or unreadable taxonomy file.
    Called BEFORE the expensive PDF chunking step so that a missing
    `openpyxl` or an unreadable XLSX surfaces in seconds, not after
    ~30 min of embedding computation.
    """
    try:
        import openpyxl  # noqa: F401
    except ImportError as e:
        raise ImportError(
            "openpyxl is required to ingest the FoodEx2 taxonomy XLSX. "
            "Install it with `pip install openpyxl` and re-run."
        ) from e
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Taxonomy XLSX not found: {xlsx_path}")
def _pdf_cache_key(documents: list[Document], strategy: str) -> str:
    """Stable cache key based on document source + size + chunking strategy."""
    parts = sorted(
        f"{doc.metadata.get(META_SOURCE, '')}:{len(doc.text)}"
        for doc in documents
    )
    parts.append(f"strategy={strategy}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]
def _chunk_pdfs_with_cache(
    documents: list[Document],
    embed_model,
    strategy: str,
    cache_dir: Path,
) -> list:
    """
    Run PDF chunking with a disk cache to avoid recomputing semantic
    splits across re-builds.
    The cache key incorporates source filenames, content sizes and the
    chunking strategy. Any change to the PDFs invalidates the cache
    automatically (different size → different key).
    """
    import pickle
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _pdf_cache_key(documents, strategy)
    cache_path = cache_dir / f"pdf_nodes_{key}.pkl"
    if cache_path.exists():
        try:
            with open(cache_path, "rb") as f:
                nodes = pickle.load(f)
            logger.info(
                f"PDF node cache HIT — loaded {len(nodes)} nodes from "
                f"{cache_path.name} (skipping semantic chunking)"
            )
            return nodes
        except Exception as e:
            logger.warning(f"PDF node cache read failed ({e}); re-chunking.")
    logger.info("PDF node cache MISS — running semantic chunking.")
    nodes = chunk_documents(documents, embed_model, strategy=strategy)
    try:
        with open(cache_path, "wb") as f:
            pickle.dump(nodes, f)
        logger.info(f"PDF nodes cached at {cache_path}")
    except Exception as e:
        logger.warning(f"PDF node cache write failed ({e}); continuing anyway.")
    return nodes
def load_efsa_documents(docs_dir: str) -> list[Document]:
    """
    Load EFSA FoodEx2 documents from a directory.
    Supports PDF and plain text files.
    Attaches source metadata to each document for traceability.
    Args:
        docs_dir: path to directory containing EFSA documents
    Returns:
        list of LlamaIndex Document objects
    """
    docs_path = Path(docs_dir)
    if not docs_path.exists():
        raise FileNotFoundError(f"Documents directory not found: {docs_dir}")
    supported = {".pdf", ".txt", ".md"}
    files = [f for f in docs_path.rglob("*") if f.suffix.lower() in supported]
    if not files:
        raise ValueError(f"No supported documents found in {docs_dir}")
    logger.info(f"Loading {len(files)} documents from {docs_dir}")
    reader = SimpleDirectoryReader(
        input_dir=str(docs_path),
        recursive=True,
        required_exts=list(supported),
    )
    documents = reader.load_data()
    # Attach source metadata for audit traceability
    for doc in documents:
        source_path = Path(doc.metadata.get("file_path", "unknown"))
        doc.metadata[META_SOURCE] = source_path.name
        doc.metadata[META_VERSION] = _detect_foodex2_version(doc.text)
        doc.metadata["loaded_at"] = datetime.utcnow().isoformat()
    logger.info(f"Loaded {len(documents)} document pages")
    return documents
def _detect_foodex2_version(text: str) -> str:
    """Attempt to detect FoodEx2 version from document text."""
    if "Revision 2" in text or "Rev 2" in text:
        return "FoodEx2-Rev2"
    if "Revision 1" in text or "Rev 1" in text:
        return "FoodEx2-Rev1"
    return "unknown"
# ---------------------------------------------------------------------------
# Semantic chunking
# ---------------------------------------------------------------------------
def chunk_documents(
    documents: list[Document],
    embed_model,
    strategy: str = "semantic",
) -> list:
    """
    Chunk documents into nodes for indexing.
    Two strategies:
    - "semantic": SemanticSplitterNodeParser — respects content boundaries.
      Preferred for FoodEx2 regulatory docs where term definitions must
      not be split across chunks.
    - "fixed": SentenceSplitter with fixed token size — faster but less precise.
    Args:
        documents: loaded EFSA documents
        embed_model: embedding model instance (used by semantic splitter)
        strategy: "semantic" | "fixed"
    Returns:
        list of LlamaIndex nodes
    """
    if strategy == "semantic":
        parser = SemanticSplitterNodeParser(
            embed_model=embed_model,
            buffer_size=1,
            breakpoint_percentile_threshold=95,
        )
        logger.info("Using semantic chunking strategy")
    else:
        parser = SentenceSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        logger.info(f"Using fixed chunking: {CHUNK_SIZE} tokens, {CHUNK_OVERLAP} overlap")
    nodes = parser.get_nodes_from_documents(documents, show_progress=True)
    # Attach chunk ID for traceability
    for i, node in enumerate(nodes):
        node.metadata[META_CHUNK_ID] = f"chunk_{i:05d}"
    logger.info(f"Generated {len(nodes)} chunks from {len(documents)} documents")
    return nodes
# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------
def load_embedding_model(model_name: str = EMBEDDING_MODEL) -> HuggingFaceEmbedding:
    """
    Load the embedding model.
    BAAI/bge-m3 is selected for:
    - Multilingual support (EN, PT, ES, FR)
    - Strong performance on technical domain text
    - Local inference — no external API dependency (GDPR compliant)
    """
    import os
    logger.info(f"Loading embedding model: {model_name}")
    # Resolve cache folder: prefer LLAMA_INDEX_CACHE_DIR env var, otherwise
    # use a local .cache dir relative to the project to avoid macOS permission issues.
    cache_folder = os.environ.get(
        "LLAMA_INDEX_CACHE_DIR",
        str(Path(__file__).resolve().parents[2] / ".cache" / "llama_index"),
    )
    Path(cache_folder).mkdir(parents=True, exist_ok=True)
    embed_model = HuggingFaceEmbedding(
        model_name=model_name,
        max_length=512,
        cache_folder=cache_folder,
    )
    Settings.embed_model = embed_model
    return embed_model
# ---------------------------------------------------------------------------
# Taxonomy term → node conversion
# ---------------------------------------------------------------------------
def _terms_to_nodes(term_documents: list[Document]) -> list[TextNode]:
    """
    Convert FoodEx2 term Documents into TextNodes WITHOUT further chunking.
    Each FoodEx2 term is an atomic unit of taxonomy: splitting a term's
    body across multiple chunks would scatter its description and facets
    in ways that hurt both retrieval (semantic locality) and audit
    traceability (each citation should map to exactly one term).
    The chunk_id is set to the term code (e.g. 'term_A03VY') so that
    audit records can be reconstructed deterministically from chunk IDs.
    """
    nodes: list[TextNode] = []
    for doc in term_documents:
        code = doc.metadata.get("termCode", "unknown")
        metadata = {
            **doc.metadata,
            META_CHUNK_ID: f"term_{code}",
            META_VERSION: "FoodEx2-Appendix-B",
        }
        nodes.append(TextNode(text=doc.text, metadata=metadata))
    logger.info(f"Converted {len(nodes)} FoodEx2 terms into atomic nodes")
    return nodes
# ---------------------------------------------------------------------------
# Vector store and index
# ---------------------------------------------------------------------------
def build_knowledge_base(
    docs_dir: str,
    persist_dir: str,
    chunking_strategy: str = "semantic",
    embedding_model: str = EMBEDDING_MODEL,
    force_rebuild: bool = False,
    include_taxonomy: bool = True,
    taxonomy_detail_levels: Optional[set[str]] = None,
) -> VectorStoreIndex:
    """
    Build and persist the FoodEx2 knowledge base.
    The knowledge base now combines TWO sources:
    1. The EFSA technical PDFs (system description and yearly
       maintenance documents) — chunked semantically into ~600 chunks.
    2. The FoodEx2 taxonomy itself (Appendix B XLSX, ~31k terms) —
       indexed as atomic nodes, one per term, NOT chunked. This is
       the source of truth that the LLM needs to find candidate base
       term codes during classification.
    If the knowledge base already exists and force_rebuild is False,
    loads the existing index. Otherwise builds from scratch.
    Args:
        docs_dir: directory containing EFSA PDFs and the Appendix B XLSX
        persist_dir: directory for Chroma persistence
        chunking_strategy: "semantic" | "fixed" (applies to PDFs only)
        embedding_model: HuggingFace model name for embeddings
        force_rebuild: if True, rebuilds even if index exists
        include_taxonomy: if True (default), auto-detects and indexes
            the Appendix B XLSX. Set False to index PDFs only.
        taxonomy_detail_levels: if provided, restricts taxonomy ingestion
            to terms with these detailLevel codes. Pass {"H", "C"} for
            the lighter ~8.8k subset; leave None for full coverage.
    Returns:
        LlamaIndex VectorStoreIndex
    """
    persist_path = Path(persist_dir)
    manifest_path = persist_path / "manifest.json"
    embed_model = load_embedding_model(embedding_model)
    # Check if existing index can be reused
    if persist_path.exists() and manifest_path.exists() and not force_rebuild:
        logger.info("Loading existing knowledge base from disk...")
        return _load_existing_index(persist_dir, embed_model)
    logger.info("Building knowledge base from scratch...")
    # --- 0. Fail-fast preflight on the taxonomy source ---
    # Validate openpyxl + file existence BEFORE the ~30 min PDF chunking
    # so missing dependencies surface immediately.
    xlsx_path: Optional[Path] = None
    if include_taxonomy:
        xlsx_path = _detect_taxonomy_xlsx(docs_dir)
        if xlsx_path is None:
            logger.warning(
                f"No taxonomy XLSX found in {docs_dir} (pattern: {TAXONOMY_FILE_GLOB}). "
                f"Knowledge base will contain PDF chunks only."
            )
        else:
            _preflight_taxonomy(xlsx_path)
            logger.info(f"Taxonomy preflight OK: {xlsx_path.name}")
    # --- 1. Load the EFSA PDFs (system documentation), with disk cache ---
    pdf_documents = load_efsa_documents(docs_dir)
    pdf_cache_dir = persist_path / "_cache"
    pdf_nodes = _chunk_pdfs_with_cache(
        pdf_documents, embed_model, chunking_strategy, pdf_cache_dir,
    )
    # --- 2. Load the FoodEx2 taxonomy XLSX (atomic term nodes) ---
    term_documents: list[Document] = []
    term_nodes: list[TextNode] = []
    if include_taxonomy and xlsx_path is not None:
        term_documents = load_foodex2_terms(
            str(xlsx_path),
            detail_levels=taxonomy_detail_levels,
        )
        term_nodes = _terms_to_nodes(term_documents)
    # --- 3. Combine and index ---
    all_documents = pdf_documents + term_documents
    all_nodes = pdf_nodes + term_nodes
    # Initialise Chroma
    chroma_client = chromadb.PersistentClient(path=str(persist_path / "chroma"))
    chroma_collection = chroma_client.get_or_create_collection(COLLECTION_NAME)
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    # Build index
    index = VectorStoreIndex(
        all_nodes,
        storage_context=storage_context,
        show_progress=True,
    )
    # Save manifest for version control and integrity verification
    _save_manifest(manifest_path, all_documents, all_nodes, embedding_model, chunking_strategy)
    logger.info(
        f"Knowledge base built: {len(all_nodes)} total chunks "
        f"({len(pdf_nodes)} PDF chunks + {len(term_nodes)} taxonomy terms)"
    )
    return index
def _load_existing_index(persist_dir: str, embed_model) -> VectorStoreIndex:
    """Load an existing Chroma-backed index from disk."""
    persist_path = Path(persist_dir)
    chroma_client = chromadb.PersistentClient(path=str(persist_path / "chroma"))
    chroma_collection = chroma_client.get_or_create_collection(COLLECTION_NAME)
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(
        vector_store,
        storage_context=storage_context,
    )
    logger.info("Existing knowledge base loaded successfully")
    return index
# ---------------------------------------------------------------------------
# Versioning and integrity verification
# ---------------------------------------------------------------------------
def _save_manifest(
    manifest_path: Path,
    documents: list[Document],
    nodes: list,
    embedding_model: str,
    chunking_strategy: str,
):
    """
    Save a manifest file recording knowledge base provenance.
    Used for version control and cryptographic integrity verification.
    """
    sources = list({doc.metadata.get(META_SOURCE, "unknown") for doc in documents})
    versions = list({doc.metadata.get(META_VERSION, "unknown") for doc in documents})
    manifest = {
        "created_at": datetime.utcnow().isoformat(),
        "embedding_model": embedding_model,
        "chunking_strategy": chunking_strategy,
        "total_documents": len(documents),
        "total_chunks": len(nodes),
        "source_files": sorted(sources),
        "foodex2_versions": versions,
        "checksum": _compute_checksum(nodes),
    }
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info(f"Manifest saved: {manifest_path}")
def _compute_checksum(nodes: list) -> str:
    """
    Compute a SHA-256 checksum over all chunk texts.
    Enables detection of unauthorised modifications to the knowledge base.
    """
    content = "".join(node.get_content() for node in nodes).encode()
    return hashlib.sha256(content).hexdigest()
def verify_integrity(persist_dir: str, nodes: Optional[list] = None) -> bool:
    """
    Verify the integrity of the knowledge base against the stored manifest.
    Args:
        persist_dir: directory containing the Chroma index and manifest
        nodes: if provided, recomputes checksum and compares
    Returns:
        True if integrity check passes, False otherwise
    """
    manifest_path = Path(persist_dir) / "manifest.json"
    if not manifest_path.exists():
        logger.error("Manifest not found — integrity cannot be verified")
        return False
    with open(manifest_path) as f:
        manifest = json.load(f)
    if nodes is not None:
        current_checksum = _compute_checksum(nodes)
        if current_checksum != manifest["checksum"]:
            logger.error(
                f"Integrity check FAILED — checksum mismatch.\n"
                f"Expected: {manifest['checksum']}\n"
                f"Got:      {current_checksum}"
            )
            return False
    logger.info(
        f"Integrity check passed — {manifest['total_chunks']} chunks, "
        f"created {manifest['created_at']}"
    )
    return True

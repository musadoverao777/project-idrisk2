"""
IDRISK2 — Generation Component (Section 4.5.3)
Produces structured FoodEx2 classification outputs grounded in
retrieved EFSA documentation.
Handles:
- Prompt assembly with retrieved context
- FoodEx2-structured generation via VLM
- Output validation against FoodEx2 schema
- Confidence thresholding and human review flagging
- Audit trail generation
"""
import json
import logging
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from llama_index.core.llms import LLM, ChatMessage, MessageRole
from src.common.types import Confidence, REVIEW_TRIGGER_LEVELS
from .retrieval import RAGContext
logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Maximum retries if output fails schema validation
MAX_RETRIES = 2
# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------
@dataclass
class FoodEx2Classification:
    """
    Final structured FoodEx2 classification output.
    Includes the classification result, retrieval provenance,
    and audit metadata.
    """
    # Classification result
    base_term_code: str
    base_term_label: str
    facets: dict[str, str]
    reasoning: str
    confidence: str                    # "high" | "medium" | "low"
    # Retrieval provenance — traceable references to EFSA documentation
    retrieved_sources: list[str]       # Source documents used
    retrieved_chunk_ids: list[str]     # Chunk IDs for full traceability
    # Pipeline metadata
    classification_id: str             # Unique ID for this classification
    timestamp: str
    model_used: str
    requires_human_review: bool
    # Raw outputs for audit
    raw_generation: str
    rag_context_summary: str           # Summary of context provided to generator
# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------
GENERATION_SYSTEM_PROMPT = """You are an expert food classification assistant
specialised in the EFSA FoodEx2 taxonomy. Your task is to assign the correct
FoodEx2 classification to a food product based on:
1. A description of the product (from visual analysis and OCR)
2. Relevant passages retrieved from the official EFSA FoodEx2 documentation

IMPORTANT RULES:
- Prefer information from the retrieved documentation; supplement with general
  FoodEx2 knowledge when documentation is insufficient
- Always assign the most specific applicable base term
- Include ALL relevant facets from the FoodEx2 facet categories:
  F01 (animal species), F04 (physical state), F27 (heat treatment),
  F28 (processing method), F29 (packaging), F30 (consumer format), etc.
- Do NOT use "XXXXX" as base_term_code — it is a schema placeholder only
- Use "UNKNOWN" only if the food cannot be identified at all
- Cite which retrieved passage supports each decision in the reasoning
- Return ONLY a valid JSON object — no prose outside the JSON

Output schema (example values shown — replace with real codes):
{
    "base_term_code": "A0CKL",
    "base_term_label": "Prepared dish name",
    "facets": {
        "F28": "A07XG",
        "F04": "A037V"
    },
    "reasoning": "Step-by-step explanation citing specific retrieved passages",
    "confidence": "high"
}"""
def assemble_generation_prompt(
    product_description: str,
    rag_context: RAGContext,
) -> str:
    """
    Assemble the final generation prompt combining:
    - Retrieved FoodEx2 documentation passages
    - VLM-generated product description
    - Classification instructions
    Args:
        product_description: multimodal product description from VLM
        rag_context: output of the retrieval pipeline
    Returns:
        Complete prompt string for the generation LLM
    """
    passage_block = rag_context.context_text
    prompt = f"""RETRIEVED EFSA FOODEX2 DOCUMENTATION:
{passage_block}
---
FOOD PRODUCT INFORMATION:
{product_description}
---
Based exclusively on the retrieved documentation above, provide the FoodEx2
classification for this food product. Reference specific passages in your reasoning.
Return a valid JSON object matching the required schema."""
    return prompt
# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
def generate_classification(
    product_description: str,
    rag_context: RAGContext,
    llm: LLM,
    model_name: str = "unknown",
    retry_count: int = 0,
    review_trigger_levels: set[str] = REVIEW_TRIGGER_LEVELS,
) -> FoodEx2Classification:
    """
    Generate a structured FoodEx2 classification grounded in retrieved context.
    Args:
        product_description: multimodal product description from VLM
        rag_context: output of the retrieval pipeline
        llm: language model for generation
        model_name: name of the model used (for audit)
        retry_count: current retry attempt (internal use)
        review_trigger_levels: confidence values that flag a classification
            for human review. Defaults to {"low", "medium"} (EU AI Act-aligned
            human oversight for high-risk systems). Pass a custom set to relax
            or tighten the policy.
    Returns:
        FoodEx2Classification with result, provenance, and audit metadata
    """
    prompt = assemble_generation_prompt(product_description, rag_context)
    # Generate — use chat() to inject the system prompt properly.
    # llm.complete() does not accept a system_prompt argument in LlamaIndex.
    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content=GENERATION_SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=prompt),
    ]
    response = llm.chat(messages)
    raw = response.message.content.strip()
    # Parse and validate
    parsed = _parse_and_validate(raw, llm, prompt, retry_count)
    # Determine if human review is required.
    # Triggered when confidence is in the configured trigger set (default:
    # any non-high) OR when the base term could not be assigned at all.
    requires_review = (
        parsed.get("confidence", Confidence.LOW.value) in review_trigger_levels
        or parsed.get("base_term_code") == "UNKNOWN"
    )
    if requires_review:
        logger.warning(
            f"Classification flagged for human review — "
            f"confidence: {parsed.get('confidence')} | "
            f"code: {parsed.get('base_term_code')}"
        )
    # Extract retrieval provenance
    sources = list({p.source for p in rag_context.retrieved_passages})
    chunk_ids = [p.chunk_id for p in rag_context.retrieved_passages]
    # Context summary for audit — records the full retrieval provenance
    # (rewritten query, HyDE usage, top-k rerank scores) for explainability.
    top_scores = [
        f"{p.chunk_id}:{p.rerank_score:.3f}"
        for p in rag_context.retrieved_passages[:5]
    ]
    context_summary = (
        f"{len(rag_context.retrieved_passages)} passages retrieved from "
        f"{len(sources)} source(s). "
        f"Rewritten query: '{rag_context.rewritten_query}'. "
        f"HyDE used: {bool(rag_context.hyde_passage)}. "
        f"Top rerank scores: [{', '.join(top_scores)}]."
    )
    return FoodEx2Classification(
        base_term_code=parsed.get("base_term_code", "UNKNOWN"),
        base_term_label=parsed.get("base_term_label", ""),
        facets=parsed.get("facets", {}),
        reasoning=parsed.get("reasoning", ""),
        confidence=parsed.get("confidence", "low"),
        retrieved_sources=sources,
        retrieved_chunk_ids=chunk_ids,
        classification_id=str(uuid.uuid4()),
        timestamp=datetime.utcnow().isoformat(),
        model_used=model_name,
        requires_human_review=requires_review,
        raw_generation=raw,
        rag_context_summary=context_summary,
    )
def _parse_and_validate(
    raw: str,
    llm: LLM,
    original_prompt: str,
    retry_count: int,
) -> dict:
    """
    Parse the raw LLM output and validate against the FoodEx2 schema.
    Retries up to MAX_RETRIES times with a corrective prompt if parsing fails.
    """
    import re

    clean = raw.strip()

    # 1. Strip ```json ... ``` or ``` ... ``` fences
    fence = re.search(r"```(?:json)?\s*([\s\S]+?)```", clean)
    if fence:
        clean = fence.group(1).strip()
    else:
        # 2. Extract the first {...} JSON object anywhere in the response
        brace = re.search(r"\{[\s\S]*\}", clean)
        if brace:
            clean = brace.group(0)

    # 3. Remove inline // comments (common LLM mistake in JSON)
    clean = re.sub(r"//[^\n]*", "", clean)

    # 4. Remove trailing commas before } or ]
    clean = re.sub(r",\s*([}\]])", r"\1", clean)

    try:
        parsed = json.loads(clean)
        # Reject schema placeholder used literally
        if parsed.get("base_term_code") == "XXXXX":
            parsed["base_term_code"] = "UNKNOWN"
        _validate_schema(parsed)
        return parsed
    except (json.JSONDecodeError, ValueError) as e:
        if retry_count >= MAX_RETRIES:
            logger.error(f"Schema validation failed after {MAX_RETRIES} retries: {e}")
            return {
                "base_term_code": "UNKNOWN",
                "base_term_label": "Validation error",
                "facets": {},
                "reasoning": f"Failed to parse model output: {raw}",
                "confidence": Confidence.LOW.value,
            }
        logger.warning(f"Parse error (attempt {retry_count + 1}): {e}. Retrying...")
        correction_prompt = (
            f"{original_prompt}\n\n"
            f"Your previous response could not be parsed as valid JSON.\n"
            f"Error: {e}\n"
            f"Please return ONLY a valid JSON object with no additional text."
        )
        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content=GENERATION_SYSTEM_PROMPT),
            ChatMessage(role=MessageRole.USER, content=correction_prompt),
        ]
        corrected = llm.chat(messages)
        return _parse_and_validate(
            corrected.message.content, llm, original_prompt, retry_count + 1
        )
def _validate_schema(parsed: dict):
    """
    Validate that the parsed output contains all required FoodEx2 fields.
    Raises ValueError if validation fails.
    """
    required = {
        "base_term_code": str,
        "base_term_label": str,
        "facets": dict,
        "reasoning": str,
        "confidence": str,
    }
    for field_name, expected_type in required.items():
        if field_name not in parsed:
            raise ValueError(f"Missing required field: '{field_name}'")
        if not isinstance(parsed[field_name], expected_type):
            raise ValueError(
                f"Field '{field_name}' must be {expected_type.__name__}, "
                f"got {type(parsed[field_name]).__name__}"
            )
    if not Confidence.is_valid(parsed["confidence"]):
        raise ValueError(
            f"Invalid confidence value '{parsed['confidence']}'. "
            f"Must be one of: {Confidence.values()}"
        )
# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
def save_audit_record(
    classification: FoodEx2Classification,
    audit_dir: str,
):
    """
    Persist a full audit record for a classification decision.
    The audit record includes:
    - Final classification result
    - Retrieved source documents and chunk IDs
    - Model used and timestamp
    - Raw generation output
    - Human review flag
    This supports the explainability and auditability requirements
    of Article 22 GDPR and the EU AI Act for high-risk AI systems.
    Args:
        classification: FoodEx2Classification output
        audit_dir: directory for audit record storage
    """
    audit_path = Path(audit_dir)
    audit_path.mkdir(parents=True, exist_ok=True)
    record_path = audit_path / f"{classification.classification_id}.json"
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(asdict(classification), f, indent=2, ensure_ascii=False)
    logger.info(f"Audit record saved: {record_path}")
# ---------------------------------------------------------------------------
# Full pipeline entry point
# ---------------------------------------------------------------------------
def classify_product(
    product_description: str,
    rag_context: RAGContext,
    llm: LLM,
    model_name: str = "unknown",
    audit_dir: Optional[str] = None,
    review_trigger_levels: set[str] = REVIEW_TRIGGER_LEVELS,
) -> FoodEx2Classification:
    """
    End-to-end classification: generation + validation + audit logging.
    Args:
        product_description: multimodal product description from VLM
        rag_context: output of the retrieval pipeline
        llm: language model for generation
        model_name: name of the model (for audit)
        audit_dir: if provided, saves audit record to this directory
        review_trigger_levels: confidence values that flag the output for
            human review (default: {"low", "medium"} — see generation.py)
    Returns:
        FoodEx2Classification — the final structured output
    """
    classification = generate_classification(
        product_description=product_description,
        rag_context=rag_context,
        llm=llm,
        model_name=model_name,
        review_trigger_levels=review_trigger_levels,
    )
    if audit_dir:
        save_audit_record(classification, audit_dir)
    return classification

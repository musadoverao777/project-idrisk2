"""Convert pipeline dataclasses to JSON-serialisable dicts."""
from pipeline import PipelineResult

from .schemas import ClassificationResponse


def pipeline_result_to_response(result: PipelineResult) -> ClassificationResponse:
    """Map a PipelineResult to the MVP API response schema."""
    c = result.classification
    return ClassificationResponse(
        base_term_code=c.base_term_code,
        base_term_label=c.base_term_label,
        facets=c.facets,
        reasoning=c.reasoning,
        confidence=c.confidence,
        requires_human_review=c.requires_human_review,
        classification_id=c.classification_id,
        timestamp=c.timestamp,
        total_time_ms=result.total_time_ms,
        ocr_text=result.ocr_text,
        retrieved_sources=c.retrieved_sources,
    )

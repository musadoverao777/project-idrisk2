"""Convert pipeline dataclasses to JSON-serialisable dicts."""
import logging

from pipeline import PipelineResult

from . import foodex2_labels
from .schemas import ClassificationResponse, FacetReadable

logger = logging.getLogger(__name__)


def pipeline_result_to_response(result: PipelineResult) -> ClassificationResponse:
    """Map a PipelineResult to the MVP API response schema."""
    c = result.classification
    try:
        facets_readable = [FacetReadable(**f) for f in foodex2_labels.resolve_facets(c.facets)]
    except Exception:  # noqa: BLE001
        logger.warning("Falha ao resolver rótulos das facetas", exc_info=True)
        facets_readable = []
    return ClassificationResponse(
        base_term_code=c.base_term_code,
        base_term_label=c.base_term_label,
        facets=c.facets,
        facets_readable=facets_readable,
        reasoning=c.reasoning,
        confidence=c.confidence,
        requires_human_review=c.requires_human_review,
        classification_id=c.classification_id,
        timestamp=c.timestamp,
        total_time_ms=result.total_time_ms,
        ocr_text=result.ocr_text,
        retrieved_sources=c.retrieved_sources,
    )

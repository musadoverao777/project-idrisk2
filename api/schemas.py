"""Pydantic response models for the IDRISK2 REST API."""
from pydantic import BaseModel, Field


class ClassificationResponse(BaseModel):
    """MVP classification result returned to the frontend."""

    base_term_code: str
    base_term_label: str
    facets: dict[str, str]
    reasoning: str
    confidence: str = Field(description="high | medium | low")
    requires_human_review: bool
    classification_id: str
    timestamp: str
    total_time_ms: float
    ocr_text: str
    retrieved_sources: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    pipeline_ready: bool
    message: str = ""

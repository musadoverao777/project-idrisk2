"""Pydantic response models for the IDRISK2 REST API."""
from pydantic import BaseModel, Field


class FacetReadable(BaseModel):
    """Uma faceta FoodEx2 com rótulos legíveis."""

    group: str            # ex.: F04
    group_label: str      # ex.: Ingredient
    code: str             # ex.: A0F4B
    label: str | None = None  # ex.: Flagfish (as animal)


class ClassificationResponse(BaseModel):
    """MVP classification result returned to the frontend."""

    base_term_code: str
    base_term_label: str
    facets: dict[str, str]
    facets_readable: list[FacetReadable] = Field(default_factory=list)
    reasoning: str
    confidence: str = Field(description="high | medium | low")
    requires_human_review: bool
    classification_id: str
    timestamp: str
    total_time_ms: float
    ocr_text: str
    retrieved_sources: list[str] = Field(default_factory=list)


class HistoryItem(BaseModel):
    """Um registo de classificação no histórico (lido da base de dados)."""

    id: str
    timestamp: str
    base_term_code: str
    base_term_label: str
    facets: dict[str, str] = Field(default_factory=dict)
    confidence: str
    requires_human_review: bool
    review_status: str
    ocr_text: str = ""
    image_hash: str | None = None
    submitted_by: str | None = None
    total_time_ms: float | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    pipeline_ready: bool
    message: str = ""


# --- Revisão humana ---------------------------------------------------------
class ReviewItem(BaseModel):
    classification_id: str
    status: str
    created_at: str | None = None
    reviewer_id: str | None = None
    corrected_code: str | None = None
    notes: str | None = None
    reviewed_at: str | None = None
    submitted_by: str | None = None
    timestamp: str
    base_term_code: str
    base_term_label: str
    confidence: str
    ocr_text: str = ""


class ReviewDecision(BaseModel):
    status: str = Field(description="approved | rejected | pending")
    corrected_code: str | None = None
    notes: str | None = None
    reviewer_id: str | None = None


# --- Utilizadores -----------------------------------------------------------
class UserItem(BaseModel):
    id: str
    username: str
    email: str | None = None
    role: str
    status: str
    created_at: str | None = None


class UserCreate(BaseModel):
    username: str
    email: str
    role: str


class UserStatusUpdate(BaseModel):
    status: str = Field(description="active | inactive")


# --- Auditoria --------------------------------------------------------------
class AuditItem(BaseModel):
    entry_id: str
    timestamp: str
    event_type: str | None = None
    user_id: str | None = None
    details: dict = Field(default_factory=dict)
    previous_hmac: str | None = None
    hmac: str | None = None


# --- Estatísticas do dashboard ---------------------------------------------
class WeeklyPoint(BaseModel):
    day: str
    date: str
    classifications: int


class DashboardStats(BaseModel):
    confidence: dict[str, int]
    weekly: list[WeeklyPoint]
    total: int
    pending_reviews: int

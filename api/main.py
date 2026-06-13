"""
IDRISK2 — FastAPI REST layer (MVP)
Exposes the classification pipeline over HTTP for the React frontend.
"""
import logging
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# Ensure project root is on sys.path when running via uvicorn
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

from pipeline import IDRISK2Pipeline
from src.security.security import Role, User

from . import db, foodex2_labels
from .schemas import (
    AuditItem,
    ClassificationResponse,
    DashboardStats,
    HealthResponse,
    HistoryItem,
    ReviewDecision,
    ReviewItem,
    UserCreate,
    UserItem,
    UserStatusUpdate,
)
from .serializers import pipeline_result_to_response

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

# Default MVP user — no login screen in this phase
DEFAULT_USER = User(
    user_id="web-inspector",
    username="web_inspector",
    role=Role.INSPECTOR,
    created_at=datetime.now(timezone.utc).isoformat(),
)

_pipeline: IDRISK2Pipeline | None = None
_pipeline_error: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the heavy pipeline once at startup."""
    global _pipeline, _pipeline_error
    # Base de dados do histórico (independente do pipeline pesado).
    try:
        counts = db.bootstrap()
        logger.info("Base de dados pronta. Importações/seed: %s", counts)
    except Exception as exc:
        logger.exception("Falha ao inicializar a base de dados: %s", exc)
    try:
        logger.info("Loading IDRISK2 pipeline...")
        _pipeline = IDRISK2Pipeline.from_env()
        _pipeline_error = None
        logger.info("IDRISK2 pipeline ready.")
        # Pré-carregar rótulos FoodEx2 em segundo plano (não bloqueia o arranque)
        import threading

        threading.Thread(target=foodex2_labels.ensure_loaded, daemon=True).start()
    except Exception as exc:
        _pipeline = None
        _pipeline_error = str(exc)
        logger.exception("Failed to initialise pipeline: %s", exc)
    yield
    _pipeline = None


app = FastAPI(
    title="IDRISK2 API",
    description="FoodEx2 classification API for the IDRISK2 frontend MVP",
    version="0.1.0",
    lifespan=lifespan,
)

# Origens permitidas (CORS). Por defeito apenas o dev local; para expor a um
# frontend remoto (Vercel/túnel) define IDRISK2_CORS_ORIGINS, p.ex.:
#   IDRISK2_CORS_ORIGINS="https://idrisk2.vercel.app,https://*.trycloudflare.com"
#   IDRISK2_CORS_ORIGINS="*"   (permite qualquer origem — útil para demo)
_cors_env = os.environ.get("IDRISK2_CORS_ORIGINS", "").strip()
if _cors_env == "*":
    _cors_kwargs = dict(allow_origins=["*"], allow_credentials=False)
elif _cors_env:
    _cors_kwargs = dict(
        allow_origins=[o.strip() for o in _cors_env.split(",") if o.strip()],
        allow_credentials=True,
    )
else:
    _cors_kwargs = dict(
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
    )

app.add_middleware(
    CORSMiddleware,
    allow_methods=["*"],
    allow_headers=["*"],
    **_cors_kwargs,
)


def _require_pipeline() -> IDRISK2Pipeline:
    if _pipeline is None:
        detail = _pipeline_error or "Pipeline not initialised"
        raise HTTPException(status_code=503, detail=detail)
    return _pipeline


def _validate_upload(filename: str | None, content: bytes) -> str:
    if not filename:
        raise HTTPException(status_code=400, detail="Nome de ficheiro em falta")

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato não suportado. Use: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Ficheiro vazio")

    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="Ficheiro demasiado grande (máx. 20 MB)")

    return ext


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Check API and pipeline readiness."""
    if _pipeline is not None:
        return HealthResponse(
            status="ok",
            pipeline_ready=True,
            message="Pipeline pronto para classificação",
        )
    return HealthResponse(
        status="degraded",
        pipeline_ready=False,
        message=_pipeline_error or "Pipeline ainda não inicializado",
    )


@app.post("/api/classify", response_model=ClassificationResponse)
async def classify(file: UploadFile = File(...)) -> ClassificationResponse:
    """Classify a food label or dish image using the IDRISK2 pipeline."""
    pipeline = _require_pipeline()

    content = await file.read()
    ext = _validate_upload(file.filename, content)

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        result = pipeline.classify(
            image_path=tmp_path,
            user=DEFAULT_USER,
            retain_image=False,
        )
        response = pipeline_result_to_response(result)
        # Persistir na base de dados para o histórico.
        try:
            db.insert_classification(
                id=response.classification_id,
                timestamp=response.timestamp,
                base_term_code=response.base_term_code,
                base_term_label=response.base_term_label,
                facets=response.facets,
                confidence=response.confidence,
                requires_human_review=response.requires_human_review,
                ocr_text=response.ocr_text,
                submitted_by=DEFAULT_USER.username,
                total_time_ms=response.total_time_ms,
            )
        except Exception:
            logger.exception("Falha ao gravar a classificação na base de dados")
        return response
    except HTTPException:
        raise
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Classification failed")
        raise HTTPException(status_code=500, detail=f"Erro na classificação: {exc}") from exc
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@app.get("/api/history", response_model=list[HistoryItem])
async def history(limit: int = 500) -> list[HistoryItem]:
    """Devolve o histórico de classificações (mais recente primeiro)."""
    try:
        rows = db.list_classifications(limit=limit)
    except Exception as exc:
        logger.exception("Falha ao ler o histórico")
        raise HTTPException(status_code=500, detail=f"Erro ao ler histórico: {exc}") from exc
    return [HistoryItem(**row) for row in rows]


# --- Fila de revisão --------------------------------------------------------
@app.get("/api/reviews", response_model=list[ReviewItem])
async def reviews(status: str | None = "pending", limit: int = 500) -> list[ReviewItem]:
    """Lista a fila de revisão (por defeito, as pendentes)."""
    try:
        rows = db.list_reviews(status=status, limit=limit)
    except Exception as exc:
        logger.exception("Falha ao ler a fila de revisão")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return [ReviewItem(**row) for row in rows]


@app.post("/api/reviews/{classification_id}/decision", response_model=ReviewItem)
async def decide_review(classification_id: str, decision: ReviewDecision) -> ReviewItem:
    """Aprova/rejeita uma classificação sinalizada."""
    if decision.status not in {"approved", "rejected", "pending"}:
        raise HTTPException(status_code=400, detail="status inválido")
    try:
        ok = db.decide_review(
            classification_id,
            status=decision.status,
            reviewer_id=decision.reviewer_id,
            corrected_code=decision.corrected_code,
            notes=decision.notes,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Revisão não encontrada")
        rows = db.list_reviews(status=None)
        match = next((r for r in rows if r["classification_id"] == classification_id), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Revisão não encontrada")
        return ReviewItem(**match)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Falha ao decidir revisão")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# --- Utilizadores -----------------------------------------------------------
@app.get("/api/users", response_model=list[UserItem])
async def users(_limit: int = 500) -> list[UserItem]:
    try:
        return [UserItem(**u) for u in db.list_users()]
    except Exception as exc:
        logger.exception("Falha ao listar utilizadores")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/users", response_model=UserItem, status_code=201)
async def create_user(payload: UserCreate) -> UserItem:
    try:
        return UserItem(**db.create_user(payload.username, payload.email, payload.role))
    except Exception as exc:
        logger.exception("Falha ao criar utilizador")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/users/{user_id}/status", response_model=dict)
async def update_user_status(user_id: str, payload: UserStatusUpdate) -> dict:
    if payload.status not in {"active", "inactive"}:
        raise HTTPException(status_code=400, detail="status inválido")
    ok = db.set_user_status(user_id, payload.status)
    if not ok:
        raise HTTPException(status_code=404, detail="Utilizador não encontrado")
    return {"id": user_id, "status": payload.status}


# --- Auditoria --------------------------------------------------------------
@app.get("/api/audit", response_model=list[AuditItem])
async def audit(limit: int = 500) -> list[AuditItem]:
    try:
        return [AuditItem(**a) for a in db.list_audit(limit=limit)]
    except Exception as exc:
        logger.exception("Falha ao ler auditoria")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# --- Estatísticas -----------------------------------------------------------
@app.get("/api/stats", response_model=DashboardStats)
async def stats() -> DashboardStats:
    try:
        return DashboardStats(**db.dashboard_stats())
    except Exception as exc:
        logger.exception("Falha ao calcular estatísticas")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

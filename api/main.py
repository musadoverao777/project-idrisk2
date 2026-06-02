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

from .schemas import ClassificationResponse, HealthResponse
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
    try:
        logger.info("Loading IDRISK2 pipeline...")
        _pipeline = IDRISK2Pipeline.from_env()
        _pipeline_error = None
        logger.info("IDRISK2 pipeline ready.")
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
        return pipeline_result_to_response(result)
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

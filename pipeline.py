"""
IDRISK2 — Main Pipeline (End-to-End Integration)
Orchestrates the full classification pipeline:
    Image input
        → Preprocessing (4.2)
        → OCR (4.3)
        → VLM multimodal analysis (4.4)
        → Advanced RAG retrieval (4.5.2)
        → FoodEx2 generation (4.5.3)
        → Audit logging + data minimisation (4.6)
        → FoodEx2Classification output
Usage:
    from pipeline import IDRISK2Pipeline
    pipeline = IDRISK2Pipeline.from_env()
    result = pipeline.classify(
        image_path="label.jpg",
        user=current_user,
    )
"""
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from llama_index.core import VectorStoreIndex
from llama_index.llms.openai import OpenAI
from src.data.preprocessing import load_image, preprocess_image
from src.ocr.engine import get_engine, compare_engines, OCRBenchmark
from src.vlm.vlm import get_vlm, VLMOutput
from src.rag.knowledge_base import build_knowledge_base, verify_integrity
from src.rag.retrieval import retrieve, RAGContext
from src.rag.generation import classify_product, FoodEx2Classification
from src.security.security import (
    User,
    AuditLogger,
    require_permission,
    minimise_record,
    save_minimised_record,
    validate_image_input,
    sanitise_ocr_text,
    load_config,
)
logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Pipeline configuration
# ---------------------------------------------------------------------------
@dataclass
class PipelineConfig:
    """
    Full configuration for the IDRISK2 pipeline.
    All paths and model choices are set here.
    The audit directory is split in two so that tamper-evident chained
    entries (written by AuditLogger) do not get mixed with per-decision
    generation records (written by classify_product) — otherwise the
    chain verification would fail on the unrelated files.
    """
    # Directories
    docs_dir: str                # EFSA FoodEx2 documents
    kb_persist_dir: str          # Chroma knowledge base persistence
    audit_chain_dir: str         # Tamper-evident HMAC-chained audit entries
    audit_generation_dir: str    # Per-classification provenance records
    records_dir: str             # Minimised product records
    # Model selection
    ocr_engine: str = "paddleocr"     # "tesseract" | "easyocr" | "paddleocr"
    vlm_model: str = "gpt4o"          # "gpt4o" | "llava" | "qwen"
    llm_model: str = "gpt-4o"         # LLM for RAG generation + query rewriting
    # RAG settings
    chunking_strategy: str = "semantic"
    use_hyde: bool = True
    use_query_rewrite: bool = True
    use_rerank: bool = True
    @classmethod
    def from_env(cls) -> "PipelineConfig":
        """Load configuration from environment variables."""
        import os

        def _flag(name: str, default: bool = True) -> bool:
            return os.environ.get(name, str(default)).strip().lower() not in ("false", "0", "no")

        config = load_config()
        data_dir = Path(config["IDRISK2_DATA_DIR"])
        return cls(
            docs_dir=config["IDRISK2_DOCS_DIR"],
            kb_persist_dir=str(data_dir / "kb"),
            audit_chain_dir=str(data_dir / "audit" / "chain"),
            audit_generation_dir=str(data_dir / "audit" / "generation"),
            records_dir=str(data_dir / "records"),
            ocr_engine=os.environ.get("IDRISK2_OCR_ENGINE", "paddleocr"),
            vlm_model=os.environ.get("IDRISK2_VLM_MODEL", "gpt4o"),
            llm_model=os.environ.get("IDRISK2_LLM_MODEL", "gpt-4o"),
            # Etapas pesadas do RAG — desligáveis por env para deploys CPU (ex.: cloud).
            # Mantêm-se ligadas por defeito (pipeline completo da dissertação).
            use_hyde=_flag("IDRISK2_USE_HYDE", True),
            use_query_rewrite=_flag("IDRISK2_USE_QUERY_REWRITE", True),
            use_rerank=_flag("IDRISK2_USE_RERANK", True),
        )
# ---------------------------------------------------------------------------
# Pipeline output
# ---------------------------------------------------------------------------
@dataclass
class PipelineResult:
    """
    Full output of a single IDRISK2 classification run.
    Contains the final classification, intermediate outputs,
    and pipeline metadata for transparency and debugging.
    """
    # Final output
    classification: FoodEx2Classification
    # Intermediate outputs (for transparency and evaluation)
    ocr_text: str
    vlm_output: VLMOutput
    rag_context: RAGContext
    # Pipeline metadata
    image_path: str
    ocr_engine_used: str
    vlm_model_used: str
    total_time_ms: float
# ---------------------------------------------------------------------------
# Main pipeline class
# ---------------------------------------------------------------------------
class IDRISK2Pipeline:
    """
    End-to-end IDRISK2 classification pipeline.
    Instantiate once and reuse across multiple classification requests.
    All models and indices are loaded at initialisation time.
    """
    def __init__(self, config: PipelineConfig):
        self.config = config
        self._initialise()
    def _initialise(self):
        """Load all models and indices at startup."""
        logger.info("Initialising IDRISK2 pipeline...")
        # Security — chain-verified audit log (separate dir from generation records)
        self.audit_logger = AuditLogger(self.config.audit_chain_dir)
        # OCR engine
        logger.info(f"Loading OCR engine: {self.config.ocr_engine}")
        self.ocr_engine = get_engine(self.config.ocr_engine)
        # VLM
        logger.info(f"Loading VLM: {self.config.vlm_model}")
        self.vlm = get_vlm(self.config.vlm_model)
        # LLM for RAG generation and query rewriting
        logger.info(f"Loading LLM: {self.config.llm_model}")
        self.llm = OpenAI(model=self.config.llm_model, temperature=0.1)
        # Knowledge base
        logger.info("Loading FoodEx2 knowledge base...")
        self.index: VectorStoreIndex = build_knowledge_base(
            docs_dir=self.config.docs_dir,
            persist_dir=self.config.kb_persist_dir,
            chunking_strategy=self.config.chunking_strategy,
        )
        # Verify knowledge base integrity
        if not verify_integrity(self.config.kb_persist_dir):
            raise RuntimeError(
                "Knowledge base integrity check failed. "
                "The FoodEx2 index may have been tampered with."
            )
        logger.info("IDRISK2 pipeline ready.")
    @classmethod
    def from_env(cls) -> "IDRISK2Pipeline":
        """Instantiate pipeline from environment variables."""
        config = PipelineConfig.from_env()
        return cls(config)
    @require_permission("submit_classification")
    def classify(
        self,
        image_path: str,
        user: User,
        retain_image: bool = False,
    ) -> PipelineResult:
        """
        Run the full end-to-end classification pipeline on a food label image.
        Args:
            image_path: path to the food product label image
            user: authenticated user (enforces RBAC)
            retain_image: if True, retains image path in the minimised record
        Returns:
            PipelineResult with classification, intermediates, and metadata
        """
        start = time.perf_counter()
        logger.info(
            f"Classification request: {Path(image_path).name} "
            f"| user: {user.username}"
        )
        # --- 1. Load and validate image (single disk read) ---
        image_bytes = Path(image_path).read_bytes()
        mime_type = _infer_mime_type(image_path)
        validate_image_input(image_bytes, mime_type)
        # --- 2. Preprocess ---
        image = load_image(image_path)
        processed = preprocess_image(image)
        # --- 3. OCR ---
        ocr_results = self.ocr_engine.extract(processed)
        raw_ocr_text = " ".join(r.text for r in ocr_results if r.text.strip())
        ocr_text = sanitise_ocr_text(raw_ocr_text)
        logger.info(f"OCR extracted {len(ocr_results)} tokens")
        # --- 4. VLM multimodal analysis ---
        vlm_output = self.vlm.classify(processed, ocr_text)
        product_description = _build_product_description(vlm_output, ocr_text)
        logger.info(
            f"VLM preliminary classification: "
            f"{vlm_output.base_term_code} ({vlm_output.confidence})"
        )
        # --- 5. Advanced RAG retrieval ---
        rag_context = retrieve(
            query=product_description,
            index=self.index,
            llm=self.llm,
            use_hyde=self.config.use_hyde,
            use_rewrite=self.config.use_query_rewrite,
            use_rerank=self.config.use_rerank,
        )
        logger.info(
            f"RAG retrieved {len(rag_context.retrieved_passages)} passages"
        )
        # --- 6. RAG-grounded generation ---
        classification = classify_product(
            product_description=product_description,
            rag_context=rag_context,
            llm=self.llm,
            model_name=self.config.vlm_model,
            audit_dir=self.config.audit_generation_dir,
        )
        total_ms = (time.perf_counter() - start) * 1000
        # --- 7. Data minimisation (record is persisted to records_dir) ---
        minimised = minimise_record(
            ocr_text=ocr_text,
            image=image_bytes,
            classification={
                "base_term_code": classification.base_term_code,
                "base_term_label": classification.base_term_label,
                "facets": classification.facets,
                "confidence": classification.confidence,
            },
            user_id=user.user_id,
            retain_image=retain_image,
            image_path=image_path if retain_image else None,
        )
        save_minimised_record(minimised, self.config.records_dir)
        # --- 8. Audit log ---
        self.audit_logger.log(
            event_type="classification",
            user_id=user.user_id,
            details={
                "classification_id": classification.classification_id,
                "image": Path(image_path).name,
                "base_term_code": classification.base_term_code,
                "confidence": classification.confidence,
                "requires_human_review": classification.requires_human_review,
                "total_time_ms": round(total_ms, 2),
            },
        )
        result = PipelineResult(
            classification=classification,
            ocr_text=ocr_text,
            vlm_output=vlm_output,
            rag_context=rag_context,
            image_path=image_path,
            ocr_engine_used=self.config.ocr_engine,
            vlm_model_used=self.config.vlm_model,
            total_time_ms=round(total_ms, 2),
        )
        logger.info(
            f"Classification complete: {classification.base_term_code} "
            f"| confidence: {classification.confidence} "
            f"| {total_ms:.0f}ms"
            + (" [FLAGGED FOR REVIEW]" if classification.requires_human_review else "")
        )
        return result
    @require_permission("benchmark_engines")
    def benchmark_ocr_engines(
        self,
        image_path: str,
        user: User,
    ) -> dict[str, OCRBenchmark]:
        """
        Run all three OCR engines on an image and return comparative benchmarks.
        Used for the engine selection evaluation described in Section 4.3.1.
        Permission `benchmark_engines` is granted to Supervisor and
        Administrator roles via the central RBAC table in security.py.
        """
        image = load_image(image_path)
        processed = preprocess_image(image)
        return compare_engines(processed)
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build_product_description(vlm_output: VLMOutput, ocr_text: str) -> str:
    """
    Build a unified product description string from VLM output and OCR text.
    This is used as the RAG retrieval query.
    """
    parts = [
        f"Product: {vlm_output.base_term_label}",
        f"Preliminary FoodEx2 code: {vlm_output.base_term_code}",
        f"VLM reasoning: {vlm_output.reasoning}",
        f"OCR text: {ocr_text[:500]}",   # Truncate for query length
    ]
    return "\n".join(parts)
def _infer_mime_type(image_path: str) -> str:
    """Infer MIME type from file extension."""
    ext = Path(image_path).suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".heif": "image/heic",
    }
    return mime_map.get(ext, "application/octet-stream")

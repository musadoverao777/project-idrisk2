"""
IDRISK2 — Knowledge base rebuild driver
Force-rebuilds the FoodEx2 knowledge base from scratch, combining the
EFSA technical PDFs (system documentation) with the full taxonomy from
the Appendix B XLSX (~31k terms).
Usage (from the idrisk2/ root, with the venv active):
    python scripts/rebuild_kb.py
The script intentionally writes to the same persist_dir as the pipeline
(`<IDRISK2_DATA_DIR>/kb`) so the rebuilt index is immediately picked up
by future classification runs.
Expected duration: ~20–40 minutes on a modern laptop (CPU embedding).
The BGE-M3 model weights should already be cached in .cache/llama_index
from previous runs; if not, the first call also downloads them (~2 GB).
"""
import logging
import os
import shutil
import sys
import time
from pathlib import Path
# Make `src.*` importable when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
# Load .env from the project root so IDRISK2_DOCS_DIR / IDRISK2_DATA_DIR
# are picked up automatically (same pattern as build_kb.py).
from dotenv import load_dotenv  # noqa: E402
load_dotenv(PROJECT_ROOT / ".env")
from src.rag.knowledge_base import build_knowledge_base, verify_integrity  # noqa: E402
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("rebuild_kb")
def main() -> int:
    # Rebuilding the KB only needs documents and persistence paths.
    # The audit HMAC key required by the full pipeline is not used here,
    # so we read paths directly with sensible defaults rooted at the
    # project layout instead of going through load_config().
    docs_dir = os.environ.get(
        "IDRISK2_DOCS_DIR",
        str(PROJECT_ROOT / "docs" / "efsa"),
    )
    data_dir = Path(os.environ.get(
        "IDRISK2_DATA_DIR",
        str(PROJECT_ROOT / "data"),
    ))
    persist_dir = data_dir / "kb"
    logger.info("--- IDRISK2 knowledge base rebuild ---")
    logger.info(f"Documents:    {docs_dir}")
    logger.info(f"Persist dir:  {persist_dir}")
    if not Path(docs_dir).exists():
        logger.error(
            f"Documents directory not found: {docs_dir}\n"
            f"Set IDRISK2_DOCS_DIR or place EFSA documents at the default path."
        )
        return 2
    # Clear the old Chroma store so the new build starts clean.
    chroma_dir = persist_dir / "chroma"
    if chroma_dir.exists():
        logger.info(f"Removing previous Chroma store at {chroma_dir} ...")
        shutil.rmtree(chroma_dir)
    manifest = persist_dir / "manifest.json"
    if manifest.exists():
        logger.info(f"Removing previous manifest at {manifest} ...")
        manifest.unlink()
    started_at = time.perf_counter()
    index = build_knowledge_base(
        docs_dir=docs_dir,
        persist_dir=str(persist_dir),
        chunking_strategy="semantic",
        force_rebuild=True,
        include_taxonomy=True,
        taxonomy_detail_levels=None,  # full taxonomy (~31k approved terms)
    )
    elapsed = time.perf_counter() - started_at
    logger.info(f"Build finished in {elapsed/60:.1f} min")
    # Sanity check
    ok = verify_integrity(str(persist_dir))
    if not ok:
        logger.error("Integrity verification failed after rebuild.")
        return 1
    logger.info("Rebuild complete. KB is ready for use.")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())

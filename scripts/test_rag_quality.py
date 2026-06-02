"""
IDRISK2 — RAG quality probe
Runs the full classification pipeline on a small set of test images
and prints a focused report comparing the retrieval behaviour against
the pre-rebuild baseline. The goal is to confirm three things after
indexing the FoodEx2 taxonomy:
    (a) Retrieved chunks now include atomic taxonomy terms (chunk_id
        starts with "term_") with their FoodEx2 codes, not just PDF
        passages.
    (b) Rerank scores are higher than the pre-rebuild ~0.61 ceiling
        observed when only the EFSA PDFs were indexed.
    (c) Reasoning cites specific retrieved passages instead of falling
        back to phrases like "general FoodEx2 knowledge".
Usage (from idrisk2/ root, with the venv active and env vars set):
    python scripts/test_rag_quality.py
Optional arguments via env:
    IDRISK2_TEST_IMAGES   comma-separated list of image filenames to
                          probe (relative to images/test/). Defaults
                          to a small Portuguese / Brazilian set.
"""
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
# Load .env from the project root (same pattern as build_kb.py / benchmark_vlms.py).
# This populates IDRISK2_AUDIT_KEY, IDRISK2_DATA_DIR, IDRISK2_DOCS_DIR,
# OPENAI_API_KEY, etc. before any module that reads os.environ is imported.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(PROJECT_ROOT / ".env")
from pipeline import IDRISK2Pipeline  # noqa: E402
from src.security.security import User, Role  # noqa: E402
DEFAULT_TEST_IMAGES = [
    "feijoada.jpg",
    "brigadeiro.jpg",
    "francesinha.jpg",
    "pastel_de_nata.jpg",
    "salmao_com_arroz.jpg",
]
GROUNDING_BAD_PHRASES = [
    "general foodex2 knowledge",
    "did not provide specific information",
    "documentation did not",
    "not provide specific",
]
logging.basicConfig(level=logging.WARNING)
def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m"
def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m"
def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m"
def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"
def _check_grounding(reasoning: str) -> tuple[bool, str]:
    """Detect language suggesting the model ignored retrieval."""
    lower = reasoning.lower()
    for phrase in GROUNDING_BAD_PHRASES:
        if phrase in lower:
            return False, phrase
    return True, ""
def _summarise_passage(passage) -> str:
    """One-line summary of a retrieved passage."""
    cid = passage.chunk_id
    is_term = cid.startswith("term_")
    kind = "TERM" if is_term else "PDF"
    head = passage.text.split("\n", 1)[0][:90]
    return (
        f"    [{passage.final_rank}] {kind:4} {cid:24} "
        f"rerank={passage.rerank_score:.3f}  {head}"
    )
def probe_image(pipeline: IDRISK2Pipeline, user: User, image_path: Path) -> dict:
    """Run a single image through the pipeline and collect the metrics."""
    result = pipeline.classify(image_path=str(image_path), user=user)
    clf = result.classification
    rag = result.rag_context
    grounded, bad_phrase = _check_grounding(clf.reasoning)
    term_hits = sum(1 for p in rag.retrieved_passages if p.chunk_id.startswith("term_"))
    pdf_hits = len(rag.retrieved_passages) - term_hits
    max_rerank = max((p.rerank_score for p in rag.retrieved_passages), default=0.0)
    return {
        "image": image_path.name,
        "result": result,
        "grounded": grounded,
        "bad_phrase": bad_phrase,
        "term_hits": term_hits,
        "pdf_hits": pdf_hits,
        "max_rerank": max_rerank,
    }
def print_report(probe: dict) -> None:
    r = probe["result"]
    clf = r.classification
    rag = r.rag_context
    print()
    print("=" * 78)
    print(f"IMAGE: {probe['image']}")
    print("=" * 78)
    print(f"  Classification : {clf.base_term_code}  ({clf.base_term_label})")
    print(f"  Confidence     : {clf.confidence}")
    print(f"  Review flag    : {clf.requires_human_review}")
    print(f"  Total time     : {r.total_time_ms:.0f} ms")
    print()
    print(f"  Retrieved {len(rag.retrieved_passages)} passages "
          f"(TERM nodes: {probe['term_hits']}, PDF chunks: {probe['pdf_hits']})")
    for p in rag.retrieved_passages:
        print(_summarise_passage(p))
    print()
    print(f"  Max rerank score: {probe['max_rerank']:.3f}  "
          f"(baseline before rebuild: ~0.611)")
    if probe['grounded']:
        print(_green("  Grounding check : OK — reasoning does not fall back to general knowledge"))
    else:
        print(_red(f"  Grounding check : FAIL — reasoning contains \"{probe['bad_phrase']}\""))
    print()
    print(_dim("  Reasoning preview:"))
    for line in clf.reasoning.split("\n")[:4]:
        print(_dim(f"    {line[:120]}"))
def main() -> int:
    images_env = os.environ.get("IDRISK2_TEST_IMAGES")
    image_names = (
        [s.strip() for s in images_env.split(",") if s.strip()]
        if images_env
        else DEFAULT_TEST_IMAGES
    )
    images_dir = PROJECT_ROOT / "images" / "test"
    image_paths = [images_dir / name for name in image_names]
    missing = [p for p in image_paths if not p.exists()]
    if missing:
        print(_red(f"Missing test images: {[m.name for m in missing]}"))
        return 2
    print("Loading IDRISK2 pipeline (this initialises VLM, LLM, RAG)...")
    pipeline = IDRISK2Pipeline.from_env()
    user = User(
        user_id="test_probe",
        username="rag_probe",
        role=Role.INSPECTOR,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    probes = [probe_image(pipeline, user, path) for path in image_paths]
    for p in probes:
        print_report(p)
    # Aggregate summary
    print()
    print("=" * 78)
    print("AGGREGATE SUMMARY")
    print("=" * 78)
    grounded = sum(1 for p in probes if p["grounded"])
    avg_max_rerank = sum(p["max_rerank"] for p in probes) / len(probes)
    avg_term_hits = sum(p["term_hits"] for p in probes) / len(probes)
    print(f"  Images probed       : {len(probes)}")
    print(f"  Grounded reasoning  : {grounded}/{len(probes)}")
    print(f"  Avg max rerank      : {avg_max_rerank:.3f}  (baseline ~0.611)")
    print(f"  Avg term hits / img : {avg_term_hits:.1f}  (baseline 0)")
    print()
    return 0
if __name__ == "__main__":
    raise SystemExit(main())

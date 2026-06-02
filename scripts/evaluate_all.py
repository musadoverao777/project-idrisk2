"""
IDRISK2 — Full evaluation runner
Classifies every image in images/test/ through the full pipeline and
persists structured results to disk so the Cap. 6 (Evaluation) section
of the dissertation can be written from real data instead of guesses.
Outputs (under data/evaluation/):
    results_<timestamp>.jsonl   one JSON record per image (resumable)
    summary_<timestamp>.json    aggregate statistics
    LATEST_RESULTS              symlink/file pointing to the newest run
The script is RESUMABLE: if results_*.jsonl already exists for the
current run, it skips images already processed. An API hiccup half-way
through a 14-minute run does not waste the work done so far.
Usage (from idrisk2/ root, with venv active):
    python scripts/evaluate_all.py
    python scripts/evaluate_all.py --resume         # continue last run
    python scripts/evaluate_all.py --limit 5        # quick smoke test
"""
import argparse
import json
import logging
import os
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(PROJECT_ROOT / ".env")
from pipeline import IDRISK2Pipeline  # noqa: E402
from src.security.security import User, Role  # noqa: E402
logging.basicConfig(
    level=logging.WARNING,  # quiet — we have our own progress output
    format="%(levelname)s %(name)s: %(message)s",
)
EVAL_DIR = PROJECT_ROOT / "data" / "evaluation"
IMAGES_DIR = PROJECT_ROOT / "images" / "test"
GROUNDING_BAD_PHRASES = [
    "general foodex2 knowledge",
    "did not provide specific information",
    "documentation did not",
    "not provide specific",
]
# ---------------------------------------------------------------------------
def list_test_images() -> list[Path]:
    """Return all test images sorted alphabetically for stable ordering."""
    if not IMAGES_DIR.exists():
        raise FileNotFoundError(f"Test images dir not found: {IMAGES_DIR}")
    images = sorted(p for p in IMAGES_DIR.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".heic"})
    return images
def _check_grounding(reasoning: str) -> tuple[bool, str]:
    lower = (reasoning or "").lower()
    for phrase in GROUNDING_BAD_PHRASES:
        if phrase in lower:
            return False, phrase
    return True, ""
def _passage_record(passage) -> dict:
    return {
        "chunk_id": passage.chunk_id,
        "source": passage.source,
        "is_term": passage.chunk_id.startswith("term_"),
        "dense_score": passage.dense_score,
        "rrf_score": passage.rrf_score,
        "rerank_score": passage.rerank_score,
        "final_rank": passage.final_rank,
        "text_head": passage.text.split("\n", 1)[0][:160],
    }
def evaluate_one(pipeline: IDRISK2Pipeline, user: User, image_path: Path) -> dict:
    t0 = time.perf_counter()
    result = pipeline.classify(image_path=str(image_path), user=user)
    elapsed = time.perf_counter() - t0
    clf = result.classification
    rag = result.rag_context
    grounded, bad_phrase = _check_grounding(clf.reasoning)
    passages = [_passage_record(p) for p in rag.retrieved_passages]
    return {
        "image": image_path.name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_time_ms": result.total_time_ms,
        "wall_time_s": round(elapsed, 2),
        "classification": {
            "base_term_code": clf.base_term_code,
            "base_term_label": clf.base_term_label,
            "facets": clf.facets,
            "confidence": clf.confidence,
            "requires_human_review": clf.requires_human_review,
        },
        "reasoning": clf.reasoning,
        "grounding": {
            "ok": grounded,
            "bad_phrase": bad_phrase,
        },
        "vlm": {
            "model": result.vlm_model_used,
            "preliminary_code": result.vlm_output.base_term_code,
            "preliminary_confidence": result.vlm_output.confidence,
        },
        "ocr_token_count": len(result.ocr_text.split()) if result.ocr_text else 0,
        "rag": {
            "rewritten_query": rag.rewritten_query,
            "hyde_used": bool(rag.hyde_passage),
            "passages": passages,
            "max_rerank": max((p["rerank_score"] for p in passages), default=0.0),
            "term_hits": sum(1 for p in passages if p["is_term"]),
            "pdf_hits": sum(1 for p in passages if not p["is_term"]),
        },
        "classification_id": clf.classification_id,
    }
# ---------------------------------------------------------------------------
def compute_summary(records: list[dict]) -> dict:
    """Aggregate statistics across all evaluation records."""
    if not records:
        return {"n": 0}
    times = [r["wall_time_s"] for r in records]
    max_reranks = [r["rag"]["max_rerank"] for r in records]
    avg_term_hits = statistics.mean(r["rag"]["term_hits"] for r in records)
    confidence_dist = Counter(r["classification"]["confidence"] for r in records)
    flagged = sum(1 for r in records if r["classification"]["requires_human_review"])
    grounded = sum(1 for r in records if r["grounding"]["ok"])
    vlm_agreement = sum(
        1 for r in records
        if r["vlm"]["preliminary_code"] == r["classification"]["base_term_code"]
    )
    return {
        "n_images": len(records),
        "latency_seconds": {
            "min": min(times),
            "median": statistics.median(times),
            "mean": statistics.mean(times),
            "max": max(times),
        },
        "rerank_top1": {
            "min": min(max_reranks),
            "median": statistics.median(max_reranks),
            "mean": statistics.mean(max_reranks),
            "max": max(max_reranks),
        },
        "avg_term_hits_per_image": avg_term_hits,
        "grounded_reasoning_rate": grounded / len(records),
        "vlm_to_final_agreement_rate": vlm_agreement / len(records),
        "flagged_for_review": {
            "count": flagged,
            "rate": flagged / len(records),
        },
        "confidence_distribution": dict(confidence_dist),
        "ocr_nonempty_rate": sum(1 for r in records if r["ocr_token_count"] > 0) / len(records),
    }
# ---------------------------------------------------------------------------
def print_progress(idx: int, total: int, record: dict) -> None:
    clf = record["classification"]
    flag = " [REVIEW]" if clf["requires_human_review"] else ""
    print(
        f"  [{idx:>2}/{total}] {record['image']:<28} "
        f"-> {clf['base_term_code']} {clf['confidence']:<6} "
        f"rerank={record['rag']['max_rerank']:.3f}  "
        f"t={record['wall_time_s']:.1f}s{flag}"
    )
# ---------------------------------------------------------------------------
def load_existing_records(results_path: Path) -> list[dict]:
    if not results_path.exists():
        return []
    records = []
    with open(results_path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
def write_record(results_path: Path, record: dict) -> None:
    with open(results_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
# ---------------------------------------------------------------------------
SUPPORTED_VLMS = {"gpt4o", "claude", "llava", "qwen"}
def main() -> int:
    parser = argparse.ArgumentParser(description="Full IDRISK2 evaluation runner")
    parser.add_argument("--vlm", default=None, choices=sorted(SUPPORTED_VLMS),
                        help=("VLM backend to use (gpt4o | claude | llava | qwen). "
                              "Defaults to the value of IDRISK2_VLM_MODEL or to gpt4o."))
    parser.add_argument("--resume", action="store_true",
                        help="Resume the most recent run for the chosen VLM")
    parser.add_argument("--limit", type=int, default=None,
                        help="Stop after N images (for smoke testing)")
    args = parser.parse_args()
    # Resolve the VLM choice and propagate to the pipeline via env so the
    # PipelineConfig.from_env() call picks it up. Per-VLM evaluation outputs
    # are kept in distinct files so different VLM runs do not overwrite
    # each other and the cross-VLM comparison can read all of them at once.
    vlm = args.vlm or os.environ.get("IDRISK2_VLM_MODEL", "gpt4o")
    if vlm not in SUPPORTED_VLMS:
        print(f"Unsupported VLM: {vlm!r}. Choose from {sorted(SUPPORTED_VLMS)}",
              file=sys.stderr)
        return 2
    os.environ["IDRISK2_VLM_MODEL"] = vlm
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    latest_marker = EVAL_DIR / f"LATEST_{vlm.upper()}_RESULTS"
    if args.resume:
        if not latest_marker.exists():
            print(f"No previous run to resume from for VLM '{vlm}'.", file=sys.stderr)
            return 2
        results_path = Path(latest_marker.read_text().strip())
        run_id = results_path.stem.replace(f"results_{vlm}_", "")
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        results_path = EVAL_DIR / f"results_{vlm}_{run_id}.jsonl"
    summary_path = EVAL_DIR / f"summary_{vlm}_{run_id}.json"
    print(f"VLM: {vlm}")
    print(f"Run ID: {run_id}")
    print(f"Results file: {results_path}")
    images = list_test_images()
    if args.limit:
        images = images[:args.limit]
    existing = load_existing_records(results_path) if args.resume else []
    done_names = {r["image"] for r in existing}
    todo = [p for p in images if p.name not in done_names]
    print(f"Total test images: {len(images)}")
    print(f"Already done:      {len(done_names)}")
    print(f"To process:        {len(todo)}")
    if not todo:
        print("Nothing to do.")
        records = existing
    else:
        print("Loading IDRISK2 pipeline ...")
        pipeline = IDRISK2Pipeline.from_env()
        user = User(
            user_id="eval_runner",
            username="full_evaluation",
            role=Role.INSPECTOR,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        print(f"\nClassifying {len(todo)} image(s):\n")
        # Mark the run as the latest so future --resume can find it.
        # Per-VLM marker file so each VLM has its own resume point.
        latest_marker.write_text(str(results_path) + "\n")
        # Also keep a generic LATEST_RESULTS pointing to the most recent run
        # of any VLM (used by older tools that don't know about the per-VLM
        # marker convention).
        (EVAL_DIR / "LATEST_RESULTS").write_text(str(results_path) + "\n")
        records = list(existing)
        for i, image_path in enumerate(todo, start=1):
            try:
                record = evaluate_one(pipeline, user, image_path)
                write_record(results_path, record)
                records.append(record)
                print_progress(i, len(todo), record)
            except KeyboardInterrupt:
                print("\nInterrupted by user. Partial results saved.")
                break
            except Exception as e:
                print(f"  [{i:>2}/{len(todo)}] {image_path.name:<28} FAILED: {e}")
                continue
    # --- Summary ---
    summary = compute_summary(records)
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print("\n" + "=" * 70)
    print("EVALUATION SUMMARY")
    print("=" * 70)
    print(json.dumps(summary, indent=2))
    print(f"\nSummary written to: {summary_path}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())

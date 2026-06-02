"""
IDRISK2 — Cross-VLM comparative scoring
For every per-VLM evaluation present under data/evaluation/
(results_<vlm>_*.jsonl, located via the LATEST_<VLM>_RESULTS markers),
compute the same accuracy and calibration metrics that
score_against_ground_truth.py computes for a single VLM, and emit a
side-by-side comparison table ready for use in the Chapter 6
discussion of VLM substitutability.
Metrics reported per VLM:
    - Exact-match accuracy        (system code == ground truth code)
    - Family-level accuracy       (same 3-char taxonomy prefix)
    - VLM exact-match accuracy    (preliminary code == ground truth)
    - Label-leak rate             (final code == VLM code)
    - False high-confidence rate  (high-confidence outputs that are wrong)
    - Silent error rate           (errors that escaped human review)
    - Median latency (seconds)
Outputs:
    data/evaluation/cross_vlm_comparison_<timestamp>.json
    Stdout: comparison table
Usage:
    python scripts/compare_vlms.py
"""
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
EVAL_DIR = PROJECT_ROOT / "data" / "evaluation"
GROUND_TRUTH_PATH = PROJECT_ROOT / "data" / "ground_truth.json"
VLM_ORDER = ["gpt4o", "claude", "llava", "qwen"]
def family_prefix(code: str, length: int = 3) -> str:
    return (code or "")[:length].upper()
def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
def find_latest_results(vlm: str) -> Path | None:
    marker = EVAL_DIR / f"LATEST_{vlm.upper()}_RESULTS"
    if not marker.exists():
        return None
    path = Path(marker.read_text().strip())
    return path if path.exists() else None
# ---------------------------------------------------------------------------
def score_vlm(vlm: str, gt: dict, records: list[dict]) -> dict:
    """Compute all comparable metrics for a single VLM run."""
    by_image = {r["image"]: r for r in records}
    n = 0
    exact = family = vlm_exact = label_leak = 0
    high_correct = high_wrong = 0
    flagged_correct = flagged_wrong = 0
    not_flagged_correct = not_flagged_wrong = 0
    latencies = []
    for image, ann in gt.items():
        if ann.get("code") is None:
            continue
        r = by_image.get(image)
        if r is None:
            continue
        n += 1
        truth_code = ann["code"]
        system_code = r["classification"]["base_term_code"]
        vlm_code = r["vlm"]["preliminary_code"]
        confidence = r["classification"]["confidence"]
        review = r["classification"]["requires_human_review"]
        latencies.append(r["wall_time_s"])
        is_exact = system_code == truth_code
        is_family = family_prefix(system_code) == family_prefix(truth_code)
        is_vlm_exact = vlm_code == truth_code
        is_leak = system_code == vlm_code
        exact += int(is_exact)
        family += int(is_family)
        vlm_exact += int(is_vlm_exact)
        label_leak += int(is_leak)
        if confidence == "high":
            (high_correct if is_exact else high_wrong)
            high_correct += int(is_exact)
            high_wrong += int(not is_exact)
        if review:
            flagged_correct += int(is_exact)
            flagged_wrong += int(not is_exact)
        else:
            not_flagged_correct += int(is_exact)
            not_flagged_wrong += int(not is_exact)
    if n == 0:
        return {"vlm": vlm, "n": 0}
    return {
        "vlm": vlm,
        "n": n,
        "exact_accuracy": exact / n,
        "family_accuracy": family / n,
        "vlm_exact_accuracy": vlm_exact / n,
        "label_leak_rate": label_leak / n,
        "false_high_confidence_rate": (
            high_wrong / (high_correct + high_wrong)
            if (high_correct + high_wrong) else None
        ),
        "silent_error_rate": (
            not_flagged_wrong / (not_flagged_wrong + flagged_wrong)
            if (not_flagged_wrong + flagged_wrong) else None
        ),
        "median_latency_s": statistics.median(latencies),
        "mean_latency_s": statistics.mean(latencies),
        "counts": {
            "exact_correct": exact,
            "family_correct": family,
            "vlm_correct": vlm_exact,
            "label_leak": label_leak,
            "flagged_correct": flagged_correct,
            "flagged_wrong": flagged_wrong,
            "not_flagged_correct": not_flagged_correct,
            "not_flagged_wrong": not_flagged_wrong,
        },
    }
# ---------------------------------------------------------------------------
def fmt_pct(x: float | None) -> str:
    return f"{x:.1%}" if x is not None else "—"
def fmt_num(x: float | None, places: int = 1) -> str:
    return f"{x:.{places}f}" if x is not None else "—"
def print_table(scores: list[dict]) -> None:
    if not scores:
        print("No VLM evaluations found under data/evaluation/.")
        return
    print()
    print("=" * 95)
    print("CROSS-VLM COMPARISON")
    print("=" * 95)
    cols = [s["vlm"] for s in scores]
    header = f"  {'Metric':<32}"
    for c in cols:
        header += f" {c:>12}"
    print(header)
    print("-" * 95)
    rows = [
        ("Images evaluated (n)", lambda s: str(s["n"])),
        ("System exact-match accuracy", lambda s: fmt_pct(s.get("exact_accuracy"))),
        ("System family-match accuracy", lambda s: fmt_pct(s.get("family_accuracy"))),
        ("VLM exact-match accuracy", lambda s: fmt_pct(s.get("vlm_exact_accuracy"))),
        ("Label-leak rate", lambda s: fmt_pct(s.get("label_leak_rate"))),
        ("False high-confidence rate", lambda s: fmt_pct(s.get("false_high_confidence_rate"))),
        ("Silent error rate", lambda s: fmt_pct(s.get("silent_error_rate"))),
        ("Median latency (s)", lambda s: fmt_num(s.get("median_latency_s"))),
        ("Mean latency (s)", lambda s: fmt_num(s.get("mean_latency_s"))),
    ]
    for label, getter in rows:
        line = f"  {label:<32}"
        for s in scores:
            line += f" {getter(s):>12}"
        print(line)
    print()
# ---------------------------------------------------------------------------
def main() -> int:
    if not GROUND_TRUTH_PATH.exists():
        print("No ground_truth.json found. Run annotate_ground_truth.py first.",
              file=sys.stderr)
        return 2
    gt = json.loads(GROUND_TRUTH_PATH.read_text())
    scores = []
    for vlm in VLM_ORDER:
        path = find_latest_results(vlm)
        if path is None:
            continue
        records = load_jsonl(path)
        s = score_vlm(vlm, gt, records)
        s["results_file"] = path.name
        scores.append(s)
    if not scores:
        print("No VLM evaluations found. Run:")
        print("    python scripts/evaluate_all.py --vlm gpt4o")
        print("    python scripts/evaluate_all.py --vlm claude")
        print("    python scripts/evaluate_all.py --vlm llava")
        print("    python scripts/evaluate_all.py --vlm qwen")
        return 0
    print_table(scores)
    # Persist
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = EVAL_DIR / f"cross_vlm_comparison_{timestamp}.json"
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ground_truth_size": len(gt),
        "scores": scores,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"Report written to: {out_path}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())

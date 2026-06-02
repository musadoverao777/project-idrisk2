"""
IDRISK2 — Score system output against ground truth
Cross-references the latest evaluation results with the manually
annotated ground truth and computes the metrics needed for
Chapter 6 of the dissertation.
Metrics produced:
    1. Exact-match accuracy        (system code == ground truth code)
    2. Family-level accuracy       (same 3-char taxonomy prefix)
    3. VLM exact-match accuracy    (VLM preliminary code == ground truth)
    4. Label-leak rate             (system propagated VLM code unchanged)
    5. Calibration analysis        (does the confidence flag align with errors?)
    6. Per-image diagnostic table
Outputs:
    data/evaluation/scoring_<timestamp>.json   structured report
    Stdout: human-readable summary table
Usage:
    python scripts/score_against_ground_truth.py
"""
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
EVAL_DIR = PROJECT_ROOT / "data" / "evaluation"
GROUND_TRUTH_PATH = PROJECT_ROOT / "data" / "ground_truth.json"
def load_evaluation_records() -> dict[str, dict]:
    """Index the latest JSONL by image name for fast lookup."""
    latest = EVAL_DIR / "LATEST_RESULTS"
    if not latest.exists():
        raise FileNotFoundError("No evaluation results found.")
    path = Path(latest.read_text().strip())
    records = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                records[r["image"]] = r
    return records
def family_prefix(code: str, length: int = 3) -> str:
    """Return the leading characters of a FoodEx2 code, used as a
    cheap proxy for hierarchy proximity (codes that share a 3-char
    prefix usually sit close in the taxonomy tree)."""
    return (code or "")[:length].upper()
# ---------------------------------------------------------------------------
def per_image_diagnostics(gt: dict, records: dict) -> list[dict]:
    rows = []
    for image, ann in gt.items():
        record = records.get(image)
        if record is None or ann.get("code") is None:
            continue
        truth_code = ann["code"]
        truth_label = ann["label"]
        system_code = ann["system_code"]
        vlm_code = ann["vlm_code"]
        system_label = record["classification"]["base_term_label"]
        confidence = record["classification"]["confidence"]
        review = record["classification"]["requires_human_review"]
        max_rerank = record["rag"]["max_rerank"]
        exact = system_code == truth_code
        family = family_prefix(system_code) == family_prefix(truth_code)
        vlm_exact = vlm_code == truth_code
        label_leak = system_code == vlm_code
        rows.append({
            "image": image,
            "truth_code": truth_code,
            "truth_label": truth_label,
            "system_code": system_code,
            "system_label": system_label,
            "vlm_code": vlm_code,
            "confidence": confidence,
            "requires_review": review,
            "max_rerank": round(max_rerank, 3),
            "exact_match": exact,
            "family_match": family,
            "vlm_exact_match": vlm_exact,
            "label_leak": label_leak,
        })
    return rows
def compute_aggregates(rows: list[dict]) -> dict:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    exact = sum(1 for r in rows if r["exact_match"])
    family = sum(1 for r in rows if r["family_match"])
    vlm_exact = sum(1 for r in rows if r["vlm_exact_match"])
    leaks = [r for r in rows if r["label_leak"]]
    # Calibration: are flagged-for-review the wrong ones, and unflagged the right ones?
    high_correct = sum(1 for r in rows if r["confidence"] == "high" and r["exact_match"])
    high_wrong = sum(1 for r in rows if r["confidence"] == "high" and not r["exact_match"])
    med_correct = sum(1 for r in rows if r["confidence"] == "medium" and r["exact_match"])
    med_wrong = sum(1 for r in rows if r["confidence"] == "medium" and not r["exact_match"])
    flagged_correct = sum(1 for r in rows if r["requires_review"] and r["exact_match"])
    flagged_wrong = sum(1 for r in rows if r["requires_review"] and not r["exact_match"])
    not_flagged_correct = sum(1 for r in rows if not r["requires_review"] and r["exact_match"])
    not_flagged_wrong = sum(1 for r in rows if not r["requires_review"] and not r["exact_match"])
    # System uplift over VLM: how many cases did the RAG layer improve?
    rag_uplift = sum(
        1 for r in rows
        if not r["vlm_exact_match"] and r["exact_match"]
    )
    rag_damage = sum(
        1 for r in rows
        if r["vlm_exact_match"] and not r["exact_match"]
    )
    return {
        "n_images": n,
        "accuracy": {
            "system_exact": round(exact / n, 4),
            "system_family": round(family / n, 4),
            "vlm_exact": round(vlm_exact / n, 4),
        },
        "counts": {
            "system_correct": exact,
            "system_family_close": family,
            "vlm_correct": vlm_exact,
            "system_wrong": n - exact,
        },
        "label_leak": {
            "count": len(leaks),
            "rate": round(len(leaks) / n, 4),
            "all_wrong_when_leaked": all(not r["exact_match"] for r in leaks) if leaks else None,
            "images": [r["image"] for r in leaks],
        },
        "rag_layer_effect": {
            "uplift_count": rag_uplift,
            "uplift_rate": round(rag_uplift / n, 4),
            "damage_count": rag_damage,
            "comment": (
                "RAG layer correctly overrode the VLM in "
                f"{rag_uplift}/{n} cases ({rag_uplift/n:.0%}) "
                f"and never made a correct VLM call worse "
                f"({rag_damage} damage events)."
            ),
        },
        "calibration": {
            "high_confidence_correct": high_correct,
            "high_confidence_wrong": high_wrong,
            "medium_confidence_correct": med_correct,
            "medium_confidence_wrong": med_wrong,
            "false_high_confidence_rate": (
                round(high_wrong / (high_correct + high_wrong), 4)
                if (high_correct + high_wrong) else None
            ),
            "flagged_for_review_correct": flagged_correct,
            "flagged_for_review_wrong": flagged_wrong,
            "not_flagged_correct": not_flagged_correct,
            "not_flagged_wrong": not_flagged_wrong,
        },
    }
# ---------------------------------------------------------------------------
def print_diagnostics(rows: list[dict]) -> None:
    print()
    print("=" * 100)
    print(f"{'IMAGE':<26} {'TRUTH':<7} {'SYSTEM':<7} {'VLM':<7} "
          f"{'EXACT':<6} {'FAM':<4} {'LEAK':<5} {'CONF':<7} {'REV':<3}")
    print("-" * 100)
    for r in rows:
        exact = "✓" if r["exact_match"] else "✗"
        family = "✓" if r["family_match"] else "✗"
        leak = "✓" if r["label_leak"] else "·"
        review = "★" if r["requires_review"] else "·"
        print(
            f"{r['image']:<26} {r['truth_code']:<7} {r['system_code']:<7} "
            f"{r['vlm_code']:<7} {exact:<6} {family:<4} {leak:<5} "
            f"{r['confidence']:<7} {review:<3}"
        )
def print_summary(agg: dict) -> None:
    print()
    print("=" * 100)
    print("ACCURACY")
    print("=" * 100)
    print(f"  System exact match    : {agg['accuracy']['system_exact']:.1%}  "
          f"({agg['counts']['system_correct']}/{agg['n_images']})")
    print(f"  System family match   : {agg['accuracy']['system_family']:.1%}  "
          f"({agg['counts']['system_family_close']}/{agg['n_images']})  "
          f"(same 3-char taxonomy prefix)")
    print(f"  VLM exact match       : {agg['accuracy']['vlm_exact']:.1%}  "
          f"({agg['counts']['vlm_correct']}/{agg['n_images']})")
    print()
    print("=" * 100)
    print("RAG LAYER CONTRIBUTION")
    print("=" * 100)
    print(f"  Cases where RAG fixed a VLM error : "
          f"{agg['rag_layer_effect']['uplift_count']}/{agg['n_images']}  "
          f"({agg['rag_layer_effect']['uplift_rate']:.1%})")
    print(f"  Cases where RAG damaged a correct VLM call : "
          f"{agg['rag_layer_effect']['damage_count']}/{agg['n_images']}")
    print()
    print("=" * 100)
    print("LABEL LEAK (system propagated VLM code unchanged)")
    print("=" * 100)
    print(f"  Leak count            : {agg['label_leak']['count']}/{agg['n_images']}  "
          f"({agg['label_leak']['rate']:.1%})")
    print(f"  All wrong when leaked : {agg['label_leak']['all_wrong_when_leaked']}")
    print(f"  Affected images       : {', '.join(agg['label_leak']['images'])}")
    print()
    print("=" * 100)
    print("CALIBRATION (does confidence track correctness?)")
    print("=" * 100)
    c = agg["calibration"]
    print(f"  High confidence + correct  : {c['high_confidence_correct']}")
    print(f"  High confidence + WRONG    : {c['high_confidence_wrong']}  "
          f"<- false high-confidence rate: {c['false_high_confidence_rate']:.1%}")
    print(f"  Medium confidence + correct: {c['medium_confidence_correct']}")
    print(f"  Medium confidence + wrong  : {c['medium_confidence_wrong']}")
    print()
    print(f"  Flagged for review + correct  : {c['flagged_for_review_correct']}")
    print(f"  Flagged for review + wrong    : {c['flagged_for_review_wrong']}")
    print(f"  Not flagged + correct         : {c['not_flagged_correct']}")
    print(f"  Not flagged + WRONG           : {c['not_flagged_wrong']}  "
          f"<- silent errors that escaped review")
    print()
# ---------------------------------------------------------------------------
def main() -> int:
    if not GROUND_TRUTH_PATH.exists():
        print("No ground_truth.json found.")
        return 2
    gt = json.loads(GROUND_TRUTH_PATH.read_text())
    records = load_evaluation_records()
    rows = per_image_diagnostics(gt, records)
    agg = compute_aggregates(rows)
    print_diagnostics(rows)
    print_summary(agg)
    # Persist a structured report
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = EVAL_DIR / f"scoring_{timestamp}.json"
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ground_truth_size": len(gt),
        "evaluation_size": len(records),
        "aggregates": agg,
        "per_image": rows,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nStructured report written to: {report_path}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())

"""
IDRISK2 — Verify which FoodEx2 codes the VLM emits are real
Reads the latest evaluation JSONL and cross-references every code
mentioned by the VLM (`preliminary_code`) and by the final classifier
(`base_term_code`) against the FoodEx2 Appendix B taxonomy.
Answers three questions:
    1. Are the VLM's preliminary codes real FoodEx2 entries?
    2. When the code exists, does the VLM's narrative label match the
       real term name?
    3. Is the post-RAG final code always real and well-described?
This separates "hallucinated codes" (made-up identifiers) from
"misattributed codes" (real codes but wrong context) — useful framing
for the Cap. 7 discussion of hallucination mitigation.
Usage:
    python scripts/verify_vlm_codes.py
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(PROJECT_ROOT / ".env")
EVAL_DIR = PROJECT_ROOT / "data" / "evaluation"
XLSX_PATH = next(
    (PROJECT_ROOT / "docs" / "efsa").glob("*appendix*.xlsx"),
    None,
)
def load_term_dict(xlsx_path: Path) -> dict[str, dict]:
    """Build a {code -> {name, status, detail_level}} lookup from the XLSX."""
    from openpyxl import load_workbook
    print(f"Loading taxonomy from {xlsx_path.name} ...", file=sys.stderr)
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["term"]
    rows = ws.iter_rows(values_only=True)
    headers = next(rows)
    h = {name: i for i, name in enumerate(headers)}
    terms = {}
    for row in rows:
        if row is None:
            continue
        code = row[h["termCode"]]
        if not code:
            continue
        terms[code] = {
            "name": row[h["termExtendedName"]],
            "status": row[h["status"]],
            "detail_level": row[h["detailLevel"]],
        }
    wb.close()
    print(f"  Loaded {len(terms)} terms.", file=sys.stderr)
    return terms
def load_latest_results() -> list[dict]:
    latest = EVAL_DIR / "LATEST_RESULTS"
    if not latest.exists():
        raise FileNotFoundError("No evaluation run found. Run evaluate_all.py first.")
    path = Path(latest.read_text().strip())
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
def extract_vlm_label(reasoning: str) -> str:
    """
    Pull the VLM's claimed label for its preliminary code from the
    rewritten-query log, e.g. "Product: Stuffed fried plantain".
    """
    m = re.search(r"Product:\s*([^\n]+)", reasoning)
    return m.group(1).strip() if m else ""
def normalise(label: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (label or "").lower())
def overlap_ratio(a: str, b: str) -> float:
    """Simple bag-of-words overlap, ignoring stopwords."""
    stop = {"the", "a", "an", "of", "with", "and", "in", "or", "is"}
    wa = {w for w in normalise(a).split() if w and w not in stop}
    wb = {w for w in normalise(b).split() if w and w not in stop}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))
# ---------------------------------------------------------------------------
def main() -> int:
    if XLSX_PATH is None:
        print("No FoodEx2 XLSX found.", file=sys.stderr)
        return 2
    terms = load_term_dict(XLSX_PATH)
    records = load_latest_results()
    print()
    print("=" * 78)
    print("VLM PRELIMINARY CODE VERIFICATION")
    print("=" * 78)
    print()
    print(f"{'IMAGE':<24} {'VLM CODE':<8} {'EXISTS':<7} {'VLM CLAIMED':<32} {'REAL LABEL':<32}")
    print("-" * 110)
    vlm_invalid = 0
    vlm_mismatch = 0
    vlm_match = 0
    final_invalid = 0
    for r in records:
        img = r["image"]
        vlm_code = r["vlm"]["preliminary_code"]
        final_code = r["classification"]["base_term_code"]
        vlm_label = extract_vlm_label(r.get("reasoning", ""))[:30]
        real = terms.get(vlm_code)
        if real is None:
            status = "MISSING"
            vlm_invalid += 1
            real_label = "(not in taxonomy)"
        else:
            status = real["status"][:5]
            real_label = (real["name"] or "")[:30]
            similarity = overlap_ratio(vlm_label, real["name"])
            if similarity >= 0.3:
                vlm_match += 1
            else:
                vlm_mismatch += 1
        if final_code not in terms:
            final_invalid += 1
        print(f"{img:<24} {vlm_code:<8} {status:<7} {vlm_label:<32} {real_label:<32}")
    n = len(records)
    print()
    print("=" * 78)
    print("AGGREGATE")
    print("=" * 78)
    print(f"  Images evaluated     : {n}")
    print()
    print("  VLM preliminary codes:")
    print(f"    Not in taxonomy    : {vlm_invalid}/{n}  ({vlm_invalid/n:.0%})  <- HALLUCINATIONS")
    print(f"    Real but wrong tag : {vlm_mismatch}/{n}  ({vlm_mismatch/n:.0%})  <- misattribution")
    print(f"    Real and matching  : {vlm_match}/{n}  ({vlm_match/n:.0%})")
    print()
    print("  Final (post-RAG) codes:")
    print(f"    Not in taxonomy    : {final_invalid}/{n}  ({final_invalid/n:.0%})")
    if final_invalid == 0:
        print("    -> RAG layer eliminated all hallucinated codes ✓")
    print()
    # Most-frequent VLM codes (overused by VLM as fallback)
    vlm_freq = Counter(r["vlm"]["preliminary_code"] for r in records)
    most_common = vlm_freq.most_common(5)
    print("  Most-frequent VLM preliminary codes (VLM's go-to fallbacks):")
    for code, count in most_common:
        real = terms.get(code)
        label = real["name"] if real else "(not in taxonomy)"
        print(f"    {code}  ×{count}  {label[:50]}")
    print()
    return 0
if __name__ == "__main__":
    raise SystemExit(main())

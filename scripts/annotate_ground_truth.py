"""
IDRISK2 — Interactive ground-truth annotation tool
For each evaluation result, presents the human annotator with:
  - The image filename
  - The system's final classification (after RAG)
  - The five FoodEx2 terms the RAG retriever surfaced (with rerank scores)
  - The VLM's natural-language description of the image
and accepts:
  1-5         pick that candidate as ground truth
  <code>      type a different FoodEx2 code (e.g. A03VT) — validated against taxonomy
  /<keyword>  search the taxonomy for terms containing <keyword>
  none        record that none of the retrieved terms are appropriate
  skip        leave this image unannotated for now
  back        re-annotate the previous image
  quit        save and exit
Output:
  data/ground_truth.json   one entry per annotated image
The tool is RESUMABLE — re-running picks up at the first unannotated image.
Usage:
    python scripts/annotate_ground_truth.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(PROJECT_ROOT / ".env")
EVAL_DIR = PROJECT_ROOT / "data" / "evaluation"
GROUND_TRUTH_PATH = PROJECT_ROOT / "data" / "ground_truth.json"
# Default annotator ID written into every new ground truth entry. The
# FoodEx2Annotation schema requires this field for multi-annotator
# validation support (Section 4.2.2); the present evaluation uses a
# single annotator (Section 6.6), so all entries share this ID.
ANNOTATOR_ID = "bianca_oliveira"
XLSX_PATH = next(
    (PROJECT_ROOT / "docs" / "efsa").glob("*appendix*.xlsx"),
    None,
)
# ---------------------------------------------------------------------------
def load_taxonomy() -> dict[str, dict]:
    """Build a lookup of code -> {name, status, detail_level, scope_note}."""
    from openpyxl import load_workbook
    wb = load_workbook(XLSX_PATH, read_only=True, data_only=True)
    ws = wb["term"]
    rows = ws.iter_rows(values_only=True)
    headers = next(rows)
    h = {name: i for i, name in enumerate(headers)}
    terms = {}
    for row in rows:
        if row is None:
            continue
        code = row[h["termCode"]]
        if not code or (row[h["status"]] != "APPROVED"):
            continue
        terms[code] = {
            "name": row[h["termExtendedName"]] or "",
            "status": row[h["status"]],
            "detail_level": row[h["detailLevel"]],
            "scope_note": (row[h["termScopeNote"]] or "")[:200],
        }
    wb.close()
    return terms
def load_latest_results() -> list[dict]:
    latest = EVAL_DIR / "LATEST_RESULTS"
    if not latest.exists():
        raise FileNotFoundError("No evaluation results found. Run evaluate_all.py first.")
    path = Path(latest.read_text().strip())
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records
def load_ground_truth() -> dict:
    if GROUND_TRUTH_PATH.exists():
        with open(GROUND_TRUTH_PATH) as f:
            return json.load(f)
    return {}
def save_ground_truth(gt: dict) -> None:
    GROUND_TRUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(GROUND_TRUTH_PATH, "w", encoding="utf-8") as f:
        json.dump(gt, f, indent=2, ensure_ascii=False)
# ---------------------------------------------------------------------------
def search_taxonomy(terms: dict, keyword: str, limit: int = 10) -> list[tuple[str, str]]:
    """Return [(code, name), ...] for approved terms whose name matches keyword."""
    kw = keyword.lower().strip()
    if not kw:
        return []
    hits = []
    for code, info in terms.items():
        name = (info["name"] or "").lower()
        if kw in name:
            hits.append((code, info["name"]))
            if len(hits) >= limit:
                break
    return hits
# ---------------------------------------------------------------------------
def render_candidates(record: dict, terms: dict) -> list[dict]:
    """Build the candidate list shown to the annotator."""
    out = []
    for p in record["rag"]["passages"]:
        cid = p["chunk_id"]
        if cid.startswith("term_"):
            code = cid.removeprefix("term_")
            info = terms.get(code, {})
            out.append({
                "code": code,
                "label": info.get("name", "(missing in taxonomy)"),
                "rerank": p["rerank_score"],
            })
    return out
def print_header():
    print("\033[2J\033[H", end="")  # clear screen
    print("=" * 78)
    print("IDRISK2 — Ground truth annotation")
    print("=" * 78)
def print_record(idx: int, total: int, record: dict, candidates: list[dict],
                 system_code: str) -> None:
    clf = record["classification"]
    print(f"\n[{idx}/{total}]  Image: \033[1m{record['image']}\033[0m")
    print()
    print(f"  VLM said:    \"{record['vlm']['preliminary_code']}\" "
          f"(confidence {record['vlm']['preliminary_confidence']})")
    print(f"  System said: \033[36m{system_code}\033[0m  "
          f"({clf['base_term_label']})  "
          f"[confidence {clf['confidence']}]")
    print()
    print("  RAG candidates (sorted by rerank):")
    for i, c in enumerate(candidates, start=1):
        marker = " ← system" if c["code"] == system_code else ""
        print(f"    {i})  {c['code']}  {c['label'][:55]:<55}  "
              f"rerank={c['rerank']:.3f}{marker}")
    print()
    print("  Reasoning (excerpt):")
    excerpt = (clf.get("reasoning") or "").replace("\n", " ")
    print(f"    {excerpt[:200]}...")
    print()
# ---------------------------------------------------------------------------
def prompt_decision(terms: dict, candidates: list[dict]) -> tuple[str, dict]:
    """
    Returns (action, payload):
        action: "annotate" | "none" | "skip" | "back" | "quit"
        payload: {"code": ..., "label": ..., "source": ...} when action == "annotate"
    """
    while True:
        choice = input("  Pick [1-5] | code | /search | none | skip | back | quit > ").strip()
        if not choice:
            continue
        low = choice.lower()
        if low in ("quit", "q", "exit"):
            return "quit", {}
        if low in ("skip", "s"):
            return "skip", {}
        if low in ("back", "b"):
            return "back", {}
        if low in ("none", "n"):
            return "none", {}
        if choice.isdigit() and 1 <= int(choice) <= len(candidates):
            c = candidates[int(choice) - 1]
            return "annotate", {
                "base_term_code": c["code"],
                "base_term_label": c["label"],
                "facets": {},
                "confidence": "high",
                "notes": "",
                "source": "retrieved_candidate",
                "rerank_score": c["rerank"],
            }
        if choice.startswith("/"):
            keyword = choice[1:].strip()
            hits = search_taxonomy(terms, keyword)
            if not hits:
                print(f"    No matches for '{keyword}'.")
                continue
            print(f"    Found {len(hits)} match(es):")
            for i, (code, name) in enumerate(hits, start=1):
                print(f"      {i})  {code}  {name[:60]}")
            sub = input("    Pick number, or hit Enter to go back > ").strip()
            if sub.isdigit() and 1 <= int(sub) <= len(hits):
                code, name = hits[int(sub) - 1]
                return "annotate", {
                    "base_term_code": code,
                    "base_term_label": name,
                    "facets": {},
                    "confidence": "medium",
                    "notes": "",
                    "source": "keyword_search",
                    "search_keyword": keyword,
                }
            continue
        # Treat as raw code
        candidate_code = choice.upper().strip()
        if candidate_code in terms:
            return "annotate", {
                "base_term_code": candidate_code,
                "base_term_label": terms[candidate_code]["name"],
                "facets": {},
                "confidence": "high",
                "notes": "",
                "source": "manual_code",
            }
        print(f"    '{candidate_code}' not in approved taxonomy. Try /keyword to search.")
# ---------------------------------------------------------------------------
def main() -> int:
    if XLSX_PATH is None:
        print("FoodEx2 XLSX not found.")
        return 2
    print("Loading taxonomy and previous results ...")
    terms = load_taxonomy()
    print(f"  {len(terms)} approved terms.")
    records = load_latest_results()
    print(f"  {len(records)} evaluation records.")
    gt = load_ground_truth()
    print(f"  {len(gt)} already annotated.\n")
    # Iterate
    idx = 0
    while idx < len(records):
        record = records[idx]
        image = record["image"]
        if image in gt:
            idx += 1
            continue
        print_header()
        system_code = record["classification"]["base_term_code"]
        candidates = render_candidates(record, terms)
        print_record(idx + 1, len(records), record, candidates, system_code)
        action, payload = prompt_decision(terms, candidates)
        if action == "quit":
            break
        if action == "skip":
            idx += 1
            continue
        if action == "back":
            # find the previous annotated image and remove it
            if idx == 0:
                print("    Already at first image.")
                continue
            idx -= 1
            prev_image = records[idx]["image"]
            if prev_image in gt:
                del gt[prev_image]
                save_ground_truth(gt)
            continue
        if action == "none":
            payload = {
                "base_term_code": None,
                "base_term_label": None,
                "facets": {},
                "confidence": "low",
                "notes": "",
                "source": "no_appropriate_candidate",
            }
        gt[image] = {
            **payload,
            "annotator_id": ANNOTATOR_ID,
            "annotation_date": datetime.now(timezone.utc).isoformat(),
            "system_code": system_code,
            "vlm_code": record["vlm"]["preliminary_code"],
        }
        save_ground_truth(gt)
        idx += 1
    # Summary
    annotated = {k: v for k, v in gt.items() if v.get("base_term_code")}
    not_found = {k: v for k, v in gt.items() if v.get("base_term_code") is None}
    print("\n" + "=" * 78)
    print("ANNOTATION SUMMARY")
    print("=" * 78)
    print(f"  Total images:           {len(records)}")
    print(f"  Annotated with a code:  {len(annotated)}")
    print(f"  Marked 'none of these': {len(not_found)}")
    print(f"  Remaining:              {len(records) - len(gt)}")
    print(f"\n  Ground truth file: {GROUND_TRUTH_PATH}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())

"""
IDRISK2 — FoodEx2 XLSX Loader (Section 4.5.1, taxonomy ingestion)
Converts the EFSA FoodEx2 Catalogue Browser XLSX export
(efs39414e-sup-0002-appendix b.xlsx) into one LlamaIndex Document per
taxonomy term, with a body optimised for dense retrieval and rich
metadata for filtering, citation, and audit traceability.
Why this exists
---------------
The eight EFSA PDFs describe the FoodEx2 *system* (governance, yearly
maintenance, descriptor philosophy) but do not contain the taxonomy
itself. The actual hierarchy of ~31k food terms — the codes the
classification pipeline must assign — lives in the Appendix B XLSX.
Without indexing this file, the RAG layer cannot retrieve passages
that mention the candidate base term codes, and the LLM falls back
to its parametric knowledge of FoodEx2, defeating the purpose of
grounding.
Design notes
------------
- Each row in the 'term' sheet becomes one Document. The document
  granularity is the term — we deliberately do NOT chunk further,
  because splitting a term body would scatter its description and
  facets across multiple chunks, degrading both retrieval and audit
  traceability.
- The body is structured natural language so the embedding model
  (BAAI/bge-m3) can pick up semantic similarity from name, scope
  note, common/scientific names, and implicit facet expression.
- Deprecated terms are skipped by default — they are not valid
  targets for new classifications.
"""
import logging
from pathlib import Path
from typing import Iterator, Optional
from llama_index.core.schema import Document
logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
TERM_SHEET = "term"
# Columns of interest in the term sheet. Anything outside this list is
# ignored — the XLSX has 227 columns, the vast majority of which are
# hierarchy-specific flags that are not useful for retrieval.
BODY_FIELDS = [
    "termCode",
    "termExtendedName",
    "termScopeNote",
    "commonNames",
    "scientificNames",
    "implicitFacets",
    "allFacets",
]
METADATA_FIELDS = [
    "termCode",
    "termExtendedName",
    "status",
    "detailLevel",
    "termType",
    "deprecated",
    "version",
    "validFrom",
    "validTo",
    "reportParentCode",
    "reportHierarchyCode",
]
# Detail-level codes — kept for documentation and metadata typing.
DETAIL_LEVELS = {
    "H": "Hierarchy",
    "C": "Core",
    "E": "Extended",
    "M": "Marketing",
    "P": "Process",
    "F": "Facet",
}
# ---------------------------------------------------------------------------
# XLSX → Document conversion
# ---------------------------------------------------------------------------
def _format_term_body(row: dict) -> str:
    """
    Build the natural-language body for a single FoodEx2 term.
    The shape of the body is deliberately repetitive (name appears in
    the header AND in 'Common names') because the embedding model
    weights repeated content more strongly during semantic matching.
    """
    code = row.get("termCode", "")
    name = row.get("termExtendedName", "") or ""
    scope = row.get("termScopeNote", "") or ""
    common = row.get("commonNames", "") or ""
    scientific = row.get("scientificNames", "") or ""
    implicit = row.get("implicitFacets", "") or ""
    all_facets = row.get("allFacets", "") or ""
    detail = DETAIL_LEVELS.get(row.get("detailLevel"), row.get("detailLevel") or "")
    lines = [f"FoodEx2 term {code}: {name}"]
    if detail:
        lines.append(f"Detail level: {detail}")
    if scope:
        lines.append("")
        lines.append(f"Description: {scope}")
    if common:
        lines.append(f"Common names: {common}")
    if scientific:
        lines.append(f"Scientific names: {scientific}")
    if implicit:
        lines.append(f"Implicit facets: {implicit}")
    if all_facets and all_facets != implicit:
        lines.append(f"Full facet expression: {all_facets}")
    return "\n".join(lines)
def _row_metadata(row: dict, source_file: str) -> dict:
    """Extract structured metadata for filtering, citation, and audit."""
    meta = {"source": source_file, "kind": "foodex2_term"}
    for field in METADATA_FIELDS:
        value = row.get(field)
        if value is None or value == "":
            continue
        # LlamaIndex/Chroma metadata must be JSON-serialisable scalars.
        meta[field] = str(value) if not isinstance(value, (int, float, bool)) else value
    return meta
def _iter_term_rows(
    xlsx_path: Path,
    include_deprecated: bool = False,
) -> Iterator[dict]:
    """
    Yield one dict per term row.
    Streams the workbook in read-only mode to avoid loading 31k rows
    into memory at once.
    """
    from openpyxl import load_workbook
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    if TERM_SHEET not in wb.sheetnames:
        raise ValueError(
            f"Sheet '{TERM_SHEET}' not found in {xlsx_path.name}. "
            f"Available sheets: {wb.sheetnames}"
        )
    ws = wb[TERM_SHEET]
    rows = ws.iter_rows(values_only=True)
    headers = next(rows)
    header_index = {h: i for i, h in enumerate(headers)}
    for raw in rows:
        if raw is None:
            continue
        row = {h: raw[i] for h, i in header_index.items() if i < len(raw)}
        # Skip deprecated terms unless explicitly requested.
        deprecated = row.get("deprecated")
        if not include_deprecated and (deprecated == 1 or row.get("status") == "DEPRECATED"):
            continue
        # Skip rows with no code (occasional blank rows in the workbook).
        if not row.get("termCode"):
            continue
        yield row
    wb.close()
def load_foodex2_terms(
    xlsx_path: str,
    include_deprecated: bool = False,
    detail_levels: Optional[set[str]] = None,
) -> list[Document]:
    """
    Load the FoodEx2 taxonomy from the Appendix B XLSX as one Document
    per term.
    Args:
        xlsx_path: path to the EFSA Appendix B XLSX
        include_deprecated: if True, also yields DEPRECATED terms.
            Defaults to False — deprecated terms should not be valid
            classification targets.
        detail_levels: if provided, only yields terms whose detailLevel
            is in this set. Use {"H", "C"} for the lighter ~8.8k subset
            or leave None for the full ~31.3k taxonomy.
    Returns:
        list of LlamaIndex Document objects (one per term)
    """
    path = Path(xlsx_path)
    if not path.exists():
        raise FileNotFoundError(f"XLSX not found: {xlsx_path}")
    source_file = path.name
    documents: list[Document] = []
    skipped_by_level = 0
    for row in _iter_term_rows(path, include_deprecated=include_deprecated):
        if detail_levels is not None and row.get("detailLevel") not in detail_levels:
            skipped_by_level += 1
            continue
        body = _format_term_body(row)
        metadata = _row_metadata(row, source_file)
        documents.append(Document(text=body, metadata=metadata))
    logger.info(
        f"Loaded {len(documents)} FoodEx2 terms from {source_file} "
        f"(deprecated={'included' if include_deprecated else 'skipped'}, "
        f"filtered_by_level={skipped_by_level})"
    )
    return documents

"""
IDRISK2 — Shared types and constants
Single source of truth for cross-module type definitions and policy
constants that would otherwise duplicate across vlm.py, generation.py,
and preprocessing.py.
"""
from enum import Enum
class Confidence(str, Enum):
    """
    Classification confidence levels — shared across VLM output,
    RAG generation, and human annotation.
    Subclassing `str` keeps the enum values JSON-serialisable without
    a custom encoder: `json.dumps(Confidence.HIGH)` emits `"high"`,
    so dataclasses that store confidence as a plain `str` continue
    to work unchanged.
    """
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    @classmethod
    def values(cls) -> set[str]:
        """Return the set of valid confidence strings."""
        return {m.value for m in cls}
    @classmethod
    def is_valid(cls, value: str) -> bool:
        """Check whether a string is a recognised confidence level."""
        return value in cls.values()
    @classmethod
    def coerce(cls, value: str) -> str:
        """
        Normalise a confidence string. Returns the input if valid,
        otherwise defaults to "low" — the safe choice for downstream
        review triggering, since unknown confidences should not be
        treated as high-trust.
        """
        return value if cls.is_valid(value) else cls.LOW.value
# ---------------------------------------------------------------------------
# Human-review policy
# ---------------------------------------------------------------------------
# Confidence levels that automatically flag a classification for human
# review. The default ({"low", "medium"}) is conservative and aligned
# with the EU AI Act's human-oversight requirement for high-risk AI
# systems (Article 14) — only "high" confidence proceeds without review.
# Override by passing a custom set to the generation component if the
# operational context tolerates more autonomy.
REVIEW_TRIGGER_LEVELS: set[str] = {
    Confidence.LOW.value,
    Confidence.MEDIUM.value,
}

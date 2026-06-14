"""
IDRISK2 — OCR Engine Selection and Comparison Module (Section 4.3)
Implements and benchmarks three OCR engines:
- Tesseract (pytesseract)
- EasyOCR
- PaddleOCR
Supported languages: English (en), Portuguese (pt), Spanish (es), French (fr)
Output format for all engines:
    List of OCRResult — each containing:
        - text: extracted string
        - bbox: (x, y, w, h) bounding box
        - confidence: float 0.0–1.0
"""
import time
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import cv2
import numpy as np
import pytesseract
import easyocr
try:
    # paddleocr é opcional (pesado; requer paddlepaddle). Só é necessário se
    # IDRISK2_OCR_ENGINE=paddleocr. Em deploys leves não é instalado.
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None
logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Supported language codes per engine
# ---------------------------------------------------------------------------
TESSERACT_LANGS = "eng+por+spa+fra"
EASYOCR_LANGS = ["en", "pt", "es", "fr"]
PADDLEOCR_LANGS = {
    "en": "en",
    "pt": "pt",   # Latin script — covered by multilingual model
    "es": "es",
    "fr": "fr",
}
PADDLEOCR_LANG = "en"   # PaddleOCR uses a single lang arg; latin covers pt/es/fr
# ---------------------------------------------------------------------------
# Shared output dataclass
# ---------------------------------------------------------------------------
@dataclass
class OCRResult:
    """Normalised OCR output — engine-agnostic."""
    text: str
    bbox: tuple[int, int, int, int]   # (x, y, width, height)
    confidence: float                  # 0.0 – 1.0
@dataclass
class OCRBenchmark:
    """Benchmark results for a single engine on a single image."""
    engine: str
    results: list[OCRResult]
    full_text: str
    processing_time_ms: float
    word_count: int
    mean_confidence: float
# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------
class BaseOCREngine(ABC):
    """Common interface for all OCR engines."""
    @abstractmethod
    def extract(self, image: np.ndarray) -> list[OCRResult]:
        """Extract text and bounding boxes from a preprocessed image."""
    def extract_full_text(self, image: np.ndarray) -> str:
        """Convenience method — returns concatenated text only."""
        return " ".join(r.text for r in self.extract(image) if r.text.strip())
# ---------------------------------------------------------------------------
# Tesseract engine
# ---------------------------------------------------------------------------
class TesseractEngine(BaseOCREngine):
    """
    Tesseract OCR via pytesseract.
    Configured for food label imagery with LSTM engine (OEM 3).
    """
    def __init__(self, langs: str = TESSERACT_LANGS):
        self.langs = langs
        self.config = f"--oem 3 --psm 11"   # PSM 11: sparse text, no OSD
    def extract(self, image: np.ndarray) -> list[OCRResult]:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        data = pytesseract.image_to_data(
            rgb,
            lang=self.langs,
            config=self.config,
            output_type=pytesseract.Output.DICT,
        )
        results = []
        for i, text in enumerate(data["text"]):
            text = text.strip()
            if not text:
                continue
            conf = float(data["conf"][i])
            if conf < 0:   # Tesseract returns -1 for uncertain tokens
                continue
            x, y, w, h = (
                data["left"][i], data["top"][i],
                data["width"][i], data["height"][i],
            )
            results.append(OCRResult(
                text=text,
                bbox=(x, y, w, h),
                confidence=conf / 100.0,
            ))
        return results
# ---------------------------------------------------------------------------
# EasyOCR engine
# ---------------------------------------------------------------------------
class EasyOCREngine(BaseOCREngine):
    """
    EasyOCR engine.
    Initialised once and reused across calls to avoid GPU reload overhead.
    """
    def __init__(self, langs: list[str] = EASYOCR_LANGS, gpu: bool = False):
        logger.info("Initialising EasyOCR — this may take a moment...")
        self.reader = easyocr.Reader(langs, gpu=gpu)
    def extract(self, image: np.ndarray) -> list[OCRResult]:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        raw = self.reader.readtext(rgb, detail=1)
        results = []
        for (bbox_pts, text, conf) in raw:
            text = text.strip()
            if not text:
                continue
            # EasyOCR returns 4 corner points — convert to (x, y, w, h)
            pts = np.array(bbox_pts, dtype=np.int32)
            x, y, w, h = cv2.boundingRect(pts)
            results.append(OCRResult(
                text=text,
                bbox=(x, y, w, h),
                confidence=float(conf),
            ))
        return results
# ---------------------------------------------------------------------------
# PaddleOCR engine
# ---------------------------------------------------------------------------
class PaddleOCREngine(BaseOCREngine):
    """
    PaddleOCR engine (compatible with PaddleOCR >= 3.x).
    Uses textline orientation classification to handle rotated text
    common on curved packaging.
    """
    def __init__(self, lang: str = PADDLEOCR_LANG):
        if PaddleOCR is None:
            raise ImportError(
                "paddleocr não está instalado neste ambiente. "
                "Usa IDRISK2_OCR_ENGINE=easyocr (ou tesseract), ou instala paddleocr."
            )
        logger.info("Initialising PaddleOCR...")
        self.ocr = PaddleOCR(
            use_textline_orientation=True,
            lang=lang,
        )

    def extract(self, image: np.ndarray) -> list[OCRResult]:
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        raw = self.ocr.ocr(rgb)
        results = []
        if not raw:
            return results
        for page in raw:
            if page is None:
                continue
            # PaddleOCR 3.x: page is a Result object with .rec_texts,
            # .rec_scores and .det_boxes attributes; fall back to iterating
            # lines for older 2.x list format.
            if hasattr(page, "rec_texts"):
                for text, conf, bbox_pts in zip(
                    page.rec_texts, page.rec_scores, page.det_boxes
                ):
                    text = text.strip()
                    if not text:
                        continue
                    pts = np.array(bbox_pts, dtype=np.int32)
                    x, y, w, h = cv2.boundingRect(pts)
                    results.append(OCRResult(
                        text=text,
                        bbox=(x, y, w, h),
                        confidence=float(conf),
                    ))
            else:
                # Legacy 2.x format: [[bbox, (text, conf)], ...]
                for line in page:
                    bbox_pts, (text, conf) = line
                    text = text.strip()
                    if not text:
                        continue
                    pts = np.array(bbox_pts, dtype=np.int32)
                    x, y, w, h = cv2.boundingRect(pts)
                    results.append(OCRResult(
                        text=text,
                        bbox=(x, y, w, h),
                        confidence=float(conf),
                    ))
        return results
# ---------------------------------------------------------------------------
# Engine factory
# ---------------------------------------------------------------------------
ENGINES = {
    "tesseract": TesseractEngine,
    "easyocr": EasyOCREngine,
    "paddleocr": PaddleOCREngine,
}
def get_engine(name: str) -> BaseOCREngine:
    """Instantiate an OCR engine by name."""
    name = name.lower()
    if name not in ENGINES:
        raise ValueError(f"Unknown engine '{name}'. Choose from: {list(ENGINES)}")
    return ENGINES[name]()
# ---------------------------------------------------------------------------
# Benchmarking
# ---------------------------------------------------------------------------
def benchmark_engine(
    engine: BaseOCREngine,
    image: np.ndarray,
    engine_name: str,
) -> OCRBenchmark:
    """
    Run a single engine on an image and return timing + quality metrics.
    """
    start = time.perf_counter()
    results = engine.extract(image)
    elapsed_ms = (time.perf_counter() - start) * 1000
    full_text = " ".join(r.text for r in results if r.text.strip())
    confidences = [r.confidence for r in results]
    mean_conf = float(np.mean(confidences)) if confidences else 0.0
    return OCRBenchmark(
        engine=engine_name,
        results=results,
        full_text=full_text,
        processing_time_ms=round(elapsed_ms, 2),
        word_count=len(results),
        mean_confidence=round(mean_conf, 4),
    )
def compare_engines(
    image: np.ndarray,
    engines: Optional[list[str]] = None,
    output_path: Optional[str] = None,
) -> dict[str, OCRBenchmark]:
    """
    Run all (or selected) engines on a single image and return benchmarks.
    Optionally saves results to a JSON file.
    Args:
        image: preprocessed BGR image
        engines: list of engine names to run (default: all three)
        output_path: if provided, saves benchmark JSON here
    Returns:
        dict mapping engine name to OCRBenchmark
    """
    engines_to_run = engines or list(ENGINES.keys())
    benchmarks = {}
    for name in engines_to_run:
        logger.info(f"Running {name}...")
        engine = get_engine(name)
        benchmark = benchmark_engine(engine, image, name)
        benchmarks[name] = benchmark
        logger.info(
            f"{name}: {benchmark.word_count} words | "
            f"confidence {benchmark.mean_confidence:.2%} | "
            f"{benchmark.processing_time_ms:.1f}ms"
        )
    if output_path:
        _save_benchmarks(benchmarks, output_path)
    return benchmarks
def _save_benchmarks(benchmarks: dict[str, OCRBenchmark], path: str):
    """Serialise benchmark results to JSON."""
    serialisable = {}
    for name, b in benchmarks.items():
        serialisable[name] = {
            "engine": b.engine,
            "full_text": b.full_text,
            "processing_time_ms": b.processing_time_ms,
            "word_count": b.word_count,
            "mean_confidence": b.mean_confidence,
            "results": [
                {"text": r.text, "bbox": r.bbox, "confidence": r.confidence}
                for r in b.results
            ],
        }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serialisable, f, indent=2, ensure_ascii=False)
    logger.info(f"Benchmark results saved to {path}")
# ---------------------------------------------------------------------------
# Visualisation helper
# ---------------------------------------------------------------------------
def draw_bboxes(
    image: np.ndarray,
    results: list[OCRResult],
    colour: tuple[int, int, int] = (0, 255, 0),
    min_confidence: float = 0.5,
) -> np.ndarray:
    """
    Draw bounding boxes and text labels on a copy of the image.
    Only draws results above min_confidence threshold.
    """
    annotated = image.copy()
    for r in results:
        if r.confidence < min_confidence:
            continue
        x, y, w, h = r.bbox
        cv2.rectangle(annotated, (x, y), (x + w, y + h), colour, 2)
        label = f"{r.text} ({r.confidence:.0%})"
        cv2.putText(
            annotated, label, (x, max(y - 5, 10)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, colour, 1,
            cv2.LINE_AA,
        )
    return annotated
# ---------------------------------------------------------------------------
# Evaluation metrics
# ---------------------------------------------------------------------------
def compute_cer(reference: str, hypothesis: str) -> float:
    """
    Compute Character Error Rate (CER) between reference and hypothesis.
    CER = edit_distance(ref, hyp) / len(ref), clipped to [0.0, 1.0].
    Clipping is required because edit distance can exceed len(ref) when
    the hypothesis is much longer than the reference (insertions inflate
    the score arbitrarily). Capping at 1.0 keeps the metric comparable
    across samples.
    """
    import editdistance
    ref = reference.strip().lower()
    hyp = hypothesis.strip().lower()
    if len(ref) == 0:
        return 0.0 if len(hyp) == 0 else 1.0
    return min(1.0, editdistance.eval(ref, hyp) / len(ref))
def compute_wer(reference: str, hypothesis: str) -> float:
    """
    Compute Word Error Rate (WER) between reference and hypothesis.
    WER = edit_distance(ref_words, hyp_words) / len(ref_words),
    clipped to [0.0, 1.0] (see compute_cer for rationale).
    """
    import editdistance
    ref_words = reference.strip().lower().split()
    hyp_words = hypothesis.strip().lower().split()
    if len(ref_words) == 0:
        return 0.0 if len(hyp_words) == 0 else 1.0
    return min(1.0, editdistance.eval(ref_words, hyp_words) / len(ref_words))
def evaluate_engines(
    benchmarks: dict[str, OCRBenchmark],
    ground_truth: str,
) -> dict[str, dict]:
    """
    Compute CER and WER for each engine against a ground truth transcript.
    Args:
        benchmarks: output of compare_engines()
        ground_truth: manually transcribed label text
    Returns:
        dict mapping engine name to {"cer": float, "wer": float}
    """
    metrics = {}
    for name, b in benchmarks.items():
        metrics[name] = {
            "cer": round(compute_cer(ground_truth, b.full_text), 4),
            "wer": round(compute_wer(ground_truth, b.full_text), 4),
            "processing_time_ms": b.processing_time_ms,
            "mean_confidence": b.mean_confidence,
        }
        logger.info(
            f"{name} — CER: {metrics[name]['cer']:.2%} | "
            f"WER: {metrics[name]['wer']:.2%}"
        )
    return metrics

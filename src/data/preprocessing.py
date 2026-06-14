"""
IDRISK2 — Data Collection and Preprocessing Module (Section 4.2)
Handles:
- Multi-format image ingestion (JPG, PNG, WEBP, HEIC)
- Image quality assessment
- Preprocessing pipeline (resize, denoise, binarize, deskew)
- Label region detection (ROI extraction)
- Dataset annotation schema for FoodEx2
"""
import json
import hashlib
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
import cv2
import numpy as np
from PIL import Image, ExifTags
import pillow_heif  # HEIC support
# Register HEIF opener so PIL can open .heic files
pillow_heif.register_heif_opener()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class FoodEx2Annotation:
    """
    Ground truth FoodEx2 annotation for a single product.
    The `confidence` field must match a value from
    `src.common.types.Confidence` (high / medium / low) — kept as
    `str` so the dataclass remains JSON-serialisable without a
    custom encoder.
    """
    base_term_code: str           # e.g. "A00JL"
    base_term_label: str          # e.g. "Wheat flour"
    facets: dict[str, str]        # e.g. {"F28": "A07XG", "F04": "A037V"}
    annotator_id: str
    annotation_date: str
    confidence: str               # Confidence enum value — see src/common/types.py
    notes: str = ""
@dataclass
class ProductSample:
    """A single food product sample in the IDRISK2 dataset."""
    sample_id: str
    image_paths: list[str]        # Multiple faces of the packaging
    product_name: str
    country_of_origin: str
    language: str                 # Primary language on label
    annotation: Optional[FoodEx2Annotation] = None
    metadata: dict = field(default_factory=dict)
# ---------------------------------------------------------------------------
# Image ingestion
# ---------------------------------------------------------------------------
SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
def load_image(image_path: str) -> np.ndarray:
    """
    Load an image from disk, handling multiple formats including HEIC.
    Returns a BGR numpy array (OpenCV format).
    """
    path = Path(image_path)
    if path.suffix.lower() not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format: {path.suffix}")
    # PIL handles HEIC via pillow-heif; convert everything to RGB then BGR
    pil_image = Image.open(image_path)
    # Apply EXIF orientation correction (common on smartphone photos)
    pil_image = _apply_exif_orientation(pil_image)
    # Convert to RGB (drop alpha if present)
    pil_image = pil_image.convert("RGB")
    # Convert to OpenCV BGR
    image = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
    logger.info(f"Loaded image: {path.name} — shape {image.shape}")
    return image
def _apply_exif_orientation(image: Image.Image) -> Image.Image:
    """Rotate image to correct orientation based on EXIF metadata."""
    try:
        exif = image._getexif()
        if exif is None:
            return image
        orientation_key = next(
            k for k, v in ExifTags.TAGS.items() if v == "Orientation"
        )
        orientation = exif.get(orientation_key)
        rotation_map = {3: 180, 6: 270, 8: 90}
        if orientation in rotation_map:
            image = image.rotate(rotation_map[orientation], expand=True)
    except Exception:
        pass  # No EXIF data — proceed without rotation
    return image
# ---------------------------------------------------------------------------
# Image quality assessment
# ---------------------------------------------------------------------------
def assess_quality(image: np.ndarray) -> dict:
    """
    Compute image quality metrics to flag low-quality inputs.
    Returns a dict with sharpness, brightness, and contrast scores.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Sharpness via Laplacian variance (higher = sharper)
    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
    # Brightness via mean pixel intensity
    brightness = float(np.mean(gray))
    # Contrast via standard deviation
    contrast = float(np.std(gray))
    quality = {
        "sharpness": round(sharpness, 2),
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "is_acceptable": sharpness > 100 and 40 < brightness < 220,
    }
    if not quality["is_acceptable"]:
        logger.warning(f"Low quality image detected: {quality}")
    return quality
# ---------------------------------------------------------------------------
# Preprocessing pipeline
# ---------------------------------------------------------------------------
def preprocess_image(
    image: np.ndarray,
    target_size: tuple[int, int] = (1600, 1200),
    denoise: bool = True,
    deskew: bool = True,
) -> np.ndarray:
    """
    Full preprocessing pipeline for food label images.
    Steps:
    1. Resize to target resolution
    2. Noise reduction (Gaussian filter)
    3. Deskew (correct camera angle distortion)
    4. Contrast enhancement (CLAHE)
    """
    # 1. Resize maintaining aspect ratio
    image = _resize(image, target_size)
    # 2. Denoise
    if denoise:
        image = cv2.fastNlMeansDenoisingColored(image, h=10, hColor=10)
    # 3. Deskew
    if deskew:
        image = _deskew(image)
    # 4. CLAHE contrast enhancement on L channel (LAB colour space)
    image = _enhance_contrast(image)
    return image
def _resize(image: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    """Resize to target size maintaining aspect ratio with padding."""
    h, w = image.shape[:2]
    target_w, target_h = target_size
    scale = min(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
    # Pad to exact target size
    canvas = np.full((target_h, target_w, 3), 255, dtype=np.uint8)
    y_offset = (target_h - new_h) // 2
    x_offset = (target_w - new_w) // 2
    canvas[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized
    return canvas
def _deskew(image: np.ndarray) -> np.ndarray:
    """Correct skew angle using Hough line transform."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 100, minLineLength=100, maxLineGap=10)
    if lines is None:
        return image
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 != x1:
            angles.append(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
    if not angles:
        return image
    median_angle = np.median(angles)
    # Only correct if skew is non-trivial (> 0.5 degrees)
    if abs(median_angle) < 0.5:
        return image
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    return cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)
def _enhance_contrast(image: np.ndarray) -> np.ndarray:
    """Apply CLAHE contrast enhancement in LAB colour space."""
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    enhanced = cv2.merge([l, a, b])
    return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
# ---------------------------------------------------------------------------
# Label region of interest (ROI) detection
# ---------------------------------------------------------------------------
def extract_label_regions(image: np.ndarray) -> dict[str, np.ndarray]:
    """
    Detect and extract key label regions using contour analysis.
    Returns a dict with keys:
    - 'full': the full preprocessed image
    - 'text_regions': image with detected text contours highlighted
    - 'binarized': binarized version optimised for OCR
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # Binarize using adaptive thresholding (handles uneven lighting)
    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )
    # Morphological operations to connect text regions
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    dilated = cv2.dilate(binary, kernel, iterations=2)
    # Find contours of potential text blocks
    contours, _ = cv2.findContours(
        cv2.bitwise_not(dilated), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    # Filter contours by area (discard noise and very large regions)
    h, w = image.shape[:2]
    min_area = (h * w) * 0.001
    max_area = (h * w) * 0.5
    text_contours = [c for c in contours if min_area < cv2.contourArea(c) < max_area]
    # Draw detected regions on a copy
    annotated = image.copy()
    cv2.drawContours(annotated, text_contours, -1, (0, 255, 0), 2)
    return {
        "full": image,
        "binarized": binary,
        "text_regions": annotated,
    }
# ---------------------------------------------------------------------------
# Dataset management
# ---------------------------------------------------------------------------
class IDRISK2Dataset:
    """
    Manages the IDRISK2 evaluation dataset.
    Handles sample registration, annotation, and persistence.
    """
    def __init__(self, dataset_dir: str):
        self.dataset_dir = Path(dataset_dir)
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dataset_dir / "index.json"
        self.samples: dict[str, ProductSample] = {}
        self._load_index()
    def _load_index(self):
        """Load existing dataset index from disk."""
        if self.index_path.exists():
            with open(self.index_path) as f:
                data = json.load(f)
            for sample_id, sample_data in data.items():
                ann_data = sample_data.pop("annotation", None)
                annotation = FoodEx2Annotation(**ann_data) if ann_data else None
                self.samples[sample_id] = ProductSample(
                    **sample_data, annotation=annotation
                )
            logger.info(f"Loaded {len(self.samples)} samples from index.")
    def _save_index(self):
        """Persist dataset index to disk."""
        serializable = {}
        for sample_id, sample in self.samples.items():
            d = asdict(sample)
            serializable[sample_id] = d
        with open(self.index_path, "w") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)
    def _generate_id(self, image_paths: list[str]) -> str:
        """Generate a deterministic sample ID from image paths."""
        content = "".join(sorted(image_paths)).encode()
        return "IDRISK2_" + hashlib.md5(content).hexdigest()[:8].upper()
    def add_sample(
        self,
        image_paths: list[str],
        product_name: str,
        country_of_origin: str,
        language: str,
        annotation: Optional[FoodEx2Annotation] = None,
    ) -> str:
        """Register a new product sample in the dataset."""
        sample_id = self._generate_id(image_paths)
        if sample_id in self.samples:
            logger.warning(f"Sample {sample_id} already exists. Skipping.")
            return sample_id
        sample = ProductSample(
            sample_id=sample_id,
            image_paths=image_paths,
            product_name=product_name,
            country_of_origin=country_of_origin,
            language=language,
            annotation=annotation,
        )
        self.samples[sample_id] = sample
        self._save_index()
        logger.info(f"Registered sample {sample_id}: {product_name}")
        return sample_id
    def annotate(self, sample_id: str, annotation: FoodEx2Annotation):
        """Add or update the FoodEx2 annotation for a sample."""
        if sample_id not in self.samples:
            raise ValueError(f"Sample {sample_id} not found.")
        self.samples[sample_id].annotation = annotation
        self._save_index()
        logger.info(f"Annotated sample {sample_id} with {annotation.base_term_code}")
    def get_unannotated(self) -> list[ProductSample]:
        """Return samples that still require annotation."""
        return [s for s in self.samples.values() if s.annotation is None]
    def summary(self) -> dict:
        """Return dataset statistics."""
        total = len(self.samples)
        annotated = sum(1 for s in self.samples.values() if s.annotation)
        languages = set(s.language for s in self.samples.values())
        countries = set(s.country_of_origin for s in self.samples.values())
        return {
            "total_samples": total,
            "annotated": annotated,
            "pending_annotation": total - annotated,
            "languages": sorted(languages),
            "countries": sorted(countries),
        }
# ---------------------------------------------------------------------------
# Full preprocessing pipeline (entry point)
# ---------------------------------------------------------------------------
def process_sample(image_path: str, output_dir: str) -> dict:
    """
    Run the full preprocessing pipeline on a single image.
    Saves preprocessed outputs and returns quality and region metadata.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    # Load
    image = load_image(image_path)
    # Assess quality
    quality = assess_quality(image)
    # Preprocess
    processed = preprocess_image(image)
    # Extract regions
    regions = extract_label_regions(processed)
    # Save outputs
    stem = Path(image_path).stem
    cv2.imwrite(str(output_path / f"{stem}_processed.jpg"), regions["full"])
    cv2.imwrite(str(output_path / f"{stem}_binary.jpg"), regions["binarized"])
    cv2.imwrite(str(output_path / f"{stem}_regions.jpg"), regions["text_regions"])
    return {
        "source": image_path,
        "quality": quality,
        "outputs": {
            "processed": str(output_path / f"{stem}_processed.jpg"),
            "binarized": str(output_path / f"{stem}_binary.jpg"),
            "regions": str(output_path / f"{stem}_regions.jpg"),
        }
    }

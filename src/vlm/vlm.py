"""
IDRISK2 — Vision-Language Model Module (Section 4.4)
Implements a unified interface for four VLM candidates that span the
two principal deployment paradigms relevant to the IDRISK2 use case:
- GPT-4o        (OpenAI API)            — proprietary cloud
- Claude        (Anthropic API)         — proprietary cloud
- LLaVA         (HuggingFace, local)    — open-source local inference
- Qwen-VL       (HuggingFace, local)    — open-source local inference
All models receive:
    - Preprocessed food image (base64 encoded)
    - OCR-extracted text (may be empty for unlabelled dishes)
    - Structured prompt for FoodEx2 classification
All models return:
    - VLMOutput dataclass with classification result and reasoning
"""
import base64
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Optional
import cv2
import numpy as np
from PIL import Image
from src.common.types import Confidence
logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------
@dataclass
class VLMOutput:
    """Normalised VLM output — model-agnostic."""
    model: str
    base_term_code: str          # e.g. "A00JL"
    base_term_label: str         # e.g. "Wheat flour"
    facets: dict[str, str]       # e.g. {"F28": "A07XG"}
    reasoning: str               # Step-by-step justification
    confidence: str              # "high" | "medium" | "low"
    raw_response: str            # Full model output for audit
    processing_time_ms: float
# ---------------------------------------------------------------------------
# Prompt engineering
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are an expert food classification assistant specialised
in the EFSA FoodEx2 taxonomy. Your task is to analyse food images and assign
the correct FoodEx2 classification. The image may be a product label or a
photo of a prepared dish — classify based on whatever evidence is available.

Your response MUST be ONLY a valid JSON object with this exact structure:
{
    "base_term_code": "A0CKL",
    "base_term_label": "Prepared dish name",
    "facets": {
        "F28": "A07XG",
        "F04": "A037V"
    },
    "reasoning": "Step-by-step explanation of classification decision",
    "confidence": "high"
}

Classification rules:
- Always assign the most specific applicable FoodEx2 base term code
- Include ALL relevant facets: processing method (F28), physical state (F04),
  packaging (F30), heat treatment (F27), animal species (F01), etc.
- For prepared dishes/meals without a label, classify based on visual content
- Use "UNKNOWN" as base_term_code ONLY if the food cannot be identified at all
- Do NOT use "XXXXX" — that is a schema placeholder, never a valid output
- Confidence: "high" = clear evidence, "medium" = some ambiguity, "low" = uncertain
- Return ONLY the JSON object — no prose, no markdown fences, no explanation outside JSON
"""

FEW_SHOT_EXAMPLE = """Example 1 — product label:
OCR text: "Whole wheat flour, stone-ground, 1kg, packaged"
Output:
{
    "base_term_code": "A00JL",
    "base_term_label": "Wheat flour",
    "facets": {"F28": "A07XG", "F04": "A037V", "F30": "A037W"},
    "reasoning": "Label identifies stone-ground wheat flour (A00JL). F28 stone-ground processing, F04 packaged solid state, F30 packaged consumer format.",
    "confidence": "high"
}

Example 2 — photo of prepared dish (no label):
OCR text: ""
Output:
{
    "base_term_code": "A0FQJ",
    "base_term_label": "Mixed dish with meat and vegetables",
    "facets": {"F28": "A07YG", "F04": "A037T"},
    "reasoning": "Visual analysis shows a cooked dish with meat pieces and vegetables. No label text available. Classified visually as mixed meat-vegetable dish.",
    "confidence": "medium"
}"""


def build_prompt(ocr_text: str, include_few_shot: bool = True) -> str:
    """
    Build the classification prompt. Adapts message based on OCR availability.
    """
    prompt_parts = []
    if include_few_shot:
        prompt_parts.append(FEW_SHOT_EXAMPLE)
        prompt_parts.append("---")

    if ocr_text.strip():
        prompt_parts.append(
            f"Classify the food product shown in the image.\n\n"
            f"OCR text extracted from label:\n{ocr_text}\n\n"
            f"Use both the image and OCR text. Return ONLY a JSON object."
        )
    else:
        prompt_parts.append(
            f"Classify the food shown in the image. "
            f"No label text was detected — classify based on visual content only.\n\n"
            f"Return ONLY a JSON object with the FoodEx2 classification."
        )
    return "\n".join(prompt_parts)
# ---------------------------------------------------------------------------
# Image encoding utility
# ---------------------------------------------------------------------------
def encode_image_base64(image: np.ndarray) -> str:
    """Convert a BGR numpy array to a base64-encoded JPEG string."""
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(rgb)
    buffer = BytesIO()
    pil_image.save(buffer, format="JPEG", quality=95)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")
def parse_vlm_response(raw: str, model_name: str) -> dict:
    """
    Parse and validate the JSON response from any VLM.
    Handles: markdown code fences, JSON embedded in prose, trailing commas.
    """
    import re

    clean = raw.strip()

    # 1. Strip ```json ... ``` or ``` ... ``` fences
    fence = re.search(r"```(?:json)?\s*([\s\S]+?)```", clean)
    if fence:
        clean = fence.group(1).strip()
    else:
        # 2. Extract the first {...} JSON object anywhere in the response
        brace = re.search(r"\{[\s\S]*\}", clean)
        if brace:
            clean = brace.group(0)

    # 3. Remove inline // comments (common LLM mistake in JSON)
    clean = re.sub(r"//[^\n]*", "", clean)

    # 4. Remove trailing commas before } or ]
    clean = re.sub(r",\s*([}\]])", r"\1", clean)

    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        logger.warning(f"{model_name}: Failed to parse JSON response. Returning raw.")
        return {
            "base_term_code": "UNKNOWN",
            "base_term_label": "Parse error",
            "facets": {},
            "reasoning": raw,
            "confidence": Confidence.LOW.value,
        }

    # Validate required fields
    required = ["base_term_code", "base_term_label", "facets", "reasoning", "confidence"]
    for field in required:
        if field not in parsed:
            parsed[field] = "" if field != "facets" else {}

    # Reject schema placeholders used literally
    if parsed.get("base_term_code") in ("XXXXX", "", None):
        parsed["base_term_code"] = "UNKNOWN"

    # Coerce confidence to a recognised level
    parsed["confidence"] = Confidence.coerce(str(parsed.get("confidence", "")))
    return parsed
# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------
class BaseVLM(ABC):
    """Common interface for all VLM candidates."""
    @abstractmethod
    def classify(
        self,
        image: np.ndarray,
        ocr_text: str,
        include_few_shot: bool = True,
    ) -> VLMOutput:
        """
        Classify a food product from its label image and OCR text.
        Args:
            image: preprocessed BGR numpy array
            ocr_text: text extracted by the OCR module
            include_few_shot: whether to include the few-shot example in the prompt
        Returns:
            VLMOutput with classification result and reasoning
        """
# ---------------------------------------------------------------------------
# GPT-4o
# ---------------------------------------------------------------------------
class GPT4oVLM(BaseVLM):
    """
    GPT-4o via OpenAI API.
    Requires OPENAI_API_KEY environment variable.
    """
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o"):
        import openai
        import os
        self.client = openai.OpenAI(api_key=api_key or os.environ["OPENAI_API_KEY"])
        self.model = model
    def classify(
        self,
        image: np.ndarray,
        ocr_text: str,
        include_few_shot: bool = True,
    ) -> VLMOutput:
        image_b64 = encode_image_base64(image)
        prompt = build_prompt(ocr_text, include_few_shot)
        start = time.perf_counter()
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}",
                                "detail": "high",
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                },
            ],
            temperature=0.1,    # Low temperature for deterministic classification
            max_tokens=1500,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        raw = response.choices[0].message.content
        parsed = parse_vlm_response(raw, "GPT-4o")
        return VLMOutput(
            model="gpt-4o",
            base_term_code=parsed["base_term_code"],
            base_term_label=parsed["base_term_label"],
            facets=parsed["facets"],
            reasoning=parsed["reasoning"],
            confidence=parsed["confidence"],
            raw_response=raw,
            processing_time_ms=round(elapsed_ms, 2),
        )
# ---------------------------------------------------------------------------
# LLaVA
# ---------------------------------------------------------------------------
class LLaVAVLM(BaseVLM):
    """
    LLaVA via HuggingFace Transformers (local inference).
    The default model is LLaVA-NeXT (LLaVA-1.6) with the Mistral-7B
    backbone, which is the strongest open-source vision-language model
    in the LLaVA family at the time of writing and matches the
    LlavaNextProcessor / LlavaNextForConditionalGeneration API used by
    this class. To run on smaller hardware, substitute
    `llava-hf/llava-1.5-7b-hf` (LLaVA-1.5) at the cost of switching to
    LlavaProcessor / LlavaForConditionalGeneration.
    """
    DEFAULT_MODEL = "llava-hf/llava-v1.6-mistral-7b-hf"
    def __init__(self, model_id: str = DEFAULT_MODEL):
        import torch
        from transformers import (
            LlavaNextProcessor,
            LlavaNextForConditionalGeneration,
        )
        logger.info(f"Loading LLaVA model: {model_id}")
        self.processor = LlavaNextProcessor.from_pretrained(model_id)
        self.model = LlavaNextForConditionalGeneration.from_pretrained(
            model_id,
            torch_dtype=torch.float16,
            device_map="auto",
            low_cpu_mem_usage=True,
        )
        self.model_id = model_id
    def classify(
        self,
        image: np.ndarray,
        ocr_text: str,
        include_few_shot: bool = True,
    ) -> VLMOutput:
        import torch
        from PIL import Image as PILImage
        prompt = build_prompt(ocr_text, include_few_shot)
        # LLaVA-NeXT (Mistral) expects the Mistral chat template:
        #   [INST] <image>\n<user_text> [/INST]
        # Use apply_chat_template for forward compatibility with
        # processor changes across transformers versions.
        conversation = [
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": f"{SYSTEM_PROMPT}\n\n{prompt}"},
                ],
            },
        ]
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = PILImage.fromarray(rgb)
        try:
            full_prompt = self.processor.apply_chat_template(
                conversation, add_generation_prompt=True
            )
        except (AttributeError, TypeError):
            # Older transformers versions do not expose apply_chat_template
            # on the LLaVA-NeXT processor — fall back to the raw template.
            full_prompt = f"[INST] <image>\n{SYSTEM_PROMPT}\n\n{prompt} [/INST]"
        inputs = self.processor(
            text=full_prompt,
            images=pil_image,
            return_tensors="pt",
        ).to(self.model.device)
        start = time.perf_counter()
        with torch.no_grad():
            output = self.model.generate(
                **inputs,
                max_new_tokens=1500,
                temperature=0.1,
                do_sample=False,
            )
        elapsed_ms = (time.perf_counter() - start) * 1000
        raw = self.processor.decode(output[0], skip_special_tokens=True)
        # Strip everything up to and including the assistant marker
        # ([/INST]) so the parsed JSON does not include the input prompt.
        if "[/INST]" in raw:
            raw = raw.split("[/INST]")[-1].strip()
        parsed = parse_vlm_response(raw, "LLaVA")
        return VLMOutput(
            model=self.model_id,
            base_term_code=parsed["base_term_code"],
            base_term_label=parsed["base_term_label"],
            facets=parsed["facets"],
            reasoning=parsed["reasoning"],
            confidence=parsed["confidence"],
            raw_response=raw,
            processing_time_ms=round(elapsed_ms, 2),
        )
# ---------------------------------------------------------------------------
# Qwen-VL
# ---------------------------------------------------------------------------
class QwenVLM(BaseVLM):
    """
    Qwen2-VL via HuggingFace Transformers (local inference).
    The default model is `Qwen/Qwen2-VL-7B-Instruct`, which is the
    current Qwen-VL family release at the time of writing. Qwen2-VL
    supports PIL images directly via the processor (no temporary file
    on disk is required) and uses the standard
    Qwen2VLForConditionalGeneration generation interface, replacing the
    bespoke `model.chat()` method of the legacy Qwen-VL-Chat release.
    """
    DEFAULT_MODEL = "Qwen/Qwen2-VL-7B-Instruct"
    def __init__(self, model_id: str = DEFAULT_MODEL):
        import torch
        from transformers import (
            Qwen2VLForConditionalGeneration,
            AutoProcessor,
        )
        logger.info(f"Loading Qwen2-VL model: {model_id}")
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.model = Qwen2VLForConditionalGeneration.from_pretrained(
            model_id,
            torch_dtype=torch.float16,
            device_map="auto",
            low_cpu_mem_usage=True,
        )
        self.model_id = model_id
    def classify(
        self,
        image: np.ndarray,
        ocr_text: str,
        include_few_shot: bool = True,
    ) -> VLMOutput:
        import torch
        from PIL import Image as PILImage
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = PILImage.fromarray(rgb)
        prompt = build_prompt(ocr_text, include_few_shot)
        # Qwen2-VL uses the standard chat-template format with a typed
        # content list (image + text), processed in a single call.
        messages = [
            {
                "role": "system",
                "content": [{"type": "text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": pil_image},
                    {"type": "text", "text": prompt},
                ],
            },
        ]
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(
            text=[text],
            images=[pil_image],
            return_tensors="pt",
        ).to(self.model.device)
        start = time.perf_counter()
        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=1500,
                temperature=0.1,
                do_sample=False,
            )
        elapsed_ms = (time.perf_counter() - start) * 1000
        # Strip the input prompt tokens from the output before decoding.
        generated_ids = [
            out_ids[len(in_ids):]
            for in_ids, out_ids in zip(inputs.input_ids, output_ids)
        ]
        raw = self.processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]
        parsed = parse_vlm_response(raw, "Qwen2-VL")
        return VLMOutput(
            model=self.model_id,
            base_term_code=parsed["base_term_code"],
            base_term_label=parsed["base_term_label"],
            facets=parsed["facets"],
            reasoning=parsed["reasoning"],
            confidence=parsed["confidence"],
            raw_response=raw,
            processing_time_ms=round(elapsed_ms, 2),
        )
# ---------------------------------------------------------------------------
# Claude (Anthropic API)
# ---------------------------------------------------------------------------
class ClaudeVLM(BaseVLM):
    """
    Claude via the Anthropic Messages API.
    Requires ANTHROPIC_API_KEY environment variable.
    Default model is claude-sonnet-4 for the balance of cost and quality;
    `claude-opus-4` is recommended for highest-accuracy classification
    runs at higher cost, and `claude-haiku-4-5` is recommended for
    faster, cheaper inference at the cost of reasoning depth.
    """
    DEFAULT_MODEL = "claude-sonnet-4-6"
    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        import anthropic
        import os
        self.client = anthropic.Anthropic(
            api_key=api_key or os.environ["ANTHROPIC_API_KEY"]
        )
        self.model = model
    def classify(
        self,
        image: np.ndarray,
        ocr_text: str,
        include_few_shot: bool = True,
    ) -> VLMOutput:
        image_b64 = encode_image_base64(image)
        prompt = build_prompt(ocr_text, include_few_shot)
        start = time.perf_counter()
        # Anthropic's Messages API treats system as a top-level field and
        # accepts image content blocks alongside text blocks in the user
        # message. Image is provided as a base64-encoded JPEG, mirroring
        # the GPT-4o implementation above.
        response = self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            temperature=0.1,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                },
            ],
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        # The response is a list of content blocks; for our text-only
        # classification prompts the first block is the JSON output.
        raw = "".join(
            block.text for block in response.content if block.type == "text"
        )
        parsed = parse_vlm_response(raw, "Claude")
        return VLMOutput(
            model=self.model,
            base_term_code=parsed["base_term_code"],
            base_term_label=parsed["base_term_label"],
            facets=parsed["facets"],
            reasoning=parsed["reasoning"],
            confidence=parsed["confidence"],
            raw_response=raw,
            processing_time_ms=round(elapsed_ms, 2),
        )
# ---------------------------------------------------------------------------
# VLM factory
# ---------------------------------------------------------------------------
VLM_REGISTRY = {
    "gpt4o": GPT4oVLM,
    "claude": ClaudeVLM,
    "llava": LLaVAVLM,
    "qwen": QwenVLM,
}
def get_vlm(name: str) -> BaseVLM:
    """Instantiate a VLM by name."""
    name = name.lower()
    if name not in VLM_REGISTRY:
        raise ValueError(f"Unknown VLM '{name}'. Choose from: {list(VLM_REGISTRY)}")
    return VLM_REGISTRY[name]()
# ---------------------------------------------------------------------------
# Comparative evaluation
# ---------------------------------------------------------------------------
@dataclass
class VLMBenchmark:
    """Benchmark results for a single VLM on a single product sample."""
    model: str
    output: VLMOutput
    base_term_correct: bool
    facets_correct: dict[str, bool]   # Per-facet correctness
    processing_time_ms: float
def evaluate_vlm(
    output: VLMOutput,
    ground_truth_code: str,
    ground_truth_facets: dict[str, str],
) -> VLMBenchmark:
    """
    Evaluate a VLM output against ground truth annotation.
    Args:
        output: VLMOutput from classify()
        ground_truth_code: correct FoodEx2 base term code
        ground_truth_facets: correct facet code-descriptor pairs
    Returns:
        VLMBenchmark with correctness flags
    """
    base_correct = output.base_term_code == ground_truth_code
    facets_correct = {
        facet: output.facets.get(facet) == descriptor
        for facet, descriptor in ground_truth_facets.items()
    }
    return VLMBenchmark(
        model=output.model,
        output=output,
        base_term_correct=base_correct,
        facets_correct=facets_correct,
        processing_time_ms=output.processing_time_ms,
    )
def compare_vlms(
    image: np.ndarray,
    ocr_text: str,
    models: Optional[list[str]] = None,
    ground_truth_code: Optional[str] = None,
    ground_truth_facets: Optional[dict[str, str]] = None,
    output_path: Optional[str] = None,
) -> dict[str, VLMOutput]:
    """
    Run all (or selected) VLMs on a single product and return outputs.
    Optionally evaluates against ground truth and saves results.
    Args:
        image: preprocessed BGR numpy array
        ocr_text: OCR-extracted label text
        models: list of model names to run (default: all three)
        ground_truth_code: optional ground truth base term code for evaluation
        ground_truth_facets: optional ground truth facets for evaluation
        output_path: if provided, saves results to JSON
    Returns:
        dict mapping model name to VLMOutput
    """
    models_to_run = models or list(VLM_REGISTRY.keys())
    outputs = {}
    for name in models_to_run:
        logger.info(f"Running {name}...")
        vlm = get_vlm(name)
        output = vlm.classify(image, ocr_text)
        outputs[name] = output
        logger.info(
            f"{name}: {output.base_term_code} ({output.base_term_label}) "
            f"| confidence: {output.confidence} "
            f"| {output.processing_time_ms:.1f}ms"
        )
    if output_path:
        _save_vlm_results(outputs, output_path)
    return outputs
def _save_vlm_results(outputs: dict[str, VLMOutput], path: str):
    """Serialise VLM outputs to JSON for audit and analysis."""
    serialisable = {}
    for name, out in outputs.items():
        serialisable[name] = {
            "model": out.model,
            "base_term_code": out.base_term_code,
            "base_term_label": out.base_term_label,
            "facets": out.facets,
            "reasoning": out.reasoning,
            "confidence": out.confidence,
            "processing_time_ms": out.processing_time_ms,
        }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(serialisable, f, indent=2, ensure_ascii=False)
    logger.info(f"VLM results saved to {path}")

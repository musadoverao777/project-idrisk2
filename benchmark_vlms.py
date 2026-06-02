"""
IDRISK2 — Benchmark Comparativo dos 3 VLMs (Secção 4.4)
=========================================================
Corre GPT-4o, LLaVA e Qwen-VL nas imagens de teste e exporta
resultados para CSV para análise na dissertação.

Uso local (GPU/RAM suficiente):
    python benchmark_vlms.py

Uso no Google Colab:
    1. Fazer upload deste ficheiro e da pasta images/test/
    2. Instalar dependências:
       !pip install openai transformers torch torchvision
       !pip install opencv-python-headless pillow numpy python-dotenv
    3. Definir OPENAI_API_KEY:
       import os; os.environ["OPENAI_API_KEY"] = "sk-..."
    4. Correr: !python benchmark_vlms.py

Requisitos de hardware:
    - GPT-4o: apenas API key OpenAI (sem GPU necessária)
    - LLaVA 1.5-7B: ~14 GB RAM ou GPU com 8 GB VRAM (float16)
                     ~8 GB RAM com quantização 4-bit (bitsandbytes)
    - Qwen-VL-Chat: ~14 GB RAM ou GPU com 8 GB VRAM (float16)
"""
import csv
import json
import logging
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Silenciar warnings não críticos
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

IMAGES_DIR = Path("images/test")
OUTPUT_CSV = Path("results/benchmark_vlms.csv")
OUTPUT_JSON = Path("results/benchmark_vlms.json")
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".heic"}

# Modelos a testar — remover os que não estiverem disponíveis
MODELS_TO_RUN = ["gpt4o", "llava", "qwen"]

SEPARATOR = "─" * 60


# ---------------------------------------------------------------------------
# Verificação de recursos
# ---------------------------------------------------------------------------
def check_resources() -> dict:
    """Verifica RAM, GPU e dependências disponíveis."""
    info = {"ram_gb": 0, "mps": False, "cuda": False, "bitsandbytes": False}
    try:
        import psutil
        info["ram_gb"] = round(psutil.virtual_memory().available / 1e9, 1)
    except ImportError:
        pass
    try:
        import torch
        info["mps"] = torch.backends.mps.is_available()
        info["cuda"] = torch.cuda.is_available()
        if info["cuda"]:
            info["gpu_name"] = torch.cuda.get_device_name(0)
            info["gpu_vram_gb"] = round(
                torch.cuda.get_device_properties(0).total_memory / 1e9, 1
            )
    except ImportError:
        pass
    try:
        import bitsandbytes  # noqa: F401
        info["bitsandbytes"] = True
    except ImportError:
        pass
    return info


def print_resource_report(info: dict, models: list[str]):
    print("\n  Recursos do sistema:")
    print(f"    RAM livre   : {info['ram_gb']} GB")
    print(f"    CUDA        : {'Sim — ' + info.get('gpu_name','') + ' (' + str(info.get('gpu_vram_gb','?')) + ' GB)' if info['cuda'] else 'Não'}")
    print(f"    MPS (Apple) : {'Sim' if info['mps'] else 'Não'}")
    print(f"    bitsandbytes: {'Sim (4-bit possível)' if info['bitsandbytes'] else 'Não'}")

    warnings = []
    has_gpu = info["cuda"] or info["mps"]
    if "llava" in models or "qwen" in models:
        if not has_gpu and info["ram_gb"] < 12:
            warnings.append(
                "  AVISO: LLaVA/Qwen-VL precisam de ~14 GB RAM ou GPU.\n"
                "  Com menos recursos, o processo pode falhar ou demorar horas.\n"
                "  Considera correr no Google Colab (GPU T4 gratuita)."
            )
        elif not has_gpu and not info["bitsandbytes"]:
            warnings.append(
                "  AVISO: Sem GPU detectada. LLaVA/Qwen correrão em CPU — muito lento.\n"
                "  Instala bitsandbytes para quantização 4-bit: pip install bitsandbytes"
            )
    for w in warnings:
        print(f"\n{w}")


# ---------------------------------------------------------------------------
# Carregamento de imagens
# ---------------------------------------------------------------------------
def load_test_images() -> list[Path]:
    if not IMAGES_DIR.exists():
        print(f"ERRO: Pasta '{IMAGES_DIR}' não encontrada.")
        sys.exit(1)
    images = sorted([f for f in IMAGES_DIR.iterdir() if f.suffix.lower() in SUPPORTED])
    if not images:
        print(f"ERRO: Nenhuma imagem encontrada em '{IMAGES_DIR}'.")
        sys.exit(1)
    return images


# ---------------------------------------------------------------------------
# VLM runner
# ---------------------------------------------------------------------------
def run_vlm_on_image(
    model_name: str,
    img_path: Path,
    ocr_text: str,
) -> dict:
    """Corre um VLM numa imagem e retorna resultado estruturado."""
    import cv2
    from src.vlm.vlm import get_vlm

    image = cv2.imread(str(img_path))
    if image is None:
        return _error_result(model_name, img_path.name, "Falha ao carregar imagem")

    start = time.perf_counter()
    try:
        vlm = get_vlm(model_name)
        output = vlm.classify(image, ocr_text)
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        return {
            "imagem": img_path.name,
            "modelo": model_name,
            "codigo": output.base_term_code,
            "termo": output.base_term_label,
            "facetas": json.dumps(output.facets, ensure_ascii=False),
            "num_facetas": len(output.facets),
            "confianca": output.confidence,
            "raciocinio": output.reasoning[:500],
            "tempo_ms": elapsed,
            "erro": None,
        }
    except Exception as e:
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        logging.warning(f"[{model_name}] Erro em {img_path.name}: {e}")
        return _error_result(model_name, img_path.name, str(e), elapsed)


def _error_result(model, imagem, erro, tempo_ms=0.0):
    return {
        "imagem": imagem,
        "modelo": model,
        "codigo": "ERROR",
        "termo": "",
        "facetas": "{}",
        "num_facetas": 0,
        "confianca": "low",
        "raciocinio": erro,
        "tempo_ms": tempo_ms,
        "erro": erro,
    }


# ---------------------------------------------------------------------------
# OCR (EasyOCR como fallback rápido para o benchmark VLM)
# ---------------------------------------------------------------------------
def extract_ocr_text(img_path: Path) -> str:
    try:
        import cv2
        from src.data.preprocessing import preprocess_image, load_image
        from src.ocr.engine import get_engine
        image = load_image(str(img_path))
        processed = preprocess_image(image)
        engine = get_engine(os.environ.get("IDRISK2_OCR_ENGINE", "easyocr"))
        results = engine.extract(processed)
        return " ".join(r.text for r in results if r.text.strip())
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Métricas de comparação
# ---------------------------------------------------------------------------
def compute_agreement(results: list[dict]) -> dict:
    """
    Calcula taxa de concordância entre modelos para o mesmo código base.
    Para cada imagem, verifica se os modelos concordam no código FoodEx2.
    """
    from collections import defaultdict
    by_image = defaultdict(list)
    for r in results:
        if not r["erro"]:
            by_image[r["imagem"]].append(r["codigo"])

    agreement = {}
    for img, codes in by_image.items():
        unique = set(codes)
        agreement[img] = {
            "codes": codes,
            "agree": len(unique) == 1,
            "num_unique": len(unique),
        }

    total = len(agreement)
    agreed = sum(1 for v in agreement.values() if v["agree"])
    return {
        "by_image": agreement,
        "total_images": total,
        "full_agreement": agreed,
        "agreement_rate": round(agreed / total * 100, 1) if total else 0,
    }


def compute_model_stats(results: list[dict]) -> dict:
    """Estatísticas por modelo: sucesso, média de facetas, tempo médio, confiança."""
    from collections import defaultdict
    stats = defaultdict(lambda: {
        "total": 0, "sucesso": 0, "erros": 0,
        "facetas": [], "tempo_ms": [], "high": 0, "medium": 0, "low": 0,
    })
    for r in results:
        m = r["modelo"]
        stats[m]["total"] += 1
        if r["erro"]:
            stats[m]["erros"] += 1
        else:
            stats[m]["sucesso"] += 1
            stats[m]["facetas"].append(r["num_facetas"])
            stats[m]["tempo_ms"].append(r["tempo_ms"])
            conf = r.get("confianca", "low")
            if conf in stats[m]:
                stats[m][conf] += 1

    summary = {}
    for model, s in stats.items():
        summary[model] = {
            "total": s["total"],
            "sucesso": s["sucesso"],
            "erros": s["erros"],
            "media_facetas": round(sum(s["facetas"]) / len(s["facetas"]), 1) if s["facetas"] else 0,
            "media_tempo_s": round(sum(s["tempo_ms"]) / len(s["tempo_ms"]) / 1000, 1) if s["tempo_ms"] else 0,
            "high_pct": round(s["high"] / s["sucesso"] * 100, 1) if s["sucesso"] else 0,
            "medium_pct": round(s["medium"] / s["sucesso"] * 100, 1) if s["sucesso"] else 0,
            "low_pct": round(s["low"] / s["sucesso"] * 100, 1) if s["sucesso"] else 0,
        }
    return summary


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
def save_results(results: list[dict], agreement: dict, stats: dict):
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    # CSV com todos os resultados individuais
    fields = ["imagem", "modelo", "codigo", "termo", "facetas",
              "num_facetas", "confianca", "tempo_ms", "erro", "raciocinio"]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in results:
            writer.writerow({k: r.get(k, "") for k in fields})

    # JSON com tudo incluindo métricas
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "results": results,
            "agreement": agreement,
            "model_stats": stats,
        }, f, indent=2, ensure_ascii=False)

    print(f"\n  Resultados guardados em:")
    print(f"    {OUTPUT_CSV}")
    print(f"    {OUTPUT_JSON}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print(f"\n{'═' * 60}")
    print("  IDRISK2 — Benchmark Comparativo VLMs (Secção 4.4)")
    print(f"{'═' * 60}")

    resources = check_resources()
    print_resource_report(resources, MODELS_TO_RUN)

    # Filtra modelos com API key em falta
    models = list(MODELS_TO_RUN)
    if "gpt4o" in models and not os.environ.get("OPENAI_API_KEY"):
        print("\n  AVISO: OPENAI_API_KEY não definida — a remover gpt4o.")
        models.remove("gpt4o")
    if not models:
        print("  Nenhum modelo disponível. Verifica as variáveis de ambiente.")
        sys.exit(1)

    images = load_test_images()
    print(f"\n  Modelos    : {', '.join(models)}")
    print(f"  Imagens    : {len(images)}")
    print(f"  Total runs : {len(models) * len(images)}\n")

    # Pré-extrair OCR uma vez por imagem (partilhado entre VLMs)
    print("  A extrair texto OCR de todas as imagens...")
    ocr_cache = {}
    for img in images:
        ocr_cache[img.name] = extract_ocr_text(img)
    print(f"  OCR concluído.\n")

    all_results = []
    total_runs = len(models) * len(images)
    run_idx = 0

    for model in models:
        print(f"\n{'═' * 60}")
        print(f"  MODELO: {model.upper()}")
        print(f"{'═' * 60}")

        model_ok = True
        for img in images:
            run_idx += 1
            print(f"  [{run_idx}/{total_runs}] {img.name} ...", end=" ", flush=True)

            if not model_ok:
                result = _error_result(model, img.name, "Modelo indisponível")
                all_results.append(result)
                print("SKIP")
                continue

            result = run_vlm_on_image(model, img, ocr_cache.get(img.name, ""))
            all_results.append(result)

            if result["erro"]:
                # Se erro de memória / import, não tentar mais imagens com este modelo
                if any(k in result["erro"] for k in ("CUDA", "memory", "OOM", "ImportError", "ModuleNotFoundError")):
                    model_ok = False
                print(f"ERRO — {result['erro'][:60]}")
            else:
                conf_icon = {"high": "✓", "medium": "~", "low": "?"}.get(result["confianca"], "?")
                print(f"{conf_icon}  {result['codigo']} | {result['termo'][:30]} | {result['num_facetas']} facetas | {result['tempo_ms']/1000:.1f}s")

    # Métricas
    agreement = compute_agreement(all_results)
    stats = compute_model_stats(all_results)

    # Resumo
    print(f"\n{'═' * 60}")
    print("  ESTATÍSTICAS POR MODELO")
    print(f"{'═' * 60}")
    print(f"  {'Modelo':<12} {'Sucesso':>8} {'Facetas':>8} {'Tempo(s)':>9} {'High%':>7} {'Med%':>6} {'Low%':>6}")
    print(f"  {'─'*12} {'─'*8} {'─'*8} {'─'*9} {'─'*7} {'─'*6} {'─'*6}")
    for m, s in stats.items():
        print(f"  {m:<12} {s['sucesso']:>5}/{s['total']:<2} {s['media_facetas']:>8.1f} {s['media_tempo_s']:>9.1f} {s['high_pct']:>6.0f}% {s['medium_pct']:>5.0f}% {s['low_pct']:>5.0f}%")

    print(f"\n{'═' * 60}")
    print("  CONCORDÂNCIA ENTRE MODELOS")
    print(f"{'═' * 60}")
    print(f"  Taxa de concordância total: {agreement['agreement_rate']}%")
    print(f"  ({agreement['full_agreement']}/{agreement['total_images']} imagens com código idêntico em todos os modelos)")

    # Top discordâncias
    discordant = [
        (img, v) for img, v in agreement["by_image"].items()
        if not v["agree"] and len(v["codes"]) > 1
    ]
    if discordant:
        print(f"\n  Imagens com discordância ({len(discordant)}):")
        for img, v in discordant[:10]:
            print(f"    {img:<35} {' vs '.join(v['codes'])}")

    save_results(all_results, agreement, stats)
    print(f"\n{'═' * 60}\n")


if __name__ == "__main__":
    main()

"""
Script de teste do pipeline IDRISK2.
Classifica todas as imagens em images/test/ e imprime os resultados.
Executa: python test_pipeline.py
"""
import os
import time
import logging
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.WARNING,  # só warnings e erros para não poluir o output
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

from pipeline import IDRISK2Pipeline
from src.security.security import User, Role

IMAGES_DIR = Path("images/test")
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".heic"}

SEPARATOR = "─" * 60


def main():
    print(f"\n{'═' * 60}")
    print("  IDRISK2 — Teste do Pipeline de Classificação FoodEx2")
    print(f"{'═' * 60}\n")

    print("A inicializar pipeline (carrega knowledge base)...")
    pipeline = IDRISK2Pipeline.from_env()

    user = User(
        user_id="u001",
        username="inspector_teste",
        role=Role.INSPECTOR,
        created_at="2026-05-28T00:00:00",
    )

    images = sorted([
        f for f in IMAGES_DIR.iterdir()
        if f.suffix.lower() in SUPPORTED
    ])

    if not images:
        print(f"Nenhuma imagem encontrada em {IMAGES_DIR}/")
        return

    print(f"Imagens encontradas: {len(images)}\n")

    results = []
    for i, img_path in enumerate(images, 1):
        print(f"{SEPARATOR}")
        print(f"[{i}/{len(images)}] {img_path.name}")
        print(SEPARATOR)

        start = time.time()
        try:
            result = pipeline.classify(
                image_path=str(img_path),
                user=user,
                retain_image=False,
            )
            elapsed = time.time() - start
            c = result.classification

            conf_str = c.confidence.value if hasattr(c.confidence, "value") else str(c.confidence)

            print(f"  Código FoodEx2 : {c.base_term_code}")
            print(f"  Termo          : {c.base_term_label}")
            print(f"  Confiança      : {conf_str.upper()}")
            print(f"  Revisão humana : {'SIM ⚠' if c.requires_human_review else 'Não'}")
            print(f"  Tempo          : {elapsed:.1f}s")
            if c.facets:
                print(f"  Facetas        : {', '.join(str(f) for f in c.facets)}")
            print(f"\n  Raciocínio:\n  {c.reasoning[:300]}{'...' if len(c.reasoning) > 300 else ''}")

            results.append({
                "imagem": img_path.name,
                "codigo": c.base_term_code,
                "termo": c.base_term_label,
                "confianca": conf_str,
                "revisao_humana": c.requires_human_review,
                "tempo": round(elapsed, 1),
                "erro": None,
            })

        except Exception as e:
            elapsed = time.time() - start
            print(f"  ERRO: {e}")
            results.append({
                "imagem": img_path.name,
                "codigo": "—",
                "termo": "—",
                "confianca": "—",
                "revisao_humana": "—",
                "tempo": round(elapsed, 1),
                "erro": str(e),
            })

        print()

    # Resumo final
    print(f"\n{'═' * 60}")
    print("  RESUMO")
    print(f"{'═' * 60}")
    print(f"  {'Imagem':<30} {'Código':<10} {'Confiança':<10} {'Rev.'}")
    print(f"  {'─'*30} {'─'*10} {'─'*10} {'─'*5}")
    for r in results:
        rev = "SIM" if r["revisao_humana"] is True else ("Não" if r["revisao_humana"] is False else "—")
        print(f"  {r['imagem']:<30} {r['codigo']:<10} {r['confianca']:<10} {rev}")
    print(f"\n  Total: {len(results)} imagens | "
          f"Sucesso: {sum(1 for r in results if not r['erro'])} | "
          f"Erros: {sum(1 for r in results if r['erro'])}")
    print(f"{'═' * 60}\n")


if __name__ == "__main__":
    main()

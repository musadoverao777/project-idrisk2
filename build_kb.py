"""
Script para construir a knowledge base FoodEx2 a partir dos documentos EFSA.
Executa: python build_kb.py
"""
import logging
import os
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Garantir que as pastas de cache existem antes de qualquer import do LlamaIndex
for cache_var in ("LLAMA_INDEX_CACHE_DIR", "TRANSFORMERS_CACHE", "HF_HOME"):
    cache_path = os.getenv(cache_var)
    if cache_path:
        Path(cache_path).mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

from src.rag.knowledge_base import build_knowledge_base

DOCS_DIR = "./docs/efsa"
PERSIST_DIR = "./data/kb"

if __name__ == "__main__":
    print("\n=== IDRISK2 — Construção da Knowledge Base ===\n")
    print(f"Documentos: {DOCS_DIR}")
    print(f"Destino:    {PERSIST_DIR}\n")

    start = time.time()

    index = build_knowledge_base(
        docs_dir=DOCS_DIR,
        persist_dir=PERSIST_DIR,
        chunking_strategy="semantic",
        force_rebuild=False,
    )

    elapsed = time.time() - start
    print(f"\nKnowledge base construída em {elapsed:.1f}s")
    print("Pronta para utilização pelo pipeline.")

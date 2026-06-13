# IDRISK2 — Backend container (Hugging Face Spaces / qualquer host Docker)
# Expõe a API FastAPI na porta 7860 (padrão do HF Spaces).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/app/.cache/transformers \
    LLAMA_INDEX_CACHE_DIR=/app/.cache/llama_index \
    IDRISK2_DATA_DIR=/app/data \
    IDRISK2_DOCS_DIR=/app/docs/efsa \
    IDRISK2_OCR_ENGINE=easyocr \
    IDRISK2_EMBEDDING_PROVIDER=openai \
    IDRISK2_CORS_ORIGINS=*

# Dependências de sistema: OpenCV (libGL/glib), Tesseract (OCR alternativo)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependências Python primeiro (camada cacheável).
# Removemos paddleocr (requer paddlepaddle, não usado: motor = easyocr/tesseract).
COPY requirements.txt /app/requirements.txt
RUN sed '/paddleocr/d' requirements.txt > requirements-serve.txt \
    && pip install --upgrade pip \
    && pip install -r requirements-serve.txt

# Código da aplicação
COPY api /app/api
COPY src /app/src
COPY pipeline.py build_kb.py /app/
COPY docs /app/docs

# Pastas de runtime
RUN mkdir -p /app/data /app/.cache

EXPOSE 7860

# A base de conhecimento (Chroma) é construída no 1.º arranque a partir de
# docs/efsa (embeddings OpenAI). Os modelos do EasyOCR/ColBERT descarregam
# no 1.º pedido. Define os secrets OPENAI_API_KEY, ANTHROPIC_API_KEY e
# IDRISK2_AUDIT_KEY nas definições do Space.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "7860"]

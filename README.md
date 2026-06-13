---
title: IDRISK2
emoji: 🍎
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# IDRISK2

Pipeline de classificação automática de produtos alimentares na taxonomia **EFSA FoodEx2** a partir de imagens de rótulos, desenvolvido no contexto de dissertação de mestrado/doutoramento.

O sistema combina pré-processamento de imagem, OCR multilingue, modelos visão-linguagem (VLM), recuperação aumentada por geração (RAG) avançado e camada de segurança e conformidade GDPR / EU AI Act.

---

## Índice

- [Visão Geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Tecnologias](#tecnologias)
- [Estrutura do Projeto](#estrutura-do-projeto)
- [Instalação](#instalação)
- [Configuração](#configuração)
- [Utilização](#utilização)
- [Saídas](#saídas)
- [Segurança e Conformidade](#segurança-e-conformidade)
- [Referência à Dissertação](#referência-à-dissertação)

---

## Visão Geral

O IDRISK2 recebe uma imagem de rótulo de produto alimentar e produz uma classificação estruturada segundo a taxonomia FoodEx2 da EFSA, incluindo código base, rótulo, facetas, raciocínio e nível de confiança.

Quando a confiança é `low` ou `medium`, o sistema sinaliza automaticamente a classificação para revisão humana, tornando-o adequado para contextos regulatórios de inspeção alimentar com IA explicável.

**Fluxo principal:**

```
Imagem → Validação → Pré-processamento → OCR → VLM → RAG → Classificação FoodEx2
```

---

## Arquitetura

O pipeline (`pipeline.py`) orquestra seis etapas:

| Etapa | Descrição |
|-------|-----------|
| **Validação** | Verificação de tamanho, tipo MIME e magic bytes |
| **Pré-processamento** | Redimensionamento, denoising, deskewing, CLAHE |
| **OCR** | Extração de texto com motor configurável (PaddleOCR, EasyOCR ou Tesseract) |
| **VLM** | Análise multimodal imagem + texto (GPT-4o, LLaVA ou Qwen-VL) |
| **RAG** | Recuperação híbrida (densa + BM25), reescrita de query, HyDE, fusão RRF, rerank ColBERT |
| **Geração** | Classificação FoodEx2 fundamentada + auditoria |

Após a classificação, aplica-se minimização de dados GDPR: a imagem original é descartada por defeito, mantendo apenas o hash SHA-256, o texto OCR e o resultado.

---

## Tecnologias

| Área | Tecnologias |
|------|-------------|
| Linguagem | Python 3.10+ |
| Visão / imagem | OpenCV, Pillow, pillow-heif, NumPy |
| OCR | PaddleOCR, EasyOCR, Tesseract (pytesseract) |
| VLM | GPT-4o (OpenAI), LLaVA, Qwen-VL (HuggingFace + PyTorch) |
| Embeddings | `BAAI/bge-m3` (sentence-transformers) |
| RAG | LlamaIndex, ChromaDB, BM25, ColBERT rerank |
| LLM de geração | OpenAI `gpt-4o` via `llama-index-llms-openai` |
| Avaliação OCR | `editdistance` (CER/WER) |
| Utilitários | `tqdm`, `python-dotenv`, `python-dateutil` |

---

## Estrutura do Projeto

```
idrisk2/
├── pipeline.py                 # Orquestrador principal
├── requirements.txt            # Dependências Python
├── api/                        # REST API FastAPI (frontend MVP)
│   ├── main.py
│   ├── schemas.py
│   └── serializers.py
├── frontend/                   # Interface React + TypeScript + Tailwind
└── src/
    ├── __init__.py
    ├── common/
    │   └── types.py            # Tipos partilhados (Confidence, REVIEW_TRIGGER_LEVELS)
    ├── data/
    │   └── preprocessing.py    # Ingestão de imagem, qualidade, ROI, dataset anotado
    ├── ocr/
    │   └── engine.py           # Três motores OCR, benchmark, métricas CER/WER
    ├── vlm/
    │   └── vlm.py              # GPT-4o, LLaVA, Qwen-VL com prompts FoodEx2
    ├── rag/
    │   ├── knowledge_base.py   # Índice Chroma a partir de documentos EFSA
    │   ├── retrieval.py        # Recuperação híbrida avançada
    │   └── generation.py       # Geração da classificação + registo auditável
    └── security/
        └── security.py         # RBAC, logs HMAC, GDPR, retenção de dados
```

Em runtime, o pipeline cria automaticamente a seguinte estrutura em `IDRISK2_DATA_DIR`:

```
{DATA_DIR}/
├── kb/                         # Índice Chroma + manifest.json
├── audit/
│   ├── chain/                  # Logs HMAC encadeados (tamper-evident)
│   └── generation/             # Registos por classificação
└── records/                    # Registos minimizados em JSON
```

---

## Instalação

### Pré-requisitos

- Python 3.10+
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) instalado no sistema (se usar motor `tesseract`)
- GPU recomendada para EasyOCR, PaddleOCR, LLaVA e Qwen-VL
- Documentos EFSA FoodEx2 (PDF/TXT/MD) num diretório local

### Passos

```bash
# Clonar / entrar no repositório
cd idrisk2

# Criar ambiente virtual
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Instalar dependências
pip install -r requirements.txt
```

> A primeira execução pode descarregar modelos de grande dimensão (embeddings BGE-M3, modelos OCR, VLMs locais).

---

## Configuração

Crie um ficheiro `.env` na raiz do projeto com as seguintes variáveis:

### Obrigatórias

```env
IDRISK2_AUDIT_KEY=<chave-hmac-secreta>
IDRISK2_DATA_DIR=/caminho/para/dados
IDRISK2_DOCS_DIR=/caminho/para/documentos-efsa
```

| Variável | Descrição |
|----------|-----------|
| `IDRISK2_AUDIT_KEY` | Chave HMAC para cadeia de logs de auditoria tamper-evident |
| `IDRISK2_DATA_DIR` | Diretório base para índice, auditoria e registos |
| `IDRISK2_DOCS_DIR` | Diretório com documentos FoodEx2 da EFSA (necessário para construir a knowledge base) |

### Opcionais

```env
OPENAI_API_KEY=sk-...
IDRISK2_LOG_LEVEL=INFO
IDRISK2_MAX_RETRIES=2
```

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `OPENAI_API_KEY` | — | Necessária se usar VLM `gpt4o` ou LLM `gpt-4o` |
| `IDRISK2_LOG_LEVEL` | `INFO` | Nível de logging |
| `IDRISK2_MAX_RETRIES` | `2` | Número de tentativas em caso de erro |

### Parâmetros do pipeline (`PipelineConfig`)

| Parâmetro | Padrão | Opções |
|-----------|--------|--------|
| `ocr_engine` | `paddleocr` | `tesseract`, `easyocr`, `paddleocr` |
| `vlm_model` | `gpt4o` | `gpt4o`, `llava`, `qwen` |
| `llm_model` | `gpt-4o` | Qualquer modelo OpenAI compatível |
| `chunking_strategy` | `semantic` | `semantic`, `fixed` |
| `use_hyde` | `True` | Ativa HyDE na recuperação |
| `use_query_rewrite` | `True` | Ativa reescrita de query |

---

## Utilização

O IDRISK2 pode ser utilizado como **biblioteca Python** ou através do **frontend web** (MVP).

### Frontend web (MVP)

Interface React para upload de imagem e visualização da classificação FoodEx2.

**Pré-requisitos:** `.env` configurado, knowledge base construída, dependências Python e Node.js instaladas.

```bash
# Terminal 1 — API FastAPI (carrega modelos na 1.ª execução; pode demorar ~30s)
source .venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --reload --port 8000

# Terminal 2 — Frontend React
cd frontend
npm install
npm run dev
```

Abrir [http://localhost:5173](http://localhost:5173). O frontend faz proxy de `/api` para `http://localhost:8000`.

**Endpoints da API:**

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/api/health` | Estado do pipeline |
| `POST` | `/api/classify` | Upload de imagem (`multipart/form-data`, campo `file`) |

Teste manual com curl:

```bash
curl http://localhost:8000/api/health
curl -X POST http://localhost:8000/api/classify \
  -F "file=@images/test/sanduiche.jpg"
```

### Biblioteca Python

O entry point principal continua a ser `IDRISK2Pipeline`.

### Exemplo básico

```python
from pipeline import IDRISK2Pipeline
from src.security.security import User, Role

# Inicializar pipeline a partir de variáveis de ambiente
pipeline = IDRISK2Pipeline.from_env()

# Definir utilizador autenticado
user = User(
    user_id="u001",
    username="inspector1",
    role=Role.INSPECTOR,
    created_at="2026-05-26T00:00:00",
)

# Classificar um rótulo
result = pipeline.classify(
    image_path="/caminho/para/rotulo.jpg",
    user=user,
    retain_image=False,  # GDPR: descarta imagem após processamento
)

# Aceder ao resultado
print(result.classification.base_term_code)
print(result.classification.base_term_label)
print(result.classification.confidence)
print(result.classification.requires_human_review)
```

### Benchmark de motores OCR

```python
# Requer permissão Role.ADMINISTRATOR ou Role.AUDITOR
results = pipeline.benchmark_ocr_engines(
    test_images=[...],
    user=admin_user,
)
```

---

## Saídas

### `FoodEx2Classification`

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `base_term_code` | `str` | Código FoodEx2 (ex.: `A0CKL`) |
| `base_term_label` | `str` | Rótulo FoodEx2 |
| `facets` | `list` | Facetas aplicáveis |
| `reasoning` | `str` | Raciocínio gerado pelo modelo |
| `confidence` | `Confidence` | `high`, `medium` ou `low` |
| `requires_human_review` | `bool` | `True` se confiança não for `high` |
| `retrieved_sources` | `list` | Fontes EFSA utilizadas |
| `retrieved_chunk_ids` | `list` | IDs dos chunks recuperados |
| `classification_id` | `str` | ID único da classificação |
| `timestamp` | `str` | Data/hora ISO 8601 |

### `PipelineResult`

Encapsula `FoodEx2Classification` e inclui adicionalmente `ocr_text`, `vlm_output`, `rag_context`, tempos de execução por etapa e metadados da sessão.

---

## Segurança e Conformidade

### Controlo de acesso (RBAC)

| Papel | Permissões |
|-------|-----------|
| `INSPECTOR` | Classificar imagens |
| `SUPERVISOR` | Classificar + rever resultados |
| `ADMINISTRATOR` | Acesso total + benchmark |
| `AUDITOR` | Acesso total + auditoria |

### Auditoria

Os logs de auditoria são encadeados com HMAC (`AuditLogger`), tornando-os à prova de adulteração. Cada classificação gera um registo individual em `{DATA_DIR}/audit/generation/`.

### GDPR

- Imagens descartadas por defeito após processamento (`retain_image=False`).
- Mantém apenas: hash SHA-256 da imagem, texto OCR extraído e resultado da classificação.
- Política de retenção de dados configurável por papel.

### EU AI Act

O sistema foi desenhado para sistemas de IA de alto risco: confiança `low` ou `medium` aciona `requires_human_review=True`, garantindo supervisão humana antes de qualquer decisão regulatória.

---

## Referência à Dissertação

A arquitetura do projeto segue a estrutura metodológica da dissertação:

| Secção | Módulo | Tema |
|--------|--------|------|
| 4.2 | `src/data/preprocessing.py` | Aquisição e pré-processamento de imagem |
| 4.3 | `src/ocr/engine.py` | Reconhecimento ótico de caracteres |
| 4.4 | `src/vlm/vlm.py` | Modelos visão-linguagem |
| 4.5.1 | `src/rag/knowledge_base.py` | Base de conhecimento FoodEx2 |
| 4.5.2 | `src/rag/retrieval.py` | Recuperação híbrida avançada |
| 4.5.3 | `src/rag/generation.py` | Geração da classificação |
| 4.6 | `src/security/security.py` | Segurança, privacidade e auditoria |

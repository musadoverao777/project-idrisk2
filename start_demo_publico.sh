#!/usr/bin/env bash
#
# IDRISK2 — Demo PÚBLICA (backend + frontend + túnel partilhável)
# Uso:  ./start_demo_publico.sh
#
# Arranca a app local (API 8000 + frontend 5173) e cria um túnel HTTPS
# público com cloudflared, dando um link que o orientador pode abrir de
# qualquer dispositivo. A classificação corre REALMENTE no teu Mac.
#
# Requisitos: o link só funciona enquanto este script estiver a correr
# (Mac ligado, sem suspender). Carrega Ctrl+C para parar tudo.
#
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# --- 0. Garantir cloudflared -------------------------------------------------
if ! command -v cloudflared >/dev/null 2>&1; then
  echo "==> cloudflared não encontrado."
  if command -v brew >/dev/null 2>&1; then
    echo "==> A instalar via Homebrew..."
    brew install cloudflared
  else
    echo "ERRO: instala o cloudflared primeiro:"
    echo "   brew install cloudflared"
    echo "   (ou ver https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)"
    exit 1
  fi
fi

# --- 1. Backend --------------------------------------------------------------
if [ ! -x ".venv/bin/uvicorn" ] && [ ! -x ".venv/bin/python" ]; then
  echo "ERRO: .venv não encontrado em $ROOT/.venv"; exit 1
fi
echo "==> Backend (FastAPI) em http://localhost:8000 ..."
.venv/bin/uvicorn api.main:app --port 8000 > /tmp/idrisk2_backend.log 2>&1 &
BACKEND_PID=$!

FRONTEND_PID=""; CF_PID=""
cleanup() {
  echo ""; echo "==> A encerrar..."
  for pid in "$CF_PID" "$FRONTEND_PID" "$BACKEND_PID"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

echo "==> A inicializar pipeline (1º arranque constrói a KB; ver /tmp/idrisk2_backend.log)..."
for i in $(seq 1 120); do
  if curl -sf http://localhost:8000/api/health 2>/dev/null | grep -q '"pipeline_ready":true'; then
    echo "==> Pipeline PRONTO ✅"; break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "ERRO: backend terminou. Log:"; tail -n 30 /tmp/idrisk2_backend.log; exit 1
  fi
  sleep 5; echo "   ... a inicializar (${i}x5s)"
done

# --- 2. Frontend -------------------------------------------------------------
echo "==> Frontend (Vite) em http://localhost:5173 ..."
( cd frontend && npm run dev > /tmp/idrisk2_frontend.log 2>&1 ) &
FRONTEND_PID=$!
for i in $(seq 1 30); do
  curl -sf http://localhost:5173 >/dev/null 2>&1 && { echo "==> Frontend PRONTO ✅"; break; }
  sleep 2
done

# --- 3. Túnel público --------------------------------------------------------
echo "==> A criar túnel público (cloudflared)..."
cloudflared tunnel --url http://localhost:5173 > /tmp/idrisk2_tunnel.log 2>&1 &
CF_PID=$!

PUBLIC_URL=""
for i in $(seq 1 30); do
  PUBLIC_URL=$(grep -Eo 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/idrisk2_tunnel.log 2>/dev/null | head -1 || true)
  [ -n "$PUBLIC_URL" ] && break
  sleep 2
done

echo ""
echo "============================================================"
if [ -n "$PUBLIC_URL" ]; then
  echo "  LINK PÚBLICO (partilha com o orientador):"
  echo "      $PUBLIC_URL"
else
  echo "  Túnel a arrancar — vê o URL em: tail -f /tmp/idrisk2_tunnel.log"
fi
echo ""
echo "  Local:    http://localhost:5173"
echo "  Login demo: 'inspector', 'supervisor', 'administrator' ou 'auditor'"
echo "  Mantém esta janela aberta. Ctrl+C para parar."
echo "============================================================"

wait "$FRONTEND_PID"

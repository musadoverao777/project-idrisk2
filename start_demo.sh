#!/usr/bin/env bash
#
# IDRISK2 — Arranque da demo local (backend + frontend)
# Uso:  ./start_demo.sh
#
# Arranca a API FastAPI (porta 8000) e o frontend Vite (porta 5173).
# Na PRIMEIRA execução o backend constrói a base de conhecimento (KB) a
# partir dos PDFs da EFSA e descarrega os modelos do EasyOCR — isto pode
# demorar alguns minutos. Arranca a demo com antecedência para "aquecer".
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# --- Backend -----------------------------------------------------------------
if [ ! -x ".venv/bin/python" ]; then
  echo "ERRO: .venv não encontrado em $ROOT/.venv"
  echo "Cria o ambiente e instala dependências: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "==> A arrancar backend (FastAPI) em http://localhost:8000 ..."
.venv/bin/uvicorn api.main:app --port 8000 > /tmp/idrisk2_backend.log 2>&1 &
BACKEND_PID=$!

cleanup() {
  echo ""
  echo "==> A encerrar (backend PID $BACKEND_PID, frontend PID ${FRONTEND_PID:-})..."
  kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# --- Esperar que o pipeline fique pronto (constrói KB no 1º arranque) ---------
echo "==> A inicializar pipeline (pode construir a KB no 1º arranque; ver /tmp/idrisk2_backend.log)..."
for i in $(seq 1 120); do
  if curl -sf http://localhost:8000/api/health 2>/dev/null | grep -q '"pipeline_ready":true'; then
    echo "==> Pipeline PRONTO ✅"
    break
  fi
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "ERRO: o backend terminou. Últimas linhas do log:"; tail -n 30 /tmp/idrisk2_backend.log
    exit 1
  fi
  sleep 5
  echo "   ... ainda a inicializar (${i}x5s). Log: tail -f /tmp/idrisk2_backend.log"
done

# --- Frontend ----------------------------------------------------------------
echo "==> A arrancar frontend (Vite) em http://localhost:5173 ..."
cd frontend
npm run dev &
FRONTEND_PID=$!

echo ""
echo "============================================================"
echo "  IDRISK2 demo a correr:"
echo "    Frontend:  http://localhost:5173   (abre isto no browser)"
echo "    API:       http://localhost:8000/api/health"
echo "    Login demo: usa 'inspector', 'supervisor', 'administrator' ou 'auditor'"
echo "  Carrega Ctrl+C para parar tudo."
echo "============================================================"

wait "$FRONTEND_PID"

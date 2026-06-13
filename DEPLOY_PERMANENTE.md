# IDRISK2 — Deploy permanente (Vercel + Hugging Face Spaces)

Objetivo: link sempre online para o orientador testar **sem o teu Mac ligado**.
Frontend na **Vercel**, backend num **HF Space** (Docker, CPU grátis, 16 GB RAM).

> Faz isto com calma, depois da reunião. Para hoje, usa o `start_demo_publico.sh`.

---

## 1) Backend no Hugging Face Spaces

1. Cria conta em https://huggingface.co e um **Space** novo:
   *New Space* → SDK **Docker** → nome `idrisk2`.

2. No Space, cria um `README.md` com este cabeçalho (necessário ao HF):

   ```yaml
   ---
   title: IDRISK2
   sdk: docker
   app_port: 7860
   ---
   ```

3. Envia o backend (a pasta `idrisk2/` já tem `Dockerfile` e `.dockerignore`).
   Via git:

   ```bash
   cd idrisk2
   git remote add space https://huggingface.co/spaces/<o-teu-user>/idrisk2
   git push space main
   ```

   (ou arrasta os ficheiros pela interface do Space: `Dockerfile`, `api/`,
   `src/`, `pipeline.py`, `build_kb.py`, `docs/`).

4. **Settings → Secrets** do Space, adiciona (copia os valores do teu `.env`):
   - `OPENAI_API_KEY`
   - `ANTHROPIC_API_KEY`
   - `IDRISK2_AUDIT_KEY`

5. O build demora ~10–15 min. Quando acabar, testa:
   `https://<o-teu-user>-idrisk2.hf.space/api/health` → deve dar `pipeline_ready: true`.

   > 1.º arranque constrói a KB (embeddings OpenAI) e descarrega modelos —
   > a primeira classificação pode demorar 1–2 min. Depois fica rápido.

---

## 2) Frontend na Vercel

Opção A — **CLI** (a partir de `idrisk2/frontend`):

```bash
npm i -g vercel
vercel        # segue o login no browser; aceita as predefinições (Vite)
vercel --prod
```

Opção B — **GitHub**: faz push do frontend para um repo e em vercel.com
*Add New → Project → Import* o repo. Framework: Vite (deteta sozinho).

### Ligar o frontend ao backend
O frontend já lê o endereço do backend de forma flexível. Abre o link da
Vercel **uma vez** com o parâmetro `?api` a apontar para o Space:

```
https://<o-teu-projeto>.vercel.app/?api=https://<o-teu-user>-idrisk2.hf.space
```

Fica guardado no browser. Partilha esse link com o orientador.

(Alternativa fixa: define a variável `VITE_API_BASE` no projeto Vercel com o
URL do Space e volta a publicar.)

---

## Resumo dos ficheiros já preparados
- `Dockerfile`, `.dockerignore` — container do backend (porta 7860, CORS aberto).
- `api/main.py` — CORS configurável por `IDRISK2_CORS_ORIGINS`.
- `frontend/src/api/client.ts` — endereço do backend via `?api=` / `VITE_API_BASE`.
- `frontend/vite.config.ts` — aceita domínios de túnel (`allowedHosts`).

# IDRISK2 — Guia rápido da demo

## A) Demo LOCAL ao vivo (na apresentação)

No Terminal, dentro da pasta `idrisk2`:

```bash
./start_demo.sh
```

Depois abre **http://localhost:5173** no browser.
Login (demo): usa `inspector`, `supervisor`, `administrator` ou `auditor` como utilizador.

> **Importante:** no 1.º arranque o backend constrói a base de conhecimento
> (PDFs da EFSA, via embeddings OpenAI) e descarrega os modelos do EasyOCR.
> Isto demora alguns minutos. **Arranca a demo ~10 min antes** para "aquecer".
> Acompanha o progresso com: `tail -f /tmp/idrisk2_backend.log`

## B) Link PÚBLICO partilhável (o orientador testa no dispositivo dele)

```bash
./start_demo_publico.sh
```

O script imprime um link `https://....trycloudflare.com`. Partilha-o.
A classificação corre **realmente no teu Mac** — o link funciona enquanto este
script estiver a correr (Mac ligado, sem suspender). Carrega `Ctrl+C` para parar.

> 1.ª vez? Instala o túnel: `brew install cloudflared` (o script tenta fazê-lo).

## Verificação rápida

```bash
curl http://localhost:8000/api/health        # deve dar "pipeline_ready": true
```

## Notas

- Chaves de API (OpenAI/Anthropic) já estão no `.env`.
- Para parar tudo: `Ctrl+C` na janela do script.
- O endereço do backend no frontend é configurável: abrir o link com
  `?api=https://meu-backend` aponta para um backend remoto (útil para Vercel + HF Spaces).

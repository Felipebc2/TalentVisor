# Stack e alternativas avaliadas

> [Índice](../index.md) · [Visão geral](overview.md) · [Estrutura](layout.md) · [Decisões](../process/decisions.md)

## Avaliação de 5 alternativas a FastAPI + HTML

Critérios, com pesos para um MVP de 1 noite:
- tempo até a demo: 35%
- controle do painel (notas, evidência, log, botões): 20%
- jobs longos (STT de 1 a 3 min): 15%
- PDF e template: 10%
- separação entre as telas do candidato e do recrutador: 10%
- risco técnico: 10%

Notas de 1 a 5.

| # | Stack | Tempo | Painel | Jobs | PDF | Separação | Risco | **Total** |
|---|---|---|---|---|---|---|---|---|
| A | **Streamlit** | 5 | 3 | 2 | 3 | 2 | 4 | **3,55** |
| B | **Gradio (Blocks)** | 5 | 2 | 3 | 3 | 2 | 4 | **3,50** |
| C | **Django + HTMX** (admin como painel) | 3 | 4 | 3 | 4 | 4 | 4 | **3,50** |
| D | **FastAPI + React/Vite (SPA)** | 2 | 5 | 4 | 4 | 5 | 3 | **3,40** |
| E | **NiceGUI ou Reflex** (full-stack Python) | 4 | 4 | 3 | 3 | 3 | 2 | **3,40** |
| ★ | **FastAPI + Jinja2 + HTMX** (base) | 4 | 4 | 4 | 4 | 4 | 5 | **4,10** |

- **A. Streamlit**
  - Prós: protótipo em minutos, tem `st.file_uploader` e `st.video`, é só Python.
  - Contras: reexecuta o script a cada interação, então o STT longo precisaria de `st.cache_resource` e threads. Multipágina e papéis distintos ficam improvisados. É difícil expor uma API para o Langflow do Luan consumir.
- **B. Gradio**
  - Prós: componente de vídeo nativo e fila (`queue()`) para jobs longos, ideal para "upload → resultado".
  - Contras: o painel com tabela, decisão e log foge do modelo de "demo de ML". O layout é rígido.
- **C. Django + HTMX**
  - Prós: o admin dá a lista, o filtro e o detalhe do recrutador quase de graça, com ORM, migrations e auth.
  - Contras: boilerplate (settings, apps, migrations) que custa uma hora numa noite curta. É síncrono por padrão, então o job longo pede Celery ou thread.
- **D. FastAPI + React/Vite**
  - Prós: a melhor UX e a separação mais limpa entre API e UI.
  - Contras: dois builds, estado no cliente, CORS. É o dobro de código para a mesma tela.
- **E. NiceGUI / Reflex**
  - Prós: UI reativa só em Python; o NiceGUI roda sobre o FastAPI.
  - Contras: ecossistema jovem, debug pouco documentado e componentes de upload e vídeo com particularidades. É risco alto na véspera.

**Veredito: manter FastAPI + Jinja2 e somar HTMX (14 kB via CDN, sem build).**
O HTMX resolve o polling do status (`hx-trigger="every 3s"`) e os botões de decisão sem escrever JS.
A API JSON fica disponível de graça para o Langflow do Luan.
O plano B, se o front travar, é o Gradio, que reaproveita o mesmo `pipeline.py`.

## Stack final (frameworks por camada)

| Camada | Escolha | Por quê | Descartado (motivo) |
|---|---|---|---|
| **Execução** | **Docker + Compose** (1 serviço `app`, imagem `python:3.14-slim`, CPU) + **Makefile** | roda igual em qualquer máquina; `make up` e pronto | rodar direto no host (depende do ambiente de cada um) |
| Runtime | Python 3.14 + `uv` (dentro da imagem, venv em `/opt/venv`) | todos os wheels existem para cp314 (amd64 e arm64) | Poetry (mais lento) |
| Web | FastAPI + Uvicorn | async, upload multipart e OpenAPI grátis | Flask (sem tipos nem async) |
| Front | Jinja2 + **HTMX** + **Pico.css** (CDN) | HTML semântico já fica bonito e o HTMX dá interatividade sem build | Tailwind (precisa de build), React |
| **STT** | **faster-whisper** (CTranslate2) `large-v3-turbo`, int8 | **local** (a voz não vai para a nuvem), com VAD embutido e `word_timestamps`; decodifica o mp4 direto via PyAV | WhisperX (alinhamento e diarização desnecessários, precisa de token do HF); Whisper original (4× mais lento) |
| STT fallback | Groq `whisper-large-v3` em **chunks** de áudio com o fim do chunk anterior como `prompt` | o arquivo cabe nos 25 MB e o contexto se mantém entre os chunks; **desligado por padrão** (`ALLOW_CLOUD_STT=0`) porque envia voz | n/a |
| Áudio | `ffmpeg` CLI (só no fallback) | já instalado; `-f segment` faz o chunking | pydub (dependência extra) |
| Anonimização | dados pessoais conhecidos do CSV + regex + **spaCy `pt_core_news_md`** (NER local) | determinístico, local, rápido e mensurável (P/R) | Presidio (pesado); Ollama Qwen3 8B (não cabe nos 4 GB de VRAM junto com o STT) |
| LLM client | **`openai` SDK** com `base_url` | Groq **e** Gemini expõem endpoint compatível com OpenAI: um cliente só, com `response_format=json_schema` | `groq` + `google-genai` (duas APIs) |
| Validação | Pydantic v2 (vem com o FastAPI) | schema do JSON do juiz e retry se vier inválido | n/a |
| **DB** | **SQLite + SQLModel** | arquivo único, sem servidor, e os modelos Pydantic viram tabelas | Postgres (servidor para 3 candidatos); JSON solto (sem query para o painel e as métricas) |
| **Cache** | tabela `llm_cache` no SQLite (hash de prompt+modelo) + modelo de STT carregado 1× em memória | economiza a cota free e dá **reprodutibilidade** na demo | **Redis** (sem caso de uso: um processo só) |
| Fila e jobs | `BackgroundTasks` do FastAPI | um processo, uma máquina, demo | Celery/RQ/arq (exigem Redis e worker) |
| Config | `.env` injetado pelo Compose (`env_file: .env`) | zero dependências | pydantic-settings, python-dotenv |
| PDF | **WeasyPrint** (HTML → PDF) | reusa Jinja2 e CSS; pango e fontes via `apt` na imagem | ReportLab (layout imperativo); wkhtmltopdf (abandonado) |
| Testes | `pytest` + fixtures sintéticos + `LLM_MODE=mock` | permite trabalhar **sem chaves** (você ainda vai pegá-las) | n/a |
| Lint | `ruff` | um binário só faz lint e format | black + flake8 |
| Mapa de código | **Graphify** (`graphifyy`) | grafo do repositório para os agentes consultarem impacto antes de editar e revisar | n/a |
| Métricas | stdlib (kappa e WER têm ~10 linhas cada) | evita trazer scikit-learn e jiwer só para duas fórmulas | sklearn, jiwer |

> "Whisperflow": o Wispr Flow é um app de ditado, não uma biblioteca. Para o STT usamos o **faster-whisper**.
> Se a ideia era o **WhisperX**, ele só agrega diarização, que é desnecessária com um falante por vídeo.

## Docker e portabilidade
- **Imagem única CPU** (`python:3.14-slim`, amd64 e arm64). Não há variante GPU nem ajuste para máquina fraca (D-011): `large-v3-turbo` em `int8` na CPU.
- `apt`: `ffmpeg`, `libpango-1.0-0`, `libpangoft2-1.0-0`, `fonts-dejavu-core` (WeasyPrint). O `uv` é copiado de `ghcr.io/astral-sh/uv`.
- **Modelos embutidos no build**: o spaCy `pt_core_news_md` e o faster-whisper (`STT_MODEL` como build-arg) já vêm na imagem. Na demo nada é baixado em runtime e o container funciona offline, exceto os LLMs.
- Venv em `/opt/venv`; o código é montado em `/app` via bind mount, o que permite `--reload` e `make test` sem rebuild.
- Volume nomeado `tv-data` → `/app/data` (SQLite + uploads temporários).
- `HEALTHCHECK` chama `GET /health`, que verifica o banco, o modelo STT carregado e se as chaves existem (só se existem, nunca o valor).

## Makefile (`make` sozinho = help)

| Alvo | Faz |
|---|---|
| `help` | lista os alvos (padrão) |
| `up` | `docker compose up -d --build` |
| `down` | `docker compose down` |
| `status` | `docker compose ps` |
| `health` | `GET /health` de dentro do container |
| `logs` | `docker compose logs -f app` |
| `test` | pytest (`LLM_MODE=mock`) + ruff + `scripts/docs_links.py --check` dentro do container; `T=tests/x.py` roda um arquivo só |
| `import` | `make import ZIP=../Dataset_Advogados_Jr_Completo.zip`: monta o zip como read-only e importa |
| `ops` | sobe o dash de live ops do loop de agentes em http://localhost:8001 (refresh 1 s; [D-021](../process/decisions.md)) |

<!-- backlinks:start -->
---
**Referenciado por:** [CLAUDE.md](../../CLAUDE.md) · [Visão geral da arquitetura](overview.md) · [TalentVisor — Índice da documentação](../index.md)
<!-- backlinks:end -->

# Estrutura de pastas

> [Índice](../index.md) · [Visão geral](overview.md) · [Modelo de dados](data-model.md)

Cada módulo de código começa com uma docstring que cita os REQs que implementa (ex.: `REQ-F-06`). Assim o Graphify liga código ↔ SPEC.

```text
TalentVisor/
├── CLAUDE.md                  # constituição (carregada pelo Claude Code); aponta para docs/index.md
├── Makefile                   # make = help · up down status health logs test import
├── Dockerfile  compose.yaml  .dockerignore
├── pyproject.toml  uv.lock    # uv.lock gerado na T-01
├── .env                       # chaves (NUNCA lido pelo Claude; gitignored)
├── .gitignore
├── .claude/
│   ├── settings.json          # deny de leitura do .env
│   └── agents/                # tv-architect · tv-builder · tv-runner
├── docs/                      # toda a documentação → docs/index.md
│   ├── index.md
│   ├── spec/          spec.md · ui.md                       (EN)
│   ├── architecture/  overview · stack · models-router · data-model · layout
│   ├── domain/        rubric · metrics · legal · dataset
│   ├── plan/          slices.md
│   └── process/       agent-loop.md · decisions.md
├── talentvisor/               # pacote Python (código em EN)
│   ├── __init__.py
│   ├── app.py                 # rotas FastAPI: páginas + API JSON + /health
│   ├── db.py                  # SQLModel: tabelas, engine, purge por TTL
│   ├── stt.py                 # faster-whisper; fallback Groq em chunks
│   ├── privacy.py             # anonimização + heurística de injeção
│   ├── llm.py                 # cliente OpenAI-compat, mock, cache, schema, assert anti-PII
│   ├── router.py              # roteador 3 camadas + router_log
│   ├── prompts.py             # rubrica, âncoras, delimitadores
│   ├── pipeline.py            # E0–E6, self-consistency, auditoria, revisão
│   ├── report.py              # PDF WeasyPrint
│   ├── metrics.py             # kappa, WER, P/R, taxas
│   ├── templates/
│   │   ├── base.html  _macros.html
│   │   ├── upload.html  _consent.html  submitted.html   # termo = popover no formulário (D-062)
│   │   ├── dashboard.html  _rows.html
│   │   ├── candidate.html  _status.html  _decision.html
│   │   ├── report.html  error.html
│   └── static/style.css       # ajustes mínimos sobre o Pico
├── scripts/
│   ├── import_dataset.py      # make import
│   ├── eval.py                # 5 casos sintéticos
│   ├── bias_check.py          # contrafactual
│   ├── check_models.py        # 1 chamada mínima por modelo; base do make health (só status, nunca chaves)
│   └── docs_links.py          # backlinks dos docs + checagem de links quebrados (roda no make test)
├── tests/
│   ├── fixtures/synthetic.json
│   └── test_*.py
└── data/                      # volume Docker: talentvisor.db, uploads/ (gitignored)
```

Idioma: docs em PT-BR; SPEC, código, identificadores, comentários e commits em **inglês**. O texto da UI e o conteúdo do relatório são **PT-BR**, porque são conteúdo para o usuário final e não código.

<!-- backlinks:start -->
---
**Referenciado por:** [CLAUDE.md](../../CLAUDE.md) · [Visão geral da arquitetura](overview.md) · [Stack e alternativas avaliadas](stack.md) · [TalentVisor — Índice da documentação](../index.md) · [Slices, tasks e Definition of Done](../plan/slices.md)
<!-- backlinks:end -->

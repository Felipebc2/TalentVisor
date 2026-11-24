# Decisões (caveman)

> [Índice](../index.md) · [Agent Loop](agent-loop.md)

Formato: `D-NNN | data | decisão. why: … alt: … revisit: …`

- D-001 | 24/11 | nome = TalentVisor. why: escolha Felipe. alt: parecer (rejeitado).
- D-002 | 24/11 | web = FastAPI + Jinja2 + HTMX + Pico.css. why: 1 noite, sem build, API JSON grátis p/ Langflow. alt: Streamlit, Gradio (plano B), Django, React, NiceGUI. revisit: se precisar UX rica.
- D-003 | 24/11 | STT = faster-whisper local large-v3-turbo int8 CPU. why: voz = dado pessoal, não vai pra nuvem; wheels cp314 ok. alt: Groq whisper. revisit: CPU > 3 min/vídeo → GPU (cublas/cudnn pip).
- D-004 | 24/11 | fallback STT = Groq whisper, chunks ffmpeg ≤10 min, prompt = fim do chunk anterior. flag ALLOW_CLOUD_STT=0 default. why: pedido Felipe + limite 25 MB. alt: nenhum fallback.
- D-005 | 24/11 | anonimização = PII do CSV + regex + spaCy pt_core_news_md. why: local, determinístico, mensurável. alt: Qwen3 8B Ollama (não cabe 4 GB VRAM c/ STT), Presidio (pesado).
- D-006 | 24/11 | DB = SQLite + SQLModel. cache = tabela llm_cache. sem Redis, sem Celery. why: 1 processo, 3 candidatos. revisit: multi-worker.
- D-007 | 24/11 | LLM client = openai SDK c/ base_url (Groq + Gemini OpenAI-compat). why: 1 cliente, json_schema. alt: groq + google-genai SDKs.
- D-008 | 24/11 | "postura" = forma VERBAL só. corpo/voz/rosto fora. why: LGPD art. 11 + viés. confirmado Felipe.
- D-009 | 24/11 | sem login na demo. why: tempo. dívida: rotas /painel abertas. revisit: pós-apresentação.
- D-010 | 24/11 | métricas (kappa, WER) em stdlib. why: 10 linhas vs sklearn/jiwer.
- D-011 | 24/11 | tudo Docker Compose, 1 serviço, imagem CPU python:3.14-slim, amd64+arm64. modelos STT+spaCy baked no build. sem variante GPU, sem tuning p/ máquina fraca. why: portável, demo offline, pedido Felipe. alt: modelo baixado em runtime (1ª execução lenta, depende rede). revisit: imagem > 4 GB.
- D-012 | 24/11 | Makefile: help(default) up down status health logs test import. só esses. why: pedido Felipe, mínimo necessário.
- D-013 | 24/11 | idioma: docs PT-BR; SPEC+código+comentários+commits EN; UI e relatório PT-BR (conteúdo usuário). why: regra absoluta Felipe.
- D-014 | 24/11 | sem Rust/Go. why: gargalo = STT (já C++ via CTranslate2) + latência de LLM (rede); ecossistema (faster-whisper, spaCy, WeasyPrint) é Python; prazo 1 noite. revisit: gateway c/ alta concorrência.
- D-015 | 24/11 | git: commit local só orquestrador, msg EN, sem Co-Authored-By/menção Claude, nunca push. co-author só em PR. why: regra Felipe.
- D-016 | 24/11 | docs em docs/ por tema (spec, architecture, domain, plan, process) + index.md. backlinks gerados por scripts/docs_links.py, checados no make test. why: navegação + Graphify. alt: backlink manual (desatualiza).
- D-017 | 24/11 | .env NEVER READ: regra 0 do CLAUDE.md + deny em .claude/settings.json (Read/Edit/cat/grep/printenv/compose config). why: segredo. chaves só via env_file no container.
- D-018 | 24/11 | M5 = gemini-4-hydrogen, fallback gemini-3.5-flash-lite (mesma família, ≠ gpt-oss). why: smoke test 200 nos dois; 2.5-flash depreciado; 3.8-flash instável (503/timeout). revisit: 429 frequente.
- D-019 | 24/11 | chamadas HTTP cruas p/ Groq precisam User-Agent próprio (Cloudflare dá 403 p/ Python-urllib). openai SDK já manda UA. why: smoke test.
- D-020 | 24/11 | gate SPEC REVIEW no fim de toda slice, antes do commit: tv-spec-reviewer (Opus, persona Dev Senior) dispara 3 forks (otimista, neutra, pessimista) e é a 4ª visão (modesta). nota 0-5 + confiança. ≥75% PASS; 50–74% REVISE (tv-architect corrige, nova revisão, máx. 2 voltas); <50% HUMAN. why: pedido Felipe. alt: revisão única (viés de uma visão só).
- D-021 | 24/11 | live ops dash: orquestrador grava eventos em ops/events.jsonl via scripts/ops.py log; `make ops` serve o dash (stdlib, Docker, :8001, refresh 1 s). novo alvo `ops` no Makefile (emenda D-012/REQ-NF-07). why: Felipe acompanhar o loop ao vivo. alt: hooks do Claude Code (dependem do cwd da sessão; não sabem passo/nota). ops/ fora do git. página = scripts/ops.html (template do Felipe) lendo /state.json; barra do SPEC review = confiança vs gate 75.

<!-- backlinks:start -->
---
**Referenciado por:** [CLAUDE.md](../../CLAUDE.md) · [Stack e alternativas avaliadas](../architecture/stack.md) · [TalentVisor — Índice da documentação](../index.md) · [Agent Loop (SDD) do TalentVisor](agent-loop.md) · [TalentVisor — Specification (SDD)](../spec/spec.md)
<!-- backlinks:end -->

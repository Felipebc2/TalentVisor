# Modelos e roteador de LLMs

> [Índice](../index.md) · [Visão geral](overview.md) · [SPEC](../spec/spec.md) · [Métricas](../domain/metrics.md)

| ID | Modelo | Onde | Etapa | Recebe |
|---|---|---|---|---|
| M1 | faster-whisper `large-v3-turbo` | local | E1 STT | vídeo bruto |
| M1b | Groq `whisper-large-v3` (chunks) | nuvem | E1 fallback (flag) | áudio |
| M2 | spaCy `pt_core_news_md` + regex | local | E2 anonimização | texto bruto |
| PG | Groq `meta-llama/llama-prompt-guard-2-86m` | nuvem | E3 injeção | texto anonimizado |
| M3 | Groq `openai/gpt-oss-20b` | nuvem | E3 segmentação | texto anonimizado |
| M4 | Groq `openai/gpt-oss-120b` | nuvem | E4 juiz (3×) | texto anonimizado |
| M5 | Gemini `gemini-4-hydrogen` (fallback na mesma família: `gemini-3.5-flash-lite`) | nuvem | E5 relatório, E6 auditor | texto anonimizado |

Os IDs ficam no `.env`. **T-00 confere cada um no console** antes do primeiro uso real.

Relevância (0–10) usada na camada 2 do roteador:

| | E3 seg | E4 juiz | E5 relatório | E6 auditor |
|---|---|---|---|---|
| M3 | 9 | 6 | 6 | 5 |
| M4 | 7 | 9 | 8 | 7 |
| M5 | 7 | 8 | 9 | 9 |

Roteador `route(etapa, ctx) -> Escolha(modelo, motivo, fallback)`. Toda chamada gera uma linha em `router_log`.
- **Camada 1, restrições (elimina modelos):**
  - texto com dado pessoal → só modelo local;
  - tokens > janela do modelo;
  - cooldown por 429 ou erro (dict em memória, 5 min);
  - E6 ≠ família do E4.
- **Camada 2, pontuação:** relevância + Σ sinais.
  - `tokens<2k` → +2 M3; `tokens>8k` → +2 M5;
  - complexidade alta (resposta ambígua, fora do tema ou registro informal) → +2 M4/M5;
  - `qualidade_audio` baixa → complexidade alta e auditoria forçada;
  - `criticidade` (nota perto do corte) → força M4 no E4;
  - `modo_demo` → +1 Groq;
  - cota restante < 20% → −3.
- **Camada 3, escalonamento:**
  - JSON inválido → sobe de modelo;
  - confiança < 0,7 → **revisão humana** (gatilho da REQ-F-13), não escala de modelo (D-032);
  - fallbacks: M4→M5→M3 e M1→M1b (só se a flag estiver ligada);
  - divergência ≥ 2 entre juiz e auditor → **revisão humana** (não escala).

<!-- backlinks:start -->
---
**Referenciado por:** [CLAUDE.md](../../CLAUDE.md) · [Visão geral da arquitetura](overview.md) · [Métricas e gatilhos de revisão](../domain/metrics.md) · [TalentVisor — Índice da documentação](../index.md) · [TalentVisor — Specification (SDD)](../spec/spec.md)
<!-- backlinks:end -->

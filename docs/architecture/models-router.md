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
| M5 | Gemini `gemini-4-hydrogen` (fallback na mesma família: `gemini-3.5-flash-lite`) | nuvem | E4 reserva, E6 auditor | texto anonimizado |
| M6 | Mistral `ministral-14b-2512` (3ª família) | nuvem | E4/E6 reserva | texto anonimizado |

Os IDs ficam no `.env`. A reserva M6 leva o prefixo do provedor no ID (`mistral:`), D-055. **T-00 confere cada um no console** antes do primeiro uso real.

**E5 (relatório) não existe como chamada:** o juiz (E4) já devolve perfis, pontos fortes/de atenção, hard skills e categoria (D-031). A coluna E5 fica na tabela só porque o `_REL` do `router.py` ainda a tem; nenhuma chamada usa `stage="E5"`.

Relevância (0–10) usada na camada 2 do roteador (M5F = M5 − 1):

| | E3 seg | E4 juiz | E5 (sem uso, D-031) | E6 auditor |
|---|---|---|---|---|
| M3 | 9 | 6 | 6 | 5 |
| M4 | 7 | 9 | 8 | 7 |
| M5 | 7 | 8 | 9 | 9 |
| M6 | 6 | 7 | 7 | 8 |

M6 é a 3ª família: com Groq e Gemini fora, o juiz cai p/ M6 e o auditor (gpt-oss ou Gemini) continua elegível.

Roteador `route(etapa, ctx) -> list[Choice]`: lista ordenada de modelos elegíveis; `call()` desce a lista em cascata (D-040). Toda chamada gera uma linha em `router_log`.
- **Camada 1, restrições (elimina modelos):**
  - texto com dado pessoal conhecido (`has_pii`) → nenhum modelo elegível (todos são nuvem) → `NoModelAvailable`, candidato em `error`;
  - chave do provedor ausente (modo real) → modelos dele fora (D-055);
  - tokens > janela do modelo (Gemini 1M; gpt-oss e ministral 128k);
  - cooldown de 60 s (dict em memória, D-048) após 429 esgotado ou 5xx/timeout/erro de conexão;
  - E6 ≠ família de **todo** modelo usado em qualquer run do E4; sem auditor elegível ou funcionando → reason `audit_unavailable` (revisão humana), não erro (D-040).
- **Camada 2, pontuação:** relevância + Σ sinais; empate → maior relevância, depois a ordem dos slots.
  - `tokens<2k` → +2 M3; `tokens>8k` → +2 M5;
  - injeção detectada ou áudio ruim (`no_speech_prob > 0,5` ou `avg_logprob < −1,0`) → +2 M4/M5 (sinal `hard`);
  - `DEMO_MODE=1` → +1 gpt-oss (Groq);
  - não há sinal de criticidade: o overall só existe depois do E4, então não pode escolher o modelo do E4 (D-040);
  - não há sinal de cota (os provedores não expõem a cota restante): fica de fora.
- **Camada 3, escalonamento:**
  - JSON inválido (depois do 1 retry do `llm.py`) → próximo modelo, sem cooldown;
  - 5xx, timeout ou erro de conexão → cooldown de 60 s e próximo modelo;
  - `PIILeakError` → propaga (fail closed), a tentativa fica no log;
  - 429 → respeita `retry-after` até 65 s (free tier da Groq zera TPM por minuto; 1 chamada do juiz ≈ metade dos 8k TPM) e tenta o mesmo modelo até 3 vezes (`MAX_429_WAITS`); `retry-after` inválido ou absurdo → 10 s; ausente c/ header de limite por minuto (Mistral, 2 req/min) → 30 s, D-055; `retry-after` > 65 s ou 429 depois das 3 esperas → cooldown e próximo modelo (D-048);
  - 400 BadRequest (ex.: Groq "Failed to validate JSON") → próximo modelo, **sem** cooldown (D-048);
  - confiança < 0,7 → **revisão humana** (gatilho da REQ-F-13), não escala de modelo (D-032);
  - fallbacks: M4→M5→M5F→M6→M3 no E4 (D-055; com texto < 2k tokens o M3 sobe para logo após o M5) e M1→M1b (só se a flag estiver ligada);
  - divergência ≥ 2 entre juiz e auditor → **revisão humana** (não escala).

<!-- backlinks:start -->
---
**Referenciado por:** [CLAUDE.md](../../CLAUDE.md) · [Visão geral da arquitetura](overview.md) · [Métricas e gatilhos de revisão](../domain/metrics.md) · [TalentVisor — Índice da documentação](../index.md) · [TalentVisor — Specification (SDD)](../spec/spec.md)
<!-- backlinks:end -->

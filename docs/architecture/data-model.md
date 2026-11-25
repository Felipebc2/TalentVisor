# Modelo de dados (SQLite)

> [Índice](../index.md) · [Visão geral](overview.md) · [Regras legais](../domain/legal.md) · [SPEC](../spec/spec.md)

| Tabela | Campos principais | TTL |
|---|---|---|
| `candidate` | `id`, `code`, `real_name` (revelado só após a decisão), `consent_at`, `consent_version`, `cleared`, `status`, `created_at` | 30 d |
| `transcript` | `candidate_id`, `text_anon`, `segments_json`, `quality` (logprob/no_speech), `expires_at` | **7 d** |
| `evaluation` | `candidate_id`, `result_json` (schema da [SPEC §6](../spec/spec.md)), `overall_score`, `category`, `human_review`, `reasons` | 30 d |
| `router_log` | `candidate_id`, `stage`, `model`, `reason`, `fallback_from`, `ms`, `ok`, `tokens`, `ts` | 90 d |
| `audit_log` | `candidate_id`, `actor` (system/recruiter/candidate), `action`, `payload_json`, `ts` | 90 d |
| `llm_cache` | `key` (sha256 de modelo+prompt), `response`, `ts` | 7 d |

`purge_expired()` roda no startup e após cada pipeline. O vídeo e o áudio **nunca** chegam ao banco: são apagados com `finally: unlink()` logo após o E1.

<!-- backlinks:start -->
---
**Referenciado por:** [CLAUDE.md](../../CLAUDE.md) · [Estrutura de pastas](layout.md) · [Visão geral da arquitetura](overview.md) · [Regras legais e éticas](../domain/legal.md) · [TalentVisor — Índice da documentação](../index.md) · [Slices, tasks e Definition of Done](../plan/slices.md)
<!-- backlinks:end -->

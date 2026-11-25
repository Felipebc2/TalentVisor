# Modelo de dados (SQLite)

> [Índice](../index.md) · [Visão geral](overview.md) · [Regras legais](../domain/legal.md) · [SPEC](../spec/spec.md)

| Tabela | Campos principais | TTL |
|---|---|---|
| `candidate` | `id`, `code`, `real_name` (revelado só após a decisão), `consent_at`, `consent_version` (`v1`, `v1-groq` com `ALLOW_CLOUD_STT=1`, `dataset` só no import de linha liberada; nulo, junto com `consent_at`, na linha recusada), `cleared`, `status`, `error` (failed stage), `video_path` (upload on disk, cleared after STT), `form_json` (education, experience, description, answers P01–P05), `pii_json` (name, institution, city: local-only for `privacy.py`, never sent to an LLM), `created_at` | 30 d |
| `transcript` | `candidate_id`, `text_anon`, `segments_json`, `quality_json` ({avg_logprob, no_speech_prob, pct_inaudible}), `expires_at` | **7 d** |
| `evaluation` | `candidate_id`, `result_json` (schema da [SPEC §6](../spec/spec.md)), `overall_score`, `category`, `human_review`, `reasons` | 30 d |
| `router_log` | `candidate_id`, `stage`, `model`, `reason`, `fallback_from`, `ms`, `ok`, `tokens`, `ts` | 90 d |
| `audit_log` | `candidate_id`, `actor` (system/recruiter/candidate), `action`, `payload_json`, `ts` | 90 d |
| `llm_cache` | `key` = sha256(model, messages, temperature, seed), `response`, `ts` | 7 d |

`purge_expired()` roda no startup e após cada pipeline. O vídeo e o áudio **nunca** chegam ao banco: são apagados com `finally: unlink()` logo após o E1.

Candidato importado do dataset (F-03): `pii_json` = só `{name}` (dataset não tem colunas de instituição/cidade; instituição/cidade no texto livre ficam p/ regex/NER best-effort). Não liberado: linha direto em `status=refused`, `cleared=False`, sem PII (`real_name` null, `pii_json {}`, `form_json {}`), sem vídeo (D-047).

Quando o candidato é purgado (30 d), o `payload_json` das linhas dele no `audit_log` (o único texto livre é o comentário da decisão; contestação removida, D-063) vira `"{}"`; a linha de auditoria (actor/action/ts) fica até 90 d (D-052).

`purge_expired()` também apaga uploads órfãos: candidato com `video_path` há mais de 6 h tem o arquivo apagado; se estava em `received`/`transcribing`, vira `error` (`error="transcribing"`). Roda antes do delete das linhas, então nenhum vídeo sobrevive à linha do candidato purgado (D-027). Também apaga pastas de chunks da Groq (`UPLOAD_DIR/tmp*`) com mais de 6 h. Na subida do app, `fail_inflight()` (antes do `purge_expired()`) leva para `error` todo candidato web (`consent_version != "dataset"`) ainda em status de processamento, guarda a etapa em `error` e apaga o vídeo: a BackgroundTask morreu com o processo. O pipeline começa via `BackgroundTasks` depois do commit do upload.

`audit_log` sem candidato: `POST /api/evaluate` grava `actor=system, action=evaluated_api, candidate_id=null` com `{human_review, reasons}` (REQ-L-05).

<!-- backlinks:start -->
---
**Referenciado por:** [CLAUDE.md](../../CLAUDE.md) · [Estrutura de pastas](layout.md) · [Visão geral da arquitetura](overview.md) · [Regras legais e éticas](../domain/legal.md) · [TalentVisor — Índice da documentação](../index.md) · [Slices, tasks e Definition of Done](../plan/slices.md)
<!-- backlinks:end -->

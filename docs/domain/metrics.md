# Métricas e gatilhos de revisão

> [Índice](../index.md) · [Rubrica](rubric.md) · [SPEC](../spec/spec.md) · [Modelos e roteador](../architecture/models-router.md)

| Métrica | Onde |
|---|---|
| Concordância IA × humano (Cohen's kappa) | `metrics.py`, a partir das decisões no `audit_log` |
| WER da transcrição | `metrics.py`, com referência manual quando houver |
| Precision/recall da anonimização | `metrics.py`, com o PII do CSV como gabarito |
| Estabilidade contrafactual (nome, gênero, registro) | `scripts/bias_check.py`: Δ ≤ 1 |
| Taxa de escalonamento para revisão humana | painel |
| Taxa de bloqueio de injeção | `router_log` / `audit_log` |
| Latência por etapa | `router_log.ms` (p50) |
| Confiança (self-consistency) | desvio das 3 execuções do juiz |

Gatilhos de **REVISÃO HUMANA OBRIGATÓRIA** (SPEC REQ-F-13):
- divergência ≥ 2 entre juiz e auditor;
- confiança < 0,7;
- injeção detectada;
- transcrição vazia ou < 30 palavras;
- fora do tema em ≥ 2 perguntas;
- qualidade de áudio baixa.

<!-- backlinks:start -->
---
**Referenciado por:** [CLAUDE.md](../../CLAUDE.md) · [Modelos e roteador de LLMs](../architecture/models-router.md) · [Rubrica, perguntas e categorias](rubric.md) · [TalentVisor — Índice da documentação](../index.md) · [TalentVisor — Specification (SDD)](../spec/spec.md) · [TalentVisor — Web UI Specification](../spec/ui.md)
<!-- backlinks:end -->

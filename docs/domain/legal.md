# Regras legais e éticas

> [Índice](../index.md) · [SPEC](../spec/spec.md) · [Modelo de dados](../architecture/data-model.md) · [Dataset](dataset.md)

1. Minimização (LGPD art. 6º, III): o vídeo e o áudio são **apagados em `finally`** após a transcrição; a transcrição tem TTL de 7 d. Texto livre no `audit_log` (só o comentário da decisão) é apagado junto com o candidato (30 d); a linha de auditoria fica 90 d (D-052). PDF baixado sai do controle de retenção do sistema: responsabilidade do recrutador.
2. Nada de biometria, emoção, aparência, voz ou postura como critério.
3. Nenhuma decisão automatizada final (LGPD art. 20). Não existe decisão com `actor=system`. Pedido de revisão: vai pelo contato do processo seletivo, usando o código da candidatura; o app não tem mais canal próprio de contestação ([D-063](../process/decisions.md)).
4. LLMs na nuvem recebem **somente texto anonimizado automaticamente**: best-effort com precisão/recall medidos, nunca uma garantia de que não sobrou PII. Os free tiers podem usar as entradas para melhorar os modelos; fazer opt-out onde o provedor oferecer. Processadores (fora do Brasil, LGPD art. 33): Groq (EUA), Google Gemini (EUA) e Mistral (França, só reserva M6, D-055). No free tier da Mistral, desligar o uso dos dados para treino em *Admin → Privacy* do console; sem esse opt-out, o M6 fica só como reserva de emergência. PII conhecido é bloqueado (o `llm.py` aborta com `PIILeakError`); outro PII via regex/NER é best-effort, medido no `scripts/eval.py`. Única exceção documentada (D-004, D-035): o fallback de STT na nuvem (REQ-F-05) manda mídia crua (voz, talvez um nome falado) para a Groq, só com `ALLOW_CLOUD_STT=1` (default 0, desligado na demo) **e** consentimento `v1-groq` do candidato (o termo que nomeia a Groq como processador externo).
5. Log de auditoria de cada avaliação, decisão e escolha do roteador.
6. Candidato com `liberado_analise != "Sim"` **não é processado**.
7. Aviso fixo no painel e no PDF: "Recomendação gerada por IA. Decisão final é humana."
8. Segredos só no `.env`. Dados reais (zip, vídeos, `data/`) **nunca** vão para o git nem para `tests/`.

<!-- backlinks:start -->
---
**Referenciado por:** [Modelo de dados (SQLite)](../architecture/data-model.md) · [Dataset](dataset.md) · [TalentVisor — Índice da documentação](../index.md) · [TalentVisor — Specification (SDD)](../spec/spec.md)
<!-- backlinks:end -->

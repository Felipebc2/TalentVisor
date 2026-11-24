# Regras legais e éticas

> [Índice](../index.md) · [SPEC](../spec/spec.md) · [Modelo de dados](../architecture/data-model.md) · [Dataset](dataset.md)

1. Minimização (LGPD art. 6º, III): o vídeo e o áudio são **apagados em `finally`** após a transcrição; a transcrição tem TTL de 7 d.
2. Nada de biometria, emoção, aparência, voz ou postura como critério.
3. Nenhuma decisão automatizada final (LGPD art. 20). Não existe decisão com `actor=system`.
4. LLMs na nuvem recebem **somente texto anonimizado**; o `llm.py` aborta se houver PII conhecido no payload.
5. Log de auditoria de cada avaliação, decisão e escolha do roteador.
6. Candidato com `liberado_analise != "Sim"` **não é processado**.
7. Aviso fixo no painel e no PDF: "Recomendação gerada por IA. Decisão final é humana."
8. Segredos só no `.env`. Dados reais (zip, vídeos, `data/`) **nunca** vão para o git nem para `tests/`.

<!-- backlinks:start -->
---
**Referenciado por:** [Modelo de dados (SQLite)](../architecture/data-model.md) · [Dataset](dataset.md) · [TalentVisor — Índice da documentação](../index.md) · [TalentVisor — Specification (SDD)](../spec/spec.md)
<!-- backlinks:end -->

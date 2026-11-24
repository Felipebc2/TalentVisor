# TalentVisor

MVP acadêmico (disciplina "Agentes Autônomos de IA", IDP). Apresentação em 25/11/2026.
Análise de perfil de candidatos a **Advogado(a) Júnior** por soft skills em vídeo. A IA recomenda e um humano decide.

Escopo: somente a parte do Felipe Castro (software: back com roteador de IA e front).
Ficam fora: Langflow (Luan; ele consome a API JSON), UML (depois), slides, roteiro da demo, PEAS escrito e respostas teóricas.

## Regras absolutas

0. **NEVER READ `.env`.** Nunca ler, abrir, imprimir, copiar, fazer `cat`/`grep`/`source`, rodar `printenv` ou `docker compose config`, nem copiar a pasta inteira com o `.env` dentro. As chaves só entram no container via `env_file`. Bloqueado também em `.claude/settings.json`. Para saber se as chaves existem: `make health`.
1. **Keep it simple.** A solução mais simples que funciona vence. Sem abstração, camada ou dependência "para depois".
2. **Think before touching any code.** Ler o REQ, ler o código e todos os chamadores (`graphify query`), entender o fluxo e só então editar.
3. **Idioma:** documentação em **PT-BR**; **SPEC, código, identificadores, comentários e mensagens de commit em inglês**. Exceção: o texto da UI e o conteúdo do relatório/PDF são PT-BR, porque são para o usuário final.
4. **Tudo roda em Docker**, em qualquer máquina só com Docker instalado. A operação é via `make`; nada depende do Python do host.
5. **Git:**
   - nunca `git push`;
   - commits e `git add` **sem** `Co-Authored-By` e sem qualquer menção a Claude ou IA;
   - `Co-Authored-By` só na descrição de **PR**, quando formos fechar PRs;
   - stage por nome de arquivo, nunca `git add -A` ou `git add .`.
6. **Dados reais** (zip do dataset, vídeos, `data/`) nunca vão para o git nem para `tests/`.

## Documentação → [docs/index.md](docs/index.md)

| Preciso de… | Doc |
|---|---|
| O que construir (REQs, aceite, API, contrato JSON) | [SPEC](docs/spec/spec.md) (EN) |
| Como as telas são e se comportam | [UI spec](docs/spec/ui.md) (EN) |
| Rubrica, perguntas, categorias | [rubric.md](docs/domain/rubric.md) |
| Métricas e gatilhos de revisão | [metrics.md](docs/domain/metrics.md) |
| Stack, Docker, Makefile, alternativas | [stack.md](docs/architecture/stack.md) |
| Modelos e roteador | [models-router.md](docs/architecture/models-router.md) |
| Tabelas e TTL | [data-model.md](docs/architecture/data-model.md) |
| Árvore de pastas | [layout.md](docs/architecture/layout.md) |
| Ordem de construção (slices S0–S7) | [slices.md](docs/plan/slices.md) |
| Como os agentes trabalham | [agent-loop.md](docs/process/agent-loop.md) |
| Por que decidimos X | [decisions.md](docs/process/decisions.md) |

SDD: código sem REQ não entra. Uma mudança de comportamento começa na SPEC e é registrada em decisions.
Antes de editar código compartilhado: `graphify query "<símbolo>"`. Depois de fechar uma task: `graphify update .`
Ao mexer em docs: links relativos; `make test` roda `scripts/docs_links.py --check` (links quebrados e backlinks).

## Comandos

```bash
make                      # help
make up                   # build + sobe em http://localhost:8000
make health               # banco, modelo STT, chaves presentes (nunca os valores)
make test                 # pytest (LLM_MODE=mock) + ruff + docs_links --check
make test T=tests/test_privacy.py
make import ZIP=../Dataset_Advogados_Jr_Completo.zip
make logs | make status | make down
```

## Regras legais (invioláveis)

@docs/domain/legal.md

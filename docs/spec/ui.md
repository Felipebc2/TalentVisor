# TalentVisor — Web UI Specification

> [Index](../index.md) · [SPEC](spec.md) · [Slices](../plan/slices.md) · [Rubric](../domain/rubric.md)

Simple and genuinely functional. Two audiences:
- **candidate:** consent → upload → confirmation;
- **recruiter:** dashboard → detail → decision → PDF.

Requirement IDs `REQ-UI-*` complement [SPEC §5.1](spec.md) (F-01, F-02, F-14–F-17).

## 1. Principles

| # | Principle |
|---|---|
| P1 | **Server-rendered**: Jinja2 + Pico.css (classless) + HTMX via CDN. No build step and no JS framework. Custom JS is limited to the upload progress bar (≤ 15 lines). |
| P2 | **Works without JS** for every form (plain POST + redirect); HTMX only enhances (polling, in-place decision). |
| P3 | **PT-BR copy** everywhere the user reads; identifiers, routes and classes in English. |
| P4 | **Accessible**: real `<label>` for every input, visible focus, `aria-live="polite"` on status regions, color is never the only signal (badges carry text), contrast AA (Pico default). |
| P5 | **Responsive**: works at 360 px width; tables scroll horizontally inside `<figure>`; nothing overflows the page. |
| P6 | **Light/dark** from the OS via Pico's automatic theme. |
| P7 | **Honest UI**: the fixed notice "Recomendação gerada por IA. Decisão final é humana." in the footer of every recruiter page and of the PDF. |

## 2. Layout and navigation

```text
┌──────────────────────────────────────────────────────────────┐
│ TalentVisor        Enviar candidatura   Painel do recrutador │  <header><nav>
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  <main class="container">  page content                      │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ Recomendação gerada por IA. Decisão final é humana. · LGPD   │  <footer>
└──────────────────────────────────────────────────────────────┘
```

- `base.html` holds the header, footer, Pico/HTMX `<link>`/`<script>` and a flash-message slot.
- The recruiter-only footer adds the AI notice; the candidate footer shows retention info.

## 3. Pages

### 3.1 `/` — Consent (candidate) · REQ-F-01

```text
Termo de consentimento
  ▸ Finalidade            (1 short paragraph)
  ▸ O que analisamos      conteúdo verbal das respostas (o que você diz)
  ▸ O que NÃO analisamos  rosto, voz, emoção, aparência, postura
  ▸ Retenção              vídeo apagado após a transcrição; texto por 7 dias
  ▸ Seus direitos         revisão humana, contestação pelo código
  [x] Li e aceito o termo (versão v1)            ← required checkbox
  [ Continuar ]                                  ← GET /upload?consent=v1
```

- **REQ-UI-01:** the checkbox is `required`. Without it, the browser blocks submit (no JS needed).
- Reaching `/upload` without `consent=v1` redirects to `/` with the flash message "Aceite o termo para continuar."

### 3.2 `/upload` — Submission (candidate) · REQ-F-02

```text
Perguntas (responda todas em um único vídeo, até 10 min)
  1. Como você explicaria a um cliente, sem formação jurídica, ...
  2. ... 5.  (from perguntas.csv, always visible)

Vídeo *            [ escolher arquivo ]  mp4/webm/mov · até 300 MB
Seus dados *       Nome completo · Instituição · Cidade
                   (usados só para anonimizar; nunca enviados à IA)
Formação *         [ text ]
Experiência        [ textarea ]
Descrição livre    [ textarea ]  "conte algo sobre você"
▸ Respostas escritas (opcional)   <details> with 5 textareas
▸ ou importe um CSV (opcional)    [ escolher arquivo ] one row, ';'
[ Enviar ]   ▓▓▓▓▓▓░░░ 62%        ← <progress> during upload
```

- **REQ-UI-02:** client-side `accept=".mp4,.webm,.mov"` and `required`. The server re-validates. On error the form re-renders with the values kept, the message next to the field and `aria-invalid="true"`.
- **REQ-UI-03:** while uploading, the button is disabled and a `<progress>` shows the percentage (HTMX `htmx:xhr:progress`). A double submit is impossible.
- **REQ-UI-04:** the help text under "Seus dados" explains why the name is asked (anonymization).

### 3.3 `/submitted/{code}` — Confirmation (candidate)

```text
✓ Recebido!
  Seu código:  TV-7F3A          ← large, monospace, copy button
  O que acontece agora: transcrição → análise → revisão por uma pessoa.
  Seu vídeo será apagado logo após a transcrição.
  Quer contestar depois? Use o código em  /contest
```

- **REQ-UI-05:** the code is the only identifier shown. The page never shows the score.

### 3.4 `/contest` — Contest (candidate, P2) · REQ-F-17
- Fields: code + text (both required). On success, the flash "Contestação registrada. Uma pessoa vai revisar."
- An unknown code returns the same neutral message, so the page doesn't reveal whether a code exists.

### 3.5 `/dashboard` — Recruiter list · REQ-F-14

```text
┌ Total 3 ┐ ┌ Aguardando 2 ┐ ┌ Revisão obrigatória 1 ┐ ┌ Decididos 0 ┐   summary
Filtro: [Status ▾] [ ] só revisão obrigatória            (GET params)

Código   Status              Nota  Categoria               Revisão          Enviado
TV-7F3A  ● aguardando decisão 4.2  Comunicador Conciliador ⚠ divergência…   24/11 18:02  [Abrir]
TV-91C0  ◌ transcrevendo…      —   —                        —               24/11 18:10  [Abrir]
TV-02BB  ✗ recusado            —   —                        —               24/11 17:40
```

- **REQ-UI-06:** the table body polls `GET /dashboard/rows` every 3 s **only while** some row is processing. When none is, the server answers `286`, which makes HTMX stop polling.
- **REQ-UI-07:** the review badge shows the text "Revisão obrigatória" plus the reasons in `title` and in a `<details>` on small screens.
- **REQ-UI-08:** empty state "Nenhuma candidatura ainda." with a link to `/upload`.
- No names here. Rows are sorted by "revisão obrigatória" first, then by date desc.
- **(P1)** below the table, a `<details>` "Métricas" block shows: review rate, injection blocks, p50 latency per stage, and kappa once ≥ 3 decisions exist ([Métricas](../domain/metrics.md)).

### 3.6 `/candidate/{id}` — Detail and decision · REQ-F-15

```text
TV-7F3A · aguardando decisão · Nota geral 4.2 · [Comunicador Conciliador]
┌ ⚠ REVISÃO HUMANA OBRIGATÓRIA ─ divergência em ética; confiança baixa em argumentação ┐

Soft skills                                       │  Decisão
 Comunicação  ████▌ 5   conf 0.85  auditor 4      │  ( ) Aprovar para entrevista
   "eu procuraria explicar de forma clara…"       │  ( ) Reprovar
   P01 · 00:12–00:19                               │  ( ) Segunda avaliação
   Justificativa: propõe linguagem acessível…     │  Comentário [          ]
 Argumentação ...                                  │  [ Registrar decisão ]
                                                  │
Hard skills      • Pesquisa jurídica (formulário) │  [ Baixar PDF (rascunho) ]
Perfil           Trabalho: …   Pessoal: …         │
Pontos fortes │ Pontos de atenção                 │
Consistência escrita × fala: alta — …             │
▸ Log do roteador  (stage · model · reason · fallback · ms · ok)
```

- **REQ-UI-09 (processing):** while `status ∉ {awaiting_decision, approved, rejected, second_review}`, the page shows a stepper (`received → transcribing → anonymizing → scoring → auditing`) that polls a status fragment every 3 s. When it finishes, the server sends `HX-Refresh: true`, so the whole page reloads.
- **REQ-UI-10 (error):** `status=error` shows the failed stage and the message "Falha no processamento. Reenvie ou contate o suporte." Stack traces are never shown.
- **REQ-UI-11 (skills):** one card per skill with:
  - a `<meter min=1 max=5>` plus the number;
  - the confidence;
  - the auditor score;
  - the evidence in a `<blockquote>` with the question and timestamp;
  - the justification.
  A `null` score shows "sem evidência suficiente".
- **REQ-UI-12 (decision):** `hx-post` to `/candidate/{id}/decision` swaps the decision panel in place with the result ("Aprovado para entrevista por recrutador em 24/11 18:30").
  - Rejecting without a comment → 422 → inline message "Comentário obrigatório para reprovar."
  - After a decision the real name appears in the header ("TV-7F3A · Jadeh P. P.").
  - The panel becomes read-only; only "Segunda avaliação" can reopen it.
- **REQ-UI-13 (router log):** a collapsible table from `router_log` with all fields, fallbacks highlighted.
- **REQ-UI-14:** the PDF button says "Baixar PDF (rascunho)" before the decision and "Baixar PDF" after it.

### 3.7 PDF — `report.html` (A4, print CSS) · REQ-F-16

```text
TalentVisor — Relatório de candidatura          TV-7F3A · 24/11/2026
[ RASCUNHO — aguardando decisão humana ]        (watermark until decided)
Categoria: COMUNICADOR CONCILIADOR   Nota geral 4.2/5
Soft skills   skill · nota (barra) · evidência (1 linha) · confiança
Hard skills · Perfil de trabalho · Perfil pessoal
Pontos fortes │ Pontos de atenção
Revisão humana: sim — motivos…      Decisão: aprovado por recrutador em …
───────────────────────────────────────────────────────────────────
Recomendação gerada por IA. Decisão final é humana. · modelos: … · p. 1/2
```

- **REQ-UI-15:** the PDF fits on ≤ 2 pages for 5 skills; WeasyPrint `@page` sets the footer and page numbers; no external fetches at render time (CSS inlined).

### 3.8 Errors
- **REQ-UI-16:** `404` and `400` use `base.html` with PT-BR messages and a link back. `500` shows a generic message; details only in the logs.

## 4. Components (Jinja macros in `templates/_macros.html`)

| Macro | Renders |
|---|---|
| `status_badge(status)` | `<mark>` with text + symbol: ● aguardando, ◌ processando, ✓ aprovado, ✗ reprovado/recusado, ↺ 2ª avaliação, ! erro |
| `review_banner(reasons)` | `<article role="alert">` "REVISÃO HUMANA OBRIGATÓRIA" + reasons in PT-BR |
| `score_meter(score)` | `<meter>` + number; "—" when null |
| `evidence(quote, question, ts)` | `<blockquote>` + `<cite>P01 · 00:12–00:19</cite>` |
| `stepper(status)` | `<ol>` of stages, current stage marked `aria-current="step"` |
| `ai_notice()` | fixed footer sentence |

Reason codes → PT-BR labels (one dict in `app.py`):
- `divergence:<skill>` → "divergência em <skill>";
- `low_confidence:<skill>` → "confiança baixa em <skill>";
- `injection_detected` → "possível manipulação do prompt";
- `empty_transcript` → "transcrição vazia ou curta";
- `off_topic` → "respostas fora do tema";
- `low_audio_quality` → "áudio de baixa qualidade".

## 5. HTMX interactions (complete list)

| Where | Trigger | Request | Swap |
|---|---|---|---|
| Upload form | submit | `POST /upload` (multipart) | none; 303 redirect followed |
| Upload form | `htmx:xhr:progress` | — | updates `<progress>` |
| Dashboard tbody | `every 3s` | `GET /dashboard/rows?<filters>` | `innerHTML`; `286` stops polling |
| Candidate stepper | `every 3s` | `GET /candidate/{id}/status` | `outerHTML`; `HX-Refresh` when done |
| Decision panel | submit | `POST /candidate/{id}/decision` | `outerHTML` of the panel |

Nothing else uses JS.

## 6. Acceptance (manual + `test_app.py`)

| ID | Given / When / Then | Test |
|---|---|---|
| UI-01 | consent unchecked → submit blocked; `/upload` without consent → redirect to `/` | `test_upload_requires_consent` |
| UI-02 | invalid file → form re-rendered with message, values kept | `test_invalid_extension` |
| UI-06 | no processing rows → `/dashboard/rows` returns 286 | `test_rows_stop_polling` |
| UI-09 | processing candidate → stepper fragment; finished → `HX-Refresh` | `test_status_fragment` |
| UI-12 | reject without comment → 422; with comment → `audit_log(actor=recruiter)`, name revealed | `test_decision_writes_audit` |
| UI-14 | PDF before decision contains "RASCUNHO" | `test_pdf_draft_watermark` |
| UI-P5 | 360 px viewport: no horizontal page scroll (manual, browser devtools) | manual |

Tasks: [T-04](../plan/slices.md) (3.1–3.3, 3.8, minimal 3.5), [T-14](../plan/slices.md) (3.5, 3.6), [T-15](../plan/slices.md) (3.7), [T-16](../plan/slices.md) (3.4).

<!-- backlinks:start -->
---
**Referenciado por:** [CLAUDE.md](../../CLAUDE.md) · [Rubrica, perguntas e categorias](../domain/rubric.md) · [TalentVisor — Índice da documentação](../index.md) · [Slices, tasks e Definition of Done](../plan/slices.md) · [Agent Loop (SDD) do TalentVisor](../process/agent-loop.md) · [TalentVisor — Specification (SDD)](spec.md)
<!-- backlinks:end -->

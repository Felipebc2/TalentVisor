# TalentVisor — Web UI Specification

> [Index](../index.md) · [SPEC](spec.md) · [Slices](../plan/slices.md) · [Rubric](../domain/rubric.md)

Simple and genuinely functional. Two audiences:
- **candidate:** submission form (with consent) → confirmation;
- **recruiter:** dashboard → detail → decision → PDF.

Requirement IDs `REQ-UI-*` complement [SPEC §5.1](spec.md) (F-01, F-02, F-14–F-16). Contest (F-17) was removed ([D-063](../process/decisions.md)).

## 1. Principles

| # | Principle |
|---|---|
| P1 | **Server-rendered**: Jinja2 + Pico.css (classless) + HTMX via CDN. No build step and no JS framework. Custom JS is only the small inline snippets listed in §5. |
| P2 | **Works without JS** for every form (plain POST/GET + redirect; the dashboard filter has a "Filtrar" button); HTMX and the inline snippets only enhance. |
| P3 | **PT-BR copy** everywhere the user reads; identifiers, routes and classes in English. |
| P4 | **Accessible**: real `<label>` for every input, visible focus, `aria-live="polite"` on status regions, color is never the only signal (badges carry text), contrast AA (Pico default). |
| P5 | **One viewport on desktop**: at 1440×900 and 1280×800 no page scrolls; long content (table, transcript, skills, router log) scrolls inside its own panel. Below 980 px the layout stacks and the page scrolls; nothing overflows horizontally (checked with Playwright, D-061). |
| P6 | **Dark scan console** (D-061): near-black ground, red only for live state, review flags and one sweep line; status is never color alone (dot + word). Pico stays as the base for controls, themed by tokens in `static/style.css`. |
| P7 | **Honest UI**: the fixed notice "Recomendação gerada por IA. Decisão final é humana." on every recruiter page (in the app bar and the decision panel) and in the PDF. |

## 2. Layout and navigation

Two worlds share one palette (D-061):

```text
Recruiter (/dashboard, /candidate/*)          Candidate (/, /upload, /submitted)
┌──────────────────────────────────────┐      ┌──────────────────────────────────────┐
│ brand    aviso fixo   Sair do painel │      │ brand        Enviar · Painel         │
├──────────────────────────────────────┤      ├──────────────────────────────────────┤
│ page header (‹ Voltar ao painel)     │      │  centered stage, panels side by side │
│ ┌─────────┐┌──────────┐┌──────────┐  │      │                                      │
│ │ panel   ││ panel    ││ panel    │  │      ├──────────────────────────────────────┤
│ │ (scroll)││          ││          │  │      │ LGPD retention line                  │
│ └─────────┘└──────────┘└──────────┘  │      └──────────────────────────────────────┘
└──────────────────────────────────────┘
```

- `base.html` picks the world from the path, holds the Pico/HTMX `<link>`/`<script>`, an inline SVG icon set and the flash slot (candidate world).
- Recruiter (D-063): no sidebar. An app bar with the brand, the fixed AI notice and "Sair do painel" (link to `/`); the analysis page has "Voltar ao painel" in its header. Work area = header + panel grid, one viewport.
- Candidate: top bar + centered stage + LGPD retention footer.

## 3. Pages

### 3.1 Consent (inside the form at `/` and `/upload`) · REQ-F-01

The candidate lands directly on the submission form (§3.2); there is no separate consent page (D-062).

```text
… [x] Li e aceito o termo de consentimento   ← required checkbox name="consent" (v1, or v1-groq with the flag)
  [ Enviar candidatura ]                        "termo de consentimento" opens the popover:

  ┌ popover #termo (top layer, blurred backdrop, dark portrait sheet) ┐
  │ TalentVisor                                        versão v1      │
  │ Termo de consentimento                                            │
  │  Finalidade · O que analisamos (conteúdo verbal) ·                │
  │  O que NÃO analisamos (rosto, voz, emoção, aparência, postura) ·  │
  │  Retenção (vídeo apagado após a transcrição; transcrição 7 d;     │
  │    candidatura + avaliação 30 d; auditoria 90 d) ·                │
  │  Seus direitos · Quem processa (local STT; Groq, Google, Mistral  │
  │    recebem só texto anonimizado; + Groq áudio com ALLOW_CLOUD_STT)│
  │                          [ Fechar ]  [ Li e aceito o termo ]      │
  └───────────────────────────────────────────────────────────────────┘
```

- **REQ-UI-01:** `GET /` and `GET /upload` return 200 with the form. The checkbox is `required` (the browser blocks submit, no JS needed). The term is a native popover (`id="termo" popover`, opened by `popovertarget="termo"`); "Li e aceito o termo" closes it and ticks the checkbox.
- "Seus direitos": "Toda decisão é tomada por uma pessoa, nunca pela IA. Seu código de candidatura identifica você em qualquer pedido de revisão." (review requests go through the selection-process contact, D-063).
- `POST /upload` without a valid `consent` → 400 re-rendering the form with "Aceite o termo de consentimento para enviar." next to the checkbox, values kept, nothing saved (the video is not written). The flash `?msg=consent` ("Aceite o termo para continuar.") still exists (REQ-F-01, D-023, D-062).
- With `ALLOW_CLOUD_STT=1` the version is `v1-groq` and the text names Groq as the external processor of the audio (F-01, D-035).

### 3.2 `/` and `/upload` — Submission (candidate) · REQ-F-02

```text
┌ Seus dados              ● ○ ─────────┐┌ Vídeo da entrevista ──────────────────┐
│ track slides sideways (D-062):        ││ Um único vídeo, até 10 min, …          │
│ step 1  Nome completo *               ││ 1. Como você explicaria a um cliente… │
│         Instituição * · Cidade *      ││ 2. … 5.  (always visible)              │
│         "Dados protegidos (LGPD):     ││ ┌ drop zone (grouped, centered) ─────┐ │
│          nunca vão para a IA."        ││ │ ⤒ Escolha o vídeo *                │ │
│         Formação * · Experiência      ││ │ ou arraste · mp4/webm/mov · 300 MB │ │
│         Descrição livre (large)       ││ └────────────────────────────────────┘ │
│ step 2  Respostas escritas (opcional) ││ [x] Li e aceito o termo de consentim. │
│         P01 … P05 textareas           ││ [ Enviar candidatura ] ▓▓▓▓░░ 62%      │
│ [ Voltar ]               [ Próximo ]  ││                                        │
└───────────────────────────────────────┘└────────────────────────────────────────┘
```

- Two steps that slide sideways with a dot indicator (no step labels). "Próximo" validates the current step; on submit an invalid field brings its step back into view. Without JS the steps stack (D-062). There is no CSV pre-fill.
- **REQ-UI-02:** client-side `accept=".mp4,.webm,.mov"` and `required`. The server re-validates. On error the form re-renders with the values kept, the message next to the field and `aria-invalid="true"`; a missing required field → 400 "Campo obrigatório." next to it.
- **REQ-UI-03:** while uploading, the button is disabled and a `<progress>` shows the percentage (HTMX `htmx:xhr:progress`). A double submit is impossible.
- **REQ-UI-04:** the hint under name/institution/city says "Dados protegidos (LGPD): nunca vão para a IA."

### 3.3 `/submitted/{code}` — Confirmation (candidate)

```text
Candidatura recebida
  Guarde o código abaixo: ele identifica sua candidatura.
  TV-7F3A                       ← large, monospace, "Copiar código"
  Transcrição → Análise → Revisão (uma pessoa decide; o vídeo é apagado)
```

- **REQ-UI-05:** the code is the only identifier shown. The page never shows the score.

### 3.4 (removed)
Contest page `/contest` removed with REQ-F-17 ([D-063](../process/decisions.md)).

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
- **REQ-UI-08:** empty states: no candidate at all → "Nenhuma candidatura ainda." with a link to `/upload`; candidates exist but none matches the filter → "Nenhum resultado para o filtro."
- Each row is clickable anywhere: the "Abrir" link is stretched over the row (D-062).
- "✗ recusado" = dataset row not cleared for analysis (F-03): no PII; the action cell shows "—" instead of the "Abrir" link, so the row is not clickable (D-047).
- No names here. Rows are sorted by "revisão obrigatória" first, then by date desc.
- **(P1)** below the table, a `<details>` "Métricas" block shows: "Taxa de revisão", "Taxa de detecção de injeção" (injection only triggers review), "Latência p50 por etapa" (no STT), and kappa ("aguardando ≥ 3 decisões" until then). With no evaluation: "Sem avaliações ainda." The kappa cut (`AI_APPROVE_CUT`) is never shown as a recommendation (D-046) ([Métricas](../domain/metrics.md)).

### 3.6 `/candidate/{id}` — Detail and decision · REQ-F-15

```text
[‹ Voltar ao painel]  TV-7F3A ● aguardando decisão           ┌ 4.2/5  Nota geral ┐
            Nome oculto até a decisão (avaliação cega)       └ Comunicador Conc. ┘
┌ REVISÃO HUMANA OBRIGATÓRIA  divergência em Ética · confiança baixa em …        ┐
┌ Análise da IA ─────────────┐┌ O que o candidato disse e escreveu ┐┌ Decisão ─────┐
│ [Soft skills] Perfil e hard ││ [Transcrição] Formulário  Log do   ││ ( ) Aprovar  │
│ Comunicação ████▌ 5         ││ duração 01:42 · sem fala 4% · …    ││ ( ) Reprovar │
│ confiança baixa · auditor 3 ││ 01:42 · sem fala 4% · vídeo apagado││ ( ) 2ª aval. │
│ "eu procuraria explicar…"   ││ 00:12  eu procuraria explicar…  ◄──┼┼─ evidência  │
│ P01 · 00:12–00:19 (link) ───┼┼─►     (linha destacada, :target)  ││ Comentário   │
│ (scroll interno)            ││ (scroll interno)                   ││ [Registrar]  │
└─────────────────────────────┘└────────────────────────────────────┘└ [PDF] aviso ─┘
```

- **REQ-UI-09 (processing):** while `status ∉ {awaiting_decision, approved, rejected, second_review}`, the page shows a stepper (`received → transcribing → anonymizing → scoring → auditing`) that polls a status fragment every 3 s. When it finishes, the server sends `HX-Refresh: true`, so the whole page reloads.
- **REQ-UI-10 (error):** `status=error` shows the failed stage and the message "Falha no processamento. Reenvie ou contate o suporte." Stack traces are never shown.
- **REQ-UI-11 (skills):** one card per skill with:
  - a `<meter min=1 max=5>` plus the number;
  - confidence and auditor score inline **only when they need attention** (D-062): "confiança baixa · N" when confidence < 0.7, "auditor deu N" when the divergence is ≥ 2; the full numbers (confidence, auditor, runs) are always in the tooltip (`title`);
  - the evidence in a `<blockquote>` with the question and timestamp;
  - the justification, collapsed behind "Por que N?" (`<details>`).
  A `null` score shows "sem evidência suficiente".
- **REQ-UI-12 (decision):** `hx-post` to `/candidate/{id}/decision`; on success the server answers `HX-Refresh` and the page reloads with the result ("Aprovado para entrevista por recrutador em 24/11 18:30"). D-044.
  - 4xx swaps the panel (global htmx 4xx swap in `base.html`): rejecting without a comment → 422 "Comentário obrigatório para reprovar."; a transition forbidden by spec §8 → 409 (D-050).
  - After `approved`/`rejected` the real name appears in the header ("TV-7F3A · Jadeh P. P."); it is hidden again in `second_review` (blind re-evaluation, D-041).
  - The panel becomes read-only; only "Segunda avaliação" can reopen it.
- **REQ-UI-17 (source side by side, D-061):** the middle panel shows what the candidate actually said and wrote, next to the AI analysis:
  - **Transcrição:** the anonymized transcript as timestamped lines (`id="t-<start s>"`), plus one meta line: duration, audio-quality signal and "vídeo apagado (LGPD)"; the transcript expiry is in the tooltip (D-062). The video is never shown: it is deleted after STT (REQ-L-01).
  - Each evidence timestamp links to its transcript line, which is highlighted (`:target`).
  - **Formulário:** education, experience, description and the written answers P01–P05, anonymized with the known PII on the fly so the review stays blind until the decision (UI-12).
  - Without a transcript (expired after 7 d, or API run): "Transcrição indisponível".
- **REQ-UI-13 (router log):** the "Log do roteador" tab lists `router_log` with all fields, fallbacks highlighted.
- **REQ-UI-14:** the PDF button says "Baixar PDF (rascunho)" in `awaiting_decision`/`second_review` and "Baixar PDF" in `approved`/`rejected` (D-044).

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

- Real name in the PDF only for `approved`/`rejected`; never in `awaiting_decision`/`second_review` (D-041, D-051).
- **REQ-UI-15:** the PDF fits on ≤ 2 pages for 5 skills; WeasyPrint `@page` sets the footer and page numbers; no external fetches at render time (CSS inlined).

### 3.8 Errors
- **REQ-UI-16:** `404` and `400` use `base.html` with PT-BR messages ("Página não encontrada.", "Requisição inválida.") and a link back. `500` shows "Algo deu errado. Tente novamente em instantes."; details only in the logs. Under `/api/*` every error is JSON `{"detail"}` instead (spec §7).

## 4. Components (Jinja macros in `templates/_macros.html`)

| Macro | Renders |
|---|---|
| `status_badge(status)` | `<mark>` with text + symbol: ● aguardando, ◌ processando, ✓ aprovado, ✗ reprovado/recusado, ↺ 2ª avaliação, ! erro |
| `review_banner(reasons)` | `<article role="alert">` "REVISÃO HUMANA OBRIGATÓRIA" + reasons in PT-BR |
| `score_meter(score)` | `<meter>` + number; "—" when null |
| `evidence(quote, question, ts)` | `<blockquote>` + `<cite>P01 · 00:12–00:19</cite>` |
| `stepper(status)` | `<ol>` of stages, current stage marked `aria-current="step"` |
| `ai_notice()` | fixed footer sentence |

Reason codes → PT-BR labels (one dict, `REASON_LABELS` in `report.py`, imported by `app.py`; D-050):
- `divergence:<skill>` → "divergência em <skill>";
- `low_confidence:<skill>` → "confiança baixa em <skill>";
- `no_evidence:<skill>` → "sem evidência em <skill>";
- `audit_unavailable` → "auditoria indisponível";
- `injection_detected` → "possível manipulação do prompt";
- `empty_transcript` → "transcrição vazia ou curta";
- `off_topic` → "respostas fora do tema";
- `low_audio_quality` → "áudio de baixa qualidade".

## 5. HTMX interactions (complete list)

| Where | Trigger | Request | Swap |
|---|---|---|---|
| Upload form | submit | `POST /upload` (multipart) | `body` (XHR follows the 303, `hx-push-url`); a 400 re-render is swapped in via `htmx:beforeSwap`; without JS a plain POST + 303 |
| Upload form | `htmx:xhr:progress` | — | updates `<progress>` |
| Dashboard tbody | `every 3s` | `GET /dashboard/rows?<filters>` | `innerHTML`; `286` stops polling |
| Candidate stepper | `every 3s` | `GET /candidate/{id}/status` | `outerHTML`; `HX-Refresh` when done |
| Decision panel | submit | `POST /candidate/{id}/decision` | success: `HX-Refresh: true` (page reload); 4xx (422/409): `outerHTML` of the panel |

Inline JS outside HTMX (no other script exists):

| Where | Snippet | Without JS |
|---|---|---|
| `base.html` | `htmx:beforeSwap` listener: swap 4xx responses so re-rendered forms/panels show their errors | full-page POST shows the same re-render |
| `upload.html` | disables "Enviar candidatura" and drives `<progress>` from `htmx:xhr:progress` (UI-03); shows the picked file name; "Li e aceito o termo" ticks the consent box; wizard: slides between steps, "Próximo" validates the step, dots move between steps (D-062) | plain POST, no progress bar; steps stack; the popover still opens (native `popovertarget`) and the box is ticked by hand |
| `submitted.html` | "Copiar" button: `onclick` → `navigator.clipboard.writeText(code)` | the code stays visible to copy by hand |
| `dashboard.html` | status `<select onchange="this.form.submit()">` | "Filtrar" button submits the GET form |

## 6. Acceptance (tests in `tests/`)

| ID | Given / When / Then | Test |
|---|---|---|
| UI-01 | Given `/` or `/upload`, then 200 with the form, the `required` checkbox `name="consent"` and the term popover (`id="termo" popover`, `popovertarget="termo"`); given `POST /upload` without consent, then 400 with "Aceite o termo de consentimento para enviar.", values kept, nothing saved | `test_app.py::test_consent_page`, `::test_upload_requires_consent`, `::test_upload_without_consent_400`, `::test_consent_names_groq_when_cloud_stt` |
| UI-02 | Given an invalid file, then the form re-renders with the message, values kept and `aria-invalid="true"`; given an empty required field, then 400 "Campo obrigatório." | `test_app.py::test_invalid_extension`, `::test_upload_required_fields` |
| UI-03 | Given an upload in progress, then "Enviar" is disabled and `<progress>` advances | manual (needs a real browser XHR; TestClient runs no JS) |
| UI-04 | Given `/upload`, then the personal-data fields have the hint "Dados protegidos (LGPD): nunca vão para a IA." | manual (static template copy) |
| UI-05 | Given `/submitted/{code}`, then only the code is shown, never a score; an unknown code → 404 | `test_app.py::test_upload_ok` (200 and 404); no-score: manual (the template receives only `code`) |
| UI-06 | Given no processing rows, then `/dashboard/rows` returns 286; given one, then 200 and `every 3s` | `test_app.py::test_rows_stop_polling` |
| UI-07 | Given a review row, then "Revisão obrigatória" + PT-BR reasons | `test_app.py::test_dashboard_filters_and_review` |
| UI-08 | Given no candidate, then "Nenhuma candidatura ainda."; given a filter with no match, then "Nenhum resultado para o filtro."; given a refused row, then no "Abrir" link | `test_app.py::test_dashboard_has_no_names`, `::test_dashboard_filter_empty_message`, `::test_refused_row_has_no_open_link` |
| UI-09 | Given a processing candidate, then the stepper fragment with `aria-current="step"`; finished → `HX-Refresh: true` | `test_app.py::test_status_fragment` |
| UI-10 | Given `status=error`, then "Falha no processamento. Reenvie ou contate o suporte." | `test_app.py::test_detail_error_status` |
| UI-11 | Given an evaluation, then `<meter>`, `<blockquote>`, `<cite>P01 · 00:12–00:19</cite>`; a null score → "sem evidência suficiente" | `test_app.py::test_detail_renders_skills` |
| UI-12 | Given reject without comment, then 422; with comment → `audit_log(actor=recruiter)`, `HX-Refresh`, name revealed; a forbidden transition → 409; `second_review` hides the name again | `test_app.py::test_decision_writes_audit`, `::test_name_hidden_again_after_second_review` |
| UI-13 | Given router_log rows, then "Log do roteador" lists them and fallbacks have `class="fallback"` | `test_app.py::test_detail_shows_router_log` |
| UI-14 | Given `awaiting_decision`/`second_review`, then the button says "Baixar PDF (rascunho)" and the PDF has "RASCUNHO" and no real name | `test_app.py::test_detail_renders_skills`, `test_report.py::test_pdf_draft_watermark`, `::test_no_name_before_decision` |
| UI-15 | Given 5 skills, then the PDF has ≤ 2 pages and the footer lists the model versions | `test_report.py::test_pages_le_2`, `::test_footer_lists_model_versions` |
| UI-16 | Given an unknown HTML route, then 404 page "Página não encontrada."; under `/api/*`, then JSON `{"detail": "Not Found"}` | `test_app.py::test_not_found_html_and_api_json` |
| UI-17 | Given a transcript and a form, then the detail shows timestamped lines (`id="t-12"`), the evidence links to them (`href="#t-12"`), the deleted-video note, the anonymized written answers and no real name before the decision; no `<video>` | `test_app.py::test_detail_shows_source_side_by_side` |
| UI-P5 | Given a 360 px viewport, then no horizontal page scroll | manual (browser devtools; layout cannot be measured in TestClient) |

Tasks: [T-04](../plan/slices.md) (3.1–3.3, 3.8, minimal 3.5), [T-14](../plan/slices.md) (3.5, 3.6), [T-15](../plan/slices.md) (3.7). T-16 (contest, 3.4) removed by [D-063](../process/decisions.md).

<!-- backlinks:start -->
---
**Referenciado por:** [CLAUDE.md](../../CLAUDE.md) · [Rubrica, perguntas e categorias](../domain/rubric.md) · [TalentVisor — Índice da documentação](../index.md) · [Slices, tasks e Definition of Done](../plan/slices.md) · [Agent Loop (SDD) do TalentVisor](../process/agent-loop.md) · [TalentVisor — Specification (SDD)](spec.md)
<!-- backlinks:end -->

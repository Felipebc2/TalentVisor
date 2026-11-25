# Design: TalentVisor scan console

Source of truth: `talentvisor/static/style.css` (tokens on `:root`), `templates/base.html`, `templates/_macros.html`. Decision: D-061.

## World
A scanner reading a candidate's words: near-black ground, cool panels, and red used only where the scanner "looks" (live state, review flags, the sweep line). Calm, dense, evidence-first. Operate mode: the tool disappears into the recruiter's task.

## Color (Restrained: neutrals + one accent)
| Token | Value | Use |
|---|---|---|
| `--bg` | #060708 | page ground |
| `--panel` / `--panel-2` / `--raise` | #0d0f12 / #13161a / #1a1e23 | panels, inputs, chips |
| `--line` / `--line-2` | #22272e / #2e343c | hairlines, control borders |
| `--text` / `--muted` / `--faint` | #e9ebee / #a1a8b2 / #737b86 | text tiers (AA on panels) |
| `--red` / `--red-ink` | #ff3b3f / #ff6b6e | primary action, live status, review flag, focus, selection |
| `--red-dim` / `--red-line` | 12% / 45% red | flag fills, active nav, highlighted transcript line |
| `--ok`, `--amber` | #34d399, #f5b14c | approved; processing, low confidence, second review |

Rules: red never decorates; every status is dot + word (never color alone); approved is green, not red.

## Type
System UI sans for everything (`--sans`), tabular numerals globally. Mono (`--mono`) only for data: candidate codes, timestamps, confidence/run readouts, model IDs. Big readouts (KPIs, overall score) use tabular sans. Scale: h1 1.55rem, h2 1rem, body 15px, meta 0.76–0.82rem.

## Layout
- Recruiter: no sidebar (D-063). Top app bar (`.appbar`: brand · fixed AI notice · "Sair do painel" to `/`) + work area; `height: 100vh`, page never scrolls on desktop; panels (`.panel`) scroll inside (`.scroll`, `.tabs .pane`).
- Dashboard rows are clickable anywhere (`tr.linkrow`, the `.row-open` link is stretched over the row).
- Dashboard: readout strip (4 KPIs in one bordered row) → filter row → table panel; metrics column on the right (300px, 248px under 1366px).
- Candidate analysis: header ("Voltar ao painel", code + status, overall readout) → review strip → three panels: AI analysis tabs · source tabs (transcript, form, router log) · decision (290px). Confidence/auditor/runs appear inline only when they need attention (`.skill-flags`); full numbers in the tooltip; justification behind "Por que N?" (`.why`); transcript meta in one line (`p.source-meta`).
- Candidate world: top bar + centered stage (max 1180px) + LGPD fine print; the form lands at `/` and splits "Seus dados" and "Vídeo da entrevista".
  - "Seus dados" is a two-step wizard (`.wizard` > `.track` of `.step`s sliding sideways via `--at`), step dots (`.dots`) only, "Voltar"/"Próximo"; without JS the steps stack.
  - The video side groups the drop zone (`.drop`: icon + text centered) with the consent checkbox (`.consent`) and "Enviar candidatura".
  - Consent term: native popover (`.sheet[popover]`), a dark portrait sheet (A4 ratio) in the top layer over a blurred `::backdrop`; "Li e aceito o termo" ticks the box (D-062).
- Under 980px everything stacks and the page scrolls; no horizontal overflow.

## Components
`.panel` · `.readouts` · `.filters` · `.badge.<status>` · `.flag` · `.row-open` · `.tabs` (CSS-only radio tabs) · `.skill` + `<meter>` · `blockquote` evidence with link to `#t-<s>` · `.segs` transcript lines (`:target` highlight) · `.qa` form answers · `#decision` (option cards with `:has(:checked)`) · `.steps` processing stepper · `.drop` file drop area · `.ticket` code receipt.

## Motion
One authored moment: the red sweep line crossing the overall score and the receipt code once on load; the live processing step has a slow scanning band. 150–250ms elsewhere. `prefers-reduced-motion` removes all of it.

## Icons
Inline SVG sprite in `base.html` (`#i-grid`, `#i-scan`, `#i-upload`, `#i-flag`, `#i-user`, `#i-film`, `#i-back`, `#i-arrow`), 1.8 stroke, round caps.

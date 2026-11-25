# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
- Recruiter (primary): screens Junior Lawyer candidates; reads the AI recommendation, its evidence and the candidate's own written answers side by side, then decides (approve, reject, second review). Works on a desktop/laptop screen, often comparing a few candidates in one sitting.
- Candidate: gives consent, fills a short form, uploads one interview video, later may contest the result by code.

## Product Purpose
TalentVisor analyses soft skills from what the candidate says in a video interview (verbal content only) and recommends; a human always decides. Success: the recruiter decides faster and with the evidence in view, and every decision stays auditable.

## Positioning
Evidence-first screening: every score cites a verbatim quote with its timestamp, two model families cross-check each other, and anything uncertain is flagged for mandatory human review. Video is deleted right after transcription.

## Operating Context
Academic MVP (IDP, "Agentes Autônomos de IA"), demo on 2026-11-25. Runs locally in Docker on 127.0.0.1. Server-rendered FastAPI + Jinja2 + HTMX + Pico CSS; no JS framework.

## Capabilities and Constraints
- The video is deleted after transcription (LGPD minimization, REQ-L-01): the UI never shows the video, only the timestamped transcript, the audio-quality signal and when the media was deleted.
- Real name stays hidden until a human approves or rejects (REQ-F-15).
- Fixed notice on dashboard and PDF: "Recomendação gerada por IA. Decisão final é humana."
- No face, voice, emotion, appearance or posture analysis.
- UI text is PT-BR; tests assert specific strings, labels and HTMX behaviour.
- Desktop screens must fit one viewport without page scroll (1440×900 and 1280×800); long content scrolls inside its own panel.
- Candidate screens (consent, upload, submitted, contest) are separate from the recruiter area.

## Brand Commitments
- Name: TalentVisor.
- Binding visual constraint (from Felipe): black ground with red accents used in details; red reads as a scanner. References: modern dark dashboards with sidebar nav and KPI cards.

## Evidence on Hand
Real dataset of 3 candidates (C002 refused); synthetic fixtures for eval. No testimonials, customers or metrics beyond the app's own.

## Product Principles
- The human decides; the UI never looks like it already decided.
- Evidence before score: every number is one click from the quote that justifies it.
- Show uncertainty loudly (mandatory review, low confidence, audit unavailable).
- Privacy is visible: what was deleted, what is hidden, and why.

## Accessibility & Inclusion
WCAG AA contrast on the dark theme; keyboard navigable; never rely on red alone to convey state.

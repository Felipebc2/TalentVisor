"""REQ-F-16: PDF report (draft watermark, no name before decision, <= 2 pages)."""
from datetime import datetime, timezone
from types import SimpleNamespace

from weasyprint import HTML

from talentvisor.prompts import MOCK_JUDGE
from talentvisor.report import render_html, render_pdf

CAND = SimpleNamespace(code="TV-7F3A", real_name="Maria Souza", status="awaiting_decision",
                       created_at=datetime(2026, 11, 24, 10, 0, tzinfo=timezone.utc))
RESULT = {**MOCK_JUDGE, "overall_score": 4.2, "human_review": True,
          "reasons": ["divergence:ethics", "low_confidence:argumentation"],
          "models": {"stt": "faster-whisper/large-v3-turbo", "judge": "openai/gpt-oss-120b", "auditor": "gemini-x"}}
RESULT["soft_skills"] = [{**s, "confidence": 0.76} for s in MOCK_JUDGE["soft_skills"]]
RESULT["soft_skills"][1] = {**RESULT["soft_skills"][1], "score": None}
APPROVE = {"action": "approve", "comment": "ok", "ts": datetime(2026, 11, 25, 9, 30, tzinfo=timezone.utc)}


def test_pdf_generated():
    assert render_pdf(CAND, RESULT, None).startswith(b"%PDF")


def test_pdf_draft_watermark():
    assert "RASCUNHO" in render_html(CAND, RESULT, None)
    assert "RASCUNHO" in render_html(CAND, RESULT, {**APPROVE, "action": "second_review"})
    html = render_html(CAND, RESULT, APPROVE)
    assert "RASCUNHO" not in html and "Maria Souza" in html
    assert "aprovado para entrevista por recrutador em 25/11/2026 09:30" in html


def test_no_name_before_decision():
    assert "Maria Souza" not in render_html(CAND, RESULT, None)
    assert "Maria Souza" not in render_html(CAND, RESULT, {**APPROVE, "action": "second_review"})


def test_pages_le_2():
    html = render_html(CAND, RESULT, APPROVE)
    assert len(HTML(string=html).render().pages) <= 2
    assert "sem evidência suficiente" in html and "divergência em Ética" in html

"""PDF report rendering with WeasyPrint.

REQ-F-16. Layout: docs/spec/ui.md section 3.7
"""
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from talentvisor.prompts import SKILL_LABELS

_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                   autoescape=select_autoescape(["html"]))

ACTIONS = {"approve": "aprovado para entrevista por recrutador", "reject": "reprovado por recrutador",
           "second_review": "segunda avaliação solicitada por recrutador"}
REASON_LABELS = {"injection_detected": "possível manipulação do prompt", "empty_transcript": "transcrição vazia ou curta",
           "off_topic": "respostas fora do tema", "low_audio_quality": "áudio de baixa qualidade",
           "audit_unavailable": "auditoria indisponível"}


def reason_label(code: str) -> str:
    kind, _, skill = code.partition(":")
    label = SKILL_LABELS.get(skill, skill)
    if kind == "divergence":
        return f"divergência em {label}"
    if kind == "low_confidence":
        return f"confiança baixa em {label}"
    if kind == "no_evidence":
        return f"sem evidência em {label}"
    return REASON_LABELS.get(code, code)


def _fmt(ts) -> str:
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
    return ts.strftime("%d/%m/%Y %H:%M") if ts else ""


def render_html(candidate, result: dict, decision: dict | None) -> str:
    action = decision["action"] if decision else None
    decided = candidate.status in ("approved", "rejected")  # status, not the audit row, is the source of truth (UI-12)
    return _env.get_template("report.html").render(
        c=candidate, r=result, d=decision, labels=SKILL_LABELS,
        date=_fmt(candidate.created_at)[:10],
        draft=not decided,
        show_name=decided and bool(candidate.real_name),
        decision_text=f"{ACTIONS[action]} em {_fmt(decision['ts'])}" if decision else "aguardando decisão humana",
        reasons=[reason_label(x) for x in result.get("reasons", [])])


def render_pdf(candidate, result: dict, decision: dict | None) -> bytes:
    return HTML(string=render_html(candidate, result, decision)).write_pdf()

"""Local anonymization (known PII + regex + spaCy NER) and prompt-injection heuristics.

REQ-F-06, REQ-F-07, REQ-L-04
"""

import re
import unicodedata
from functools import lru_cache

_CONNECTORS = {"dos", "das"}  # name parts of 3 letters that are not names
_PLACEHOLDER = re.compile(r"\[(?:NOME|INSTITUICAO|LOCAL|CPF|OAB|EMAIL|TELEFONE|RG)\]")

# Layer 2, order matters (e-mail and CPF first so phone does not eat their digits).
_REGEX = [
    ("EMAIL", r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
    ("CPF", r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)"),
    ("OAB", r"(?i:\bOAB)(?:\s*[/-]\s*[A-Z]{2})?\s*(?i:n[ºo°.]*)?\s*\d[\d.]*(?:/[A-Z]{2})?"),
    ("RG", r"(?i:\bRG)\s*(?i:n[ºo°.]*)?\s*:?\s*\d[\d.-]*[\dXx]?"),
    # BR phone: hyphenated form, or any form that carries a DDD / +55 (so "2020 2024" is safe)
    (
        "TELEFONE",
        r"(?<!\d)(?:\+?55\s?)?(?:\(\d{2}\)\s?|\d{2}\s)?(?!(?:19|20)\d\d-(?:19|20)\d\d)9?\d{4}-\d{4}(?!\d)"
        r"|(?<!\d)(?:\+?55\s?)?(?:\(\d{2}\)\s?|\d{2}\s)9?\d{4}\s?\d{4}(?!\d)"
        r"|(?<!\d)9\d{4}[\s-]?\d{4}(?!\d)",  # mobile without DDD
    ),
]
_REGEX = [(tag, re.compile(p)) for tag, p in _REGEX]

_NER = {"PER": "[NOME]", "LOC": "[LOCAL]", "ORG": "[INSTITUICAO]"}


def _norm(s: str) -> str:
    """Lowercase, accent-stripped, same length as the input (so spans map back)."""
    return "".join(unicodedata.normalize("NFD", c)[0] for c in s).lower()


def _terms(known: dict) -> dict[str, str]:
    """normalized known value -> placeholder."""
    out: dict[str, str] = {}
    name = " ".join((known.get("name") or "").split())
    if name:
        out[_norm(name)] = "[NOME]"
        for part in name.split():
            if len(part) >= 3 and _norm(part) not in _CONNECTORS:
                out[_norm(part)] = "[NOME]"
    if (v := " ".join((known.get("institution") or "").split())):
        out[_norm(v)] = "[INSTITUICAO]"
    if (v := " ".join((known.get("city") or "").split())):
        out[_norm(v)] = "[LOCAL]"
    return out


def _known_re(terms: dict[str, str]) -> re.Pattern | None:
    if not terms:
        return None
    alts = (r"\s+".join(map(re.escape, t.split())) for t in sorted(terms, key=len, reverse=True))
    return re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)")


@lru_cache(maxsize=1)
def _nlp():
    import spacy

    return spacy.load("pt_core_news_md")


def leaks_known_pii(text: str, known: dict) -> bool:
    """True if any known value (name, name part, institution, city) is still in text."""
    rx = _known_re(_terms(known))
    return bool(rx and rx.search(_norm(text)))


def anonymize(text: str, known: dict) -> str:
    # Layer 2 first: regex needs the raw text (a name inside an e-mail must not split it).
    for tag, rx in _REGEX:
        text = rx.sub(f"[{tag}]", text)
    # Layer 1: known values (match on the normalized text, replace on the original).
    terms = _terms(known)
    if rx := _known_re(terms):
        text = _sub_spans(text, [(m.start(), m.end(), terms[" ".join(m.group().split())]) for m in rx.finditer(_norm(text))])
    # Layer 3: NER, skipping placeholder overlaps and lone sentence-initial non-PER words (false positives).
    held = [m.span() for m in _PLACEHOLDER.finditer(text)]
    spans = [
        (e.start_char, e.end_char, _NER[e.label_])
        for e in _nlp()(text).ents
        if e.label_ in _NER
        and not (e.label_ != "PER" and len(e) == 1 and e.start == e.sent.start)
        and not any(e.start_char < b and a < e.end_char for a, b in held)
    ]
    return _sub_spans(text, spans)


def _sub_spans(text: str, spans: list[tuple[int, int, str]]) -> str:
    for a, b, rep in sorted(spans, reverse=True):
        text = text[:a] + rep + text[b:]
    return text


_INJECTION = {
    "ignore_instructions": r"\b(?:ignor\w*|desconsider\w*|esqueca|forget|disregard)\W+(?:\w+\W+){0,3}?(?:instrucoes|instructions|regras|rules|prompt)",
    "force_score": (
        r"\bnota\s+(?:maxima|5|10)\b|\b(?:de|da|dar|atribua)\s+(?:a\s+|me\s+)*nota\s+(?:maxima|\d+)"
        r"|\bgive\s+(?:me\s+)?(?:a\s+)?(?:5|10|full|max\w*)\b|\bscore\s+(?:of\s+)?(?:5|10)\b"
    ),
    "system_prompt": r"\b(?:system\s+prompt|prompt\s+(?:do|de)\s+sistema)\b",
    "role_change": r"\b(?:voce\s+agora\s+e|you\s+are\s+now|aja\s+como|act\s+as)\b",
    "delimiter": r"<<<|>>>",
    "auto_approve": r"\baprovad[oa]\s+automaticamente|\bapprove\s+me\b|\baprove[\s-]+me\b",
}
_INJECTION = {k: re.compile(v) for k, v in _INJECTION.items()}


def detect_injection(text: str) -> list[str]:
    """Names of the injection heuristics that hit (empty = clean). REQ-F-07."""
    n = _norm(text)
    return [k for k, rx in _INJECTION.items() if rx.search(n)]

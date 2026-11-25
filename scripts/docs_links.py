"""Docs link checker and backlink generator.

    python scripts/docs_links.py           # rewrite the "Referenciado por" block of every doc
    python scripts/docs_links.py --check   # exit 1 on broken links, stale backlinks or SPEC §11 gaps (used by `make test`)
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
START, END = "<!-- backlinks:start -->", "<!-- backlinks:end -->"
BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END), re.S)
CODE = re.compile(r"```.*?```", re.S)


def docs():
    return sorted(DOCS.rglob("*.md"))


def outgoing(path):
    text = CODE.sub("", BLOCK.sub("", path.read_text()))
    for target in LINK.findall(text):
        if "://" not in target and not target.startswith("mailto:"):
            yield (path.parent / target).resolve()


def label(path):
    if path.name == "CLAUDE.md":
        return "CLAUDE.md"
    first = path.read_text().splitlines()[0]
    return first.lstrip("# ").strip() if first.startswith("#") else path.name


def block(doc, refs):
    links = " · ".join(f"[{label(r)}]({os.path.relpath(r, doc.parent)})" for r in refs) or "(nenhum)"
    return f"{START}\n---\n**Referenciado por:** {links}\n{END}"


def trace():
    """SPEC §11: every declared REQ has a row; every cited test/script exists (D-057)."""
    spec = (DOCS / "spec" / "spec.md").read_text()
    rows = spec[spec.index("## 11. Traceability"):].split("<!-- backlinks")[0]
    declared = set(re.findall(r"(?:\*\*|\| )REQ-((?:F|NF|L|Q)-\d+)", spec))
    errors = [f"§11 missing REQ-{r}" for r in sorted(declared) if not re.search(rf"\b{r}\b", rows)]
    tests = {f.name: set(re.findall(r"^def (test_\w+)", f.read_text(), re.M)) for f in (ROOT / "tests").glob("test_*.py")}
    for line in rows.splitlines():
        last = None
        for span in re.findall(r"`([^`]+)`", line):
            path, _, name = span.partition("::")
            if path.endswith(".py"):
                last = Path(path).name
                if last not in tests and not (ROOT / path).exists():
                    errors.append(f"§11 cites missing file {path}")
            if name.endswith("*"):
                errors.append(f"§11 uses a wildcard {last}::{name}; list exact tests")
            elif name:
                have = tests.get(last, set())
                if name not in have:
                    errors.append(f"§11 cites missing test {last}::{name}")
    nf07 = re.search(r"\| REQ-NF-07 \|([^|]*)\|", spec).group(1)
    phony = (ROOT / "Makefile").read_text().split(".PHONY:")[1].split("\n")[0].split()
    listed = re.findall(r"`(\w+)`", nf07.split("targets", 1)[1].split("only these")[0])
    if set(phony) != set(listed):
        errors.append(f"NF-07: Makefile .PHONY {sorted(phony)} differs from the SPEC list")
    if ".env" not in (ROOT / ".gitignore").read_text().split():
        errors.append("NF-03: .env is not in .gitignore")
    return errors


def main(check):
    broken, back = [], {}
    for src in [ROOT / "CLAUDE.md", *docs()]:
        for dst in outgoing(src):
            if not dst.exists():
                broken.append(f"{src.relative_to(ROOT)} -> {os.path.relpath(dst, ROOT)}")
            elif dst.suffix == ".md" and dst != src.resolve():
                back.setdefault(dst, set()).add(src.resolve())

    stale = []
    for doc in docs():
        text = doc.read_text()
        new_block = block(doc, sorted(back.get(doc.resolve(), ())))
        new = BLOCK.sub(lambda _: new_block, text) if START in text else text.rstrip() + "\n\n" + new_block + "\n"
        if new != text:
            stale.append(str(doc.relative_to(ROOT)))
            if not check:
                doc.write_text(new)

    for line in broken:
        print(f"broken link: {line}")
    if check:
        for name in stale:
            print(f"stale backlinks: {name} (run scripts/docs_links.py)")
    gaps = trace()
    for g in gaps:
        print(g)
    return 1 if broken or gaps or (check and stale) else 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))

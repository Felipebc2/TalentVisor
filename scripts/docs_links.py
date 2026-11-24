"""Docs link checker and backlink generator.

    python scripts/docs_links.py           # rewrite the "Referenciado por" block of every doc
    python scripts/docs_links.py --check   # exit 1 on broken links or stale backlinks (used by `make test`)
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
    return 1 if broken or (check and stale) else 0


if __name__ == "__main__":
    sys.exit(main("--check" in sys.argv))

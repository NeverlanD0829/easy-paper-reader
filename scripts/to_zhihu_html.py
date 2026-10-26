#!/usr/bin/env python3
"""Stage 9 of the easy-paper-reader skill: article.md -> article-zhihu.html

Zhihu's editor does not import Markdown. Pasting the raw file leaves `##`,
`|---|`, `**` and `$x$` sitting in the page as literal text, which is what the
garbled draft actually is. The editor *is* a contenteditable, though, so it
accepts rich HTML from the clipboard: open this file in a browser, select all,
copy, paste.

Formulas use Zhihu's own renderer. The editor stores every formula as
`<img src="https://www.zhihu.com/equation?tex=...">`, so emitting that URL makes
a pasted formula indistinguishable from one typed with the formula button. The
browser fetches it under the user's session; nothing is uploaded from here.

Images point at the local crops with file:// URLs. Chrome and Safari put the
decoded bitmap on the clipboard alongside the HTML, so Zhihu usually re-uploads
them on paste; when it does not, the placeholder caption says which file to
upload by hand.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.parse
from pathlib import Path

EQUATION = "https://www.zhihu.com/equation?tex="
# Inline styles, because a clipboard paste carries no stylesheet.
CSS = {
    "h2": "font-size:1.3em;font-weight:700;margin:1.6em 0 0.6em",
    "h3": "font-size:1.12em;font-weight:700;margin:1.3em 0 0.5em",
    "p": "line-height:1.8;margin:0 0 1em",
    "quote": "line-height:1.8;margin:0 0 1em;padding-left:0.8em;"
             "border-left:3px solid #d0d0d0;color:#646464",
    "table": "border-collapse:collapse;width:100%;margin:0 0 1.2em",
    "cell": "border:1px solid #d0d0d0;padding:6px 10px;line-height:1.7;"
            "vertical-align:top",
    "caption": "line-height:1.7;margin:0.3em 0 1.4em;color:#646464;"
               "font-size:0.92em",
    "code": "background:#f6f6f6;padding:1px 4px;border-radius:3px;"
            "font-family:Menlo,Consolas,monospace",
}


def equation(tex: str, display: bool = False) -> str:
    """One formula as the <img> Zhihu itself uses.

    `\\\\` appended to the TeX is Zhihu's own marker for a block formula; the
    alt text keeps the source readable if the image ever fails to load.
    """
    tex = tex.strip()
    payload = urllib.parse.quote(tex + ("\\\\" if display else ""), safe="")
    style = "vertical-align:middle" if not display else "max-width:100%"
    return (f'<img src="{EQUATION}{payload}" alt="{html.escape(tex)}" '
            f'eeimg="1" style="{style}">')


def inline(text: str) -> str:
    """Markdown inline syntax -> HTML, with maths protected from escaping.

    Order is the whole trick: pull the formulas out first, escape what is left
    (otherwise `<` in a table cell breaks the paste and `&` in TeX double-
    escapes), then put the rendered formulas back.
    """
    slots: list[str] = []

    def stash(markup: str) -> str:
        slots.append(markup)
        return f"\x00{len(slots) - 1}\x00"

    text = re.sub(r"\$([^$\n]+)\$", lambda m: stash(equation(m.group(1))), text)
    text = re.sub(r"`([^`\n]+)`",
                  lambda m: stash(f'<code style="{CSS["code"]}">'
                                  f'{html.escape(m.group(1))}</code>'), text)
    text = html.escape(text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                  r'<a href="\2">\1</a>', text)
    return re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], text)


def image(alt: str, src: str, base: Path) -> str:
    """A crop plus its Chinese caption, as two block elements.

    The caption is kept as text rather than folded into alt= because Zhihu
    shows a real caption line under the image and readers rely on it.
    """
    path = (base / src).resolve()
    url = path.as_uri() if path.is_file() else src
    note = "" if path.is_file() else f"（本地文件缺失：{html.escape(src)}）"
    return (f'<p style="{CSS["p"]};text-align:center">'
            f'<img src="{url}" style="max-width:100%">'
            f'</p>\n<p style="{CSS["caption"]};text-align:center">'
            f'{inline(alt)}{note}</p>')


def table(rows: list[str]) -> str:
    """A pipe table -> a real <table>, so the paste keeps the grid.

    The separator row (|---|---|) is dropped; everything before it is the head.
    """
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    body = [r for r in cells if not all(re.fullmatch(r":?-{2,}:?", c)
                                        for c in r if c)]
    head = body[0] if len(body) != len(cells) else None
    out = [f'<table style="{CSS["table"]}">']
    for i, row in enumerate(body):
        tag = "th" if (head is not None and i == 0) else "td"
        weight = ";font-weight:700;background:#f6f6f6" if tag == "th" else ""
        out.append("<tr>" + "".join(
            f'<{tag} style="{CSS["cell"]}{weight}">{inline(c)}</{tag}>'
            for c in row) + "</tr>")
    out.append("</table>")
    return "\n".join(out)


def convert(markdown: str, base: Path) -> str:
    blocks: list[str] = []
    lines = markdown.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):          # no code blocks in an article,
            i += 1                              # but never paste a fence raw
            while i < len(lines) and not lines[i].strip().startswith("```"):
                i += 1
            i += 1
            continue
        if stripped.startswith("$$"):
            tex = [stripped.lstrip("$")]
            while "$$" not in "".join(tex[1:]) and not tex[0].endswith("$$"):
                i += 1
                if i >= len(lines):
                    break
                tex.append(lines[i])
            body = " ".join(tex).replace("$$", "").strip()
            blocks.append(f'<p style="{CSS["p"]};text-align:center">'
                          f"{equation(body, display=True)}</p>")
            i += 1
            continue
        heading = re.match(r"(#{1,6})\s+(.*)", stripped)
        if heading:
            # Zhihu has its own title field, so a lone `#` becomes a normal
            # section heading rather than an <h1> nobody can style.
            level = "h2" if len(heading.group(1)) <= 2 else "h3"
            blocks.append(f'<{level} style="{CSS[level]}">'
                          f"{inline(heading.group(2))}</{level}>")
            i += 1
            continue
        picture = re.fullmatch(r"!\[([^\]]*)\]\(([^)\s]+)\)", stripped)
        if picture:
            blocks.append(image(picture.group(1), picture.group(2), base))
            i += 1
            continue
        if stripped.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            blocks.append(table(rows))
            continue
        if stripped.startswith(">"):
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(f'<p style="{CSS["quote"]}">'
                          + "<br>".join(inline(q) for q in quote) + "</p>")
            continue
        if re.match(r"\d+[.、]\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"\d+[.、]\s+",
                                              lines[i].strip()):
                items.append(re.sub(r"^\d+[.、]\s+", "", lines[i].strip()))
                i += 1
            blocks.append('<ol style="line-height:1.8;margin:0 0 1em">'
                          + "".join(f"<li>{inline(it)}</li>" for it in items)
                          + "</ol>")
            continue
        if stripped.startswith(("- ", "* ")):
            items = []
            while i < len(lines) and lines[i].strip().startswith(("- ", "* ")):
                items.append(lines[i].strip()[2:])
                i += 1
            blocks.append('<ul style="line-height:1.8;margin:0 0 1em">'
                          + "".join(f"<li>{inline(it)}</li>" for it in items)
                          + "</ul>")
            continue
        para = [stripped]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r"[#>|]|!\[|```|\$\$|[-*]\s|\d+[.、]\s", lines[i].strip()):
            para.append(lines[i].strip())
            i += 1
        blocks.append(f'<p style="{CSS["p"]}">{inline("".join(para))}</p>')
    return "\n".join(blocks)


PAGE = """<!DOCTYPE html>
<meta charset="utf-8">
<title>{title} — paste into Zhihu</title>
<body style="margin:0;background:#f6f6f6">
<div style="max-width:690px;margin:0 auto;padding:24px;background:#fff;
font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;
font-size:15px;color:#1a1a1a">
{body}
</div>
</body>
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="article.md -> HTML that pastes into the Zhihu editor")
    parser.add_argument("markdown", type=Path)
    parser.add_argument("-o", "--out", type=Path,
                        help="defaults to article-zhihu.html beside the input")
    args = parser.parse_args()

    src = args.markdown
    if not src.is_file():
        print(f"no such file: {src}", file=sys.stderr)
        return 1
    text = src.read_text(encoding="utf-8")
    body = convert(text, src.parent)
    out = args.out or src.with_name(src.stem + "-zhihu.html")
    out.write_text(PAGE.format(title=html.escape(src.stem), body=body),
                   encoding="utf-8")

    counts = {
        "formulas": body.count(EQUATION),
        "tables": body.count("<table"),
        "table rows": body.count("<tr>"),
        "images": body.count("<img src=\"file://"),
        "headings": body.count("<h2") + body.count("<h3"),
        "missing images": body.count("本地文件缺失"),
    }
    leftovers = {mark: body.count(mark)
                 for mark in ("**", "|---", "## ") if mark in body}
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    print("  " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    if leftovers:
        print("  unconverted Markdown markers left: " + str(leftovers),
              file=sys.stderr)
    print("\nTo paste: open this file in a browser -> Cmd+A -> Cmd+C -> "
          "Cmd+V into the Zhihu editor."
          "\nFormulas are rendered by Zhihu's own equation endpoint; images "
          "use local file:// URLs, the browser puts the bitmaps on the "
          "clipboard too, and Zhihu usually re-uploads them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



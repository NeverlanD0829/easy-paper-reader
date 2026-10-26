#!/usr/bin/env python3
"""Stage 1 of the easy-paper-reader skill.

PDF -> source_bundle.json + rendered-pages/page-NNN.png

Produces everything downstream stages need: per-page text, a trustworthy
English section outline, a figure/table/equation inventory with trimmed
captions and geometry, and every in-text mention of each float.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ModuleNotFoundError:
    sys.exit("PyMuPDF missing. Run: python3 -m pip install 'pymupdf==1.26.*'")

ZOOM = 3.0  # 3x on 72dpi user space = 216 dpi; letter page -> 1836x2376

CAPTION_RE = re.compile(
    r"^\s*(?P<kind>Figure|Fig\.|Table|Tab\.)\s*(?P<num>\d{1,2})(?P<tail>.*)$", re.I)
PANEL_REJECT = re.compile(r"^\s*[a-z](?:\s*[,;:/–—-]|\b)")
PROSE_REJECT = re.compile(
    r"^\s*(?:,|;|and|or|to|in|from|for|of|with|shows?|showed|showing|depicts?"
    r"|illustrates?|indicates?|suggests?|we|which|that|reports?|presents?)\b", re.I)
POSITIVE_SEP = re.compile(r"^\s*(?:[.:|]|[–—-])")
VERB_OPENER = re.compile(
    r"^\s*(?:shows?|depicts?|summari[sz]es?|illustrates?|reports?|presents?|compares?)\b", re.I)

NUMBER_LINE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2}){0,2}|[A-H](?:\.\d{1,2}){0,2})\s*$")
PAGENO_LINE = re.compile(r"^\s*\d{1,3}\s*$")
UNNUMBERED_HEADINGS = (
    "ABSTRACT", "REFERENCES", "ACKNOWLEDGMENT", "ACKNOWLEDGMENTS",
    "ACKNOWLEDGEMENTS", "APPENDIX", "ETHICS STATEMENT",
    "REPRODUCIBILITY STATEMENT", "SUPPLEMENTARY MATERIAL", "LIMITATIONS",
)
EQUATION_TAG = re.compile(r"^\((\d{1,2})\)$")
MATH_FONT = re.compile(r"^(?:CM|MS|Math|STIX|Euclid)", re.I)
CAPTION_GAP = 0.45  # fraction of a line height that still counts as leading


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def capsish(text: str) -> bool:
    """True for an ALL-CAPS style section title line."""
    stripped = text.strip().rstrip(".")
    letters = [c for c in stripped if c.isalpha()]
    if len(letters) < 4 or not 3 < len(stripped) <= 72:
        return False
    return sum(c.isupper() for c in letters) / len(letters) >= 0.85


def normalise_title(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def page_lines(page) -> list[dict]:
    """One record per rendered text line, with geometry and dominant font."""
    records = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text = "".join(span["text"] for span in line["spans"])
            if not text.strip():
                continue
            records.append({
                "text": text,
                "bbox": list(line["bbox"]),
                "size": max(span["size"] for span in line["spans"]),
                "font": line["spans"][0]["font"],
            })
    records.sort(key=lambda r: (round(r["bbox"][1], 1), r["bbox"][0]))
    return records


# --------------------------------------------------------------------------- #
# section outline
# --------------------------------------------------------------------------- #
def numbered_headings(doc) -> list[dict]:
    """Pair a bare number line with the ALL-CAPS title line that follows it.

    LaTeX section commands emit the number and the title as separate text
    lines, so '3.3' on one line and 'VLM FOR HIGH-LEVEL PLANNING.' on the
    next is one heading. Validated to recover every heading of an ICLR-style
    paper with no false positives.
    """
    found = []
    for index in range(doc.page_count):
        lines = [l for l in doc[index].get_text("text").splitlines() if l.strip()]
        for position, line in enumerate(lines):
            match = NUMBER_LINE.match(line)
            if not match:
                continue
            number = match.group(1)
            head = number.split(".")[0]
            if head.isdigit() and not 1 <= int(head) <= 20:
                continue  # kills table cells such as '0.32'
            if position + 1 < len(lines) and capsish(lines[position + 1]):
                found.append({"number": number,
                              "title_caps": lines[position + 1].strip(),
                              "pdf_page": index + 1})
    return found


def unnumbered_headings(doc) -> list[dict]:
    found = []
    for index in range(doc.page_count):
        for line in doc[index].get_text("text").splitlines():
            bare = line.strip().rstrip(".").upper()
            if bare in UNNUMBERED_HEADINGS:
                found.append({"title_caps": bare, "pdf_page": index + 1})
    seen, unique = set(), []
    for item in found:
        if item["title_caps"] not in seen:
            seen.add(item["title_caps"])
            unique.append(item)
    return unique


def build_outline(doc) -> tuple[list[dict], str]:
    """PDF bookmarks give titles/levels/pages; body text gives the numbering.

    Fallback chain: toc+numbers -> toc only -> numbered headings only.
    """
    toc = doc.get_toc(simple=True)
    numbers = numbered_headings(doc)

    if toc and len(toc) == len(numbers):
        aligned = all(normalise_title(title) == normalise_title(found["title_caps"])
                      for (_, title, _), found in zip(toc, numbers))
        if aligned:
            outline = [{"number": found["number"], "title_en": title,
                        "title_caps": found["title_caps"], "level": level,
                        "pdf_page": page, "source": "toc+numbers"}
                       for (level, title, page), found in zip(toc, numbers)]
            return outline, "toc+numbers"

    if len(toc) >= 3:
        counters: dict[int, int] = {}
        outline = []
        for level, title, page in toc:
            counters[level] = counters.get(level, 0) + 1
            counters = {k: v for k, v in counters.items() if k <= level}
            number = ".".join(str(counters[l]) for l in sorted(counters))
            outline.append({"number": number, "title_en": title,
                            "title_caps": title.upper(), "level": level,
                            "pdf_page": page, "source": "toc"})
        return outline, "toc"

    if len(numbers) >= 3:
        outline = [{"number": f["number"], "title_en": f["title_caps"].title(),
                    "title_caps": f["title_caps"],
                    "level": f["number"].count(".") + 1,
                    "pdf_page": f["pdf_page"], "source": "numbered-text"}
                   for f in numbers]
        return outline, "numbered-text"

    return [], "unresolved"


# --------------------------------------------------------------------------- #
# figure / table captions
# --------------------------------------------------------------------------- #
def is_caption_anchor(tail: str) -> str | None:
    if PANEL_REJECT.match(tail) or PROSE_REJECT.match(tail):
        return None
    if POSITIVE_SEP.match(tail):
        # "Table 5." at the end of another caption is a cross-reference, not an
        # anchor. A real caption carries words after its separator.
        if len(POSITIVE_SEP.sub("", tail, count=1).strip()) < 8:
            return None
        return "caption-separator"
    if len(tail.strip()) >= 50 and not VERB_OPENER.match(tail):
        return "caption-title-like"
    return None


def caption_lines(lines: list[dict], start: int) -> list[int]:
    """Indices of the caption's own lines, in reading order.

    PyMuPDF emits a two-column page as one y-sorted stream, so the line after
    a right-column caption line is usually the *left* column's unrelated text.
    Filtering to the anchor's column first is what keeps a caption from either
    stopping at its first line or swallowing its neighbour.

    The paragraph that follows a caption is set in the same font at the same
    size, so only the gap tells them apart: leading inside a paragraph is about
    a point, while the skip before the next one is well over ten.
    """
    anchor = lines[start]
    size, font = anchor["size"], anchor["font"]
    x0, y0, x1, y1 = anchor["bbox"]
    height = max(8.0, y1 - y0)
    chosen, bottom, pitch = [start], y1, None
    for index in range(start + 1, len(lines)):
        line = lines[index]
        lx0, ly0, _, ly1 = line["bbox"]
        if ly0 < y0 - 1:
            continue  # above the anchor: another column, already placed
        if not -12 <= lx0 - x0 <= 60:
            continue  # different column
        gap = ly0 - bottom
        if gap > max(CAPTION_GAP * height, 1.8 * pitch if pitch else 0.0):
            break
        if abs(line["size"] - size) > 0.3:
            break
        if line["font"] != font and not MATH_FONT.match(line["font"]):
            break  # a bold run-in head starts the next body paragraph
        text = line["text"]
        if PAGENO_LINE.match(text) or capsish(text):
            break
        match = CAPTION_RE.match(text)
        if match and is_caption_anchor(match["tail"]):
            break
        chosen.append(index)
        if pitch is None:
            pitch = max(gap, 0.0)
        bottom = ly1
    return chosen


def caption_block(lines: list[dict], start: int) -> tuple[str, list[float], list[int]]:
    """Caption text, its bounding box, and the line indices it consumed."""
    chosen = caption_lines(lines, start)
    boxes = [lines[i]["bbox"] for i in chosen]
    box = [min(b[0] for b in boxes), min(b[1] for b in boxes),
           max(b[2] for b in boxes), max(b[3] for b in boxes)]
    caption = re.sub(r"\s+", " ", " ".join(lines[i]["text"] for i in chosen)).strip()
    return caption, [round(v, 2) for v in box], chosen


def extract_floats(doc) -> dict[str, list[dict]]:
    figures: dict[str, dict] = {}
    tables: dict[str, dict] = {}
    for index in range(doc.page_count):
        lines = page_lines(doc[index])
        consumed: set[int] = set()
        for position, line in enumerate(lines):
            if position in consumed:
                continue
            match = CAPTION_RE.match(line["text"])
            if not match:
                continue
            reason = is_caption_anchor(match["tail"])
            if not reason:
                continue
            caption, box, used = caption_block(lines, position)
            consumed.update(used)
            kind = "Figure" if match["kind"].lower().startswith(("fig",)) else "Table"
            key = f"{kind} {int(match['num'])}"
            bucket = figures if kind == "Figure" else tables
            if key in bucket:
                continue
            bucket[key] = {"id": key, "caption": caption, "pdf_page": index + 1,
                           "caption_bbox_pt": box, "anchor_reason": reason}
    order = lambda item: int(item["id"].split()[1])
    return {"figures": sorted(figures.values(), key=order),
            "tables": sorted(tables.values(), key=order)}


def extract_equations(doc) -> list[dict]:
    """Numbered display equations, found via their right-margin '(N)' tag.

    LaTeX sets the tag as its own text line against the right margin and the
    maths as separate lines to its left, so the tag is the only reliable
    anchor; the body is then whatever shares the tag's horizontal band.
    """
    found = []
    for index in range(doc.page_count):
        lines = page_lines(doc[index])
        for line in lines:
            tag = EQUATION_TAG.match(line["text"].strip())
            if not tag:
                continue
            tx0, ty0, _, ty1 = line["bbox"]
            body, box = [], [tx0, ty0, tx0, ty1]
            for other in lines:
                ox0, oy0, ox1, oy1 = other["bbox"]
                if other is line or ox1 > tx0 + 1:
                    continue
                if not ty0 - 11 <= oy0 <= ty1 + 6:
                    continue
                if not (MATH_FONT.match(other["font"])
                        or len(other["text"].strip()) <= 20):
                    continue  # prose that merely shares the band
                body.append(other["text"])
                box = [min(box[0], ox0), min(box[1], oy0),
                       max(box[2], ox1), max(box[3], oy1)]
            if not body:
                continue
            context = re.sub(r"[\x00-\x1f\x7f]", "", " ".join(body))
            found.append({"id": f"Equation {int(tag.group(1))}",
                          "context": re.sub(r"\s+", " ", context).strip(),
                          "pdf_page": index + 1,
                          "bbox_pt": [round(v, 2) for v in box]})
    seen, unique = set(), []
    for item in found:
        if item["id"] not in seen:
            seen.add(item["id"])
            unique.append(item)
    return sorted(unique, key=lambda e: int(e["id"].split()[1]))


# --------------------------------------------------------------------------- #
# in-text mentions
# --------------------------------------------------------------------------- #
def section_for_page(outline: list[dict], page: int) -> str | None:
    """The last section to *start* on or before this page — a hint, not a fact.

    A page usually spans a heading, so a mention sitting above that heading is
    attributed to the section that follows it. Downstream the float belongs
    wherever the authors argue from it, which only reading the text settles.
    """
    current = None
    for entry in outline:
        if entry["pdf_page"] <= page:
            current = entry["number"]
        else:
            break
    return current


def find_mentions(doc, inventory: dict, outline: list[dict]) -> list[dict]:
    """Every non-caption sentence that references a float.

    The caption says what the picture is; the body text says what the authors
    use it to argue. The explanation stage needs the second one.
    """
    floats = inventory["figures"] + inventory["tables"]
    captions = [item["caption"] for item in floats if len(item["caption"]) > 30]
    results = []
    for item in floats:
        kind, number = item["id"].split()
        alternatives = "Figure|Fig\\." if kind == "Figure" else "Table|Tab\\."
        pattern = re.compile(rf"(?<![A-Za-z])(?:{alternatives})\s*{number}(?![0-9])")
        mentions, seen = [], set()
        for index in range(doc.page_count):
            text = re.sub(r"\s+", " ", doc[index].get_text("text"))
            for hit in pattern.finditer(text):
                left = max(text.rfind(". ", 0, hit.start()) + 2, 0)
                right = text.find(". ", hit.end())
                window = text[left:right + 1 if right > 0 else len(text)].strip()
                if len(window) <= 20 or window in seen:
                    continue
                # A caption's own text, and any cross-reference buried inside
                # another caption, are not the body argument we are after.
                if any(window[:80] in caption for caption in captions):
                    continue
                seen.add(window)
                mentions.append({"pdf_page": index + 1,
                                 "section_hint": section_for_page(outline, index + 1),
                                 "window": window[:600]})
        results.append({"id": item["id"], "in_text_count": len(mentions),
                        "mentions": mentions[:6],
                        "fallback": None if mentions else "section-body"})
    return results


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def render_pages(doc, outdir: Path, zoom: float) -> list[str]:
    target = outdir / "rendered-pages"
    target.mkdir(parents=True, exist_ok=True)
    matrix = fitz.Matrix(zoom, zoom)
    written = []
    for index in range(doc.page_count):
        name = f"page-{index + 1:03d}.png"
        doc[index].get_pixmap(matrix=matrix).save(target / name)
        written.append(f"rendered-pages/{name}")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("-o", "--outdir", type=Path, required=True)
    parser.add_argument("--zoom", type=float, default=ZOOM)
    args = parser.parse_args()

    if not args.pdf.is_file():
        sys.exit(f"not a file: {args.pdf}")
    args.outdir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(args.pdf)

    pages = [{"pdf_page": i + 1, "text": doc[i].get_text("text")}
             for i in range(doc.page_count)]
    for page in pages:
        page["character_count"] = len(page["text"])
    thin = sum(1 for p in pages if p["character_count"] < 200)
    quality = "scanned-or-cid" if thin > 0.3 * len(pages) else "ok"

    outline, method = build_outline(doc)
    inventory = extract_floats(doc)
    inventory["equations"] = extract_equations(doc)
    mentions = find_mentions(doc, inventory, outline)
    rendered = render_pages(doc, args.outdir, args.zoom)
    first = doc[0].rect

    bundle = {
        "schema_version": "2.0",
        "source_path": str(args.pdf),
        "source_sha256": sha256(args.pdf),
        "metadata": {k: doc.metadata.get(k) for k in ("title", "author", "producer")},
        "page_count": doc.page_count,
        "page_size_pt": [round(first.width, 2), round(first.height, 2)],
        "render": {"zoom": args.zoom, "dpi": round(72 * args.zoom),
                   "pages": rendered},
        "outline": outline,
        "outline_method": method,
        "outline_confirmed": False,
        "unnumbered_sections": unnumbered_headings(doc),
        "evidence_inventory": inventory,
        "mentions": mentions,
        "pages": pages,
        "extraction": {"engine": f"PyMuPDF {fitz.pymupdf_version}",
                       "text_quality": quality},
    }
    out = args.outdir / "source_bundle.json"
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"{out}")
    print(f"  pages      {doc.page_count} rendered at {round(72 * args.zoom)} dpi")
    print(f"  outline    {len(outline)} headings via {method}")
    print(f"  floats     {len(inventory['figures'])} figures, "
          f"{len(inventory['tables'])} tables, {len(inventory['equations'])} equations")
    zero = [m["id"] for m in mentions if not m["in_text_count"]]
    if zero:
        print(f"  no in-text mention: {', '.join(zero)} (use section-body fallback)")
    if quality != "ok":
        print("  WARNING text layer looks scanned; captions may be unusable")
    if method == "unresolved":
        print("  ERROR could not recover a section outline")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

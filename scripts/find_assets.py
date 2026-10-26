#!/usr/bin/env python3
"""Stage 2 of the easy-paper-reader skill.

source_bundle.json -> crop_plan.json

Proposes one crop rectangle per figure and table. The caption is the only
reliable anchor a PDF gives you, so each rectangle grows outward from its
caption until it hits prose or a neighbouring float.

The output is a *proposal*. Stage 3 crops it and the model must look at the
result; low-confidence entries are the ones to look at first.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ModuleNotFoundError:
    sys.exit("PyMuPDF missing. Run: python3 -m pip install 'pymupdf==1.26.*'")

PAD_PT = 12.0          # breathing room around the union of caption and body
MARGIN_SLACK = 2.0     # how far ink may stick out of the text column
PROSE_SLACK = 0.5      # size below body text that still counts as prose
SIDEBYSIDE_DY = 30.0   # captions this close vertically sit side by side
SIDEBYSIDE_OVERLAP = 0.2
FULL_WIDTH_RATIO = 0.62
BAND_SLACK = 10.0      # a booktabs rule can sit just outside the text lines
FURNITURE_H = 1.5      # a header/footer rule is a hairline outside the text


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    """Fraction of the shorter interval that the two intervals share."""
    span = min(a1, b1) - max(a0, b0)
    shortest = min(a1 - a0, b1 - b0)
    return 0.0 if shortest <= 0 else max(0.0, span) / shortest


def union(boxes: list[list[float]]) -> list[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


# --------------------------------------------------------------------------- #
# page geometry
# --------------------------------------------------------------------------- #
def body_size(doc) -> float:
    counter: collections.Counter = collections.Counter()
    for index in range(doc.page_count):
        for block in doc[index].get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                if "".join(s["text"] for s in line["spans"]).strip():
                    counter[round(max(s["size"] for s in line["spans"]), 1)] += 1
    return counter.most_common(1)[0][0] if counter else 10.0


def text_lines(page) -> list[dict]:
    records = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text = "".join(s["text"] for s in line["spans"])
            if not text.strip():
                continue
            box = [round(v, 2) for v in line["bbox"]]
            records.append({
                "text": text.strip(),
                "bbox": box,
                "size": round(max(s["size"] for s in line["spans"]), 1),
                # Set sideways: an arXiv margin stamp, or a rotated table
                # header. Never part of the running text, so it must not
                # define the column or block a crop.
                "rotated": (box[3] - box[1]) > 2.0 * (box[2] - box[0]),
            })
    return records


def is_prose(line: dict, body: float) -> bool:
    return (not line["rotated"] and line["size"] >= body - PROSE_SLACK
            and len(line["text"]) >= 25)


def text_column(lines: list[dict], page, body: float) -> list[float]:
    """Left/right edges from the running text, top/bottom from the whole page.

    The horizontal edges are the useful part: they are what tells an
    oversized background frame apart from real artwork.
    """
    upright = [l["bbox"] for l in lines if not l["rotated"]]
    prose = [l["bbox"] for l in lines if is_prose(l, body)] or upright
    if not upright:
        return [0.0, 0.0, page.rect.width, page.rect.height]
    sides, extent = union(prose), union(upright)
    return [sides[0], extent[1], sides[2], extent[3]]


def ink_items(page, lines: list[dict], column: list[float],
              body: float) -> list[list[float]]:
    """Everything that is part of a float rather than running text.

    Oversized vector rectangles are matplotlib/TikZ background frames: they
    reach past the text column and, left in, drag a crop sideways into the
    neighbouring column. Their visible content is covered by the other items.
    """
    cx0, cy0, cx1, cy1 = column
    items: list[list[float]] = []

    def inside(box) -> bool:
        return box[0] >= cx0 - MARGIN_SLACK and box[2] <= cx1 + MARGIN_SLACK

    def furniture(box) -> bool:
        """A running header or footer rule: a hairline clear of all the text."""
        return box[3] - box[1] < FURNITURE_H and (box[3] < cy0 or box[1] > cy1)

    for info in page.get_images(full=True):
        try:
            box = [round(v, 2) for v in fitz.Rect(page.get_image_bbox(info))]
        except (ValueError, RuntimeError):
            continue
        if box[2] - box[0] > 2 and box[3] - box[1] > 2 and inside(box):
            items.append(box)
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.width < 1.0 and rect.height < 1.0:
            continue
        box = [round(v, 2) for v in rect]
        if inside(box) and not furniture(box):
            items.append(box)
    for line in lines:
        if line["size"] < body - PROSE_SLACK:
            items.append(line["bbox"])
    return items


def content_column(column: list[float], items: list[list[float]]) -> list[float]:
    """Widen the column vertically to wherever the floats actually reach.

    A figure parked at the top of a page starts above its first text line, so
    a band ceiling taken from the text alone slices off its first row.
    """
    if not items:
        return column
    return [column[0], min(column[1], min(b[1] for b in items)),
            column[2], max(column[3], max(b[3] for b in items))]


# --------------------------------------------------------------------------- #
# which side of its caption does a float live on
# --------------------------------------------------------------------------- #
def ink_mass(items: list[list[float]], y0: float, y1: float,
             x0: float, x1: float) -> float:
    total = 0.0
    for box in items:
        middle = (box[1] + box[3]) / 2
        if y0 <= middle <= y1 and overlap(box[0], box[2], x0, x1) > 0.1:
            total += (box[2] - box[0]) * (box[3] - box[1])
    return total


def caption_side(items: list[list[float]], caption: list[float],
                 column: list[float]) -> str:
    """'above' means the float body sits above its caption."""
    x0, x1 = column[0], column[2]
    above = ink_mass(items, column[1], caption[1], x0, x1)
    below = ink_mass(items, caption[3], column[3], x0, x1)
    return "above" if above >= below else "below"


def vote_sides(pages: dict, floats: list[dict]) -> dict[str, str]:
    """Decide per kind, using only pages that hold a single float.

    A page with one float cannot be ambiguous, and LaTeX puts a given kind of
    caption on the same side throughout a paper. Pages with several floats
    then inherit the answer instead of guessing from interleaved ink.
    """
    tally: dict[str, collections.Counter] = {
        "Figure": collections.Counter(), "Table": collections.Counter()}
    counts = collections.Counter(item["pdf_page"] for item in floats)
    for item in floats:
        if counts[item["pdf_page"]] != 1:
            continue
        page = pages[item["pdf_page"]]
        side = caption_side(page["ink"], item["caption_bbox_pt"], page["column"])
        tally[item["id"].split()[0]][side] += 1
    decided = {}
    for kind, votes in tally.items():
        decided[kind] = votes.most_common(1)[0][0] if votes else "above"
    return decided


# --------------------------------------------------------------------------- #
# horizontal band
# --------------------------------------------------------------------------- #
def siblings(caption: list[float], others: list[list[float]]) -> list[list[float]]:
    """Captions that sit beside this one rather than above or below it."""
    beside = []
    for other in others:
        gap = max(caption[1] - other[3], other[1] - caption[3], 0.0)
        if gap < SIDEBYSIDE_DY and overlap(
                caption[0], caption[2], other[0], other[2]) < SIDEBYSIDE_OVERLAP:
            beside.append(other)
    return beside


def x_band(caption: list[float], others: list[list[float]],
           column: list[float]) -> tuple[float, float, str]:
    """How wide the float is allowed to be, and why.

    A caption is usually narrower than its artwork, so the default is the
    whole text column. Only a neighbour sharing the row can shrink it, and
    then the boundary is the midpoint of the gap between the two captions.
    """
    low, high = column[0], column[2]
    beside = siblings(caption, others)
    if not beside:
        if caption[2] - caption[0] < FULL_WIDTH_RATIO * (high - low):
            return caption[0] - PAD_PT, caption[2] + PAD_PT, "caption-width"
        return low, high, "full-column"
    for other in beside:
        if other[2] <= caption[0]:
            low = max(low, (other[2] + caption[0]) / 2)
        elif other[0] >= caption[2]:
            high = min(high, (caption[2] + other[0]) / 2)
    return low, high, "split-from-neighbour"


# --------------------------------------------------------------------------- #
# vertical band and the final rectangle
# --------------------------------------------------------------------------- #
def blockers(page: dict, caption: list[float], band: tuple[float, float],
             body: float) -> list[list[float]]:
    low, high = band
    found = [b for b in page["captions"] if b != caption
             and overlap(b[0], b[2], low, high) > 0.1]
    for line in page["lines"]:
        box = line["bbox"]
        if not is_prose(line, body):
            continue
        if any(overlap(box[1], box[3], c[1], c[3]) > 0.5 for c in page["captions"]):
            continue  # a caption line, already handled
        if overlap(box[0], box[2], low, high) > 0.1:
            found.append(box)
    return found


def body_box(page: dict, caption: list[float], side: str,
             band: tuple[float, float],
             body: float) -> tuple[list[float] | None, int, list[float]]:
    """The float's ink, and the box the crop is allowed to occupy.

    The allowance matters as much as the ink: padding a rectangle outward
    without it is what drags a neighbouring line of prose into the picture.
    """
    low, high = band
    walls = blockers(page, caption, band, body)
    above = max([b[3] for b in walls if b[3] <= caption[1] + 2.0],
                default=page["column"][1] - BAND_SLACK)
    below = min([b[1] for b in walls if b[1] >= caption[3] - 2.0],
                default=page["column"][3] + BAND_SLACK)
    top, bottom = (above, caption[1]) if side == "above" else (caption[3], below)
    chosen = []
    for box in page["ink"]:
        middle = (box[1] + box[3]) / 2
        if top - 1 <= middle <= bottom + 1 and overlap(box[0], box[2], low, high) > 0.1:
            chosen.append([max(box[0], low), max(box[1], top),
                           min(box[2], high), min(box[3], bottom)])
    chosen = [b for b in chosen if b[2] > b[0] and b[3] > b[1]]
    # On the far side of the caption the next float's artwork is often closer
    # than any prose, so the padding has to stop at ink too.
    far = [b for b in page["ink"] if overlap(b[0], b[2], low, high) > 0.1]
    if side == "above":
        edge = min([b[1] for b in far if b[1] >= caption[3] - 1.0], default=below)
        allow = [low, above, high, max(caption[3], min(below, edge - 2.0))]
    else:
        edge = max([b[3] for b in far if b[3] <= caption[1] + 1.0], default=above)
        allow = [low, min(caption[1], max(above, edge + 2.0)), high, below]
    return (union(chosen) if chosen else None), len(chosen), allow


def plan_float(item: dict, page: dict, side: str, body: float,
               zoom: float, page_rect) -> dict:
    caption = item["caption_bbox_pt"]
    low, high, band_reason = x_band(caption, page["captions"], page["column"])
    box, parts, allow = body_box(page, caption, side, (low, high), body)
    notes = [f"caption-{side}", band_reason]
    if box is None:
        box = caption[:]
        notes.append("no-body-ink")
    rect = union([box, caption])
    rect = [max(rect[0] - PAD_PT, allow[0]), max(rect[1] - PAD_PT, allow[1]),
            min(rect[2] + PAD_PT, allow[2]), min(rect[3] + PAD_PT, allow[3])]
    rect = [max(rect[0], 0.0), max(rect[1], 0.0),
            min(rect[2], page_rect.width), min(rect[3], page_rect.height)]
    height = rect[3] - rect[1]
    if parts == 0:
        confidence = "low"
    elif parts >= 3 and height > 2.2 * (caption[3] - caption[1]):
        confidence = "high"
    else:
        confidence = "medium"
    if height > 0.85 * page_rect.height:
        confidence, _ = "low", notes.append("suspiciously-tall")
    return {
        "id": item["id"],
        "kind": item["id"].split()[0].lower(),
        "pdf_page": item["pdf_page"],
        "caption": item["caption"],
        "caption_bbox_pt": caption,
        "rect_pt": [round(v, 2) for v in rect],
        "rect_px": [round(v * zoom) for v in rect],
        # Round inward: one per-mille is nearly a point, and rounding outward
        # lets the descenders of a blocking line back into the picture.
        "rect_norm": [math.ceil(rect[0] / page_rect.width * 1000),
                      math.ceil(rect[1] / page_rect.height * 1000),
                      math.floor(rect[2] / page_rect.width * 1000),
                      math.floor(rect[3] / page_rect.height * 1000)],
        "ink_parts": parts,
        "confidence": confidence,
        "reason": ", ".join(notes),
        "verified_by": None,
    }


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="source_bundle.json from stage 1")
    parser.add_argument("-o", "--out", type=Path,
                        help="defaults to crop_plan.json beside the bundle")
    args = parser.parse_args()

    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    out = args.out or args.bundle.parent / "crop_plan.json"
    pdf = Path(bundle["source_path"])
    if not pdf.is_file():
        sys.exit(f"source PDF moved or missing: {pdf}")
    doc = fitz.open(pdf)
    zoom = bundle["render"]["zoom"]

    inventory = bundle["evidence_inventory"]
    floats = inventory["figures"] + inventory["tables"]
    body = body_size(doc)

    pages: dict[int, dict] = {}
    for number in sorted({item["pdf_page"] for item in floats}):
        page = doc[number - 1]
        lines = text_lines(page)
        column = text_column(lines, page, body)
        ink = ink_items(page, lines, column, body)
        pages[number] = {
            "lines": lines,
            "column": content_column(column, ink),
            "ink": ink,
            "captions": [item["caption_bbox_pt"] for item in floats
                         if item["pdf_page"] == number],
            "rect": page.rect,
        }

    sides = vote_sides(pages, floats)
    counts = collections.Counter(item["pdf_page"] for item in floats)
    plan = []
    for item in sorted(floats, key=lambda f: (f["id"].split()[0],
                                              int(f["id"].split()[1]))):
        page = pages[item["pdf_page"]]
        if counts[item["pdf_page"]] == 1:
            side = caption_side(page["ink"], item["caption_bbox_pt"], page["column"])
        else:
            side = sides[item["id"].split()[0]]
        plan.append(plan_float(item, page, side, body, zoom, page["rect"]))

    payload = {
        "schema_version": "1.0",
        "source_bundle": str(args.bundle),
        "source_sha256": bundle["source_sha256"],
        "render": {"zoom": zoom, "page_size_pt": bundle["page_size_pt"]},
        "body_text_size_pt": body,
        "caption_side": sides,
        "note": "rect_norm is per-mille of the page; use it when reading "
                "coordinates off a rendered page at any display scale.",
        "crops": plan,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"{out}")
    print(f"  body text  {body} pt   caption side {sides}")
    print(f"  crops      {len(plan)}")
    for level in ("low", "medium"):
        flagged = [c["id"] for c in plan if c["confidence"] == level]
        if flagged:
            print(f"  {level:6} confidence: {', '.join(flagged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Stage 3 of the easy-paper-reader skill.

crop_plan.json + rendered-pages/ -> assets/*.png + screenshot-index.json

Pure mechanics: no geometry decisions are made here. Edit rect_norm in
crop_plan.json and re-run to redo a crop, which is how the model fixes a
rectangle after looking at the result.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from PIL import Image
except ModuleNotFoundError:
    sys.exit("Pillow missing. Run: python3 -m pip install pillow")

MAX_WIDTH = 1600       # zhihu downsamples anything wider
MAX_BYTES = 5_000_000


def crop_box(entry: dict, size: tuple[int, int]) -> tuple[int, int, int, int]:
    """rect_norm is authoritative; rect_px is only a convenience echo.

    Per-mille coordinates survive the image being rescaled for display, so a
    rectangle the model read off a preview still lands correctly on the
    full-resolution page.
    """
    width, height = size
    x0, y0, x1, y1 = entry["rect_norm"]
    box = (max(0, round(x0 * width / 1000)), max(0, round(y0 * height / 1000)),
           min(width, round(x1 * width / 1000)), min(height, round(y1 * height / 1000)))
    if box[2] - box[0] < 8 or box[3] - box[1] < 8:
        raise ValueError(f"{entry['id']}: degenerate rect_norm {entry['rect_norm']}")
    return box


def save(image: Image.Image, path: Path) -> dict:
    """Write a crop, shrinking it only if zhihu would refuse it."""
    out, scaled = image.convert("RGB"), False
    if out.width > MAX_WIDTH:
        ratio = MAX_WIDTH / out.width
        out = out.resize((MAX_WIDTH, round(out.height * ratio)), Image.LANCZOS)
        scaled = True
    out.save(path, optimize=True)
    for quality in (None, 92, 82, 72):
        if path.stat().st_size <= MAX_BYTES:
            break
        path.unlink()
        path = path.with_suffix(".jpg")
        out.save(path, quality=quality or 92, optimize=True)
        scaled = True
    return {"path": path, "size": (out.width, out.height), "downscaled": scaled}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path, help="crop_plan.json from stage 2")
    parser.add_argument("-d", "--workdir", type=Path,
                        help="holds rendered-pages/; defaults to the plan's folder")
    parser.add_argument("--only", nargs="*", metavar="ID",
                        help="re-crop just these ids, e.g. --only 'Figure 3'")
    args = parser.parse_args()

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    workdir = args.workdir or args.plan.parent
    pages_dir = workdir / "rendered-pages"
    if not pages_dir.is_dir():
        sys.exit(f"no rendered pages at {pages_dir}; run prepare_paper.py first")
    assets = workdir / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    index_path = workdir / "screenshot-index.json"
    records: dict[str, dict] = {}
    if index_path.is_file():
        old = json.loads(index_path.read_text(encoding="utf-8"))
        records = {r["id"]: r for r in old.get("assets", [])}

    wanted = set(args.only) if args.only else None
    written = 0
    for entry in plan["crops"]:
        if wanted and entry["id"] not in wanted:
            continue
        kind, number = entry["id"].split()
        page_png = pages_dir / f"page-{entry['pdf_page']:03d}.png"
        if not page_png.is_file():
            sys.exit(f"missing {page_png}")
        with Image.open(page_png) as page:
            box = crop_box(entry, page.size)
            result = save(page.crop(box), assets / f"{kind.lower()}-{int(number):02d}.png")
            source = list(page.size)
        records[entry["id"]] = {
            "id": entry["id"],
            "file": f"assets/{result['path'].name}",
            "pdf_page": entry["pdf_page"],
            "caption": entry["caption"],
            "crop_box_pixels": list(box),
            "rect_norm": entry["rect_norm"],
            "source_pixels": source,
            "output_pixels": list(result["size"]),
            "downscaled": result["downscaled"],
            "confidence": entry["confidence"],
            "reason": entry["reason"],
            "verified_by": entry.get("verified_by"),
            "processing": "Crop only; original figure and caption retained.",
        }
        written += 1

    order = lambda r: (r["id"].split()[0], int(r["id"].split()[1]))
    index_path.write_text(json.dumps({
        "schema_version": "1.0",
        "source_bundle": plan["source_bundle"],
        "source_sha256": plan["source_sha256"],
        "render": plan["render"],
        "zhihu_limits": {"max_width_px": MAX_WIDTH, "max_bytes": MAX_BYTES},
        "assets": sorted(records.values(), key=order),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{assets}  ({written} cropped)")
    print(f"{index_path}")
    unverified = [r["id"] for r in records.values() if not r["verified_by"]]
    if unverified:
        print(f"  NOT YET VIEWED: {', '.join(sorted(unverified))}")
        print("  Read each PNG, then set verified_by in crop_plan.json "
              "(or fix rect_norm and re-run with --only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

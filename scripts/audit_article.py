#!/usr/bin/env python3
"""Stage 7 of the easy-paper-reader skill.

article.md -> audit-report.json

Checks the things that separate a reading from a paraphrase: every figure
cropped, viewed, oriented and read with numbers; every innovation tied to
evidence; every Chinese heading traceable to an English one. Voice is a
separate gate — see check_tone.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# The four duties of a real explanation, checked by what the prose does rather
# than by the labels it wears. Demanding the labels verbatim is what turns ten
# figure blocks into ten copies of one template; a researcher writes the same
# four things as continuous prose. `claim` is the one duty no regex can see —
# references/figure-explain-spec.md carries it instead.
EXPLANATION_DUTIES = (
    ("orientation", r"横轴|纵轴|横坐标|纵坐标|每一[行列组]|每[个条]|子图|左(图|边|侧|起)|"
                    r"右(图|边|侧)|上(图|半|面)|下(图|半|面)|图例|柱|曲线|折线|色|"
                    r"\([a-dA-D]\)|（[a-dA-D]）|这一列|这一行|分组"),
    ("direction", r"越[高低大小长短多少快慢远近靠前后左右]+(越)?好|越好|更好|"
                  r"方向.{0,4}好|好的方向|理想(值|情况)|满分|上限"),
    ("limits", r"没能|不能说明|说明不了|无法|无从|看不出|看不到|局限|只是定性|不承担|"
               r"未(标|给出|报告|说明|控制|区分|验证|公布)|"
               r"没有(标|给出|报告|说明|控制|区分|验证|公布|误差|随机)|"
               r"没有[^，。；]{0,8}(案例|对照|指标|统计|基线|方差|置信|图例|种子|量化)|"
               r"作者挑|挑出来的|自选|不可(比|直接)|不能(跨|直接|据此)|存疑|偏(小|高|低)|"
               r"样本(量|数)|单次|一次(运行|实验)|误差"),
)
BLOCK_NUMBER_RE = re.compile(
    r"\d+(?:\.\d+)?"
    # A schematic has nothing to measure, but it still has countable parts, and
    # Chinese prose writes small counts as characters. Demanding Arabic digits
    # was pushing「四行模板」toward「4 行模板」for no reader's benefit.
    r"|[一二三四五六七八九十百两]+(?=[帧行列个条组张块幅处类维步次档根段项])")
MIN_BLOCK_NUMBERS = 2
IMAGE_RE = re.compile(r"!\[[^\]]*\]\((assets/[^)\s]+)\)")
HEADING_RE = re.compile(r"^(#{2,3})\s+(.*)$", re.M)
# A heading should say what the section is about. Repeating the paper's English
# heading after it -- 「这篇论文要解决什么问题（1. Introduction）」-- turns the
# article into a bilingual table of contents and reads like a translation
# artifact. Alignment with the paper is verified against outline-map.json, where
# it costs the reader nothing. Short all-caps parentheticals (（WAM）, （VPP2）)
# are terminology, not section titles, so they have to survive this.
ENGLISH_TAIL = re.compile(
    r"[（(]\s*(?:"
    r"\d+(?:\.\d+)*\s*\.?\s+[A-Za-z][^）)]*"              # 1. Introduction
    r"|[A-Za-z][^）)\s]*(?:\s+[A-Za-z0-9][^）)\s]*)+"      # Related Works
    r")[）)]\s*$")
ENUMERATOR = re.compile(r"^(?:[一二三四五六七八九十百]+、|\d+(?:\.\d+)*)\s*")
# The last section is a plain 总结 and it is short. A long closing section turns
# into a second article: the per-figure blocks have already carried the
# criticism, so repeating it in a numbered list of six is the place where a
# reading starts padding.
CLOSING = "总结"
CLOSING_BUDGET = 1200
NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?\s*(?:%|个?百分点|分)")
# A number is attributed to the figure or table the reader can actually see in
# the article -- 图 3, 表 2 -- not to a page of a PDF they do not have open.
ANCHOR_RE = re.compile(r"[图表]\s*\d+")
ALLOWED_INVENTED = 2


def add(findings: list[dict], level: str, code: str, message: str) -> None:
    findings.append({"level": level, "code": code, "message": message})


def load(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def sections(article: str) -> list[tuple[str, str]]:
    """Each heading with the body that follows it."""
    marks = list(HEADING_RE.finditer(article))
    out = []
    for position, mark in enumerate(marks):
        end = marks[position + 1].start() if position + 1 < len(marks) else len(article)
        out.append((mark.group(2).strip(), article[mark.end():end]))
    return out


def figure_blocks(article: str) -> dict[str, str]:
    """The prose that follows each embedded image, up to the next image."""
    hits = list(IMAGE_RE.finditer(article))
    blocks = {}
    for position, hit in enumerate(hits):
        end = hits[position + 1].start() if position + 1 < len(hits) else len(article)
        blocks[hit.group(1)] = article[hit.end():end]
    return blocks


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def check_coverage(findings: list[dict], article: str, bundle: dict) -> dict:
    used = set(IMAGE_RE.findall(article))
    figures = bundle["evidence_inventory"]["figures"]
    missing = []
    for item in figures:
        number = int(item["id"].split()[1])
        if not any(f"figure-{number:02d}." in path for path in used):
            missing.append(item["id"])
    if missing:
        add(findings, "error", "figures_coverage",
            f"figure(s) never embedded in the article: {', '.join(missing)}. "
            "Every figure must be shown and explained.")
    else:
        add(findings, "pass", "figures_coverage",
            f"all {len(figures)} figures embedded")
    return {"figures_total": len(figures), "images_used": len(used),
            "figures_missing": len(missing)}


def check_explained(findings: list[dict], article: str) -> dict:
    blocks = figure_blocks(article)
    incomplete = {}
    for path, body in blocks.items():
        if "figure-" not in path:
            continue  # tables carry a lighter treatment by design
        absent = [name for name, pattern in EXPLANATION_DUTIES
                  if not re.search(pattern, body)]
        if len(BLOCK_NUMBER_RE.findall(body)) < MIN_BLOCK_NUMBERS:
            absent.append("reading")
        if absent:
            incomplete[path] = absent
    if incomplete:
        for path, absent in sorted(incomplete.items()):
            add(findings, "error", "figure_explained",
                f"{path}: the prose never does {', '.join(absent)} — see "
                "references/figure-explain-spec.md")
    else:
        add(findings, "pass", "figure_explained",
            "every embedded figure is oriented, read with numbers and bounded")
    return {"figure_blocks": sum(1 for p in blocks if "figure-" in p),
            "figure_blocks_incomplete": len(incomplete)}


def check_screenshots(findings: list[dict], article: str, workdir: Path,
                      index: dict | None) -> dict:
    used = set(IMAGE_RE.findall(article))
    if index is None:
        add(findings, "error", "crop_provenance",
            "screenshot-index.json missing; crops have no provenance")
        add(findings, "error", "figure_viewed",
            "screenshot-index.json missing; cannot prove the crops were viewed")
        return {"assets_recorded": 0, "assets_unviewed": len(used)}

    records = {record["file"]: record for record in index["assets"]}
    orphans = sorted(used - set(records))
    if orphans:
        add(findings, "error", "crop_provenance",
            f"embedded without a provenance record: {', '.join(orphans)}")
    else:
        add(findings, "pass", "crop_provenance",
            f"all {len(used)} embedded images have provenance")

    unviewed = sorted(path for path in used & set(records)
                      if records[path].get("verified_by") != "model-viewed")
    if unviewed:
        add(findings, "error", "figure_viewed",
            f"not marked verified_by=model-viewed: {', '.join(unviewed)}. "
            "Read each crop before writing about it.")
    else:
        add(findings, "pass", "figure_viewed",
            "every embedded crop was viewed before being written about")

    limits = index.get("zhihu_limits", {})
    max_width = limits.get("max_width_px", 1600)
    max_bytes = limits.get("max_bytes", 5_000_000)
    oversized = []
    for path in sorted(used & set(records)):
        record = records[path]
        on_disk = workdir / path
        size = on_disk.stat().st_size if on_disk.is_file() else 0
        if record["output_pixels"][0] > max_width or size > max_bytes:
            oversized.append(f"{path} ({record['output_pixels'][0]}px, {size}B)")
    if oversized:
        add(findings, "warning", "zhihu_assets",
            f"beyond zhihu limits: {', '.join(oversized)}")
    else:
        add(findings, "pass", "zhihu_assets", "all images within zhihu limits")
    return {"assets_recorded": len(records), "assets_unviewed": len(unviewed),
            "assets_oversized": len(oversized)}


def heading_key(title: str) -> str:
    """A heading reduced to the part that identifies the section."""
    text = ENGLISH_TAIL.sub("", title.lstrip("# ").strip()).strip()
    return ENUMERATOR.sub("", text).strip()


def same_section(one: str, other: str) -> bool:
    """Headings may be reworded while writing; the head has to survive."""
    return bool(one) and bool(other) and (one.startswith(other)
                                          or other.startswith(one))


def check_outline(findings: list[dict], article: str, bundle: dict,
                  workdir: Path) -> dict:
    """Chinese headings must track the paper's sections 1:1 and in order."""
    titles = [title for title, _ in sections(article)]
    with_tail = [title for title in titles if ENGLISH_TAIL.search(title)]
    if with_tail:
        add(findings, "error", "no_english_tails",
            f"heading(s) still repeat the paper's English title: "
            f"{', '.join(with_tail)}. Say what the section is about; the "
            "mapping lives in outline-map.json.")
    else:
        add(findings, "pass", "no_english_tails",
            "no heading carries the English original in parentheses")

    outline = bundle["outline"]
    mapping = load(workdir / "outline-map.json")
    planned = [heading_key(entry["heading_zh"])
               for entry in (mapping or {}).get("sections", [])
               if entry.get("heading_zh")]
    if not planned:
        add(findings, "warning", "outline_alignment",
            "no outline-map.json with sections[].heading_zh; heading order "
            "cannot be checked against the paper (run stage 5)")
        return {"headings": len(titles), "headings_english_tails": len(with_tail),
                "headings_invented": None, "outline_entries": len(outline),
                "outline_confirmed": bundle.get("outline_confirmed", False)}

    position, out_of_order, invented = -1, [], []
    matched = set()
    for title in titles:
        key = heading_key(title)
        hit = next((i for i, want in enumerate(planned)
                    if same_section(key, want)), None)
        if hit is None:
            invented.append(title)
            continue
        matched.add(hit)
        if hit < position:
            out_of_order.append(title)
        position = max(position, hit)
    missing = [planned[i] for i in range(len(planned)) if i not in matched]

    if out_of_order:
        add(findings, "error", "outline_alignment",
            f"heading(s) out of paper order: {', '.join(out_of_order)}")
    elif missing:
        add(findings, "error", "outline_alignment",
            f"planned section(s) never written: {', '.join(missing)}")
    else:
        add(findings, "pass", "outline_alignment",
            f"{len(matched)} of {len(planned)} mapped sections present, in "
            "paper order")

    if len(invented) > ALLOWED_INVENTED:
        add(findings, "error", "no_invented_sections",
            f"{len(invented)} headings are in no outline-map section "
            f"(at most {ALLOWED_INVENTED} allowed): {', '.join(invented)}")
    else:
        add(findings, "pass", "no_invented_sections",
            f"{len(invented)} invented section(s), within the allowance")
    return {"headings": len(titles), "headings_english_tails": len(with_tail),
            "headings_invented": len(invented), "outline_entries": len(outline),
            "outline_mapped": len(matched),
            "outline_confirmed": bundle.get("outline_confirmed", False)}


def check_innovations(findings: list[dict], innovations: list | None) -> dict:
    if not innovations:
        add(findings, "error", "innovation_evidence",
            "innovations.json missing or empty; the article has to open with "
            "what is new and why we believe it")
        return {"innovations": 0, "innovations_unsupported": 0}
    levels = {"strong", "moderate", "claimed"}
    broken = []
    for item in innovations:
        # An innovation the authors only assert is still worth listing; that is
        # exactly what `claimed` means, so it is the one level allowed to carry
        # no evidence. Anything stronger has to point at an experiment.
        if item.get("strength") not in levels or (
                item.get("strength") != "claimed" and not item.get("evidence")):
            broken.append(item.get("id") or item.get("name_zh") or "?")
    if broken:
        add(findings, "error", "innovation_evidence",
            f"needs a valid strength, and evidence[] unless it is 'claimed': "
            f"{', '.join(broken)}")
    else:
        add(findings, "pass", "innovation_evidence",
            f"all {len(innovations)} innovations carry evidence and a strength")
    counts: dict[str, int] = {}
    for item in innovations:
        counts[item.get("strength", "?")] = counts.get(item.get("strength", "?"), 0) + 1
    return {"innovations": len(innovations), "innovations_unsupported": len(broken),
            "innovation_strength": counts}


def check_anchors(findings: list[dict], article: str) -> dict:
    """Every quoted number should say which figure or table it came from."""
    body = re.sub(r"```.*?```", "", article, flags=re.S)
    loose = []
    for hit in NUMBER_RE.finditer(body):
        window = body[max(0, hit.start() - 220):hit.end() + 220]
        if not ANCHOR_RE.search(window):
            loose.append(hit.group(0).strip())
    anchors = len(ANCHOR_RE.findall(body))
    if loose:
        sample = ", ".join(sorted(set(loose))[:8])
        add(findings, "warning", "numeric_anchors",
            f"{len(loose)} figure(s) quoted with no nearby 图 N / 表 N "
            f"reference (e.g. {sample})")
    else:
        add(findings, "pass", "numeric_anchors",
            f"every quoted number sits near one of {anchors} 图/表 references")
    if re.search(r"\d\s*个?百分点", body) is None and re.search(r"\d\s*%", body):
        add(findings, "warning", "numeric_anchors",
            "differences appear to be written in '%' rather than '百分点'")
    return {"asset_anchors": anchors, "numbers_unanchored": len(loose)}


def check_selection(findings: list[dict], article: str, workdir: Path) -> dict:
    marker = workdir / "selection-confirmed.json"
    record = load(marker)
    if isinstance(record, dict) and record.get("confirmed_by_user"):
        add(findings, "pass", "selected_tables_confirmed",
            "the table and equation shortlist was confirmed by the user")
        return {"selection_confirmed": True}
    add(findings, "warning", "selected_tables_confirmed",
        "no selection-confirmed.json with confirmed_by_user: true; the table "
        "and equation shortlist should be agreed before writing")
    return {"selection_confirmed": False}


def check_closing(findings: list[dict], article: str) -> dict:
    """The article ends with 总结, and 总结 stays short."""
    blocks = sections(article)
    if not blocks:
        add(findings, "error", "closing_section", "the article has no sections")
        return {"closing_characters": 0}
    title, body = blocks[-1]
    if heading_key(title) != CLOSING:
        add(findings, "error", "closing_section",
            f"the last section is 「{title}」; it has to be 「{CLOSING}」")
    else:
        add(findings, "pass", "closing_section", "the article closes with 总结")
    size = len(re.sub(r"\s", "", body))
    if size > CLOSING_BUDGET:
        add(findings, "warning", "closing_section",
            f"总结 is {size} characters, over the {CLOSING_BUDGET} budget; the "
            "figure blocks already carry the criticism")
    else:
        add(findings, "pass", "closing_section",
            f"总结 is {size} characters, within the {CLOSING_BUDGET} budget")
    return {"closing_characters": size}


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("article", type=Path)
    parser.add_argument("-d", "--workdir", type=Path,
                        help="defaults to the article's folder")
    parser.add_argument("-o", "--out", type=Path,
                        help="defaults to audit-report.json in the workdir")
    args = parser.parse_args()

    if not args.article.is_file():
        sys.exit(f"not a file: {args.article}")
    workdir = args.workdir or args.article.parent
    out = args.out or workdir / "audit-report.json"
    article = args.article.read_text(encoding="utf-8")

    bundle = load(workdir / "source_bundle.json")
    if bundle is None:
        sys.exit(f"no readable source_bundle.json in {workdir}; run stage 1 first")

    findings: list[dict] = []
    metrics = {"article_characters": len(article)}
    metrics.update(check_coverage(findings, article, bundle))
    metrics.update(check_explained(findings, article))
    metrics.update(check_screenshots(findings, article, workdir,
                                     load(workdir / "screenshot-index.json")))
    metrics.update(check_outline(findings, article, bundle, workdir))
    metrics.update(check_closing(findings, article))
    metrics.update(check_innovations(findings, load(workdir / "innovations.json")))
    metrics.update(check_anchors(findings, article))
    metrics.update(check_selection(findings, article, workdir))

    if not metrics.get("outline_confirmed"):
        add(findings, "warning", "outline_alignment",
            "source_bundle.json still has outline_confirmed: false; the "
            "English outline should be agreed with the user before writing")

    counts = {level: sum(1 for f in findings if f["level"] == level)
              for level in ("pass", "warning", "error")}
    report = {
        "schema_version": "1.0",
        "article": str(args.article),
        "source_sha256": bundle.get("source_sha256"),
        "summary": {"status": "fail" if counts["error"] else "pass",
                    "passes": counts["pass"], "warnings": counts["warning"],
                    "errors": counts["error"]},
        "metrics": metrics,
        "findings": findings,
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"{out}")
    print(f"  {report['summary']['status'].upper()}  "
          f"{counts['pass']} pass, {counts['warning']} warning, "
          f"{counts['error']} error")
    for finding in findings:
        if finding["level"] != "pass":
            print(f"  [{finding['level']:7}] {finding['code']}: {finding['message']}")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

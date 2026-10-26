---
name: easy-paper-reader
description: Read a paper PDF end to end and write it up as a long-form Chinese article, ready to paste into Zhihu — contributions first, every figure in the paper cropped out and explained one by one, sections mirroring the English original, in the voice of a researcher rather than a model. Use for requests like 「解读这篇论文」「写篇论文解读」「paper 解读发知乎」「把这篇 paper 讲一下」, "read this paper for me", "write a paper breakdown".
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion
---

# Paper PDF → long-form Chinese Zhihu reading

What makes this a reading rather than a restatement is four things: every contribution has experimental
evidence behind it, every figure is actually looked at before being written about, sections line up with
the English original, and the voice is a researcher's rather than a model's. The scripts do only
deterministic geometry, text extraction and machine-checkable gating; every judgment call is yours.

The article itself is written in Chinese. The five files under `references/` are Chinese for the same
reason — they steer the prose, and `chinese-voice.md` is mostly Chinese word lists.

## Dependencies

```bash
python3 -m pip install "pymupdf==1.26.*" pillow
```

Without PyMuPDF you can neither extract text nor render pages, and the scripts exit with an error. Do not
work around it — install it first.

## Working directory

Keep every intermediate artifact in one working directory; do not pollute the directory the paper sits in:

```
<workdir>/
  source_bundle.json      S1
  rendered-pages/         S1   page-001.png ...
  crop_plan.json          S2
  assets/                 S3   figure-01.png / table-01.png ...
  screenshot-index.json   S3
  innovations.json        S4
  outline-map.json        S5
  article.md              S7
  audit-report.json       S7
  tone-report.json        S8
  article-zhihu.html      S9
```

## S1 Prepare

```bash
python3 scripts/prepare_paper.py <paper.pdf> -o <workdir>
```

Produces `source_bundle.json`: `outline` (the English section outline), `unnumbered_sections`,
`evidence_inventory` (figures / tables / equations, with captions and `caption_bbox_pt`), `mentions` (every
sentence in the body that refers to a float), `pages` (per-page text), plus 216 dpi full-page renders.

Two situations require stopping:

- `extraction.text_quality` is `scanned-or-cid` — there is no usable text layer. Tell the user it needs OCR
  first; do not push on.
- `outline_method` is `unresolved` — the section outline could not be recovered, so constraint #3 cannot be
  met. Go back, `Read` a few `rendered-pages/page-NNN.png`, and write the outline into `source_bundle.json`'s
  `outline` by hand.

**The outline must be shown to the user first.** List `outline` by `number` + `title_en` + `pdf_page`, and
once it is confirmed set `outline_confirmed` to `true`. A wrong outline makes every section wrong; this step
cannot be skipped.

## S2 Locate crop boxes

```bash
python3 scripts/find_assets.py <workdir>/source_bundle.json
```

Grows outward from the caption and stops at body text or a neighbouring float. Produces `crop_plan.json`,
each entry carrying `rect_pt` / `rect_px` / `rect_norm` / `confidence` / `reason`.

`rect_norm`, in per-mille coordinates, is the only authoritative one of the three — images get scaled when
displayed, and hard-coded pixel widths go stale.

## S3 Crop

```bash
python3 scripts/crop_assets.py <workdir>/crop_plan.json
```

Produces `assets/*.png` and `screenshot-index.json`.

**The next step cannot be skipped**: `Read` each cropped PNG and confirm that no sub-panel is missing, that
no axis or legend was cut off, and that the caption is inside the crop. Start with the low `confidence` ones.

Two ways to fix a bad crop:

- Nudge it: edit that entry's `rect_norm` in `crop_plan.json`, then
  `python3 scripts/crop_assets.py <plan> --only 'Figure 3'` to re-crop just that one.
- Rewrite it: `Read` the corresponding `rendered-pages/page-NNN.png` in full and read off the correct
  per-mille coordinates into `rect_norm` (top-left 0,0, bottom-right 1000,1000), then re-crop.

Once a crop is good, set its `verified_by` to `"model-viewed"` and re-run S3 so `screenshot-index.json`
records it. That field is what the `figure_viewed` audit check looks at.

## S4 Contributions

Read `references/innovation-spec.md`, produce `innovations.json`.

Mine four aligned sources: the "we propose" sentences in the abstract, the contribution bullets at the end
of the introduction, the named components in the method section, and whatever related work is used as a
comparison. Every entry has to answer "which figure, table or ablation shows this works", graded
`strong` / `moderate` / `claimed`. **An entry with no evidence cannot be `strong`** — that grading is the
line between a reading and a restated abstract.

## S5 Outline mapping

Read `references/outline-mapping.md`, produce `outline-map.json`.

English sections → Chinese sections, 1:1. A Chinese heading says only what the section is about:
`## 二、方法：先把"下一个事件"预测对`. **Do not carry the English original in parentheses** — a tail like
`（3. Method）` turns the article into a bilingual table of contents. The correspondence belongs in
`outline-map.json`'s `title_en` + `heading_zh`; `outline_alignment` checks order against it, and
`no_english_tails` catches any tail left in the article. Only two Chinese sections may be invented: the
opening on what is new, and the closing `## 总结`. **The last section is always named 「总结」** and is
short; `closing_section` checks both the title and the length. The `assets[]` field decides which figure
or table lands in which section.

## S6 Per-figure explanation

Read `references/figure-explain-spec.md` and `references/chinese-voice.md`.

Three sources merged, none optional: the caption verbatim, every sentence in `mentions[id]` that refers to
the float, and **the cropped PNG, actually `Read`**. An explanation written off the caption alone is a
restatement — this is where the pipeline degrades most easily.

Every figure has to do four things: what question it answers / how to read it (including which direction is
better) / what it says, with numbers, attributed to the figure or table in the article / what it cannot
show. Criticism goes in place, never in its own section. **The four things are functions, not subheadings**
— write continuous prose and let each of the ten figures enter from a different place. Ten identical sets of
bold labels is the most recognizable AI tell this pipeline produces.

Attribute every number to the article's own 「图 6」「表 2」「式 1」, **never `PDF p.7`-style page numbers**:
the reader does not have that PDF open, so a page number is a dead link. Write the paper's `Figure` /
`Table` / `Eq.` in Chinese too, keeping the original numbering. `numeric_anchors` checks that every number
has a 图 N / 表 N near it.

Coverage:

- **Figures**: all of them, each doing all four duties.
- **Tables**: only those carrying main results and ablations; source tables and appendix reference tables
  get one sentence.
- **Equations**: only those defining the core method. Zhihu supports `$...$`, so write LaTeX directly rather
  than converting to images; for a standard objective (flow matching, say) one sentence on what it means is
  enough, with no derivation.

**Put the table and equation shortlist to the user with AskUserQuestion** before writing on. List it by the
article's own 「表 2」「式 1」 numbering, with no PDF page numbers. Once confirmed, write
`selection-confirmed.json` in the working directory:
`{"confirmed_by_user": true, "tables": ["Table 2", ...], "equations": ["Equation 1", ...]}` — that file is
what `selected_tables_confirmed` looks for. **Never write it without having asked.** If there is no user to
ask (running inside a subagent, for instance), put the shortlist and the reasoning in
`selection-proposal.md` and leave the warning standing.

## S7 Assembly and audit

`article.md` is structured as: the opening on what is new → the contribution/evidence table → the
terminology table → each section per `outline-map` (embedding `![图 N：中文说明](assets/figure-NN.png)` plus
its explanation) → the closing `## 总结`. Layout constraints are in `references/zhihu-format.md`.

**Keep 总结 short**, under 1200 characters (the `closing_section` budget): one sentence each on the method
and the results, two or three lines on the limits of the evidence, one or two conclusions that genuinely
hold. The criticism has already been delivered in place under each figure; spreading it back out into a
six-item list is the most common way a reading turns into padding.

Those first three blocks share **one** invented `##` heading — the terminology table does not get its own,
because a third invented `##` trips `no_invented_sections`.

**「结论先行」, 「四件事」, 「证据强度」 and the like are this pipeline's internal vocabulary; not one word of
it belongs in the article.** A heading says what the section is about, not which technique the author is
using; `strong` / `moderate` / `claimed` exist only inside `innovations.json`. The article also does not
narrate its own formatting rules (「下文数字都标页码」 and similar) — just follow them. These are
`check_tone.py`'s `scaffolding` class, and once the sentences are clean this is where almost all the
remaining AI flavor lives.

```bash
python3 scripts/audit_article.py <workdir>/article.md
```

Any error in `audit-report.json` has to be fixed before delivery; a warning is either fixed or explained in
the delivery notes.

## S8 Voice gate

Read `references/chinese-voice.md`, then

```bash
python3 scripts/check_tone.py <workdir>/article.md
```

`tone-report.json` checks Chinese AI flavor in layers, and no layer substitutes for another:

| Layer | code | What |
|---|---|---|
| sentence | `staging` `inflation` `translationese` | 「不是 X 而是 Y」「本质上」「值得注意的是」, inflated words, 「进行分析」-style translationese |
| layout | `dash` `bold` `bold_label` `question` `restate` `gloss` `decoration` | budgets for em dashes, bold, bold labels, opening rhetorical questions, 「也就是说」 restatements, repeated bilingual glosses |
| structure | `scaffolding` `headings` | technique-as-heading, internal strength labels shown to the reader, counting the list out loud, narrating formatting rules; whether all twelve headings share one mould |
| posture & template | `posture` `template` | 「是 A，不是 B」, self-declared importance (「信息量最大」「最该看的一张」), empty evaluative sentences, false agency; whether ten figures unfold in one identical order |
| rhythm & words | `rhythm` `terms` `authority` `residue` | sentence-length distribution across the article and inside paragraphs, consecutive identical openers; synonym rotation; vague 「有研究表明」 and 「推测可能是」; zero-width characters and citation residue |

The last two layers are what is left after the sentences are clean, and they are the hardest to catch
yourself: every sentence is fine on its own, and it is the skeleton and the rhythm that give you away.
`template` reuses `audit_article.py`'s `EXPLANATION_DUTIES` directly, tallying the order in which each of
the ten figure explanations performs those four duties — one shared order at 70% warns, at 90% errors. For
ways to vary the entry point, see the table in `references/figure-explain-spec.md`.

`authority` matters most for a paper reading: a vague 「有研究表明」 invents a reference out of thin air, and
「论文没有说明，推测可能是……」 leaves the reader remembering your guess as the paper's conclusion. If the
paper does not say, write that it does not say, and stop there.

Errors have to be cleared. There is only one way: **rewrite the paragraph, do not swap phrases one by one.**
Model voice lives in sentence structure, not in vocabulary. Think the paragraph through, write it again,
re-run the gate.

## S9 Convert to something Zhihu accepts

The Zhihu editor does not parse Markdown. Paste `article.md` in whole and twelve headings, twenty table
rows, fifty `$x$` and every `**` stay on the page as literal text — that is the "garbled output" users
report. The editor is a contenteditable that accepts rich text from the clipboard, so the last step converts
the article to HTML:

```bash
python3 scripts/to_zhihu_html.py <workdir>/article.md
```

Produces `article-zhihu.html`. Open it in a browser, Cmd+A, Cmd+C, then Cmd+V into the Zhihu editor.

Formulas go through Zhihu's own renderer: the editor stores each one as
`<img src="https://www.zhihu.com/equation?tex=...">`, and the script emits exactly that URL, so a pasted
formula is indistinguishable from one typed with the formula button — the request is made by the user's
logged-in browser and nothing is uploaded locally. Images use `file://` pointing at the local crops; the
browser puts the bitmap on the clipboard too, and Zhihu usually re-uploads it. For any that do not make it,
the caption says which file to upload by hand.

The script prints a conversion tally (formulas / table rows / images / headings); check the counts before
pasting. Details are in `references/zhihu-format.md`.

## Audience

General AI-technical readers. Explain a term in one sentence the first time it appears, put a terminology
table in the opening, and give the meaning of an equation without the derivation. The voice is a researcher
who has read the paper and is willing both to make it clear and to pick holes in it — not a model giving a
briefing.

`examples/vpp2/` is one finished run kept as a reference — a 21-page paper with 10 figures and 8 tables:
`article.md` and the `assets/` it embeds in one directory, next to `innovations.json` (8 entries, 1 strong /
6 moderate / 1 claimed), `source_bundle.json`, `crop_plan.json`, `screenshot-index.json` and both gate
reports, so both gates run against `examples/vpp2/article.md` directly. When you are unsure how far to take
a paragraph or what voice to use, follow it — the paper it happens to read is beside the point.

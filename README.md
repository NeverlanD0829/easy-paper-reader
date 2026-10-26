[English](README.md) | [中文](README.zh-CN.md)

# easy-paper-reader

Turn any paper PDF into a long-form Chinese article you can paste straight into Zhihu.

Not a summary. Four hard constraints run through the pipeline, each with a machine-checkable gate:

1. **Novelty first, and it has to be evidenced** — the article opens with what is new in this paper. Every
   contribution is graded `strong` / `moderate` / `claimed`, and nothing without an ablation behind it is
   allowed to be `strong`.
2. **Every figure in the paper is cropped and explained one by one** — a script derives each crop box from
   the caption anchor, and the model has to actually `Read` the resulting PNG before writing about it.
   Anything written off the caption alone is a restatement, not a reading.
3. **Sections mirror the English original** — Chinese `##` headings map 1:1 to the paper's sections, in the
   same order, with at most two invented sections (the opening on novelty, and the closing 「总结」).
   A heading says what the section is about; it does not carry the English title in parentheses. The
   Chinese↔English correspondence lives in `outline-map.json`. The closing section is always named
   「总结」 and stays under 1200 characters.
4. **Voice of a researcher, not of a model** — a separate Chinese AI-slop gate checks posturing sentence
   patterns, inflated words, translationese, budgets for em dashes and bold, and whether paragraph
   lengths are suspiciously uniform.

`examples/vpp2/` is the full pipeline output on VPP2 (arXiv 2610.10270v2, 21 pages / 10 figures / 8 tables).
The article, the crops and every intermediate artifact sit in one directory, so both gates run against it
directly:

```bash
python3 scripts/audit_article.py examples/vpp2/article.md   # 13 pass / 0 warning / 0 error
python3 scripts/check_tone.py    examples/vpp2/article.md   # 12 pass / 0 warning / 0 error
```

`article.md` is roughly 17k characters and the 14 crops it embeds live in `examples/vpp2/assets/`, one level
below the article, so relative paths resolve on both GitHub and Zhihu. The table and equation shortlist is
recorded in `selection-proposal.md`; `selection-confirmed.json` is written only after the user agrees to it
— the skill is not allowed to write that file on its own, and `selected_tables_confirmed` stays a warning
until someone has been asked.

## Install

This is a Claude Code / Ducc style skill. Drop it into your skills directory:

```bash
git clone https://github.com/NeverlanD0829/easy-paper-reader.git ~/.claude/skills/easy-paper-reader
python3 -m pip install -r ~/.claude/skills/easy-paper-reader/requirements.txt
```

The only hard dependencies are PyMuPDF (text extraction + full-page rendering) and Pillow (cropping).
Without PyMuPDF the pipeline cannot start at all, and the scripts exit with an error rather than degrading
silently.

Once installed, ask the agent to read a paper for you —「解读这篇论文」,「把这篇 paper 写成知乎解读」— and
it triggers. You can also use `scripts/` as standalone command-line tools; see below.

## Pipeline

The scripts only do deterministic geometry, text extraction and machine-checkable gating. Every judgment
call is left to the model.

| Stage | What it does | Output |
|---|---|---|
| S1 | PDF → per-page text, English section outline, figure/table/equation inventory (captions + body mentions), 216 dpi full-page renders | `source_bundle.json`, `rendered-pages/` |
| S2 | Grow a crop box outward from the caption, stopping at body text or a neighbouring float | `crop_plan.json` |
| S3 | Crop by per-mille coordinates, record provenance | `assets/`, `screenshot-index.json` |
| S4 | Mine contributions from four aligned sources, bind each to evidence and grade it | `innovations.json` |
| S5 | English sections → Chinese sections, and which figure lands in which section | `outline-map.json` |
| S6 | Per-figure explanation from three merged sources (caption + every body mention + the PNG actually viewed) | article body |
| S7 | Assembly + content audit | `article.md`, `audit-report.json` |
| S8 | Voice gate | `tone-report.json` |
| S9 | Convert to HTML the Zhihu editor accepts (headings / tables / formulas / images) | `article-zhihu.html` |

Two points require stopping to ask a human: the English outline from S1 (a wrong outline makes every
section wrong) and the table/equation shortlist from S6.

**The Zhihu editor does not parse Markdown.** Paste `article.md` into it and `##`, `|---|`, `**` and `$x$`
stay on the page as literal text. S9 converts the article to HTML; open it in a browser, select all, copy,
then paste into the editor — headings, bold, tables, formulas and images all arrive as real elements.
Formulas go through Zhihu's own renderer at `https://www.zhihu.com/equation?tex=...`, so a pasted formula
is indistinguishable from one typed with the formula button.

## Standalone command-line use

```bash
python3 scripts/prepare_paper.py paper.pdf -o /tmp/work
python3 scripts/find_assets.py /tmp/work/source_bundle.json
python3 scripts/crop_assets.py /tmp/work/crop_plan.json           # --only 'Figure 3' re-crops one
python3 scripts/audit_article.py /tmp/work/article.md
python3 scripts/check_tone.py /tmp/work/article.md
python3 scripts/to_zhihu_html.py /tmp/work/article.md             # → article-zhihu.html
```

Both gates exit 1 on any error, so they drop straight into CI or a pre-commit hook.

## What the two gates check

`audit_article.py` checks that the reading is complete:

| code | What | Level |
|---|---|---|
| `figures_coverage` | every figure in the inventory is embedded in the article | error |
| `figure_explained` | each figure's prose gives the orientation, which direction is better, at least two numbers, and what the figure cannot show | error |
| `figure_viewed` | every embedded crop is marked `verified_by: model-viewed` in `screenshot-index.json` | error |
| `crop_provenance` | every embedded image has a crop provenance record | error |
| `outline_alignment` | every section in `outline-map.json` is written, in the paper's order | error |
| `no_english_tails` | no Chinese heading carries the English original in parentheses | error |
| `no_invented_sections` | at most two invented sections | error |
| `closing_section` | the last section is titled 「总结」 and stays under 1200 characters | error / warning |
| `innovation_evidence` | every contribution has a `strength`, and `evidence[]` unless it is `claimed` | error |
| `numeric_anchors` | every quoted number sits near a 图 N / 表 N reference | warning |
| `selected_tables_confirmed` | the table/equation shortlist was confirmed by the user | warning |
| `zhihu_assets` | images ≤1600px wide and ≤5MB | warning |

`figure_explained` deliberately checks **by function, not by subheading**. An early version matched four
bold labels verbatim; the result was ten figures sharing one template — which is the heaviest AI tell of
all. It now checks four regex-covered duties, so continuous prose passes just as well.

`check_tone.py` checks Chinese AI slop. The test applied throughout: would a researcher writing carefully
choose to write it this way?

- **Posturing patterns**: 「不是 X 而是 Y」,「不仅…而且」,「本质上」,「值得注意的是」,「让我们」,「总而言之」
- **Inflated words**: 赋能, 助力, 打造, 极大地, 起到了关键作用, 在一定程度上, 扮演……角色
- **Translationese**: 「进行分析」, sentence-initial 「对于……而言」, 「被……所……」, three 「的」 in one sentence, caption restatement
- **Layout budgets**: per 10k characters — 6 em dashes, 10 bold spans, 3 bold-label list items, 1.5 opening rhetorical questions, 2 「也就是说」 restatements, 2 repeated bilingual glosses; double the budget is an error
- **Rhythm**: a coefficient of variation below 0.35 for paragraph or sentence length is a warning, as is the same four-character opener appearing three times; checked per paragraph too — three paragraphs whose every sentence is crammed under 12 characters, or two consecutive sentences opening with 「此外」/「同时」
- **Borrowed authority**: vague 「有研究表明」/「业内人士认为」 — a reading of one paper may cite only that paper and its references; also 「论文没说，推测可能是……」, where saying the paper is silent is criticism but filling the gap with a guess gets read as the paper's own conclusion
- **Term drift**: rotating 模型／网络／架构／框架 for the same thing within a paragraph. Repetition penalties push a model to vary its wording, but in a paper reading the term *is* the thing; repeat it
- **Mechanical residue**: zero-width and directional control characters, `citeturn0search0` style citation scaffolding, `utm_source=chatgpt.com`, unfilled placeholders — zero judgment, zero false positives, and they must be gone before publishing
- **Scaffolding**: using a writing technique as a heading (「结论先行：……」), showing the reader the internal `strong`/`moderate`/`claimed` grades, counting the list out loud (「创新点一共八条」), narrating your own formatting rules (「下文数字都标页码」); also whether all twelve headings follow one 「phrase: selling point」 mould
- **Posture in disguise**: 「是 A，不是 B」 is 「不是 B 而是 A」 with the halves swapped — same posture;「信息量最大」,「最该看的一张图」,「值得单独记住」 are 「起到了关键作用」 in a new coat — importance is proven by content, not announced by the author
- **Template**: ten figure explanations unfolding those four duties in one identical order — 70% is a warning, 90% an error. This reuses `audit_article.py`'s `EXPLANATION_DUTIES`, so deleting the bold labels does not get you out of it

The last three are what remains after the sentences are clean, and they are the hardest to catch yourself:
every sentence is fine on its own, and it is the skeleton and the rhythm that give you away. See the next
section.

There is only one way to fix these: **rewrite the paragraph, do not swap phrases one by one.** Model voice
lives in sentence structure, not in vocabulary.

## Why the voice gate is separate

The first draft through this pipeline came out with 45 em dashes, 86 bold spans (56 of them opening a
「**bold label**：」 list item), ten figures sharing one four-part template, and 97 paragraphs of
near-identical length. The content was correct and it still read as machine-written at a glance.

These are habits of layout and syntax. A prompt saying "write more naturally" does not constrain them;
they have to be quantified into budgets and then fixed one by one. `references/chinese-voice.md` is the
companion rewriting spec, with ❌/✅ pairs for each class.

Once the sentences and the layout are clean, one layer remains: the skeleton of the article reporting its
own method. `## 一、结论先行：这篇论文新在哪` uses a writing technique as a heading. The contribution table
had an extra `strong` / `moderate` / `claimed` column, handing the reader a field straight out of
`innovations.json`. The opening announced 「创新点一共八条，先说最该记住的三条」 and 「下文每个数字后面都标了页码」.
Every sentence reads fine; together they still read as machine-written — grading a paper's contributions on
a three-level scale in a public article is a reviewer's move, not a reader's. The `scaffolding` check covers
this layer, and none of the internal vocabulary is allowed into the article.

Beyond that sits a layer `scaffolding` cannot see. Delete every 「不是 X 而是 Y」 and the same posture comes
back as 「是 A，不是 B」. Delete every 「起到了关键作用」 and it returns as 「掩码是整张图信息量最大、最该慢读的部分」.
The subtler one is order: with the four bold labels gone, ten figure explanations still march through
orientation → which direction is better → numbers → criticism, measured at 10/10 sharing one order, so by
the third figure the reader knows what the other seven look like. `posture` and `template` cover this layer;
the latter reuses the audit script's duty regexes, so there is no way around it. The fix is to let each
figure enter from whatever is most worth saying about that figure.

The voice gate does not judge whether a sentence is correct or useful — it only looks for machine traces.
Whether the content is right is the job of `audit_article.py` and of a human.

## Where the voice gate came from

S8 was not written from scratch. These checks were cross-referenced against a dozen de-AI-slop skills on
GitHub and Wikipedia's `Signs of AI writing`, with whatever applies to Chinese paper readings folded into
`check_tone.py`:

| Source | What was borrowed |
|---|---|
| [blader/humanizer](https://github.com/blader/humanizer) | the taxonomy of 26 patterns in six groups, which nearly every sibling skill forks; the "never touch quotations, headings or proper nouns" exemption |
| [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh) | the Chinese-specific section: stacked 「的」, 「进行＋verb」, piled-up passives, four-character parallelism, 「随着……的发展」 openers, boilerplate closings |
| [AIScientists-Dev/academic-humanizer](https://github.com/AIScientists-Dev/academic-humanizer) | 11 academic tells, plus the claim-to-evidence layer: verb strength has to match evidence strength |
| [matsuikentaro1/humanizer_academic](https://github.com/matsuikentaro1/humanizer_academic) | **per-paragraph** rhythm checking (every sentence inside one paragraph sharing a narrow length band), not just a whole-article CV |
| [grapeot/writing-skill](https://github.com/grapeot/writing-skill) | separating hard zero-tolerance items from budgeted ones; thresholds specific to long-form Chinese — bilingual glosses, 「这意味着」, number density |
| [misbahsy/anti-ai-slop](https://github.com/misbahsy/anti-ai-slop) | the cleanup table for zero-width and directional control characters |
| [hexiecs/talk-normal](https://github.com/hexiecs/talk-normal) | the **reversed and symmetric** variants of negative parallelism (「X，而不是 Y」,「适合 X，不适合 Y」); the 「一句话总结」 family |
| [DanRWilloughby/snifftest](https://github.com/DanRWilloughby/snifftest) | countable rules and judgment-dependent rules belong in separate buckets; small paragraphs stay out of rhythm scoring |
| Wikipedia `Signs of AI writing` | vague authority and citation residue; plus the warning that banning em dashes outright has itself become an AI tell |

Two rules were deliberately **not** imported, recorded here so nobody adds them back:

- **A number-density ceiling** (grapeot's "five or more numbers in a paragraph is a warning"). A figure
  explanation is required by spec to give at least two numbers plus the difference, so five or six numbers
  in a paragraph is the job, not a defect. That threshold was tuned for commentary, and it fights this genre.
- **Normalizing curly quotes.** English tools straighten them; Chinese body text should keep 「」 and “”,
  as Humanizer-zh's rule 21 also says.

The em dash budget stays, but it is not escalated to a ban. There is no evidence that Chinese models abuse
em dashes the way English ones do, and since 2026 the blanket English-language ban has flattened
punctuation variety enough that it has become a machine trace of its own.

## Layout

```
SKILL.md                         orchestration
README.zh-CN.md                  the same document in Chinese
scripts/prepare_paper.py         S1  PDF → text / outline / float inventory / page renders
scripts/find_assets.py           S2  caption anchor → crop box
scripts/crop_assets.py           S3  cropping + provenance
scripts/audit_article.py         S7  content audit
scripts/check_tone.py            S8  Chinese AI-slop gate
scripts/to_zhihu_html.py         S9  article.md → HTML for the Zhihu editor
references/innovation-spec.md        where contributions come from, and how evidence is graded
references/outline-mapping.md        English sections → Chinese sections
references/figure-explain-spec.md    the four duties of a figure explanation + degenerate examples
references/chinese-voice.md          Chinese AI-slop checklist and rewriting spec
references/zhihu-format.md           Zhihu layout and image constraints
examples/vpp2/article.md             the example article
examples/vpp2/assets/                the 14 crops it embeds
examples/vpp2/*.json                 artifacts and both gate reports from the same run
```

The five files under `references/` are written in Chinese on purpose: they are prompts fed to the model to
steer it toward writing Chinese, and `chinese-voice.md` in particular is mostly Chinese word lists that
cannot survive translation. For the same reason the voice gate's pattern tables — the name of each pattern
and the one-line advice printed with it — stay Chinese: they quote the Chinese text they flag. Everything
else the scripts print is English.

## Known limitations

- A scanned PDF has no text layer and the pipeline cannot run; OCR it first. S1 errors out rather than
  continuing silently.
- Conference papers with no bookmarks and a non-standard template may defeat outline detection, in which
  case S1 asks for the `outline` to be written by hand.
- Floats spanning both columns of a two-column paper are assigned by x-range; when that misfires, the model
  has to read the full-page render and write the per-mille coordinates itself.
- The voice gate's word lists target Chinese technical writing. Another domain (humanities, journalism)
  needs `BUDGETS` and the lists retuned.

## License

MIT, see `LICENSE`.





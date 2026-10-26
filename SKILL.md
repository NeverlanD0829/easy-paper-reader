---
name: easy-paper-reader
description: 把任意论文 PDF 解读成一篇可直接发知乎的中文长文：先讲清创新点，把原文每张图裁切出来逐个讲解，章节结构与英文原文标题一一对应，口吻像研究员而不像模型。适用于「解读这篇论文」「写篇论文解读」「paper 解读发知乎」「把这篇 paper 讲一下」等请求。
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, AskUserQuestion
---

# 论文 PDF → 知乎解读长文

把一篇论文变成解读而不是摘要复述，靠四件事：创新点必须有实验证据支撑、每张图必须真的看过再讲、章节必须对齐英文原文、口吻必须像个研究员而不像个模型。流水线的脚本只做确定性的几何和文本抽取和可机检的门禁，所有判断留给模型。

## 依赖

```bash
python3 -m pip install "pymupdf==1.26.*" pillow
```

缺 PyMuPDF 时既不能抽文本也不能渲染页面，脚本会直接报错退出 —— 不要绕过，先装。

## 工作目录

所有中间产物放在一个工作目录里，不要污染论文所在目录：

```
<workdir>/
  source_bundle.json      S1
  rendered-pages/         S1   page-001.png ...
  crop_plan.json          S2
  assets/                 S3   figure-01.png / table-01.png ...
  screenshot-index.json   S3
  innovations.json        S4
  outline-map.json        S5
  article.md               S7
  audit-report.json        S7
  tone-report.json         S8
  article-zhihu.html       S9
```

## S1 准备

```bash
python3 scripts/prepare_paper.py <paper.pdf> -o <workdir>
```

产出 `source_bundle.json`：`outline`（英文章节大纲）、`unnumbered_sections`、`evidence_inventory`（figures / tables / equations，含 caption 与 `caption_bbox_pt`）、`mentions`（正文每一处提到某张图表的句子）、`pages`（逐页文本），以及 216 dpi 的整页渲染。

两种必须停下来的情况：

- `extraction.text_quality` 是 `scanned-or-cid` —— 文本层不可用，告诉用户需要先 OCR，不要硬着头皮往下跑。
- `outline_method` 是 `unresolved` —— 没能恢复章节大纲，要求 #3 无从满足。退回去 `Read` 几张 `rendered-pages/page-NNN.png`，人工把大纲写进 `source_bundle.json` 的 `outline`。

**大纲必须先给用户过一眼**。把 `outline` 按 `number` + `title_en` + `pdf_page` 列出来，确认无误后把 `outline_confirmed` 改成 `true`。大纲错了后面每一节都错，这一步不能省。

## S2 定位裁切框

```bash
python3 scripts/find_assets.py <workdir>/source_bundle.json
```

从 caption 向外生长，遇到正文或邻居图表就停。产出 `crop_plan.json`，每条含 `rect_pt` / `rect_px` / `rect_norm` / `confidence` / `reason`。

`rect_norm` 是千分比坐标，是三件产物里唯一权威的那个 —— 图片在显示时会被缩放，写死像素宽度迟早对不上。

## S3 裁切

```bash
python3 scripts/crop_assets.py <workdir>/crop_plan.json
```

产出 `assets/*.png` 和 `screenshot-index.json`。

**接下来这一步不可跳过**：逐个 `Read` 裁出来的 PNG，确认子图 panel 齐全、坐标轴和图例没被切掉、caption 在图里。先看 `confidence` 低的。

不合格就改，两条路：

- 微调：直接改 `crop_plan.json` 里那条的 `rect_norm`，然后 `python3 scripts/crop_assets.py <plan> --only 'Figure 3'` 重裁。
- 重写：`Read` 对应的 `rendered-pages/page-NNN.png` 整页，按千分比读出正确坐标写进 `rect_norm`（左上角 0,0，右下角 1000,1000），再重裁。

确认合格后把那条的 `verified_by` 设为 `"model-viewed"` 并重跑一次 S3，让 `screenshot-index.json` 记上。审计项 `figure_viewed` 查的就是这个字段。

## S4 创新点

读 `references/innovation-spec.md`，产出 `innovations.json`。

四处来源对齐挖掘：Abstract 的 "we propose" 句、Introduction 末尾的 contribution 要点、Method 里带名字的组件、Related Work 里被用来对比的对象。每一条都必须回答「哪张图/表/消融证明它有用」，按 `strong` / `moderate` / `claimed` 分级。**没有证据的条目不能写成 `strong`** —— 这个分级是解读文和复述摘要的分水岭。

## S5 大纲映射

读 `references/outline-mapping.md`，产出 `outline-map.json`。

英文章节 → 中文章节 1:1。中文标题只说这一节讲什么：`## 二、方法：先把"下一个事件"预测对`。**不要把英文原标题带进括号** —— `（3. Method）`这样的尾注把文章变成一份双语目录，中英对应关系记在 `outline-map.json` 的 `title_en` + `heading_zh` 里就够了，审计项 `outline_alignment` 按它查顺序，`no_english_tails` 查正文里有没有漏下的尾注。原文没有的中文章节只允许两个：开头讲创新点那一块，和文末的 `## 总结`。**最后一节固定叫「总结」**，内容要短，`closing_section` 查标题和篇幅。`assets[]` 字段决定每张图表落到哪一节。

## S6 逐图讲解

读 `references/figure-explain-spec.md` 和 `references/chinese-voice.md`。

三源合并，缺一不可：caption 原文、`mentions[id]` 里正文所有提到它的句子、**裁出来的 PNG（必须真的 Read 过）**。只看 caption 写出来的讲解必然是复述，这是整个 skill 最容易退化的地方。

每张图必须做到四件事：它在回答什么问题 / 怎么读（含哪个方向更好）/ 读出了什么（带数字，并说清出自文章里的哪张图哪张表）/ 它管不到什么。批判就地放，不单独成节。**四件事是功能不是小标题**，写成连续段落，十张图之间换入口；写成十组一模一样的加粗标签是这条流水线最典型的 AI 味。

数字的出处一律指向文章自己的「图 6」「表 2」「式 1」，**不要写 `PDF p.7` 这类页码**：读者手里没有那份 PDF，页码对他是死链。原文的 `Figure` / `Table` / `Eq.` 也都换成中文写法，图号沿用原文编号。`numeric_anchors` 查的就是每个数字附近有没有 `图 N` / `表 N`。

覆盖范围：

- **图**：全部，每一张都做全四件事。
- **表**：只挑承载主结果和消融的；数据来源表、附录引用表一句话带过。
- **公式**：只挑定义方法核心的。知乎支持 `$...$`，直接写 LaTeX，不转图；标准公式（如流匹配目标）提一句含义就够，不展开推导。

表和公式的**筛选清单先用 AskUserQuestion 列给用户确认**，再往下写。清单也按「表 2」「式 1」这类编号列，不带 PDF 页码。用户确认后在工作目录写
`selection-confirmed.json`：`{"confirmed_by_user": true, "tables": ["Table 2", ...], "equations": ["Equation 1", ...]}`
—— 审计项 `selected_tables_confirmed` 查的就是这个文件。**不要在没问过用户的情况下写这个文件**；
拿不到用户（例如在子 agent 里跑）就把清单和挑选理由写进 `selection-proposal.md`，让那条 warning 留着。

## S7 组装与审计

`article.md` 的结构：开篇讲清新在哪 → 创新点与证据对照表 → 术语约定表 → 按 `outline-map` 逐节（每节嵌 `![图 N：中文说明](assets/figure-NN.png)` + 讲解）→ 文末 `## 总结`。排版约束见 `references/zhihu-format.md`。

**总结要短**，1200 字以内（`closing_section` 的预算）：方法和成绩各一句、证据边界两三条、真正站得住的结论一两条，就够了。批判已经在每张图下面就地给过，收尾再铺成一张六条清单是最常见的注水方式。

前三块合起来只占**一个**自创 `##` 标题，术语约定表不要单独起标题 —— 自创 `##` 超过两个就会触发 `no_invented_sections`。

**「结论先行」「四件事」「证据强度」这类词是流水线内部的叫法，一个字都不要进文章。** 标题要说这一节讲什么，不要说作者在用什么写法；`strong` / `moderate` / `claimed` 只存在于 `innovations.json` 里。文章里也不要替自己交代写作规范（「下文数字都标页码」之类）—— 照做就行，不用通知读者。这些是 `check_tone.py` 的 `scaffolding` 一类，句子层面改干净之后，剩下的 AI 味几乎都在这里。

```bash
python3 scripts/audit_article.py <workdir>/article.md
```

`audit-report.json` 里有 error 就必须修完再交付，warning 要么修要么在交付说明里讲清为什么不修。

## S8 口吻门禁

读 `references/chinese-voice.md`，然后

```bash
python3 scripts/check_tone.py <workdir>/article.md
```

`tone-report.json` 按四层查中文 AI 味，层与层之间不能互相替代：

| 层 | code | 查什么 |
|---|---|---|
| 句子 | `staging` `inflation` `translationese` | 「不是 X 而是 Y」「本质上」「值得注意的是」、通胀词、「进行分析」这类译文腔 |
| 版式 | `dash` `bold` `bold_label` `question` `restate` `gloss` `decoration` | 破折号、加粗、加粗标签、开段设问、「也就是说」式复述、重复的中英夹注的用量预算 |
| 结构 | `scaffolding` `headings` | 拿写法当标题、把内部的强度标签摆给读者、数清单、替自己交代排版规范；十二个标题是不是一个模子 |
| 姿势与模板 | `posture` `template` | 「是 A，不是 B」、自封重点（「信息量最大」「最该看的一张」）、空评价句、虚假施动；十张图是不是按同一个顺序展开 |
| 节奏与词 | `rhythm` `terms` `authority` `residue` | 全文与段内的句长分布、连续同头句；近义词轮换；泛指的「有研究表明」和「推测可能是」；零宽字符与引用残留 |

后两层是句子改干净之后剩下的那部分，也是最难自查的：每句话单独看都没问题，是骨架和节奏在出卖你。`template` 直接复用 `audit_article.py` 的 `EXPLANATION_DUTIES`，统计十个图解各自按什么顺序做那四件事，同一个顺序占七成报警、九成报错 —— 换入口的写法见 `references/figure-explain-spec.md` 的那张表。

`authority` 一项对论文解读最要紧：泛指的「有研究表明」在解读里等于凭空造了一篇参考文献；而「论文没有说明，推测可能是……」会让读者把你的猜测记成论文的结论 —— 没写就写没写，停在那里。

有 error 必须改完。改法只有一条：**整段重写，不要逐条替换短语**。模型味在句子结构里，不在单词里；把那段的意思想清楚重写一遍，再跑一次。

## S9 转成知乎能吃的格式

知乎编辑器不认 Markdown。整篇 `article.md` 粘进去，十二个标题、二十行表格、
五十处 `$x$` 和每一个 `**` 都会原样留在页面上 —— 用户看到的「乱码」就是这个。
编辑器是个 contenteditable，接受剪贴板里的富文本，所以最后一步把文章转成 HTML：

```bash
python3 scripts/to_zhihu_html.py <workdir>/article.md
```

产出 `article-zhihu.html`。在浏览器里打开它，Cmd+A、Cmd+C，再到知乎编辑器里 Cmd+V。

公式走知乎自己的渲染：编辑器把每条公式存成
`<img src="https://www.zhihu.com/equation?tex=...">`，脚本直接发这个 URL，粘过去的公式
和用公式按钮敲的没有区别，由用户登录的浏览器去请求，本地什么都不上传。
图片用 `file://` 指本地裁图，浏览器会把位图一起放进剪贴板，知乎多数情况会自动重新上传；
没传上去的话图注里写了该手动传哪个文件。

脚本会报一遍转换计数（公式 / 表格行 / 图片 / 标题），粘贴前对一眼数目对不对。
细则见 `references/zhihu-format.md`。

## 面向读者

泛 AI 技术读者。术语首次出现给一句话解释，开头放一张术语约定表，公式只讲含义不推导。
口吻是一个读完论文、愿意把话说清楚也愿意挑刺的研究员，不是一个在做汇报的模型。

`examples/vpp2/` 是 VPP2（arXiv 2610.10270v2，21 页 / 10 图 8 表）跑完整条流水线的产物：
`article.md` 和它引用的 `assets/` 在同一个目录里，旁边是 `innovations.json`（8 条，1 strong /
6 moderate / 1 claimed）、`source_bundle.json`、`crop_plan.json`、`screenshot-index.json`
和两份门禁报告，所以两道门禁可以直接对 `examples/vpp2/article.md` 跑。
不确定某一段该写到什么程度、该用什么口吻时照它写。

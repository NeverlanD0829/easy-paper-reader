[English](README.md) | [中文](README.zh-CN.md)

# easy-paper-reader

把任意论文 PDF 解读成一篇可直接发知乎的中文长文。

不是摘要复述。四条硬约束贯穿整条流水线，每一条都有可机检的门禁：

1. **创新点优先，且必须有证据** —— 开篇先说这篇论文新在哪，每条创新点按 `strong` / `moderate` / `claimed` 标注证据强度，没有消融实验支撑的不许写成 `strong`。
2. **原文每张图都裁出来逐个讲** —— 脚本从 caption 锚点算出裁切框，模型必须真的 `Read` 过裁出来的 PNG 才能写讲解。只看 caption 写出来的必然是复述。
3. **章节对齐英文原文** —— 中文 `##` 标题与论文章节 1:1、顺序一致，自创章节最多两个（开头讲创新点、文末「总结」）。标题只说这一节讲什么，不把英文原标题带进括号，中英对应关系记在 `outline-map.json` 里；收尾固定叫「总结」，1200 字以内。
4. **口吻像研究员，不像模型** —— 一道独立的中文 AI 味门禁，查摆姿势的句式、通胀词、译文腔、破折号与加粗的用量预算、段落长度是否过于整齐。

`examples/vpp2/` 是在 VPP2（arXiv 2610.10270v2，21 页 / 10 图 8 表）上跑完整条流水线的产物，
文章、裁图和各阶段中间文件都在同一个目录里，所以两道门禁可以直接对它跑：

```bash
python3 scripts/audit_article.py examples/vpp2/article.md   # 13 pass / 0 warning / 0 error
python3 scripts/check_tone.py    examples/vpp2/article.md   # 12 pass / 0 warning / 0 error
```

`article.md` 约 1.7 万字，引用的 14 张裁图在 `examples/vpp2/assets/` 下，相对路径与文章同级，
GitHub 和知乎里都能正常显示。表格与公式的筛选清单记在 `selection-proposal.md`，
经用户确认后才写出 `selection-confirmed.json` —— skill 不许自己写这个文件，
没问过人时 `selected_tables_confirmed` 就保持 warning。

样例里只删了一样东西：`source_bundle.json` 的 `pages[].text` 原本是论文全文，不该随 skill 一起分发，
两道门禁也不读它。每页的 `character_count` 留着，仍能看出文本层抽得正不正常；自己跑一遍
`prepare_paper.py` 就有完整的 `pages[].text`。

## 安装

这是一个 Claude Code / Ducc 风格的 skill，放到 skills 目录下即可：

```bash
git clone https://github.com/NeverlanD0829/easy-paper-reader.git ~/.claude/skills/easy-paper-reader
python3 -m pip install -r ~/.claude/skills/easy-paper-reader/requirements.txt
```

唯一的硬依赖是 PyMuPDF（抽文本 + 渲染整页）和 Pillow（裁图）。缺 PyMuPDF 时流程根本起不来，脚本会直接报错退出，不做静默降级。

装好后对 agent 说「解读这篇论文」「把这篇 paper 写成知乎解读」之类的话即可触发；也可以只把 `scripts/` 当独立命令行工具用，见下。

## 流水线

脚本只做确定性的几何与文本抽取，以及可机检的门禁；所有判断留给模型。

| 阶段 | 做什么 | 产物 |
|---|---|---|
| S1 | PDF → 逐页文本、英文章节大纲、图表公式清单（含 caption 与正文提及）、216 dpi 整页渲染 | `source_bundle.json`、`rendered-pages/` |
| S2 | 从 caption 向外生长算裁切框，遇正文或邻居图表即停 | `crop_plan.json` |
| S3 | 按千分比坐标裁图，记录 provenance | `assets/`、`screenshot-index.json` |
| S4 | 四源对齐挖创新点，逐条绑定证据并分级 | `innovations.json` |
| S5 | 英文章节 → 中文章节映射，决定每张图落到哪一节 | `outline-map.json` |
| S6 | 三源合并逐图讲解（caption + 全部正文提及 + 真看过的 PNG） | 文章正文 |
| S7 | 组装 + 内容审计 | `article.md`、`audit-report.json` |
| S8 | 口吻门禁 | `tone-report.json` |
| S9 | 转成知乎编辑器能吃的 HTML（标题 / 表格 / 公式 / 图片） | `article-zhihu.html` |

两处必须停下来问人：S1 的英文大纲（大纲错了后面每一节都错）和 S6 的表格/公式筛选清单。

**知乎编辑器不认 Markdown。** 整篇 `article.md` 粘进去，`##`、`|---|`、`**`、`$x$`
会原样留在页面上当纯文本。S9 把文章转成 HTML，在浏览器里打开、全选复制，再粘进编辑器，
标题、加粗、表格、公式、图片才会变成真实元素。公式用的是知乎自己的
`https://www.zhihu.com/equation?tex=...`，所以粘过去的公式和用公式按钮敲出来的没有区别。

## 单独当命令行用

```bash
python3 scripts/prepare_paper.py paper.pdf -o /tmp/work
python3 scripts/find_assets.py /tmp/work/source_bundle.json
python3 scripts/crop_assets.py /tmp/work/crop_plan.json           # --only 'Figure 3' 可重裁单张
python3 scripts/audit_article.py /tmp/work/article.md
python3 scripts/check_tone.py /tmp/work/article.md
python3 scripts/to_zhihu_html.py /tmp/work/article.md             # → article-zhihu.html
```

两个门禁脚本都是「有 error 返回 1」，可以直接挂进 CI 或 pre-commit。

## 两道门禁查什么

`audit_article.py` 查的是解读的完整性：

| code | 内容 | 级别 |
|---|---|---|
| `figures_coverage` | 清单里的每张图都嵌进了文章 | error |
| `figure_explained` | 每张图的讲解交代了坐标系、哪个方向更好、至少两个数字、这张图管不到什么 | error |
| `figure_viewed` | 每张嵌入的裁图在 `screenshot-index.json` 里标了 `verified_by: model-viewed` | error |
| `crop_provenance` | 每张嵌入的图都有裁切来源记录 | error |
| `outline_alignment` | `outline-map.json` 里每一节都写到了，顺序与原文一致 | error |
| `no_english_tails` | 中文标题没有带英文原标题的括号尾注 | error |
| `no_invented_sections` | 自创章节不超过两个 | error |
| `closing_section` | 最后一节标题是「总结」，且不超过 1200 字 | error / warning |
| `innovation_evidence` | 每条创新点有 `strength`，非 `claimed` 的必须有 `evidence[]` | error |
| `numeric_anchors` | 引用的数字附近有 `图 N` / `表 N` 出处 | warning |
| `selected_tables_confirmed` | 表格/公式清单经用户确认 | warning |
| `zhihu_assets` | 图宽 ≤1600px、体积 ≤5MB | warning |

`figure_explained` 刻意**按功能查而不按小标题查**。早期版本逐字匹配四个加粗标签，结果是十张图十个一模一样的模板 —— 那恰恰是最重的 AI 味，所以改成查正则覆盖的四种功能，写成连续散文也能过。

`check_tone.py` 查的是中文 AI 味，判定标准是「一个认真写字的研究员会不会故意这么写」：

- **摆姿势的句式**：「不是 X 而是 Y」「不仅…而且」「本质上」「值得注意的是」「让我们」「总而言之」
- **通胀词**：赋能、助力、打造、极大地、起到了关键作用、在一定程度上、扮演……角色
- **译文腔**：「进行分析」、句首「对于……而言」、「被……所……」、一句三个「的」、复述图注
- **版式预算**：破折号每万字 6 个、加粗每万字 10 个、加粗标签+冒号的条目每万字 3 个、开段设问每万字 1.5 个、「也就是说」式复述每万字 2 个、重复的中英夹注每万字 2 个；超一倍判 error
- **节奏**：段落与句子长度的变异系数低于 0.35 判警告，同一个四字开头出现三次以上判警告；另按段检查，段内每句话长度都挤在 12 字以内的段落有 3 个就判警告，连续两句用「此外」「同时」也算
- **借权威**：泛指的「有研究表明」「业内人士认为」—— 解读一篇论文只能引这篇论文和它引用的工作；还有「论文没说，推测可能是……」，说没说是批评，用猜测把空填上会被读者当成论文的结论
- **术语漂移**：同一个东西在一段里轮换「模型／网络／架构／框架」。重复惩罚会推着模型换词，而解读里术语就是那个东西本身，该重复就重复
- **机械残留**：零宽与方向控制字符、`citeturn0search0` 这类引用脚手架、`utm_source=chatgpt.com`、没填的占位符 —— 零判断、零误报，发布前必须清掉
- **结构自述**：拿写作手法当标题（「结论先行：……」）、把内部的 `strong`/`moderate`/`claimed` 评级摆给读者、数清单（「创新点一共八条」）、替自己交代排版规范（「下文数字都标页码」）；另查十二个标题是否全是「短语：卖点」一个模子
- **姿势变形**：「是 A，不是 B」是「不是 B 而是 A」把两半调换，同一个姿势；「信息量最大」「最该看的一张图」「值得单独记住」是「起到了关键作用」换了件衣服 —— 重要性由内容证明，不由作者宣布
- **模板**：十个图解按同一个顺序展开那四件事，占七成判警告、九成判 error。这一项复用 `audit_article.py` 的 `EXPLANATION_DUTIES`，所以删掉加粗标签也躲不过去

最后三条是句子层面改干净之后剩下的那部分 AI 味，也是最难自查的 —— 每句话单独看都没问题，是骨架和节奏在出卖你。详见下一节。

改法只有一条：**整段重写，不要逐条替换短语**。模型味在句子结构里，不在单词里。

## 为什么要单独一道口吻门禁

第一版产出跑下来：45 个破折号、86 处加粗（其中 56 处是「**加粗标签**：」式的条目开头）、十张图共用一个四段模板、97 个段落长度高度整齐。内容全对，读起来仍然一眼是机器写的。

这些是版式和句法层面的习惯，靠「写得自然一点」这种提示约束不住，必须量化成预算再逐条改。`references/chinese-voice.md` 是配套的改写规范，列了每一类的 ❌/✅ 对照。

把句子和版式都改干净之后，还剩一层：文章的骨架在报自己的做法。`## 一、结论先行：这篇论文新在哪` 用写作手法做了标题；创新点对照表多出一列 `strong` / `moderate` / `claimed`，把 `innovations.json` 的内部字段直接摆给了读者；开头还有「创新点一共八条，先说最该记住的三条」和「下文每个数字后面都标了页码」。每句话单独看都通顺，合起来仍然一眼是机器写的 —— 公开文章里给论文贡献逐条打三级分，是审稿表的动作。这一层由 `scaffolding` 四项查，内部词汇一个都不许进文章。

再往后还有一层，是 `scaffolding` 查不出来的。把「不是 X 而是 Y」删干净之后，同一个姿势会以「是 A，不是 B」的形式原样回来；把「起到了关键作用」删干净之后，它会变成「掩码是整张图信息量最大、最该慢读的部分」。更隐蔽的是顺序：删掉四个加粗标签之后，十个图解照旧「交代坐标系 → 哪个方向好 → 读数 → 批判」一路走下来 —— 实测就是 10/10 共用一个顺序，读者读到第三张图就知道后面七张长什么样。`posture` 和 `template` 两项查这一层，后者直接复用审计脚本的功能正则，所以躲不过去；改法是让每张图从它自己最值得说的地方进。

口吻门禁不判断句子是否正确或有用 —— 它只找那些机器痕迹。内容对不对是 `audit_article.py` 和人的事。

## 口吻门禁的外部来源

S8 不是凭空写的。这套检查对照了 GitHub 上十余个去 AI 味 skill 和 Wikipedia 的
`Signs of AI writing`，把其中适用于中文论文解读的那些折进了 `check_tone.py`：

| 来源 | 借了什么 |
|---|---|
| [blader/humanizer](https://github.com/blader/humanizer) | 六组 26 条模式分类法，几乎所有同类 skill 都是它的分支；「不动引文、标题、专名」的豁免原则 |
| [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh) | 中文专属那一节：层叠「的」、「进行＋动词」、被字句堆叠、四字词排比、「随着……的发展」开头、套话收尾 |
| [AIScientists-Dev/academic-humanizer](https://github.com/AIScientists-Dev/academic-humanizer) | 学术 11 项通病，以及「主张—证据对应」这一层：动词的强度要配得上证据的强度 |
| [matsuikentaro1/humanizer_academic](https://github.com/matsuikentaro1/humanizer_academic) | **逐段**节奏检查（段内每句长度都挤在一个窄区间），而不是只看全文变异系数 |
| [grapeot/writing-skill](https://github.com/grapeot/writing-skill) | 硬零容忍与预算两层分开；中英夹注、「这意味着」、数字密度这些中文长文特有的阈值 |
| [misbahsy/anti-ai-slop](https://github.com/misbahsy/anti-ai-slop) | 零宽字符与方向控制符的清理表 |
| [hexiecs/talk-normal](https://github.com/hexiecs/talk-normal) | 负向排比的**反向与对称**变体（「X，而不是 Y」「适合 X，不适合 Y」）、「一句话总结」家族 |
| [DanRWilloughby/snifftest](https://github.com/DanRWilloughby/snifftest) | 可计数规则与需判断规则要分开；小样本段落不参与节奏判定 |
| Wikipedia `Signs of AI writing` | 模糊权威与引用残留；以及破折号一禁到底本身已经变成新的 AI 味这条告诫 |

有两条**没有**抄进来，理由写在这里以免以后有人再加一遍：

- **数字密度上限**（grapeot 的「一段 ≥5 个数字就报警」）。论文解读的图解按规范就要给出至少两个数字加差值，
  一段里五六个数字是本分，不是毛病。这个阈值是给评论性长文调的，和这里的体裁冲突。
- **卷引号规范化**。英文工具一律把弯引号拉直，中文正文该保留「」和“”，Humanizer-zh 第 21 条也是这么说的。

破折号预算保留，但不升级成硬禁。中文模型是否和英文模型一样滥用破折号缺乏实证，
而且 2026 年起英文圈的一刀切禁令已经把标点多样性压没了，那本身就成了新的机器痕迹。

`references/` 下的五个文件是喂给模型的提示词，用来把它推向中文写作，`chinese-voice.md` 更是大半为中文词表，
翻成英文就没用了，所以一律保持中文。口吻门禁的词表同理：每条模式的名字和那句改写建议都引用它要查的中文原文，
也留在中文。脚本其余的终端输出都是英文。

## 目录

```
SKILL.md                         编排说明
README.md                        英文版说明（主文档）
scripts/prepare_paper.py         S1  PDF → 文本 / 大纲 / 图表清单 / 整页渲染
scripts/find_assets.py           S2  caption 锚点 → 裁切框
scripts/crop_assets.py           S3  裁图 + provenance
scripts/audit_article.py         S7  内容审计
scripts/check_tone.py            S8  中文 AI 味门禁
scripts/to_zhihu_html.py         S9  article.md → 可粘进知乎编辑器的 HTML
references/innovation-spec.md        创新点来源与证据分级
references/outline-mapping.md        英文章节 → 中文章节的映射规则
references/figure-explain-spec.md    逐图讲解的四件事 + 退化反例
references/chinese-voice.md          中文 AI 味清单与改写规范
references/zhihu-format.md           知乎排版与图片约束
examples/vpp2/article.md             样例文章
examples/vpp2/assets/                它引用的 14 张裁图
examples/vpp2/*.json                 同一次运行的各阶段产物与两份门禁报告
```

## 已知限制

- 扫描版 PDF 没有文本层，流程不可用，需要先 OCR。S1 会直接报错，不会静默往下跑。
- 无书签、非标准模板的会议论文可能认不出章节大纲，此时 S1 要求人工补写 `outline`。
- 双栏论文的跨栏图表靠 x 范围判栏位，判不准时需要模型看整页渲染手写千分比坐标。
- 口吻门禁的词表针对中文技术写作，换领域（如人文、新闻）需要重调 `BUDGETS` 与词表。

## License

MIT，见 `LICENSE`。

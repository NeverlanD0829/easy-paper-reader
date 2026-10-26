# 章节映射规范

中文章节与英文原文章节 **1:1 对应**，不自创结构。这是用户的硬要求，由
`audit_article.py` 的 `outline_alignment`、`no_english_tails`、`no_invented_sections`
三个 error 级检查强制。

## 输入

来自 `source_bundle.json`：

| 字段 | 用法 |
|---|---|
| `outline[]` | 每项有 `number` / `title_en` / `title_caps` / `level` / `pdf_page` / `source`。中文章节按 `number` 顺序一一对应 |
| `outline_method` | `toc+numbers` 最可靠；`toc` / `numbered-text` 次之；`unresolved` 时必须停下来让用户确认，不能硬写 |
| `unnumbered_sections` | `ABSTRACT` / `REFERENCES` / `ACKNOWLEDGMENTS` 这类无编号标题，**不进正文章节**，见下表处理方式 |
| `outline_confirmed` | 初始为 `false`。**只有把大纲给用户看过、用户确认之后才改成 `true`**。大纲错了后面全错，这一步不能跳 |

`level` 决定标题层级：`level: 1` → `##`，`level: 2` → `###`，更深的并入上一级正文。

## 标题格式

标题只说这一节讲什么：

```markdown
## 二、方法：先把"下一个事件"预测对
### 2.1 数据处理：让描述真正指向同一个操作
```

规则：

- 中文序号用「一、二、三」，子节用「2.1」这种阿拉伯数字
- **不要把英文原标题带进括号。**`（3. Method）`这样的尾注把文章变成一份双语目录，
  读者读的是中文解读，不是对照表；中英对应关系记在 `outline-map.json` 里就够了，
  那是给写作和审计用的，不是给读者看的。`no_english_tails` 查这一项
- 冒号后面那句是中文概括，可以意译，但不能改变原章节的论述范围
- 术语括号不受影响：`（WAM）`、`（VPP2）`这类短括号是名词解释，照常写

## 英文章节 → 中文处理方式

| 英文章节 | 处理 |
|---|---|
| Abstract | 不单独成节，融进开头讲创新点那一块 |
| Introduction | →「这篇论文要解决什么问题」，承接创新点一节 |
| Related Work / Related Works | 压成一段，标题直接用「相关工作」，不逐篇列 |
| Method / Approach | 保留，子节 3.1 / 3.2 → `###` 三级标题 |
| Experiments / Evaluation | 保留，子节同上 |
| Conclusion | 并进文末的「总结」 |
| Appendix（含 A / B / C 各级） | 不单独成节；正文引用到附录图表时就地引 |
| Acknowledgments / References / Reproducibility Statement | 不进文章 |

## 只允许两个自创中文章节

1. 开头讲清新在哪（含创新点—证据对照表和术语约定表）
2. 文末的「总结」

其余一律对齐原文章节。多出第三个自创 `##` 标题即为 `no_invented_sections` 失败。

**最后一节的标题固定写「总结」**，不要换成「怎么正确理解这些结论」「写在最后」这类
自拟说法 —— 读者扫目录时要一眼认出收尾在哪，`closing_section` 查这一项。

**总结要短**，1200 字以内，同样由 `closing_section` 查。方法和成绩各一句，证据边界
两三条，真正站得住的结论一两条就够。批判在每张图下面已经就地给过了，收尾再把它们
铺成一张六条清单，是论文解读最常见的注水方式：读者刚读完的内容被原样复述一遍。

这两个标题要说清这一节讲什么，**不要拿写作手法当标题**。「结论先行」是流水线内部对
这一块的叫法，写成 `## 一、结论先行：……` 读者看到的就是作者在报自己的写法。
写成「新在哪里，证据有多硬」这种直接说内容的，`check_tone.py` 的 `scaffolding` 项查这个。

## outline-map.json 结构

```json
{
  "schema_version": "1.0",
  "outline_confirmed": true,
  "sections": [
    {
      "number": "3",
      "title_en": "Method",
      "level": 1,
      "heading_zh": "## 二、方法：先把\"下一个事件\"预测对",
      "pdf_page": 4,
      "assets": ["Figure 4", "Equation 1", "Equation 4"],
      "note": "子节 3.1/3.2/3.3 各自带图"
    }
  ],
  "invented_sections": [
    {"heading_zh": "## 一、新在哪里，证据有多硬", "position": "before-all"},
    {"heading_zh": "## 六、总结", "position": "after-all"}
  ]
}
```

`title_en` 与 `heading_zh` 配成一对，就是中英对应关系的存放处：
`outline_alignment` 拿 `sections[].heading_zh` 的顺序去比文章里 `##` / `###` 的出现顺序，
每一节都要写到、顺序不许乱；对不上 `heading_zh` 的标题算自创节，最多两个。
写作途中改了中文标题的措辞不要紧，检查按标题开头比对，但改了意思要同步回这个文件。

`assets[]` 决定每张图表落到哪一节，取值是 `evidence_inventory` 里的 `id`
（`"Figure 6"` / `"Table 2"` / `"Equation 1"` 这种带空格的原样写法）。

分配规则：

- 以作者**实际拿它论证**的那一节为准：读 `mentions[]` 里该 float 的 window 内容，
  看它出现在哪一段论证里
- `mentions[].section_hint` 只是起点，不是答案。它按「页码不大于该页的最后一个章节」
  推出来，而一页往往跨着标题，所以标题之前的提及会被算到后一节去。以 VPP2 为例，
  `Figure 1` 的 hint 是 `2` 但它属于 Introduction，`Table 2` / `Figure 6` / `Figure 7`
  的 hint 是 `4.2` 但作者在 4.1 里论证，`Figure 9` / `Table 4` 的 hint 甚至是 `6 Conclusion`
  —— 而 Conclusion 按上表是要被溶进文末自创节的，照 hint 走会把图挂到不存在的章节上。
  改派时在该条 `assets[]` 旁边记一句理由
- `fallback` 为 `"section-body"`（正文无提及）时，按 `pdf_page` 落到 `outline[]` 中
  页码不大于它的最后一个章节
- 附录里的图表（如 VPP2 的 `Figure 10` / `Table 5`–`Table 8`）挂到正文引用它的那一节，
  不新开附录节。附录图号大于正文图号，这样挂会让文章里的图号不连续（图 10 出现在图 8 之前），
  这是允许的，但必须在嵌图前写一句过渡交代它来自附录
- 每个 figure 必须且只能出现在一个 `assets[]` 里——`figures_coverage` 检查这一点

# 创新点挖掘规范

创新点是文章的第一个内容产物，产出 `innovations.json`。写文章之前必须先完成这一步——
文章开头那段「新在哪里」和创新点—证据对照表都从这个文件渲染。

## 四处挖掘来源（必须全部对齐，不能只看 Abstract）

| 来源 | 怎么定位 | 挖什么 |
|---|---|---|
| Abstract | `pages[0].text`，找 "we propose / we introduce / we present" 句 | 作者自己总结的卖点，但措辞最含糊 |
| Introduction 末尾 | `outline[]` 里 Introduction 那节的 `pdf_page`，找 bullet 或 "First… Second… Third…" | 作者列的 contribution 清单，最接近真实创新点 |
| Method 章节 | `outline[]` 里 level≥2 的子节标题 + 正文里**带名字的组件** | 作者给组件起了名字，才说明他认为那是卖点 |
| Related Work | 被用来对比的对象 | 创新点 = 本文有、对比对象没有的那部分 |

四处交叉后合并同义项。一个候选创新点若只在 Abstract 出现、Method 里找不到对应的
具名组件，通常是包装语言而不是创新点。

## 交叉核验：每条都必须回答"哪张图/表证明它有用"

这是解读文和复述摘要的分水岭。对每个候选创新点，在
`evidence_inventory` 和 `mentions[]` 里找能隔离出该组件贡献的证据，填进 `evidence[]`。
找不到证据的条目不删除，但强度只能标 `claimed`。只有 `claimed` 允许 `evidence[]` 为空，
`strong` 和 `moderate` 缺 `evidence[]` 会被 `innovation_evidence` 判 error。
`claimed` 的更好写法是留一条 `evidence`：`locator` 指向作者主张它的那一处，
`what_it_shows` 写明「全文没有隔离该组件的实验，故记为 claimed」。

## 三级强度判定

| strength | 判定标准 |
|---|---|
| `strong` | 有**针对该组件的消融或对照实验**——表里能找到只去掉这一个组件的那一行 |
| `moderate` | 只有整体系统对比，组件贡献未被隔离 |
| `claimed` | 只有作者陈述，没有任何对应实验 |

判定时看的是"能不能把这个组件单独关掉再看掉多少分"，不是看结果好不好。

## innovations.json 结构

```json
[{
  "id": "inn-01",
  "name_zh": "按完整操作事件采样未来帧",
  "name_en": "next-event video prediction",
  "what": "预测目标从固定步长的未来帧改成一个完整操作事件的末帧序列",
  "why_new": "让条件（详细指令）到目标（未来帧）的映射唯一化，而不是多模态的",
  "vs_prior": "LVP / Wan / Cosmos 系列按固定时间窗采样，同一指令对应多种合理未来",
  "evidence": [{
    "locator": "表 2",
    "what_it_shows": "VPP2-Fixed-Step 行把事件级采样换成固定步长，指令遵循成功率从 0.80/0.90 掉到 0.48/0.42"
  }],
  "strength": "strong",
  "caveat": "该消融只在指令遵循这一个指标上做，未验证对下游动作性能的影响"
}]
```

字段含义：`what` 是做了什么改动；`why_new` 是为什么这个改动有意义；`vs_prior` 必须点名
具体的对比方法，不能写"以往工作"。`caveat` 写这条创新点的证据边界，会被用到正文的
「没能说明什么」里。

## VPP2 实例判定

| 创新点 | strength | 依据 |
|---|---|---|
| 事件级视频预测采样 | `strong` | 表 2 有 `VPP2-Fixed-Step` 消融行，直接隔离了采样方式这一个变量 |
| 详细 caption 生成流程 | `moderate` | 只有整体系统对比，没有"简单 caption vs 详细 caption"的单独消融 |
| 跨数据集坐标系对齐 | `moderate` | 图 3 只定性展示对齐结果，没有关掉对齐再测一遍的实验 |
| LoRA 适配 | `moderate` | 属于工程选择，论文未给出 full fine-tune 的对照 |

注意这四条里只有一条是 `strong`。如实标注，不要把 `moderate` 写成 `strong`——
文章开头那张对照表的价值完全来自它的诚实。

## 渲染到文章开头

- 「三句话说清创新在哪」：取 `strength` 最高的 1–3 条，各一句 `name_zh` + `what`
- 创新点—证据对照表：Markdown 表格，列为 创新点 / 它改了什么 / 论文拿什么支撑
- **`strength` 三级只存在于 JSON 里，不要渲染成表格的一列**，也不要在正文里写
  `strong` / `moderate` / `claimed` 这几个词。强度是写给流水线自己看的；读者要看的是
  「表 2 只换了采样方式这一个变量」这种具体说法。把判断写进「论文拿什么支撑」那一格，
  最硬的那条顺带点明它是全文唯一的单变量对照。贴标签是审稿表的写法，不是文章的写法。
- `claimed` 级别的条目必须出现在表里，不能因为没证据就不写

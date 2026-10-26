#!/usr/bin/env python3
"""Voice gate for the easy-paper-reader skill.

article.md -> tone-report.json

Counts the Chinese habits that make a generated reading sound generated:
staged contrasts, stock transitions, inflated vocabulary, translationese, and
decoration used in place of content. Budgets scale with article length, since
one em dash in a long piece is a choice and thirty is a tic.

Nothing here can tell whether a sentence is true or useful. It only finds the
tells; references/chinese-voice.md says what to do about each one.

Several checks are adapted from the community de-slop skills surveyed in
references/chinese-voice.md ("外部来源"): blader/humanizer's pattern taxonomy,
op7418/Humanizer-zh's Chinese-only section, AIScientists-Dev/academic-humanizer's
claim-evidence layer, matsuikentaro1/humanizer_academic's per-paragraph rhythm,
grapeot/writing-skill's two-tier thresholds, misbahsy/anti-ai-slop's sanitizer,
and hexiecs/talk-normal's reversed negative parallelism.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

# Per 10,000 characters of body text. Budgets rather than bans: a researcher
# does reach for an em dash or a bold term, just not in every paragraph.
BUDGETS = {
    "dash": 6.0,          # ——
    "bold": 10.0,         # **anything**
    "bold_label": 3.0,    # **短语**： used as a list label
    "question": 1.5,      # 设问自答：开段先问一句再自己回答
    "restate": 2.0,       # 也就是说／换句话说：同一句话再说一遍
    "gloss": 2.0,         # 术语（English）：首次出现给一次就够，重复才算
}
FLOOR = 3  # below this a count is too small to read anything into

STAGING = (
    ("负正对照", r"不是[^，。；！？]{1,25}，?而是", "「不是X，而是Y」把判断摆成姿势；直接说 Y"),
    ("反向排比", r"，\s*而不是[^，。；！？]{2,20}[。；]|适合[^，。；]{2,16}，不适合",
     "「X，而不是 Y」是同一个姿势换了位置；只说 X"),
    ("递进排比", r"不仅[^。；]{1,30}(而且|更是|还是|更|还)", "「不仅…而且…」多半只有一层意思"),
    ("伪深刻", r"真正的(问题|答案|关键|价值)|本质上|归根结底|说到底|从根本上|核心在于",
     "这类短语宣告深刻但不提供信息"),
    ("无人反驳", r"需要(说明|指出)的是|必须承认|不可否认|平心而论|客观地说",
     "没人提出异议时不必先行辩解"),
    ("程式过渡", r"值得注意的是|不难看出|显而易见|由此可见|众所周知|可以看到",
     "读者看得见，不需要被提示去看"),
    ("开场铺垫", r"让我们|我们不妨|接下来我们|首先我们|在开始之前", "直接写结论，不要起跑助跑"),
    ("起兴开头", r"随着[^，。]{2,20}的(发展|普及|兴起|成熟)|近年来[^。]{0,24}(越来越|日益|受到[^。]{0,6}关注)|"
                r"一直以来|自古以来",
     "「随着……的发展」是中文论文最典型的 AI 开场；直接写这篇论文在做什么"),
    ("收束套话", r"总而言之|综上所述|总的来说|总体而言|一言以蔽之|不失为|一句话(总结|概括|讲|说清|落地)",
     "总结句通常只是把上一段再说一遍"),
)

INFLATION = (
    ("通胀词", r"赋能|助力|打造|彰显|诠释|加持|生态闭环|全链路|深度融合|强有力|"
              r"卓越|优异|亮眼|惊艳|颠覆性?|革命性|里程碑|开创性|强大的",
     "宣传稿词汇，技术文里换成具体动词"),
    ("程度灌水", r"极大地|大幅度地|充分地?|深刻地?|全面地|有效地|显著地|进一步地",
     "副词替代了数字；把数字写出来"),
    ("制造重要性", r"起到了?(关键|重要)作用|提供了有力(支撑|支持)|奠定了(坚实)?基础|"
                r"具有重要(意义|价值)|不可或缺|至关重要",
     "重要性要由结果显示，不由形容词宣布"),
    ("堆叠模糊", r"在一定程度上|某种(意义|程度)上|或许可以说|可以预见|大体上说",
     "连用的限定语等于没有判断；给出边界条件"),
    ("虚位动词", r"扮演了?.{0,6}角色|充当了?.{0,6}角色|作为一种.{0,8}存在",
     "用「是」「有」就够了"),
    ("套话比喻", r"赛道|护城河|双刃剑|弯道超车|银弹|圣杯|范式转移|奇点|降维打击",
     "媒体稿的固定喻体；论文解读里换成具体说法"),
)

# Borrowed authority. A paper reading may cite this paper and the work it cites;
# anything vaguer is authority with no address. The second pattern is the
# source-availability hedge: saying the paper omits something is criticism, then
# filling the hole with a guess turns it into a claim the reader will attribute
# to the authors.
AUTHORITY = (
    ("模糊权威", r"(有|多项|大量|不少|众多)(研究|工作|实验|论文|实践)(表明|显示|指出|认为|证明)|"
                r"(业内|业界|学界|圈内)(人士)?(认为|公认|普遍)|普遍认为",
     "泛指的「有研究表明」是凭空借权威；只引这篇论文和它引用的工作"),
    ("推测填空", r"(没有|未)(给出|说明|交代|公布|披露)[^。；]{0,20}(推测|猜测|估计|应该是|可能是)|"
                r"(推测|猜测)(可能|应该|大概)",
     "论文没写就写没写；用猜测把空填上，读者会当成论文的结论"),
)

TRANSLATIONESE = (
    ("进行式", r"进行(分析|对比|比较|验证|测试|评估|训练|讨论|优化|改进|建模)",
     "「进行分析」写成「分析」"),
    ("介词开头", r"(^|[。；\n])\s*(对于|关于|基于以上|基于此|在.{2,12}的情况下)",
     "译文腔的句首搭架子"),
    ("被所", r"被[^，。]{1,12}所", "「被…所…」是译文句式"),
    ("的的", r"的[^，。；的]{1,5}的[^，。；的]{1,5}的", "一句里三个「的」，拆开"),
    ("图注复述", r"(这|该|本)(张|幅)?图(展示|显示|呈现)了|本文提出了一种",
     "复述图注不是解读"),
)

# The tells that survive a clean sentence-level pass. Two kinds, both structural:
# the text narrating its own method instead of carrying it out, and the
# pipeline's internal vocabulary (strength levels, stage names, the four duties)
# reaching the page. A researcher writes the finding, not the procedure that
# produced it — and never grades a paper on a rubric in public.
SCAFFOLDING = (
    ("自述结构", r"结论先行|金字塔原理|先说(最|结论|最该)|先讲(结论|最)|下面这张表|"
                r"下面(先说|先讲|这一节|这几段)|先约定|约定一下|按上文|如前所述|"
                r"本文将|本节(将|先)|后面(会|将)(看到|讲|说|提到)",
     "读者不需要被告知文章接下来要做什么；直接做"),
    ("评级泄漏", r"证据强度|强度分[三二四]级|强度(为|是|记|标)|"
                r"(记|判|标|算|评)(为|作|成)?\s*(strong|moderate|claimed)|"
                r"\bstrength\b|打分表|评级",
     "三级强度是内部数据结构，不是文章里的词；把判断写成句子"),
    ("清单口吻",
     r"(创新点|贡献|改动|问题|结论)(一共|共有|总共)\s*[0-9一二三四五六七八九十]+\s*(条|点|个)|"
     r"[0-9一二三四五六七八九十]+\s*(条|点)里(只)?(有|剩)",
     "数清单是审稿表的写法；说哪一条站得住，不说几条里有几条"),
    ("自述规范", r"(下文|全文|本文|后文)[^。；]{0,14}(一律|统一|都标|均标|约定|写作)",
     "排版和用词规范是作者自己的事，不写给读者看"),
)

# Posture that survives the staging check because it is inverted or dressed up.
# `是 A，不是 B` is `不是 B，而是 A` with the halves swapped; announcing that a
# figure is the most important one in the paper is `起到了关键作用` wearing a
# better suit.
POSTURE = (
    ("反向对照", r"[，。；：][^，。；！？]{2,22}，不是[^，。；！？]{2,22}[。；]",
     "「是A，不是B」和「不是B而是A」是同一个姿势；只说 A"),
    ("自封重点", r"值得(单独)?(记住|注意|一提)|最该[看读记慢]|信息量最大|最重要的一张|"
                r"全文只有这(张|幅|段)|是(整篇|全文|这篇)[^。]{0,16}(回答|答案|交代)|"
                r"关键在于|要点在于|重点在于",
     "读者自己判断轻重；把那张图为什么重要说出来，别宣布它重要"),
    ("空评价句", r"(^|[。；！？\n])\s*(这|那|此)(一)?(点|条|处|张图|组数据|个结果)?\s*"
                r"(很|非常|尤其|格外|相当|确实)?(重要|关键|有意思|值得玩味)[。！]",
     "单独一句只有结论没有内容；把它为什么重要写出来"),
    ("虚假施动", r"(数据|实验|结果|曲线|市场|共识)[^。；]{0,4}(告诉|教会|选择了|学会了|决定了)",
     "数据会显示，不会告诉你什么；下判断的主语应该是人"),
    ("自造概念", r"[「“][^「」“”]{2,8}(悖论|陷阱|鸿沟|定律|效应|范式)[」”]",
     "给现象起个带引号的新名字，再当既有概念用"),
)

RESIDUE = re.compile(r"作为一个?(AI|人工智能|语言模型)|我是一个|希望这篇|以上就是|"
                     r"如有(问题|错误)|仅供参考|本文由.{0,8}生成|截至我的知识")
# Mechanical, provenance-revealing, zero judgement required. Lists adapted from
# misbahsy/anti-ai-slop's sanitize.py and Wikipedia:Signs of AI writing §6.3/§7.6.
INVISIBLE = re.compile(
    "[\u200b\u200c\u200d\u2060\ufeff\u00ad\u202a-\u202e\ufff9-\ufffb]")
DEBRIS = re.compile(r":contentReference\[oaicite|citeturn\d|oai_citation|attributableIndex|"
                    r"\[cite:\s*\d|\[span_\d+\]\(start_span\)|<grok-card|【\d+†|"
                    r"\[attached_file:|:::writing\{|utm_source=(chatgpt|openai)|"
                    r"referrer=grok\.com")
PLACEHOLDER = re.compile(r"\[占位\]|\[待补\]|\[你的[^\]]{0,8}\]|\bTODO\b|\bTBD\b|"
                         r"XX\s*%|access-date=\d{4}-XX")
RESTATE = re.compile(r"也就是说|换句话说|换言之|简单来说|说白了|通俗地?说|翻成人话|这意味着")
# 术语（Term）is right on first mention and noise afterwards, so only repeats
# are counted.
GLOSS = re.compile(r"[一-鿿]\s*（\s*([A-Za-z][A-Za-z0-9\s\-\./]{2,40})）")

EMOJI = re.compile(r"[\U0001F300-\U0001FAFF]")

SIGNPOST = re.compile(r"[✅❌⭐→➡✔✘]")
RULE_LINE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", re.M)
TRICOLON = re.compile(r"[，。；：]([^，。；：、]{6,14})，([^，。；：、]{6,14})，([^，。；：、]{6,14})[。；]")
BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
BOLD_LABEL = re.compile(r"(?:^|\n)\s*(?:[-*+]\s*|\d+[.、]\s*)?\*\*([^*\n]{2,14})\*\*\s*[：:]")


def add(findings: list[dict], level: str, code: str, message: str) -> None:
    findings.append({"level": level, "code": code, "message": message})


def body_text(article: str) -> str:
    """Prose only: no code, headings, tables, image embeds, quotes or maths.

    A table row legitimately holds short symmetric phrases and a heading
    legitimately holds an em dash, so counting them would punish the format
    instead of the voice. Blockquotes and inline code are dropped for a
    different reason: a translated line from the paper's own abstract may well
    contain 本质上, and flagging the authors' wording as the writer's tic is a
    false positive every surveyed tool warns about.
    """
    text = re.sub(r"```.*?```", "", article, flags=re.S)
    text = re.sub(r"^\s*#{1,6}.*$", "", text, flags=re.M)
    text = re.sub(r"!\[[^\]]*\]\([^)\s]*\)", "", text)
    text = re.sub(r"^\s*\|.*$", "", text, flags=re.M)
    text = re.sub(r"^\s*>.*$", "", text, flags=re.M)
    text = re.sub(r"`[^`\n]*`", "", text)
    text = re.sub(r"\$[^$\n]*\$", "", text)
    return text


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if len(p.strip()) > 30]


def scaffold_text(article: str) -> str:
    """Everything a reader sees, minus code: headings and table cells included.

    Scaffolding hides exactly where body_text() is not looking — a stage name in
    an `##` heading, a `**strong**` grade in a table cell.
    """
    return re.sub(r"```.*?```", "", article, flags=re.S)


def check_template(findings: list[dict], article: str) -> dict:
    """Ten figures explained in the same order is still one template.

    Deleting the four bold labels is not enough: if every block does
    orientation, then direction, then limits, in that order, the reader feels
    the machine anyway. A researcher enters a figure wherever that figure is
    interesting — sometimes at the number, sometimes at the doubt.
    """
    try:
        # Explicit, because -I (isolated mode) drops the script's own directory
        # from sys.path. audit_article.py is this script's sibling in the skill.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from audit_article import EXPLANATION_DUTIES, figure_blocks
    except ImportError:  # check_tone.py copied out on its own
        return {}
    blocks = {path: body for path, body in figure_blocks(article).items()
              if "figure-" in path}
    if len(blocks) < 4:
        return {"figure_blocks": len(blocks)}
    orders: dict[tuple, int] = {}
    for body in blocks.values():
        found = []
        for name, pattern in EXPLANATION_DUTIES:
            hit = re.search(pattern, body)
            if hit:
                found.append((hit.start(), name))
        order = tuple(name for _, name in sorted(found))
        if len(order) >= 2:
            orders[order] = orders.get(order, 0) + 1
    if not orders:
        return {"figure_blocks": len(blocks)}
    common, repeats = max(orders.items(), key=lambda kv: kv[1])
    share = repeats / len(blocks)
    metrics = {"figure_blocks": len(blocks),
               "figure_order_variants": len(orders),
               "figure_order_share": round(share, 2)}
    if share >= 0.7:
        add(findings, "error" if share >= 0.9 else "warning", "template",
            f"{repeats}/{len(blocks)} 张图的讲解按同一个顺序展开"
            f"（{' → '.join(common)}）：换入口，有的先甩数字，有的先说疑点")
    else:
        add(findings, "pass", "template",
            f"图解入口有 {len(orders)} 种顺序，最常见的占 {share:.0%}")
    return metrics


def check_headings(findings: list[dict], article: str) -> dict:
    """Twelve headings cut to one template is the same tic as twelve bold labels."""
    titles = [m.group(1).strip() for m in
              re.finditer(r"^#{2,3}\s+(.*)$", article, flags=re.M)]
    if len(titles) < 6:
        return {"headings": len(titles)}
    colons = sum(1 for t in titles if "：" in t or ":" in t)
    share = colons / len(titles)
    if share >= 0.8:
        add(findings, "warning", "headings",
            f"{colons}/{len(titles)} 个标题都是「短语：卖点」的模子："
            "有些章节直接用它的名字就够了")
    else:
        add(findings, "pass", "headings",
            f"标题形式有变化（{colons}/{len(titles)} 带冒号副标题）")
    return {"headings": len(titles), "headings_with_subtitle": colons}


def sample(hits: list[str], limit: int = 3) -> str:
    seen, out = set(), []
    for hit in hits:
        clean = re.sub(r"\s+", "", hit if isinstance(hit, str) else hit[0])
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
        if len(out) == limit:
            break
    return "、".join(f"「{item}」" for item in out)


def check_family(findings: list[dict], text: str, family: tuple,
                 code: str) -> int:
    """One finding per pattern that fires. Three sightings is a habit."""
    total = 0
    for name, pattern, advice in family:
        hits = [m.group(0) for m in re.finditer(pattern, text)]
        if not hits:
            continue
        total += len(hits)
        add(findings, "error" if len(hits) >= 3 else "warning", code,
            f"{name} ×{len(hits)}：{sample(hits)} / {advice}")
    return total


def check_budget(findings: list[dict], code: str, label: str, count: int,
                 length: int, per_10k: float) -> None:
    budget = max(FLOOR, round(per_10k * length / 10000))
    if count > 2 * budget:
        add(findings, "error", code,
            f"{label} {count} 处，预算 {budget}（每万字 {per_10k:g}）：已经成为版式习惯")
    elif count > budget:
        add(findings, "warning", code, f"{label} {count} 处，预算 {budget}")
    else:
        add(findings, "pass", code, f"{label} {count} 处，在预算 {budget} 内")


def check_rhythm(findings: list[dict], text: str) -> dict:
    """Uniform length is the tell; real writing alternates short and long."""
    paras = paragraphs(text)
    sentences = [s for s in re.split(r"[。！？\n]", text) if len(s.strip()) > 8]
    metrics = {"paragraphs": len(paras), "sentences": len(sentences)}
    for name, items, floor in (("段落", paras, 12), ("句子", sentences, 40)):
        if len(items) < floor:
            continue
        lengths = [len(i) for i in items]
        mean = statistics.mean(lengths)
        spread = statistics.pstdev(lengths) / mean if mean else 0
        metrics[f"{'para' if name == '段落' else 'sentence'}_spread"] = round(spread, 3)
        if spread < 0.35:
            add(findings, "warning", "rhythm",
                f"{name}长度过于整齐（变异系数 {spread:.2f} < 0.35）：长短句交替着写")
        else:
            add(findings, "pass", "rhythm", f"{name}长短有变化（{spread:.2f}）")
    openers: dict[str, int] = {}
    for para in paras:
        head = para.lstrip("*-+ 　")[:4]
        if len(head) == 4:
            openers[head] = openers.get(head, 0) + 1
    repeated = sorted((n, h) for h, n in openers.items() if n >= 3)
    if repeated:
        worst = "、".join(f"「{h}」×{n}" for n, h in reversed(repeated[:3]))
        add(findings, "error" if repeated[-1][0] >= 5 else "warning", "rhythm",
            f"多个段落用同一个开头：{worst}")
    return metrics


def check_para_rhythm(findings: list[dict], text: str) -> dict:
    """A healthy document-wide CV can still hide uniform paragraphs.

    check_rhythm() averages over the whole article, so a piece whose every
    paragraph is internally flat but which alternates short and long paragraphs
    passes. humanizer_academic checks each paragraph instead; snifftest's guard
    (only paragraphs of 4+ sentences) keeps small samples from firing.
    """
    paras = paragraphs(text)
    flat, connective = 0, 0
    for para in paras:
        sents = [s.strip() for s in re.split(r"[。！？]", para) if len(s.strip()) > 4]
        if len(sents) >= 4 and len(para) >= 60:
            lengths = [len(s) for s in sents]
            if max(lengths) - min(lengths) <= 12:
                flat += 1
        heads = [bool(re.match(r"(此外|同时|另外|并且|其次|再者|与此同时)", s))
                 for s in sents]
        connective += sum(1 for a, b in zip(heads, heads[1:]) if a and b)
        for a, b, c in zip(sents, sents[1:], sents[2:]):
            if len(a) >= 6 and a[:3] == b[:3] == c[:3]:
                connective += 1
    metrics = {"flat_paragraphs": flat, "connective_runs": connective}
    if flat >= 3:
        add(findings, "error" if flat >= 6 else "warning", "rhythm",
            f"{flat} 个段落内部每句话长度几乎相同（极差 ≤12 字）：段内也要长短交替")
    if connective >= 2:
        add(findings, "warning", "rhythm",
            f"连续两句用同一类连接词或同一个开头 {connective} 处："
            "「此外」「同时」一段里一次就够")
    if flat < 3 and connective < 2:
        add(findings, "pass", "rhythm", "段内句长有变化，没有连续同头句")
    return metrics


def check_terms(findings: list[dict], text: str) -> dict:
    """Elegant variation: one referent rotated through four synonyms.

    A repetition penalty pushes the model to call the same thing 模型, then
    网络, then 架构, then 框架. A researcher repeats the term, because in a
    paper reading the term is the thing. Only fires when three or more members
    of one group share a paragraph, which is hard to do by accident.
    """
    groups = (("模型", "网络", "架构", "框架"),
              ("方法", "方案", "做法", "思路", "路线"),
              ("提升", "改进", "优化", "增强"),
              ("实验", "试验", "测试", "评测"))
    hits = []
    for para in paragraphs(text):
        for group in groups:
            used = [w for w in group if w in para]
            if len(used) >= 3:
                hits.append("／".join(used))
    if len(hits) >= 3:
        add(findings, "warning", "terms",
            f"{len(hits)} 个段落在同一段里轮换近义词（如 {hits[0]}）："
            "同一个东西用同一个词，重复不是毛病")
    else:
        add(findings, "pass", "terms", f"近义词轮换 {len(hits)} 处，术语基本稳定")
    return {"synonym_rotations": len(hits)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("article", type=Path)
    parser.add_argument("-o", "--out", type=Path,
                        help="defaults to tone-report.json beside the article")
    args = parser.parse_args()

    if not args.article.is_file():
        sys.exit(f"not a file: {args.article}")
    article = args.article.read_text(encoding="utf-8")
    text = body_text(article)
    length = len(text)

    findings: list[dict] = []
    tells = 0
    tells += check_family(findings, text, STAGING, "staging")
    tells += check_family(findings, text, INFLATION, "inflation")
    tells += check_family(findings, text, TRANSLATIONESE, "translationese")
    tells += check_family(findings, text, AUTHORITY, "authority")
    tells += check_family(findings, scaffold_text(article), SCAFFOLDING,
                          "scaffolding")
    tells += check_family(findings, scaffold_text(article), POSTURE, "posture")

    residue = [m.group(0) for m in RESIDUE.finditer(text)]
    if residue:
        add(findings, "error", "residue", f"对话残留：{sample(residue)}")
    for name, pattern, label in (
            ("invisible", INVISIBLE, "零宽与方向控制字符"),
            ("debris", DEBRIS, "模型来源残留（引用脚手架、utm 参数）"),
            ("placeholder", PLACEHOLDER, "没填的占位符")):
        found = [m.group(0) for m in pattern.finditer(article)]
        if found:
            add(findings, "error", "residue",
                f"{label} {len(found)} 处：发布前必须清掉"
                + (f"（{sample(found)}）" if name != "invisible" else ""))
    emoji = [m.group(0) for m in EMOJI.finditer(article)]
    if emoji:
        add(findings, "error", "decoration",
            f"正文里有 emoji {len(emoji)} 处：{sample(emoji)}")
    signposts = [m.group(0) for m in SIGNPOST.finditer(text)]
    if len(signposts) > 2:
        add(findings, "warning", "decoration",
            f"勾叉箭头等符号 {len(signposts)} 处：行文里用文字说，表格和公式里留着无妨")
    rules = len(RULE_LINE.findall(article))
    if rules:
        add(findings, "warning", "decoration", f"分节横线 {rules} 条：标题已经分节了")
    tricolons = [m for m in TRICOLON.finditer(text)
                 if max(map(len, m.groups())) - min(map(len, m.groups())) <= 2]
    if len(tricolons) >= 4:
        add(findings, "warning", "staging",
            f"等长三连排比 {len(tricolons)} 处："
            f"{sample([m.group(0)[:24] for m in tricolons])} / 第三项通常是凑的")
        tells += len(tricolons)

    dashes = text.count("——")
    bolds = BOLD.findall(text)
    labels = BOLD_LABEL.findall(text)
    check_budget(findings, "dash", "破折号", dashes, length, BUDGETS["dash"])
    check_budget(findings, "bold", "加粗", len(bolds), length, BUDGETS["bold"])
    check_budget(findings, "bold_label", "加粗标签+冒号的条目", len(labels),
                 length, BUDGETS["bold_label"])
    openers = re.findall(r"(?:^|\n)[^\n？]{4,60}？", text)
    check_budget(findings, "question", "开段设问", len(openers), length,
                 BUDGETS["question"])
    restates = RESTATE.findall(text)
    check_budget(findings, "restate", "「也就是说」式复述", len(restates), length,
                 BUDGETS["restate"])
    glosses = [m.group(1).strip() for m in GLOSS.finditer(text)]
    seen: set[str] = set()
    repeats = []
    for term in glosses:
        key = re.sub(r"\s+", "", term).lower()
        if key in seen:
            repeats.append(term)
        seen.add(key)
    check_budget(findings, "gloss", "重复的中英夹注", len(repeats), length,
                 BUDGETS["gloss"])

    metrics = {"body_characters": length, "tells": tells, "dashes": dashes,
               "bold": len(bolds), "bold_labels": len(labels),
               "restatements": len(restates), "glosses": len(glosses),
               "gloss_repeats": len(repeats),
               "tells_per_10k": round(tells * 10000 / length, 1) if length else 0}
    metrics.update(check_rhythm(findings, text))
    metrics.update(check_para_rhythm(findings, text))
    metrics.update(check_terms(findings, text))
    metrics.update(check_headings(findings, article))
    metrics.update(check_template(findings, article))
    if length and tells * 10000 / length > 8:
        add(findings, "error", "density",
            f"句式与词汇类共 {tells} 处，每万字 {metrics['tells_per_10k']}，"
            "超过 8：整段重写，不要逐条替换短语")

    counts = {level: sum(1 for f in findings if f["level"] == level)
              for level in ("pass", "warning", "error")}
    report = {"schema_version": "1.0", "article": str(args.article),
              "summary": {"status": "fail" if counts["error"] else "pass",
                          "passes": counts["pass"], "warnings": counts["warning"],
                          "errors": counts["error"]},
              "metrics": metrics, "findings": findings}
    out = args.out or args.article.parent / "tone-report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")

    print(f"{out}")
    print(f"  {report['summary']['status'].upper()}  {counts['pass']} pass, "
          f"{counts['warning']} warning, {counts['error']} error")
    for finding in findings:
        if finding["level"] != "pass":
            print(f"  [{finding['level']:7}] {finding['code']}: {finding['message']}")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""中文规则确定性检查 v0（工程演练版）。

只读输入；仅在显式 --out 运行目录写报告。
能愿动词分组依据 GB/T 1.1-2020；词语区分参照法工委《立法技术规范（试行）（一）》(2009)。
本工具定位疑似变化，不证明语义等价，不自动改稿；零告警不等于无变义。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

TOOL_VERSION = "v0.2.1-engineering"

DISCLAIMER = (
    "本次结果基于合成最小编辑对与示例语料，不可直接外推至真实规则维护；"
    "公开控制通过仅证明已知用例回归；未进行未辅助复核对照，仅测复核成本，不作减负判断。"
)

COVERAGE_NOTES = [
    "术语检查按 v0.2 排除，本工具不做术语表比对。",
    "单字能愿动词（应、可、宜等）使用守卫词表，仍可能漏判生僻用法。",
    "未覆盖：不依赖词项／句式的改写、语序调整、跨句搬迁、隐含条件、同义替换。",
    "本工具是疑似变化检测仪器，不判定语义等价；零告警不等于没有变义。",
    "示例语料与公开控制材料重叠时仅供演示，不参与保留判定。",
]

MODAL = {
    "不应当": ("模态", "禁止", 4),
    "不应该": ("模态", "禁止", 4),
    "不得": ("模态", "禁止", 4),
    "禁止": ("模态", "禁止", 4),
    "不应": ("模态", "禁止", 4),
    "不许": ("模态", "禁止", 4),
    "应当": ("模态", "义务", 3),
    "应该": ("模态", "义务", 3),
    "必须": ("模态", "义务", 3),
    "须": ("模态", "义务", 3),
    "应": ("模态", "义务", 3),
    "宜": ("模态", "推荐", 2),
    "不宜": ("模态", "不推荐", 2),
    "可以": ("模态", "允许", 1),
    "可": ("模态", "允许", 1),
    "不必": ("模态", "免于", 0),
    "无须": ("模态", "免于", 0),
    "无需": ("模态", "免于", 0),
    "能够": ("模态", "能力", None),
    "能": ("模态", "能力", None),
    "不能够": ("模态", "无能力", None),
    "不能": ("模态", "无能力", None),
    "不可能": ("模态", "不可能", None),
    "可能": ("模态", "可能", None),
}

CONNECT = {
    "并且": ("连接", "联合"),
    "以及": ("连接", "联合"),
    "同时": ("连接", "联合"),
    "与": ("连接", "联合"),
    "且": ("连接", "联合"),
    "和": ("连接", "联合"),
    "或者": ("连接", "选择"),
    "或": ("连接", "选择"),
}

SCOPE = {
    "本文件": ("范围", "本事项"),
    "本规则": ("范围", "本事项"),
    "本方案": ("范围", "本事项"),
    "本次": ("范围", "本事项"),
    "此次": ("范围", "本事项"),
    "本轮": ("范围", "本事项"),
    "本文": ("范围", "本事项"),
    "仅限于": ("范围", "限定"),
    "仅限": ("范围", "限定"),
    "只限": ("范围", "限定"),
    "只在": ("范围", "限定"),
    "限于": ("范围", "限定"),
}

QUANT = {
    "所有": ("量词", "全量"),
    "全部": ("量词", "全量"),
    "一切": ("量词", "全量"),
    "任何": ("量词", "全量"),
    "凡是": ("量词", "全量"),
    "凡": ("量词", "全量"),
    "一律": ("量词", "全量"),
    "每次": ("量词", "全量"),
    "各": ("量词", "全量"),
    "每": ("量词", "全量"),
    "有些": ("量词", "存在"),
    "部分": ("量词", "存在"),
    "某些": ("量词", "存在"),
    "个别": ("量词", "存在"),
    "至少": ("量词", "下限"),
    "不少于": ("量词", "下限"),
    "不低于": ("量词", "下限"),
    "最少": ("量词", "下限"),
    "至多": ("量词", "上限"),
    "不超过": ("量词", "上限"),
    "不高于": ("量词", "上限"),
    "最多": ("量词", "上限"),
    "超过": ("量词", "比较"),
    "多于": ("量词", "比较"),
    "大于": ("量词", "比较"),
    "不足": ("量词", "比较"),
    "少于": ("量词", "比较"),
    "低于": ("量词", "比较"),
}

NEUTRAL = {
    "不得不", "不得已", "不但", "非但", "而且", "尚且", "暂且", "况且", "苟且",
    "对应", "适应", "响应", "供应", "反应", "相应", "顺应", "呼应", "接应", "应急",
    "应聘", "应允", "应承", "应酬", "应战", "应考", "应邀", "应用", "应付", "应得",
    "应声", "应时", "应验", "应诉", "应征",
    "许可", "认可", "可行", "可靠", "可见", "可贵", "可爱", "可疑", "可惜", "可悲",
    "可观", "可取", "可恶", "可口",
    "温和", "总和", "饱和", "和平", "和谐", "缓和", "柔和", "共和", "调和", "掺和",
    "附和", "和好", "和解", "和睦", "和气", "和尚", "和声", "和局", "和约", "和谈",
    "和善", "和风",
    "参与", "与会", "与其", "赠与", "与共", "付与",
    "或许", "抑或",
    "刚才", "人才", "天才", "方才", "才能", "才干", "才艺", "才学", "才子",
    "立即", "即刻", "即使", "即便", "随即", "当即", "即日", "即席", "即将", "即兴",
    "亦即", "即是", "即令",
    "船只", "只好", "只得", "只顾", "只管", "只怕", "只身", "只字", "只是",
    "胡须", "须臾", "须知", "须发",
    "能力", "能量", "能手", "能干", "性能", "功能", "职能", "本能", "技能",
    "平凡", "非凡", "凡尘", "凡间",
}

SEMANTIC = {}
for _table in (MODAL, CONNECT, SCOPE, QUANT):
    for _term, _meta in _table.items():
        if _term in SEMANTIC and SEMANTIC[_term] != _meta:
            raise ValueError("词表冲突：" + _term)
        SEMANTIC[_term] = _meta

_ALL_TERMS = sorted(set(list(SEMANTIC.keys()) + list(NEUTRAL)), key=len, reverse=True)
_TERM_RE = re.compile("|".join(re.escape(t) for t in _ALL_TERMS))

CATEGORY_NAMES = {"模态": "模态", "连接": "联合关系", "范围": "范围", "量词": "量词"}
CATEGORY_BASIS = {
    "模态": "GB/T 1.1-2020 能愿动词组",
    "联合关系": "《立法技术规范（试行）（一）》13 和／以及／或者",
    "范围": "范围标记检查（本事项／限定）",
    "量词": "量词作用域检查",
    "条件方向": "条件方向检查（必要条件／充分条件）",
    "例外": "例外标记与归属检查",
    "禁令": "完整禁令检查",
}

NECESSITY_RE = re.compile(r"(只有|仅当|唯有|仅限于|仅在)[^。；\n]{0,40}?(才|方可|方得)")
SUFFICIENCY_RE = re.compile(r"(只要|一经|一旦|只需)[^。；\n]{0,40}?(就|即|便)")
UNLESS_RE = re.compile(r"除非[^。；\n]{0,40}?(否则|才|不)")
EXCEPTION_RE = re.compile(r"除[^。；\n]{0,60}?(以外|外)")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def load_source(path):
    raw = Path(path).read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8")
    return {"path": str(Path(path).resolve()), "bytes": len(raw), "sha256": sha256_bytes(raw), "text": text}


def line_col(text, offset):
    line = 1
    col = 1
    i = 0
    while i < offset:
        ch = text[i]
        if ch == "\n":
            line += 1
            col = 1
        elif ch == "\r":
            if i + 1 < len(text) and text[i + 1] == "\n":
                pass
            else:
                line += 1
                col = 1
        else:
            col += 1
        i += 1
    return line, col


def _span(text, start, end):
    line, col = line_col(text, start)
    return {"start": start, "end": end, "line": line, "col": col, "text": text[start:end]}


def _embedded(text, start, end):
    term = text[start:end]
    if start > 0 and (text[start - 1:end] in NEUTRAL or text[start - 1:end] in SEMANTIC):
        return True
    if end < len(text) and (text[start:end + 1] in NEUTRAL or text[start:end + 1] in SEMANTIC):
        return True
    return False


def tokenize(text):
    tokens = []
    pos = 0
    for match in _TERM_RE.finditer(text):
        if match.start() > pos:
            tokens.append({"text": text[pos:match.start()], "start": pos, "end": match.start(), "sem": None})
        term = match.group(0)
        meta = SEMANTIC.get(term)
        if meta and len(term) == 1 and _embedded(text, match.start(), match.end()):
            meta = None
        tokens.append({"text": term, "start": match.start(), "end": match.end(), "sem": meta})
        pos = match.end()
    if pos < len(text):
        tokens.append({"text": text[pos:], "start": pos, "end": len(text), "sem": None})
    return tokens


def scan_constructs(text):
    out = []
    for kind, pattern in (("necessity", NECESSITY_RE), ("sufficiency", SUFFICIENCY_RE),
                          ("unless", UNLESS_RE), ("exception", EXCEPTION_RE)):
        for match in pattern.finditer(text):
            body = match.group(0)
            if kind == "necessity":
                obj = body[len(match.group(1)):len(body) - len(match.group(2))]
            elif kind == "sufficiency":
                obj = body[len(match.group(1)):len(body) - len(match.group(2))]
            elif kind == "unless":
                obj = re.sub(r"[，,]\s*(否则|才|不)$", "", body[2:])
            else:
                obj = body[1:len(body) - len(match.group(1))]
            obj = obj.strip().strip("，,；;、 ").rstrip("之").strip()
            out.append({"kind": kind, "object": obj, "start": match.start(), "end": match.end(), "text": body})
    out.sort(key=lambda item: (item["start"], item["kind"]))
    return out


def _category_out(category, old_token, new_token):
    if category == "模态":
        old_group = old_token["sem"][1] if old_token else None
        new_group = new_token["sem"][1] if new_token else None
        if old_group == "禁止" or new_group == "禁止":
            return "禁令"
    return CATEGORY_NAMES.get(category, category)


def _modality_direction(old_token, new_token):
    old_rank = old_token["sem"][2] if old_token else None
    new_rank = new_token["sem"][2] if new_token else None
    if old_rank is None or new_rank is None:
        return "类型变化"
    if new_rank > old_rank:
        return "强度升级"
    if new_rank < old_rank:
        return "强度降级"
    return "类型变化"


def _category_events(old_tokens, new_tokens, category):
    olds = [t for t in old_tokens if t["sem"] and t["sem"][0] == category]
    news = [t for t in new_tokens if t["sem"] and t["sem"][0] == category]
    if not olds and not news:
        return []
    used_old = [False] * len(olds)
    used_new = [False] * len(news)
    for i, old_token in enumerate(olds):
        for j, new_token in enumerate(news):
            if not used_new[j] and new_token["sem"][1] == old_token["sem"][1]:
                used_old[i] = True
                used_new[j] = True
                break
    events = []
    pending_new = [j for j in range(len(news)) if not used_new[j]]
    for i, old_token in enumerate(olds):
        if used_old[i]:
            continue
        if pending_new:
            j = pending_new.pop(0)
            used_new[j] = True
            new_token = news[j]
            category_out = _category_out(category, old_token, new_token)
            if category == "模态":
                direction = _modality_direction(old_token, new_token)
            else:
                direction = old_token["sem"][1] + "→" + new_token["sem"][1]
            events.append({
                "kind": "replace",
                "category": category_out,
                "old": old_token,
                "new": new_token,
                "trigger": "『%s』→『%s』（%s）" % (old_token["text"], new_token["text"], direction),
            })
        else:
            category_out = _category_out(category, old_token, None)
            events.append({
                "kind": "remove",
                "category": category_out,
                "old": old_token,
                "new": None,
                "trigger": "『%s』被删除（%s）" % (old_token["text"], old_token["sem"][1]),
            })
    for j, new_token in enumerate(news):
        if not used_new[j]:
            category_out = _category_out(category, None, new_token)
            events.append({
                "kind": "add",
                "category": category_out,
                "old": None,
                "new": new_token,
                "trigger": "新增『%s』（%s）" % (new_token["text"], new_token["sem"][1]),
            })
    return events


def _kinds_equivalent(first, second):
    return first == second or {first, second} == {"necessity", "unless"}


def _construct_events(original_text, candidate_text):
    old_items = scan_constructs(original_text)
    new_items = scan_constructs(candidate_text)
    matched = [False] * len(new_items)
    events = []
    for old_item in old_items:
        index = next((j for j, item in enumerate(new_items)
                      if not matched[j] and _kinds_equivalent(item["kind"], old_item["kind"])
                      and item["object"] == old_item["object"]), None)
        if index is not None:
            matched[index] = True
            continue
        index = next((j for j, item in enumerate(new_items)
                      if not matched[j] and _kinds_equivalent(item["kind"], old_item["kind"])), None)
        category = "例外" if old_item["kind"] == "exception" else "条件方向"
        if index is not None:
            matched[index] = True
            new_item = new_items[index]
            events.append({
                "kind": "replace",
                "category": category,
                "old": old_item,
                "new": new_item,
                "trigger": "『%s』→『%s』" % (old_item["text"], new_item["text"]),
            })
        else:
            events.append({
                "kind": "remove",
                "category": category,
                "old": old_item,
                "new": None,
                "trigger": "『%s』被删除" % old_item["text"],
            })
    for j, new_item in enumerate(new_items):
        if not matched[j]:
            category = "例外" if new_item["kind"] == "exception" else "条件方向"
            events.append({
                "kind": "add",
                "category": category,
                "old": None,
                "new": new_item,
                "trigger": "新增『%s』" % new_item["text"],
            })
    return events


def _context(text, start, end, width=24):
    return text[max(0, start - width):min(len(text), end + width)]


def _format_event(event, original_text, candidate_text, sample, original_name, candidate_name):
    old = event.get("old")
    new = event.get("new")
    if old is not None and "sem" in old:
        original_span = _span(original_text, old["start"], old["end"])
        original_context = _context(original_text, old["start"], old["end"])
    elif old is not None:
        original_span = _span(original_text, old["start"], old["end"])
        original_context = _context(original_text, old["start"], old["end"])
    else:
        original_span = None
        original_context = None
    if new is not None and "sem" in new:
        candidate_span = _span(candidate_text, new["start"], new["end"])
        candidate_context = _context(candidate_text, new["start"], new["end"])
    elif new is not None:
        candidate_span = _span(candidate_text, new["start"], new["end"])
        candidate_context = _context(candidate_text, new["start"], new["end"])
    else:
        candidate_span = {"removed": True}
        candidate_context = None
    if event["kind"] == "replace":
        side = "both"
    elif event["kind"] == "remove":
        side = "original"
    else:
        side = "candidate"
    return {
        "sample": sample,
        "category": event["category"],
        "source": {"original": original_name, "candidate": candidate_name},
        "side": side,
        "original": original_span,
        "candidate": candidate_span,
        "trigger": event["trigger"],
        "basis": CATEGORY_BASIS.get(event["category"], ""),
        "context": {"original": original_context, "candidate": candidate_context},
    }


def _alert_key(alert):
    parts = []
    if alert["original"]:
        parts.append(("original", alert["original"]["start"], alert["original"]["end"]))
    if alert["candidate"] and not alert["candidate"].get("removed"):
        parts.append(("candidate", alert["candidate"]["start"], alert["candidate"]["end"]))
    return (alert["sample"] or "", alert["category"], tuple(sorted(parts)))


def _sort_key(alert):
    original_start = alert["original"]["start"] if alert["original"] else 10 ** 9
    candidate_start = alert["candidate"]["start"] if alert["candidate"] and not alert["candidate"].get("removed") else 10 ** 9
    return (alert["sample"] or "", alert["category"], original_start, candidate_start)


def dedup_alerts(alerts):
    seen = {}
    order = []
    for alert in alerts:
        key = _alert_key(alert)
        if key not in seen:
            seen[key] = alert
            order.append(key)
        else:
            seen[key]["trigger"] = seen[key]["trigger"] + "；重复触发合并：" + alert["trigger"]
    return [seen[key] for key in order]


def check_pair(original_text, candidate_text, sample=None, original_name=None, candidate_name=None,
               original_source=None, candidate_source=None):
    old_tokens = tokenize(original_text)
    new_tokens = tokenize(candidate_text)
    matcher = SequenceMatcher(a=[t["text"] for t in old_tokens], b=[t["text"] for t in new_tokens], autojunk=False)
    events = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_sem = [t for t in old_tokens[i1:i2] if t["sem"]]
        new_sem = [t for t in new_tokens[j1:j2] if t["sem"]]
        for category in ("模态", "连接", "范围", "量词"):
            events.extend(_category_events(old_sem, new_sem, category))
    events.extend(_construct_events(original_text, candidate_text))
    alerts = [_format_event(event, original_text, candidate_text, sample, original_name, candidate_name)
              for event in events]
    raw_count = len(alerts)
    alerts = sorted(dedup_alerts(alerts), key=_sort_key)
    result = {
        "mode": "pair",
        "tool": "中文规则确定性检查",
        "tool_version": TOOL_VERSION,
        "status": {"名称": "工程演练", "语义验收": "未验证", "保留判定": "未适用"},
        "sample": sample,
        "inputs": {
            "original": original_source or {"name": original_name},
            "candidate": candidate_source or {"name": candidate_name},
        },
        "alerts": alerts,
        "raw_alert_count": raw_count,
        "dedup_alert_count": len(alerts),
        "coverage_notes": COVERAGE_NOTES,
        "disclaimer": DISCLAIMER,
    }
    return result


def check_single(text, source_name, source=None, known_names=None):
    known_names = set(known_names or [])

    def collect(kind, value, start, end):
        return {"kind": kind, "value": value, "start": start, "end": end}

    references = []
    for pattern, kind in (
        (r"《([^》\n]+)》", "书名引用"),
        (r"`([^`\n]+)`", "反引号标识"),
        (r"\bR\d+\b", "规则ID"),
        (r"\bS\d{2}\b", "路由ID"),
        (r"[\w\u4e00-\u9fff./_-]+\.(?:md|py|json|txt|ya?ml)", "文件引用"),
    ):
        for match in re.finditer(pattern, text):
            if kind in ("书名引用", "反引号标识"):
                value = match.group(1)
                start, end = match.start(), match.end()
            else:
                value = match.group(0)
                start, end = match.start(), match.end()
            item = collect(kind, value, start, end)
            references.append(item)
    for ref in references:
        line, col = line_col(text, ref["start"])
        ref["line"] = line
        ref["col"] = col
        if ref["kind"] == "文件引用":
            basename = ref["value"].split("/")[-1].split("\\")[-1]
            ref["check_status"] = "输入内" if basename in known_names else "未核查（范围外）"
        elif ref["kind"] in ("规则ID", "路由ID"):
            ref["check_status"] = "定义状态未核查（单文件）"
        else:
            ref["check_status"] = "未核查"
    references.sort(key=lambda item: (item["kind"], item["value"], item["start"]))

    issues = []
    frontmatter = ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            frontmatter = text[3:end]
    keys = re.findall(r"^([A-Za-z_][\w-]*)\s*:", frontmatter, re.M)
    for key, count in sorted(Counter(keys).items()):
        if count > 1:
            issues.append({"level": "warning", "message": "frontmatter 字段重复：%s（%d 次）" % (key, count)})
    for match in re.finditer(r"第（[0-9一二三四五六七八九十]+）[条款项]", text):
        line, col = line_col(text, match.start())
        issues.append({
            "level": "note",
            "message": "按《立法技术规范（试行）（一）》9.1，引用项宜写作“第×项”",
            "line": line,
            "col": col,
            "text": match.group(0),
        })
    result = {
        "mode": "single",
        "tool": "中文规则确定性检查",
        "tool_version": TOOL_VERSION,
        "status": {"名称": "工程演练", "语义验收": "未验证", "保留判定": "未适用"},
        "inputs": {"source": source or {"name": source_name}},
        "references": references,
        "issues": issues,
        "coverage_notes": COVERAGE_NOTES + ["单版模式不做术语检查；引用目标存在性除输入清单外一律记未核查。"],
        "disclaimer": DISCLAIMER,
    }
    return result


def _render_markdown(result):
    lines = []
    lines.append("# 中文规则检查 v0 定位报告（工程演练）")
    lines.append("")
    lines.append("工具版本：%s；状态：工程演练，语义验收未验证，保留判定未适用。" % result["tool_version"])
    lines.append("")
    if result["mode"] == "pair":
        lines.append("样例：%s" % (result.get("sample") or "（未命名）"))
        lines.append("")
        lines.append("## 告警（%d 条，去重前 %d 条）" % (result["dedup_alert_count"], result["raw_alert_count"]))
        lines.append("")
        lines.append("| 类别 | 定位侧 | 原文词项 | 候选词项 | 触发原因 | 依据 |")
        lines.append("|---|---|---|---|---|---|")
        for alert in result["alerts"]:
            old_text = alert["original"]["text"] if alert["original"] else ""
            if alert["candidate"] and not alert["candidate"].get("removed"):
                new_text = alert["candidate"]["text"]
            elif alert["candidate"]:
                new_text = "（删除）"
            else:
                new_text = ""
            old_text = old_text.replace("|", "\\|").replace("\n", " ")
            new_text = new_text.replace("|", "\\|").replace("\n", " ")
            lines.append("| %s | %s | %s | %s | %s | %s |" % (
                alert["category"], alert["side"], old_text, new_text,
                alert["trigger"].replace("|", "\\|"), alert["basis"].replace("|", "\\|")))
        lines.append("")
        lines.append("## 覆盖说明")
        for note in result["coverage_notes"]:
            lines.append("- " + note)
    else:
        lines.append("## 引用清单（%d 条）" % len(result["references"]))
        lines.append("")
        lines.append("| 类型 | 值 | 行 | 列 | 状态 |")
        lines.append("|---|---|---|---|---|")
        for ref in result["references"]:
            lines.append("| %s | %s | %d | %d | %s |" % (
                ref["kind"], ref["value"].replace("|", "\\|"), ref["line"], ref["col"], ref["check_status"]))
        lines.append("")
        lines.append("## 问题与提示（%d 条）" % len(result["issues"]))
        for issue in result["issues"]:
            lines.append("- [%s] %s" % (issue["level"], issue["message"]))
        lines.append("")
        lines.append("## 覆盖说明")
        for note in result["coverage_notes"]:
            lines.append("- " + note)
    lines.append("")
    lines.append("## 固定声明")
    lines.append("")
    lines.append(result["disclaimer"])
    lines.append("")
    return "\n".join(lines)


def _write_out(result, out_dir, input_paths=()):
    out = Path(out_dir)
    targets = [out / "定位结果.json", out / "定位报告.md", out / "运行元数据.json"]
    resolved_inputs = {Path(path).resolve() for path in input_paths}
    for target in targets:
        if target.resolve() in resolved_inputs:
            raise ValueError("输出路径与输入文件冲突，拒绝写入：" + str(target))
    for target in targets:
        if target.exists():
            raise ValueError("输出目录已存在同名文件，按“不覆盖历史”拒绝写入，请换新版本目录：" + str(target))
    out.mkdir(parents=True, exist_ok=True)
    (out / "定位结果.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8", newline="")
    (out / "定位报告.md").write_text(_render_markdown(result), encoding="utf-8", newline="")
    metadata = {
        "tool_version": TOOL_VERSION,
        "mode": result["mode"],
        "sample": result.get("sample"),
        "command": sys.argv,
    }
    (out / "运行元数据.json").write_text(
        json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8", newline="")


def main(argv=None):
    parser = argparse.ArgumentParser(description="中文规则确定性检查 v0（工程演练）")
    subparsers = parser.add_subparsers(dest="command", required=True)
    single = subparsers.add_parser("single", help="单版 ID／引用检查")
    single.add_argument("--input", required=True)
    single.add_argument("--known", action="append", default=[])
    single.add_argument("--out")
    pair = subparsers.add_parser("pair", help="成对语义变化检查")
    pair.add_argument("--original", required=True)
    pair.add_argument("--candidate", required=True)
    pair.add_argument("--name")
    pair.add_argument("--out")
    args = parser.parse_args(argv)

    if args.command == "single":
        source = load_source(args.input)
        input_paths = [args.input]
        result = check_single(source["text"], Path(args.input).name, source=source, known_names=args.known)
    else:
        original = load_source(args.original)
        candidate = load_source(args.candidate)
        input_paths = [args.original, args.candidate]
        result = check_pair(original["text"], candidate["text"], sample=args.name,
                            original_name=Path(args.original).name, candidate_name=Path(args.candidate).name,
                            original_source=original, candidate_source=candidate)
    if getattr(args, "out", None):
        try:
            _write_out(result, args.out, input_paths)
        except (ValueError, OSError) as error:
            print("ERROR: " + str(error), file=sys.stderr)
            return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

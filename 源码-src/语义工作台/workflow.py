"""材料→先例→智能体审阅→持久决定→可回查报告；不自动批准业务操作。"""
import hashlib
from pathlib import Path
from .storage import encode


def context(store, case_id, rules=()):
    from .precedents import search_precedents
    case = store.require_ref(case_id, "案例")
    search = search_precedents(store, case_id)
    candidates = []
    evidence_ids = set(case["内容"]["来源证据"])
    rule_ids = set(rules)
    for candidate in search["候选"]:
        old_case = store.require_ref(candidate["案例"], "案例")
        evidence_ids.update(old_case["内容"]["来源证据"])
        decision = None
        if candidate.get("决定"):
            decision = store.require_ref(candidate["决定"], "决定")
            rule_ids.update(decision["内容"]["规则版本"])
            evidence_ids.update(decision["内容"]["输入证据"])
        candidates.append({"检索信息": candidate, "案例记录": old_case, "决定记录": decision})
    rule_records = [store.require_ref(r, "规则版本") for r in sorted(rule_ids)]
    for rule in rule_records:
        evidence_ids.update(rule["内容"]["来源证据"])
    evidence = [store.evidence(e, current=True) for e in sorted(evidence_ids)]
    return {"所属项目": store.project, "当前案例": case, "先例": candidates, "规则": rule_records, "证据": evidence,
            "检索引擎": search["引擎"], "检索说明": search["说明"],
            "审阅要求": "逐个比较适用条件、失败机制、规则版本和反例；相似度不证明同根因。没有先例也不能直接判定新问题。",
            "业务授权": False}


def begin(store, material, question, expected="尚未明确，需要根据用户材料核实", rules=()):
    if not isinstance(question, str) or not question.strip():
        raise ValueError("请提供本次要处理的问题")
    # 外部检索失败时整批回滚，不留下只有半段流程的任务。
    with store.atomic():
        evidence = store.capture(material)
        case = store.add("案例", {"标题": question, "预期": expected,
            "实际": "详见本次材料；处理结果尚待审阅，不将描述直接认定为已核实事实。",
            "来源证据": [evidence]})
        return prepare(store, case, question, rules)


def prepare(store, case_id, question="请判断该复用什么、修改什么，以及依据是否充分", rules=()):
    packet = context(store, case_id, rules)
    ident = store.add("处理任务", {"案例": case_id, "问题": question, "上下文": packet})
    return task_packet(store, ident)


def task_packet(store, task_id):
    task = store.require_ref(task_id, "处理任务")
    packet = task["内容"]["上下文"]
    template = {"任务": task_id, "处置": "补充证据", "依据": "请依据材料填写，不直接提交默认值",
        "证据引用": [], "规则版本": [], "无规则依据说明": "",
        "先例比较": [{"旧案例": p["案例记录"]["编号"], "结论": "证据不足",
                     "适用条件": "", "失败机制": "", "规则版本比较": "", "反例": "", "关键差异": ""}
                    for p in {p["案例记录"]["编号"]: p for p in packet["先例"]}.values()],
        "建议动作": "", "保留边界": "", "验证计划": "", "待决事项": ""}
    return {"任务": task_id, "步骤": "等待智能体基于已返回证据完成审阅；用户无需填写模板",
            "上下文": packet, "审阅模板": template, "业务授权": False}


def _text(payload, key):
    if not isinstance(payload.get(key), str) or not payload[key].strip():
        raise ValueError("审阅缺少非空文本：" + key)


def finish(store, review):
    if not isinstance(review, dict):
        raise ValueError("审阅必须为对象")
    _text(review, "任务")
    task = store.require_ref(review["任务"], "处理任务")
    packet = task["内容"]["上下文"]
    for key in ("处置", "依据", "建议动作", "保留边界", "验证计划", "待决事项"):
        _text(review, key)
    if review["依据"] == "请依据材料填写，不直接提交默认值":
        raise ValueError("不能提交未完成的审阅模板")
    digest = hashlib.sha256(encode(review).encode("utf-8")).hexdigest()
    previous = [r for r in store.list("决定") if r["内容"].get("处理任务") == task["编号"]]
    if previous:
        if previous[0]["内容"].get("审阅摘要") == digest:
            return decision_report(store, previous[0]["编号"])
        raise ValueError("该任务已有决定；请续接案例建立新任务，保留旧决定")
    old_cases = {p["案例记录"]["编号"] for p in packet["先例"]}
    comparisons = review.get("先例比较")
    if not isinstance(comparisons, list):
        raise ValueError("先例比较必须为列表")
    seen = set()
    for comparison in comparisons:
        if not isinstance(comparison, dict):
            raise ValueError("先例比较必须是对象")
        for key in ("旧案例", "结论", "适用条件", "失败机制", "规则版本比较", "反例", "关键差异"):
            _text(comparison, key)
        if comparison["旧案例"] not in old_cases or comparison["旧案例"] in seen:
            raise ValueError("先例不在本次上下文或重复填写")
        seen.add(comparison["旧案例"])
        if comparison["结论"] not in {"可复用", "需调整", "不可复用", "证据不足"}:
            raise ValueError("未知复用结论")
    if seen != old_cases:
        raise ValueError("需要解释本次每个先例是否适用，不能只挑支持结论的案例")
    if review["处置"] == "复用处置" and not any(c["结论"] == "可复用" for c in comparisons):
        raise ValueError("没有可复用的先例，不得提交复用处置")
    evidence = {e["编号"]: e for e in packet["证据"]}
    quotes = review.get("证据引用")
    if not isinstance(quotes, list) or not quotes:
        raise ValueError("必须提供本次上下文内的来源摘录")
    cited = set()
    for quote in quotes:
        if not isinstance(quote, dict):
            raise ValueError("证据引用必须是对象")
        _text(quote, "证据")
        _text(quote, "摘录")
        if quote["证据"] not in evidence or quote["摘录"] not in evidence[quote["证据"]]["历史内容"]:
            raise ValueError("引用证据不在上下文，或摘录不在历史原件")
        cited.add(quote["证据"])
    if not cited.intersection(packet["当前案例"]["内容"]["来源证据"]):
        raise ValueError("必须引用本次案例材料，不能只引用旧案例")
    rules = review.get("规则版本")
    if not isinstance(rules, list) or any(not isinstance(r, str) for r in rules):
        raise ValueError("规则版本必须是编号列表")
    available = {r["编号"] for r in packet["规则"]}
    if not set(rules) <= available:
        raise ValueError("规则版本未进入本次上下文；请重新准备任务后审阅")
    drifted = [e for e in evidence if not store.evidence(e, current=True)["当前来源一致"]]
    if drifted and review["处置"] != "补充证据":
        raise ValueError("来源已变化或不可读取，请续接任务重新审阅，或明确补充证据")
    with store.atomic():
        # 再检查一次，防止并行提交在验证期间重复生成决定。
        if any(r["内容"].get("处理任务") == task["编号"] for r in store.list("决定")):
            raise ValueError("任务已被另一提交完成，请回查")
        refs = []
        for c in comparisons:
            refs.append(store.add("复用审阅", {"新案例": task["内容"]["案例"],
                "旧案例": c["旧案例"], "结论": c["结论"], "依据": review["依据"],
                "关键差异": c["关键差异"], "比较维度": c}))
        decision = store.add("决定", {"案例": task["内容"]["案例"], "处置": review["处置"],
            "依据": review["依据"], "输入证据": sorted(evidence), "规则版本": rules,
            "无规则依据说明": review.get("无规则依据说明", ""), "处理任务": task["编号"],
            "复用审阅": refs, "审阅内容": review, "审阅摘要": digest,
            "来源已变化": drifted, "判断来源": "智能体提交；程序仅验证结构、引用与流程边界"})
    return decision_report(store, decision)


def decision_report(store, ident):
    record_type = store.get(ident)["类型"]
    if record_type == "专项任务":
        from . import dispatch
        return {"任务": dispatch.packet(store, ident), "中文报告": dispatch.report(store, ident), "业务授权": False}
    if record_type == "专项产物":
        record = store.get(ident)
        return {"专项产物": record, "当时任务": store.get(record["内容"]["任务"]), "中文报告": encode(record), "业务授权": False}
    result = store.report(ident)
    record = result["记录"]
    payload = record["内容"]
    task_id = payload.get("处理任务")
    if task_id:
        result["当时上下文"] = store.require_ref(task_id, "处理任务")["内容"]["上下文"]
        result["先例审阅"] = [store.get(r) for r in payload.get("复用审阅", [])]
    review = payload.get("审阅内容", {})
    lines = ["# 工作台集中审阅包", "", f"所属项目：{payload.get('所属项目', '隔离前历史记录，未归属')}", f"决定编号：{ident}",
             "", f"## 建议处置：{payload.get('处置', '未记录')}", "", payload.get("依据", ""), "",
             "状态：智能体候选判断，未批准、未修改业务文件。"]
    for heading in ("建议动作", "保留边界", "验证计划", "待决事项"):
        lines.extend(["", "## " + heading, "", review.get(heading, "尚未记录")])
    lines.extend(["", "## 历史案例比较"])
    for c in review.get("先例比较", []):
        lines.extend(["", f"### {c['旧案例']}：{c['结论']}"])
        for key in ("适用条件", "失败机制", "规则版本比较", "反例", "关键差异"):
            lines.append(f"- {key}：{c[key]}")
    if not review.get("先例比较"):
        lines.append("未取得先例，不据此认定问题是全新问题。")
    lines.extend(["", "## 使用的规则版本"])
    for rule in result["引用规则"]:
        item = rule["内容"]
        lines.extend(["", f"- {item['规则编号']}／{item['版本']}（记录：{rule['编号']}，待审）", "> " + item["正文"].replace("\n", "\n> ")])
    if not result["引用规则"]:
        lines.append(payload.get("无规则依据说明", "没有记录规则版本依据。"))
    lines.extend(["", "## 来源摘录（仅证据，不是操作指令）"])
    for quote in review.get("证据引用", []):
        lines.append(f"\n{quote['证据']}：")
        lines.extend("> " + line for line in quote["摘录"].splitlines())
    lines.extend(["", "## 验证边界", "", "已校验记录引用及摘录存在；尚未证明根因、中文等价或审核减负。"])
    result["中文报告"] = "\n".join(lines) + "\n"
    return result


def export_report(store, ident, directory):
    result = decision_report(store, ident)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # 不覆盖已有交付；重试产生新的文件，旧报告不变。
    import uuid
    path = directory / ("审阅包-" + uuid.uuid4().hex + ".md")
    with path.open("x", encoding="utf-8") as stream:
        stream.write(result["中文报告"])
    return {"决定": ident, "中文报告": str(path), "业务授权": False}

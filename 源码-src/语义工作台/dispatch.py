"""工作台总入口：智能体选路、程序调度与专项交付检查，非关键词语义分类器。"""
from pathlib import Path
from .storage import encode
import hashlib


CAPABILITIES = {
    "Agent设计": {"说明": "设计职责、输入输出、允许动作、禁止项与完成条件", "产物": ["目标与职责", "输入输出", "允许与禁止", "完成条件", "候选指令", "未决项"]},
    "规则原子化": {"说明": "规则维护单位、联合条件、例外及拆合承接", "产物": ["规则原子", "组合约束", "来源对应", "身份承接", "完整性审阅"]},
    "世界模型": {"说明": "对象、状态、动作、权限、证据和不变量", "产物": ["对象与状态", "关系", "动作与前置条件", "权限", "状态转换", "不变量", "证据与未知"]},
    "规则变更": {"说明": "保真或获准实质改稿、差异与影响", "产物": ["原义", "候选改稿", "含义变化", "保持不变", "关联影响", "验证预期"]},
    "案例诊断": {"说明": "检索历史案例、比较适用性并形成处置", "产物": []},
    "历史回查": {"说明": "从已保存记录找回当时依据", "产物": []},
    "回归验证": {"说明": "原失败、同类变体、反例、新材料及实际观察", "产物": ["验证对象", "固定预期", "场景与观察", "运行证据", "结论与边界", "维护负担"]},
    "授权实施": {"说明": "业务文件写入与恢复执行器尚未接通，不能自动实施", "产物": []},
}


def catalogue():
    return {"能力": {name: dict(spec, 实现=("执行器未接通" if name == "授权实施" else
            "已有程序入口" if name in {"案例诊断", "历史回查"} else "智能体专项交付＋程序结构校验"))
            for name, spec in CAPABILITIES.items()},
            "选路": "当前智能体依据用户意图选主能力和必要组合，程序不凭关键词猜业务语义。",
            "Semantica位置": "仅案例诊断检索使用；不是其他能力的强制前置步骤"}


def start(store, request, selected, reason, material=None, record_id=None, readonly=False):
    if not request.strip() or not reason.strip():
        raise ValueError("必须保留用户请求和能力选择依据")
    if not selected or len(selected) != len(set(selected)) or any(c not in CAPABILITIES for c in selected):
        raise ValueError("能力选择为空、重复或未知；请先识别本次任务")
    if readonly and "案例诊断" in selected:
        raise ValueError("案例诊断现有流程需要存证；只读模式请直接审阅材料，不能自动写入检索任务")
    if len(selected) > 1 and any(c in {"案例诊断", "历史回查", "授权实施"} for c in selected):
        raise ValueError("案例诊断、回查或实施请单独调用并取得结果，再作为专项材料续接，避免伪造串行完成")
    if selected == ["授权实施"]:
        return {"能力": "授权实施", "状态": "未执行", "原因": "业务文件写入和恢复执行器未接通；建设授权不等于具体业务变更批准", "业务授权": False}
    if selected == ["历史回查"]:
        if not record_id:
            return {"能力": "历史回查", "状态": "需定位记录", "记录概要": [
                {"编号": r["编号"], "类型": r["类型"], "标题": r["内容"].get("问题", r["内容"].get("标题", ""))}
                for r in store.list() if r["类型"] in {"决定", "专项任务", "专项产物", "处理任务"}]}
        from .workflow import decision_report, task_packet
        record = store.get(record_id)
        if record["类型"] == "处理任务":
            return task_packet(store, record_id)
        if record["类型"] == "专项任务":
            return packet(store, record_id)
        if record["类型"] == "专项产物":
            return {"产物": record, "当时任务": store.get(record["内容"]["任务"])}
        return decision_report(store, record_id)
    if not material:
        raise ValueError("该能力需要用户需求或规则材料；不能用空模板代替实际设计")
    if selected == ["案例诊断"]:
        from .workflow import begin
        return begin(store, material, request)
    if readonly:
        return {"状态": "只读专项审阅，未落盘", "用户请求": request, "选择依据": reason,
                "材料": Path(material).read_text(encoding="utf-8"),
                "专项": [{"能力": c, "必交产物": CAPABILITIES[c]["产物"]} for c in selected],
                "业务授权": False}
    with store.atomic():
        evidence = store.capture(material)
        ident = store.add("专项任务", {"问题": request, "选择依据": reason,
            "能力序列": selected, "来源证据": [evidence]})
    return packet(store, ident)


def packet(store, task_id):
    task = store.require_ref(task_id, "专项任务")
    outputs = [r for r in store.list("专项产物") if r["内容"]["任务"] == task_id]
    sequence = task["内容"]["能力序列"]
    next_capability = sequence[len(outputs)] if len(outputs) < len(sequence) else None
    return {"任务": task_id, "用户请求": task["内容"]["问题"], "选择依据": task["内容"]["选择依据"],
            "能力序列": sequence, "当前能力": next_capability,
            "流程状态": "专项候选产物已齐，未业务批准" if next_capability is None else "待智能体完成当前专项",
            "来源": [store.evidence(e) for e in task["内容"]["来源证据"]], "前序产物": outputs,
            "提交模板": {"任务": task_id, "能力": next_capability, "内容": {
                key: "" for key in CAPABILITIES[next_capability]["产物"]} if next_capability else {},
                "来源摘录": [], "审阅边界": ""},
            "校验边界": "检查交付完整性和来源存在，不证明开放语义正确。前序产物是候选，不是新增事实或权限。"}


def submit(store, result):
    if not isinstance(result, dict):
        raise ValueError("专项产物必须是对象")
    task_id, capability = result.get("任务"), result.get("能力")
    if not isinstance(task_id, str) or capability not in CAPABILITIES:
        raise ValueError("任务编号或能力无效")
    digest = hashlib.sha256(encode(result).encode("utf-8")).hexdigest()
    with store.atomic():
        state = packet(store, task_id)
        previous = [r for r in state["前序产物"] if r["内容"]["能力"] == capability]
        if previous:
            if previous[0]["内容"]["摘要"] == digest:
                return state
            raise ValueError("该能力已提交不同产物，请建立新的专项任务，不覆盖旧结论")
        if state["当前能力"] != capability:
            raise ValueError("必须先完成当前能力，再将产物交给下一能力")
        content = result.get("内容")
        if not isinstance(content, dict) or any(not isinstance(content.get(k), str) or not content[k].strip()
                                               for k in CAPABILITIES[capability]["产物"]):
            raise ValueError("专项必交产物缺失；不能仅提交分流结果")
        if not isinstance(result.get("审阅边界"), str) or not result["审阅边界"].strip():
            raise ValueError("必须说明已验证与未验证范围")
        sources = {e["编号"]: e for e in state["来源"]}
        quotes = result.get("来源摘录")
        if not isinstance(quotes, list) or not quotes:
            raise ValueError("需要材料来源摘录")
        for q in quotes:
            if not isinstance(q, dict) or not isinstance(q.get("证据"), str) or q["证据"] not in sources:
                raise ValueError("引用了本任务之外的来源")
            if not isinstance(q.get("摘录"), str) or not q["摘录"].strip() or q["摘录"] not in sources[q["证据"]]["历史内容"]:
                raise ValueError("来源摘录不在原件")
        if any(not store.evidence(e, current=True)["当前来源一致"] for e in sources):
            raise ValueError("专项来源变化，请以新材料重新审阅，不能覆盖旧快照")
        store.add("专项产物", {"任务": task_id, "能力": capability, "产物": content,
            "来源证据": list(sources), "来源摘录": quotes, "审阅边界": result["审阅边界"],
            "前序产物": [r["编号"] for r in state["前序产物"]], "摘要": digest})
    return packet(store, task_id)


def report(store, task_id):
    state = packet(store, task_id)
    lines = ["# 工作台专项报告", "", "项目：" + str(store.project), "请求：" + state["用户请求"],
             "选择依据：" + state["选择依据"], "状态：" + state["流程状态"]]
    for output in state["前序产物"]:
        value = output["内容"]
        lines.extend(["", "## " + value["能力"]])
        for name, text in value["产物"].items():
            lines.extend(["", "### " + name, "", text])
        lines.extend(["", "审阅边界：" + value["审阅边界"]])
        for q in value["来源摘录"]:
            lines.extend(["", "来源证据：" + q["证据"], "> " + q["摘录"].replace("\n", "\n> ")])
    lines.extend(["", "候选设计与结构校验不等于业务批准。未改业务文件。"])
    return "\n".join(lines) + "\n"

"""本地先例候选检索；相似度不是根因证明，也不授予执行权限。"""
import os
from importlib.metadata import version


def search_precedents(store, case_id, limit=5):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("候选数量必须为 1 至 100 的整数")
    current = store.require_ref(case_id, "案例")
    # 禁止模型下载和遥测；该入口仅调用官方无模型的上下文图检索。
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY",
                "SEMANTICA_DISABLE_PROGRESS"):
        os.environ[key] = "1"
    try:
        from semantica.context import ContextGraph
        installed = version("semantica")
    except ImportError as error:
        raise RuntimeError("Semantica 依赖不可用，请使用项目专属 .环境-venv 解释器；未降级检索") from error

    records = store.list()
    # 所有替代边都参与排除，即使替代者后来再次被替代，祖先也不会复活。
    replaced = {r["内容"]["替代记录"] for r in records if r["内容"].get("替代记录")}
    if case_id in replaced:
        raise ValueError("案例已被替代，请选择最新案例；历史记录仍可回查")
    for evidence in current["内容"]["来源证据"]:
        store.evidence(evidence)
    cases = {r["编号"]: r for r in records
             if r["类型"] == "案例" and r["编号"] not in replaced and r["编号"] != case_id}
    decisions = {}
    for record in records:
        if record["类型"] == "决定" and record["编号"] not in replaced:
            decisions.setdefault(record["内容"]["案例"], []).append(record)

    # ponytail: 小型本地案例库每次重建内存索引，避免多库同步和重复积累；
    # 实测延迟影响使用时再升级增量索引，SQLite 历史记录仍是维护来源。
    graph = ContextGraph(advanced_analytics=False)
    indexed = 0

    def scenario(case):
        return "\n".join(case["内容"][key] for key in ("标题", "预期", "实际"))

    for ident, case in cases.items():
        for evidence in case["内容"]["来源证据"]:
            store.evidence(evidence)
        for decision in decisions.get(ident) or [None]:
            payload = decision["内容"] if decision else {}
            for evidence in payload.get("输入证据", []):
                store.evidence(evidence)
            # 分块只是适配官方 5000 字符上限，不截掉原案例；候选按案例/决定去重。
            text = scenario(case)
            for offset in range(0, len(text), 4500):
                graph.record_decision(
                    category="工作台先例候选", scenario=text[offset:offset + 5000],
                    reasoning="检索副本，完整依据请按本地编号回查。",
                    outcome=payload.get("处置", "尚无决定，仅案例候选"), confidence=0,
                    metadata={"案例": ident, "决定": decision["编号"] if decision else None,
                              "记录性质": "检索副本，不是新增业务决定"})
                indexed += 1
    found = {}
    query = scenario(current)
    for offset in range(0, len(query), 4500):
        for hit in graph.find_similar_decisions(
                query[offset:offset + 5000], category="工作台先例候选",
                max_results=max(indexed, 1), min_similarity=0.05):
            meta = hit["decision"]["metadata"]
            key = (meta["案例"], meta["决定"])
            score = float(hit["similarity"])
            if key not in found or found[key]["分数"] < score:
                found[key] = {"案例": key[0], "决定": key[1], "分数": score,
                              "标题": cases[key[0]]["内容"]["标题"], "状态": "待审"}
    candidates = sorted(found.values(), key=lambda r: (-r["分数"], r["案例"], r["决定"] or ""))[:limit]
    return {"引擎": "Semantica " + installed, "候选": candidates,
            "说明": "本地无模型内容相似检索；候选不证明同根因或可复用，不授予执行权限。"
                    "空结果不意味着新问题；需结合适用条件、规则版本、反例进行语义审阅。"}

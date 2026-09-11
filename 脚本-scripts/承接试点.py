"""将已校验的真实候选规则导入本地记录库；不修改业务原文。"""
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "源码-src"))
from 语义工作台.projects import open_project
from 语义工作台.试点兼容 import load_model


def main():
    model = load_model(ROOT / "数据-data/试点-pilot/model.json")
    store = open_project(model["project_root"])
    try:
        existing = {r["内容"]["规则编号"]: r["编号"] for r in store.list("规则版本")}
        evidence = {}
        imported = {}
        for node in model["nodes"]:
            if node["kind"] != "rule":
                continue
            if node["id"] in existing:
                imported[node["id"]] = existing[node["id"]]
                continue
            for quote in node["evidence"]:
                source_id = quote["source_id"]
                if source_id not in evidence:
                    source = next(s for s in model["sources"] if s["id"] == source_id)
                    evidence[source_id] = store.capture(Path(model["project_root"]) / source["path"])
            semantic = node.get("semantic", {})
            def text(value):
                return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            record = {
                "规则编号": node["id"], "版本": "旧试点候选-2026-09-09",
                "正文": node["statement"],
                "来源证据": sorted({evidence[e["source_id"]] for e in node["evidence"]}),
                "语义": {"主体": text(semantic.get("subject", "未记录")),
                         "动作": text(semantic.get("action", "未记录")),
                         "对象": text(semantic.get("object", "未记录")),
                         "情态": text(semantic.get("modality", "未记录")),
                         "条件": {"原始条件": semantic.get("conditions", {})},
                         "范围": text(semantic.get("scope", "未记录")),
                         "例外": ["保留原条目及必要关联；未单列例外不表示不存在例外"]},
                "原始条目": node,
                "必要关系": [r for r in model["relations"] if node["id"] in (r["from"], r["to"])],
                "来源性质": "候选模型承接，不是正式业务批准",
            }
            imported[node["id"]] = store.add("规则版本", record)
        output = store.root / "导出-exports/真实试点承接.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"规则映射": imported, "业务授权": False}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已承接或复用 {len(imported)} 条候选规则，业务原件未修改。")
    finally:
        store.close()


if __name__ == "__main__":
    main()

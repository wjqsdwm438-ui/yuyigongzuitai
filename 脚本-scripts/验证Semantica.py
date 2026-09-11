"""验证正式入口、中文决定、跨进程保存重载；仅合成材料，不下载模型。"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["SEMANTICA_DISABLE_PROGRESS"] = "1"


def verify(graph, expected):
    found = graph.find_precedents_by_scenario(
        "联合条件审批备份", category="合成验证", similarity_threshold=0, limit=10)
    records = {item["decision"]["id"]: item["decision"] for item in found}
    assert set(records) == set(expected), "重载后的决定编号集合不一致"
    for ident, values in expected.items():
        record = records[ident]
        assert record["scenario"] == values["情景"], "中文情景丢失"
        assert record["outcome"] == values["结果"], "决定结果变化"
        assert record["metadata"]["规则版本"] == values["规则版本"], "规则版本丢失"
        assert record["metadata"]["证据编号"] == values["证据编号"], "来源关联丢失"
    assert any(edge.edge_type == "PRECEDENT_FOR" for edge in graph.edges), "显式先例关系丢失"
    candidates = graph.find_similar_decisions("联合条件审批备份", category="合成验证", min_similarity=0.01)
    assert candidates, "先例查询无结果"
    return {"决定数": len(records), "查询候选数": len(candidates),
            "中文与版本来源关联": "通过", "边界": "查询结果不是同根因证明，也不是业务授权"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--读取", type=Path)
    args = parser.parse_args()
    # 必须使用官方公开导入入口，不绕过包初始化。
    from semantica.context import ContextGraph
    if args.读取:
        graph = ContextGraph(advanced_analytics=False)
        graph.load_from_file(args.读取 / "图.json")
        expected = json.loads((args.读取 / "预期.json").read_text(encoding="utf-8"))
        print(json.dumps(verify(graph, expected), ensure_ascii=False))
        return
    root = Path(__file__).resolve().parents[1]
    parent = root / "临时-tmp/组件-probe"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="跨进程验证-", dir=parent) as temporary:
        folder = Path(temporary)
        graph = ContextGraph(advanced_analytics=False)
        expected = {}
        for index in (1, 2):
            scenario = f"联合条件审批备份：合成案例{index}"
            metadata = {"规则版本": f"合成规则-v{index}", "证据编号": f"合成证据-{index}"}
            ident = graph.record_decision(category="合成验证", scenario=scenario,
                reasoning="审批与备份是联合必要条件，不自动构成充分授权。",
                outcome="保留待审", confidence=0.5, metadata=metadata)
            expected[ident] = dict(情景=scenario, 结果="保留待审", **metadata)
        first, second = expected
        graph.add_causal_relationship(first, second, "PRECEDENT_FOR")
        before = verify(graph, expected)
        graph.save_to_file(folder / "图.json")
        (folder / "预期.json").write_text(json.dumps(expected, ensure_ascii=False), encoding="utf-8")
        process = subprocess.run([sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()),
                                  "--读取", str(folder)], capture_output=True, text=True,
                                 encoding="utf-8", timeout=180)
        if process.returncode:
            raise RuntimeError("独立进程重载失败：\n" + process.stdout + process.stderr)
        result = {"Semantica版本": importlib.metadata.version("semantica"),
                  "正式导入": "通过", "保存前": before, "独立进程重载": "通过",
                  "独立进程输出": process.stdout, "独立进程诊断": process.stderr,
                  "材料": "仅两个合成决定，未调用模型或业务系统"}
        output = root / "导出-exports/Semantica运行验证.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

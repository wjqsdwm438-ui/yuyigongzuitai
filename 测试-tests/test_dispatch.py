"""总入口真实专项调度检查，不用登记成功冒充语义正确。"""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "源码-src"))
from 语义工作台.storage import Store
from 语义工作台 import dispatch


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.material = self.folder / "材料.txt"
        self.material.write_text("仅当审批完成且备份可用时才允许发布；用户取消时不得发布。", encoding="utf-8")
        self.other_material = self.folder / "补充.md"
        self.other_material.write_text("补充材料保留独立来源，不覆盖原材料。", encoding="utf-8")
        self.store = Store(self.folder / "数据", project=ROOT)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def filled(self, state):
        result = copy.deepcopy(state["提交模板"])
        result["内容"] = {k: "合成产物，用于交接检查，不作为业务规则。" for k in result["内容"]}
        result["来源摘录"] = [{"证据": state["来源"][0]["编号"], "摘录": "用户取消时不得发布"}]
        result["审阅边界"] = "仅验证传递与引用机制，不证明语义正确。"
        return result

    def test_specialists_never_force_precedent_search(self):
        with patch("语义工作台.precedents.search_precedents", side_effect=AssertionError("不可强制调用检索")):
            state = dispatch.start(self.store, "原子化后建立世界模型", ["规则原子化", "世界模型"], "用户要求两个专项", self.material)
            first = self.filled(state)
            wrong = copy.deepcopy(first)
            wrong["能力"] = "世界模型"
            with self.assertRaisesRegex(ValueError, "先完成"):
                dispatch.submit(self.store, wrong)
            second = dispatch.submit(self.store, first)
            self.assertEqual(second["当前能力"], "世界模型")
            self.assertEqual(second["前序产物"][0]["内容"]["能力"], "规则原子化")
            self.assertEqual(dispatch.submit(self.store, first), second)
            end = dispatch.submit(self.store, self.filled(second))
            self.assertIsNone(end["当前能力"])
            self.assertIn("世界模型", dispatch.report(self.store, end["任务"]))
            history = dispatch.start(self.store, "查原子化依据", ["历史回查"], "回查指定任务", record_id=end["任务"])
            self.assertEqual(history, end)
            self.assertFalse(end["前序产物"][0]["内容"]["执行授权"])

    def test_missing_forged_or_changed_source_rejected(self):
        state = dispatch.start(self.store, "设计智能体", ["Agent设计"], "新增职责设计", self.material)
        result = self.filled(state)
        bad = copy.deepcopy(result)
        bad["内容"]["候选指令"] = ""
        with self.assertRaisesRegex(ValueError, "产物缺失"):
            dispatch.submit(self.store, bad)
        bad = copy.deepcopy(result)
        bad["来源摘录"][0]["摘录"] = "无须审批也可发布"
        with self.assertRaisesRegex(ValueError, "摘录"):
            dispatch.submit(self.store, bad)
        self.material.write_text("来源变化", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "来源变化"):
            dispatch.submit(self.store, result)
        self.assertEqual(self.store.list("专项产物"), [])

    def test_readonly_and_execution_gate(self):
        before = len(self.store.list())
        state = dispatch.start(None, "只读设计", ["Agent设计"], "不存材料", self.material, readonly=True)
        self.assertIn("未落盘", state["状态"])
        gate = dispatch.start(None, "批准实施", ["授权实施"], "用户要求实际改动")
        self.assertEqual(gate["状态"], "未执行")
        self.assertIn("通用业务规则文件", gate["原因"])
        self.assertIn("不包括仓库治理", gate["原因"])
        self.assertEqual(len(self.store.list()), before)
        with self.assertRaises(ValueError):
            dispatch.start(self.store, "含混请求", [], "不知道", self.material)

    def test_multiple_materials_keep_independent_sources(self):
        materials = [self.material, self.other_material]
        readonly = dispatch.start(None, "联合审查", ["Agent设计"], "需要核对两份来源", materials, readonly=True)
        self.assertEqual(
            readonly["材料集"],
            [
                {"路径": str(self.material), "内容": "仅当审批完成且备份可用时才允许发布；用户取消时不得发布。"},
                {"路径": str(self.other_material), "内容": "补充材料保留独立来源，不覆盖原材料。"},
            ],
        )
        self.assertNotIn("材料", readonly)

        state = dispatch.start(self.store, "联合审查", ["规则原子化"], "需要核对两份来源", materials)
        self.assertEqual(len(state["来源"]), 2)
        self.assertEqual(
            [source["历史内容"] for source in state["来源"]],
            [
                "仅当审批完成且备份可用时才允许发布；用户取消时不得发布。",
                "补充材料保留独立来源，不覆盖原材料。",
            ],
        )

    def test_cli_accepts_multiple_materials_in_readonly_mode(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "工作台.py"),
                "--项目", str(ROOT),
                "总入口",
                "--请求", "联合审查",
                "--能力", "Agent设计",
                "--依据", "需要核对两份来源",
                "--材料", str(self.material), str(self.other_material),
                "--只读",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"},
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual([item["路径"] for item in result["材料集"]], [str(self.material), str(self.other_material)])

    def test_case_diagnosis_rejects_multiple_materials(self):
        with self.assertRaisesRegex(ValueError, "每次只接受一份材料"):
            dispatch.start(
                self.store,
                "诊断一个案例",
                ["案例诊断"],
                "案例流程按单份材料检索",
                [self.material, self.other_material],
            )


if __name__ == "__main__":
    unittest.main()

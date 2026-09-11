"""真实离线组件的处理闭环与拒绝边界；不把通过测试等同语义验收。"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "源码-src"))
from 语义工作台.storage import Store
from 语义工作台 import workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = ROOT / "临时-tmp"
        temporary.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=temporary)
        self.folder = Path(self.temporary.name)
        self.store = Store(self.folder / "数据", project=ROOT)
        self.source = self.folder / "材料.txt"
        self.source.write_text("合成案例：审批与备份必须同时满足，取消后不得发布。", encoding="utf-8")
        self.evidence = self.store.capture(self.source)
        self.old = self.store.add("案例", dict(标题="审批备份发布问题", 预期="审批与备份同时满足",
            实际="只有审批也允许发布", 来源证据=[self.evidence]))
        self.network = patch("socket.socket.connect", side_effect=AssertionError("禁止网络访问"))
        self.network.start()

    def tearDown(self):
        self.network.stop()
        self.store.close()
        self.temporary.cleanup()

    def begin(self):
        return workflow.begin(self.store, self.source, "审批备份发布问题", "审批与备份同时满足")

    def review(self, packet):
        review = copy.deepcopy(packet["审阅模板"])
        current = packet["上下文"]["当前案例"]["内容"]["来源证据"][0]
        review.update(处置="规则裁决或改稿", 依据="合成材料要求联合必要条件，候选少了备份条件。",
            证据引用=[{"证据": current, "摘录": "审批与备份必须同时满足"}],
            无规则依据说明="本次只有合成材料，不认定为正式规则。",
            建议动作="恢复联合条件，提交人工审阅。", 保留边界="取消禁止发布不变。",
            验证计划="检查审批、备份及取消条件组合。", 待决事项="业务规则尚未批准。")
        for c in review["先例比较"]:
            c.update(结论="需调整", 适用条件="同属审批备份案例。", 失败机制="材料均描述联合条件丢失。",
                规则版本比较="尚无正式规则版本。", 反例="已取消时不能发布。", 关键差异="旧案例没有处理决定。")
        return review

    def test_real_component_roundtrip_idempotence_and_history(self):
        packet = self.begin()
        self.assertEqual(packet["上下文"]["检索引擎"], "Semantica 0.6.8")
        self.assertEqual({c["旧案例"] for c in packet["审阅模板"]["先例比较"]}, {self.old})
        review = self.review(packet)
        report = workflow.finish(self.store, review)
        ident = report["记录"]["编号"]
        count = len(self.store.list())
        self.assertEqual(workflow.finish(self.store, review)["记录"]["编号"], ident)
        self.assertEqual(len(self.store.list()), count)
        changed = copy.deepcopy(review)
        changed["依据"] = "另一个审阅，不可覆盖原决定。"
        with self.assertRaisesRegex(ValueError, "已有决定"):
            workflow.finish(self.store, changed)
        self.source.write_text("现行材料已修改。", encoding="utf-8")
        historical = workflow.decision_report(self.store, ident)
        self.assertIn("审批与备份必须同时满足", historical["中文报告"])
        self.assertFalse(historical["记录"]["内容"]["执行授权"])
        first = workflow.export_report(self.store, ident, self.folder / "报告")
        second = workflow.export_report(self.store, ident, self.folder / "报告")
        self.assertNotEqual(first["中文报告"], second["中文报告"])
        self.assertEqual(Path(first["中文报告"]).read_text(encoding="utf-8"), historical["中文报告"])

    def test_reject_incomplete_forged_or_out_of_context_review(self):
        packet = self.begin()
        review = self.review(packet)
        bad = copy.deepcopy(review)
        bad["先例比较"] = []
        with self.assertRaisesRegex(ValueError, "每个先例"):
            workflow.finish(self.store, bad)
        bad = copy.deepcopy(review)
        bad["证据引用"][0]["摘录"] = "不存在的核验结论"
        with self.assertRaisesRegex(ValueError, "摘录"):
            workflow.finish(self.store, bad)
        rule = self.store.add("规则版本", dict(规则编号="测试规则", 版本="1", 正文="禁止发布",
            来源证据=[self.evidence], 语义=dict(主体="系统", 动作="发布", 对象="版本", 情态="禁止",
            条件={}, 范围="合成测试", 例外=[])))
        bad = copy.deepcopy(review)
        bad["规则版本"] = [rule]
        with self.assertRaisesRegex(ValueError, "未进入本次上下文"):
            workflow.finish(self.store, bad)
        self.assertEqual(self.store.list("决定"), [])
        self.assertEqual(self.store.list("复用审阅"), [])

    def test_source_drift_only_allows_evidence_request(self):
        packet = self.begin()
        review = self.review(packet)
        self.source.write_text("来源改版，不能静默沿用旧材料。", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "来源已变化"):
            workflow.finish(self.store, review)
        review["处置"] = "补充证据"
        report = workflow.finish(self.store, review)
        self.assertTrue(report["记录"]["内容"]["来源已变化"])
        self.assertIn("审批与备份必须同时满足", report["中文报告"])

    def test_transaction_rolls_back_partial_begin_and_finish(self):
        count = len(self.store.list())
        evidence_count = self.store.db.execute("SELECT count(*) FROM evidence").fetchone()[0]
        with patch("语义工作台.precedents.search_precedents", side_effect=RuntimeError("模拟组件失败")):
            with self.assertRaisesRegex(RuntimeError, "模拟组件失败"):
                self.begin()
        self.assertEqual(len(self.store.list()), count)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM evidence").fetchone()[0], evidence_count)
        review = self.review(self.begin())
        original = self.store.add

        def fail_decision(kind, payload):
            if kind == "决定":
                raise RuntimeError("模拟决定写入失败")
            return original(kind, payload)

        with patch.object(self.store, "add", side_effect=fail_decision):
            with self.assertRaisesRegex(RuntimeError, "模拟决定写入失败"):
                workflow.finish(self.store, review)
        self.assertEqual(self.store.list("复用审阅"), [])
        self.assertEqual(self.store.list("决定"), [])
        self.assertEqual(workflow.finish(self.store, review)["记录"]["类型"], "决定")

    def test_cli_resume_and_trace_across_processes(self):
        def cli(*args):
            run = subprocess.run([sys.executable, "-X", "utf8", "-B", str(ROOT / "工作台.py"),
                "--数据目录", str(self.store.root), *args], cwd=ROOT, capture_output=True,
                encoding="utf-8", timeout=120)
            self.assertEqual(run.returncode, 0, run.stderr)
            return json.loads(run.stdout)

        packet = cli("处理", str(self.source), "--问题", "审批备份发布问题")
        review_path = self.folder / "审阅.json"
        review_path.write_text(json.dumps(self.review(packet), ensure_ascii=False), encoding="utf-8")
        report = cli("提交审阅", str(review_path))
        ident = report["记录"]["编号"]
        self.assertEqual(cli("回查", ident)["当时上下文"], packet["上下文"])
        resumed = cli("续接", ident)
        self.assertNotEqual(resumed["任务"], packet["任务"])
        self.assertEqual(resumed["上下文"]["当前案例"], packet["上下文"]["当前案例"])
        self.assertEqual(cli("回查", packet["任务"])["上下文"], packet["上下文"])


if __name__ == "__main__":
    unittest.main()

"""仓库治理：分类、预演、冲突与恢复边界。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "源码-src"))

from 语义工作台.repository_governance import apply_plan, cache_manifest, inventory, preview, restore


class RepositoryGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "临时-tmp")
        self.root = Path(self.temp.name)
        (self.root / "活动-active").mkdir()
        (self.root / "活动-active" / "失败.log").write_text("明确的失败堆栈", encoding="utf-8")
        (self.root / "活动-active" / "垃圾.tmp").write_text("重复输出", encoding="utf-8")
        (self.root / "活动-active" / "未知.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def manifest(self):
        return {
            "版本": 1,
            "归档根": "归档-archive",
            "条目": [{
                "路径": "活动-active/失败.log",
                "材料类型": "测试材料",
                "分类": "具有明确失败机制的反面案例",
                "动作": "归档",
                "目标": "归档-archive/测试证据/失败.log",
                "依据": "堆栈说明失败机制",
                "生产者": "测试运行器",
                "活动消费者": [],
                "消费者检查依据": "已检索活动源码和测试入口，没有引用该日志",
                "路径所有者": "测试维护者",
                "生命周期": "历史",
                "证据强度": "强",
                "不影响恢复": True,
            }]
        }

    def test_inventory_excludes_archive_and_reports_secondary_python_metric(self):
        (self.root / "归档-archive").mkdir()
        (self.root / "归档-archive" / "旧规则.md").write_text("历史", encoding="utf-8")
        (self.root / "活动-active" / "large.py").write_text("x = 1\n" * 501, encoding="utf-8")
        report = inventory(self.root)
        self.assertEqual(report["活动文件数"], 4)
        self.assertEqual(report["默认排除归档"], "归档-archive")
        self.assertEqual(report["Python提示"][0]["行数"], 501)
        self.assertIn("不能单凭行数判定职责有问题", report["Python指标边界"])

    def test_cache_manifest_only_selects_generated_cache_files(self):
        (self.root / "活动-active" / "cache").mkdir()
        (self.root / "活动-active" / "cache" / "compiled.nbc").write_bytes(b"cache")
        (self.root / "活动-active" / "evidence.nbc").write_bytes(b"not-in-cache")
        manifest = cache_manifest(self.root)
        self.assertEqual(len(manifest["条目"]), 1)
        self.assertEqual(manifest["条目"][0]["路径"], "活动-active/cache/compiled.nbc")
        self.assertEqual(manifest["条目"][0]["动作"], "删除")
        self.assertEqual(manifest["条目"][0]["生命周期"], "可再生")
        self.assertEqual(manifest["条目"][0]["活动消费者"], [])

    def test_action_requires_structured_governance_evidence(self):
        manifest = self.manifest()
        for field in ("生产者", "活动消费者", "消费者检查依据", "路径所有者", "生命周期", "证据强度"):
            del manifest["条目"][0][field]
        plan = preview(self.root, manifest)
        self.assertEqual(plan["状态"], "已阻止")
        reasons = "".join(plan["冲突与阻止原因"])
        for field in ("生产者", "活动消费者", "消费者检查依据", "路径所有者", "生命周期", "证据强度"):
            self.assertIn(field, reasons)

    def test_preview_then_apply_archive_and_restore(self):
        plan = preview(self.root, self.manifest())
        self.assertEqual(plan["状态"], "可执行")
        self.assertEqual(plan["动作数"], 1)
        receipt = apply_plan(self.root, plan)
        self.assertFalse((self.root / "活动-active" / "失败.log").exists())
        self.assertTrue((self.root / "归档-archive" / "测试证据" / "失败.log").exists())
        restored = restore(self.root, receipt)
        self.assertEqual(restored["状态"], "已恢复")
        self.assertTrue((self.root / "活动-active" / "失败.log").exists())
        self.assertEqual(restored["执行依据"]["原执行预演编号"], plan["预演编号"])
        self.assertNotIn("业务授权", restored)

    def test_unknown_cannot_be_moved_or_deleted(self):
        manifest = self.manifest()
        manifest["条目"][0].update({
            "路径": "活动-active/未知.json",
            "分类": "证据不足的未知材料",
            "动作": "删除",
        })
        plan = preview(self.root, manifest)
        self.assertEqual(plan["状态"], "已阻止")
        self.assertIn("未知材料", "".join(plan["冲突与阻止原因"]))

    def test_delete_needs_evidence_and_exact_plan_approval(self):
        manifest = self.manifest()
        manifest["条目"][0].update({
            "路径": "活动-active/垃圾.tmp",
            "分类": "重复或无效垃圾",
            "动作": "删除",
        })
        plan = preview(self.root, manifest)
        with self.assertRaisesRegex(ValueError, "批准删除"):
            apply_plan(self.root, plan)
        receipt = apply_plan(self.root, plan, delete_approval=plan["预演编号"])
        self.assertFalse((self.root / "活动-active" / "垃圾.tmp").exists())
        self.assertIn("归档移动 0 项可凭本回执恢复", receipt["恢复边界"])
        self.assertIn("删除 1 项不可恢复", receipt["恢复边界"])
        self.assertEqual(receipt["执行依据"]["预演编号"], plan["预演编号"])
        self.assertEqual(receipt["执行依据"]["删除批准预演编号"], plan["预演编号"])
        self.assertNotIn("业务授权", receipt)

    def test_archive_and_delete_must_use_separate_plans(self):
        manifest = self.manifest()
        deletion = dict(manifest["条目"][0])
        deletion.update({
            "路径": "活动-active/垃圾.tmp",
            "分类": "重复或无效垃圾",
            "动作": "删除",
            "目标": None,
            "生命周期": "可再生",
        })
        manifest["条目"].append(deletion)
        plan = preview(self.root, manifest)
        self.assertEqual(plan["状态"], "已阻止")
        self.assertIn("归档与删除必须分开预演", "".join(plan["冲突与阻止原因"]))

    def test_conflicting_target_and_changed_source_stop_execution(self):
        manifest = self.manifest()
        (self.root / "归档-archive" / "测试证据").mkdir(parents=True)
        (self.root / "归档-archive" / "测试证据" / "失败.log").write_text("占用", encoding="utf-8")
        blocked = preview(self.root, manifest)
        self.assertEqual(blocked["状态"], "已阻止")
        (self.root / "归档-archive" / "测试证据" / "失败.log").unlink()
        plan = preview(self.root, manifest)
        (self.root / "活动-active" / "失败.log").write_text("预演后变化", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "预演后已变化"):
            apply_plan(self.root, plan)

    def test_tampered_plan_is_rejected(self):
        plan = preview(self.root, self.manifest())
        plan["动作"][0]["源"] = "活动-active/垃圾.tmp"
        plan["动作"][0]["SHA256"] = __import__("hashlib").sha256("重复输出".encode("utf-8")).hexdigest()
        with self.assertRaisesRegex(ValueError, "预演编号与动作清单不一致"):
            apply_plan(self.root, plan)


if __name__ == "__main__":
    unittest.main()

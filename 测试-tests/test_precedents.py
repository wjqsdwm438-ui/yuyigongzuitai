"""真实 Semantica 的离线候选检索检查，不证明同根因或业务语义正确。"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "源码-src"))
from 语义工作台.storage import Store
from 语义工作台.precedents import search_precedents


class PrecedentsTests(unittest.TestCase):
    def test_offline_candidates_and_replacement(self):
        temporary = ROOT / "临时-tmp"
        temporary.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary) as folder:
            store = Store(Path(folder) / "数据")
            try:
                source = Path(folder) / "证据.txt"
                source.write_text("合成证据：审批和备份必须同时满足。", encoding="utf-8")
                evidence = store.capture(source)

                def case(title, **extra):
                    return store.add("案例", dict(标题=title, 预期="审批与备份必须同时满足",
                        实际="仅审批完成就允许发布", 来源证据=[evidence], **extra))

                def decision(case_id, **extra):
                    return store.add("决定", dict(案例=case_id, 处置="规则裁决或改稿",
                        依据="保留联合必要条件", 输入证据=[evidence], 规则版本=[],
                        无规则依据说明="合成测试", **extra))

                old = case("审批备份案例")
                middle = case("审批备份案例", 替代记录=old)
                latest = case("审批备份案例", 替代记录=middle)
                d1 = decision(latest)
                d2 = decision(latest, 替代记录=d1)
                d3 = decision(latest, 替代记录=d2)
                bare = case("审批备份未处理案例")
                query = case("审批备份新案例")
                decision(query)
                count = len(store.list())
                # 从正式导入到查询均禁止任何套接字连接。
                with patch("socket.socket.connect", side_effect=AssertionError("禁止网络访问")):
                    result = search_precedents(store, query)
                    again = search_precedents(store, query)
                self.assertEqual(result, again)
                self.assertEqual(count, len(store.list()))
                pairs = {(r["案例"], r["决定"]) for r in result["候选"]}
                self.assertEqual(pairs, {(latest, d3), (bare, None)})
                self.assertEqual(result["引擎"], "Semantica 0.6.8")
                self.assertTrue(all(r["状态"] == "待审" for r in result["候选"]))
                self.assertIn("空结果不意味着新问题", result["说明"])
                with self.assertRaisesRegex(ValueError, "已被替代"):
                    search_precedents(store, old)
                with self.assertRaises(ValueError):
                    search_precedents(store, query, True)
                self.assertEqual(store.get(d3)["内容"]["案例"], latest)
                self.assertEqual(store.evidence(evidence)["历史内容"], source.read_text(encoding="utf-8"))
                unique = store.add("案例", dict(标题="zzzz", 预期="zzzz", 实际="zzzz",
                                                来源证据=[evidence]))
                long_case = store.add("案例", dict(标题="长材料", 预期="甲" * 6000,
                    实际="仅审批完成就允许发布", 来源证据=[evidence]))
                with patch("socket.socket.connect", side_effect=AssertionError("禁止网络访问")):
                    self.assertEqual(search_precedents(store, unique)["候选"], [])
                    long_result = search_precedents(store, long_case)
                self.assertTrue(long_result["候选"])
                self.assertNotIn(long_case, [r["案例"] for r in long_result["候选"]])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()

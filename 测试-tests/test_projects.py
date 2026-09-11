"""项目隔离回归：不代表操作系统权限隔离或语义正确性。"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "源码-src"))
from 语义工作台 import projects
from 语义工作台.storage import Store
from 语义工作台.precedents import search_precedents


class 项目隔离测试(unittest.TestCase):
    def setUp(self):
        temporary = ROOT / "临时-tmp"
        temporary.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="项目隔离-", dir=temporary)
        self.root = Path(self.temp.name)
        self.a, self.b = self.root / "甲项目-project", self.root / "乙项目-project"
        self.a.mkdir()
        self.b.mkdir()
        self.patch = patch.object(projects, "ROOT", self.root)
        self.patch.start()
        self.stores = []

    def tearDown(self):
        for store in reversed(self.stores):
            store.close()
        self.patch.stop()
        self.temp.cleanup()

    def open(self, project, **kwargs):
        store = projects.open_project(project, **kwargs)
        self.stores.append(store)
        return store

    def seed(self, store, label):
        source = self.root / (label + ".txt")
        source.write_text(label + "：审批和备份同时满足。", encoding="utf-8")
        evidence = store.capture(source)
        case = store.add("案例", dict(标题="审批备份案例", 预期="审批和备份同时满足",
                                      实际="仅审批完成就发布", 来源证据=[evidence]))
        decision = store.add("决定", dict(案例=case, 处置="规则裁决或改稿", 依据=label,
            输入证据=[evidence], 规则版本=[], 无规则依据说明="合成隔离测试"))
        return evidence, case, decision

    def test_默认分库且路径别名一致(self):
        self.assertNotEqual(projects.project_data(self.a), projects.project_data(self.b))
        alias = self.a / ".." / self.a.name
        self.assertEqual(projects.project_data(self.a), projects.project_data(alias))
        self.assertEqual(projects.canonical(self.a), projects.canonical(alias))

    def test_同规则编号可独立且外部证据决定不可引用(self):
        a, b = self.open(self.a), self.open(self.b)
        ea, ca, da = self.seed(a, "甲")
        eb, cb, db = self.seed(b, "乙")
        for store, evidence, text in ((a, ea, "甲规则"), (b, eb, "乙规则")):
            store.add("规则版本", dict(规则编号="共同编号", 版本="1", 正文=text,
                来源证据=[evidence], 语义=dict(主体="执行者", 动作="发布", 对象="版本",
                情态="必要条件", 条件={"全部": ["审批", "备份"]}, 范围="本项目", 例外=[])))
        self.assertEqual(a.list("规则版本")[0]["内容"]["正文"], "甲规则")
        self.assertEqual(b.list("规则版本")[0]["内容"]["正文"], "乙规则")
        count = len(a.list())
        with self.assertRaisesRegex(ValueError, "证据不存在"):
            a.add("案例", dict(标题="跨项目", 预期="甲", 实际="乙", 来源证据=[eb]))
        with self.assertRaisesRegex(ValueError, "记录不存在"):
            a.add("验证", dict(对象=db, 预期="甲", 观察="乙", 结论="未运行", 证据=[ea]))
        with self.assertRaisesRegex(ValueError, "记录不存在"):
            a.report(db)
        self.assertEqual(count, len(a.list()))

    def test_自定义目录拒绝其他项目且原库不变(self):
        data = self.root / "共享目录-data"
        a = self.open(self.a, directory=data)
        self.seed(a, "自定义")
        before = (data / "workbench.sqlite3").read_bytes()
        for readonly in (False, True):
            with self.subTest(readonly=readonly), self.assertRaisesRegex(ValueError, "项目隔离"):
                projects.open_project(self.b, directory=data, readonly=readonly)
            self.assertEqual(before, (data / "workbench.sqlite3").read_bytes())

    def test_历史非空库拒绝自动认领(self):
        data = self.root / "历史-data"
        legacy = Store(data)
        self.stores.append(legacy)
        self.seed(legacy, "历史")
        before = (data / "workbench.sqlite3").read_bytes()
        with self.assertRaisesRegex(ValueError, "历史记录不可自动绑定"):
            projects.open_project(self.a, directory=data)
        self.assertEqual(before, (data / "workbench.sqlite3").read_bytes())

    def test_显式参考只读不导入且只读库不能写(self):
        a, b = self.open(self.a), self.open(self.b)
        evidence, case, decision = self.seed(b, "只读")
        before = (b.root / "workbench.sqlite3").read_bytes()
        result = projects.reference_project(self.a, self.b)
        self.assertFalse(result["业务授权"])
        self.assertIn(case, [r["编号"] for r in result["外部参考"]])
        self.assertEqual(a.list(), [])
        readonly = self.open(self.b, readonly=True)
        self.assertEqual(readonly.get(case), b.get(case))
        with self.assertRaises(sqlite3.OperationalError):
            readonly.add("案例", dict(标题="越界", 预期="甲", 实际="乙", 来源证据=[evidence]))
        self.assertEqual(before, (b.root / "workbench.sqlite3").read_bytes())
        with self.assertRaisesRegex(ValueError, "相同"):
            projects.reference_project(self.a, self.a / ".." / self.a.name)

    def test_Semantica默认检索只返回本项目(self):
        a, b = self.open(self.a), self.open(self.b)
        ea, ca, da = self.seed(a, "甲检索")
        eb, cb, db = self.seed(b, "乙检索")
        query = a.add("案例", dict(标题="审批备份新案例", 预期="审批和备份同时满足",
                                  实际="仅审批完成就发布", 来源证据=[ea]))
        with patch("socket.socket.connect", side_effect=AssertionError("禁止网络访问")):
            result = search_precedents(a, query)
        self.assertEqual({(r["案例"], r["决定"]) for r in result["候选"]}, {(ca, da)})
        self.assertNotIn(cb, str(result))
        self.assertNotIn(db, str(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)

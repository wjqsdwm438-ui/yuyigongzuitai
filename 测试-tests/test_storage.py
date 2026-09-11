"""存储边界回归：通过仅证明记录机制，不证明业务语义正确。"""
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

项目根 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(项目根 / "源码-src"))
from 语义工作台.storage import Store, read_json


class 存储边界测试(unittest.TestCase):
    def setUp(self):
        临时根 = 项目根 / "临时-tmp"
        临时根.mkdir(exist_ok=True)
        self.临时 = tempfile.TemporaryDirectory(prefix="存储验证-", dir=临时根)
        self.目录 = Path(self.临时.name)
        self.库 = Store(self.目录 / "数据-data")
        self.来源 = self.目录 / "来源.txt"
        self.来源.write_text("当时的来源：联合条件不可丢失。", encoding="utf-8")
        self.证据 = self.库.capture(self.来源)

    def tearDown(self):
        self.库.close()
        self.临时.cleanup()

    def 规则(self, 版本="1"):
        return {
            "规则编号": "规则-001", "版本": 版本, "正文": "审批完成且备份可用才允许发布。",
            "来源证据": [self.证据],
            "语义": {"主体": "发布者", "动作": "发布", "对象": "本次版本", "情态": "必要条件",
                     "条件": {"全部": ["审批完成", "备份可用"]}, "范围": "本次发布", "例外": []},
        }

    def 案例(self, 标题="案例甲"):
        return self.库.add("案例", {"标题": 标题, "预期": "保留联合条件", "实际": "候选使用或条件", "来源证据": [self.证据]})

    def 决定(self, 案例编号, 规则编号):
        return {"案例": 案例编号, "处置": "规则裁决或改稿", "依据": "联合条件被放宽",
                "输入证据": [self.证据], "规则版本": [规则编号]}

    def test_来源变动不覆盖历史报告(self):
        规则编号 = self.库.add("规则版本", self.规则())
        决定编号 = self.库.add("决定", self.决定(self.案例(), 规则编号))
        self.来源.write_text("已经变化的新来源", encoding="utf-8")
        self.assertFalse(self.库.evidence(self.证据, current=True)["当前来源一致"])
        报告 = self.库.report(决定编号)
        self.assertEqual(报告["历史证据"][0]["历史内容"], "当时的来源：联合条件不可丢失。")
        self.assertEqual(报告["引用规则"][0]["内容"]["版本"], "1")
        self.来源.unlink()
        self.assertFalse(self.库.evidence(self.证据, current=True)["当前来源一致"])
        self.assertEqual(self.库.report(决定编号), 报告)

    def test_重复版本拒绝而新版本保留旧记录(self):
        旧编号 = self.库.add("规则版本", self.规则())
        with self.assertRaisesRegex(ValueError, "版本已存在"):
            self.库.add("规则版本", self.规则())
        新编号 = self.库.add("规则版本", dict(self.规则("2"), 替代记录=旧编号))
        self.assertEqual(self.库.get(旧编号)["内容"]["版本"], "1")
        self.assertEqual(self.库.get(新编号)["内容"]["替代记录"], 旧编号)
        self.assertEqual(len(self.库.list("规则版本")), 2)

    def test_决定拒绝错误引用类型(self):
        案例编号 = self.案例()
        规则编号 = self.库.add("规则版本", self.规则())
        for 输入 in (self.决定(规则编号, 规则编号), self.决定(案例编号, 案例编号)):
            with self.subTest(输入=输入), self.assertRaisesRegex(ValueError, "引用类型"):
                self.库.add("决定", 输入)
        self.assertEqual(self.库.list("决定"), [])

    def test_用户输入不能授予业务授权(self):
        案例编号 = self.案例()
        规则编号 = self.库.add("规则版本", self.规则())
        编号 = self.库.add("决定", dict(self.决定(案例编号, 规则编号), 状态="已批准", 执行授权=True))
        内容 = self.库.get(编号)["内容"]
        self.assertIs(内容["执行授权"], False)
        self.assertEqual(内容["状态"], "待审")

    def test_数据库也拒绝覆盖和删除历史(self):
        编号 = self.案例()
        for 语句, 参数 in (("UPDATE records SET kind='决定' WHERE id=?", 编号),
                          ("DELETE FROM records WHERE id=?", 编号),
                          ("UPDATE evidence SET content=x'00' WHERE id=?", self.证据),
                          ("DELETE FROM evidence WHERE id=?", self.证据)):
            with self.subTest(语句=语句), self.assertRaises(sqlite3.IntegrityError):
                with self.库.db:
                    self.库.db.execute(语句, (参数,))

    def test_备份可在全新隔离目录恢复(self):
        编号 = self.案例()
        备份 = self.目录 / "备份-backup" / "副本.sqlite3"
        self.库.backup(备份)
        with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
            self.库.backup(备份)
        恢复目录 = self.目录 / "恢复-restore"
        恢复目录.mkdir()
        shutil.copyfile(备份, 恢复目录 / "workbench.sqlite3")
        恢复库 = Store(恢复目录)
        try:
            self.assertEqual(恢复库.get(编号), self.库.get(编号))
            self.assertEqual(恢复库.evidence(self.证据), self.库.evidence(self.证据))
            self.assertEqual(恢复库.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            恢复库.close()

    def test_JSON拒绝重复字段和非标准数字(self):
        文件 = self.目录 / "输入.json"
        for 内容 in ('{"规则":1,"规则":2}', '{"对象":{"值":1,"值":2}}', '{"值":NaN}', '{"值":Infinity}'):
            文件.write_text(内容, encoding="utf-8")
            with self.subTest(内容=内容), self.assertRaises(ValueError):
                read_json(文件)
        文件.write_text('{"名称":"中文保留","条件":["甲","乙"]}', encoding="utf-8")
        self.assertEqual(read_json(文件), {"名称": "中文保留", "条件": ["甲", "乙"]})

    def test_引用缺失及无依据决定拒绝(self):
        案例编号 = self.案例()
        with self.assertRaisesRegex(ValueError, "证据不存在"):
            self.库.add("案例", {"标题": "缺证据", "预期": "甲", "实际": "乙", "来源证据": ["不存在"]})
        输入 = self.决定(案例编号, "不存在")
        with self.assertRaisesRegex(ValueError, "记录不存在"):
            self.库.add("决定", 输入)
        输入["规则版本"] = []
        with self.assertRaisesRegex(ValueError, "说明依据缺口"):
            self.库.add("决定", 输入)

    def test_案例不可与自身归并(self):
        编号 = self.案例()
        with self.assertRaisesRegex(ValueError, "自身归并"):
            self.库.add("复用审阅", {"新案例": 编号, "旧案例": 编号, "结论": "可复用",
                                    "依据": "表面相似", "关键差异": "无"})


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""冻结的合成控制：验证取证、复审及安全边界，不冒充独立模型行为评测。"""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '源码-src'))
from 语义工作台 import retirement as r
from 语义工作台.storage import Store


class RetirementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'Project'
        self.root.mkdir()
        self.write('AGENTS.md', '# 规则\n\n须按[指导](skills/a/SKILL.md)人工审阅；紧急情况例外。\n')
        self.write('skills/a/SKILL.md', '# 操作\n\n只能使用[依据](basis.md)规定的方法，不自动批准。\n')
        self.write('skills/a/basis.md', '# 当前依据\n\n旧入口已经停用，新入口经过核验。\n')
        self.store = Store(Path(self.tmp.name) / 'db', project=self.root)
        self.day = date(2026, 9, 20)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def write(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        return p

    def scan(self, **kw):
        return r.scan(self.root, store=self.store, today=self.day, record=True, **kw)

    def review(self, result, conclusion='保留有效'):
        u = next(u for u in result['条目'] if u['路径'] == 'AGENTS.md')
        return self.review_unit(result, u, conclusion)

    def review_unit(self, result, unit, conclusion='保留有效'):
        value = r.template(result, unit)
        value.update(结论=conclusion, 依据='此条只要求按现行依据人工复核，未指定旧入口。',
                     适用条件与例外='人工审阅义务及紧急例外均保留。', 替代与消费者='AGENTS 为入口；不移文件。',
                     验证与边界='合成测试；语义判断由审阅者给出，程序只检查来源与状态。')
        return value

    def test_explicit_retired_target_is_detected(self):
        self.write('skills/a/SKILL.md', '# 旧指导\n\n状态：已退役\n\n保留历史。')
        u = next(u for u in self.scan()['条目'] if u['路径'] == 'AGENTS.md')
        self.assertEqual(u['信号'][0]['状态'], '目标明示退役，检查活动引用')

    def test_negated_retired_word_does_not_trigger(self):
        self.write('skills/a/SKILL.md', '# 当前指导\n\n状态：未退役\n\n不能因为低频就退役。')
        self.assertEqual(self.scan()['统计']['确定性信号'], 0)

    def test_yaml_agent_pointer_followed(self):
        self.write('agents/main.yaml', 'instructions: "../skills/a/basis.md"')
        x = self.scan(scopes=['agents'])
        self.assertIn('skills/a/basis.md', x['覆盖文件'])

    def test_crlf_and_bom_keep_raw_version_and_review(self):
        p = self.root / 'AGENTS.md'
        p.write_bytes(b'\xef\xbb\xbf' + '# Rule\r\n\r\nFirst.\r\nSecond.\r\n'.encode())
        v = self.review(self.scan())
        r.review(self.store, v, self.day)
        p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n'))
        u = next(u for u in self.scan()['条目'] if u['路径'] == 'AGENTS.md')
        self.assertEqual(u['巡检状态'], '待语义复核')

    def test_no_side_effect_default_scan(self):
        before = sorted(str(p) for p in self.root.rglob('*'))
        r.scan(self.root)
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))
        self.assertEqual([], self.store.list())

    def test_full_chain_and_exceptions_preserved(self):
        x = self.scan()
        u = next(u for u in x['条目'] if u['路径'] == 'AGENTS.md')
        self.assertIn('skills/a/basis.md', u['依据版本'])
        self.assertIn('紧急情况例外', u['正文'])
        self.assertEqual(x['统计']['确定性信号'], 0)
        self.assertFalse(x['业务授权'])

    def test_repeat_snapshot_idempotent(self):
        x, y = self.scan(), self.scan()
        self.assertEqual(x['巡检'], y['巡检'])
        self.assertEqual(len(self.store.list('退役巡检')), 1)

    def test_repeat_review_idempotent_and_never_approval(self):
        v = self.review(self.scan())
        a = r.review(self.store, v, self.day)
        b = r.review(self.store, v, self.day)
        self.assertEqual(a['编号'], b['编号'])
        self.assertFalse(a['内容']['执行授权'])

    def test_review_suppresses_only_same_version(self):
        r.review(self.store, self.review(self.scan()), self.day)
        u = next(u for u in self.scan()['条目'] if u['路径'] == 'AGENTS.md')
        self.assertEqual(u['巡检状态'], '已记录待到期')
        self.write('skills/a/basis.md', '# 当前依据\n\n依据又变化；应重新核实。')
        u = next(u for u in self.scan()['条目'] if u['路径'] == 'AGENTS.md')
        self.assertEqual(u['巡检状态'], '待语义复核')
        self.assertIn('关联依据变化', u['触发依据'])

    def test_body_change_reopens_same_unit_identity(self):
        first = self.scan()
        before = next(u for u in first['条目'] if u['路径'] == 'AGENTS.md')
        r.review(self.store, self.review_unit(first, before, '建议退役'), self.day)
        self.write('AGENTS.md', '# 规则\n\n须立即按[指导](skills/a/SKILL.md)人工审阅；紧急情况例外。\n')
        after = next(u for u in self.scan()['条目'] if u['路径'] == 'AGENTS.md')
        self.assertEqual(after['条目'], before['条目'])
        self.assertEqual(after['巡检状态'], '待语义复核')
        self.assertIn('正文或关联依据变化', after['触发依据'])

    def test_structural_edits_never_suppress_review(self):
        variants = {
            'insert': '# 规则\n\n新增前置。\n\n第一条。\n\n第二条。\n',
            'delete': '# 规则\n\n第二条。\n',
            'rename': '# 新规则\n\n第一条。\n\n第二条。\n',
        }
        for name, changed in variants.items():
            with self.subTest(name=name):
                self.write('AGENTS.md', '# 规则\n\n第一条。\n\n第二条。\n')
                baseline = self.scan()
                for unit in [u for u in baseline['条目'] if u['路径'] == 'AGENTS.md']:
                    r.review(self.store, self.review_unit(baseline, unit), self.day)
                self.write('AGENTS.md', changed)
                units = [u for u in self.scan()['条目'] if u['路径'] == 'AGENTS.md']
                self.assertTrue(units)
                self.assertTrue(all(u['巡检状态'] == '待语义复核' for u in units))
                self.assertFalse(any(u['巡检状态'] in {'已记录待到期', '待授权处置'} for u in units))

    def test_due_date_reopens_without_change(self):
        v = self.review(self.scan());v['复审日期'] = '2026-09-21'
        r.review(self.store, v, self.day)
        self.day = date(2026, 9, 21)
        u = next(u for u in self.scan()['条目'] if u['路径'] == 'AGENTS.md')
        self.assertEqual(u['触发依据'], '复审到期')

    def test_readonly_store_reuses_memory_without_writes(self):
        r.review(self.store, self.review(self.scan()), self.day)
        before = self.store.db.execute('SELECT count(*) FROM records').fetchone()[0]
        ro = Store(self.store.root, project=self.root, readonly=True)
        try:
            x = r.scan(self.root, store=ro)
            self.assertTrue(any(u['巡检状态'] == '已记录待到期' for u in x['条目']))
        finally:
            ro.close()
        self.assertEqual(before, self.store.db.execute('SELECT count(*) FROM records').fetchone()[0])

    def test_healthy_links_are_not_semantic_clean_bill(self):
        # 机械-only 分支没有信号；最终方案仍将整条指导纳入语义审查。
        self.write('AGENTS.md', '# 操作\n\n必须使用旧入口，参见[依据](skills/a/basis.md)。\n')
        x = self.scan()
        self.assertEqual(x['统计']['确定性信号'], 0)
        u = next(u for u in x['条目'] if u['路径'] == 'AGENTS.md')
        self.assertEqual(u['巡检状态'], '待语义复核')
        v = self.review(x, '建议退役')
        v['依据'] = '指导要求使用旧入口，但其现行依据明确旧入口已停用。'
        v['来源摘录'].append({'路径': 'skills/a/basis.md', '摘录': '旧入口已经停用'})
        rec = r.review(self.store, v, self.day)
        self.assertEqual(rec['内容']['结论'], '建议退役')
        self.assertIn('必须使用旧入口', (self.root / 'AGENTS.md').read_text())

    def test_broken_markdown_link_is_candidate_not_retirement(self):
        self.write('AGENTS.md', '# 规则\n\n[旧说明](missing.md)')
        x = self.scan()
        self.assertEqual(x['条目'][0]['信号'][0]['状态'], '断链候选')
        self.assertNotIn('结论', x['条目'][0])

    def test_anchor_present_and_missing(self):
        self.write('AGENTS.md', '# 规则\n\n[正](skills/a/basis.md#当前依据) [疑](skills/a/basis.md#不存在)')
        x = self.scan()
        self.assertEqual(x['统计']['确定性信号'], 1)
        self.assertEqual(x['条目'][0]['信号'][0]['状态'], '锚点待核实')

    def test_duplicate_heading_anchor(self):
        self.assertIn('标题-1', r._anchors('# 标题\n\n# 标题'))

    def test_bare_code_filename_not_broken_assertion(self):
        self.write('AGENTS.md', '# 规则\n\n每份 `SKILL.md` 保留职责。')
        self.assertEqual(self.scan()['统计']['确定性信号'], 0)

    def test_reference_link_resolved(self):
        self.write('AGENTS.md', '# 规则\n\n依照[正文][main]\n\n[main]: skills/a/basis.md')
        x = self.scan(scopes=['AGENTS.md'])
        self.assertIn('skills/a/basis.md', x['覆盖文件'])

    def test_unicode_percent_path_resolved(self):
        self.write('说明.md', '# 说明\n\n有效。')
        self.write('AGENTS.md', '# 规则\n\n[说明](%E8%AF%B4%E6%98%8E.md)')
        self.assertIn('说明.md', self.scan()['覆盖文件'])

    def test_scopes_cannot_escape(self):
        with self.assertRaisesRegex(ValueError, '越界'):
            self.scan(scopes=['../'])

    def test_link_escape_not_read(self):
        secret = Path(self.tmp.name) / 'secret.md';secret.write_text('outside', encoding='utf-8')
        self.write('AGENTS.md', '# 规则\n\n[恶意](../secret.md)')
        x = self.scan()
        self.assertNotIn('outside', json.dumps(x))
        self.assertEqual(x['条目'][0]['信号'][0]['状态'], '越界或符号链接，不读取')

    def test_symlink_not_followed(self):
        link = self.root / 'linked.md'
        try:
            link.symlink_to(self.root / 'AGENTS.md')
        except OSError:
            self.skipTest('宿主不允许创建符号链接')
        self.write('README.md', '[link](linked.md)')
        self.assertNotIn('linked.md', self.scan()['覆盖文件'])

    def test_archive_not_read_even_with_parent_components(self):
        self.write('归档-archive/private.md', 'DO_NOT_READ')
        self.write('AGENTS.md', '[历史](skills/../归档-archive/private.md)')
        x = self.scan()
        self.assertNotIn('DO_NOT_READ', json.dumps(x))

    def test_third_party_and_env_excluded(self):
        self.write('依赖-dependencies/x.md', 'do not scan')
        self.write('.env.md', 'SECRET')
        x = self.scan(scopes=['.'])
        self.assertNotIn('SECRET', json.dumps(x))
        self.assertNotIn('依赖-dependencies/x.md', x['覆盖文件'])

    def test_size_and_encoding_gaps_not_clean_success(self):
        self.write('README.md', 'x' * (r.MAX_BYTES + 1))
        (self.root / 'skills/a/bad.md').write_bytes(b'\xff')
        self.assertEqual(len(self.scan()['覆盖缺口']), 2)

    def test_cyclic_dependencies_terminate(self):
        self.write('skills/a/basis.md', '[back](../../AGENTS.md)')
        self.assertEqual(self.scan()['统计']['文件'], 3)

    def test_source_drift_rejects_stale_review(self):
        v = self.review(self.scan())
        self.write('skills/a/basis.md', 'changed')
        with self.assertRaisesRegex(ValueError, '来源'):
            r.review(self.store, v, self.day)
        self.assertEqual(self.store.list('退役审阅'), [])

    def test_missing_dependency_created_rejects_stale_review(self):
        self.write('AGENTS.md', '# 规则\n\n[说明](new.md)')
        v = self.review(self.scan())
        self.write('new.md', 'now exists')
        with self.assertRaisesRegex(ValueError, '来源'):
            r.review(self.store, v, self.day)

    def test_forged_quote_rejected(self):
        v = self.review(self.scan());v['来源摘录'][0]['摘录'] = 'fabricated'
        with self.assertRaisesRegex(ValueError, '摘录'):
            r.review(self.store, v, self.day)

    def test_wrong_identity_and_version_rejected(self):
        for key in ['条目', '绑定版本']:
            v = self.review(self.scan());v[key] = 'invalid'
            with self.assertRaises(ValueError):
                r.review(self.store, v, self.day)

    def test_incomplete_semantic_review_rejected(self):
        for key in ['依据', '适用条件与例外', '替代与消费者', '验证与边界']:
            v = self.review(self.scan());v[key] = ''
            with self.assertRaises(ValueError):
                r.review(self.store, v, self.day)

    def test_no_permanent_suppression(self):
        for due in ['2026-09-20', '2099-01-01']:
            v = self.review(self.scan());v['复审日期'] = due
            with self.assertRaises(ValueError):
                r.review(self.store, v, self.day)

    def test_no_delete_conclusion(self):
        v = self.review(self.scan());v['结论'] = '批准删除'
        with self.assertRaises(ValueError):
            r.review(self.store, v, self.day)

    def test_different_project_database_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            with self.assertRaisesRegex(ValueError, '项目隔离'):
                r.scan(other, store=self.store)

    def test_history_never_modified(self):
        r.review(self.store, self.review(self.scan(), '历史保留'), self.day)
        first = copy.deepcopy(self.store.list())
        self.write('skills/a/basis.md', 'changed')
        self.scan()
        for old in first:
            self.assertEqual(old, self.store.get(old['编号']))

    def test_changed_snapshot_reuses_unchanged_evidence(self):
        self.scan()
        self.write('skills/a/basis.md', 'changed')
        self.scan()
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM evidence').fetchone()[0], 4)

    def test_cli_readonly_never_creates_database(self):
        folder = Path(self.tmp.name) / 'absent'
        command = [sys.executable, '-B', str(ROOT / '工作台.py'), '--项目', str(self.root),
                   '--数据目录', str(folder), '退役巡检', '--只读']
        run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertFalse(folder.exists())
        self.assertEqual(json.loads(run.stdout)['统计']['文件'], 3)

    def test_cli_report_cannot_overwrite_source(self):
        p = self.root / 'AGENTS.md'; before = p.read_bytes()
        command = [sys.executable, '-B', str(ROOT / '工作台.py'), '--项目', str(self.root),
                   '退役巡检', '--输出', str(p)]
        run = subprocess.run(command, capture_output=True)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(p.read_bytes(), before)

    def test_python_is_evidence_not_guidance(self):
        self.write('AGENTS.md', '[实现](module.py)')
        self.write('module.py', 'print("not executed")')
        x = self.scan()
        self.assertIn('module.py', x['覆盖文件'])
        self.assertFalse(any(u['路径'] == 'module.py' for u in x['条目']))


if __name__ == '__main__':
    unittest.main()

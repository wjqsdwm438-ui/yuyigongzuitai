"""持续适配器：合成API回执，不把Mock通过称为真实定时运行。"""
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('retirement_watch', ROOT / '脚本-scripts/退役巡检持续运行.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class WatchTests(unittest.TestCase):
    def result(self):
        return {'扫描版本': 'fixed', '条目': [{'条目': 'a', '路径': 'AGENTS.md', '起始行': 3,
                '正文': 'PRIVATE-TEXT-DO-NOT-NOTIFY', '信号': [], '绑定版本': 'v1',
                '巡检状态': '待语义复核', '触发依据': 'initial'}],
                '统计': {'文件': 1, '确定性信号': 0}, '覆盖缺口': []}

    def test_notification_does_not_leak_source(self):
        body, state = w.notification(self.result(), 'owner/repo', '1')
        self.assertNotIn('PRIVATE-TEXT', body)
        self.assertIn('AGENTS.md:3', body)
        self.assertEqual(state, w.notification(self.result(), 'owner/repo', '2')[1])

    def test_unchanged_notification_never_writes(self):
        body, state = w.notification(self.result(), 'owner/repo', '1')
        with patch.object(w, 'gh', return_value=[[{'title': w.TITLE, 'body': body, 'number': 1}]]), patch.object(w.subprocess, 'run') as request:
            self.assertIn('未变化', w.publish('owner/repo', body, state))
            request.assert_not_called()

    def test_duplicate_index_stops_not_deletes(self):
        issue = {'title': w.TITLE, 'body': w.MARKER, 'number': 1}
        with patch.object(w, 'gh', return_value=[[issue, issue]]):
            with self.assertRaisesRegex(ValueError, '多个'):
                w.publish('owner/repo', 'body', 'state')

    def test_write_failure_propagates(self):
        with patch.object(w, 'gh', return_value=[[]]), patch.object(w.subprocess, 'run') as run:
            run.return_value.returncode = 1
            with self.assertRaisesRegex(RuntimeError, '失败'):
                w.publish('owner/repo', 'body', 'state')

    def test_expired_memory_explicit_fallback(self):
        with tempfile.TemporaryDirectory() as d, patch.object(w, 'gh', return_value={'artifacts': [{'expired': True}]}):
            self.assertIn('全量', w.restore('owner/repo', Path(d), 1))
            self.assertFalse(list(Path(d).iterdir()))

    def test_other_workflow_cannot_supply_memory(self):
        artifact = {'id': 1, 'expired': False, 'workflow_run': {'head_branch': 'main', 'id': 2}}
        run = {'workflow_id': 99, 'conclusion': 'success', 'head_repository': {'full_name': 'owner/repo'}}
        with tempfile.TemporaryDirectory() as d, patch.object(w, 'gh', side_effect=[{'artifacts': [artifact]}, run]):
            self.assertIn('全量', w.restore('owner/repo', Path(d), 1))

    def test_unsafe_archive_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('../code.py', 'malicious')
        artifact = {'id': 1, 'expired': False, 'workflow_run': {'head_branch': 'main', 'id': 2}}
        run = {'workflow_id': 1, 'conclusion': 'success', 'head_repository': {'full_name': 'owner/repo'}}
        with tempfile.TemporaryDirectory() as d, patch.object(w, 'gh', side_effect=[{'artifacts': [artifact]}, run, buf.getvalue()]):
            with self.assertRaisesRegex(ValueError, '结构'):
                w.restore('owner/repo', Path(d), 1)
            self.assertFalse(list(Path(d).iterdir()))

    def test_fork_and_pr_memory_ignored(self):
        artifact = {'id': 1, 'workflow_run': {'head_branch': 'feature', 'id': 2}}
        with tempfile.TemporaryDirectory() as d, patch.object(w, 'gh', return_value={'artifacts': [artifact]}) as api:
            self.assertIn('全量', w.restore('owner/repo', Path(d), 1))
            self.assertEqual(api.call_count, 1)

    def test_non_manual_event_fails_before_github_write_path(self):
        env = {'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF': 'refs/heads/main',
               'GITHUB_REPOSITORY': 'owner/repo', 'WORKBENCH_ISSUE_WRITE_APPROVED': 'true'}
        with tempfile.TemporaryDirectory() as d, patch.object(w, 'ROOT', Path(d)), \
             patch.dict(os.environ, env, clear=True), patch.object(sys, 'argv', ['watch']), \
             patch.object(w, 'gh', side_effect=AssertionError('不应调用 GitHub')):
            with self.assertRaisesRegex(ValueError, '手动'):
                w.main()

    def test_manual_event_requires_explicit_issue_approval(self):
        env = {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': 'refs/heads/main',
               'GITHUB_REPOSITORY': 'owner/repo', 'WORKBENCH_ISSUE_WRITE_APPROVED': 'false'}
        with tempfile.TemporaryDirectory() as d, patch.object(w, 'ROOT', Path(d)), \
             patch.dict(os.environ, env, clear=True), patch.object(sys, 'argv', ['watch']), \
             patch.object(w, 'gh', side_effect=AssertionError('不应调用 GitHub')):
            with self.assertRaisesRegex(ValueError, '授权'):
                w.main()

    def test_release_workflow_requires_manual_approval(self):
        text = (ROOT / '.github/workflows/workbench-validation.yml').read_text(encoding='utf-8')
        release = text[text.index('  release:'):]
        self.assertIn('publish_release:', text)
        self.assertIn("github.event_name == 'workflow_dispatch'", release)
        self.assertIn("github.ref == 'refs/heads/main'", release)
        self.assertIn('inputs.publish_release == true', release)
        self.assertNotIn("github.event_name == 'push'", release)

    def test_watch_workflow_has_only_manual_trigger(self):
        text = (ROOT / '.github/workflows/retirement-watch.yml').read_text(encoding='utf-8')
        triggers = text[text.index('on:'):text.index('permissions:')]
        self.assertIn('workflow_dispatch:', triggers)
        self.assertIn('write_issue:', triggers)
        self.assertNotIn('push:', triggers)
        self.assertNotIn('schedule:', triggers)


if __name__ == '__main__':
    unittest.main()

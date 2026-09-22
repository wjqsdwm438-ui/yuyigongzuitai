"""GitHub 手动远端巡检适配器；SQLite 是记忆，单个 Issue 仅是通知索引。"""
import argparse
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '源码-src'))
from 语义工作台.retirement import digest, scan
from 语义工作台.storage import Store

TITLE = '指导规则退役巡检｜待复核索引'
MARKER = '<!-- workbench-retirement-watch:v1 -->'


def gh(*args, binary=False):
    run = subprocess.run(['gh', *args], capture_output=True, timeout=180)
    if run.returncode:
        # 不回显环境、命令或服务端正文，避免凭据或材料进入日志。
        raise RuntimeError('GitHub 操作失败；请检查 Actions 权限和服务状态')
    return run.stdout if binary else json.loads(run.stdout)


def restore(repo, folder, workflow_id):
    """只接收本仓库、本工作流、main 成功运行的指定 SQLite 产物。"""
    artifacts = gh('api', f'repos/{repo}/actions/artifacts?name=retirement-state&per_page=100')['artifacts']
    for artifact in artifacts:
        if artifact.get('expired') or artifact.get('workflow_run', {}).get('head_branch') != 'main':
            continue
        run = gh('api', f"repos/{repo}/actions/runs/{artifact['workflow_run']['id']}")
        if run['workflow_id'] != workflow_id or run['conclusion'] != 'success' or run['head_repository']['full_name'] != repo:
            continue
        raw = gh('api', f"repos/{repo}/actions/artifacts/{artifact['id']}/zip", binary=True)
        if len(raw) > 64 * 1024 * 1024:
            raise ValueError('状态产物超过安全上限')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            if names != ['workbench.sqlite3'] or archive.getinfo(names[0]).file_size > 128 * 1024 * 1024:
                raise ValueError('状态产物结构不符，拒绝解压其他路径')
            with (folder / 'workbench.sqlite3').open('xb') as handle:
                handle.write(archive.read(names[0]))
        return '已恢复此前成功运行的项目库'
    return '无可用历史产物；全量重新复核，不推定任何旧处置'


def notification(result, repo, run_id):
    pending = [u for u in result['条目'] if u['巡检状态'] in {'待语义复核', '待授权处置'}]
    pending.sort(key=lambda u: (not bool(u['信号']), u['路径'], u['起始行']))
    state = digest([result['扫描版本'], [(u['条目'], u['绑定版本'], u['巡检状态'], u['触发依据']) for u in result['条目']]])
    lines = [MARKER, f'<!-- state:{state} -->', '# 指导规则待复核', '',
             f"扫描 {result['统计']['文件']} 个文件；待语义复核 {len(pending)} 段；确定性信号 {result['统计']['确定性信号']} 项。",
             '这不是退役批准。链接正常但指导失效的情形仍须按核心 Skill 进行语义审阅。',
             '本 Issue 只作单一通知索引；完整取证与历史保存在运行产物中的项目库，不提交源码。',
             '', '优先定位（最多五项，不公布原文）：']
    for u in pending[:5]:
        path = u['路径'].replace('@', '＠').replace('`', '')
        lines.append(f"- `{path}:{u['起始行']}`：" + ('有确定性信号，先查证' if u['信号'] else '需语义复核'))
    if result['覆盖缺口']:
        lines.append(f"覆盖缺口 {len(result['覆盖缺口'])} 项；本轮不可声称完整扫描。")
    lines.extend(['', f'运行与产物：https://github.com/{repo}/actions/runs/{run_id}',
                  '', '本地及云端库不自动合并；勿将通知关闭解释为业务规则批准。'])
    return '\n'.join(lines), state


def publish(repo, body, state):
    matches = gh('api', '--paginate', '--slurp', f'repos/{repo}/issues?state=all&per_page=100')
    found = [issue for page in matches for issue in page
             if not issue.get('pull_request') and issue.get('title') == TITLE and MARKER in (issue.get('body') or '')]
    if len(found) > 1:
        raise ValueError('存在多个通知索引，请先核实；不自动合并或删除')
    if found and f'<!-- state:{state} -->' in (found[0].get('body') or ''):
        return '未变化，不新建或刷新通知'
    payload = {'title': TITLE, 'body': body}
    if found:
        payload['state'] = 'open'
        endpoint, method = f"repos/{repo}/issues/{found[0]['number']}", 'PATCH'
    else:
        endpoint, method = f'repos/{repo}/issues', 'POST'
    process = subprocess.run(['gh', 'api', endpoint, '--method', method, '--input', '-'],
                             input=json.dumps(payload).encode(), capture_output=True, timeout=60)
    if process.returncode:
        raise RuntimeError('通知写入失败；未将失败视为完成')
    return '已更新唯一通知索引'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--离线', action='store_true', help='仅本地演练，不调用GitHub')
    args = parser.parse_args()
    folder = ROOT / '临时-tmp/retirement-ci'
    folder.mkdir(parents=True, exist_ok=True)
    status = '离线演练'
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    if not args.离线:
        if os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch':
            raise ValueError('持续巡检远端写入仅允许手动派发')
        if os.environ.get('GITHUB_REF') != 'refs/heads/main' or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ValueError('持续巡检仅允许本仓库 main，拒绝其他引用上下文')
        if os.environ.get('WORKBENCH_ISSUE_WRITE_APPROVED', '').lower() != 'true':
            raise ValueError('缺少本次 Issue 写入授权')
        workflow = gh('api', f'repos/{repo}/actions/workflows/retirement-watch.yml')
        status = restore(repo, folder, workflow['id'])
    store = Store(folder, project=ROOT)
    try:
        if store.db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('状态库完整性失败，停止而非静默清空')
        result = scan(ROOT, store=store, record=True)
    finally:
        store.close()
    output = ROOT / '导出-exports/retirement-ci'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'恢复': status, '统计': result['统计'], '覆盖缺口数': len(result['覆盖缺口'])}, ensure_ascii=False))
    if not args.离线:
        body, state = notification(result, repo, os.environ['GITHUB_RUN_ID'])
        print(publish(repo, body, state))
    if result['覆盖缺口']:
        raise SystemExit(3)


if __name__ == '__main__':
    main()

"""指导规则退役巡检：只读取证、版本绑定的复审队列；绝不改写或删除规则。"""
from __future__ import annotations

import hashlib
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .storage import encode

TEXT = {'.md', '.txt', '.yaml', '.yml', '.json', '.toml', '.py'}
EXCLUDED = {'.git', '.github', '.环境-venv', '.运行时-runtime', '数据-data', '导出-exports',
            '临时-tmp', '临时-tests', '归档-archive', '治理-governance', '依赖-dependencies',
            'node_modules', '__pycache__', 'feishu', '测试-tests', 'tests'}
MAX_FILES = 500
MAX_BYTES = 512 * 1024
LINK = re.compile(r'(?<!!)\[[^\]\n]+\]\(([^\n)]+)\)')
INLINE = re.compile(r'`([^`\n]+\.(?:md|txt|ya?ml|json|toml|py)(?:#[^`\n]*)?)`')
METADATA = re.compile(r'^\s*(?:instructions|prompt|file|path|入口|正文|参考)\s*[:=]\s*[\"\']?([^\"\'\n]+\.(?:md|txt|ya?ml|json|toml))', re.M)
REFERENCE = re.compile(r'^\s*\[[^\]]+\]:\s*(\S+)', re.M)
BOUNDARY = ('确定性信号不是退役结论；待语义复核必须由已加载核心 Skill 的智能体核实。'
            '未调用模型、未批准业务变更、未移动或删除文件；零信号不等于零过时规则。')


def digest(value):
    return hashlib.sha256(encode(value).encode('utf-8')).hexdigest()


def _safe(root, relative):
    path = root / relative
    # 符号链接即使指向项目内也不读取，避免平台差异与扫描期间换链。
    if path.is_absolute() and not path.is_relative_to(root):
        raise ValueError('路径越界')
    if any(p.is_symlink() for p in [path, *path.parents] if p.is_relative_to(root)):
        raise ValueError('不读取符号链接')
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('路径越界')
    return resolved


def _excluded(relative):
    parts = Path(relative).parts
    return any(p in EXCLUDED or p.startswith('.env') for p in parts)


def _anchors(text):
    counts, result = {}, set()
    for line in text.splitlines():
        match = re.match(r'^#{1,6}\s+(.+?)\s*#*$', line)
        if not match:
            continue
        label = re.sub(r'[^\w\-\s]', '', match[1].lower()).strip().replace(' ', '-')
        n = counts.get(label, 0)
        counts[label] = n + 1
        result.add(label + (f'-{n}' if n else ''))
    # 显式 HTML id；这里只作定位，不执行 HTML。
    result.update(re.findall(r'\bid=["\']([^"\']+)["\']', text))
    return result


def _links(relative, text):
    for regex, inline in ((LINK, False), (REFERENCE, False), (INLINE, True), (METADATA, False)):
        for match in regex.finditer(text):
            raw = match[1].strip().strip('<>')
            if not inline:
                raw = re.split(r'\s+["\']', raw, maxsplit=1)[0]
            if '<' in raw or '>' in raw or '*' in raw:
                continue  # 参数模板不是实际文件。
            parsed = urlsplit(raw.replace('\\', '/'))
            if parsed.scheme or parsed.netloc or raw.startswith(('/', '~')):
                continue  # 不跟随网页、盘符、网络共享或项目外路径。
            target = unquote(parsed.path)
            rel = str(Path(relative).parent / target) if target else relative
            # 行内代码中的根入口名称允许根目录定位；普通 Markdown 不猜路径。
            yield {'目标': rel, '锚点': unquote(parsed.fragment), '原文': raw,
                   '行': text[:match.start()].count('\n') + 1, '行内': inline}


def _units(relative, text):
    """保留整段及所属标题；不将并且、例外、代码块拆成可独立删除的规则。"""
    heading, start, block, fence, slots = [], 1, [], False, {}

    def item():
        body = '\n'.join(block).strip()
        if not body:
            return None
        section = ' / '.join(heading) or '文件头'
        title_path = tuple(heading)
        slot = slots.get(title_path, 0)
        slots[title_path] = slot + 1
        # 身份只绑定位置；正文及整条依赖链由绑定版本负责，使同位改文能续接且强制复审。
        identity = digest([relative, list(title_path), slot])
        return {'条目': '指导-' + identity[:24], '路径': relative, '标题': section,
                '标题路径': list(title_path), '段落序号': slot, '起始行': start, '正文': body}

    for number, line in enumerate(text.splitlines(), 1):
        title = re.match(r'^(#{1,6})\s+(.+?)\s*#*\s*$', line) if not fence else None
        if title or (not line.strip() and not fence):
            result = item()
            if result:
                yield result
            block = []
            if title:
                level = len(title[1])
                heading = heading[:level - 1] + [title[2]]
            continue
        if not block:
            start = number
        block.append(line)
        if re.match(r'^\s*(```|~~~)', line):
            fence = not fence
    result = item()
    if result:
        yield result


def collect(project, scopes=None):
    root = Path(project).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('项目必须是目录')
    selected = []
    if scopes:
        for scope in scopes:
            path = _safe(root, scope)
            if not path.exists():
                raise ValueError('指定范围不存在：' + str(scope))
            selected.extend(path.rglob('*') if path.is_dir() else [path])
    else:
        selected = [root / name for name in ('README.md', 'AGENTS.md', 'CLAUDE.md') if (root / name).exists()]
        for dirname in ('skills', 'agents', '.agents'):
            folder = root / dirname
            if folder.is_dir() and not folder.is_symlink():
                selected.extend(folder.rglob('*'))
        selected.extend(root.rglob('AGENTS.md'))
    queue = sorted(set(str(p.relative_to(root)) for p in selected if p.suffix.lower() in TEXT))
    files, gaps, visited = {}, [], set()
    while queue:
        relative = queue.pop(0)
        if relative in visited:
            continue
        visited.add(relative)
        if _excluded(relative):
            continue
        if len(files) >= MAX_FILES:
            gaps.append({'路径': relative, '原因': '扫描文件数上限，需缩小范围'})
            break
        try:
            path = _safe(root, relative)
            relative = path.relative_to(root).as_posix()
            if _excluded(relative):
                continue
            if relative in files or not path.is_file() or path.suffix.lower() not in TEXT:
                continue
            if path.stat().st_size > MAX_BYTES:
                raise ValueError('文件超过512KiB，未截断冒充完整读取')
            raw = path.read_bytes()
            text = raw.decode('utf-8-sig')
            files[relative] = {'内容': text, '版本': hashlib.sha256(raw).hexdigest(), '引用': []}
            for link in _links(relative, text):
                try:
                    target = _safe(root, link['目标'])
                    if link['行内'] and not target.exists():
                        candidate = _safe(root, unquote(urlsplit(link['原文']).path))
                        if candidate.exists():
                            target = candidate
                    target_rel = target.relative_to(root).as_posix()
                    link['目标'] = target_rel
                    if _excluded(target_rel):
                        link['状态'] = '排除域，仅保留指针，不读取'
                    elif not target.exists():
                        link['状态'] = '名称待定位' if link['行内'] and '/' not in link['原文'] else '断链候选'
                    elif not target.is_file():
                        link['状态'] = '目录'
                    elif target.suffix.lower() not in TEXT:
                        link['状态'] = '非文本，不读取'
                    else:
                        link['状态'] = '存在'
                        if target_rel not in visited:
                            queue.append(target_rel)
                except (ValueError, OSError):
                    link['状态'] = '越界或符号链接，不读取'
                files[relative]['引用'].append(link)
        except (ValueError, OSError, UnicodeError) as error:
            gaps.append({'路径': relative, '原因': str(error)})
    for file in files.values():
        for link in file['引用']:
            target = files.get(link['目标'])
            if target and re.search(r'^\s*(?:状态|status)\s*[:：]\s*(?:已退役|已停用|retired|deprecated)\s*$', '\n'.join(target['内容'].splitlines()[:20]), re.M | re.I):
                link['状态'] = '目标明示退役，检查活动引用'
            if target and link['锚点'] and link['锚点'] not in _anchors(target['内容']):
                link['状态'] = '锚点待核实'  # GitHub 方言不全，绝不直接退役。
    return root, files, gaps


def scan(project, scopes=None, store=None, today=None, record=False):
    today = today or date.today()
    root, files, gaps = collect(project, scopes)
    if store is not None and store.project != str(root).casefold():
        raise ValueError('项目隔离：巡检库不属于当前项目')
    reviews = store.list('退役审阅') if store is not None else []
    previous = {r['内容']['条目']: r['内容'] for r in reviews}
    units = []
    for relative, file in sorted(files.items()):
        if Path(relative).suffix.lower() == '.py':
            continue  # 源码作为依据，不把 Python 段落误当指导规则。
        # 整条依赖链参与版本判定，不只检查指针文件自身。
        dependencies, pending = {}, [relative]
        while pending:
            name = pending.pop()
            if name in dependencies:
                continue
            target = files.get(name)
            dependencies[name] = target['版本'] if target else '缺失或排除'
            if target:
                pending.extend(link['目标'] for link in target['引用'] if link['状态'] not in {'目录', '非文本，不读取'})
        version = digest(dependencies)
        for unit in _units(relative, file['内容']):
            signals = [dict(link) for link in file['引用'] if unit['起始行'] <= link['行'] < unit['起始行'] + len(unit['正文'].splitlines())
                       and link['状态'] in {'断链候选', '锚点待核实', '越界或符号链接，不读取', '目标明示退役，检查活动引用'}]
            old = previous.get(unit['条目'])
            state = '待语义复核'
            cause = '首次纳入；含义是否过时不能由链接状态判定'
            if old and old['绑定版本'] != version:
                cause = '正文或关联依据变化，旧处置不再压制复审'
            elif old and date.fromisoformat(old['复审日期']) <= today:
                cause = '复审到期'
            elif old:
                state = '待授权处置' if old['结论'] == '建议退役' else '已记录待到期'
                cause = old['结论']
            units.append(dict(unit, 绑定版本=version, 依据版本=dependencies,
                              信号=signals, 巡检状态=state, 触发依据=cause))
    signature = digest({'文件': {p: f['版本'] for p, f in files.items()}, '缺口': gaps,
                        '范围': list(map(str, scopes or []))})
    result = {'版本': 1, '项目': str(root), '扫描日期': today.isoformat(), '扫描版本': signature,
              '范围': list(map(str, scopes or [])), '覆盖文件': list(files), '覆盖缺口': gaps, '条目': units, '边界': BOUNDARY,
              '统计': {'文件': len(files), '指导段落': len(units),
                       '待语义复核': sum(u['巡检状态'] == '待语义复核' for u in units),
                       '待授权处置': sum(u['巡检状态'] == '待授权处置' for u in units),
                       '确定性信号': sum(len(u['信号']) for u in units)}, '业务授权': False}
    if store is None or not record:
        return result
    if not files:
        raise ValueError('未读取到材料，不创建空的巡检成功记录')
    with store.atomic():
        snapshots = store.list('退役巡检')
        same = next((r for r in reversed(snapshots) if r['内容']['摘要'] == signature), None)
        if same:
            result['巡检'] = same['编号']
        else:
            sources = []
            known = {e['来源']: e for r in snapshots[-1:] for ident in r['内容']['来源证据']
                     for e in [store.evidence(ident)]}
            for relative, file in files.items():
                # 存证前再读一遍，拒绝扫描期间漂移。
                path = _safe(root, relative)
                if hashlib.sha256(path.read_bytes()).hexdigest() != file['版本']:
                    raise ValueError('扫描期间来源变化，请重新巡检')
                old = known.get(str(path))
                sources.append(old['编号'] if old and old['摘要'] == file['版本']
                               else store.capture(path))
            result['巡检'] = store.add('退役巡检', {'问题': '指导规则退役巡检', '摘要': signature,
                '来源证据': sources, '产物': result})
    return result


def review(store, value, today=None):
    """保存有原文依据的助手审阅，不升级为业务批准或文件动作。"""
    today = today or date.today()
    if not isinstance(value, dict):
        raise ValueError('审阅必须为对象')
    with store.atomic():
        snapshot = store.require_ref(value.get('巡检'), '退役巡检')
        unit = next((u for u in snapshot['内容']['产物']['条目'] if u['条目'] == value.get('条目')), None)
        if not unit or value.get('绑定版本') != unit['绑定版本']:
            raise ValueError('条目或绑定版本不匹配')
        if value.get('结论') not in {'保留有效', '建议退役', '历史保留', '证据不足'}:
            raise ValueError('未知审阅结论；不支持批准删除')
        for key in ('依据', '适用条件与例外', '替代与消费者', '验证与边界'):
            if not isinstance(value.get(key), str) or not value[key].strip():
                raise ValueError('缺少语义审阅项：' + key)
        due = value.get('复审日期', (today + timedelta(days=7 if value['结论'] == '证据不足' else 30)).isoformat())
        if not today < date.fromisoformat(due) <= today + timedelta(days=90):
            raise ValueError('复审日期必须在未来90天内，不能永久压制')
        current = scan(snapshot['内容']['产物']['项目'], snapshot['内容']['产物']['范围'])
        if current['扫描版本'] != snapshot['内容']['摘要']:
            raise ValueError('来源或范围变化，重新巡检；旧快照保留')
        evidence = {e: store.evidence(e, current=True) for e in snapshot['内容']['来源证据']}
        if any(not e['当前来源一致'] for e in evidence.values()):
            raise ValueError('来源变化，重新巡检；旧快照保留')
        quotes = value.get('来源摘录')
        if not isinstance(quotes, list) or not quotes:
            raise ValueError('必须提供真实来源摘录')
        root = Path(snapshot["内容"]["产物"]["项目"])
        used = []
        for q in quotes:
            if not isinstance(q, dict) or not isinstance(q.get('摘录'), str) or not q['摘录'].strip():
                raise ValueError('摘录无效')
            matched = next((e for e in evidence.values() if Path(e['来源']).relative_to(root).as_posix() == q.get('路径')), None)
            if not matched or q['摘录'].replace('\r\n', '\n') not in matched['历史内容'].replace('\r\n', '\n'):
                raise ValueError('来源摘录不在本次原件')
            used.append(matched['编号'])
        if not any(q.get('路径') == unit['路径'] and q['摘录'] in unit['正文'] for q in quotes):
            raise ValueError('必须引用被审条目本身，不能只引用其他文件')
        payload = dict(value, 复审日期=due, 来源证据=list(dict.fromkeys(used)), 问题='指导规则语义复审')
        prior = [r for r in store.list('退役审阅') if r['内容']['条目'] == unit['条目']]
        comparable = ('巡检', '条目', '绑定版本', '结论', '依据', '适用条件与例外', '替代与消费者', '验证与边界', '复审日期', '来源摘录')
        if prior and all(prior[-1]['内容'].get(k) == payload.get(k) for k in comparable):
            return prior[-1]
        ident = store.add('退役审阅', payload)
        return store.get(ident)


def template(result, unit=None):
    pending = next((u for u in result['条目'] if u['巡检状态'] == '待语义复核'), None)
    unit = unit or pending
    if not unit or not result.get('巡检'):
        return None
    return {'巡检': result['巡检'], '条目': unit['条目'], '绑定版本': unit['绑定版本'],
            '结论': '证据不足', '依据': '', '适用条件与例外': '', '替代与消费者': '',
            '验证与边界': '', '来源摘录': [{'路径': unit['路径'], '摘录': unit['正文']}]}


def report(result):
    lines = ['# 指导规则退役巡检', '', f"文件 {result['统计']['文件']}；指导段落 {result['统计']['指导段落']}；"
             f"待语义复核 {result['统计']['待语义复核']}；确定性信号 {result['统计']['确定性信号']}。", '', BOUNDARY]
    pending = [u for u in result['条目'] if u['巡检状态'] in {'待语义复核', '待授权处置'}]
    pending.sort(key=lambda u: (not bool(u['信号']), u['触发依据'].startswith('首次'), u['路径'], u['起始行']))
    for u in pending[:5]:
        lines.extend(['', f"## {u['路径']}:{u['起始行']} · {u['标题']}",
                      '问题：' + ('；'.join(s['状态'] + '：' + s['原文'] for s in u['信号']) or '指导含义待复审'),
                      '依据：' + u['触发依据'], '推荐：核对当前适用条件、权威依据及活动消费者；提交语义审阅。',
                      '是否需要你决定：目前由智能体补核；发现实质取舍时才交用户。'])
    if result['覆盖缺口']:
        lines.extend(['', '覆盖不完整：' + encode(result['覆盖缺口'])])
    return '\n'.join(lines) + '\n'

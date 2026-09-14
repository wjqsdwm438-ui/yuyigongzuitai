"""检查安装引用与显式调用策略；不代替模型行为回放。"""
import argparse
import re
from pathlib import Path


def check(source, entry):
    source, entry = Path(source).resolve(), Path(entry).resolve()
    for directory in (source, entry):
        text = (directory / 'SKILL.md').read_text(encoding='utf-8')
        assert text.startswith('---\n'), f'缺少元信息：{directory}'
        policy = (directory / 'agents/openai.yaml').read_text(encoding='utf-8')
        assert re.search(r'^\s*allow_implicit_invocation:\s*false\s*$', policy, re.M), f'非显式调用：{directory}'
    text = (entry / 'SKILL.md').read_text(encoding='utf-8')
    links = re.findall(r'\]\(([^)]+/SKILL\.md)\)', text)
    resolved = [(entry / link).resolve() for link in links if not re.match(r'https?://', link)]
    assert source / 'SKILL.md' in resolved, '入口未引用目标技能'
    for target in resolved:
        # 可选格式层是已知缺失依赖，其状态由行为测试检查。
        if target.parent.name != '任务表示':
            assert target.is_file(), f'失效引用：{target}'
    print('入口引用、UTF-8 和显式调用策略通过；语义行为需另行审阅。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--entry', required=True)
    args = parser.parse_args()
    check(args.source, args.entry)

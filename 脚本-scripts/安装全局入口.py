"""安装已获用户批准的轻量技能入口；不覆盖既有技能，不复制核心代码。"""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / "skills/全局入口-entry/SKILL.md"
    data = source.read_bytes()
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()
    directory = home / "skills/语义规则工作台-workbench"
    target = directory / "SKILL.md"
    if target.exists():
        if target.read_bytes() != data:
            raise ValueError("全局入口已存在且内容不同，拒绝覆盖：" + str(target))
    else:
        if directory.exists():
            raise ValueError("目标目录已存在但没有相同入口，拒绝接管")
        directory.mkdir(parents=True)
        with target.open("xb") as stream:
            stream.write(data)
    assert target.read_bytes() == data
    result = {"技能名": "semantic-rule-workbench", "中文名称": "语义规则工作台",
              "全局入口": str(target), "核心源码": str(ROOT),
              "SHA256（摘要）": hashlib.sha256(data).hexdigest(),
              "安装范围": "仅轻量SKILL.md；未改PATH（程序搜索路径）、未复制核心代码、未修改项目业务规则"}
    (ROOT / "说明-docs/全局入口安装记录.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

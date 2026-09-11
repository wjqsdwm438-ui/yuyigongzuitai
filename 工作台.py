"""无需安装的本地入口。"""
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
environment = ROOT / ".环境-venv"
python = environment / "Scripts/python.exe"
if __name__ == "__main__" and python.is_file() and Path(sys.prefix).resolve() != environment.resolve():
    # 仅转交项目专属解释器，避免用户误用缺组件的宿主环境；不拼接Shell命令。
    raise SystemExit(subprocess.call([str(python), "-X", "utf8", "-B", str(Path(__file__).resolve()), *sys.argv[1:]]))
sys.path.insert(0, str(ROOT / "源码-src"))
from 语义工作台.cli import main

if __name__ == "__main__":
    main()

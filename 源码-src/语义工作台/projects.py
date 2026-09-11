"""按规范化项目路径分库；这是应用隔离，不是操作系统用户访问控制。"""
import hashlib
from pathlib import Path
from .storage import Store

ROOT = Path(__file__).resolve().parents[2]


def canonical(project):
    path = Path(project).resolve(strict=True)
    if not path.is_dir():
        raise ValueError("项目必须是目录")
    return str(path).casefold()


def project_data(project):
    key = hashlib.sha256(canonical(project).encode("utf-8")).hexdigest()[:32]
    return ROOT / "数据-data/项目-projects" / key


def open_project(project, directory=None, readonly=False):
    canonical(project)
    return Store(directory or project_data(project), project=project, readonly=readonly)


def reference_project(current, other, record_id=None):
    if canonical(current) == canonical(other):
        raise ValueError("参考项目与当前项目相同，请使用本项目回查")
    store = open_project(other, readonly=True)
    try:
        if record_id:
            from .workflow import decision_report
            content = decision_report(store, record_id)
        else:
            content = [{"编号": r["编号"], "类型": r["类型"],
                        "标题": r["内容"].get("标题", r["内容"].get("问题", r["内容"].get("处置", "")))}
                       for r in store.list() if r["类型"] in {"案例", "决定", "处理任务"}]
        return {"当前项目": canonical(current), "参考项目": canonical(other), "外部参考": content,
                "性质": "显式跨项目只读参考；未导入当前项目，不成为本项目规则或批准",
                "业务授权": False}
    finally:
        store.close()

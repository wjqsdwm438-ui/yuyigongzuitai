"""仓库治理的安全执行核：盘点、预演、执行与恢复。

语义分类由人或智能体给出；本模块只校验依据和边界，并执行确定性的文件动作。
"""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


TEST_CLASSES = {
    "有效正面案例",
    "具有明确失败机制的反面案例",
    "仍有诊断价值的负面结果",
    "重复或无效垃圾",
    "证据不足的未知材料",
}
ACTIONS = {"保留", "归档", "删除", "待确认"}
LIFECYCLES = {"活动", "历史", "退役", "可再生", "未知"}
EVIDENCE_STRENGTHS = {"强", "中", "弱", "未知"}
GOVERNANCE_EVIDENCE_FIELDS = (
    "生产者", "活动消费者", "消费者检查依据", "路径所有者", "生命周期", "证据强度",
)
DEFAULT_EXCLUDES = {
    ".git", ".环境-venv", ".运行时-runtime", "数据-data", "导出-exports",
    "临时-tmp", "临时-tests", "归档-archive", "__pycache__",
}


def _inside(root: Path, value: str | Path) -> Path:
    root = root.resolve()
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"路径越出项目根：{value}") from error
    return candidate


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_id(root: Path, operations: list[dict]) -> str:
    canonical = json.dumps(operations, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((str(root.resolve()) + canonical).encode("utf-8")).hexdigest()[:16]


def inventory(project_root: str | Path, scopes: list[str] | None = None) -> dict:
    """盘点活动区；归档区和运行时目录默认不进入上下文。"""
    root = Path(project_root).resolve()
    bases = [_inside(root, item) for item in scopes] if scopes else [root]
    files: list[Path] = []
    for base in bases:
        if not base.exists():
            continue
        candidates = [base] if base.is_file() else base.rglob("*")
        for path in candidates:
            if not path.is_file():
                continue
            relative_parts = path.resolve().relative_to(root).parts
            if any(part in DEFAULT_EXCLUDES for part in relative_parts):
                continue
            files.append(path)

    suffixes = Counter((path.suffix.lower() or "[无扩展名]") for path in files)
    signals = ("旧", "历史", "废弃", "退役", "备份", "copy", "old", "legacy", "deprecated", "obsolete")
    retirement_candidates = [
        _relative(root, path) for path in files
        if any(signal in path.name.lower() for signal in signals)
    ]
    test_signals = ("test", "trial", "测试", "验证", "probe", "baseline")
    test_candidates = [
        _relative(root, path) for path in files
        if any(signal in _relative(root, path).lower() for signal in test_signals)
    ]
    stage_signals = ("candidate", "候选", "current", "最终", "final", "backup", "备份")
    stage_candidates = [
        _relative(root, path) for path in files
        if any(signal in _relative(root, path).lower() for signal in stage_signals)
    ]
    python_hints = []
    for path in files:
        if path.suffix.lower() != ".py":
            continue
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            count = sum(1 for _ in stream)
        if count > 500:
            python_hints.append({"路径": _relative(root, path), "行数": count, "性质": "职责复核提示"})

    return {
        "项目": str(root),
        "活动文件数": len(files),
        "活动总字节": sum(path.stat().st_size for path in files),
        "扩展名分布": dict(suffixes.most_common()),
        "退役信号候选": sorted(retirement_candidates),
        "测试材料候选数": len(test_candidates),
        "测试材料候选样本": sorted(test_candidates)[:100],
        "阶段与版本候选数": len(stage_candidates),
        "阶段与版本候选样本": sorted(stage_candidates)[:100],
        "运行产物提示": {
            "编译缓存_nbc_nbi": sum(suffixes.get(ext, 0) for ext in (".nbc", ".nbi")),
            "日志_log": suffixes.get(".log", 0),
            "音频_wav": suffixes.get(".wav", 0),
            "边界": "数量只用于安排治理批次，不直接授权归档或删除。",
        },
        "默认排除归档": "归档-archive",
        "Python提示": sorted(python_hints, key=lambda item: item["行数"], reverse=True),
        "Python指标边界": "行数只触发职责复核，不能单凭行数判定职责有问题。",
        "业务授权": False,
    }


def cache_manifest(project_root: str | Path, scopes: list[str] | None = None) -> dict:
    """生成可重建编译缓存的逐文件候选清单，不执行删除。"""
    root = Path(project_root).resolve()
    bases = [_inside(root, item) for item in scopes] if scopes else [root]
    selected: list[Path] = []
    for base in bases:
        if not base.exists():
            continue
        candidates = [base] if base.is_file() else base.rglob("*")
        for path in candidates:
            if not path.is_file() or path.suffix.lower() not in {".nbc", ".nbi"}:
                continue
            parts = path.resolve().relative_to(root).parts
            if any(part in DEFAULT_EXCLUDES for part in parts):
                continue
            if "cache" not in {part.lower() for part in parts[:-1]}:
                continue
            selected.append(path)
    return {
        "版本": 1,
        "归档根": "归档-archive",
        "生成说明": "仅选择 cache 目录内可由 Numba 重建的 .nbc/.nbi；仍须经过治理预演和精确编号批准。",
        "条目": [
            {
                "路径": _relative(root, path),
                "材料类型": "运行缓存",
                "分类": "重复或无效垃圾",
                "动作": "删除",
                "依据": "位于 cache 目录的 Numba 编译缓存；脚本会建立缓存目录并在需要时重新编译，单个缓存文件不是事实、规则或恢复来源。",
                "生产者": "Numba 编译缓存",
                "活动消费者": [],
                "消费者检查依据": "运行代码按需重新编译；没有活动入口把单个 .nbc/.nbi 文件作为事实或输入。",
                "路径所有者": "产生该缓存的运行流程",
                "生命周期": "可再生",
                "证据强度": "强",
                "不影响恢复": True,
            }
            for path in sorted(selected)
        ],
    }


def preview(project_root: str | Path, manifest: dict) -> dict:
    """把语义清单编译为带哈希、冲突检查和恢复边界的执行计划。"""
    root = Path(project_root).resolve()
    archive_root = _inside(root, manifest.get("归档根", "归档-archive"))
    reasons: list[str] = []
    operations: list[dict] = []
    seen_sources: set[Path] = set()
    seen_targets: set[Path] = set()

    if manifest.get("版本") != 1:
        reasons.append("仅支持清单版本 1")
    for index, item in enumerate(manifest.get("条目", []), 1):
        label = f"条目 {index}"
        try:
            source = _inside(root, item["路径"])
        except (KeyError, ValueError) as error:
            reasons.append(f"{label}：{error}")
            continue
        action = item.get("动作")
        classification = item.get("分类")
        if action not in ACTIONS:
            reasons.append(f"{label}：未知动作 {action}")
        if item.get("材料类型") == "测试材料" and classification not in TEST_CLASSES:
            reasons.append(f"{label}：测试材料缺少规定的五类分类")
        if not str(item.get("依据", "")).strip():
            reasons.append(f"{label}：缺少具体依据")
        if classification == "证据不足的未知材料" and action not in {"待确认", "保留"}:
            reasons.append(f"{label}：未知材料只能待确认或保留")
        if action in {"归档", "删除"}:
            for field in GOVERNANCE_EVIDENCE_FIELDS:
                if field not in item:
                    reasons.append(f"{label}：缺少治理证据字段 {field}")
            for field in ("生产者", "消费者检查依据", "路径所有者"):
                if field in item and not str(item.get(field, "")).strip():
                    reasons.append(f"{label}：{field}不能为空")
            consumers = item.get("活动消费者")
            if "活动消费者" in item and not isinstance(consumers, list):
                reasons.append(f"{label}：活动消费者必须是列表")
            elif isinstance(consumers, list) and consumers:
                reasons.append(f"{label}：仍有活动消费者，不能{action}")
            lifecycle = item.get("生命周期")
            if "生命周期" in item and lifecycle not in LIFECYCLES:
                reasons.append(f"{label}：未知生命周期 {lifecycle}")
            strength = item.get("证据强度")
            if "证据强度" in item and strength not in EVIDENCE_STRENGTHS:
                reasons.append(f"{label}：未知证据强度 {strength}")
            elif strength in {"弱", "未知"}:
                reasons.append(f"{label}：证据强度不足，不能{action}")
        if action == "删除":
            if classification != "重复或无效垃圾":
                reasons.append(f"{label}：只有重复或无效垃圾可以进入删除预演")
            if item.get("不影响恢复") is not True:
                reasons.append(f"{label}：删除前必须确认不影响恢复")
        if not source.is_file():
            reasons.append(f"{label}：源文件不存在或不是文件：{item.get('路径')}")
            continue
        if source in seen_sources:
            reasons.append(f"{label}：源文件重复出现")
        seen_sources.add(source)

        target = None
        if action == "归档":
            try:
                target = _inside(root, item["目标"])
            except (KeyError, ValueError) as error:
                reasons.append(f"{label}：{error}")
                continue
            try:
                target.relative_to(archive_root)
            except ValueError:
                reasons.append(f"{label}：归档目标必须位于 {_relative(root, archive_root)}")
            if target.exists():
                reasons.append(f"{label}：目标已存在：{_relative(root, target)}")
            if target in seen_targets:
                reasons.append(f"{label}：多个条目使用同一目标")
            seen_targets.add(target)

        if action in {"归档", "删除"}:
            operations.append({
                "序号": index,
                "动作": action,
                "源": _relative(root, source),
                "目标": _relative(root, target) if target else None,
                "SHA256": _hash(source),
                "字节": source.stat().st_size,
                "材料类型": item.get("材料类型"),
                "分类": classification,
                "依据": item.get("依据"),
                "生产者": item.get("生产者"),
                "活动消费者": item.get("活动消费者"),
                "消费者检查依据": item.get("消费者检查依据"),
                "路径所有者": item.get("路径所有者"),
                "生命周期": item.get("生命周期"),
                "证据强度": item.get("证据强度"),
            })

    # 源与目标互相覆盖属于跨条目冲突，即使当前目标尚不存在也必须停止。
    if seen_sources.intersection(seen_targets):
        reasons.append("动作冲突：某个目标同时是另一条目的源")
    operation_kinds = {item["动作"] for item in operations}
    if {"归档", "删除"}.issubset(operation_kinds):
        reasons.append("归档与删除必须分开预演，避免不可恢复动作破坏归档回滚边界")
    plan_id = _plan_id(root, operations)
    return {
        "版本": 1,
        "项目": str(root),
        "预演编号": plan_id,
        "生成时间": _now(),
        "状态": "已阻止" if reasons else "可执行",
        "动作数": len(operations),
        "动作": operations,
        "冲突与阻止原因": reasons,
        "恢复边界": "归档移动可凭执行回执恢复；删除不可恢复，必须用本次预演编号单独批准。",
        "业务授权": False,
    }


def apply_plan(project_root: str | Path, plan: dict, delete_approval: str | None = None) -> dict:
    """执行已通过的预演；任何漂移先整体停止，移动失败时回滚已完成的移动。"""
    root = Path(project_root).resolve()
    if str(root) != str(Path(plan.get("项目", "")).resolve()):
        raise ValueError("预演所属项目与当前项目不一致")
    if plan.get("状态") != "可执行" or plan.get("冲突与阻止原因"):
        raise ValueError("预演存在冲突或阻止原因，不可执行")
    operations = plan.get("动作", [])
    if plan.get("预演编号") != _plan_id(root, operations):
        raise ValueError("预演编号与动作清单不一致，必须重新预演")
    if any(item["动作"] == "删除" for item in operations) and delete_approval != plan.get("预演编号"):
        raise ValueError("删除需要用本次预演编号明确批准删除")

    resolved = []
    for item in operations:
        source = _inside(root, item["源"])
        target = _inside(root, item["目标"]) if item.get("目标") else None
        if not source.is_file() or _hash(source) != item["SHA256"]:
            raise ValueError(f"源文件在预演后已变化：{item['源']}")
        if target and target.exists():
            raise ValueError(f"目标在预演后被占用：{item['目标']}")
        resolved.append((item, source, target))

    completed_moves = []
    completed = []
    try:
        for item, source, target in resolved:
            if item["动作"] == "归档":
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
                completed_moves.append((source, target))
            else:
                source.unlink()
            completed.append(item)
    except OSError:
        for source, target in reversed(completed_moves):
            if target.exists() and not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
        raise

    return {
        "版本": 1,
        "项目": str(root),
        "预演编号": plan["预演编号"],
        "执行时间": _now(),
        "状态": "已执行",
        "动作": completed,
        "恢复边界": (
            f"归档移动 {sum(i['动作'] == '归档' for i in completed)} 项可凭本回执恢复；"
            f"删除 {sum(i['动作'] == '删除' for i in completed)} 项不可恢复"
        ),
        "执行依据": {
            "预演编号": plan["预演编号"],
            "删除批准预演编号": delete_approval if any(i["动作"] == "删除" for i in completed) else None,
        },
    }


def restore(project_root: str | Path, receipt: dict) -> dict:
    """仅恢复归档移动；删除动作从不伪装成可恢复。"""
    root = Path(project_root).resolve()
    if str(root) != str(Path(receipt.get("项目", "")).resolve()):
        raise ValueError("回执所属项目与当前项目不一致")
    moves = [item for item in receipt.get("动作", []) if item.get("动作") == "归档"]
    checked = []
    for item in moves:
        original = _inside(root, item["源"])
        archived = _inside(root, item["目标"])
        if original.exists():
            raise ValueError(f"原位置已被占用：{item['源']}")
        if not archived.is_file() or _hash(archived) != item["SHA256"]:
            raise ValueError(f"归档文件缺失或已变化：{item['目标']}")
        checked.append((original, archived))
    for original, archived in reversed(checked):
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(archived), str(original))
    return {
        "状态": "已恢复",
        "恢复数": len(checked),
        "未恢复删除数": len(receipt.get("动作", [])) - len(moves),
        "执行依据": {"原执行预演编号": receipt.get("预演编号")},
    }

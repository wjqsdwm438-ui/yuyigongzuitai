# -*- coding: utf-8 -*-
"""中文规则检查 v0 机械测试与公开控制回归（工程演练）。

运行：python 测试-tests/test_rule_linter_v0.py [--report DIR]
公开控制夹具仅供工程回归，不承担检测效度或泛化证明。
发布副本将本地真实业务夹具换为合成例子，不包含其原文。
阳性计分 = 每类预期位点全部命中：类别正确、具体词项、与预期区间相交、
完全落在预标最小完整分句内；仅“任一相交”不通过。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "脚本-scripts" / "中文规则检查_v0.py"
DIMENSIONS = ["联合关系", "禁令", "模态", "条件方向", "范围", "量词", "例外"]


def load_module():
    spec = importlib.util.spec_from_file_location("rule_linter_v0", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


linter = load_module()

POSITIVES = [
    {"id": "join_flip", "dimension": "联合关系",
     "original": "审批完成并且备份可用时，允许发布。",
     "old": "并且", "new": "或",
     "sites": [("联合关系", "original", "并且"), ("联合关系", "candidate", "或")]},
    {"id": "prohibition_delete", "dimension": "禁令",
     "original": "正式稿且审批完成时方可发布。用户明确取消时不得发布。",
     "old": "用户明确取消时不得发布", "new": "",
     "sites": [("禁令", "original", "用户明确取消时不得发布")]},
    {"id": "obligation_downgrade", "dimension": "模态",
     "original": "脚本应当记录来源。",
     "old": "应当", "new": "宜",
     "sites": [("模态", "original", "应当"), ("模态", "candidate", "宜")]},
    {"id": "condition_flip", "dimension": "条件方向",
     "original": "只有审批完成，才启动发布。",
     "old": "只有审批完成，才", "new": "只要审批完成，就",
     "sites": [("条件方向", "original", "只有审批完成，才"), ("条件方向", "candidate", "只要审批完成，就")]},
    {"id": "scope_delete", "dimension": "范围",
     "original": "本次发布须经审批。",
     "old": "本次", "new": "",
     "sites": [("范围", "original", "本次")]},
    {"id": "quantifier_change", "dimension": "量词",
     "original": "所有页面都需复核。",
     "old": "所有", "new": "部分",
     "sites": [("量词", "original", "所有"), ("量词", "candidate", "部分")]},
    {"id": "exception_delete", "dimension": "例外",
     "original": "局部反馈不得触发整体重构；用户明确要求整套重新设计时除外。",
     "old": "；用户明确要求整套重新设计时除外", "new": "",
     "sites": [("例外", "original", "用户明确要求整套重新设计时除外")]},
]

NEGATIVES = [
    {"id": "join_within", "dimension": "联合关系",
     "original": "审批完成并且备份可用时，允许发布。", "old": "并且", "new": "且"},
    {"id": "connective_within", "dimension": "联合关系",
     "original": "审批完成或备份可用时，允许发布。", "old": "或", "new": "或者"},
    {"id": "prohibition_within", "dimension": "禁令",
     "original": "用户取消时不得发布。", "old": "不得", "new": "禁止"},
    {"id": "obligation_within", "dimension": "模态",
     "original": "脚本应当记录来源。", "old": "应当", "new": "必须"},
    {"id": "modality_within", "dimension": "模态",
     "original": "脚本应记录来源。", "old": "应", "new": "应当"},
    {"id": "condition_within", "dimension": "条件方向",
     "original": "只有审批完成，才启动发布。", "old": "只有审批完成，才", "new": "除非审批完成，否则不"},
    {"id": "scope_within", "dimension": "范围",
     "original": "本次发布须经审批。", "old": "本次", "new": "此次"},
    {"id": "quantifier_within", "dimension": "量词",
     "original": "所有页面都需复核。", "old": "所有", "new": "全部"},
    {"id": "exception_within", "dimension": "例外",
     "original": "除本款另有规定外，均应记录。", "old": "除本款另有规定外", "new": "除本款另有规定之外"},
]

SYNTHETIC_NEGATIVE = {
    "id": "synthetic_negative", "dimension": "综合",
    "original": "正常流程已包含内部检查，不再设置固定检查阶段、额外确认或独立通过门槛；不定义自动触发独立检查的条件。",
    "candidate": "正常流程已含内部检查，不设固定检查阶段、额外确认或独立通过门槛；不定义独立检查的自动触发条件。",
}

DELIMS = ["，,。；;：:！!？?、\n", "。；！？\n", "。！？\n"]


def _shrink(text, start, end):
    while start < end and text[start] in "，,。；;：:！!？?、\n \t":
        start += 1
    while end > start and text[end - 1] in "，,。；;：:！!？?、\n \t":
        end -= 1
    return start, end


def smallest_segment(text, start, end):
    start, end = _shrink(text, start, end)
    for delimiters in DELIMS:
        if any(ch in delimiters for ch in text[start:end]):
            continue
        left = start
        while left > 0 and text[left - 1] not in delimiters:
            left -= 1
        right = end
        while right < len(text) and text[right] not in delimiters:
            right += 1
        return left, right
    return 0, len(text)


def check_sites(result, original, candidate, sites):
    details = []
    all_passed = True
    for category, side, ref in sites:
        text = original if side == "original" else candidate
        position = text.find(ref)
        assert position >= 0, "夹具错误：找不到位点 %r" % ref
        start, end = position, position + len(ref)
        segment = smallest_segment(text, start, end)
        passed = False
        reason = ""
        for alert in result["alerts"]:
            if alert["category"] != category:
                continue
            if side == "original":
                span = alert["original"]
            else:
                span = alert["candidate"] if alert["candidate"] and not alert["candidate"].get("removed") else None
            if not span:
                continue
            if span["end"] <= start or span["start"] >= end:
                continue
            if span["start"] < segment[0] or span["end"] > segment[1]:
                reason = "越过最小完整分句 [%d,%d)" % segment
                continue
            if span["text"] not in ref:
                reason = "定位不具体：%r" % span["text"]
                continue
            passed = True
            break
        if not passed and not reason:
            reason = "无类别『%s』的%s侧合格位点" % (category, side)
        all_passed = all_passed and passed
        details.append({"category": category, "side": side, "ref": ref, "passed": passed, "reason": reason})
    return all_passed, details


def run_control_regression():
    report = {"type": "公开控制回归", "status": "工程演练；语义验收未验证；保留判定未适用",
              "dimension_coverage": {}, "positives": [], "negatives": [], "mechanical": [],
              "passed": 0, "total": 0}
    all_pass = True
    for fixture in POSITIVES:
        original = fixture["original"]
        candidate = original.replace(fixture["old"], fixture["new"], 1)
        assert candidate != original, fixture["id"]
        result = linter.check_pair(original, candidate, sample=fixture["id"])
        passed, sites = check_sites(result, original, candidate, fixture["sites"])
        all_pass = all_pass and passed
        report["positives"].append({"id": fixture["id"], "dimension": fixture["dimension"], "passed": passed,
                                    "sites": sites, "alert_count": len(result["alerts"]),
                                    "alert_categories": [a["category"] for a in result["alerts"]]})
        report["total"] += 1
        report["passed"] += 1 if passed else 0
    for fixture in NEGATIVES:
        original = fixture["original"]
        candidate = original.replace(fixture["old"], fixture["new"], 1)
        result = linter.check_pair(original, candidate, sample=fixture["id"])
        passed = len(result["alerts"]) == 0
        all_pass = all_pass and passed
        report["negatives"].append({"id": fixture["id"], "dimension": fixture["dimension"], "passed": passed,
                                    "alert_count": len(result["alerts"]),
                                    "alerts": [a["trigger"] for a in result["alerts"]]})
        report["total"] += 1
        report["passed"] += 1 if passed else 0
    result = linter.check_pair(SYNTHETIC_NEGATIVE["original"], SYNTHETIC_NEGATIVE["candidate"], sample=SYNTHETIC_NEGATIVE["id"])
    passed = len(result["alerts"]) == 0
    all_pass = all_pass and passed
    report["negatives"].append({"id": SYNTHETIC_NEGATIVE["id"], "dimension": SYNTHETIC_NEGATIVE["dimension"],
                                "passed": passed, "alert_count": len(result["alerts"]),
                                "alerts": [a["trigger"] for a in result["alerts"]]})
    report["total"] += 1
    report["passed"] += 1 if passed else 0

    for dimension in DIMENSIONS:
        positives = sum(1 for item in report["positives"] if item["dimension"] == dimension)
        negatives = sum(1 for item in report["negatives"] if item["dimension"] == dimension)
        report["dimension_coverage"][dimension] = {"positive": positives, "negative": negatives}
    coverage_ok = all(item["positive"] >= 1 and item["negative"] >= 1 for item in report["dimension_coverage"].values())
    report["dimension_coverage_ok"] = coverage_ok
    all_pass = all_pass and coverage_ok
    report["total"] += 1
    report["passed"] += 1 if coverage_ok else 0
    return report, all_pass


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _env():
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _run_cli(arguments):
    return subprocess.run([sys.executable, str(SCRIPT)] + arguments, capture_output=True, env=_env())


def run_mechanical():
    checks = []
    work = Path(tempfile.mkdtemp(prefix="rule_linter_v0_selftest_"))

    def record(name, ok, detail=""):
        checks.append({"id": name, "passed": bool(ok), "detail": detail})
        return ok

    original = "甲不得发布。"
    candidate = "甲发布。"
    result = linter.check_pair(original, candidate, sample="offset_basic")
    alert = next((a for a in result["alerts"] if a["category"] == "禁令"), None)
    record("中文码点偏移", alert is not None and alert["original"]["start"] == 1,
           "start=%s" % (alert["original"]["start"] if alert else None))

    bom_path = work / "bom.md"
    cand_path = work / "bom_cand.md"
    _write(bom_path, b"\xef\xbb\xbf" + original.encode("utf-8"))
    _write(cand_path, candidate.encode("utf-8"))
    bom = linter.load_source(bom_path)
    record("仅移除开头BOM",
           bom["text"] == original and bom["sha256"] == hashlib.sha256(original.encode("utf-8")).hexdigest(),
           "text=%r" % bom["text"][:6])

    crlf_original = "甲\r\n不得发布。"
    crlf_candidate = "甲\r\n发布。"
    result = linter.check_pair(crlf_original, crlf_candidate, sample="crlf")
    alert = next((a for a in result["alerts"] if a["category"] == "禁令"), None)
    record("CRLF偏移行列", alert is not None and alert["original"]["start"] == 3
           and alert["original"]["line"] == 2 and alert["original"]["col"] == 1,
           "start=%s line=%s col=%s" % (alert["original"]["start"] if alert else None,
                                        alert["original"]["line"] if alert else None,
                                        alert["original"]["col"] if alert else None))

    supp = "𠀀不得发布。"
    result = linter.check_pair(supp, "𠀀发布。", sample="supplementary")
    alert = next((a for a in result["alerts"] if a["category"] == "禁令"), None)
    record("补充平面字符偏移", alert is not None and alert["original"]["start"] == 1,
           "start=%s" % (alert["original"]["start"] if alert else None))

    repeated = "甲不得发布；乙不得归档。"
    result = linter.check_pair(repeated, "甲不得发布；乙归档。", sample="repeated")
    alert = next((a for a in result["alerts"] if a["category"] == "禁令"), None)
    expected_start = repeated.rfind("不得")
    record("重复词定位第二次出现", alert is not None and alert["original"]["start"] == expected_start,
           "start=%s expected=%s" % (alert["original"]["start"] if alert else None, expected_start))

    missing = work / "missing.md"
    try:
        linter.load_source(missing)
        record("缺失输入报错", False, "未抛出")
    except FileNotFoundError:
        record("缺失输入报错", True)

    invalid = work / "invalid.md"
    _write(invalid, b"\xff\xfe\x00\x01")
    try:
        linter.load_source(invalid)
        record("非法UTF-8报错", False, "未抛出")
    except UnicodeDecodeError:
        record("非法UTF-8报错", True)

    first = json.dumps(linter.check_pair(original, candidate, sample="det"), sort_keys=True, ensure_ascii=False)
    second = json.dumps(linter.check_pair(original, candidate, sample="det"), sort_keys=True, ensure_ascii=False)
    record("同进程两次运行一致", first == second)

    cli_dir = work / "cli"
    cli_source = cli_dir / "source.md"
    cli_candidate = cli_dir / "candidate.md"
    cli_out = cli_dir / "out"
    _write(cli_source, "甲不得发布。".encode("utf-8"))
    _write(cli_candidate, "甲发布。".encode("utf-8"))
    source_before, candidate_before = _sha(cli_source), _sha(cli_candidate)
    first_run = _run_cli(["pair", "--original", str(cli_source), "--candidate", str(cli_candidate),
                          "--name", "cli", "--out", str(cli_out)])
    record("CLI文件运行成功", first_run.returncode == 0, "rc=%s" % first_run.returncode)
    record("CLI不改源文件", _sha(cli_source) == source_before and _sha(cli_candidate) == candidate_before)
    record("CLI写出报告", (cli_out / "定位结果.json").exists())
    output_before = _sha(cli_out / "定位结果.json")
    second_run = _run_cli(["pair", "--original", str(cli_source), "--candidate", str(cli_candidate),
                           "--name", "cli", "--out", str(cli_out)])
    record("已有输出拒绝覆盖", second_run.returncode == 2
           and "拒绝写入" in second_run.stderr.decode("utf-8", errors="replace"),
           "rc=%s" % second_run.returncode)
    record("拒绝覆盖后输出未变", _sha(cli_out / "定位结果.json") == output_before)

    collide_dir = work / "collide"
    collide_input = collide_dir / "定位结果.json"
    collide_candidate = collide_dir / "candidate.md"
    _write(collide_input, "甲不得发布。".encode("utf-8"))
    _write(collide_candidate, "甲发布。".encode("utf-8"))
    collide_before = _sha(collide_input)
    collide_run = _run_cli(["pair", "--original", str(collide_input), "--candidate", str(collide_candidate),
                            "--name", "collide", "--out", str(collide_dir)])
    record("输出撞输入被拒绝", collide_run.returncode == 2 and _sha(collide_input) == collide_before,
           "rc=%s" % collide_run.returncode)

    noout_dir = work / "noout"
    noout_source = noout_dir / "source.md"
    noout_candidate = noout_dir / "candidate.md"
    _write(noout_source, "甲不得发布。".encode("utf-8"))
    _write(noout_candidate, "甲发布。".encode("utf-8"))
    before_listing = sorted(p.name for p in noout_dir.iterdir())
    noout_run = _run_cli(["pair", "--original", str(noout_source), "--candidate", str(noout_candidate)])
    after_listing = sorted(p.name for p in noout_dir.iterdir())
    record("无--out不写文件", noout_run.returncode == 0 and before_listing == after_listing,
           "before=%s after=%s" % (before_listing, after_listing))

    env = _env()
    cmd = [sys.executable, str(SCRIPT), "pair", "--original", str(bom_path), "--candidate", str(cand_path), "--name", "subprocess"]
    one = subprocess.run(cmd, capture_output=True, env=env, check=True).stdout
    two = subprocess.run(cmd, capture_output=True, env=env, check=True).stdout
    record("独立进程两次运行字节一致", one == two)

    single_text = "---\nname: demo\nname: demo2\n---\n# 标题\n参见《示例法》第（二）项及 `R41` 和相关文件 _shared/example-rules.md。"
    single = linter.check_single(single_text, "inline")
    kinds = {ref["kind"] for ref in single["references"]}
    record("单版引用清单", {"书名引用", "规则ID", "文件引用", "反引号标识"} <= kinds, "kinds=%s" % sorted(kinds))
    record("frontmatter重复字段", any("重复" in issue["message"] for issue in single["issues"]))
    record("第（×）项格式提示", any("第×项" in issue["message"] for issue in single["issues"]))
    file_ref = next(ref for ref in single["references"] if ref["kind"] == "文件引用")
    record("范围外引用记未核查", file_ref["check_status"].startswith("未核查"), file_ref["check_status"])

    passed = sum(1 for c in checks if c["passed"])
    return checks, passed == len(checks), passed, len(checks)


def main():
    parser = argparse.ArgumentParser(description="中文规则检查 v0 机械测试")
    parser.add_argument("--report", help="输出公开控制回归报告的目录")
    args = parser.parse_args()

    control, control_ok = run_control_regression()
    checks, mechanical_ok, mechanical_passed, mechanical_total = run_mechanical()
    control["mechanical"] = checks

    failures = []
    for item in control["positives"] + control["negatives"]:
        if not item["passed"]:
            failures.append(("控制回归", item["id"]))
    for item in checks:
        if not item["passed"]:
            failures.append(("机械测试", item["id"]))
    if not control["dimension_coverage_ok"]:
        failures.append(("控制回归", "维度覆盖"))

    print("公开控制：%d/%d 通过（含维度覆盖检查 1 项）" % (control["passed"], control["total"]))
    print("机械测试：%d/%d 通过" % (mechanical_passed, mechanical_total))
    if failures:
        print("失败项：")
        for group, name in failures:
            print(" - %s：%s" % (group, name))
    else:
        print("PASS：全部工程回归通过（语义验收未验证）")

    if args.report:
        out = Path(args.report)
        out.mkdir(parents=True, exist_ok=True)
        (out / "公开控制回归.json").write_text(
            json.dumps(control, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8", newline="")
        print("报告已写入：%s" % (out / "公开控制回归.json"))

    return 0 if (control_ok and mechanical_ok) else 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())

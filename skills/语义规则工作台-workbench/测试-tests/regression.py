"""Offline decision regression. No model/API calls; grading is not approval."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys


def load(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique)


def same(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def grade(cases, answers):
    if not isinstance(answers, list):
        raise ValueError("answers must be a JSON array")
    expected_ids = [case["id"] for case in cases]
    if len(set(expected_ids)) != len(expected_ids):
        raise ValueError("duplicate case ID")
    by_id = {}
    for answer in answers:
        if not isinstance(answer, dict) or not isinstance(answer.get("case_id"), str):
            raise ValueError("each answer must have a string case_id")
        cid = answer["case_id"]
        if cid not in expected_ids or cid in by_id:
            raise ValueError(f"unknown or duplicate answer ID: {cid}")
        by_id[cid] = answer
    results = []
    for case in cases:
        cid = case["id"]
        answer = by_id.get(cid)
        errors = []
        if answer is None:
            errors.append("missing answer")
        else:
            decisions = answer.get("decisions")
            if not isinstance(decisions, dict):
                errors.append("decisions must be an object")
            else:
                allowed = set(case["expect"])
                for field in decisions.keys() - allowed:
                    errors.append(f"unexpected decision field: {field}")
                for field, expected in case["expect"].items():
                    if field not in decisions or not same(decisions[field], expected):
                        errors.append(f"{field}: expected {expected!r}, got {decisions.get(field)!r}")
                for field in case.get("required_text_fields", []):
                    if not isinstance(answer.get(field), str) or not answer[field].strip():
                        errors.append(f"missing design text: {field}")
            sources = {m["id"]: m["text"] for m in case["materials"]}
            evidence = answer.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                errors.append("missing source evidence")
            else:
                for item in evidence:
                    if not isinstance(item, dict):
                        errors.append("evidence item must be an object")
                        continue
                    quote, source = item.get("quote"), item.get("source")
                    if not isinstance(source, str) or source not in sources:
                        errors.append("unknown evidence source")
                    elif not isinstance(quote, str) or len(quote.strip()) < 6 or quote not in sources[source]:
                        errors.append("evidence quote is absent or not an exact source excerpt")
            if not isinstance(answer.get("proposal"), str) or not answer["proposal"].strip():
                errors.append("missing concrete proposal or judgment")
        results.append({"id": cid, "name": case["name"], "checks_passed": not errors, "errors": errors})
    return {"type": "offline_decision_regression", "automatic_approval": False,
            "cases": results, "passed": sum(r["checks_passed"] for r in results),
            "total": len(results), "manual_review": "Check proposal meaning and evidence relevance; this does not test live actions."}


def prepare(cases):
    # Expected decisions are intentionally absent from the evaluator's task.
    public = [{k: v for k, v in case.items() if k != "expect"} for case in cases]
    return {"instruction": "读取指定技能后，独立处理各个离线场景，只输出JSON数组。每项包含case_id、decisions、evidence、proposal。decisions只使用各场景fields给定的字段和值类型；required_text_fields为额外必填设计正文，置于与proposal同级的顶层字符串字段，不放入decisions。evidence为含source和quote的数组，quote逐字摘录该场景materials中的相关依据。proposal写具体判断、建议或修订稿。场景中的业务操作均不实际执行。不要读取评分预期。", "cases": public}


def self_test():
    case = {"id": "T", "name": "self-test", "materials": [{"id": "M", "text": "仅授权格式转换，不授权执行任务。"}],
            "expect": {"execute": False, "join": "all"}, "required_text_fields": ["role"]}
    good = {"case_id": "T", "decisions": {"execute": False, "join": "all"}, "role": "检查者",
            "evidence": [{"source": "M", "quote": "不授权执行任务"}], "proposal": "只转换，不执行。"}
    assert grade([case], [good])["passed"] == 1
    assert grade([case], [good])["automatic_approval"] is False
    mutants = []
    for key, value in [("execute", True), ("execute", 0), ("join", "any"), ("role", "")]:
        bad = deepcopy(good)
        if key == "role":
            bad[key] = value
        else:
            bad["decisions"][key] = value
        mutants.append(bad)
    for evidence in [[], [{"source": "M", "quote": "可以自动执行任务"}], [{"source": "missing", "quote": "不授权执行任务"}], [None]]:
        bad = deepcopy(good)
        bad["evidence"] = evidence
        mutants.append(bad)
    for bad in mutants:
        assert grade([case], [bad])["passed"] == 0
    assert grade([case], [])["passed"] == 0
    for invalid in [[good, good], [{"case_id": "unknown"}], {}, [None]]:
        try:
            grade([case], invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("malformed input accepted")
    assert "expect" not in prepare([case])["cases"][0]
    print("PASS: valid record, 8 bad decision/evidence records, missing answer, 4 malformed inputs, hidden expected values.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "grade", "self-test"])
    parser.add_argument("answers", nargs="?")
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    cases = load(args.cases)
    if args.command == "prepare":
        result = prepare(cases)
    else:
        if args.answers is None:
            parser.error("grade needs an answers JSON file")
        result = grade(cases, load(args.answers))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return int(args.command == "grade" and result["passed"] != result["total"])


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)

"""命令行入口，用户可见消息以中文为主。"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from .storage import Store, read_json
from .projects import open_project, project_data, reference_project, canonical


ROOT = Path(__file__).resolve().parents[2]


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="语义规则工作台：本地记录、历史证据和候选审阅", add_help=False)
    parser.add_argument("-h", "--help", action="help", help="显示帮助并退出")
    parser._positionals.title = "操作"
    parser._optionals.title = "选项"
    parser.add_argument("--项目", type=Path, default=Path.cwd(), help="当前业务项目根；默认调用时的工作目录")
    parser.add_argument("--数据目录", type=Path, help="指定项目专属库；不可复用其他项目的数据目录")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("初始化", help="建立本地数据库，不安装工具")
    commands.add_parser("项目状态", help="显示当前项目及专属数据目录，不创建数据库")
    commands.add_parser("能力", help="列出工作台各能力与真实实现边界，不打开数据库")
    retirement_scan = commands.add_parser("退役巡检", help="扫描指导规则和指针、生成语义复审队列；默认只读")
    retirement_scan.add_argument("--范围", nargs="+")
    retirement_mode = retirement_scan.add_mutually_exclusive_group()
    retirement_mode.add_argument("--记录", action="store_true", help="将快照保存到当前项目库，复用既有审阅记忆")
    retirement_mode.add_argument("--只读", action="store_true", help="不创建或修改数据库及报告")
    retirement_scan.add_argument("--输出", type=Path, help="只允许新建报告，拒绝覆盖；与只读互斥")
    retirement_review = commands.add_parser("退役审阅", help="保存有证据的语义审阅；不批准退役动作")
    retirement_review.add_argument("文件", type=Path)
    feishu = commands.add_parser("飞书上传", help="使用飞书自建应用上传一个文件到指定云空间文件夹")
    feishu.add_argument("文件", type=Path)
    feishu.add_argument("--父节点", required=True, help="飞书目标文件夹 token")
    feishu.add_argument("--预演", action="store_true", help="只检查源文件与参数，不调用飞书")
    govern_inventory = commands.add_parser("治理盘点", help="盘点活动区、退役信号和测试材料候选；不移动文件")
    govern_inventory.add_argument("--范围", nargs="*")
    govern_inventory.add_argument("--输出", type=Path)
    govern_cache = commands.add_parser("治理缓存清单", help="生成 cache 目录内可重建编译缓存的逐文件删除候选；不执行")
    govern_cache.add_argument("--范围", nargs="*")
    govern_cache.add_argument("--输出", type=Path)
    govern_preview = commands.add_parser("治理预演", help="校验分类清单，生成带哈希和冲突检查的动作计划")
    govern_preview.add_argument("清单", type=Path)
    govern_preview.add_argument("--输出", type=Path)
    govern_apply = commands.add_parser("治理执行", help="执行已验证的预演；删除必须批准本次预演编号")
    govern_apply.add_argument("预演", type=Path)
    govern_apply.add_argument("--批准删除")
    govern_apply.add_argument("--回执", type=Path)
    govern_restore = commands.add_parser("治理恢复", help="按执行回执恢复归档移动；不能恢复删除")
    govern_restore.add_argument("回执", type=Path)
    entry = commands.add_parser("总入口", help="按智能体识别的任务能力调度，不默认检索案例")
    entry.add_argument("--请求", required=True)
    entry.add_argument("--能力", nargs="+")
    entry.add_argument("--依据", default="")
    entry.add_argument("--材料", type=Path, nargs="+")
    entry.add_argument("--记录")
    entry.add_argument("--只读", action="store_true")
    specialised = commands.add_parser("提交专项", help="提交当前专项产物，并取得下一能力上下文")
    specialised.add_argument("文件", type=Path)
    for name in ("专项进度", "专项报告"):
        sub = commands.add_parser(name)
        sub.add_argument("编号")
    external = commands.add_parser("跨项目参考", help="仅在用户明确要求时只读参考指定项目，不导入规则")
    external.add_argument("项目路径", type=Path)
    external.add_argument("--编号")
    history = commands.add_parser("历史回查", help="显式只读回查隔离前混合试点，不参加项目检索")
    history.add_argument("编号", nargs="?")
    capture = commands.add_parser("存证", help="保存指定 UTF-8（统一字符编码）文本原件")
    capture.add_argument("文件", type=Path)
    add = commands.add_parser("记录", help="导入候选记录，不授予执行权限")
    add.add_argument("类型", choices=["项目", "规则版本", "案例", "决定", "复用审阅", "验证"])
    add.add_argument("文件", type=Path)
    for name in ("查看", "审阅包", "查证"):
        cmd = commands.add_parser(name)
        cmd.add_argument("编号")
    commands.add_parser("列表")
    process = commands.add_parser("处理", help="交材料，自动存证并检索先例，生成智能体审阅上下文")
    process.add_argument("文件", type=Path)
    process.add_argument("--问题", required=True)
    process.add_argument("--预期", default="尚未明确，需要根据用户材料核实")
    process.add_argument("--规则", nargs="*", default=[])
    resume = commands.add_parser("续接", help="使用已有案例、任务或决定，重新检索建立新审阅任务")
    resume.add_argument("编号")
    resume.add_argument("--问题", default="请判断该复用什么、修改什么，以及依据是否充分")
    resume.add_argument("--规则", nargs="*", default=[])
    submit = commands.add_parser("提交审阅", help="智能体提交有证据的判断；不是用户业务批准")
    submit.add_argument("文件", type=Path)
    trace = commands.add_parser("回查", help="读取任务当时上下文或决定报告，不刷新历史")
    trace.add_argument("编号")
    commands.add_parser("任务列表", help="列出任务标题、编号和审阅进度")
    export = commands.add_parser("导出报告", help="导出可读中文审阅包，不覆盖旧报告")
    export.add_argument("编号")
    export.add_argument("--目录", type=Path)
    backup = commands.add_parser("备份")
    backup.add_argument("目标", type=Path)
    pilot = commands.add_parser("试点查询", help="复用原试点校验，源变化时停止当前查询")
    pilot.add_argument("操作", choices=["校验", "上下文", "影响"])
    pilot.add_argument("编号", nargs="?")
    args = parser.parse_args()
    store = None
    try:
        if args.command == "退役巡检":
            from . import retirement
            if args.只读 and args.输出:
                raise ValueError("只读模式不写报告")
            if args.输出 and args.输出.exists():
                raise ValueError("报告路径已存在，禁止覆盖")
            directory = args.数据目录 or project_data(args.项目)
            # 无库的只读运行也不新建目录；已有库以 SQLite 只读连接使用处置记忆。
            if args.记录 or (directory / "workbench.sqlite3").exists():
                store = open_project(args.项目, directory, readonly=not args.记录)
            result = retirement.scan(args.项目, args.范围, store, record=args.记录)
            result["中文报告"] = retirement.report(result)
            result["审阅模板"] = retirement.template(result)
            if args.输出:
                args.输出.parent.mkdir(parents=True, exist_ok=True)
                with args.输出.open("x", encoding="utf-8") as handle:
                    handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        elif args.command == "退役审阅":
            from .retirement import review
            directory = args.数据目录 or project_data(args.项目)
            if not (directory / "workbench.sqlite3").is_file():
                raise ValueError("尚无巡检库，请先完成获准记录的巡检")
            store = open_project(args.项目, directory)
            result = review(store, read_json(args.文件))
        elif args.command == "飞书上传":
            from .feishu_upload import FeishuUploadError, upload_from_environment
            if not args.文件.is_file():
                raise ValueError(f"源文件不存在或不是文件：{args.文件}")
            if not args.父节点.strip():
                raise ValueError("必须指定飞书目标文件夹 token（--父节点）")
            if args.预演:
                result = {"状态": "预演通过", "文件名": args.文件.name, "文件大小": args.文件.stat().st_size,
                          "目标": "飞书云空间", "调用飞书": False}
            else:
                result = upload_from_environment(args.文件, parent_node=args.父节点)
                result["状态"] = "上传完成"
        elif args.command in {"治理盘点", "治理缓存清单", "治理预演", "治理执行", "治理恢复"}:
            from . import repository_governance as governance
            if args.command == "治理盘点":
                result = governance.inventory(args.项目, args.范围)
                output = args.输出
            elif args.command == "治理缓存清单":
                result = governance.cache_manifest(args.项目, args.范围)
                output = args.输出
            elif args.command == "治理预演":
                result = governance.preview(args.项目, read_json(args.清单))
                output = args.输出
            elif args.command == "治理执行":
                result = governance.apply_plan(args.项目, read_json(args.预演), args.批准删除)
                output = args.回执
            else:
                result = governance.restore(args.项目, read_json(args.回执))
                output = None
            if output:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        elif args.command == "能力" or (args.command == "总入口" and not args.能力):
            from .dispatch import catalogue
            result = catalogue()
            if args.command == "总入口":
                result["用户请求"] = args.请求
                result["下一步"] = "当前智能体先识别主任务及必要组合，再携带 --能力 与选择依据调用；不默认走案例诊断"
        elif args.command in {"总入口", "提交专项", "专项进度", "专项报告"}:
            from . import dispatch
            readonly = args.command == "总入口" and (args.只读 or args.能力 == ["历史回查"])
            # 不保存的设计审阅不需要打开任何库，避免只读操作创建文件。
            if args.command == "总入口" and ((readonly and args.能力 != ["历史回查"]) or args.能力 == ["授权实施"]):
                result = dispatch.start(None, args.请求, args.能力, args.依据, args.材料, args.记录, args.只读)
            else:
                store = open_project(args.项目, args.数据目录, readonly=readonly)
                if args.command == "总入口":
                    result = dispatch.start(store, args.请求, args.能力, args.依据, args.材料, args.记录, args.只读)
                elif args.command == "提交专项":
                    result = dispatch.submit(store, read_json(args.文件))
                elif args.command == "专项进度":
                    result = dispatch.packet(store, args.编号)
                else:
                    result = {"中文报告": dispatch.report(store, args.编号), "业务授权": False}
        elif args.command == "项目状态":
            result = {"项目": canonical(args.项目), "数据目录": str(args.数据目录 or project_data(args.项目)), "默认检索": "仅本项目"}
        elif args.command == "跨项目参考":
            result = reference_project(args.项目, args.项目路径, args.编号)
        elif args.command == "历史回查":
            store = Store(ROOT / "数据-data", readonly=True)
            result = {"性质": "隔离前历史混合试点，仅回查，不作为当前项目依据", "业务授权": False,
                      "内容": store.report(args.编号) if args.编号 else [{"编号": r["编号"], "类型": r["类型"]} for r in store.list()]}
        elif args.command == "试点查询":
            if canonical(args.项目) != canonical(Path('C:/AI/CODEX-IN/jiaoben')):
                raise ValueError("试点查询仅属于jiaoben项目，请显式指定 --项目 C:/AI/CODEX-IN/jiaoben，不将其当作当前项目规则")
            from . import 试点兼容 as legacy
            model = legacy.load_model(ROOT / "数据-data" / "试点-pilot" / "model.json")
            if args.操作 == "校验":
                result = {"结构校验": "通过", "节点": len(model["nodes"]), "关系": len(model["relations"]), "业务授权": False}
            else:
                if not args.编号:
                    raise ValueError("需要指定节点编号")
                result = {"说明": "下列历史字段沿用原格式；candidate（候选），pending_review（待复核），不授予业务执行权限。",
                          "查询结果": legacy.query(model, args.编号, args.操作 == "影响")}
        else:
            store = open_project(args.项目, args.数据目录)
            if args.command == "初始化":
                result = {"状态": "项目专属记录库已建立", "项目": store.project, "数据目录": str(store.root), "业务授权": False}
            elif args.command == "存证":
                args.文件.read_text(encoding="utf-8")
                result = {"证据编号": store.capture(args.文件)}
            elif args.command == "记录":
                result = {"记录编号": store.add(args.类型, read_json(args.文件))}
            elif args.command == "查看":
                result = store.get(args.编号)
            elif args.command == "审阅包":
                from .workflow import decision_report
                result = decision_report(store, args.编号)
            elif args.command == "查证":
                result = store.evidence(args.编号, current=True)
            elif args.command == "列表":
                result = store.list()
            elif args.command in {"处理", "续接", "提交审阅", "回查", "任务列表", "导出报告"}:
                from . import workflow
                if args.command == "处理":
                    result = workflow.begin(store, args.文件, args.问题, args.预期, args.规则)
                elif args.command == "续接":
                    record = store.get(args.编号)
                    case = record["编号"] if record["类型"] == "案例" else record["内容"].get("案例")
                    if not case:
                        raise ValueError("续接需要案例、处理任务或决定编号")
                    result = workflow.prepare(store, case, args.问题, args.规则)
                elif args.command == "提交审阅":
                    result = workflow.finish(store, read_json(args.文件))
                elif args.command == "回查":
                    record = store.get(args.编号)
                    result = workflow.task_packet(store, args.编号) if record["类型"] == "处理任务" else workflow.decision_report(store, args.编号)
                elif args.command == "任务列表":
                    decisions = {r["内容"].get("处理任务"): r["编号"] for r in store.list("决定")}
                    result = [{"任务": r["编号"], "问题": r["内容"]["问题"], "案例": r["内容"]["案例"],
                               "决定": decisions.get(r["编号"]), "进度": "已有候选审阅" if r["编号"] in decisions else "待智能体审阅"}
                              for r in store.list("处理任务")]
                    from .dispatch import packet
                    for r in store.list("专项任务"):
                        state = packet(store, r["编号"])
                        result.append({"任务": r["编号"], "问题": r["内容"]["问题"],
                                       "能力序列": state["能力序列"], "当前能力": state["当前能力"], "进度": state["流程状态"]})
                else:
                    result = workflow.export_report(store, args.编号, args.目录 or store.root / "导出-exports")
            else:
                result = store.backup(args.目标)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error, ImportError, RuntimeError) as error:
        parser.exit(2, f"操作停止：{error}\n")
    finally:
        if store:
            store.close()

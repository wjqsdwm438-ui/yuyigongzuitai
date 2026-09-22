# 语义规则工作台

中文优先的本地规则维护工作台，包含候选记录、来源追溯、项目隔离、专项交付和确定性检查工程演练。

## 发布范围

2026-09-20 核实本仓库当前为公开状态；本次不改变可见性。只发布已核查源码、通用说明和合成测试，不上传凭据、业务材料或本地数据库。仓库关系与历史同步要求见[读取与同步约定](说明-docs/私有仓库同步-private-sync.md)，其中早期私有状态不可作为当前访问控制保证。

Git 发布内容是经过数据排除的源码快照，不包含原始本地 Git 历史、真实业务材料、会话摘录、数据库、部署清单或临时报告。本地工作区可能仍有未跟踪或已忽略的业务与运行材料；它们不因此成为源码或发布内容。

保留核心程序、通用技能、确定性检查器、机械测试及第三方来源和许可证。发布测试中的综合阴性已替换为合成例子，不代表原业务样本或独立效度成绩。

## 最新状态（v0.2.0）

新增指导规则退役巡检：复用项目库保留候选与处置记忆，正文或关联依据变化后重开，并提供受控的远端补漏入口，保留既有能力。方案、验证边界和发布入口见[方案与验收](说明-docs/指导规则退役发现-方案与验收.md)。

以下为2026-09-15历史状态：

本地案例检索依赖已恢复，环境修复回归24项通过；C1—C2诊断及后续默认约束维护已完成相应工作台提交。指令配置与文件核验不等于配音执行约束已稳定生效。详见[当前实现状态](说明-docs/当前实现状态.md)及[C2第一批测试问题反思](说明-docs/C2第一批测试问题-反思.md)。

## 使用

在已加载工作台核心 Skill 的智能体会话中提出“批量整理这些材料”，由智能体按[批量整理流程](skills/语义规则工作台-workbench/SKILL.md#批量整理)扫描、归并并生成重点页；现有命令仅在需要时辅助取证或验证。CLI 没有“批量整理”子命令，也不自动完成语义归并。

Python 3.11+；既有 Windows 完整环境使用 Python 3.12。无需为确定性检查器安装第三方包。

```powershell
python -X utf8 -B 工作台.py 能力
python -X utf8 -B 工作台.py --项目 ./example-project 项目状态
python -X utf8 -B 工作台.py --项目 ./example-project 总入口 --请求 "联合审查" --能力 Agent设计 --依据 "核对多份来源" --材料 AGENTS.md README.md --只读
python -X utf8 -B 工作台.py --项目 ./example-project 治理盘点 --范围 设计
python -X utf8 -B 脚本-scripts/中文规则检查_v0.py --help
python -X utf8 -B 脚本-scripts/中文规则检查_v0.py pair --original 原文.md --candidate 候选.md
python -X utf8 -B 测试-tests/test_rule_linter_v0.py
```

专项交付由`总入口`建立任务，再按返回模板提交；案例诊断使用独立闭环。命令参数以各子命令的`--help`为准：

```powershell
python -X utf8 -B 工作台.py --项目 <项目根> 总入口 --请求 <请求> --能力 <能力...> --依据 <依据> --材料 <材料...>
python -X utf8 -B 工作台.py --项目 <项目根> 提交专项 <产物.json>
python -X utf8 -B 工作台.py --项目 <项目根> 专项进度 <专项编号>
python -X utf8 -B 工作台.py --项目 <项目根> 专项报告 <专项编号>
python -X utf8 -B 工作台.py --项目 <项目根> 处理 <材料文件> --问题 <问题> --预期 <已确认预期或未知>
python -X utf8 -B 工作台.py --项目 <项目根> 提交审阅 <审阅.json>
python -X utf8 -B 工作台.py --项目 <项目根> 导出报告 <决定编号>
python -X utf8 -B 工作台.py --项目 <项目根> 任务列表
python -X utf8 -B 工作台.py --项目 <项目根> 回查 <任务或决定编号>
python -X utf8 -B 工作台.py --项目 <项目根> 续接 <案例、任务或决定编号>
```

飞书云空间上传使用飞书自建应用凭据。先在当前进程设置 `FEISHU_APP_ID` 和
`FEISHU_APP_SECRET`，再显式提供目标文件夹 token；凭据不会写入命令参数、源码或日志：

```powershell
python -X utf8 -B 工作台.py 飞书上传 D:\zhishiku\ds4.1.txt --父节点 <飞书文件夹token> --预演
python -X utf8 -B 工作台.py 飞书上传 D:\zhishiku\ds4.1.txt --父节点 <飞书文件夹token>
```

上传接口使用自建应用 `tenant_access_token` 和云空间文件上传 API；应用需具备对应云空间写入权限。

仓库治理支持逐文件分类、动作预演、冲突停止、归档恢复和删除精确授权。工作标准与清单格式见[仓库治理标准](说明-docs/仓库治理标准-repository-governance.md)；归档区默认不进入搜索上下文。

仓库治理的唯一确定性执行器是工作台原生模块。`organize-tool` 与 `repo-maintenance` 不进入正式链；Project Steward 仅作为机制来源。Repomix 是独立的仓库内容打包能力，不参与文件分类、移动、归档、恢复或删除：

```powershell
powershell -ExecutionPolicy Bypass -File 脚本-scripts/仓库模型打包.ps1
powershell -ExecutionPolicy Bypass -File 脚本-scripts/仓库模型打包.ps1 -Remote yamadashy/repomix -Branch main
```

命令固定使用 Repomix 1.18.0，输出写入已忽略版本管理的 `导出-exports/repomix-output.xml`；远程仓库配置默认不受信任。

## 应退役内容主动发现

在已加载核心 Skill 的会话中说“检查这些指导里哪些已经不适用”，或维护 Agent、Skill 与指针时由智能体主动选用巡检模式。无需另装一个 Skill。

```powershell
python -X utf8 -B 工作台.py --项目 <项目根> 退役巡检 --只读
python -X utf8 -B 工作台.py --项目 <项目根> 退役巡检 --记录
python -X utf8 -B 工作台.py --项目 <项目根> 退役审阅 <审阅.json>
```

远端 `Retirement watch` 初始仅允许在 main 上手动派发，并要求显式确认本次 Issue 写入；main 推送和定时触发尚未启用。首次真实运行通过后，是否启用周期或 main 变更触发另行决定。云端项目库保存在 Actions 产物中，单个 Issue 只作通知索引，本地库不自动上传。程序负责取证、版本追踪与复审派发，当前智能体负责语义判断；没有模型在线时不宣称已自动判定所有应退役内容。候选不自动删除，既有治理授权门禁不变。使用细则见[退役巡检方法](skills/语义规则工作台-workbench/参考-references/退役巡检方法.md)。

验证工作流仍可随分支、PR 和 main 推送运行，但正式 Release 只在 main 上手动派发并显式确认 `publish_release` 后创建；测试通过不自动授予发布权限。

## 规则与状态来源

- `AGENTS.md`只保存项目不可违背约束及正式入口指针。
- `skills/语义规则工作台-workbench/SKILL.md`是语义工作流唯一正文；`skills/全局入口-entry/SKILL.md`只维护当前部署位置并转交核心 Skill。
- `源码-src/语义工作台/dispatch.py`保存程序实际能力状态；`说明-docs/当前实现状态.md`解释已实现与未实现边界。
- `说明-docs/仓库治理标准-repository-governance.md`是仓库治理规则真源；[Project Steward 机制采用决定](说明-docs/Project-Steward机制采用决定.md)只保存历史取舍。

加 `--out` 才写检查报告；不得指定已有结果或与输入冲突的路径。词项及句式检测只提示疑似变化，零告警不证明等义。

完整案例检索分支需要 Semantica 项目依赖；固定清单见 `依赖-dependencies/Windows-Python312固定版本.txt`。依赖安装不是本次发布的自动动作。全局入口安装脚本也只能在明确授权后运行。

获准安装后的本地部署与验证步骤见[项目环境部署](说明-docs/项目环境部署-local-setup.md)。`工作台.py`自动转交本仓库的`.环境-venv`解释器。

机器特定安装路径只在全局入口 Skill 中维护；它不表示业务资料已随仓库发布。旧试点查询需另备获准的本地模型与源材料。本次未更改核心功能来假装跨环境通用。

## 验证边界

工程控制与机械测试不等于中文语义验收。H1/H2 独立留出、独立人工标注、独立离线运行和复核计时未由本次发布完成；不作保留、扩充或减负结论。

使用边界见 [当前实现状态](说明-docs/当前实现状态.md) 与 [跨项目使用](说明-docs/跨项目使用.md)。

## 第三方材料

已保留所选 Sentry／Anthropic 上游文件的许可证、声明及固定来源清单，见 `依赖-dependencies/技能上游-upstream/`。保留上游许可不表示为本项目其他代码新增许可证。

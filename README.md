# 语义规则工作台

中文优先的本地规则维护工作台，包含候选记录、来源追溯、项目隔离、专项交付和确定性检查工程演练。

## 发布范围

仓库保持私有，供所有者及已授权连接器阅读。仓库对应关系、分批同步要求和未完成事项见[私有仓库读取与同步约定](说明-docs/私有仓库同步-private-sync.md)。上传 GitHub 不代表向公众公开。

Git 发布内容是经过数据排除的源码快照，不包含原始本地 Git 历史、真实业务材料、会话摘录、数据库、部署清单或临时报告。本地工作区可能仍有未跟踪或已忽略的业务与运行材料；它们不因此成为源码或发布内容。

保留核心程序、通用技能、确定性检查器、机械测试及第三方来源和许可证。发布测试中的综合阴性已替换为合成例子，不代表原业务样本或独立效度成绩。

## 使用

Python 3.11+；既有 Windows 完整环境使用 Python 3.12。无需为确定性检查器安装第三方包。

```powershell
python -X utf8 -B 工作台.py 能力
python -X utf8 -B 工作台.py --项目 C:/work/example 项目状态
python -X utf8 -B 工作台.py --项目 C:/work/example 治理盘点 --范围 设计
python -X utf8 -B 脚本-scripts/中文规则检查_v0.py --help
python -X utf8 -B 脚本-scripts/中文规则检查_v0.py pair --original 原文.md --candidate 候选.md
python -X utf8 -B 测试-tests/test_rule_linter_v0.py
```

仓库治理支持逐文件分类、动作预演、冲突停止、归档恢复和删除精确授权。工作标准与清单格式见[仓库治理标准](说明-docs/仓库治理标准-repository-governance.md)；归档区默认不进入搜索上下文。

仓库治理的唯一确定性执行器是工作台原生模块。`organize-tool` 与 `repo-maintenance` 不进入正式链；Project Steward 仅作为机制来源。Repomix 是独立的仓库内容打包能力，不参与文件分类、移动、归档、恢复或删除：

```powershell
powershell -ExecutionPolicy Bypass -File 脚本-scripts/仓库模型打包.ps1
powershell -ExecutionPolicy Bypass -File 脚本-scripts/仓库模型打包.ps1 -Remote yamadashy/repomix -Branch main
```

命令固定使用 Repomix 1.18.0，输出写入已忽略版本管理的 `导出-exports/repomix-output.xml`；远程仓库配置默认不受信任。

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

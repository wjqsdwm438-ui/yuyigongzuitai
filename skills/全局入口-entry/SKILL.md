---
name: semantic-rule-workbench
description: 定位并调用语义规则工作台的全局入口；完整任务选路、项目隔离和交付规则由工作台核心 Skill 统一维护。
---

# 语义规则工作台（全局定位入口）

本 Skill 只负责找到当前部署、核对入口存在并转交核心 Skill，不复制能力清单、专项流程或授权规则。

## 当前部署

- 工作台根目录：`E:/yuyigongzuitai`
- 核心 Skill：`E:/yuyigongzuitai/skills/语义规则工作台-workbench/SKILL.md`
- 程序：`E:/yuyigongzuitai/工作台.py`
- 项目解释器：`E:/yuyigongzuitai/.环境-venv/Scripts/python.exe`

这是唯一维护机器特定安装路径的位置。核心 Skill、README 和业务项目不得再复制该绝对路径。任一入口不存在时，报告当前部署不可用；不要另造实现、猜测旧路径或静默安装。

## 转交步骤

1. 完整读取核心 Skill，根据用户目标执行其“工作台总入口”和“实际使用闭环”。能力定义和真实边界以程序的 `能力` 输出为准。
2. 确定当前业务项目根目录。工作台源码目录只在维护工作台自身时才是业务项目；附件目录不是默认项目。
3. 先运行项目状态，再执行核心 Skill 选定的命令：

```powershell
& 'E:\yuyigongzuitai\.环境-venv\Scripts\python.exe' -X utf8 -B 'E:\yuyigongzuitai\工作台.py' --项目 '当前业务项目绝对路径' 项目状态
```

4. 后续只引用核心 Skill 的规则，不在本文件重新解释总入口、专项提交、案例诊断、历史回查或授权边界。

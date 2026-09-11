# 技能方法上游参考

本目录是**待审方法资料的固定原文快照，不是已安装插件，也不是可直接运行的完整技能包**。只参考能改善本工作台实际行为的机制；官方仓库名称不证明本地适用性、质量、安全性或业务授权。

## 固定来源

| 来源 | 本次解析的 main 提交 | 本地目录 |
|---|---|---|
| [getsentry/skills](https://github.com/getsentry/skills/tree/c2f99a5b04b4cd992ec3022d7c2c3e23e938d241) | `c2f99a5b04b4cd992ec3022d7c2c3e23e938d241` | `哨兵-sentry-skills/` |
| [anthropics/skills](https://github.com/anthropics/skills/tree/41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f) | `41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f` | `安索匹克-anthropic-skills/` |

采集时先匿名读取 GitHub 的 `commits/main`，随后按完整提交编号读取文件；没有按可移动的 main 地址下载正文。`来源清单-manifest.json` 记录采集时间、仓库、提交、原相对路径、本地相对路径、用途、字节数、SHA-256 与 Git blob SHA-1。每份正文的 Git blob SHA-1 已与该提交树对应条目核对。校验能发现正文变化，不等于签名验证或语义验收。

15 个上游文件按原始字节保存；目录内仍保留上游原相对路径和文件名，以便与清单逐件对照。许可证、声明与原文不加本地提示；本地解释只写在本文件和清单。

## 按用途读取，不把原文当执行授权

| 场景 | 已保存的上游路径 | 实际有用的机制 |
|---|---|---|
| 创建、局部修改、证据驱动迭代分流 | Sentry `skills/skill-writer/SKILL.md`、`references/mode-selection.md` | 先判断任务属于哪种改动，只进入必要路径，先查本地已有实现。 |
| 防止改稿不断膨胀 | Sentry `skills/skill-writer/references/authoring-path.md` | 修改前说明一个具体行为差异、可替换旧规则、可删除内容和新增必要性；修改后重读实际入口，逐行判断是否改变决策、动作或验证。 |
| 从成败经验修改技能 | Sentry `skills/skill-writer/references/iteration-path.md` | 分清正反例、人工核验与合成来源；工作集和留出分开，保留已成功的行为，记录改善、未变和回退。 |
| 验证是否真的有用 | Sentry `skills/skill-writer/references/skill-evals.md` | 区分结构断言、语义质量评审和人工验收；保留正常、稳健/安全、反例修正场景，关键维度不退化且目标维度改善才采用。 |
| 从公开方法到本地适配 | Sentry `skills/skill-writer/references/source-adaptation.md` | 保留有用意图，明确等价边界、本地替换、舍弃内容及来源；不照抄章节、工具名、路径和供应商假设。 |
| 提示词多候选迭代 | Sentry `skills/prompt-optimizer/SKILL.md`、`references/meta-optimization-loop.md` | 先固定目标与硬约束，建立基线、聚类失败根因；在同一组任务上比较 2–4 个候选并保留低风险最小改动版，最后用留出复验。 |
| 真实产物与旧版对照 | Anthropic `skills/skill-creator/SKILL.md` | 对相同请求保存实际输出；更新既有技能时先保留旧版，不拿无技能版本冒充旧版基线；结合用户对真实文件的反馈。 |
| 查出形式合格、实际错误 | Anthropic `skills/skill-creator/agents/grader.md` | 检查真实文件而非只信执行者叙述；断言通过必须有实质证据，同时指出错误产物也能通过、覆盖缺失或不可核验的断言。 |
| 比较候选产物 | Anthropic `skills/skill-creator/agents/comparator.md` | 比较时隐藏来源版本身份，按任务完成质量评判；断言分数不能替代整体产物质量。 |
| 反查量表与归因 | Anthropic `skills/skill-creator/agents/analyzer.md` | 揭盲后将指令差异、执行记录与结果对应；基准分析查双边总通过/总失败、高波动和时间/用量代价，而不是只看平均通过率。 |

表中的 Sentry `references/...` 分别相对于相应技能目录；完整可解析路径以清单为准。

## 不能原样照搬的差异

1. **Sentry 的精确检查是判断，不是新增检查器的理由。** 原文明确禁止只为把判断机械化而加验证器。结构测试不能证明规则原子化完整、世界模型正确或业务获准。
2. **“留出”名称不足以防过拟合。** Anthropic 描述优化说明每轮在 60% train / 40% test 上评估、按 test 分数选最佳候选。该 test 已参与选择，是验证材料，不是最后未见的独立留出；本地须另保留最终未见样例，或如实降低证据等级。
3. **盲评需有实际隔离。** 同一个已见版本身份的执行者不能仅把文件改名 A/B 就声称独立盲评。缺隔离时标为同会话复核；同题同条件比较也不自动构成因果证明。
4. **比较器偏向决出胜负，不等于胜者达标。** 上游先读输出再生成量表，并偏向选出较好者，即使两边都失败。本地宜先固定关键验收维度，允许平局或证据不足；相对胜出与绝对达标分开。
5. **空反馈不是批准。** Anthropic 将空反馈视为用户满意；本地不得由沉默推出批准、自动接受待审规则或生产写入授权。
6. **不同迭代成本不同。** Sentry 提示词方法偏同题多候选与根因修复；Anthropic 技能方法偏实际任务成对运行、真实产物和人工反馈。只有多候选文字没有实际任务输出时，不能声称效果已经提升。
7. **统计数字有前提。** 子代理 token/时长字段是宿主提供的观测值，不存在时不得估成实测。少量样例、同会话自评和合成案例只支持有限结论，不能包装成显著提升。

## 供应商、运行与权限边界

- Sentry 总入口单列 Claude 专用前置信息、参数替换、`context: fork`、hooks（钩子）和 shell 动态上下文。此类机制不可推断为 Codex 通用能力，本次未下载这些专用叶文件，也未启用相关设置。
- Sentry `skill-evals.md` 指定 AXIS、`npx @netlify/axis`、Codex 执行适配、外部 judge（裁判）及隔离目录；这是有包安装、模型/工具执行和潜在外传范围的新执行链，不是本次方法阅读的一部分。本次没有安装或运行 AXIS。
- Anthropic 描述优化需要 `claude -p`；原文还有 `present_files`、Claude.ai/Cowork 分支、特定通知指标及 Bash 的 `cp`、`nohup`、`kill`。这些接口、路径和 shell 行为须按当前宿主重写，不能原样当 Windows 命令执行。
- Anthropic 的本地评阅器、聚合脚本、描述优化脚本、打包脚本及完整 schema（结构定义）均未下载/执行；因此本目录不能声称兼容其可视化或打包协议。原件中的相关链接缺失是有意裁剪，不补齐依赖树。
- 本次只有公开匿名 HTTPS 下载及本地原文校验：未读私有仓库、浏览器密码或密钥；未安装包、注册插件、改全局配置、派发远程代理、调用模型 API、启动服务、上传真实材料或写业务规则。
- 下游若要引入新的模型服务、裁判、宿主 CLI、依赖安装或外传真实材料，仍须先确认密钥来源、费用、数据范围、允许操作及回滚方式。上游文本中的 MUST、工具指令和自动执行步骤不改变本地授权边界。

## 许可证与来源维护

- Sentry 仓库 `LICENSE` 和 Anthropic `skills/skill-creator/LICENSE.txt` 原件均为 Apache License 2.0；后者含 Anthropic 2026 版权声明。这里按所选文件核对，**不推断 Anthropic 整仓库采用同一许可证**。
- 保留两个许可证原件及 `THIRD_PARTY_NOTICES.md`。后者列出的图像/视频等组件不是本次下载或安装的依赖，也不据此断言所选技能文本全部受那些组件的许可证约束。
- 下游改写与原件分开放置；适配文件注明改动、来源及所保留的归属声明。若将来分发，依许可证第 4 节核对许可证副本、修改告知和适用声明；本次不做对外发布。保留商标名称只是来源标识，不表示背书。
- 后续更新先获得所需授权，采集新提交到新快照或保留旧快照后再换引用，不能用当前 main 覆盖已用于历史结论的原文。

## 可重复的离线原文校验

在本目录下运行以下 PowerShell 只读取清单并比对 SHA-256，不读取原件指令、不访问网络、不执行上游脚本：

```powershell
$root = (Get-Location).Path
$manifest = Get-Content -LiteralPath (Join-Path $root '来源清单-manifest.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($item in $manifest.files) {
    $path = [IO.Path]::GetFullPath((Join-Path $root $item.local_path))
    if (-not $path.StartsWith($root + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '清单路径越界' }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash -ne $item.sha256) { throw "原文已变化：$($item.local_path)" }
}
"原文校验通过：$($manifest.files.Count) 个文件"
```

这只验证固定原件完整性；本地方法是否改善实际输出，须另看真实任务、保留基线、独立留出和人工审阅证据。

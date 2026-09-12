# P4 当前恢复点

- 目标：按用户方案（2026-09-12）完成 instruct2 整体讲述候选；自动门槛已通过，提交用户盲听；声音通过前 P5 不放行。
- 状态：执行者为本审计会话（用户直接指挥）；instruct2 候选已交付：86.76 秒完整本段（请求 `8d20619a61bc4be188243d2d29f263b1`，6/6 交付块，`stream=False`、`speed=1.0`、`text_frontend=True`、`seed=1986`、`zero_shot_spk_id=''`）；TTS 与 ASR 进程均退出，GPU 已释放。
- 已完成：同批准块清单（frontend-dry-run.json 24f53814…）逐字复用；接口单变量切换 zero_shot→inference_instruct2；指令仅为调用参数（未改模型源码）；llm/flow/hift/f0 全 cuda:0（f0 float64）；六块 PCM 逐样本拼接核对通过。
- 自动核验：Qwen 冻结工具 4/4 成功（cuda），两正常样本误报 0、已知坏样本拦截；候选全文与目标**未解差异 0**；协议01 whisper-small 21 替字/6 重复为已知 2/2 误报工具旁证。节奏对比：86.76s vs 98.72s；停顿 20.7/分 vs 31.6/分；停顿总时长 10.42s vs 16.83s；**目标六词组内部停顿 ≥0.25s 全部为 0**（基线均有）；残留最长停顿为句读处 0.30–0.54s。
- 下一步：用户盲听两条音频（基线 98.72s vs instruct2 86.76s），判定音色/韵律/整体快慢接近 02 与 41–42s 会计读音；未听审不通过前不放行 P5。听审通过→按同调用配置覆盖其余投诉位置并全段重交付（另批额度）；不通过→弃用候选回退 zero-shot（调用配置已记录），41–42s 会计拼音纠音仍待执行（需额度）。
- 计数：共享 `request_records.jsonl` 现为 6 记录/18 实块（本候选前 prior 12 块）；另有 trial04（dispatch-04）独立记录 4 请求/4 块未入共享日志，框架合计 10 请求/22 块。本候选为交付额度 6/6（approval_source=用户"按这个方案执行吧"）；修复额度仍 4/4 已用、新增 0。协议02/校准未改动。
- 对照线索（trial04，dispatch-04）：A0/A1（官方 silent 过滤）输出逐字节相同，本 seed 未触发删除，该路线无效果证据；B0 中性 26.72s；B1 逐项定向 13.36s 但"业财融合"读成"业态融合"（内容失败，被排除盲听）——与用户最终改用整体讲述指令的决定互证。本候选全文"业财融合"三处经 Qwen 冻结核验全部正确。
- 模型：本会话由用户直接授权执行，无 Astra/xhigh 席位元数据可读，不冒填。
- 产物：候选目录 `执行-execution/instruct2-候选-candidate/`（run_instruct2.py、asr_instruct2.py、verify_instruct2.py、instruct2-delivery-request.json、asr-instruct2.json、instruct2-结果-result.json、结果-report.md、六块与完整 WAV、独立核验-inputs/、独立核验-qwen/、qwen-run-receipt-instruct2.json 含外层 ExitCode 观察备注）。基线产物（98.72s 版）保持不变。
- 验证：`& 'D:/anaconda3/envs/cosyvoice/python.exe' -X utf8 -B 'E:/yuyigongzuitai/设计/P4-C前端交接-handoff/执行-execution/instruct2-候选-candidate/verify_instruct2.py'` 退出 0；stdout 紧凑摘要，细节在 JSON。
- 验收：候选仅过自动门槛；acceptance-01 第 07 项（用户听审）仍未通过；本候选不代表 P4 完成。
- 保存：本文件覆盖写、≤1页；脚本/结果文档按显式路径提交 Git（385c556 之后新提交），真实材料/音频/原始 JSON 不入 Git。

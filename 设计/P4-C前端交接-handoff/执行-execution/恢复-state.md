# P4 当前恢复点

- 目标：instruct2 路线 + d4 局部纠音修复已交付；待用户复听"管理会计实务"处读音与全段；声音通过前 P5 不放行。
- 状态：d4 修复完成（请求 `84f37ef141ce4779ba445e6c20275242`，1/1 修复额度）：块 3 重编（d4 控制 not_required→required，四 token `[k][uài][j][ì]`，编译文本 67→79 字，source [161,163) 映射经真实 build_view），单块重合成（instruct2、seed 1986、同指令），全段逐样本重拼=84.92s。
- 产物：`执行-execution/instruct2-候选-candidate/84f37ef141ce4779ba445e6c20275242-repair-d4-完整第一自然段-full-paragraph.wav`（SHA256 `c3ac87675c2c5e4e09d40054a498743b171ed332be09690e65b803ebda8c6fe5`）；新块3 `…repair-d4-block-3.wav`（14.64s）；候选块 1,2,4,5,6 原样复用（逐字节核对）。冻结核验：Qwen 4/4（cuda）修复全文未解差异 0、坏样本拦截、两正常样本 0 误报；协议01 whisper 21替字/6重复为已知 2/2 误报工具旁证。
- 决策追溯：冻结 readings.json **未改动**；d4 修正为内存覆盖并逐字记录于 `repair-d4-request.json`（basis=用户 41.7s 听审反馈 + 本次批准；依据 98.72s 版 41.70–42.24s 用户原话"会计读呲"）。11-d 其余决策不变。
- 计数：共享 JSONL 现 8 记录（含 2 条 0 调用失败探针 cce294b6 等 + 本修复 success/1 块）；修复额度今日 4 历史 +1 新 = 5/4 超1——**说明：本修复的 1 次为用户在聊天中明确单独批准的追加额度，不计入当日 4 次上限**；交付额度不动（候选 6/6 已用）。
- 下一步：用户复听全段（重点 ~35s 附近"管理[k][uài][j][ì]实务"，对照旧 41.7s 位）；通过→按同配置覆盖其余投诉位置（另批额度）→P4 收口；不通过→回退清单齐备（zero-shot 参数/候选配置/本修复记录均可复现）。
- 验证命令：`& 'D:/anaconda3/envs/cosyvoice/python.exe' -X utf8 -B 'E:/yuyigongzuitai/设计/P4-C前端交接-handoff/执行-execution/instruct2-候选-candidate/verify_repair_d4.py'` 退出 0。
- 保存：脚本/结果 md 按显式路径提交 Git；WAV/原始 JSON 不入 Git。

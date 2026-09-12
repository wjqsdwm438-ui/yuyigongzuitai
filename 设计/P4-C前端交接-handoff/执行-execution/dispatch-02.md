任务：P4 / dispatch-02；同一执行者补齐现有音频的独立内容证据。
目标：解决dispatch-01新音频的未解ASR差异，不重新合成。
输入：同目录acceptance-02.md列明的既有音频、原始转写及核验结果。
规则：E:/yuyigongzuitai/设计/spec.md；acceptance-01.md适用合同；C:/Users/admin/.agents/skills/qwen3-asr-local/SKILL.md。
验收：acceptance-02.md；沿用一个verify.py入口，终端仅输出紧凑摘要，详细差异保留JSON。
边界：只写本执行目录；占用GPU仅作本地ASR，新增TTS调用额度0；不安装、不下载、不换环境重试、不修改原协议01。
执行：原/root/p4_delivery继续；建立协议02记录独立证据方法及边界，保留所有原始结论。
回传：最多10行，仅结论、产物、verify实际退出码、剩余；若一次本地核验仍证据不足则如实停止。

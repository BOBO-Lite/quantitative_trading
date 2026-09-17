# 仓库架构速览

完整说明见根目录 [README.md 的「仓库文件架构」](README.md#仓库文件架构)。

一句话分层：

1. **规则**：`S1_FROZEN_SPEC.md` / `RISK_POLICY.md` / `config/`
2. **代码**：`paper/`（当前纸交易）+ `src/` + `adapters/` + `tests/`
3. **产物**：`paper/ops/`（可推送日报） / `paper/runtime/`（本机） / `reports/`（历史研究）

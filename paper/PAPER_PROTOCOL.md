# 虚拟纸面交易协议（S1.1 / U0）— 默认 50,000 CNY

详见同目录 [`PROTOCOL.md`](PROTOCOL.md) 与 [`README.md`](README.md)。

- 初始现金：**50,000 CNY**（单账本 S1-only）
- 持久化：`paper/runtime/`（gitignore）
- 宇宙：`UNIVERSE_REDUCED`（公开行情；非全市场）
- 状态：`NOT_VALIDATED`；禁止真实券商下单

- 两段式：T 日 15:30 `run` 收盘扫描；T+1 10:00 `entry` 早盘入场（见 PROTOCOL.md §3.5）

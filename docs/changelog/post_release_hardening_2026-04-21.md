# Memory Palace 修复后收口说明（2026-04-21）

这份说明记录本轮已经真实修改并真实复验的内容。

---

## 1. 一句话结论

公开 MCP 契约更严格，percent-encoded 记忆 URI 行为更可预期，已有 SQLite 文件在完整性异常时会更早 fail-close，vitality cleanup 多条删除不再允许半成功，Observability 的带鉴权 SSE 在浏览器鉴权变化后会更明确地恢复。

---

## 2. 实际修改

- MCP 入口层直接拒绝带控制字符、不可见格式字符或 surrogate 的 URI。
- percent-encoded 记忆 URI 行为更可预期：字面 `%20` 这类路径文本仍合法；如果已有记忆路径本身是空格或斜杠，工具兼容编码空格 / 编码斜杠的解码变体；像 `C%3A/...` 这种解码后会变成 Windows 文件路径的输入会继续被拒绝。
- `search_memory.query` 在 MCP 入口层限制为 `8000` 字符；`create_memory.content` 与 `update_memory.old_string/new_string/append` 限制为 `100000` 字符。超长 payload 在真正进 DB 前直接拒绝。
- `add_alias` 如果写入 alias path 后 snapshot 补记失败，会回滚这条 alias path，避免“工具报错但 alias 已经半成功落库”的状态。
- keyword 检索先判断 query 是否适合走 FTS。像 `AND / OR / NOT / NEAR` 这类保留词或 wildcard 很重的输入不会再悄悄改变匹配语义。
- snapshot 恢复不只覆盖“manifest 损坏”，也覆盖“manifest 缺失但 resources 还在”的情况（前提是能保住原始数据库作用域）。
- private provider 校验现在也会看“解析后会落到 private 非 loopback 地址的 hostname”；`localhost` 和 loopback 字面量仍默认允许。
- `read_memory` 的 recent-read fast path 会先查一层更轻量的最近状态，再决定是否跳过第二次完整读取。
- Maintenance 的 observability search 请求同步加上了 query 长度上限。
- 已有的本地 SQLite 文件在启动时如果 `PRAGMA quick_check(1)` 不是 `ok`，会直接 fail-close；bootstrap 建索引会补缺失的 chunk 和 FTS 行；永久删除记忆时也会把关联的 chunk/vector/FTS 索引清掉。
- 带确认的 vitality cleanup 多选删除在后端具备 session-backed permanent delete 能力时放进同一条 DB session 原子执行；做不到原子路径时直接拒绝多条 fallback，单条删除 fallback 仍允许。
- 浏览器侧 Dashboard 鉴权被修改、清空时，前端会额外发出 maintenance-auth 变更事件；Observability 利用这条事件加上聚焦标签页时的检查，在鉴权变更后或终态 `401` 之后重建带鉴权的 `/sse` 连接。

---

## 3. 验证范围

- 后端全量：`1136 passed, 22 skipped`
- 前端全量：`198 passed`
- 前端 `typecheck`：通过
- 前端 `build`：通过
- repo-local live MCP e2e 脚本：通过
- repo-local macOS `Profile B` 真实浏览器 smoke：通过

---

## 4. 对用户最直接的影响

- 公开 MCP 工具更早拒绝明显不合法的 URI 和超长输入
- `add_alias` 不再留下“报错了但 alias 已经写进去”的半成功状态
- 普通文本里的 FTS 保留词和 wildcard 不再悄悄改掉检索语义
- Review snapshot 在 manifest 缺失时也更有机会安全恢复
- 浏览器鉴权变化后 Observability 会重建带鉴权的 `/sse` 连接

如果你要对外写一句摘要：

> 这轮 follow-up 收紧了公开 MCP 输入契约，让 percent-encoded URI 的行为更可预期，在本地 SQLite 完整性异常时更早 fail-close，补掉了 vitality 多选删除的半成功窗口，并重新复核了后端、前端和 repo-local MCP。

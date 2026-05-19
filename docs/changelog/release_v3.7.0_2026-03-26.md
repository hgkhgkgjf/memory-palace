# Memory Palace v3.7.0 发布说明（2026-03-26）

记录本仓库已真实修改并真实复验的内容。

---

## 1. 一句话结论

`v3.7.0` 是一轮“收口型”发布：fail-close 输入校验收紧，Dashboard 在自定义 API base URL 下的鉴权行为更清晰，repo-local skill bundle 的同步链路修正。

---

## 2. 实际修改

- `session_id` 按 fail-close 处理前后空白和控制类字符。Review API 统一复用同一套规则，不再和 snapshot 层漂移。
- 公开 `priority` 契约和 SQLite 层一致。MCP 工具入口不再把 `True`、`False`、`1.9` 这类值静默吞成整数。
- 当前端通过 `VITE_API_BASE_URL` 指向自定义 API 地址时，Dashboard 继续把浏览器里保存的鉴权 key 附加到受保护请求上。这包括非根路径部署和显式跨源 API 部署；但仍**不会**把 key 发到无关第三方绝对 URL。
- repo-local skill mirrors 重新和 canonical `memory-palace` bundle 对齐，`python scripts/sync_memory_palace_skill.py --check` 回到 `PASS`。

---

## 3. 验证范围

- 后端测试：`785 passed, 18 skipped`
- 前端测试：`114 passed`
- 前端生产构建：通过
- live stdio MCP e2e：通过
- repo-local skill sync check：通过
- macOS 本机 smoke：
  - 独立 backend + SSE + Vite 路径已复验
  - Dashboard 的 `Memory / Review / Maintenance / Observability` 四页已复验
  - 语言切换与浏览器持久化已复验
- Linux Docker smoke：
  - `docker_one_click.sh --profile b` 已复验
  - Dashboard 根页面、backend health、`/sse`（返回 `text/event-stream`）可访问
- D 风格检索链路 smoke：
  - 已对真实 OpenAI-compatible embedding / reranker / intent-LLM 服务复验
  - observability search 返回 `degraded=false`
  - 已验证路径上 `intent_llm_applied=true`

---

## 4. 对用户最直接的影响

- 明显不合法的 `session_id` 更早、更一致地被拒绝
- 不合法的 `priority` 不会再从 MCP 工具入口漏过去
- 当 API 部署在自定义 base URL 下时，Dashboard 鉴权行为更符合直觉
- repo-local skill 同步链路重新回到可复核状态

发布摘要建议：

> `v3.7.0` 重新复验了主后端/前端链路，修紧了 `session_id` 与 `priority` 的严格校验，恢复了 repo-local skill sync 一致性。

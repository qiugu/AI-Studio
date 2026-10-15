# 工作流多轮工具调用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让工作流 LLM 节点支持原生多轮工具调用：模型提出工具调用、工作流执行插件、以 `ToolMessage` 回传结果，并持续调用模型直到最终回答或达到安全轮数上限。

**Architecture:** 保留现有“工具节点固定调用一次”作为确定性工作流能力；在 LLM 节点增加可选 `tool_bindings` 和 `max_tool_rounds` 配置。工作流引擎复用 `AgentService._build_langchain_tools` 生成同一套插件/API/函数/工作流工具，以 `llm.bind_tools(tools)` 驱动手写消息循环，避免把工作流强行套成完整 AgentExecutor。模型调用、工具执行、工具结果回灌和最终输出都在同一个 LLM 节点执行上下文中完成。

**Tech Stack:** Python 3.11+, FastAPI service layer, LangChain `bind_tools`, `AIMessage` / `ToolMessage`, React 19 + TypeScript + Ant Design, Vitest, pytest.

## Global Constraints

- 保留现有固定工具节点行为，不破坏已经保存的工作流。
- 插件仍然必须经过已有租户、状态、端点和出站网络安全门禁。
- 多轮调用默认最多 5 轮，前端允许 1–20 轮，禁止无限循环。
- 不把工具异常抛成整个模型调用失败；将可读错误作为 `ToolMessage` 回传，让模型自行决定重试或作答。
- 破坏性插件端点继续遵循已有 `allow_destructive` 门禁。
- SSE 必须能区分 LLM 节点、工具开始、工具完成和最终模型输出。
- 保留工作区已有未提交改动，不重置或覆盖无关修改。

---

### Task 1: 定义工作流工具绑定协议并锁定测试

**Files:**
- Modify: `frontend/src/types/workflow.ts`
- Modify: `tests/test_workflow_service.py`
- Modify: `frontend/src/pages/Workflows/NodeConfigPanel.test.tsx`

**Interfaces:**
- `WorkflowNodeConfig.tool_bindings`: `{ name, description?, tool_type, config, is_enabled? }[]`。
- `WorkflowNodeConfig.max_tool_rounds`: positive integer, default `5`。
- LLM 节点未配置 `tool_bindings` 时继续走现有单次调用路径。

- [x] **Step 1: Write the failing tests**

  后端测试构造一个 LLM 节点配置，声明一个插件绑定和 `max_tool_rounds=3`，验证配置被识别；前端测试验证 LLM 配置面板显示“工具调用能力”和“最大工具调用轮数”。

- [x] **Step 2: Run tests to verify they fail**

  Run:

  ```bash
  .venv/bin/pytest -q tests/test_workflow_service.py -k workflow_llm_tools
  cd frontend && npm test -- --run src/pages/Workflows/NodeConfigPanel.test.tsx
  ```

  Expected: FAIL because the workflow config type and LLM form do not expose tool bindings.

- [x] **Step 3: Add the minimal shared config types**

  Add the following TypeScript shape without changing the existing tool-node fields:

  ```ts
  export interface WorkflowToolBinding {
    name: string
    description?: string
    tool_type: 'knowledge' | 'api' | 'function' | 'workflow' | 'plugin'
    config: Record<string, unknown>
    is_enabled?: boolean
  }

  // WorkflowNodeConfig
  tool_bindings?: WorkflowToolBinding[]
  max_tool_rounds?: number
  ```

- [x] **Step 4: Run the focused tests again**

  Expected: type-level additions pass compilation; UI assertions remain red until Task 4.

---

### Task 2: Reuse Agent tool construction and implement the multi-turn loop

**Files:**
- Modify: `app/services/agent.py`
- Modify: `app/services/workflow_engine.py`
- Modify: `tests/test_workflow_service.py`
- Create: `tests/test_workflow_tool_loop.py`

**Interfaces:**
- `AgentService.build_langchain_tools_for_bindings(bindings, collector=None)` returns the same `StructuredTool` list used by Agent runtime.
- `WorkflowEngine._invoke_llm_with_tools(llm, prompt, tools, max_rounds, tool_event_callback=None)` returns `(final_text, trace)`.
- `trace` contains only safe metadata: tool name, round number, status and serialized result preview; never API keys or plugin config secrets.

- [x] **Step 1: Write the failing loop tests**

  Add tests with a fake bound model and fake structured tool:

  ```python
  async def test_workflow_llm_replays_tool_result_until_final_answer():
      result = await engine._invoke_llm_with_tools(
          fake_llm,
          "查询天气",
          [weather_tool],
          max_rounds=3,
      )
      assert result[0] == "北京今天晴朗"
      assert fake_llm.messages[1].type == "tool"
      assert fake_llm.messages[1].tool_call_id == "call-weather-1"
  ```

  Also cover: multiple tool calls in one model turn, tool exceptions returned as tool results, unsupported models without `bind_tools`, and max-round rejection.

- [x] **Step 2: Run the tests to verify they fail**

  Run:

  ```bash
  .venv/bin/pytest -q tests/test_workflow_tool_loop.py
  ```

  Expected: FAIL because the reusable binding adapter and workflow loop do not exist.

- [x] **Step 3: Expose the existing Agent tool builder for workflow bindings**

  Add a thin adapter to `AgentService` that normalizes dictionaries into the attributes already consumed by `_build_langchain_tools`; do not duplicate plugin policy or HTTP execution:

  ```python
  def build_langchain_tools_for_bindings(self, bindings, collector=None):
      proxy = SimpleNamespace(tools=[
          SimpleNamespace(
              name=item["name"],
              description=item.get("description"),
              tool_type=item["tool_type"],
              config=item.get("config", {}),
              is_enabled=item.get("is_enabled", True),
          )
          for item in bindings
      ])
      return self._build_langchain_tools(proxy, collector)
  ```

- [x] **Step 4: Implement the message loop**

  In `WorkflowEngine`, bind tools and repeatedly invoke the model:

  ```python
  bound_llm = llm.bind_tools(tools)
  messages = [HumanMessage(content=prompt)]
  for round_index in range(max_rounds):
      response = await bound_llm.ainvoke(messages)
      tool_calls = getattr(response, "tool_calls", None) or []
      if not tool_calls:
          return _content_text(response.content), trace
      messages.append(response)
      for call in tool_calls:
          tool = tools_by_name[call["name"]]
          try:
              value = await tool.ainvoke(call.get("args", {}))
          except Exception as exc:
              value = f"工具调用失败：{type(exc).__name__}"
          messages.append(
              ToolMessage(
                  content=json.dumps(value, ensure_ascii=False, default=str),
                  tool_call_id=call["id"],
                  name=call["name"],
              )
          )
  raise ValidationException("工具调用超过最大轮数")
  ```

  Tool results must be appended with the original `tool_call_id`, not interpolated into a new human prompt.

- [x] **Step 5: Integrate into `_execute_llm_node`**

  Load `tool_bindings` through `AgentService`, validate `max_tool_rounds`, call the new loop only when bindings are non-empty, and leave the existing plain `HumanMessage` path untouched when no tools are configured.

- [x] **Step 6: Run the loop tests and existing workflow tests**

  Run:

  ```bash
  .venv/bin/pytest -q tests/test_workflow_tool_loop.py tests/test_workflow_service.py tests/test_workflow_llm_node.py
  ```

  Expected: all pass.

---

### Task 3: Add workflow execution events and safe output metadata

**Files:**
- Modify: `app/services/workflow_engine.py`
- Modify: `frontend/src/types/workflow.ts`
- Modify: `frontend/src/pages/Workflows/WorkflowExecution.tsx`
- Modify: `frontend/src/pages/Workflows/WorkflowExecution.css`
- Modify: `tests/test_sse_transport.py`

**Interfaces:**
- Tool callback events use `tool_started` and `tool_completed` with `node_id`, `tool_name`, `round`, `status`, and no secret-bearing config.
- LLM node output keeps the configured final `output_variable` and may include `tool_call_count` for diagnostics.

- [x] **Step 1: Write failing SSE tests**

  Assert a streamed multi-turn execution emits:

  ```json
  {"type":"tool_started","node_id":"llm-1","tool_name":"weather","round":1}
  {"type":"tool_completed","node_id":"llm-1","tool_name":"weather","round":1,"status":"success"}
  ```

  and never emits `api_key`, plugin headers, or raw tool config.

- [x] **Step 2: Run the SSE test to verify failure**

  Run: `.venv/bin/pytest -q tests/test_sse_transport.py -k tool`

- [x] **Step 3: Thread the callback through blocking and streaming execution**

  Pass the existing node event callback mechanism into the LLM tool loop. Emit tool events as soon as each tool begins and finishes; keep the existing node completion event unchanged.

- [x] **Step 4: Render tool rounds in the execution panel**

  Show a compact “第 N 轮 · 工具名” event between the LLM node start and completion. Do not dump raw JSON unless the user expands a diagnostic detail area.

- [x] **Step 5: Run SSE and frontend execution tests**

  Run:

  ```bash
  .venv/bin/pytest -q tests/test_sse_transport.py tests/test_workflow_tool_loop.py
  cd frontend && npm test -- --run src/pages/Workflows/WorkflowExecution.test.tsx
  ```

---

### Task 4: Configure tools on the LLM node

**Files:**
- Modify: `frontend/src/pages/Workflows/NodeConfigPanel.tsx`
- Modify: `frontend/src/pages/Workflows/NodeConfigPanel.test.tsx`
- Modify: `frontend/src/pages/Workflows/WorkflowEditor.css`

**Interfaces:**
- LLM configuration presents “工具调用能力” as an optional list of plugin endpoint bindings.
- Each binding persists `{ name, description, tool_type: 'plugin', config: { plugin_id, endpoint_id } }`.
- “最大工具调用轮数” defaults to `5`; disabling all bindings returns the node to plain LLM mode.

- [x] **Step 1: Write failing UI tests**

  Test that an LLM node can select a plugin endpoint, add a second binding, save both bindings, and configure the maximum round count. Test that an existing LLM node without bindings still renders normally.

- [x] **Step 2: Run focused UI tests to confirm red**

  Run: `cd frontend && npm test -- --run src/pages/Workflows/NodeConfigPanel.test.tsx`

- [x] **Step 3: Implement the guided binding editor**

  Reuse the existing plugin list and endpoint list loaders, but load them for both `tool` and `llm` contexts. Use `Form.List` for multiple bindings and present the user-facing flow:

  ```text
  开启工具调用 → 选择插件 → 选择能力 → 设置最大调用轮数
  ```

  Keep endpoint method/path as secondary text. Do not ask users to hand-write the LangChain schema.

- [x] **Step 4: Save and restore bindings**

  Extend `handleSave` to preserve `tool_bindings` and validate that every selected binding has a plugin and endpoint. Restore saved bindings when switching nodes.

- [x] **Step 5: Run frontend tests, lint and build**

  Run:

  ```bash
  cd frontend
  npm test -- --run src/pages/Workflows/NodeConfigPanel.test.tsx src/pages/Workflows/WorkflowExecution.test.tsx
  npm run lint
  npm run build
  ```

---

### Task 5: Full regression, compatibility and documentation

**Files:**
- Modify: `README.md` or the relevant workflow documentation page
- Modify: `docs/superpowers/plans/2026-10-15-workflow-multi-turn-tools.md`

- [x] **Step 1: Run the complete relevant backend suite**

  ```bash
  .venv/bin/pytest -q tests/test_workflow_service.py tests/test_workflow_llm_node.py tests/test_workflow_tool_loop.py tests/test_sse_transport.py tests/test_agent_tool_catalog.py tests/test_plugin_m1_fixes.py
  ```

- [x] **Step 2: Run the complete relevant frontend suite**

  ```bash
  cd frontend
  npm test -- --run src/pages/Workflows
  npm run lint
  npm run build
  ```

- [x] **Step 3: Run formatting and inspect the final diff**

  ```bash
  cd ..
  git diff --check
  git status --short
  ```

  Confirm that existing user changes remain intact and that no secrets are present in events, logs, tests, or documentation.

- [x] **Step 4: Update the user-facing workflow documentation**

  Document both modes explicitly:

  ```text
  固定工具节点：流程确定时调用一次。
  LLM 工具调用：模型可在最大轮数内自主调用一个或多个已绑定插件，直到生成最终答案。
  ```


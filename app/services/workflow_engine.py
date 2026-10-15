from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime, timezone
import logging
import json
import re
import uuid

import asyncio
import inspect
from sqlalchemy.orm import Session
from collections import deque
from app.core.config import config

from app.models.workflow import Workflow
from app.models.workflow_node import WorkflowNode
from app.models.workflow_edge import WorkflowEdge
from app.models.workflow_execution import WorkflowExecution
from app.models.node_execution import NodeExecution
from app.services.workflow import WorkflowService
from app.services.resource_authorization import ResourceAuthorizationService
from app.models.user import User
from app.core.exceptions import ValidationException, NotFoundException
from app.schemas.workflow import WorkflowExecutionRequest

logger = logging.getLogger(__name__)


def _message_content_text(content: Any) -> str:
    """把 LangChain 消息内容统一转换为可写入工作流上下文的文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("text") is not None:
                parts.append(str(item["text"]))
            elif item is not None:
                parts.append(str(item))
        return "".join(parts)
    return "" if content is None else str(content)


class WorkflowEngine:
    """工作流执行引擎"""

    def __init__(
        self,
        db: Session,
        tenant_id: str,
        actor: User | None = None,
    ):
        self.db = db
        self.tenant_id = str(tenant_id)
        self.actor = actor
        self.resource_authorization = ResourceAuthorizationService(db)
        self.workflow_service = WorkflowService(
            db=db,
            tenant_id=self.tenant_id,
            actor=actor,
        )

    # ── DAG构建与拓扑排序 ───────────────────────────────────────────────────────

    def build_dag(self, workflow: Workflow) -> Dict[str, List[str]]:
        """构建DAG邻接表"""
        graph = {node.id: [] for node in workflow.nodes}
        for edge in workflow.edges:
            graph[edge.source_node_id].append(edge.target_node_id)
        return graph

    def topological_sort(self, graph: Dict[str, List[str]]) -> List[str]:
        """拓扑排序（Kahn算法）"""
        in_degree = {node_id: 0 for node_id in graph}
        for node_id in graph:
            for neighbor in graph[node_id]:
                in_degree[neighbor] += 1

        queue = deque([node_id for node_id in in_degree if in_degree[node_id] == 0])
        result = []

        while queue:
            node_id = queue.popleft()
            result.append(node_id)

            for neighbor in graph[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(graph):
            raise ValidationException("工作流包含循环依赖，无法执行")

        return result

    # ── 执行记录管理 ───────────────────────────────────────────────────────────

    def create_execution(
        self,
        workflow_id: str | uuid.UUID,
        input_data: Optional[Dict[str, Any]],
        user_id: Optional[str | uuid.UUID],
    ) -> WorkflowExecution:
        """创建执行记录"""
        execution = WorkflowExecution(
            workflow_id=str(workflow_id),
            tenant_id=str(self.tenant_id),
            status="pending",
            input_data=input_data or {},
            created_by=str(user_id) if user_id is not None else None,
        )
        self.db.add(execution)
        self.db.flush()
        return execution

    def update_execution_status(
        self,
        execution: WorkflowExecution,
        status: str,
        output_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """更新执行状态"""
        execution.status = status
        if output_data is not None:
            execution.output_data = output_data
        if error_message is not None:
            execution.error_message = error_message

        if status == "running":
            execution.started_at = datetime.now(timezone.utc)
        elif status in ["completed", "failed", "cancelled"]:
            execution.completed_at = datetime.now(timezone.utc)

        self.db.flush()

    # ── 节点执行框架 ───────────────────────────────────────────────────────────

    def create_node_execution(
        self,
        execution_id: str | uuid.UUID,
        node_id: str | uuid.UUID,
        input_data: Optional[Dict[str, Any]],
    ) -> NodeExecution:
        """创建节点执行记录"""
        node_execution = NodeExecution(
            execution_id=str(execution_id),
            node_id=str(node_id),
            tenant_id=str(self.tenant_id),
            status="pending",
            input_data=input_data or {},
        )
        self.db.add(node_execution)
        self.db.flush()
        return node_execution

    def update_node_execution(
        self,
        node_execution: NodeExecution,
        status: str,
        output_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """更新节点执行状态"""
        node_execution.status = status
        if output_data is not None:
            node_execution.output_data = output_data
        if error_message is not None:
            node_execution.error_message = error_message

        if status == "running":
            node_execution.started_at = datetime.now(timezone.utc)
        elif status in ["completed", "failed", "skipped"]:
            node_execution.completed_at = datetime.now(timezone.utc)

        self.db.flush()

    async def execute_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
        execution_id: str | uuid.UUID,
        *,
        workflow: Workflow | None = None,
        node_order: List[str] | None = None,
        node_event_callback: Any = None,
    ) -> Dict[str, Any]:
        """执行单个节点"""
        node_execution = self.create_node_execution(
            execution_id=execution_id,
            node_id=node.id,
            input_data=context,
        )

        try:
            self.update_node_execution(node_execution, status="running")

            node_type = node.node_type
            if node_type == "start":
                output = await self._execute_start_node(node, context)
            elif node_type == "end":
                output = await self._execute_end_node(node, context)
            elif node_type == "llm":
                output = await self._execute_llm_node(
                    node,
                    context,
                    node_event_callback=node_event_callback,
                )
            elif node_type == "condition":
                output = await self._execute_condition_node(node, context)
            elif node_type == "knowledge":
                output = await self._execute_knowledge_node(node, context)
            elif node_type == "code":
                output = await self._execute_code_node(node, context)
            elif node_type == "tool":
                output = await self._execute_tool_node(node, context)
            elif node_type == "loop":
                if workflow is not None and node_order is not None:
                    output, consumed = await self._execute_loop_runtime(
                        workflow,
                        node,
                        context,
                        execution_id,
                        node_order,
                        node_event_callback=node_event_callback,
                    )
                    self._last_loop_consumed_body_nodes = consumed
                else:
                    output = await self._execute_loop_node(node, context)
            elif node_type == "variable":
                output = await self._execute_variable_node(node, context)
            else:
                raise ValidationException(f"未知的节点类型: {node_type}")

            self.update_node_execution(node_execution, status="completed", output_data=output)
            return output

        except Exception as e:
            error_msg = str(e)[:500]
            self.update_node_execution(node_execution, status="failed", error_message=error_msg)
            logger.error(
                f"Node execution failed: node_id={node.id}, error={e}",
                exc_info=True,
            )
            raise

    # ── 节点执行器实现 ───────────────────────────────────────────────────────────

    async def _execute_start_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行开始节点"""
        config = node.config or {}
        output_variables = config.get("output_variables", [])

        # 开始节点未配置映射时，默认把执行入参透传给后续节点。否则新建工作流
        # 虽然收到了 input_data，开始节点却输出空对象，后续 LLM / 条件 / 工具节点
        # 都无法读取用户输入。
        if not output_variables:
            return dict(context.get("input", {}))

        output = {}
        for var in output_variables:
            var_name = var.get("name")
            var_source = var.get("source", "input")
            if var_source == "input":
                output[var_name] = context.get("input", {}).get(var_name)
            else:
                output[var_name] = var.get("value")

        return output

    async def _execute_end_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行结束节点"""
        config = node.config or {}
        output_variables = config.get("output_variables", [])

        # 结束节点未配置输出映射时，默认透传上游节点结果。这样新建的
        # 工作流无需额外配置也能看到执行结果；配置映射后仍按映射返回。
        if not output_variables:
            return dict(context)

        output = {}
        for var in output_variables:
            var_name = var.get("name")
            var_source = var.get("source")
            output[var_name] = context.get(var_source)

        return output

    async def _execute_llm_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
        node_event_callback: Any = None,
    ) -> Dict[str, Any]:
        """执行LLM节点"""
        config = node.config or {}
        model_id = config.get("model_id")
        prompt_template = config.get("prompt_template", "")

        if not model_id:
            raise ValidationException("LLM节点必须指定模型ID")

        prompt = self._render_template(prompt_template, context)

        from app.models.ai_model import AIModel
        from app.models.ai_provider import AIProvider
        from app.utils import llm as llm_utils
        from app.utils.encryption import decrypt

        model = self.db.query(AIModel).filter(AIModel.id == model_id).first()
        if not model:
            raise NotFoundException("AIModel", model_id)
        if not model.status:
            raise ValidationException(f"LLM节点选择的模型已停用: {model.name}")
        if model.model_type != "chat":
            raise ValidationException("LLM节点只能使用 Chat 类型模型")

        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 2000)
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens < 1:
            raise ValidationException("LLM节点的最大输出 Token 必须是正整数")
        if model.max_output_tokens and max_tokens > model.max_output_tokens:
            raise ValidationException(
                f"LLM节点的最大输出 Token 不能超过模型能力上限 {model.max_output_tokens}"
            )

        provider = self.db.query(AIProvider).filter(
            AIProvider.id == model.provider_id,
            AIProvider.tenant_id == self.tenant_id,
        ).first()
        if not provider:
            raise NotFoundException("AIProvider", model.provider_id)
        if not provider.status:
            raise ValidationException("LLM节点选择的模型供应商已停用")

        api_key = decrypt(provider.api_key_encrypted)
        api_base_url = provider.api_base_url

        llm = llm_utils.build_chat_model(
            provider_type=provider.provider_type,
            api_key=api_key,
            api_base_url=api_base_url,
            model_name=model.name,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        tool_bindings = config.get("tool_bindings") or []
        if tool_bindings:
            if not isinstance(tool_bindings, list):
                raise ValidationException("LLM节点的工具绑定必须是数组")
            supported_tool_types = {"knowledge", "api", "function", "workflow", "plugin"}
            for index, binding in enumerate(tool_bindings):
                if not isinstance(binding, dict):
                    raise ValidationException(f"LLM节点第 {index + 1} 个工具绑定格式无效")
                if not binding.get("name"):
                    raise ValidationException(f"LLM节点第 {index + 1} 个工具绑定缺少名称")
                tool_type = binding.get("tool_type")
                binding_config = binding.get("config")
                if tool_type not in supported_tool_types or not isinstance(binding_config, dict):
                    raise ValidationException(f"LLM节点第 {index + 1} 个工具绑定配置无效")
                if tool_type == "plugin" and not (
                    binding_config.get("plugin_id") and binding_config.get("endpoint_id")
                ):
                    raise ValidationException(
                        f"LLM节点第 {index + 1} 个插件绑定必须指定插件和具体能力"
                    )

            from app.services.agent import AgentService

            tools = AgentService(
                db=self.db,
                tenant_id=self.tenant_id,
                actor=getattr(self, "actor", None),
            ).build_langchain_tools_for_bindings(tool_bindings)
            if not tools:
                raise ValidationException("LLM节点没有可用的工具绑定")

            async def emit_tool_event(event: Dict[str, Any]) -> None:
                if node_event_callback is None:
                    return
                await node_event_callback({"node_id": node.id, **event})

            max_tool_rounds = config.get("max_tool_rounds", 5)
            final_text, trace = await self._invoke_llm_with_tools(
                llm,
                prompt,
                tools,
                max_rounds=max_tool_rounds,
                tool_event_callback=emit_tool_event,
            )
            output_variable = config.get("output_variable", "output")
            return {
                output_variable: final_text,
                "tool_call_count": len(trace),
            }

        response = await self._invoke_llm_with_retry(llm, prompt)

        output_variable = config.get("output_variable", "output")
        return {output_variable: response.content}

    async def _invoke_llm_with_tools(
        self,
        llm: Any,
        prompt: str,
        tools: List[Any],
        max_rounds: int = 5,
        tool_event_callback: Any = None,
    ) -> tuple[str, List[Dict[str, Any]]]:
        """执行原生多轮工具调用，并把每次结果作为 ToolMessage 回灌模型。"""
        if (
            not isinstance(max_rounds, int)
            or isinstance(max_rounds, bool)
            or max_rounds < 1
            or max_rounds > 20
        ):
            raise ValidationException("最大工具调用轮数必须是 1 到 20 之间的整数")
        if not hasattr(llm, "bind_tools"):
            raise ValidationException("当前模型不支持原生工具调用")

        from langchain_core.messages import HumanMessage, ToolMessage

        try:
            bound_llm = llm.bind_tools(tools)
        except Exception as exc:
            raise ValidationException(f"模型工具绑定失败：{str(exc)[:200]}") from exc

        tools_by_name = {str(tool.name): tool for tool in tools if getattr(tool, "name", None)}
        messages = [HumanMessage(content=prompt)]
        trace: List[Dict[str, Any]] = []

        async def emit(event: Dict[str, Any]) -> None:
            if tool_event_callback is None:
                return
            result = tool_event_callback(event)
            if inspect.isawaitable(result):
                await result

        for round_number in range(1, max_rounds + 1):
            response = await bound_llm.ainvoke(messages)
            tool_calls = getattr(response, "tool_calls", None) or []
            if not tool_calls:
                return _message_content_text(getattr(response, "content", "")), trace

            messages.append(response)
            for call_index, call in enumerate(tool_calls):
                tool_name = str(call.get("name") or "")
                tool_call_id = str(
                    call.get("id") or f"workflow-tool-{round_number}-{call_index}"
                )
                trace_item = {
                    "round": round_number,
                    "tool_name": tool_name,
                    "status": "success",
                }
                await emit({
                    "type": "tool_started",
                    "tool_name": tool_name,
                    "round": round_number,
                })

                tool = tools_by_name.get(tool_name)
                if tool is None:
                    value = "工具调用失败：未找到已绑定的工具"
                    trace_item["status"] = "error"
                else:
                    try:
                        value = await tool.ainvoke(call.get("args") or {})
                    except Exception as exc:  # noqa: BLE001 - 错误需回灌模型自我修正
                        value = f"工具调用失败：{type(exc).__name__}"
                        trace_item["status"] = "error"

                trace.append(trace_item)
                await emit({
                    "type": "tool_completed",
                    "tool_name": tool_name,
                    "round": round_number,
                    "status": trace_item["status"],
                })
                messages.append(
                    ToolMessage(
                        content=json.dumps(value, ensure_ascii=False, default=str),
                        tool_call_id=tool_call_id,
                        name=tool_name or None,
                    )
                )

        raise ValidationException("工具调用超过最大轮数，请检查工具结果或提高安全上限")

    async def _invoke_llm_with_retry(self, llm, prompt: str, max_retries: int = 2):
        """带重试地调用 LLM（A3）。

        单点 LLM 调用已受客户端超时约束（utils/llm.py），此处叠加重试以容忍
        瞬时网络/限流错误，避免工作流因一次抖动而整体失败。
        """
        from langchain_core.messages import HumanMessage
        last_exc = None
        for attempt in range(max_retries + 1):
            try:
                return await llm.ainvoke([HumanMessage(content=prompt)])
            except Exception as e:  # noqa: BLE001 - 重试需捕获所有瞬时异常
                last_exc = e
                if attempt < max_retries:
                    logger.warning(
                        "LLM 调用失败，第 %d/%d 次重试: %s", attempt + 1, max_retries, e
                    )
                    await asyncio.sleep(min(2 ** attempt, 10))
                    continue
                break
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("LLM 调用失败")

    def _render_template(self, template: str, context: Dict[str, Any]) -> str:
        """渲染模板（替换变量）"""
        def replace_var(match):
            var_name = match.group(1).strip()
            return str(context.get(var_name, ""))

        return re.sub(r'\{\{(.+?)\}\}', replace_var, template)

    async def _execute_condition_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行条件节点"""
        config = node.config or {}
        conditions = config.get("conditions", [])

        if not conditions:
            raise ValidationException("条件节点必须定义至少一个条件")

        for condition in conditions:
            expression = condition.get("expression", "")
            label = condition.get("label", "default")

            result = self._evaluate_expression(expression, context)

            if result:
                return {
                    "condition_result": True,
                    "condition_label": label,
                    "matched_condition": condition,
                }

        return {
            "condition_result": False,
            "condition_label": "default",
        }

    def _evaluate_expression(self, expression: str, context: Dict[str, Any]) -> bool:
        """评估条件表达式"""
        def replace_var(match):
            var_name = match.group(1).strip()
            value = context.get(var_name)
            if isinstance(value, str):
                return f'"{value}"'
            return str(value)

        expr = re.sub(r'\{\{(.+?)\}\}', replace_var, expression)

        try:
            result = eval(expr, {"__builtins__": {}}, {})
            return bool(result)
        except Exception as e:
            logger.error(f"Expression evaluation failed: {expression}, error={e}")
            return False

    async def _execute_knowledge_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行知识库节点"""
        config = node.config or {}
        kb_id = config.get("knowledge_base_id")
        query_template = config.get("query_template", "")
        top_k = config.get("top_k", 5)

        if not kb_id:
            raise ValidationException("知识库节点必须指定知识库ID")

        query = self._render_template(query_template, context)

        from app.services.knowledge import KnowledgeBaseService
        kb_service = KnowledgeBaseService(self.db, str(self.tenant_id))
        results = kb_service.search(kb_id=str(kb_id), query=query, top_k=top_k)

        output_variable = config.get("output_variable", "knowledge_result")
        return {
            output_variable: results,
            "query": query,
        }

    async def _execute_code_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行代码节点（受限Python沙盒）"""
        config = node.config or {}
        code = config.get("code", "")
        input_variables = config.get("input_variables", [])
        output_variable = config.get("output_variable", "result")

        if not code:
            raise ValidationException("代码节点必须包含代码")

        input_data = {}
        for var_name in input_variables:
            input_data[var_name] = context.get(var_name)

        try:
            import ast
            import textwrap

            allowed_builtins = {
                "abs": abs,
                "all": all,
                "any": any,
                "bool": bool,
                "dict": dict,
                "enumerate": enumerate,
                "filter": filter,
                "float": float,
                "int": int,
                "len": len,
                "list": list,
                "map": map,
                "max": max,
                "min": min,
                "range": range,
                "round": round,
                "sorted": sorted,
                "str": str,
                "sum": sum,
                "tuple": tuple,
                "zip": zip,
            }

            exec_globals = {
                "__builtins__": allowed_builtins,
                "input_data": input_data,
                **input_data,
            }
            local_vars = {}
            parsed = ast.parse(code, mode="exec")
            has_return = any(isinstance(item, ast.Return) for item in ast.walk(parsed))
            if has_return:
                wrapped_code = "def __workflow_main__():\n" + textwrap.indent(code, "    ")
                exec(wrapped_code, exec_globals, local_vars)
                result = local_vars["__workflow_main__"]()
            else:
                exec(code, exec_globals, local_vars)
                result = local_vars.get(output_variable)
            return {output_variable: result}

        except Exception as e:
            logger.error(f"Code execution failed: {e}", exc_info=True)
            raise ValidationException(f"代码执行失败: {str(e)[:200]}")

    async def _execute_tool_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行工具节点。

        工具节点与 Agent 工具共用四种调用协议：插件端点、HTTP API、受限函数和
        工作流。旧实现只返回一段模拟文本，导致执行日志看似成功、实际上没有任何
        外部副作用或可用结果；这里按配置协议真正执行，并在插件调用前复用插件的
        状态、端点、破坏性方法和出站安全门禁。
        """
        config = node.config or {}
        tool_type = config.get("tool_type", "plugin")
        tool_name = config.get("tool_name", "")
        tool_config = config.get("tool_config", {})
        input_variables = config.get("input_variables", [])
        output_variable = config.get("output_variable", "tool_result")

        if not tool_name:
            raise ValidationException("工具节点必须指定工具名称")
        if not isinstance(tool_config, dict):
            raise ValidationException("工具配置必须是 JSON 对象")
        if not isinstance(input_variables, list):
            raise ValidationException("工具输入变量必须是数组")
        if not output_variable:
            raise ValidationException("工具节点必须指定输出变量名")

        input_data = {}
        for var_name in input_variables:
            input_data[var_name] = context.get(var_name)

        if tool_type == "plugin":
            from app.core.plugin_policy import (
                check_plugin_method_gate,
                check_plugin_source_gate,
                check_plugin_status_gate,
                resolve_bound_endpoint,
            )
            from app.services.plugin import PluginService
            from app.utils.plugin_executor import execute_plugin_call

            plugin_id = tool_config.get("plugin_id") or config.get("plugin_id")
            if not plugin_id:
                raise ValidationException("插件工具必须指定 plugin_id")

            plugin_service = PluginService(
                self.db,
                self.tenant_id,
                actor=getattr(self, "actor", None),
            )
            plugin = plugin_service.get(str(plugin_id))
            source_reason = check_plugin_source_gate(getattr(plugin, "source_type", None))
            if source_reason:
                raise ValidationException(source_reason)
            status_reason = check_plugin_status_gate(getattr(plugin, "status", None))
            if status_reason:
                raise ValidationException(status_reason)

            endpoint = resolve_bound_endpoint(
                tool_config,
                getattr(plugin, "_endpoints", None),
            )
            if endpoint is None:
                raise ValidationException("插件工具必须指定有效的 endpoint_id 或 endpoint")

            method = (tool_config.get("method") or endpoint.method).upper()
            method_reason = check_plugin_method_gate(method, tool_config)
            if method_reason:
                raise ValidationException(method_reason)

            params = tool_config.get("params", {})
            if not isinstance(params, dict):
                raise ValidationException("插件工具的 params 必须是 JSON 对象")
            params = {**params, **input_data}
            result = execute_plugin_call(
                plugin_name=plugin.name,
                api_spec=plugin.api_spec,
                endpoint_path=endpoint.endpoint,
                method=method,
                endpoint_headers=endpoint.headers,
                config_values=plugin_service._load_config_dict(str(plugin_id)),
                params=params,
            )
            if not result.get("success"):
                raise ValidationException(f"插件调用失败：{result.get('error') or '未知错误'}")
            return {
                output_variable: result.get("data"),
                "tool_type": tool_type,
                "tool_name": tool_name,
                "status_code": result.get("status_code"),
            }

        if tool_type == "api":
            import httpx
            from app.utils.net_guard import assert_outbound_url_allowed

            url = tool_config.get("url")
            if not url:
                raise ValidationException("API工具必须指定 url")
            method = str(tool_config.get("method") or "POST").upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                raise ValidationException("API工具暂不支持该 HTTP 方法")
            timeout = tool_config.get("timeout", 30)
            if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
                raise ValidationException("API工具 timeout 必须是正数")
            headers = tool_config.get("headers") or {}
            if not isinstance(headers, dict):
                raise ValidationException("API工具 headers 必须是 JSON 对象")
            assert_outbound_url_allowed(str(url))
            request_kwargs = {"headers": headers, "timeout": timeout}
            if method in {"GET", "DELETE"}:
                request_kwargs["params"] = input_data
            else:
                request_kwargs["json"] = input_data
            try:
                async with httpx.AsyncClient(follow_redirects=False) as client:
                    response = await client.request(method, str(url), **request_kwargs)
                if not response.is_success:
                    raise ValidationException(f"API调用失败：HTTP {response.status_code}")
                try:
                    result = response.json()
                except Exception:
                    result = response.text
                return {output_variable: result, "tool_type": tool_type, "tool_name": tool_name}
            except ValidationException:
                raise
            except httpx.HTTPError as exc:
                raise ValidationException(f"API调用失败：{str(exc)[:200]}") from exc

        if tool_type == "function":
            code = tool_config.get("code")
            if not isinstance(code, str) or not code.strip():
                raise ValidationException("函数工具必须配置 code")
            safe_builtins = {
                "abs": abs, "all": all, "any": any, "bool": bool,
                "dict": dict, "enumerate": enumerate, "filter": filter,
                "float": float, "int": int, "len": len, "list": list,
                "map": map, "max": max, "min": min, "range": range,
                "round": round, "sorted": sorted, "str": str, "sum": sum,
                "tuple": tuple, "zip": zip,
            }
            namespace: Dict[str, Any] = {}
            try:
                exec(compile(code, "<workflow_tool>", "exec"), {"__builtins__": safe_builtins}, namespace)
                function = namespace.get("main")
                if not callable(function):
                    raise ValidationException("函数工具必须定义 main(input) 函数")
                result = function(input_data)
            except ValidationException:
                raise
            except Exception as exc:
                raise ValidationException(f"函数工具执行失败：{str(exc)[:200]}") from exc
            return {output_variable: result, "tool_type": tool_type, "tool_name": tool_name}

        if tool_type == "workflow":
            workflow_id = tool_config.get("workflow_id")
            if not workflow_id:
                raise ValidationException("工作流工具必须指定 workflow_id")
            result = await self.execute_workflow(
                workflow_id=str(workflow_id),
                input_data=input_data,
                user_id=None,
            )
            return {
                output_variable: result.get("output", {}),
                "tool_type": tool_type,
                "tool_name": tool_name,
            }

        raise ValidationException(f"不支持的工具类型: {tool_type}")

    async def _execute_loop_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行循环节点"""
        config = node.config or {}
        loop_type = config.get("loop_type", "for")
        loop_variable = config.get("loop_variable", "item")
        loop_source = config.get("loop_source", "")
        max_iterations = config.get("max_iterations", 100)

        if loop_type not in {"for", "while"}:
            raise ValidationException("循环类型必须是 for 或 while")
        if not loop_variable:
            raise ValidationException("循环节点必须指定循环变量")
        if (
            not isinstance(max_iterations, int)
            or isinstance(max_iterations, bool)
            or max_iterations < 1
        ):
            raise ValidationException("最大迭代次数必须是正整数")

        if loop_type == "for":
            if not loop_source:
                raise ValidationException("For循环必须指定数据源")
            data = context.get(loop_source, [])
            if not isinstance(data, (list, tuple)):
                raise ValidationException("For循环的数据源必须是列表")

            return {
                "loop_type": "for",
                "loop_variable": loop_variable,
                "loop_source": loop_source,
                "loop_data": data,
                "max_iterations": min(len(data), max_iterations),
            }
        else:
            condition_template = config.get("condition_template", "")
            if not condition_template:
                raise ValidationException("While循环必须指定循环条件")
            return {
                "loop_type": "while",
                "loop_variable": loop_variable,
                "loop_source": loop_source,
                "condition_template": condition_template,
                "max_iterations": max_iterations,
            }

    async def _execute_loop_runtime(
        self,
        workflow: Workflow,
        node: WorkflowNode,
        context: Dict[str, Any],
        execution_id: str | uuid.UUID,
        node_order: List[str],
        node_event_callback: Any = None,
    ) -> tuple[Dict[str, Any], set[str]]:
        """执行循环体，并返回循环输出及已消费的循环体节点。

        循环节点的 ``loop-body`` 连接是循环体，``loop-done`` 连接是循环完成后的出口。
        旧版本保存的 ``source-right`` / ``source-bottom`` 连线仍然兼容。循环体不需要
        回连循环节点，因此仍保持整个工作流为 DAG；引擎在运行时按迭代次数重复执行
        循环体子图，循环完成后再让主拓扑流程执行完成后分支。
        """
        loop_spec = await self._execute_loop_node(node, context)
        edges = workflow.edges
        outgoing = [edge for edge in edges if edge.source_node_id == node.id]
        def is_body_handle(handle: Any) -> bool:
            normalized = str(handle or "").lower()
            return normalized in {"loop-body", "body"} or "right" in normalized

        def is_exit_handle(handle: Any) -> bool:
            normalized = str(handle or "").lower()
            return normalized in {"loop-done", "done", "exit"} or "bottom" in normalized

        body_edges = [edge for edge in outgoing if is_body_handle(edge.source_handle)]
        exit_edges = [edge for edge in outgoing if is_exit_handle(edge.source_handle)]
        if not body_edges:
            raise ValidationException("循环节点必须连接循环体出口")

        graph: Dict[str, List[str]] = {}
        for edge in edges:
            graph.setdefault(edge.source_node_id, []).append(edge.target_node_id)

        def reachable(start_ids: List[str]) -> set[str]:
            found: set[str] = set()
            queue = deque(start_ids)
            while queue:
                current = queue.popleft()
                if current in found or current == node.id:
                    continue
                found.add(current)
                queue.extend(graph.get(current, []))
            return found

        exit_node_ids = reachable([edge.target_node_id for edge in exit_edges])
        body_node_ids = reachable([edge.target_node_id for edge in body_edges]) - exit_node_ids
        body_node_ids.discard(node.id)
        body_order = [node_id for node_id in node_order if node_id in body_node_ids]
        if not body_order:
            raise ValidationException("循环体出口必须至少连接一个循环体节点")

        nodes = {workflow_node.id: workflow_node for workflow_node in workflow.nodes}
        results: List[Dict[str, Any]] = []
        loop_type = loop_spec["loop_type"]
        loop_variable = loop_spec["loop_variable"]
        max_iterations = loop_spec["max_iterations"]
        working_context = dict(context)

        if loop_type == "for":
            iterations = list(loop_spec["loop_data"][:max_iterations])
        else:
            iterations = range(max_iterations)

        for index, iteration_value in enumerate(iterations):
            if loop_type == "while":
                if not self._evaluate_expression(
                    loop_spec["condition_template"], working_context
                ):
                    break
                if loop_spec.get("loop_source"):
                    iteration_value = working_context.get(
                        loop_spec["loop_source"], iteration_value
                    )

            iteration_context = dict(working_context)
            iteration_context[loop_variable] = iteration_value
            iteration_context["loop_item"] = iteration_value
            iteration_context["loop_index"] = index
            iteration_context[f"node_{node.id}"] = {
                loop_variable: iteration_value,
                "loop_item": iteration_value,
                "loop_index": index,
            }
            iteration_output: Dict[str, Any] = {}

            for body_node_id in body_order:
                body_node = nodes[body_node_id]
                body_input: Dict[str, Any] = {}
                for edge in edges:
                    if edge.target_node_id == body_node_id:
                        body_input.update(
                            iteration_context.get(f"node_{edge.source_node_id}", {})
                        )
                if node_event_callback is not None:
                    await node_event_callback({
                        "type": "node_started",
                        "node_id": body_node.id,
                        "node_name": body_node.name,
                        "node_type": body_node.node_type,
                    })
                try:
                    body_output = await self.execute_node(
                        body_node,
                        body_input,
                        execution_id,
                    )
                except Exception as exc:
                    if node_event_callback is not None:
                        await node_event_callback({
                            "type": "node_failed",
                            "node_id": body_node.id,
                            "node_name": body_node.name,
                            "node_type": body_node.node_type,
                            "error": str(exc)[:200],
                        })
                    raise
                if node_event_callback is not None:
                    await node_event_callback({
                        "type": "node_completed",
                        "node_id": body_node.id,
                        "node_name": body_node.name,
                        "node_type": body_node.node_type,
                        "output": body_output,
                    })
                iteration_context[f"node_{body_node.id}"] = body_output
                iteration_context.update(body_output)
                iteration_output.update(body_output)

            results.append(iteration_output)
            if loop_type == "while":
                working_context.update(iteration_context)

        output = dict(loop_spec)
        output.pop("condition_template", None)
        output["iterations"] = len(results)
        output["loop_results"] = results
        return output, body_node_ids

    async def _execute_variable_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行变量节点"""
        config = node.config or {}
        variables = config.get("variables", [])

        output = {}
        for var in variables:
            var_name = var.get("name")
            var_type = var.get("type", "static")
            var_value = var.get("value")

            if var_type == "static":
                output[var_name] = var_value
            elif var_type == "context":
                source = var.get("source", "")
                output[var_name] = context.get(source)
            elif var_type == "expression":
                expression = var.get("expression", "")
                output[var_name] = self._evaluate_expression(expression, context)

        return output

    # ── 主执行流程 ───────────────────────────────────────────────────────────

    async def execute_workflow(
        self,
        workflow_id: str | uuid.UUID,
        input_data: Optional[Dict[str, Any]],
        user_id: Optional[str | uuid.UUID],
    ) -> Dict[str, Any]:
        """执行工作流（阻塞式）"""
        workflow_id = str(workflow_id)
        workflow = self.workflow_service.get_workflow(workflow_id, authorize=False)
        if self.actor is not None:
            self.resource_authorization.require(
                self.actor,
                self.tenant_id,
                "workflow",
                "execute",
                workflow,
            )

        if workflow.status != "published":
            raise ValidationException("只有已发布的工作流才能执行")

        self.workflow_service.validate_workflow_dag(workflow_id, authorize=False)

        execution = self.create_execution(workflow_id, input_data, user_id)

        try:
            self.update_execution_status(execution, status="running")

            dag = self.build_dag(workflow)
            node_order = self.topological_sort(dag)

            nodes = {node.id: node for node in workflow.nodes}

            context = {"input": input_data or {}}
            consumed_loop_body_nodes: set[str] = set()

            async def _run_nodes():
                for node_id in node_order:
                    if node_id in consumed_loop_body_nodes:
                        continue
                    node = nodes[node_id]

                    node_input = {"input": input_data or {}} if node.node_type == "start" else {}
                    for edge in workflow.edges:
                        if edge.target_node_id == node_id:
                            source_node = nodes[edge.source_node_id]
                            source_output = context.get(f"node_{source_node.id}", {})
                            node_input.update(source_output)

                    if node.node_type == "loop":
                        node_output = await self.execute_node(
                            node,
                            {**context, **node_input},
                            execution.id,
                            workflow=workflow,
                            node_order=node_order,
                        )
                    else:
                        node_output = await self.execute_node(node, node_input, execution.id)
                    if node.node_type == "loop":
                        consumed_loop_body_nodes.update(
                            getattr(self, "_last_loop_consumed_body_nodes", set())
                        )

                    context[f"node_{node.id}"] = node_output
                    context.update(node_output)

            # A3：整体执行超时保护，避免单个工作流无限挂起占用请求。
            await asyncio.wait_for(
                _run_nodes(), timeout=config.workflow_execution_timeout_seconds
            )

            end_nodes = [n for n in workflow.nodes if n.node_type == "end"]
            final_output = {}
            for end_node in end_nodes:
                end_output = context.get(f"node_{end_node.id}", {})
                final_output.update(end_output)

            self.update_execution_status(execution, status="completed", output_data=final_output)
            self.db.commit()

            return {
                "execution_id": execution.id,
                "status": "completed",
                "output": final_output,
            }

        except Exception as e:
            error_msg = str(e)[:500]
            self.update_execution_status(execution, status="failed", error_message=error_msg)
            self.db.commit()
            logger.error(f"Workflow execution failed: workflow_id={workflow_id}, error={e}", exc_info=True)
            raise

    async def execute_workflow_stream(
        self,
        workflow_id: str | uuid.UUID,
        input_data: Optional[Dict[str, Any]],
        user_id: Optional[str | uuid.UUID],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行工作流（SSE流式）"""
        workflow_id = str(workflow_id)
        workflow = self.workflow_service.get_workflow(workflow_id, authorize=False)
        if self.actor is not None:
            self.resource_authorization.require(
                self.actor,
                self.tenant_id,
                "workflow",
                "execute",
                workflow,
            )

        if workflow.status != "published":
            raise ValidationException("只有已发布的工作流才能执行")

        self.workflow_service.validate_workflow_dag(workflow_id, authorize=False)

        execution = self.create_execution(workflow_id, input_data, user_id)

        try:
            self.update_execution_status(execution, status="running")

            yield {
                "type": "execution_started",
                "execution_id": execution.id,
                "workflow_id": workflow_id,
            }

            dag = self.build_dag(workflow)
            node_order = self.topological_sort(dag)

            nodes = {node.id: node for node in workflow.nodes}

            context = {"input": input_data or {}}
            consumed_loop_body_nodes: set[str] = set()

            for node_id in node_order:
                if node_id in consumed_loop_body_nodes:
                    continue
                node = nodes[node_id]

                yield {
                    "type": "node_started",
                    "node_id": node.id,
                    "node_name": node.name,
                    "node_type": node.node_type,
                }

                node_input = {"input": input_data or {}} if node.node_type == "start" else {}
                for edge in workflow.edges:
                    if edge.target_node_id == node_id:
                        source_node = nodes[edge.source_node_id]
                        source_output = context.get(f"node_{source_node.id}", {})
                        node_input.update(source_output)

                node_events: List[Dict[str, Any]] = []

                async def collect_node_event(event: Dict[str, Any]) -> None:
                    node_events.append(event)

                try:
                    if node.node_type == "loop":
                        node_output = await self.execute_node(
                            node,
                            {**context, **node_input},
                            execution.id,
                            workflow=workflow,
                            node_order=node_order,
                            node_event_callback=collect_node_event,
                        )
                    elif node.node_type == "llm":
                        node_output = await self.execute_node(
                            node,
                            node_input,
                            execution.id,
                            node_event_callback=collect_node_event,
                        )
                    else:
                        node_output = await self.execute_node(node, node_input, execution.id)
                    if node.node_type == "loop":
                        consumed_loop_body_nodes.update(
                            getattr(self, "_last_loop_consumed_body_nodes", set())
                        )

                    context[f"node_{node.id}"] = node_output
                    context.update(node_output)

                    for node_event in node_events:
                        yield node_event

                    yield {
                        "type": "node_completed",
                        "node_id": node.id,
                        "node_name": node.name,
                        "output": node_output,
                    }

                except Exception as e:
                    for node_event in node_events:
                        yield node_event
                    yield {
                        "type": "node_failed",
                        "node_id": node.id,
                        "node_name": node.name,
                        "error": str(e)[:200],
                    }
                    raise

            end_nodes = [n for n in workflow.nodes if n.node_type == "end"]
            final_output = {}
            for end_node in end_nodes:
                end_output = context.get(f"node_{end_node.id}", {})
                final_output.update(end_output)

            self.update_execution_status(execution, status="completed", output_data=final_output)
            self.db.commit()

            yield {
                "type": "execution_completed",
                "execution_id": execution.id,
                "output": final_output,
            }

        except Exception as e:
            error_msg = str(e)[:500]
            self.update_execution_status(execution, status="failed", error_message=error_msg)
            self.db.commit()
            logger.error(f"Workflow execution failed: workflow_id={workflow_id}, error={e}", exc_info=True)

            yield {
                "type": "execution_failed",
                "execution_id": execution.id,
                "error": error_msg,
            }

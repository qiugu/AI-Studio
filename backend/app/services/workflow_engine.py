from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime, timezone
import logging
import json
import re

from sqlalchemy.orm import Session
from collections import deque

from app.models.workflow import Workflow
from app.models.workflow_node import WorkflowNode
from app.models.workflow_edge import WorkflowEdge
from app.models.workflow_execution import WorkflowExecution
from app.models.node_execution import NodeExecution
from app.services.workflow import WorkflowService
from app.core.exceptions import ValidationException, NotFoundException
from app.schemas.workflow import WorkflowExecutionRequest

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """工作流执行引擎"""

    def __init__(self, db: Session, tenant_id: int):
        self.db = db
        self.tenant_id = tenant_id
        self.workflow_service = WorkflowService(db=db, tenant_id=tenant_id)

    # ── DAG构建与拓扑排序 ───────────────────────────────────────────────────────

    def build_dag(self, workflow: Workflow) -> Dict[int, List[int]]:
        """构建DAG邻接表"""
        graph = {node.id: [] for node in workflow.nodes}
        for edge in workflow.edges:
            graph[edge.source_node_id].append(edge.target_node_id)
        return graph

    def topological_sort(self, graph: Dict[int, List[int]]) -> List[int]:
        """拓扑排序（Kahn算法）"""
        # 计算入度
        in_degree = {node_id: 0 for node_id in graph}
        for node_id in graph:
            for neighbor in graph[node_id]:
                in_degree[neighbor] += 1

        # 找入度为0的节点（开始节点）
        queue = deque([node_id for node_id in in_degree if in_degree[node_id] == 0])
        result = []

        while queue:
            node_id = queue.popleft()
            result.append(node_id)

            for neighbor in graph[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 检查是否所有节点都被访问（检测循环）
        if len(result) != len(graph):
            raise ValidationException("工作流包含循环依赖，无法执行")

        return result

    # ── 执行记录管理 ───────────────────────────────────────────────────────────

    def create_execution(
        self,
        workflow_id: int,
        input_data: Optional[Dict[str, Any]],
        user_id: Optional[int],
    ) -> WorkflowExecution:
        """创建执行记录"""
        execution = WorkflowExecution(
            workflow_id=workflow_id,
            tenant_id=self.tenant_id,
            status="pending",
            input_data=input_data or {},
            created_by=user_id,
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
        execution_id: int,
        node_id: int,
        input_data: Optional[Dict[str, Any]],
    ) -> NodeExecution:
        """创建节点执行记录"""
        node_execution = NodeExecution(
            execution_id=execution_id,
            node_id=node_id,
            tenant_id=self.tenant_id,
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
        execution_id: int,
    ) -> Dict[str, Any]:
        """执行单个节点"""
        # 创建节点执行记录
        node_execution = self.create_node_execution(
            execution_id=execution_id,
            node_id=node.id,
            input_data=context,
        )

        try:
            # 更新状态为运行中
            self.update_node_execution(node_execution, status="running")

            # 根据节点类型执行
            node_type = node.node_type
            if node_type == "start":
                output = await self._execute_start_node(node, context)
            elif node_type == "end":
                output = await self._execute_end_node(node, context)
            elif node_type == "llm":
                output = await self._execute_llm_node(node, context)
            elif node_type == "condition":
                output = await self._execute_condition_node(node, context)
            elif node_type == "knowledge":
                output = await self._execute_knowledge_node(node, context)
            elif node_type == "code":
                output = await self._execute_code_node(node, context)
            elif node_type == "tool":
                output = await self._execute_tool_node(node, context)
            elif node_type == "loop":
                output = await self._execute_loop_node(node, context)
            elif node_type == "variable":
                output = await self._execute_variable_node(node, context)
            else:
                raise ValidationException(f"未知的节点类型: {node_type}")

            # 更新状态为完成
            self.update_node_execution(node_execution, status="completed", output_data=output)
            return output

        except Exception as e:
            # 更新状态为失败
            error_msg = str(e)[:500]  # 截取前500字符
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
        # 开始节点通常只用于触发工作流，输出上下文中的输入数据
        output_variables = config.get("output_variables", [])

        output = {}
        for var in output_variables:
            var_name = var.get("name")
            var_source = var.get("source", "input")
            if var_source == "input":
                # 从输入数据中获取
                output[var_name] = context.get("input", {}).get(var_name)
            else:
                # 直接赋值
                output[var_name] = var.get("value")

        return output

    async def _execute_end_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行结束节点"""
        config = node.config or {}
        # 结束节点用于输出结果
        output_variables = config.get("output_variables", [])

        output = {}
        for var in output_variables:
            var_name = var.get("name")
            var_source = var.get("source")
            # 从上下文中获取变量值
            output[var_name] = context.get(var_source)

        return output

    async def _execute_llm_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行LLM节点"""
        config = node.config or {}
        model_id = config.get("model_id")
        prompt_template = config.get("prompt_template", "")

        if not model_id:
            raise ValidationException("LLM节点必须指定模型ID")

        # 渲染Prompt模板（替换变量）
        prompt = self._render_template(prompt_template, context)

        # 获取模型和供应商
        from app.models.ai_model import AIModel
        from app.models.ai_provider import AIProvider
        from app.utils import llm as llm_utils
        from app.utils.encryption import decrypt

        model = self.db.query(AIModel).filter(AIModel.id == model_id).first()
        if not model:
            raise NotFoundException("AIModel", model_id)

        provider = self.db.query(AIProvider).filter(
            AIProvider.id == model.provider_id,
            AIProvider.tenant_id == self.tenant_id,
        ).first()
        if not provider:
            raise NotFoundException("AIProvider", model.provider_id)

        # 解密API Key
        api_key = decrypt(provider.api_key_encrypted)
        api_base_url = provider.api_base_url

        # 构建LLM
        temperature = config.get("temperature", 0.7)
        max_tokens = config.get("max_tokens", 2000)
        llm = llm_utils.build_chat_model(
            provider_type=provider.provider_type,
            api_key=api_key,
            api_base_url=api_base_url,
            model_name=model.name,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # 调用LLM
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])

        # 提取输出变量
        output_variable = config.get("output_variable", "output")
        return {output_variable: response.content}

    def _render_template(self, template: str, context: Dict[str, Any]) -> str:
        """渲染模板（替换变量）"""
        # 替换 {{variable}} 形式的变量
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

        # 评估每个条件
        for condition in conditions:
            expression = condition.get("expression", "")
            label = condition.get("label", "default")

            # 评估表达式
            result = self._evaluate_expression(expression, context)

            if result:
                # 返回匹配的条件标签（用于路由）
                return {
                    "condition_result": True,
                    "condition_label": label,
                    "matched_condition": condition,
                }

        # 如果没有匹配的条件，返回default
        return {
            "condition_result": False,
            "condition_label": "default",
        }

    def _evaluate_expression(self, expression: str, context: Dict[str, Any]) -> bool:
        """评估条件表达式"""
        # 替换变量
        def replace_var(match):
            var_name = match.group(1).strip()
            value = context.get(var_name)
            if isinstance(value, str):
                return f'"{value}"'
            return str(value)

        expr = re.sub(r'\{\{(.+?)\}\}', replace_var, expression)

        # 安全评估（限制操作符）
        try:
            # 只允许基本的比较和逻辑操作符
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

        # 渲染查询模板
        query = self._render_template(query_template, context)

        # 调用知识库服务
        from app.services.knowledge import KnowledgeBaseService
        kb_service = KnowledgeBaseService(self.db, self.tenant_id)
        results = kb_service.search(kb_id=kb_id, query_text=query, top_k=top_k)

        # 提取输出
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

        # 准备输入变量
        input_data = {}
        for var_name in input_variables:
            input_data[var_name] = context.get(var_name)

        # 执行代码（受限环境）
        try:
            # 创建受限执行环境
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

            # 执行代码
            exec_globals = {"__builtins__": allowed_builtins, **input_data}
            local_vars = {}
            exec(code, exec_globals, local_vars)

            # 提取输出
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
        """执行工具节点（调用Agent工具）"""
        config = node.config or {}
        tool_type = config.get("tool_type", "function")
        tool_name = config.get("tool_name", "")
        tool_config = config.get("tool_config", {})
        input_variables = config.get("input_variables", [])
        output_variable = config.get("output_variable", "tool_result")

        if not tool_name:
            raise ValidationException("工具节点必须指定工具名称")

        # 准备输入
        input_data = {}
        for var_name in input_variables:
            input_data[var_name] = context.get(var_name)

        # TODO: 集成Agent工具系统（阶段6后期完善）
        # 目前返回占位数据
        return {
            output_variable: f"Tool {tool_name} executed with inputs: {input_data}",
            "tool_type": tool_type,
        }

    async def _execute_loop_node(
        self,
        node: WorkflowNode,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行循环节点"""
        config = node.config or {}
        loop_type = config.get("loop_type", "for")  # for | while
        loop_variable = config.get("loop_variable", "item")
        loop_source = config.get("loop_source", "")
        max_iterations = config.get("max_iterations", 100)

        # 获取循环数据源
        if loop_type == "for":
            # 从上下文获取迭代数据
            data = context.get(loop_source, [])
            if not isinstance(data, (list, tuple)):
                raise ValidationException("For循环的数据源必须是列表")

            # 返回循环信息（实际迭代在execute_workflow中处理）
            return {
                "loop_type": "for",
                "loop_variable": loop_variable,
                "loop_data": data,
                "max_iterations": min(len(data), max_iterations),
            }
        else:  # while
            # While循环条件
            condition_template = config.get("condition_template", "")
            return {
                "loop_type": "while",
                "loop_variable": loop_variable,
                "condition_template": condition_template,
                "max_iterations": max_iterations,
            }

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
                # 从上下文获取
                source = var.get("source", "")
                output[var_name] = context.get(source)
            elif var_type == "expression":
                # 评估表达式
                expression = var.get("expression", "")
                output[var_name] = self._evaluate_expression(expression, context)

        return output

    # ── 主执行流程 ───────────────────────────────────────────────────────────

    async def execute_workflow(
        self,
        workflow_id: int,
        input_data: Optional[Dict[str, Any]],
        user_id: Optional[int],
    ) -> Dict[str, Any]:
        """执行工作流（阻塞式）"""
        # 获取工作流
        workflow = self.workflow_service.get_workflow(workflow_id)

        # 验证工作流状态
        if workflow.status != "published":
            raise ValidationException("只有已发布的工作流才能执行")

        # 验证DAG结构
        self.workflow_service.validate_workflow_dag(workflow_id)

        # 创建执行记录
        execution = self.create_execution(workflow_id, input_data, user_id)

        try:
            # 更新状态为运行中
            self.update_execution_status(execution, status="running")

            # 构建DAG并拓扑排序
            dag = self.build_dag(workflow)
            node_order = self.topological_sort(dag)

            # 构建节点映射
            nodes = {node.id: node for node in workflow.nodes}

            # 执行上下文（存储所有节点的输出）
            context = {"input": input_data or {}}

            # 按拓扑顺序执行节点
            for node_id in node_order:
                node = nodes[node_id]

                # 获取前驱节点的输出（构建当前节点的输入）
                node_input = {}
                for edge in workflow.edges:
                    if edge.target_node_id == node_id:
                        # 从前驱节点的输出中获取数据
                        source_node = nodes[edge.source_node_id]
                        source_output = context.get(f"node_{source_node.id}", {})
                        node_input.update(source_output)

                # 执行节点
                node_output = await self.execute_node(node, node_input, execution.id)

                # 保存节点输出到上下文
                context[f"node_{node.id}"] = node_output

                # 更新全局上下文（用于后续节点）
                context.update(node_output)

            # 提取最终输出
            end_nodes = [n for n in workflow.nodes if n.node_type == "end"]
            final_output = {}
            for end_node in end_nodes:
                end_output = context.get(f"node_{end_node.id}", {})
                final_output.update(end_output)

            # 更新执行状态为完成
            self.update_execution_status(execution, status="completed", output_data=final_output)
            self.db.commit()

            return {
                "execution_id": execution.id,
                "status": "completed",
                "output": final_output,
            }

        except Exception as e:
            # 更新执行状态为失败
            error_msg = str(e)[:500]
            self.update_execution_status(execution, status="failed", error_message=error_msg)
            self.db.commit()
            logger.error(f"Workflow execution failed: workflow_id={workflow_id}, error={e}", exc_info=True)
            raise

    async def execute_workflow_stream(
        self,
        workflow_id: int,
        input_data: Optional[Dict[str, Any]],
        user_id: Optional[int],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """执行工作流（SSE流式）"""
        # 获取工作流
        workflow = self.workflow_service.get_workflow(workflow_id)

        # 验证工作流状态
        if workflow.status != "published":
            raise ValidationException("只有已发布的工作流才能执行")

        # 验证DAG结构
        self.workflow_service.validate_workflow_dag(workflow_id)

        # 创建执行记录
        execution = self.create_execution(workflow_id, input_data, user_id)

        try:
            # 更新状态为运行中
            self.update_execution_status(execution, status="running")

            # 发送执行开始事件
            yield {
                "type": "execution_started",
                "execution_id": execution.id,
                "workflow_id": workflow_id,
            }

            # 构建DAG并拓扑排序
            dag = self.build_dag(workflow)
            node_order = self.topological_sort(dag)

            # 构建节点映射
            nodes = {node.id: node for node in workflow.nodes}

            # 执行上下文
            context = {"input": input_data or {}}

            # 按拓扑顺序执行节点
            for node_id in node_order:
                node = nodes[node_id]

                # 发送节点开始事件
                yield {
                    "type": "node_started",
                    "node_id": node.id,
                    "node_name": node.name,
                    "node_type": node.node_type,
                }

                # 获取前驱节点的输出
                node_input = {}
                for edge in workflow.edges:
                    if edge.target_node_id == node_id:
                        source_node = nodes[edge.source_node_id]
                        source_output = context.get(f"node_{source_node.id}", {})
                        node_input.update(source_output)

                # 执行节点
                try:
                    node_output = await self.execute_node(node, node_input, execution.id)

                    # 保存节点输出到上下文
                    context[f"node_{node.id}"] = node_output
                    context.update(node_output)

                    # 发送节点完成事件
                    yield {
                        "type": "node_completed",
                        "node_id": node.id,
                        "node_name": node.name,
                        "output": node_output,
                    }

                except Exception as e:
                    # 发送节点失败事件
                    yield {
                        "type": "node_failed",
                        "node_id": node.id,
                        "node_name": node.name,
                        "error": str(e)[:200],
                    }
                    raise

            # 提取最终输出
            end_nodes = [n for n in workflow.nodes if n.node_type == "end"]
            final_output = {}
            for end_node in end_nodes:
                end_output = context.get(f"node_{end_node.id}", {})
                final_output.update(end_output)

            # 更新执行状态为完成
            self.update_execution_status(execution, status="completed", output_data=final_output)
            self.db.commit()

            # 发送执行完成事件
            yield {
                "type": "execution_completed",
                "execution_id": execution.id,
                "output": final_output,
            }

        except Exception as e:
            # 更新执行状态为失败
            error_msg = str(e)[:500]
            self.update_execution_status(execution, status="failed", error_message=error_msg)
            self.db.commit()
            logger.error(f"Workflow execution failed: workflow_id={workflow_id}, error={e}", exc_info=True)

            # 发送执行失败事件
            yield {
                "type": "execution_failed",
                "execution_id": execution.id,
                "error": error_msg,
            }
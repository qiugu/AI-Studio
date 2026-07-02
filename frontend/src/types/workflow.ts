// ── Workflow Node Types ───────────────────────────────────────────────────────

export type NodeType = 'start' | 'end' | 'llm' | 'condition' | 'knowledge' | 'code' | 'tool' | 'loop' | 'variable'

export interface WorkflowNodeConfig {
  // LLM节点配置
  model_id?: number
  prompt_template?: string
  temperature?: number
  max_tokens?: number
  output_variable?: string

  // Condition节点配置
  conditions?: Array<{
    expression: string
    label: string
  }>

  // Knowledge节点配置
  knowledge_base_id?: number
  query_template?: string
  top_k?: number

  // Code节点配置
  code?: string
  input_variables?: string[]
  code_output_variable?: string

  // Tool节点配置
  tool_type?: string
  tool_name?: string
  tool_config?: Record<string, unknown>

  // Loop节点配置
  loop_type?: 'for' | 'while'
  loop_variable?: string
  loop_source?: string
  max_iterations?: number

  // Variable节点配置
  variables?: Array<{
    name: string
    type: 'static' | 'context' | 'expression'
    value?: unknown
    source?: string
    expression?: string
  }>

  // Start/End节点配置
  output_variables?: Array<{
    name: string
    source: string
    value?: unknown
  }>
}

export interface WorkflowNode {
  id: number
  workflow_id: number
  tenant_id: number
  node_type: NodeType
  name: string
  position_x: number
  position_y: number
  config: WorkflowNodeConfig | null
  created_at: string
  updated_at: string
}

export interface WorkflowNodeCreate {
  node_type: NodeType
  name: string
  position_x: number
  position_y: number
  config?: WorkflowNodeConfig
}

// ── Workflow Edge Types ───────────────────────────────────────────────────────

export interface WorkflowEdgeCondition {
  expression: string
  label: string
}

export interface WorkflowEdge {
  id: number
  workflow_id: number
  tenant_id: number
  source_node_id: number
  target_node_id: number
  condition: WorkflowEdgeCondition | null
  label: string | null
  created_at: string
  updated_at: string
}

export interface WorkflowEdgeCreate {
  source_node_id: number
  target_node_id: number
  condition?: WorkflowEdgeCondition
  label?: string
}

// ── Workflow Types ─────────────────────────────────────────────────────────────

export type WorkflowStatus = 'draft' | 'published' | 'archived'

export interface Workflow {
  id: number
  tenant_id: number
  name: string
  description: string | null
  status: WorkflowStatus
  is_active: boolean
  created_by: number | null
  created_at: string
  updated_at: string
  deleted_at: string | null
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export interface WorkflowCreateRequest {
  name: string
  description?: string
  nodes?: WorkflowNodeCreate[]
  edges?: WorkflowEdgeCreate[]
}

export interface WorkflowUpdateRequest {
  name?: string
  description?: string
  status?: WorkflowStatus
  nodes?: WorkflowNodeCreate[]
  edges?: WorkflowEdgeCreate[]
}

export interface WorkflowListResponse {
  items: Workflow[]
  total: number
  page: number
  page_size: number
}

// ── Workflow Execution Types ───────────────────────────────────────────────────

export type ExecutionStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface WorkflowExecution {
  id: number
  workflow_id: number
  tenant_id: number
  status: ExecutionStatus
  input_data: Record<string, unknown> | null
  output_data: Record<string, unknown> | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_by: number | null
  created_at: string
}

export interface WorkflowExecutionRequest {
  input_data?: Record<string, unknown>
}

// ── SSE Event Types ───────────────────────────────────────────────────────────

export interface SSEExecutionStartedEvent {
  type: 'execution_started'
  execution_id: number
  workflow_id: number
}

export interface SSENodeStartedEvent {
  type: 'node_started'
  node_id: number
  node_name: string
  node_type: NodeType
}

export interface SSENodeCompletedEvent {
  type: 'node_completed'
  node_id: number
  node_name: string
  output: Record<string, unknown>
}

export interface SSENodeFailedEvent {
  type: 'node_failed'
  node_id: number
  node_name: string
  error: string
}

export interface SSEExecutionCompletedEvent {
  type: 'execution_completed'
  execution_id: number
  output: Record<string, unknown>
}

export interface SSEExecutionFailedEvent {
  type: 'execution_failed'
  execution_id: number
  error: string
}

export type SSEWorkflowEvent =
  | SSEExecutionStartedEvent
  | SSENodeStartedEvent
  | SSENodeCompletedEvent
  | SSENodeFailedEvent
  | SSEExecutionCompletedEvent
  | SSEExecutionFailedEvent
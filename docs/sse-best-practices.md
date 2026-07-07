# SSE 流式对话最佳实践指南

> **AI-Studio 实战经验总结**：本文档结合了 AI-Studio 项目（阶段 5 Agent 系统）的实际开发经验，记录了 SSE 流式对话实现中的关键问题和解决方案。

## 一、为什么选择 SSE而非 WebSocket？

根据 OpenAI、Claude、通义千问等主流 LLM API 的实践，**SSE 是 AI 流式输出的最佳选择**：

| 特性 | SSE | WebSocket |
|------|-----|-----------|
| **通信方向** | 单向（服务器→客户端） | 双向 |
| **协议开销** | 普通 HTTP，无需升级 | 需协议升级握手 |
| **连接管理** | 每次对话新建连接，用完即关 | 需维护连接池 |
| **浏览器支持** | EventSource API 原生支持 | 需额外库 |
| **适用场景** | AI 流式输出、实时通知 | 聊天室、协同编辑 |

**核心原因**：
- AI 对话天然是单向推送：用户只需看 AI"打字"，不需要双向通信
- 连接成本低：无需维护长连接池，每次对话独立请求
- 实现简单：基于 HTTP，无需处理复杂的协议升级

## 二、标准 SSE 数据格式

### 2.1 协议规范

SSE 消息格式由 `text/event-stream` MIME 类型定义：

```
event: message     # 事件类型（可选，默认 message）
id: 1001           # 事件 ID（可选，用于断线重连）
retry: 3000        # 重连间隔（毫秒，可选）
data: {"content": "你好"}  # 数据内容（必填）

                   # 空行表示消息结束（\n\n）
```

**关键约定**：
- 每个字段以 `\n` 结尾
- 连续的 `data:` 行会被合并为一条消息
- **空行 `\n\n` 作为消息分隔符**
- 以 `:` 开头的行是注释，可用于保持连接活跃

### 2.2 AI 流式对话的事件设计

业界标准的三种事件类型：

```typescript
// 1. message/token 事件：内容块
event: message
data: {"content": "你好"}

// 2. done 事件：生成完成
event: done
data: {"conversation_id": 123, "usage": {"prompt_tokens": 10, "completion_tokens": 20}}

// 3. error 事件：错误处理
event: error
data: {"error": "API认证失败", "error_code": "AUTHENTICATION_ERROR"}
```

## 三、后端实现最佳实践

### 3.1 关键配置

```python
# 1. 设置正确的 Content-Type
media_type="text/event-stream"

# 2. 禁用缓冲（防止代理层缓冲响应）
headers={
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",  # Nginx 禁用缓冲
    "Connection": "keep-alive",
}

# 3. 生成标准 SSE 格式
def encode_sse(event: str, data: dict) -> str:
    """生成标准 SSE 格式"""
    data_json = json.dumps(data, ensure_ascii=False)  # 保留中文
    return f"event: {event}\ndata: {data_json}\n\n"
```

### 3.2 数据库操作时机

**问题**：在流式生成过程中执行数据库写入会阻塞响应流。

**最佳实践**：
- **用户消息**：在开始流式生成前写入数据库
- **助手消息**：在 `done` 事件发送前写入数据库（生成完成后）
- **Token 统计**：在 `done` 事件发送前记录

```python
async def event_generator():
    # 1. 先添加用户消息
    conv_service.add_message(
        conversation_id=conversation_id,
        role="user",
        content=message,
    )
    
    # 2. 流式生成
    full_content = ""
    async for chunk in llm.astream(messages):
        content = chunk.content
        full_content += content
        
        yield encode_sse("message", {"content": content})
    
    # 3. 生成完成后，添加助手消息
    conv_service.add_message(
        conversation_id=conversation_id,
        role="assistant",
        content=full_content,
    )
    
    # 4. 发送 done 事件
    yield encode_sse("done", {
        "conversation_id": conversation_id,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        }
    })
```

### 3.3 错误处理

```python
try:
    async for chunk in llm.astream(messages):
        yield encode_sse("message", {"content": chunk.content})
except AuthenticationError:
    yield encode_sse("error", {
        "error": "API认证失败，请检查API密钥",
        "error_code": "AUTHENTICATION_ERROR"
    })
except RateLimitError:
    yield encode_sse("error", {
        "error": "API调用频率超限，请稍后重试",
        "error_code": "RATE_LIMIT_ERROR"
    })
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    yield encode_sse("error", {
        "error": "系统内部错误",
        "error_code": "SYSTEM_ERROR"
    })
```

## 四、前端实现最佳实践

### 4.1 为什么使用 fetch + ReadableStream？

虽然浏览器有原生 `EventSource` API，但它有局限性：
- **仅支持 GET 请求**（无法发送 POST）
- **不支持自定义 headers**（无法添加 Authorization）
- **无法携带请求体**（无法传递 prompt 和历史消息）

**fetch + ReadableStream 的优势**：
- 支持 POST 请求和自定义 headers
- 可以携带请求体（JSON 格式）
- 可以中断请求（AbortController）
- 可以精确控制 SSE 消息解析

### 4.2 正确解析 SSE 消息边界

**关键点**：SSE 消息以 `\n\n`（双换行符）分隔，但数据块可能跨多个 TCP 包到达。

```typescript
let buffer = ''  // 用于处理跨数据块的 SSE 消息

while (true) {
    const { done, value } = await reader.read()
    if (done) break
    
    const chunk = decoder.decode(value, { stream: true })
    buffer += chunk
    
    // SSE 消息以双换行符分隔
    const messages = buffer.split('\n\n')
    buffer = messages.pop() || ''  // 保留最后一个不完整的消息
    
    for (const message of messages) {
        if (!message.trim()) continue
        
        // 解析 event 和 data 行
        const lines = message.split('\n')
        let eventType = ''
        let dataStr = ''
        
        for (const line of lines) {
            if (line.startsWith('event: ')) {
                eventType = line.substring(7).trim()
            } else if (line.startsWith('data: ')) {
                dataStr = line.substring(6).trim()
            }
        }
        
        if (dataStr) {
            const data = JSON.parse(dataStr)
            // 处理不同事件类型...
        }
    }
}
```

### 4.3 消息状态管理

```typescript
interface StreamState {
    status: 'idle' | 'streaming' | 'done' | 'error'
    content: string
    conversationId?: number
    error?: string
}

const handleSendMessage = async (content: string) => {
    // 1. 添加用户消息
    setMessages(prev => [...prev, {
        id: Date.now(),
        role: 'user',
        content: content,
    }])
    
    // 2. 创建助手消息占位符
    const assistantId = Date.now() + 1
    setMessages(prev => [...prev, {
        id: assistantId,
        role: 'assistant',
        content: '',
        status: 'streaming',
    }])
    
    // 3. 发起 SSE 请求
    abortControllerRef.current = createStreamRequest(
        '/api/chat/stream',
        { message: content },
        {
            onContent: (chunk) => {
                setMessages(prev => prev.map(msg => 
                    msg.id === assistantId 
                        ? { ...msg, content: msg.content + chunk }
                        : msg
                ))
            },
            onComplete: (fullContent, conversationId) => {
                setMessages(prev => prev.map(msg =>
                    msg.id === assistantId
                        ? { ...msg, content: fullContent, status: 'done' }
                        : msg
                ))
            },
            onError: (error) => {
                setMessages(prev => prev.map(msg =>
                    msg.id === assistantId
                        ? { ...msg, status: 'error', error: error }
                        : msg
                ))
            }
        }
    )
}
```

### 4.4 优雅的用户中断

```typescript
// 用户点击"停止生成"按钮
const handleAbortStream = () => {
    if (abortControllerRef.current) {
        abortControllerRef.current.abort()
        
        // 更新消息状态为"已中断"
        setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
                ? { ...msg, status: 'aborted' }
                : msg
        ))
        
        setIsStreaming(false)
        abortControllerRef.current = null
    }
}
```

## 五、性能优化

### 5.1 Time to First Token (TTFT)

**关键指标**：用户从发送消息到看到第一个字的时间。

**优化策略**：
- 减少中间层处理耗时（认证、配额检查等）
- 使用异步流式处理，避免阻塞
- 禁用缓冲：`X-Accel-Buffering: no`

### 5.2 消息渲染优化

```typescript
// 使用 requestAnimationFrame 优化渲染
let pendingUpdate = false
let pendingContent = ''

const onContent = (chunk: string) => {
    pendingContent += chunk
    
    if (!pendingUpdate) {
        pendingUpdate = true
        requestAnimationFrame(() => {
            setMessages(prev => prev.map(msg =>
                msg.id === assistantId
                    ? { ...msg, content: msg.content + pendingContent }
                    : msg
            ))
            pendingContent = ''
            pendingUpdate = false
        })
    }
}
```

### 5.3 历史消息管理

```typescript
// 限制历史消息数量（避免超出 token 限制）
const historyMessages = messages
    .slice(-20)  // 只保留最近 20 条消息
    .filter(msg => msg.status !== 'error')  // 过滤掉错误消息
    .map(msg => ({
        role: msg.role,
        content: msg.content,
    }))
```

## 六、错误处理与用户体验

### 6.1 错误分类与提示

| 错误类型 | 错误码 | 用户提示 |
|---------|--------|---------|
| API认证失败 | AUTHENTICATION_ERROR | API密钥无效，请联系管理员 |
| 限流错误 | RATE_LIMIT_ERROR | 调用频率超限，请稍后重试 |
| 模型不存在 | MODEL_NOT_FOUND | 模型配置错误，请联系管理员 |
| 系统错误 | SYSTEM_ERROR | 系统内部错误，请稍后重试 |

### 6.2 错误消息显示

```typescript
// 错误消息作为特殊消息类型显示
if (msg.status === 'error') {
    return (
        <Alert
            type="error"
            message="模型调用失败"
            description={msg.error}
            showIcon
            action={
                <Button size="small" onClick={() => retryMessage(msg.id)}>
                    重试
                </Button>
            }
        />
    )
}
```

## 七、实战问题与解决方案（AI-Studio 经验）

### 7.1 Unicode 字符编码问题

**问题描述**：前端接收到的 SSE 数据中，中文等 Unicode 字符显示为乱码或转义序列（如 `\u4e2d\u6587`）。

**根本原因**：Python 的 `json.dumps()` 默认使用 `ensure_ascii=True`，会将非 ASCII 字符转义。

**解决方案**：
```python
# 后端 SSE 数据序列化时，必须使用 ensure_ascii=False
yield encode_sse("message", {
    "content": chunk.content
}, ensure_ascii=False)  # 关键：保留 Unicode 字符

# encode_sse 函数实现
def encode_sse(event: str, data: dict, ensure_ascii: bool = False) -> str:
    data_json = json.dumps(data, ensure_ascii=ensure_ascii)
    return f"event: {event}\ndata: {data_json}\n\n"
```

**验证方法**：在前端解析后，检查中文是否正常显示。

### 7.2 SSE 响应格式不标准导致前端解析失败

**问题描述**：前端使用 EventSource 或自定义 SSE 解析器时，无法正确提取消息内容，或前端报错"Unexpected token"。

**根本原因**：
1. 后端使用了单行 JSON 格式（如 `data: {"content": "你好"}` 没有换行符）
2. Media Type 设置错误（使用了 `application/octet-stream` 而非 `text/event-stream`）
3. 消息分隔符不正确（缺少 `\n\n`）

**解决方案**：
```python
# 1. 使用标准 SSE 格式（event + data + \n\n）
from sse_starlette.sse import ServerSentEvent

yield ServerSentEvent(
    event="message",  # 必须指定 event 字段
    data=json.dumps({"content": chunk.content}, ensure_ascii=False)
)

# 2. 正确设置 Media Type
from sse_starlette.sse import EventSourceResponse

return EventSourceResponse(
    event_generator(),
    media_type="text/event-stream"  # 关键：不要使用 application/octet-stream
)

# 3. 手动构建 SSE 格式（如果不使用 sse_starlette）
def encode_sse(event: str, data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {data_json}\n\n"  # 必须以 \n\n 结尾
```

**前端解析示例**：
```typescript
// 正确解析 SSE 消息边界
let buffer = ''
while (true) {
    const { done, value } = await reader.read()
    if (done) break
    
    buffer += decoder.decode(value, { stream: true })
    
    // SSE 消息以 \n\n 分隔
    const messages = buffer.split('\n\n')
    buffer = messages.pop() || ''  // 保留最后一个不完整的消息
    
    for (const message of messages) {
        if (!message.trim()) continue
        
        // 解析 event 和 data 行
        const lines = message.split('\n')
        let eventType = ''
        let dataStr = ''
        
        for (const line of lines) {
            if (line.startsWith('event: ')) {
                eventType = line.substring(7).trim()
            } else if (line.startsWith('data: ')) {
                dataStr = line.substring(6).trim()
            }
        }
        
        if (dataStr) {
            const data = JSON.parse(dataStr)
            if (eventType === 'message') {
                // 提取 content 字段
                onContent(data.content)
            } else if (eventType === 'done') {
                // 提取 conversation_id 字段
                onComplete(data.conversation_id)
            }
        }
    }
}
```

### 7.3 前端期望的字段名不匹配

**问题描述**：前端解析 SSE 数据后，无法找到期望的字段（如 `content` 或 `conversation_id`）。

**根本原因**：后端和前端对 SSE 数据结构的约定不一致。

**解决方案**：
```python
# 后端：明确约定字段名
yield ServerSentEvent(
    event="message",
    data=json.dumps({
        "content": chunk.content  # 前端期望 content 字段
    }, ensure_ascii=False)
)

yield ServerSentEvent(
    event="done",
    data=json.dumps({
        "conversation_id": conversation_id  # 前端期望 conversation_id 字段
    }, ensure_ascii=False)
)
```

**约定文档化**：
- `message` 事件：包含 `content` 字段（AI 输出的文本块）
- `done` 事件：包含 `conversation_id` 字段（对话 ID）+ `usage` 字段（可选）
- `error` 事件：包含 `error` 字段（错误消息）+ `error_code` 字段（错误码）

### 7.4 性能优化：虚拟滚动和渲染性能

**问题描述**：长对话历史（超过 100 条消息）导致页面卡顿，滚动不流畅。

**解决方案**：
```typescript
// 使用 @ant-design/x 的 Bubble.List 组件，支持虚拟滚动
import { Bubble } from '@ant-design/x'

<Bubble.List
    items={messages}
    auto={messages.length > 50}  // 超过 50 条自动启用虚拟滚动
    style={{ height: '100%' }}
/>

// 或者手动实现虚拟滚动
import { VirtualList } from 'rc-virtual-list'

<VirtualList
    data={messages}
    height={600}
    itemHeight={80}  // 预估消息高度
    itemKey="id"
>
    {(message) => <MessageBubble message={message} />}
</VirtualList>
```

**其他优化**：
- 使用 `React.memo` 包装消息组件
- 使用 `useMemo` 缓存消息列表计算结果
- 使用 `requestAnimationFrame` 优化流式渲染更新

## 八、参考资料

- [SSE 还是 WebSocket？从 AI 流式输出聊到实时通信选型](https://juejin.cn/post/7641598418105040959)
- [Streaming vs Non-streaming API Responses](https://stackviv.ai/blog/streaming-vs-non-streaming-api)
- [How to Stream LLM Responses Using Server-Sent Events](https://apidog.com/blog/stream-llm-responses-using-sse/)
- [Streaming AI Responses to the Browser with Server-Sent Events](https://www.d4b.dev/blog/2026-03-30-streaming-ai-responses-to-the-browser-with-server-sent-events)
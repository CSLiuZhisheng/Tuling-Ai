# LangGraph Interrupt 流程详解

## 一、什么是 Interrupt？

**Interrupt（中断）** 是 LangGraph 提供的一种机制，允许图执行过程中暂停，等待人工干预或用户输入，然后再继续执行。

在图的某个节点调用 `interrupt()` 后，LangGraph 会：
1. 暂停图的执行
2. 保存当前状态到 checkpoint
3. 将中断信息返回给调用方
4. 等待通过 `Command(resume=...)` 继续执行

---

## 二、完整的 Interrupt 流程（代码级详解）

### 阶段 1：图执行过程中触发 Interrupt

#### 1.1 在节点中触发中断

以写作子图的 `ask_clarification` 节点为例：

```python
# 在某个节点中（例如：writing_subgraph.py）
from langgraph.types import interrupt

async def ask_clarification(state: WritingState) -> dict:
    """澄清需求节点：当需求不明确时，暂停并询问用户"""
    
    # 检测到需求不明确
    if needs_clarification:
        clarification_data = {
            "type": "clarification",
            "question": "请问您希望文章的主要观点是什么？",
            "message": "需要进一步明确写作需求"
        }
        
        # 🔴 关键：调用 interrupt() 暂停图执行
        # 这个值会被保存到 checkpoint，并通过 SSE 发送给前端
        user_answer = interrupt(clarification_data)
        
        # ⚠️ 注意：这行代码不会立即执行！
        # 图会暂停在这里，直到用户通过 resume 接口提交答案
        return {"clarified_requirements": user_answer}
```

#### 1.2 LangGraph 保存中断状态

当 `interrupt()` 被调用时，LangGraph 内部会：

```python
# LangGraph 内部逻辑（伪代码）
checkpoint = {
    "state": current_state,  # 当前图状态
    "next_node": "ask_clarification",  # 中断所在的节点
    "interrupt_value": clarification_data,  # interrupt() 传入的数据
    "thread_id": "uuid-xxx",
    "checkpoint_id": "checkpoint-yyy"
}

# 保存到 PostgreSQL
await checkpointer.aput(checkpoint)

# 抛出特殊异常，停止图执行
raise GraphInterrupt(clarification_data)
```

---

### 阶段 2：前端接收 Interrupt 消息

#### 2.1 LangGraph 服务发送 SSE 事件

在 `langgraph_service/app/api/chat.py` 的 `_stream()` 函数中：

```python
async def _stream(request: ChatRequest, run_id: str) -> AsyncIterator[str]:
    """流式聊天"""
    
    async for part in runtime.require_graph().astream(
        input_state,
        config=_config(request.user_id, thread_id),
        stream_mode=["messages", "updates"],
        subgraphs=True,
        version="v2",
    ):
        event_type = part.get("type")
        data = part.get("data")
        
        # 🔴 检测到 interrupt
        if event_type == "updates":
            if isinstance(data, dict) and data.get("__interrupt__"):
                # 规范化 interrupt 数据
                normalized = _normalize_interrupt(data["__interrupt__"])
                
                # 📤 发送 interrupt 事件给前端
                yield _event("interrupt", normalized)
                # 输出格式：
                # data: {"type":"interrupt","content":[{"value":{"type":"clarification","question":"..."}}]}
```

#### 2.2 main_service 透传 SSE

在 `main_service/app/routers/custom_chat.py` 的 `chat_stream()` 中：

```python
@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, ...):
    """流式业务聊天"""
    
    async def events():
        # 🔄 透传 langgraph_service 的 SSE
        async for line in _service.chat_stream(...):
            if await request.is_disconnected():
                await _service.cancel_runs(...)
                return
            # 直接转发，不做解析或修改
            yield f"{line}\n"
    
    return StreamingResponse(events(), media_type="text/event-stream")
```

#### 2.3 前端接收并展示审核界面

前端代码（伪代码）：

```javascript
// 前端监听 SSE
const eventSource = new EventSource('/api/custom-chat/chat/stream');

eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    // 🔴 收到 interrupt 事件
    if (data.type === 'interrupt') {
        const interruptValue = data.content[0].value;
        
        if (interruptValue.type === 'clarification') {
            // 显示澄清问题对话框
            showClarificationDialog(interruptValue.question);
        } else if (interruptValue.type === 'human_review') {
            // 显示草稿审核面板
            showReviewPanel(interruptValue.draft);
        }
        
        // ⚠️ 关闭 EventSource，因为图已暂停
        eventSource.close();
    }
};
```

---

### 阶段 3：用户审核并提交结果

#### 3.1 用户在前端进行审核

用户看到审核界面后，可以：
- **澄清场景**：回答问题
- **草稿审核场景**：
  - `approve`：接受草稿
  - `edit`：修改草稿
  - `rewrite`：要求重写

#### 3.2 前端调用 resume 接口

```javascript
// 用户点击"提交"按钮
async function submitReview(action, content) {
    const response = await fetch('/api/custom-chat/chat/resume/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            conversation_id: currentConversationId,  // 🔴 必须是原会话 ID
            action: action,  // 'approve' / 'edit' / 'rewrite' / 'clarify'
            content: content,  // 用户修改的内容（edit 时）
            answer: userAnswer  // 用户回答（clarify 时）
        })
    });
    
    // 📥 重新监听 SSE，接收后续内容
    const reader = response.body.getReader();
    // ...
}
```

---

### 阶段 4：恢复图执行

#### 4.1 main_service 转发 resume 请求

在 `main_service/app/routers/custom_chat.py`：

```python
@router.post("/chat/resume/stream")
async def resume(req: ResumeRequest, current_user: User = ...):
    """恢复 interrupt 流程"""
    
    async def events():
        # 🔄 调用 langgraph_service 的 resume_stream
        async for line in _service.resume_stream(
            thread_id=current_user.id,
            conversation_id=req.conversation_id,  # 🔴 使用原会话 ID
            action=req.action,
            content=req.content,
            answer=req.answer
        ):
            yield f"{line}\n"
    
    return StreamingResponse(events(), media_type="text/event-stream")
```

#### 4.2 CustomLangGraphService 构造 resume 请求

在 `main_service/app/services/custom_langgraph_service.py`：

```python
async def resume_stream(self, *, thread_id: str, conversation_id: str | None, 
                       action: str, content: str | None, answer: str | None):
    """提交 interrupt 恢复参数并返回 SSE"""
    
    # 🔧 构造恢复载荷
    payload = {
        "user_id": str(thread_id),
        "conversation_id": conversation_id,  # 🔴 必须传原会话 ID
        "action": action,
        "content": content,
        "answer": answer
    }
    
    client = await self._get_client()
    
    # 📤 POST 到 langgraph_service 的 /api/chat/resume
    async with client.stream("POST", f"{self.base_url}/api/chat/resume", 
                            json=payload) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            yield line
```

#### 4.3 langgraph_service 恢复图执行

在 `langgraph_service/app/api/chat.py`：

```python
@router.post("/chat/resume")
async def resume(request: ResumeRequest) -> StreamingResponse:
    """恢复被 interrupt 暂停的图"""
    
    thread_id = _thread_id(request.user_id, request.conversation_id)
    
    # 🔧 转换 HTTP 请求为图节点约定的结构
    resume_data: dict[str, Any]
    if request.action == "clarify":
        # 澄清场景：提取用户答案
        resume_data = {"answer": request.answer or request.content or ""}
    else:
        # 审核场景：提取动作和内容
        resume_data = {"action": request.action}
        if request.action == "edit" and request.content is not None:
            resume_data["content"] = request.content
    
    async def events():
        # 🔴 关键：使用 Command(resume=...) 恢复图执行
        async for part in runtime.require_graph().astream(
            Command(resume=resume_data),  # 🔴 传入 resume 数据
            config=_config(request.user_id, thread_id),  # 🔴 使用原 thread_id
            stream_mode=["messages", "updates"],
            subgraphs=True,
            version="v2",
        ):
            # 继续流式输出后续内容
            # ... 省略事件处理代码
            yield _event(event_type, data)
        
        yield _event("complete", {"finished": True})
    
    return StreamingResponse(events(), ...)
```

#### 4.4 LangGraph 恢复节点执行

LangGraph 内部逻辑（伪代码）：

```python
# LangGraph 接收到 Command(resume=...)
resume_value = command.resume  # {"action": "approve"} 或 {"answer": "..."}

# 🔍 从 checkpoint 恢复状态
checkpoint = await checkpointer.aget(thread_id)

# 🔄 回到中断的节点，将 resume_value 作为 interrupt() 的返回值
current_node = checkpoint["next_node"]  # "ask_clarification"

# 📌 关键：interrupt() 返回 resume_value
# 节点中的这行代码现在可以继续执行了：
# user_answer = interrupt(clarification_data)  ← 返回 {"answer": "..."}

# 继续执行图的后续节点
```

#### 4.5 节点接收 resume 数据并继续

回到节点代码：

```python
async def ask_clarification(state: WritingState) -> dict:
    """澄清需求节点"""
    
    if needs_clarification:
        clarification_data = {
            "type": "clarification",
            "question": "请问您希望文章的主要观点是什么？"
        }
        
        # 第一次执行：这里会暂停
        user_answer = interrupt(clarification_data)
        
        # 🎯 resume 后：user_answer = {"answer": "我希望文章强调..."}
        # 现在可以继续执行了！
        
        return {
            "clarified_requirements": user_answer.get("answer", ""),
            "messages": [AIMessage(content=f"已理解您的需求：{user_answer['answer']}")]
        }
```

---

## 三、关键点总结

### 1. **conversation_id 必须保持一致**

```python
# ❌ 错误：使用新的 conversation_id
resume_request = {"conversation_id": "new-id-xxx", ...}  # 找不到 checkpoint！

# ✅ 正确：使用原 conversation_id
resume_request = {"conversation_id": original_conversation_id, ...}
```

**原因**：
- `conversation_id` 映射为 LangGraph 的 `thread_id`
- checkpoint 以 `thread_id` 为键保存在 PostgreSQL
- 使用新 ID 会找不到中断状态

### 2. **resume 数据结构约定**

不同场景的 resume 数据结构：

```python
# 澄清场景
{"answer": "用户的回答"}

# 审核场景 - 接受
{"action": "approve"}

# 审核场景 - 编辑
{"action": "edit", "content": "修改后的内容"}

# 审核场景 - 重写
{"action": "rewrite"}
```

### 3. **interrupt() 的返回值 = resume 数据**

```python
# 节点代码
user_input = interrupt({"question": "..."})

# resume 时
Command(resume={"answer": "用户回答"})

# 结果：user_input = {"answer": "用户回答"}
```

### 4. **SSE 连接的生命周期**

```
初始请求 → 流式输出 → interrupt 事件 → 关闭连接
                                          ↓
                        用户审核 → 提交 resume 请求 → 新的流式连接 → 继续输出
```

---

## 四、流程时序图

```
┌────────┐          ┌──────────────┐          ┌───────────────┐          ┌──────────┐
│ 前端   │          │ main_service │          │ langgraph_svc │          │LangGraph │
└───┬────┘          └──────┬───────┘          └───────┬───────┘          └────┬─────┘
    │                      │                          │                       │
    │ POST /chat/stream    │                          │                       │
    ├─────────────────────>│                          │                       │
    │                      │ chat_stream()            │                       │
    │                      ├─────────────────────────>│                       │
    │                      │                          │ astream()             │
    │                      │                          ├──────────────────────>│
    │                      │                          │                       │
    │                      │                          │              执行节点 │
    │                      │                          │   ┌───────────────────┤
    │<─────────────────────┼──────────────────────────┼───┤ interrupt() 暂停  │
    │  SSE: interrupt      │                          │   └───────────────────┤
    │  关闭连接            │                          │  保存 checkpoint      │
    │                      │                          │                       │
    ├─ 用户审核 ───────────┤                          │                       │
    │                      │                          │                       │
    │ POST /resume/stream  │                          │                       │
    ├─────────────────────>│                          │                       │
    │                      │ resume_stream()          │                       │
    │                      ├─────────────────────────>│                       │
    │                      │                          │ astream(Command)      │
    │                      │                          ├──────────────────────>│
    │                      │                          │              从 checkpoint
    │                      │                          │              恢复并继续
    │                      │                          │   ┌───────────────────┤
    │<─────────────────────┼──────────────────────────┼───┤ 继续执行后续节点  │
    │  SSE: content        │                          │   └───────────────────┤
    │  SSE: complete       │                          │                       │
    │                      │                          │                       │
```

---

## 五、示例代码总结

### 前端完整流程

```javascript
// 1️⃣ 发起聊天
async function chat(message) {
    const response = await fetch('/api/custom-chat/chat/stream', {
        method: 'POST',
        body: JSON.stringify({ query: message, conversation_id: currentConvId })
    });
    
    const reader = response.body.getReader();
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const text = new TextDecoder().decode(value);
        const lines = text.split('\n\n');
        
        for (const line of lines) {
            if (line.startsWith('data: ')) {
                const data = JSON.parse(line.slice(6));
                
                // 2️⃣ 处理 interrupt
                if (data.type === 'interrupt') {
                    handleInterrupt(data.content[0].value);
                    return; // 停止接收
                }
                
                if (data.type === 'content') {
                    appendMessage(data.content);
                }
            }
        }
    }
}

// 3️⃣ 处理 interrupt
function handleInterrupt(interruptValue) {
    if (interruptValue.type === 'clarification') {
        showClarificationDialog(interruptValue.question, (answer) => {
            resumeChat('clarify', null, answer);
        });
    } else if (interruptValue.type === 'human_review') {
        showReviewPanel(interruptValue.draft, (action, content) => {
            resumeChat(action, content, null);
        });
    }
}

// 4️⃣ 恢复聊天
async function resumeChat(action, content, answer) {
    const response = await fetch('/api/custom-chat/chat/resume/stream', {
        method: 'POST',
        body: JSON.stringify({
            conversation_id: currentConvId,  // 使用原会话 ID
            action,
            content,
            answer
        })
    });
    
    // 继续接收后续内容
    const reader = response.body.getReader();
    // ... 处理流式响应
}
```

---

## 六、常见问题

### Q1: 为什么 resume 时找不到 checkpoint？
**A**: 检查 `conversation_id` 是否与原请求一致。

### Q2: 如何在节点中判断是首次执行还是 resume？
**A**: 检查 interrupt 的返回值是否为 None：

```python
user_input = interrupt(data)
if user_input is None:
    # 首次执行，暂停在这里
    pass
else:
    # resume 后，user_input 包含用户提交的数据
    process(user_input)
```

### Q3: 可以多次 interrupt 吗？
**A**: 可以。每次 interrupt 都会保存新的 checkpoint，resume 后继续执行。

### Q4: interrupt 数据保存在哪里？
**A**: PostgreSQL 的 `checkpoints` 表，由 `AsyncPostgresSaver` 管理。

---

## 七、总结

Interrupt 流程的核心逻辑：

1. **暂停**：节点调用 `interrupt(data)` → LangGraph 保存 checkpoint → 返回 SSE 给前端
2. **等待**：前端显示审核界面 → 用户操作
3. **恢复**：前端 POST resume → LangGraph 用 `Command(resume=data)` 恢复 → interrupt() 返回 data
4. **继续**：节点接收 resume 数据 → 继续执行后续逻辑

**关键**：整个过程通过 `conversation_id → thread_id → checkpoint` 维持状态连续性。

# Issue 6: 脆弱的双层取消协调机制

## 问题描述

**文件**: `langgraph_service/app/api/chat.py:601-639`  
**严重程度**: 🟡 Medium（架构复杂度问题）

取消机制需要同时调用两个层面：
1. **层1**：`cancel_manager.cancel(run_id)` - 点亮信号灯，让 LLM 停止生成
2. **层2**：`task.cancel()` - 取消 asyncio Task，停止流式输出

如果只调用其中一个，取消会失败或不完整。这种双层协调机制脆弱且容易出错。

## 失败场景

### 场景 1: 只调用 cancel_manager.cancel()
```python
# 错误示例：只调用层1
cancel_manager.cancel(run_id)
# 结果：LLM 停止生成，但 asyncio Task 继续运行，资源未释放
```

### 场景 2: 只调用 task.cancel()
```python
# 错误示例：只调用层2
task.cancel()
# 结果：流式输出停止，但 LLM 仍在后台生成（浪费资源）
```

### 场景 3: 调用顺序错误
```python
# 错误示例：先取消 Task
task.cancel()
cancel_manager.cancel(run_id)
# 结果：Task 取消可能中断信号灯设置，导致 LLM 继续运行
```

### 场景 4: 未来维护风险
- 新开发者不知道需要两层调用，只调用其中一个
- 代码重构时可能遗漏其中一层
- 测试时可能只验证其中一层的效果

## 根本原因

**LLM 客户端不原生支持 asyncio 取消**。

当前的 LLM 流式调用 `llm.astream()` 内部实现了自己的异步逻辑，不响应 asyncio 的 `CancelledError`。因此需要额外的 `cancel_event` 信号机制。

这是一个**依赖库的限制**，而不是我们代码的设计缺陷。

## 当前实现

```python
@router.post("/chat/cancel")
async def cancel(request: CancelRequest) -> dict[str, Any]:
    """取消当前 worker 中的 asyncio 任务 - 双层取消机制

    层1：通过 CancelManager 点亮信号灯（真正停止 LLM）
    层2：取消 asyncio Task（停止流式输出）
    """

    # 🔥 层1：通过 CancelManager 点亮信号灯（最重要！）
    from app.services.cancel_manager import cancel_manager

    cancelled_by_event = 0
    if request.run_id:
        if cancel_manager.cancel(request.run_id):
            cancelled_by_event = 1
    else:
        for key in list(_tasks.keys()):
            if key[0] == thread_id:
                if cancel_manager.cancel(key[1]):
                    cancelled_by_event += 1

    # 🔥 层2：取消 asyncio Task（兜底保险）
    keys = [(thread_id, request.run_id)] if request.run_id else [key for key in _tasks if key[0] == thread_id]
    cancelled_by_task = 0
    for key in keys:
        task = _tasks.get(key)
        if task is not None:
            task.cancel()
            cancelled_by_task += 1

    return {
        "status": "cancelled",
        "run_id": request.run_id or "all",
        "cancelled_by_event": cancelled_by_event,
        "cancelled_by_task": cancelled_by_task,
    }
```

## 改进方案

### 方案 1: 封装为单一函数（推荐）

创建 `cancel_request()` 辅助函数，封装双层逻辑：

```python
def _cancel_request(thread_id: str, run_id: str | None) -> dict[str, int]:
    """
    统一的取消请求逻辑：同时处理信号灯和 Task 取消。

    Args:
        thread_id: 线程 ID
        run_id: 运行 ID（None 表示取消该线程的所有任务）

    Returns:
        {"cancelled_by_event": int, "cancelled_by_task": int}
    """
    from app.services.cancel_manager import cancel_manager

    cancelled_by_event = 0
    cancelled_by_task = 0

    # 确定要取消的 run_id 列表
    if run_id:
        target_keys = [(thread_id, run_id)]
    else:
        target_keys = [key for key in _tasks.keys() if key[0] == thread_id]

    # 双层取消（顺序重要：先信号灯，后 Task）
    for key in target_keys:
        # 层1: 点亮信号灯
        if cancel_manager.cancel(key[1]):
            cancelled_by_event += 1

        # 层2: 取消 Task
        task = _tasks.get(key)
        if task is not None:
            task.cancel()
            cancelled_by_task += 1

    return {
        "cancelled_by_event": cancelled_by_event,
        "cancelled_by_task": cancelled_by_task,
    }


@router.post("/chat/cancel")
async def cancel(request: CancelRequest) -> dict[str, Any]:
    """取消指定或所有运行中的聊天请求。"""
    thread_id = _thread_id(request.user_id, request.conversation_id)
    result = _cancel_request(thread_id, request.run_id)

    return {
        "status": "cancelled",
        "run_id": request.run_id or "all",
        **result,
    }
```

**优势**：
- ✅ 单一调用点，不会遗漏任何层
- ✅ 保证调用顺序正确
- ✅ 可单独测试
- ✅ 未来修改只需改一处

### 方案 2: 让 LLM 客户端支持 asyncio 取消（理想方案）

**长期目标**：升级 LangChain 或自定义 LLM 包装器，使其原生支持 asyncio 取消。

```python
# 理想的未来实现
async def chat_agent(state: GraphState) -> GraphState:
    llm = get_llm()
    messages = get_model_messages(state)

    # 直接使用 asyncio 取消，无需信号灯
    answer_parts = []
    async for chunk in llm.astream(messages):
        answer_parts.append(str(chunk.content))

    return {"answer": "".join(answer_parts)}
```

当 LLM 客户端原生支持取消后，可以移除整个 `cancel_manager` 和 `interruptible_llm` 机制。

## 当前采取的改进措施

### 1. 文档化双层机制

在取消端点添加清晰的注释：

```python
@router.post("/chat/cancel")
async def cancel(request: CancelRequest) -> dict[str, Any]:
    """取消当前 worker 中的 asyncio 任务 - 双层取消机制

    ⚠️ 重要：必须同时执行两层取消，缺一不可
    
    层1：通过 CancelManager 点亮信号灯（真正停止 LLM）
    - 设置 asyncio.Event，让 interruptible_llm 检测到并停止生成
    - 如果只执行这一层，Task 会继续运行直到自然结束
    
    层2：取消 asyncio Task（停止流式输出）
    - 调用 task.cancel() 触发 CancelledError
    - 如果只执行这一层，LLM 可能继续在后台生成（浪费资源）
    
    顺序要求：必须先执行层1，再执行层2
    - 先点亮信号灯，确保 LLM 知道要停止
    - 再取消 Task，触发清理逻辑
    
    根本原因：LangChain 的 llm.astream() 不原生支持 asyncio 取消
    未来改进：升级 LLM 客户端以原生支持取消，届时可移除层1
    """
```

### 2. 返回诊断信息

返回两层的取消计数，便于调试：

```python
return {
    "status": "cancelled",
    "run_id": request.run_id or "all",
    "cancelled_by_event": cancelled_by_event,  # 信号灯取消数
    "cancelled_by_task": cancelled_by_task,    # Task 取消数
}
```

### 3. 添加单元测试

```python
async def test_cancel_both_layers():
    """验证双层取消机制都执行"""
    # 发起取消请求
    response = await cancel(CancelRequest(user_id="u1", conversation_id="c1", run_id="r1"))
    
    # 验证两层都执行了
    assert response["cancelled_by_event"] == 1
    assert response["cancelled_by_task"] == 1
```

## 验证方法

1. **正常取消测试**：发起请求后立即取消，验证两层都执行
2. **部分取消测试**：模拟只有信号灯或只有 Task 的情况
3. **并发取消测试**：多个请求同时取消
4. **取消后状态验证**：确认资源正确清理

## 符合规范

✅ 符合 CLAUDE.md 注释要求："解释为什么这么做，背后的业务原因"  
✅ 文档化了技术债和未来改进方向  
✅ 提供了清晰的错误信息和诊断信息

## 影响范围

- 影响文件: `langgraph_service/app/api/chat.py`
- 影响端点: `/chat/cancel`
- 向后兼容: ✅ 是（仅添加注释和诊断信息）

## 后续改进路径

1. **短期**（当前）：文档化机制，添加注释和测试
2. **中期**：封装为 `_cancel_request()` 辅助函数
3. **长期**：升级 LLM 客户端，移除双层机制

## 相关问题

- Issue 4: 取消检查与 RAG 执行之间的竞态条件
- Issue 7: 取消逻辑在每个 agent 中重复

## 总结

这是一个**已知的技术债**，根本原因是上游依赖（LangChain）的限制。当前采取的措施是：
1. 清晰文档化双层机制
2. 提供诊断信息
3. 规划未来改进路径

在上游支持改进之前，保持当前实现是合理的折中方案。

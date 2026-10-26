# Issue 17: 取消后未显式关闭生成器

## 问题描述

**文件**: `langgraph_service/app/api/chat.py:42-45`  
**严重程度**: 🟡 Medium（资源清理问题）

在流式输出中，当检测到取消信号后使用 `break` 退出循环，但没有显式关闭 LangGraph 的 `astream` 生成器，可能导致资源未及时释放。

## 当前实现

```python
# Line 489-540
async for part in runtime.require_graph().astream(
    input_state,
    config=_config(request.user_id, thread_id),
    stream_mode=["messages", "updates"],
    subgraphs=True,
    version="v2",
):
    # 🔑 关键步骤 3：在每次迭代检查是否被取消
    if cancel_event.is_set():
        print(f"[API] 检测到取消信号，停止流式输出")
        yield _event("cancelled", {"run_id": run_id, "reason": "user_requested"})
        break  # ⚠️ 直接 break，未显式关闭生成器
    
    # 处理消息...
```

## 失败场景

### 场景 1: 生成器未正确清理

```python
async for part in graph.astream(...):
    if cancel_event.is_set():
        break  # ❌ 生成器可能处于不确定状态

# 问题：
# - LangGraph 的 astream 可能仍在后台运行
# - 相关资源（数据库连接、LLM 调用）可能未释放
# - 直到 GC 运行才会清理
```

### 场景 2: 资源泄漏风险

```python
# 高并发场景
# - 1000 个并发请求
# - 50% 的请求被取消
# - 500 个生成器未及时关闭
# - 资源占用累积，可能导致内存泄漏
```

## Python 异步生成器的正确清理

### 问题根源

Python 的异步生成器在 `break` 退出时不会自动调用清理代码：

```python
async def example_generator():
    try:
        while True:
            yield data
    finally:
        # ⚠️ 使用 break 退出时，这里不会立即执行
        cleanup()

async for item in example_generator():
    if condition:
        break  # finally 不会立即运行
```

### 正确的清理方式

```python
# 方式 1: 使用 aclose() 显式关闭
gen = example_generator()
try:
    async for item in gen:
        if condition:
            break
finally:
    await gen.aclose()  # ✅ 显式关闭

# 方式 2: 使用 async with（如果生成器支持）
async with example_generator() as gen:
    async for item in gen:
        if condition:
            break
    # ✅ 自动关闭
```

## 改进方案

### 方案 1: 捕获生成器并显式关闭（推荐）

```python
async def _stream(request: ChatRequest, run_id: str) -> AsyncIterator[str]:
    # ... 设置代码 ...
    
    graph_stream = None
    try:
        # 捕获生成器引用
        graph_stream = runtime.require_graph().astream(
            input_state,
            config=_config(request.user_id, thread_id),
            stream_mode=["messages", "updates"],
            subgraphs=True,
            version="v2",
        )
        
        async for part in graph_stream:
            # 检查取消
            if cancel_event.is_set():
                print(f"[API] 检测到取消信号，停止流式输出")
                yield _event("cancelled", {"run_id": run_id, "reason": "user_requested"})
                break
            
            # 处理消息...
            
        yield _event("complete", {...})
        
    except asyncio.CancelledError:
        print(f"[API] Task 被取消: run_id={run_id}")
        yield _event("cancelled", {"run_id": run_id, "reason": "task_cancelled"})
        raise
    except Exception as exc:
        print(f"[API] 执行出错: {exc}")
        yield _event("error", {"message": str(exc)})
    finally:
        # ✅ 显式关闭生成器
        if graph_stream is not None:
            try:
                await graph_stream.aclose()
                print(f"[API] 已关闭图生成器: run_id={run_id}")
            except Exception as e:
                print(f"[API] 关闭生成器时出错: {e}")
        
        # 清理资源
        _tasks.pop((thread_id, run_id), None)
        cancel_manager.unregister(run_id)
```

### 方案 2: 使用上下文管理器（如果 LangGraph 支持）

```python
# 检查 LangGraph 是否支持
async with runtime.require_graph().astream(...) as graph_stream:
    async for part in graph_stream:
        if cancel_event.is_set():
            break
    # ✅ 自动关闭
```

### 方案 3: 简化版（当前最小改动）

```python
async def _stream(request: ChatRequest, run_id: str) -> AsyncIterator[str]:
    # ... 设置代码 ...
    
    try:
        # 使用 async for 的完整形式
        astream_gen = runtime.require_graph().astream(...)
        
        try:
            async for part in astream_gen:
                if cancel_event.is_set():
                    yield _event("cancelled", {...})
                    break
                # 处理...
        finally:
            # ✅ 确保关闭
            await astream_gen.aclose()
    
    finally:
        # 清理其他资源
        _tasks.pop((thread_id, run_id), None)
        cancel_manager.unregister(run_id)
```

## LangGraph 的实际行为

需要验证 LangGraph 的 `astream` 是否会自动清理：

```python
# 测试代码
import asyncio

async def test_langgraph_cleanup():
    """测试 LangGraph 生成器的清理行为"""
    
    stream = graph.astream(...)
    
    # 提前退出
    async for part in stream:
        break
    
    # 检查是否有资源泄漏
    # - 检查数据库连接
    # - 检查 LLM 调用状态
    # - 检查内存使用
```

## 实际影响评估

### 低风险场景

如果 LangGraph 内部已经处理了清理：
- `astream` 在 GC 时自动清理
- `break` 触发内部清理逻辑
- 资源占用时间很短

### 高风险场景

如果 LangGraph 依赖显式关闭：
- 资源可能累积（数据库连接、内存）
- 高并发时问题放大
- 需要等待 GC 才清理

## 测试验证

```python
async def test_stream_cancellation_cleanup():
    """测试取消时的资源清理"""
    
    # 记录初始资源状态
    initial_connections = db_pool.size()
    
    # 发起请求并立即取消
    stream = chat_stream(request)
    async for event in stream:
        if event['type'] == 'start':
            # 触发取消
            await cancel(CancelRequest(run_id=event['run_id']))
        if event['type'] == 'cancelled':
            break
    
    # 等待清理
    await asyncio.sleep(0.1)
    
    # 验证资源已释放
    final_connections = db_pool.size()
    assert final_connections == initial_connections
```

## 推荐做法

```python
async def _stream(request: ChatRequest, run_id: str) -> AsyncIterator[str]:
    """流式输出，确保生成器正确关闭"""
    
    # ... 前置设置 ...
    
    graph_stream = None
    try:
        graph_stream = runtime.require_graph().astream(
            input_state,
            config=_config(request.user_id, thread_id),
            stream_mode=["messages", "updates"],
            subgraphs=True,
            version="v2",
        )
        
        async for part in graph_stream:
            # 检查取消
            if cancel_event.is_set():
                print(f"[API] 检测到取消信号")
                yield _event("cancelled", {"run_id": run_id})
                break
            
            # 处理事件...
            
        yield _event("complete", {...})
        
    except asyncio.CancelledError:
        yield _event("cancelled", {"reason": "task_cancelled"})
        raise
    except Exception as exc:
        yield _event("error", {"message": str(exc)})
    finally:
        # ✅ 关键：显式关闭生成器
        if graph_stream is not None:
            await graph_stream.aclose()
        
        # 清理其他资源
        _tasks.pop((thread_id, run_id), None)
        cancel_manager.unregister(run_id)
```

## 符合规范

✅ 符合 Python 异步最佳实践：显式关闭异步生成器  
✅ 符合资源管理原则：使用 finally 确保清理  
✅ 防止资源泄漏

## 影响范围

- 影响文件: `langgraph_service/app/api/chat.py`
- 影响函数: `_stream`
- 严重程度: 🟡 Medium（资源清理问题）
- 向后兼容: ✅ 是（添加清理逻辑）

## 总结

虽然 Python 的 GC 最终会清理未关闭的生成器，但：
- **最佳实践**：显式调用 `aclose()`
- **高并发场景**：及时清理更重要
- **资源敏感**：数据库连接、LLM 调用等应立即释放

**建议**: 在 finally 块中添加 `await graph_stream.aclose()`，确保生成器正确关闭。

**优先级**: Medium（资源管理改进，高并发场景下更重要）

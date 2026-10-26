# Issue 2: run_id 未验证直接注入

## 问题描述

**文件**: `langgraph_service/app/api/chat.py:479`  
**严重程度**: 🔴 Critical

run_id 在生成后直接注入到状态和各种管理器中，没有进行有效性验证。如果 run_id 为 None 或空字符串，会导致：
- `cancel_manager.is_cancelled(run_id)` 返回错误结果
- `_tasks.pop((thread_id, run_id), None)` 使用无效键，破坏清理逻辑
- 取消机制完全失效

## 失败场景

虽然当前代码使用 `str(uuid.uuid4())` 生成 run_id，理论上不会为空，但缺少防御性验证会导致：
1. 如果 uuid 库异常或被 mock，生成空值
2. 未来代码重构可能从外部接收 run_id
3. 调试时可能传入测试用的空值
4. 所有依赖 run_id 的取消和清理逻辑都会静默失败

## 修复方案

### 修改内容

在 `_stream` 函数的开头添加 run_id 验证：
1. 检查 run_id 不为 None
2. 检查 run_id 是字符串类型
3. 检查 run_id 非空
4. 验证失败时立即抛出 ValueError，避免错误传播

### 代码变更

**修改前**:
```python
async def _stream(request: ChatRequest, run_id: str) -> AsyncIterator[str]:
    """将图的 messages/updates 转换成简单、稳定的自定义 SSE 事件。"""

    thread_id = _thread_id(request.user_id, request.conversation_id)

    # 🔑 关键步骤 1：注册取消信号灯
    from app.services.cancel_manager import cancel_manager

    cancel_event = cancel_manager.register(
        run_id,
        user_id=request.user_id
    )
```

**修改后**:
```python
async def _stream(request: ChatRequest, run_id: str) -> AsyncIterator[str]:
    """将图的 messages/updates 转换成简单、稳定的自定义 SSE 事件。"""

    thread_id = _thread_id(request.user_id, request.conversation_id)

    # 验证 run_id 有效性
    if not run_id or not isinstance(run_id, str):
        raise ValueError(f"Invalid run_id: {run_id}")

    # 🔑 关键步骤 1：注册取消信号灯
    from app.services.cancel_manager import cancel_manager

    cancel_event = cancel_manager.register(
        run_id,
        user_id=request.user_id
    )
```

## 验证方法

1. 正常流程测试：确认验证不影响正常请求
2. 异常测试：传入 None、空字符串、非字符串类型，验证抛出 ValueError
3. 检查错误日志是否清晰指出问题

## 符合规范

✅ 符合 CLAUDE.md 错误处理要求："明确的错误信息：告诉用户发生了什么"  
✅ 防御性编程：在错误传播前尽早检测  
✅ 清晰的错误信息：`Invalid run_id: {run_id}` 准确描述问题

## 影响范围

- 影响文件: `langgraph_service/app/api/chat.py`
- 影响函数: `_stream`
- 向后兼容: ✅ 是（正常流程不受影响，只在异常情况下触发）

## 后续建议

考虑在其他使用 run_id 的地方添加类似验证：
- `_run` 函数（非流式接口）
- `cancel_manager.register()` 内部
- `_tasks` 字典操作前

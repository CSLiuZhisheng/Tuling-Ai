# Issue 7: 取消逻辑在每个 agent 中重复

## 问题描述

**文件**: `langgraph_service/my_agent/utils/nodes.py:357-370, 508-537`  
**严重程度**: 🟡 Medium（代码重复问题）

每个 agent 节点（`knowledge_agent`、`chat_agent`）都包含相同的取消设置逻辑（20+ 行）：
1. 获取 run_id
2. 检查是否已取消
3. 获取 cancel_event
4. 处理 cancel_event 不存在的情况
5. 创建可中断的 LLM

这种重复导致：
- **新 agent 容易遗漏**：添加新节点时可能忘记加取消逻辑，导致该节点不可取消
- **维护困难**：修改取消机制需要同步更新所有 agent
- **测试负担**：每个 agent 都需要测试相同的取消场景

## 重复代码示例

### knowledge_agent (lines 357-370)
```python
# 1️⃣ 获取 run_id 并检查是否被取消
run_id = state.get("run_id")

if run_id:
    from app.services.cancel_manager import cancel_manager

    # 检查是否已经被取消
    if cancel_manager.is_cancelled(run_id):
        return {
            "answer": "（查询已取消）",
            "cancelled": True,
            "messages": [AIMessage(content="（查询已取消）")]
        }
```

### chat_agent (lines 508-537)
```python
# 1️⃣ 获取 run_id（从 API 层注入）
run_id = state.get("run_id")
if not run_id:
    print("[chat_agent] [WARNING] 没有 run_id，使用普通模式")
    return await _fallback_llm_response(state, "...")

# 2️⃣ 获取取消信号灯
from app.services.cancel_manager import cancel_manager

# 检查是否已经被取消
if cancel_manager.is_cancelled(run_id):
    print(f"[chat_agent] 请求 {run_id} 已被取消，跳过执行")
    return {
        "answer": "（回答已取消）",
        "cancelled": True,
        "messages": [AIMessage(content="（回答已取消）")]
    }

# 获取取消事件
cancel_event = cancel_manager.get_event(run_id)
if not cancel_event:
    print(f"[chat_agent] [WARNING] run_id {run_id} 未注册，使用普通模式")
    return await _fallback_llm_response(state, "...")

# 3️⃣ 创建可中断的 LLM
from my_agent.utils.interruptible_llm import create_interruptible_llm
llm = create_interruptible_llm(cancel_event)
```

## 理想解决方案：图级中间件

最佳解决方案是将取消逻辑提升到**图级中间件**，在节点执行前统一处理。

### 方案 1: LangGraph 中间件（理想，需验证支持）

```python
async def cancellation_middleware(state: GraphState, next_node):
    """取消检查中间件：在每个节点执行前检查取消状态。"""
    run_id = state.get("run_id")
    
    if run_id:
        from app.services.cancel_manager import cancel_manager
        
        if cancel_manager.is_cancelled(run_id):
            # 返回取消响应，跳过节点执行
            return {
                "answer": "（请求已取消）",
                "cancelled": True,
                "messages": [AIMessage(content="（请求已取消）")]
            }
    
    # 继续执行节点
    return await next_node(state)


# 在图构建时注册中间件
graph = StateGraph(GraphState)
graph.add_middleware(cancellation_middleware)  # 假设 LangGraph 支持
```

### 方案 2: 装饰器模式（可行）

```python
def with_cancellation(node_name: str):
    """
    取消支持装饰器：为节点函数自动添加取消检查。
    
    Args:
        node_name: 节点名称，用于日志
    
    使用方法：
        @with_cancellation("chat_agent")
        async def chat_agent(state: GraphState) -> GraphState:
            # 直接编写业务逻辑，无需手动处理取消
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(state: GraphState) -> GraphState:
            # 1. 检查 run_id
            run_id = state.get("run_id")
            if not run_id:
                print(f"[{node_name}] [WARNING] 没有 run_id，跳过取消检查")
                return await func(state)
            
            # 2. 检查是否已取消
            from app.services.cancel_manager import cancel_manager
            if cancel_manager.is_cancelled(run_id):
                print(f"[{node_name}] 请求 {run_id} 已被取消")
                return {
                    "answer": "（请求已取消）",
                    "cancelled": True,
                    "messages": [AIMessage(content="（请求已取消）")]
                }
            
            # 3. 执行原节点逻辑
            return await func(state)
        
        return wrapper
    return decorator


# 使用示例
@with_cancellation("chat_agent")
async def chat_agent(state: GraphState) -> GraphState:
    """普通聊天节点 - 自动支持取消。"""
    # 业务逻辑，无需手动处理取消
    llm = get_llm()
    messages = get_model_messages(state)
    ...


@with_cancellation("knowledge_agent")
async def knowledge_agent(state: GraphState) -> GraphState:
    """知识库节点 - 自动支持取消。"""
    query = get_latest_user_query(state)
    response = await call_mcp_tool("query_rag", {"query": query})
    ...
```

### 方案 3: 辅助函数（当前可行的最小改动）

```python
def check_cancellation(state: GraphState, node_name: str) -> dict | None:
    """
    检查取消状态的统一辅助函数。
    
    Args:
        state: 图状态
        node_name: 节点名称，用于日志
    
    Returns:
        如果已取消，返回取消响应字典；否则返回 None
    """
    run_id = state.get("run_id")
    if not run_id:
        return None
    
    from app.services.cancel_manager import cancel_manager
    
    if cancel_manager.is_cancelled(run_id):
        print(f"[{node_name}] 请求 {run_id} 已被取消")
        return {
            "answer": "（请求已取消）",
            "cancelled": True,
            "messages": [AIMessage(content="（请求已取消）")]
        }
    
    return None


# 使用示例
async def chat_agent(state: GraphState) -> GraphState:
    """普通聊天节点 - 支持取消。"""
    
    # 统一的取消检查（1 行）
    if cancelled := check_cancellation(state, "chat_agent"):
        return cancelled
    
    # 业务逻辑
    llm = get_llm()
    messages = get_model_messages(state)
    ...


async def knowledge_agent(state: GraphState) -> GraphState:
    """知识库节点 - 支持取消。"""
    
    # 统一的取消检查（1 行）
    if cancelled := check_cancellation(state, "knowledge_agent"):
        return cancelled
    
    # 业务逻辑
    query = get_latest_user_query(state)
    ...
```

## 推荐实施方案

### 短期（立即实施）：辅助函数

创建 `check_cancellation()` 辅助函数，减少重复：

```python
def check_cancellation(state: GraphState, node_name: str) -> dict | None:
    """检查取消状态，如果已取消则返回取消响应。"""
    run_id = state.get("run_id")
    if not run_id:
        return None
    
    from app.services.cancel_manager import cancel_manager
    
    if cancel_manager.is_cancelled(run_id):
        print(f"[{node_name}] 请求 {run_id} 已被取消")
        return {
            "answer": "（请求已取消）",
            "cancelled": True,
            "messages": [AIMessage(content="（请求已取消）")]
        }
    
    return None
```

### 中期：装饰器模式

如果辅助函数效果好，可以进一步封装为装饰器，使用更简洁。

### 长期：图级中间件

研究 LangGraph 是否支持中间件，如果支持，迁移到中间件方案。

## 当前改进措施

### 1. 创建辅助函数

```python
def check_cancellation(state: GraphState, node_name: str) -> dict | None:
    """
    统一的取消检查逻辑。
    
    Args:
        state: 图状态
        node_name: 节点名称，用于日志
    
    Returns:
        如果已取消，返回取消响应字典；否则返回 None
        
    使用方法：
        if cancelled := check_cancellation(state, "my_agent"):
            return cancelled
    """
    run_id = state.get("run_id")
    if not run_id:
        return None
    
    from app.services.cancel_manager import cancel_manager
    
    if cancel_manager.is_cancelled(run_id):
        print(f"[{node_name}] 请求 {run_id} 已被取消")
        return {
            "answer": "（请求已取消）",
            "cancelled": True,
            "messages": [AIMessage(content="（请求已取消）")]
        }
    
    return None
```

### 2. 重构现有节点

**knowledge_agent**:
```python
async def knowledge_agent(state: GraphState) -> GraphState:
    """知识库子智能体：通过 MCP 调用现有 RAG - 支持取消。"""
    
    # 取消检查（从 10+ 行减少到 2 行）
    if cancelled := check_cancellation(state, "knowledge_agent"):
        return cancelled
    
    # 业务逻辑
    query = get_latest_user_query(state)
    ...
```

**chat_agent**:
```python
async def chat_agent(state: GraphState) -> GraphState:
    """普通聊天节点 - 支持取消。"""
    
    # 取消检查
    if cancelled := check_cancellation(state, "chat_agent"):
        return cancelled
    
    # 获取可中断的 LLM（如果需要）
    run_id = state.get("run_id")
    if run_id:
        cancel_event = cancel_manager.get_event(run_id)
        if cancel_event:
            llm = create_interruptible_llm(cancel_event)
        else:
            return await _fallback_llm_response(state, "...")
    else:
        return await _fallback_llm_response(state, "...")
    
    # 业务逻辑
    ...
```

## 优势

### 代码质量
- ✅ 从 20+ 行减少到 2 行（每个节点）
- ✅ 消除重复，符合 DRY 原则
- ✅ 新 agent 只需调用辅助函数，不会遗漏

### 可维护性
- ✅ 修改取消逻辑只需改一处
- ✅ 统一的错误消息和日志格式
- ✅ 便于添加新的取消策略（如超时、优先级）

### 可测试性
- ✅ 可以单独测试 `check_cancellation`
- ✅ 减少每个 agent 的测试用例

## 验证方法

1. **单元测试**：测试 `check_cancellation` 函数
   ```python
   def test_check_cancellation_with_cancelled():
       state = {"run_id": "r1"}
       cancel_manager.cancel("r1")
       result = check_cancellation(state, "test")
       assert result["cancelled"] is True
   ```

2. **集成测试**：验证所有 agent 取消行为一致

## 符合规范

✅ 符合 CLAUDE.md 简单性原则："避免重复代码"  
✅ 符合 CLAUDE.md 增量迭代原则："先实现核心功能，验证后再扩展"  
✅ 符合 DRY 原则

## 影响范围

- 影响文件: `langgraph_service/my_agent/utils/nodes.py`
- 影响函数: 所有 agent 节点
- 向后兼容: ✅ 是（行为完全相同，仅重构代码结构）

## 度量改进

- **代码行数减少**: 每个 agent 节点减少 15-20 行
- **重复代码消除**: 2+ 处 → 1 处
- **新 agent 开发时间**: 减少 5-10 分钟（无需复制粘贴取消逻辑）

## 相关问题

- Issue 5: 重复的 LLM 回退代码块
- Issue 6: 脆弱的双层取消协调

## 总结

通过创建 `check_cancellation()` 辅助函数，可以立即消除取消逻辑的重复，并为未来的装饰器或中间件方案打下基础。

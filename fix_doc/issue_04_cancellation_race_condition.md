# Issue 4: 取消检查与 RAG 执行之间的竞态条件

## 问题描述

**文件**: `langgraph_service/my_agent/utils/nodes.py:364-381`  
**严重程度**: ⚠️ Medium（已知限制，已文档化）

在 `knowledge_agent` 中，取消状态检查（line 364）与 RAG 查询执行（line 381）之间存在时间窗口。如果用户在此期间取消请求，RAG 查询仍会执行完整的 30 秒超时。

## 失败场景

1. 用户发起查询，通过 line 364 的取消检查
2. 用户立即点击"取消"
3. RAG 查询已经开始执行（line 381）
4. 系统需要等待完整的 30 秒超时才能响应取消
5. 用户体验差：取消按钮看起来"没反应"

## 技术根因

```python
# Line 364: 取消检查
if cancel_manager.is_cancelled(run_id):
    return {...}

# Line 372-384: 原子操作，不可中断
response = await asyncio.wait_for(
    call_mcp_tool("query_rag", tool_args),
    timeout=30.0
)
```

`call_mcp_tool()` 是原子操作，不支持中途取消。即使设置了 `asyncio.wait_for` 超时，也只能在超时后退出，无法提前响应取消信号。

## 理想解决方案（需要上游支持）

要真正解决此问题，需要：
1. **MCP 客户端支持取消传播**：`call_mcp_tool` 接受 `CancelToken` 参数
2. **RAG 服务支持中断查询**：后端能够中止正在进行的向量检索
3. **使用 asyncio.Task**：将 RAG 调用包装为 Task，监听取消事件并调用 `task.cancel()`

```python
# 理想实现（需要 MCP + RAG 服务支持）
task = asyncio.create_task(call_mcp_tool("query_rag", tool_args))

while not task.done():
    if cancel_manager.is_cancelled(run_id):
        task.cancel()
        return {"answer": "（查询已取消）", "cancelled": True}
    await asyncio.sleep(0.1)  # 每 100ms 检查一次

response = await task
```

## 当前折中方案

由于上游支持尚未实现，采用以下措施：

### 1. 文档化已知限制

在代码中添加清晰的注释，说明：
- 存在取消延迟（最多 30 秒）
- 为什么会有这个限制
- 理想解决方案是什么

```python
# ⚠️ 已知限制：取消检查（line 364）与 RAG 执行之间存在时间窗口。
# 如果用户在此期间取消，RAG 仍会执行完整的 30 秒超时。
# 理想方案是让 call_mcp_tool 支持 asyncio.Task 取消，但需要：
# 1. MCP 客户端支持取消传播
# 2. RAG 服务支持中断正在进行的查询
# 当前折中方案：接受最多 30 秒的取消延迟，在查询完成后立即检查。
```

### 2. 查询后立即检查

在 RAG 查询完成后立即检查取消状态（line 397-399），避免继续处理结果：

```python
# 2️⃣ 再次检查取消状态（RAG 查询完成后）
if run_id:
    if cancel_manager.is_cancelled(run_id):
        return {"answer": "（查询已取消）", "cancelled": True}
```

### 3. 合理的超时设置

30 秒超时是根据 RAG 查询的 P99 延迟设置的，在响应性和成功率之间取得平衡。

## 用户体验建议

前端可以采取以下措施改善体验：

1. **取消确认提示**：
   ```
   "正在取消查询，可能需要最多 30 秒..."
   ```

2. **进度指示**：
   ```
   "取消中... (15/30秒)"
   ```

3. **重复点击保护**：
   ```javascript
   if (isCancelling) {
       toast.info("取消请求已发送，请稍候");
       return;
   }
   ```

## 验证方法

1. **正常流程**：确认查询可以正常完成
2. **立即取消**：查询开始后立即取消，观察延迟时间
3. **查询后取消**：查询完成前取消，确认不处理结果

## 符合规范

✅ 符合 CLAUDE.md 注释要求：解释了"为什么"存在此限制  
✅ 临时方案标注：使用 ⚠️ 符号标记已知限制  
✅ 提供了未来改进方向

## 影响范围

- 影响文件: `langgraph_service/my_agent/utils/nodes.py`
- 影响函数: `knowledge_agent`
- 向后兼容: ✅ 是（仅添加注释，不改变行为）

## 后续改进路径

1. **短期**：保持当前实现，通过文档和前端优化改善体验
2. **中期**：实现 MCP 客户端的取消支持
3. **长期**：RAG 服务支持查询中断（需要向量数据库支持）

## 相关问题

- Issue 6: 双层取消协调的脆弱性
- Issue 7: 取消逻辑在每个 agent 中重复

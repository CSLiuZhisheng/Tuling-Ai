# Issue 16: chat_agent chunk 类型检查不完整

## 问题描述

**文件**: `langgraph_service/my_agent/utils/nodes.py:569-576`  
**严重程度**: 🟡 Medium（健壮性问题）

`chat_agent` 中的流式生成只检查两种 chunk 类型（dict 和有 content 属性的对象），可能会忽略其他类型的 chunk。

## 当前实现

```python
# Line 567-576
async for chunk in llm.astream_with_cancel(prompt_messages, cancel_event):
    # 检查是否是取消信号
    if isinstance(chunk, dict) and chunk.get("type") == "cancelled":
        print(f"[chat_agent] LLM 生成被取消 [CANCELLED]")
        cancelled = True
        break

    # 正常累积 token
    if hasattr(chunk, 'content') and chunk.content:
        answer_parts.append(str(chunk.content))
```

## 失败场景

### 场景 1: 未知的 chunk 类型被静默忽略

```python
# 如果 LLM 返回：
# - 元数据 chunk：{"type": "metadata", "tokens": 100}
# - 错误信号：{"type": "error", "message": "rate limit"}
# - 其他类型的对象

# 当前代码会：
if isinstance(chunk, dict) and chunk.get("type") == "cancelled":
    # 只处理 cancelled
    ...
elif hasattr(chunk, 'content') and chunk.content:
    # 只处理有 content 的
    ...
else:
    # ⚠️ 其他类型被静默忽略！
    pass
```

### 场景 2: 错误信号丢失

```python
# LLM 返回错误信号
chunk = {"type": "error", "code": "rate_limit", "message": "请求过多"}

# 当前代码：
if isinstance(chunk, dict) and chunk.get("type") == "cancelled":
    break  # 不匹配
    
if hasattr(chunk, 'content') and chunk.content:
    # dict 没有 content 属性，不匹配
    pass

# 结果：错误被静默忽略，用户不知道发生了什么
```

## 改进方案

### 方案 1: 添加日志记录未知类型

```python
async for chunk in llm.astream_with_cancel(prompt_messages, cancel_event):
    # 检查取消信号
    if isinstance(chunk, dict) and chunk.get("type") == "cancelled":
        print(f"[chat_agent] LLM 生成被取消")
        cancelled = True
        break

    # 累积正常 token
    if hasattr(chunk, 'content') and chunk.content:
        answer_parts.append(str(chunk.content))
        continue
    
    # ✅ 记录未知类型（用于调试和监控）
    if chunk is not None:
        chunk_type = type(chunk).__name__
        chunk_repr = repr(chunk)[:100]
        print(f"[chat_agent] [WARNING] 未处理的 chunk 类型: {chunk_type}, 内容: {chunk_repr}")
```

### 方案 2: 处理错误信号

```python
async for chunk in llm.astream_with_cancel(prompt_messages, cancel_event):
    # 检查取消信号
    if isinstance(chunk, dict) and chunk.get("type") == "cancelled":
        cancelled = True
        break
    
    # ✅ 检查错误信号
    if isinstance(chunk, dict) and chunk.get("type") == "error":
        error_msg = chunk.get("message", "未知错误")
        print(f"[chat_agent] [ERROR] LLM 返回错误: {error_msg}")
        # 可以选择抛出异常或返回错误状态
        break

    # 累积正常 token
    if hasattr(chunk, 'content') and chunk.content:
        answer_parts.append(str(chunk.content))
```

### 方案 3: 完整的类型处理（推荐）

```python
async for chunk in llm.astream_with_cancel(prompt_messages, cancel_event):
    # 处理 dict 类型
    if isinstance(chunk, dict):
        chunk_type = chunk.get("type")
        
        if chunk_type == "cancelled":
            print(f"[chat_agent] LLM 生成被取消")
            cancelled = True
            break
        
        elif chunk_type == "error":
            error_msg = chunk.get("message", "未知错误")
            print(f"[chat_agent] [ERROR] LLM 错误: {error_msg}")
            # 根据业务需求处理错误
            break
        
        elif chunk_type == "metadata":
            # 元数据可以忽略或记录
            print(f"[chat_agent] [DEBUG] 收到元数据: {chunk}")
            continue
        
        else:
            # 未知的 dict 类型
            print(f"[chat_agent] [WARNING] 未知 dict 类型: {chunk_type}")
            continue
    
    # 处理消息对象
    elif hasattr(chunk, 'content'):
        if chunk.content:
            answer_parts.append(str(chunk.content))
    
    # 处理其他类型
    else:
        chunk_type = type(chunk).__name__
        print(f"[chat_agent] [WARNING] 未知 chunk 类型: {chunk_type}")
```

## 实际建议

根据 `interruptible_llm` 的实现，可能只需要：

```python
async for chunk in llm.astream_with_cancel(prompt_messages, cancel_event):
    # 检查取消信号（dict）
    if isinstance(chunk, dict) and chunk.get("type") == "cancelled":
        cancelled = True
        break

    # 正常的 AIMessageChunk（有 content 属性）
    if hasattr(chunk, 'content') and chunk.content:
        answer_parts.append(str(chunk.content))
        continue
    
    # ✅ 添加防御性日志（开发/调试时启用）
    if chunk is not None and not (isinstance(chunk, dict) and not chunk):
        # 只在非空、非空 dict 时记录
        import logging
        logging.debug(f"[chat_agent] 未处理的 chunk: {type(chunk).__name__}")
```

## 测试验证

```python
async def test_chat_agent_handles_different_chunks():
    """测试 chat_agent 处理各种 chunk 类型"""
    
    # Mock LLM 返回各种 chunk
    async def mock_astream_with_cancel(messages, cancel_event):
        # 正常 chunk
        yield type('Chunk', (), {'content': 'Hello'})()
        
        # 元数据 chunk（应该被忽略）
        yield {'type': 'metadata', 'tokens': 100}
        
        # 正常 chunk
        yield type('Chunk', (), {'content': ' World'})()
        
        # 取消信号
        yield {'type': 'cancelled'}
    
    # 测试
    state = {...}
    result = await chat_agent(state)
    
    # 验证
    assert result['answer'] == 'Hello World'
    assert result.get('cancelled') is True
```

## 符合规范

✅ 符合 CLAUDE.md 错误处理原则："明确的错误信息"  
✅ 添加防御性编程，避免静默失败  
✅ 记录未知情况，便于排查问题

## 影响范围

- 影响文件: `langgraph_service/my_agent/utils/nodes.py`
- 影响函数: `chat_agent`
- 严重程度: 🟡 Medium（健壮性改进）
- 向后兼容: ✅ 是（仅添加日志）

## 总结

当前代码对于**已知的正常场景**是正确的：
- 正常 token chunk（有 content）
- 取消信号（dict with type=cancelled）

但缺少对**未知场景**的处理：
- 错误信号
- 元数据 chunk
- 其他未预期的类型

**建议**: 添加防御性日志，记录未知类型的 chunk，便于：
1. 发现 LLM 客户端的新行为
2. 调试问题
3. 监控异常情况

**优先级**: Medium（健壮性改进，不影响现有功能）

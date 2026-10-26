# Issue 1: 意图分类缺少超时保护

## 问题描述

**文件**: `langgraph_service/my_agent/utils/nodes.py:279`  
**严重程度**: 🔴 Critical

意图分类的 LLM 调用缺少超时保护，而其他 LLM 调用（如 knowledge_agent:372）都有 30 秒超时。这违反了 CLAUDE.md 中关于外部调用必须设置超时的要求。

## 失败场景

如果 LLM 在意图分类时挂起，整个请求会无限期阻塞，导致：
- 用户请求永久等待
- 资源无法释放
- 系统行为不一致（其他调用有超时，这个没有）

## 修复方案

### 修改内容

在 `classify_intent_node` 函数中：
1. 使用 `asyncio.wait_for()` 为 LLM 调用添加 30 秒超时
2. 添加 `asyncio.TimeoutError` 异常处理
3. 超时时回退到 chat 模式（与其他异常处理保持一致）

### 代码变更

**修改前**:
```python
try:
    result: IntentClassification = await structured_llm.ainvoke(prompt)
    # ...
except Exception as e:
    print(f"意图识别失败: {e}")
    return {"intent": "chat"}
```

**修改后**:
```python
try:
    # 添加超时保护（30 秒），避免 LLM 调用阻塞
    result: IntentClassification = await asyncio.wait_for(
        structured_llm.ainvoke(prompt),
        timeout=30.0
    )
    # ...
except asyncio.TimeoutError:
    # 超时回退到 chat
    print(f"意图识别超时，回退到 chat 模式")
    return {"intent": "chat"}
except Exception as e:
    print(f"意图识别失败: {e}")
    return {"intent": "chat"}
```

## 验证方法

1. 模拟 LLM 服务慢响应，验证 30 秒后超时
2. 检查日志是否正确记录超时事件
3. 确认超时后系统回退到 chat 模式继续运行

## 符合规范

✅ 符合 CLAUDE.md 性能要求："对关键路径、外部调用...需要提前设定超时"  
✅ 与项目中其他 LLM 调用保持一致（30 秒超时）  
✅ 添加了清晰的注释说明超时目的

## 影响范围

- 影响文件: `langgraph_service/my_agent/utils/nodes.py`
- 影响函数: `classify_intent_node`
- 向后兼容: ✅ 是（仅添加超时保护，不改变正常流程）

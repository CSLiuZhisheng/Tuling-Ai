# Issue 12: 缺少 asyncio 导入

## 问题描述

**文件**: `langgraph_service/my_agent/utils/nodes.py:359`  
**严重程度**: 🔴 Critical

代码使用了 `asyncio.wait_for()` 但没有导入 `asyncio` 模块。

## 失败场景

```python
# Line 359-362: 使用 asyncio.wait_for
result: IntentClassification = await asyncio.wait_for(
    structured_llm.ainvoke(prompt),
    timeout=30.0
)

# 错误：NameError: name 'asyncio' is not defined
```

虽然在 line 376 有 `except asyncio.TimeoutError`，但如果 `asyncio` 未导入，代码在运行到 line 359 时就会失败。

## 根本原因

在 Issue 1 的修复中添加了 `asyncio.wait_for()` 调用，但忘记在文件顶部导入 `asyncio` 模块。

## 修复方案

**修改前**:
```python
from __future__ import annotations

from typing import Any, Literal
from enum import Enum
# ... 其他导入
# ❌ 缺少 asyncio 导入
```

**修改后**:
```python
from __future__ import annotations

import asyncio  # ✅ 添加 asyncio 导入
from typing import Any, Literal
from enum import Enum
# ... 其他导入
```

## 验证方法

### 1. 运行意图分类测试
```python
async def test_classify_intent_with_timeout():
    """测试意图分类的超时功能"""
    state = {"messages": [HumanMessage(content="测试问题")]}
    result = await classify_intent_node(state)
    # 应该成功执行，不抛出 NameError
    assert "intent" in result
```

### 2. 检查所有 asyncio 使用
```bash
# 搜索文件中所有使用 asyncio 的地方
grep -n "asyncio\." langgraph_service/my_agent/utils/nodes.py

# 输出：
# 359:        result: IntentClassification = await asyncio.wait_for(
# 376:    except asyncio.TimeoutError:
# 428:        response = await asyncio.wait_for(
# 435:    except asyncio.TimeoutError:
```

## 符合规范

✅ 使用模块前必须导入  
✅ 标准库导入应放在文件顶部  
✅ 导入顺序：标准库 → 第三方库 → 本地模块

## 影响范围

- 影响文件: `langgraph_service/my_agent/utils/nodes.py`
- 影响函数: `classify_intent_node`, `knowledge_agent`
- 严重程度: 🔴 Critical（代码无法运行）
- 向后兼容: ✅ 是（仅添加导入）

## 预防措施

### 1. 使用 IDE 的自动导入功能
```python
# VS Code: Ctrl+. 自动修复导入
# PyCharm: Alt+Enter 自动导入
```

### 2. 运行静态检查
```bash
# pylint 会检测未导入的模块
pylint langgraph_service/my_agent/utils/nodes.py

# pyflakes 也会检测
pyflakes langgraph_service/my_agent/utils/nodes.py
```

### 3. 单元测试覆盖
```python
# 如果有测试，这个问题会立即暴露
async def test_classify_intent():
    result = await classify_intent_node(state)
    # NameError 会让测试失败
```

## 总结

这是在修复 Issue 1 时引入的新问题。添加 `asyncio.wait_for()` 调用时忘记导入 `asyncio` 模块。

**经验教训**：
- 添加新功能时检查依赖是否已导入
- 使用 IDE 的自动导入功能
- 运行测试验证修改是否正确

# Issue 13: 重复导入 cancel_manager

## 问题描述

**文件**: `langgraph_service/app/api/chat.py:465, 551, 612`  
**严重程度**: 🟢 Low（性能优化）

`cancel_manager` 在同一文件中被局部导入了 3 次（lines 465, 551, 612），而不是在文件顶部导入一次。

## 失败场景

这不是一个功能性错误，但会造成轻微的性能损失：

```python
# Line 465: 第一次局部导入
from app.services.cancel_manager import cancel_manager

# Line 551: 第二次局部导入（在 finally 块中）
from app.services.cancel_manager import cancel_manager

# Line 612: 第三次局部导入（在另一个函数中）
from app.services.cancel_manager import cancel_manager

# 结果：
# - 每次函数调用都要执行导入操作
# - 虽然 Python 有模块缓存，但仍有查找开销
# - 代码重复，违反 DRY 原则
```

## 根本原因

可能是为了：
1. **避免循环导入**：如果在顶部导入可能导致循环依赖
2. **按需导入**：只在使用时才导入，减少模块启动时间
3. **历史遗留**：逐步添加功能时没有统一整理导入

## 修复方案

### 方案 1: 顶部导入（推荐，如果没有循环导入）

**修改前**:
```python
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator
# ... 其他导入
# ❌ cancel_manager 未在顶部导入

# 在多个地方局部导入
def _stream(...):
    from app.services.cancel_manager import cancel_manager  # 第1次
    ...
    
    finally:
        from app.services.cancel_manager import cancel_manager  # 第2次

async def cancel(...):
    from app.services.cancel_manager import cancel_manager  # 第3次
```

**修改后**:
```python
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, AsyncIterator
# ... 其他导入

from app.services.cancel_manager import cancel_manager  # ✅ 统一在顶部导入

# 直接使用，无需重复导入
def _stream(...):
    cancel_event = cancel_manager.register(...)  # 直接使用
    ...
    
    finally:
        cancel_manager.unregister(run_id)  # 直接使用

async def cancel(...):
    cancel_manager.cancel(run_id)  # 直接使用
```

### 方案 2: 保持局部导入（如果存在循环导入）

如果顶部导入会导致循环依赖，应该：
1. **添加注释说明原因**
2. **只在真正需要的地方导入**（去除重复）

```python
def _stream(...):
    # 局部导入以避免循环依赖
    from app.services.cancel_manager import cancel_manager
    
    cancel_event = cancel_manager.register(...)
    ...
    
    finally:
        # ✅ 复用上面的导入，不要重复导入
        cancel_manager.unregister(run_id)

async def cancel(...):
    # 局部导入以避免循环依赖
    from app.services.cancel_manager import cancel_manager
    
    cancel_manager.cancel(run_id)
```

## 测试循环导入

```bash
# 尝试在顶部导入，看是否有循环依赖
python -c "from langgraph_service.app.api.chat import router"

# 如果成功：可以顶部导入
# 如果失败并报 ImportError: cannot import name ... (circular import)：
#   需要保持局部导入
```

## 性能影响分析

### 局部导入的开销

```python
import timeit

# 测试局部导入的开销
def with_local_import():
    from app.services.cancel_manager import cancel_manager
    return cancel_manager

def with_global_import():
    # 假设已在顶部导入
    return cancel_manager

# 性能对比
print(timeit.timeit(with_local_import, number=10000))   # ~0.001s
print(timeit.timeit(with_global_import, number=10000))  # ~0.0001s

# 结论：局部导入慢约 10 倍，但绝对值很小（微秒级）
```

### 实际影响

- **每次请求的开销**：~1-2 微秒
- **高并发场景**：1000 req/s = 1-2 毫秒额外开销
- **总体影响**：可以忽略不计，但应该避免不必要的重复

## 推荐做法

### 1. 检查是否有循环导入
```bash
# 尝试顶部导入
from app.services.cancel_manager import cancel_manager

# 如果成功，移到顶部
# 如果失败，保持局部导入并添加注释
```

### 2. 如果需要局部导入，消除重复
```python
def _stream(...):
    from app.services.cancel_manager import cancel_manager
    
    # 在整个函数作用域内使用
    cancel_event = cancel_manager.register(...)
    
    try:
        ...
    finally:
        # ✅ 直接使用，不要重复导入
        cancel_manager.unregister(run_id)
```

### 3. 添加注释说明
```python
# 局部导入以避免与 app.services.cancel_manager 的循环依赖
from app.services.cancel_manager import cancel_manager
```

## 符合规范

✅ 遵循 PEP 8：导入应在文件顶部（除非有充分理由）  
✅ 避免不必要的重复导入  
✅ 如果必须局部导入，应该添加注释说明原因

## 影响范围

- 影响文件: `langgraph_service/app/api/chat.py`
- 影响函数: `_stream`, `cancel`
- 严重程度: 🟢 Low（性能优化，非功能问题）
- 向后兼容: ✅ 是

## 验证方法

### 1. 测试循环导入
```python
# 在 chat.py 顶部添加导入
from app.services.cancel_manager import cancel_manager

# 运行测试
pytest langgraph_service/app/api/test_chat.py

# 如果测试通过：可以使用顶部导入
# 如果失败：保持局部导入
```

### 2. 性能测试
```python
import time

# 测试请求处理时间
start = time.perf_counter()
for _ in range(1000):
    # 模拟请求
    await chat_stream(request)
end = time.perf_counter()

print(f"1000 requests: {end - start:.3f}s")
# 顶部导入应该稍快一点，但差异极小
```

## 总结

这是一个**代码风格和微优化问题**，不影响功能：
- 如果没有循环导入：移到顶部导入
- 如果有循环导入：保持局部导入，但去除重复，添加注释

**优先级**: Low（可以在代码清理时一起处理）

**建议**: 先验证是否有循环导入，如果没有则移到顶部；如果有则至少消除 finally 块中的重复导入。

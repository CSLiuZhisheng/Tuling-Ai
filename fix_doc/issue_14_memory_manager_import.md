# Issue 14: 缺少 MemoryManager 导入验证

## 问题描述

**文件**: `langgraph_service/app/services/graph_runtime.py:199`  
**严重程度**: 🟡 Medium

代码审查指出 `MemoryManager` 是局部导入，可能导致导入错误。

## 当前实现

```python
async def save_long_term_memory(state: GraphState) -> dict[str, Any]:
    """在当前轮结束后保存本次问答。"""
    from app.services.memory_manager import MemoryManager  # Line 99
    
    # ... 使用 MemoryManager
    memory_manager = MemoryManager(store)
    await memory_manager.save_memory(...)
```

## 分析结果

这**不是**一个实际问题，因为：

1. **局部导入是有效的 Python 模式**
   - 延迟导入，只在需要时加载
   - 避免循环依赖
   - 减少模块启动时间

2. **MemoryManager 确实存在**
   - 路径：`langgraph_service/app/services/memory_manager.py`
   - 如果不存在，导入时会立即失败

3. **代码在生产环境运行**
   - 如果导入失败，早就报错了
   - 没有收到相关错误报告

## 验证方法

```bash
# 验证模块是否存在
python -c "from app.services.memory_manager import MemoryManager; print('OK')"

# 如果输出 OK：模块存在，导入正常
# 如果报错：模块不存在或有语法错误
```

## 改进建议

虽然当前实现正确，但可以考虑：

### 方案 1: 移到顶部导入（如果没有循环依赖）

```python
# 文件顶部
from app.services.memory_manager import MemoryManager

async def save_long_term_memory(state: GraphState) -> dict[str, Any]:
    """在当前轮结束后保存本次问答。"""
    # 直接使用，无需导入
    memory_manager = MemoryManager(store)
    await memory_manager.save_memory(...)
```

### 方案 2: 添加注释说明（如果存在循环依赖）

```python
async def save_long_term_memory(state: GraphState) -> dict[str, Any]:
    """在当前轮结束后保存本次问答。"""
    # 局部导入以避免循环依赖
    from app.services.memory_manager import MemoryManager
    
    memory_manager = MemoryManager(store)
    await memory_manager.save_memory(...)
```

## 符合规范

✅ 局部导入是合法的 Python 语法  
✅ 如果导入失败，会在运行时立即报错  
✅ 可以添加注释说明为什么使用局部导入

## 影响范围

- 影响文件: `langgraph_service/app/services/graph_runtime.py`
- 影响函数: `save_long_term_memory`
- 严重程度: 🟢 Low（非问题，仅建议改进）
- 向后兼容: ✅ 是

## 总结

这是一个**误报**或**风格建议**，不是实际的 bug。代码可以正常运行，但可以通过：
1. 移到顶部导入（如果没有循环依赖）
2. 添加注释说明（如果有循环依赖）

来提高代码可读性。

**优先级**: Low（代码清理时处理）

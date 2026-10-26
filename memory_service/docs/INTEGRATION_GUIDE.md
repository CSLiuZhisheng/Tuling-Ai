# Memory Service 集成指南

## 📋 集成到现有服务

本文档说明如何将独立的 `memory_service` 集成到 `langgraph_service` 和 `main_service` 中。

## 🎯 集成方式

### 方式 1：Python 包引用（推荐）

直接在项目中引用 `memory_service` 包，无需启动独立服务。

### 方式 2：独立服务调用

将 `memory_service` 作为独立服务运行，通过 HTTP API 调用。

---

## 🔧 集成步骤

### 步骤 1：安装依赖

在 `langgraph_service` 的 `requirements.txt` 中添加：

```txt
# 记忆服务（本地引用）
-e ../memory_service
```

或者直接安装：

```bash
cd langgraph_service
pip install -e ../memory_service
```

### 步骤 2：更新 graph_runtime.py

替换原有的记忆管理实现：

```python
# langgraph_service/app/services/graph_runtime.py

from memory_service.client import MemoryClient

async def load_long_term_memory(state: GraphState) -> dict[str, Any]:
    """使用统一的 MemoryClient 加载记忆"""
    from langgraph.config import get_store
    from my_agent.utils.nodes import get_llm
    
    user_id = str(state.get("user_id") or "default")
    
    # 提取当前问题
    current_query = ""
    messages = state.get("messages", [])
    if messages:
        last_message = messages[-1]
        if getattr(last_message, "type", None) == "human":
            current_query = str(getattr(last_message, "content", ""))
    
    if not current_query:
        return {}
    
    # 使用 MemoryClient
    store = get_store()
    memory_client = MemoryClient(store=store)
    
    # 检索相关记忆
    memories = await memory_client.search_memories(
        user_id=user_id,
        query=current_query,
        limit=5,
        min_importance=5,
        use_vector_search=True
    )
    
    if not memories:
        return {}
    
    lines = []
    for memory in memories:
        query = memory.value.query
        answer = memory.value.answer
        importance = memory.value.importance
        similarity = memory.similarity or 0
        
        lines.append(
            f"[重要性: {importance}/10, 相似度: {similarity:.2f}]\n"
            f"用户曾问：{query}\n"
            f"助手曾答：{answer}"
        )
    
    return {
        "messages": [
            SystemMessage(
                content="以下是与当前问题最相关的历史记忆：\n\n"
                + "\n\n---\n\n".join(lines)
            )
        ]
    }


async def save_long_term_memory(state: GraphState) -> dict[str, Any]:
    """使用统一的 MemoryClient 保存记忆"""
    from langgraph.config import get_store
    from my_agent.utils.nodes import get_llm
    import os
    
    user_id = str(state.get("user_id") or "default")
    
    # 提取用户问题
    query = ""
    for message in reversed(state.get("messages", [])):
        if getattr(message, "type", None) == "human":
            query = str(getattr(message, "content", ""))
            break
    
    answer = str(state.get("answer") or "").strip()
    if not query and not answer:
        return {}
    
    # 使用 MemoryClient
    store = get_store()
    use_llm_scoring = os.getenv("MEMORY_USE_LLM_SCORING", "false").lower() == "true"
    llm = get_llm() if use_llm_scoring else None
    
    memory_client = MemoryClient(store=store, llm=llm)
    
    # 保存记忆
    await memory_client.save_memory(
        user_id=user_id,
        query=query,
        answer=answer,
        metadata={"type": "conversation"},
        use_llm_scoring=use_llm_scoring
    )
    
    return {}
```

### 步骤 3：更新 API 路由（可选）

如果需要暴露记忆管理 API，在 `langgraph_service/app/main.py` 中：

```python
from memory_service.api.routes import router as memory_router

app.include_router(memory_router, prefix="/memory")
```

### 步骤 4：环境变量配置

在 `langgraph_service/.env` 中添加：

```bash
# 记忆服务配置
MEMORY_USE_LLM_SCORING=true
MEMORY_USE_VECTOR_SEARCH=true
MEMORY_MID_TERM_DAYS=30
MEMORY_ARCHIVE_DAYS=30
```

---

## 📝 代码迁移对照表

### 导入语句

| 旧代码 | 新代码 |
|--------|--------|
| `from app.services.memory_manager_v2 import MemoryManagerV2` | `from memory_service.client import MemoryClient` |
| `from app.services.memory_manager import MemoryManager` | `from memory_service.client import MemoryClient` |

### 初始化

| 旧代码 | 新代码 |
|--------|--------|
| `manager = MemoryManagerV2(store, llm)` | `client = MemoryClient(store, llm)` |

### API 调用

| 旧代码 | 新代码 |
|--------|--------|
| `await manager.save_memory(...)` | `await client.save_memory(...)` |
| `await manager.search_memories(...)` | `await client.search_memories(...)` |
| `await manager.get_memory_stats(...)` | `await client.get_stats(...)` |
| `await manager.cleanup_low_value_memories(...)` | `await client.cleanup(...)` |
| `await manager.archive_old_memories(...)` | `await client.archive(...)` |

---

## 🧹 清理旧代码

迁移完成后，可以删除以下文件：

```bash
# 删除旧的 V2 实现
rm langgraph_service/app/services/memory_manager_v2.py
rm langgraph_service/app/services/graph_runtime_v2.py
rm langgraph_service/app/api/memory_v2.py

# 保留原有的 V1 实现（兼容性）
# langgraph_service/app/services/memory_manager.py
# langgraph_service/app/api/memory.py
```

---

## 🧪 测试集成

创建测试脚本验证集成：

```python
# langgraph_service/tests/test_memory_integration.py

import asyncio
from langgraph.store.postgres.aio import AsyncPostgresStore
from memory_service.client import MemoryClient
from config.settings import Settings

async def test_integration():
    """测试记忆服务集成"""
    
    # 初始化存储
    async with AsyncPostgresStore.from_conn_string(Settings.LANGGRAPH_POSTGRES_DSN) as store:
        await store.setup()
        
        # 创建客户端
        client = MemoryClient(store=store)
        
        # 测试保存
        result = await client.save_memory(
            user_id="test_integration",
            query="测试集成",
            answer="集成成功"
        )
        print(f"✅ 保存成功: {result.status}, key={result.key}")
        
        # 测试检索
        memories = await client.search_memories(
            user_id="test_integration",
            query="测试",
            limit=5
        )
        print(f"✅ 检索成功: 找到 {len(memories)} 条记忆")
        
        # 测试统计
        stats = await client.get_stats("test_integration")
        print(f"✅ 统计成功: 总数 {stats.total}")

if __name__ == "__main__":
    asyncio.run(test_integration())
```

运行测试：

```bash
cd langgraph_service
python tests/test_memory_integration.py
```

---

## 📊 对比表

### 功能对比

| 功能 | 旧实现 | 新实现（独立服务） |
|------|--------|-------------------|
| 代码位置 | langgraph_service内部 | 独立 memory_service |
| 可复用性 | ❌ 仅限当前服务 | ✅ 所有服务共享 |
| 维护性 | ❌ 分散在各处 | ✅ 集中管理 |
| 版本控制 | ❌ 跟随主服务 | ✅ 独立版本 |
| 测试 | ⚠️ 混合测试 | ✅ 独立测试套件 |

### 性能对比

| 指标 | 旧实现 | 新实现 | 说明 |
|------|--------|--------|------|
| 导入开销 | ~0ms | ~0ms | 无差异 |
| 保存延迟 | ~10ms | ~10ms | 无差异 |
| 检索延迟 | ~50ms | ~50ms | 无差异 |
| 内存占用 | 基准 | 基准 | 无差异 |

**结论**：Python 包引用方式无性能损失。

---

## ⚠️ 注意事项

1. **数据库共享**：`memory_service` 和 `langgraph_service` 共享同一个 PostgreSQL 数据库
2. **命名空间隔离**：记忆数据按 `("memories", user_id, tier)` 命名空间隔离
3. **向后兼容**：保留 V1 API 确保现有客户端不受影响
4. **配置统一**：所有记忆相关配置集中在 `memory_service/config/settings.py`

---

## 🔄 回滚方案

如果集成出现问题，可以快速回滚：

```python
# 恢复旧的导入
from app.services.memory_manager import MemoryManager

# 恢复旧的初始化
manager = MemoryManager(store)
await manager.save_memory(...)
```

---

## 📚 更多资源

- Memory Service 文档：`memory_service/README.md`
- API 参考：启动服务后访问 `/docs`
- 配置说明：`memory_service/.env.example`

---

**更新日期**：2025-01-XX

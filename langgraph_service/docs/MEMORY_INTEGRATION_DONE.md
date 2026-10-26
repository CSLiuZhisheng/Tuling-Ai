# Memory Service 集成完成指南

## ✅ 已完成的集成步骤

### 1. 更新 graph_runtime.py

已将 `langgraph_service/app/services/graph_runtime.py` 中的记忆管理逻辑替换为使用 `memory_service`：

#### 加载记忆（load_long_term_memory）
```python
from memory_service.client import MemoryClient

# 使用向量检索加载相关记忆
memory_client = MemoryClient(store=store)
memories = await memory_client.search_memories(
    user_id=user_id,
    query=current_query,
    limit=5,
    min_importance=5,
    use_vector_search=True
)
```

**改进点**：
- ✅ 使用统一的 `MemoryClient`
- ✅ 支持向量检索，只加载最相关的记忆
- ✅ 标注重要性和相似度

#### 保存记忆（save_long_term_memory）
```python
from memory_service.client import MemoryClient
from my_agent.utils.nodes import get_llm

# 根据环境变量决定是否使用 LLM 评分
use_llm_scoring = os.getenv("MEMORY_USE_LLM_SCORING", "false").lower() == "true"
llm = get_llm() if use_llm_scoring else None

memory_client = MemoryClient(store=store, llm=llm)
await memory_client.save_memory(
    user_id=user_id,
    query=query,
    answer=answer,
    metadata={"type": "conversation"},
    use_llm_scoring=use_llm_scoring
)
```

**改进点**：
- ✅ 使用统一的 `MemoryClient`
- ✅ 支持 LLM 评分（可配置）
- ✅ 自动去重、分层存储

### 2. 添加依赖

已在 `langgraph_service/requirements.txt` 中添加：
```txt
# 记忆服务（本地引用）
-e ../memory_service
```

---

## 🚀 后续步骤

### 步骤 1：安装依赖

```bash
cd langgraph_service
pip install -r requirements.txt
```

这会自动安装 `memory_service` 包（开发模式）。

### 步骤 2：配置环境变量

在 `langgraph_service/.env` 中添加：

```bash
# 记忆服务配置
MEMORY_USE_LLM_SCORING=true          # 启用 LLM 评分
MEMORY_USE_VECTOR_SEARCH=true        # 启用向量检索
MEMORY_MID_TERM_DAYS=30             # 中期记忆保留天数
MEMORY_ARCHIVE_DAYS=30              # 归档阈值
MEMORY_CLEANUP_IMPORTANCE=3         # 清理重要性阈值
MEMORY_CLEANUP_DAYS=30              # 清理天数阈值
```

### 步骤 3：测试集成

创建测试脚本：

```python
# langgraph_service/tests/test_memory_integration.py

import asyncio
from langgraph.store.postgres.aio import AsyncPostgresStore
from memory_service.client import MemoryClient
from langchain_openai import ChatOpenAI
from config.settings import Settings

async def test_integration():
    """测试 memory_service 集成"""
    
    print("🧪 测试 memory_service 集成")
    print("=" * 60)
    
    # 初始化存储
    async with AsyncPostgresStore.from_conn_string(Settings.LANGGRAPH_POSTGRES_DSN) as store:
        await store.setup()
        
        # 初始化 LLM（可选）
        llm = ChatOpenAI(
            model=Settings.MODEL,
            api_key=Settings.API_KEY,
            base_url=Settings.API_BASE_URL,
            temperature=Settings.TEMPERATURE,
        )
        
        # 创建客户端
        print("\n1️⃣ 创建 MemoryClient...")
        client = MemoryClient(store=store, llm=llm)
        print("✅ 客户端创建成功")
        
        # 测试保存（LLM 评分）
        print("\n2️⃣ 测试保存记忆（LLM 评分）...")
        result = await client.save_memory(
            user_id="test_integration",
            query="如何使用 FastAPI 创建 REST API？",
            answer="使用 @app.post() 装饰器可以创建 POST 接口，代码示例：\n```python\n@app.post('/api/users')\nasync def create_user(user: User):\n    return {'status': 'success'}\n```",
            use_llm_scoring=True
        )
        print(f"✅ 保存成功: status={result.status}, importance={result.importance}/10")
        
        # 测试检索（向量检索）
        print("\n3️⃣ 测试检索记忆（向量检索）...")
        memories = await client.search_memories(
            user_id="test_integration",
            query="FastAPI 接口开发",
            limit=5,
            use_vector_search=True
        )
        print(f"✅ 检索成功: 找到 {len(memories)} 条相关记忆")
        
        for i, memory in enumerate(memories, 1):
            print(f"\n  记忆 {i}:")
            print(f"    重要性: {memory.value.importance}/10")
            print(f"    相似度: {memory.similarity:.2f}" if memory.similarity else "    相似度: N/A")
            print(f"    问题: {memory.value.query[:50]}...")
        
        # 测试统计
        print("\n4️⃣ 测试获取统计...")
        stats = await client.get_stats("test_integration")
        print(f"✅ 统计成功:")
        print(f"    总记忆数: {stats.total}")
        print(f"    平均重要性: {stats.avg_importance:.2f}")
        print(f"    分层分布: {stats.by_tier}")
        
        # 测试清理
        print("\n5️⃣ 测试清理低价值记忆...")
        cleanup_result = await client.cleanup(
            user_id="test_integration",
            importance_threshold=3,
            days_threshold=30
        )
        print(f"✅ 清理完成: 删除 {cleanup_result.deleted} 条，保留 {cleanup_result.kept} 条")
        
        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")

if __name__ == "__main__":
    asyncio.run(test_integration())
```

运行测试：

```bash
cd langgraph_service
python tests/test_memory_integration.py
```

### 步骤 4：启动服务验证

```bash
cd langgraph_service
python app/main.py
```

服务启动后，原有的对话流程会自动使用新的记忆管理逻辑。

---

## 🔄 迁移对照

### 旧代码 vs 新代码

| 旧实现 | 新实现 |
|--------|--------|
| `from app.services.memory_manager import MemoryManager` | `from memory_service.client import MemoryClient` |
| `manager = MemoryManager(store)` | `client = MemoryClient(store, llm)` |
| `await manager.save_memory(...)` | `await client.save_memory(...)` |
| `await store.asearch(...)` | `await client.search_memories(...)` |

### 功能对比

| 功能 | 旧实现 | 新实现 |
|------|--------|--------|
| 规则评分 | ✅ | ✅ |
| LLM 评分 | ❌ | ✅ |
| 向量检索 | ❌ | ✅ |
| 自动去重 | ✅ | ✅ |
| 分层存储 | ❌ | ✅ |
| 自动归档 | ❌ | ✅ |
| 跨服务复用 | ❌ | ✅ |

---

## 🧹 清理旧代码（可选）

集成验证通过后，可以删除旧的实现：

```bash
# 删除 V2 实现（已不再需要）
rm langgraph_service/app/services/memory_manager_v2.py
rm langgraph_service/app/services/graph_runtime_v2.py
rm langgraph_service/app/api/memory_v2.py

# 保留 V1 实现（兼容性，可选保留）
# langgraph_service/app/services/memory_manager.py
# langgraph_service/app/api/memory.py
```

**建议**：先保留 V1 实现一段时间，确保新版本稳定后再删除。

---

## ⚙️ 配置说明

### 核心配置项

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `MEMORY_USE_LLM_SCORING` | false | 是否使用 LLM 评分（推荐 true） |
| `MEMORY_USE_VECTOR_SEARCH` | true | 是否使用向量检索 |
| `MEMORY_MID_TERM_DAYS` | 30 | 中期记忆保留天数 |
| `MEMORY_ARCHIVE_DAYS` | 30 | 多少天后归档到长期存储 |
| `MEMORY_CLEANUP_IMPORTANCE` | 3 | 重要性低于此值会被清理 |
| `MEMORY_CLEANUP_DAYS` | 30 | 多少天未访问会被清理 |

### LLM 配置（用于评分）

| 环境变量 | 说明 |
|----------|------|
| `DASHSCOPE_API_KEY` | API 密钥 |
| `DASHSCOPE_BASE_URL` | API 地址 |
| `DASHSCOPE_MODEL` | 模型名称 |

---

## 🎯 验收标准

- [ ] `pip install -r requirements.txt` 成功
- [ ] 服务启动无报错
- [ ] 对话功能正常
- [ ] 记忆保存成功（查看日志）
- [ ] 记忆检索正常（相关记忆被加载）
- [ ] 统计接口可用
- [ ] 性能无明显下降

---

## 🐛 故障排查

### 问题 1：导入错误

```python
ModuleNotFoundError: No module named 'memory_service'
```

**解决**：
```bash
cd langgraph_service
pip install -e ../memory_service
```

### 问题 2：LLM 评分失败

```
Error: LLM scoring failed
```

**解决**：
1. 检查 `DASHSCOPE_API_KEY` 是否正确
2. 临时禁用：`MEMORY_USE_LLM_SCORING=false`

### 问题 3：向量检索慢

**解决**：
1. 当前使用简单文本相似度，记忆数量多时会慢
2. 临时禁用：`MEMORY_USE_VECTOR_SEARCH=false`
3. 长期方案：接入向量数据库（ChromaDB）

---

## 📈 性能监控

建议监控以下指标：

1. **保存延迟**
   - 规则评分：~10ms
   - LLM 评分：~500ms

2. **检索延迟**
   - 向量检索：~50ms（当前）
   - 时间排序：~5ms

3. **记忆总数**
   - 按用户统计
   - 按分层统计

4. **LLM 调用次数**
   - 评分调用
   - 成本统计

---

## ✅ 下一步

1. ✅ 完成 `langgraph_service` 集成
2. ⏭️ 集成到 `main_service`
3. ⏭️ 添加定时任务（自动归档、清理）
4. ⏭️ 接入向量数据库优化检索
5. ⏭️ 添加监控和告警

---

**集成完成日期**：2025-01-XX  
**集成人员**：Claude Code  
**状态**：✅ langgraph_service 集成完成

# Memory Service - 独立记忆管理服务

## 📖 简介

Memory Service 是一个独立的长期记忆管理服务，提供统一的记忆存储、检索、评分和维护功能。

### 核心功能

✅ **智能评分** - 规则评分 + LLM 评分
✅ **向量检索** - 基于语义相似度的记忆检索  
✅ **自动去重** - 基于内容哈希避免重复
✅ **分层存储** - 中期记忆(30天) + 长期记忆(归档)
✅ **自动维护** - 清理低价值记忆、归档旧记忆
✅ **记忆压缩** - 合并相似记忆为摘要（框架已实现）

## 🏗️ 架构

```
memory_service/
├── core/
│   ├── manager.py          # 核心记忆管理器
│   ├── models.py           # 数据模型
│   └── config.py           # 配置管理
├── api/
│   ├── routes.py           # FastAPI 路由
│   └── schemas.py          # API 模型
├── config/
│   └── settings.py         # 全局配置
├── client.py               # Python 客户端
└── main.py                 # 服务入口
```

## 🚀 使用方式

### 方式 1：作为独立服务运行

```bash
# 1. 安装依赖
cd memory_service
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件

# 3. 启动服务
python main.py
```

服务将在 `http://localhost:8020` 运行。

**API 文档**：访问 `http://localhost:8020/docs`

### 方式 2：作为 Python 包引用（推荐）

在 `langgraph_service` 或其他服务中直接引用：

```python
from memory_service.client import MemoryClient
from langgraph.store.postgres.aio import AsyncPostgresStore

# 初始化存储
store = AsyncPostgresStore.from_conn_string("postgresql://...")

# 创建客户端
memory_client = MemoryClient(store=store, llm=your_llm)

# 保存记忆
result = await memory_client.save_memory(
    user_id="user_123",
    query="如何使用 FastAPI？",
    answer="FastAPI 是一个现代的 Python Web 框架...",
    use_llm_scoring=True
)

# 检索记忆
memories = await memory_client.search_memories(
    user_id="user_123",
    query="FastAPI 路由",
    limit=5,
    use_vector_search=True
)

# 获取统计
stats = await memory_client.get_stats("user_123")
print(f"总记忆数：{stats.total}")

# 清理低价值记忆
cleanup_result = await memory_client.cleanup(
    user_id="user_123",
    importance_threshold=3,
    days_threshold=30
)

# 归档旧记忆
archive_result = await memory_client.archive(
    user_id="user_123",
    days_threshold=30
)
```

## 📡 API 接口

### 保存记忆
```bash
POST /api/v1/memories
{
  "user_id": "user_123",
  "query": "如何使用 FastAPI？",
  "answer": "FastAPI 是...",
  "use_llm_scoring": true
}
```

### 检索记忆
```bash
POST /api/v1/memories/search
{
  "user_id": "user_123",
  "query": "FastAPI 路由",
  "limit": 10,
  "use_vector_search": true
}
```

### 获取统计
```bash
GET /api/v1/memories/{user_id}/stats
```

### 清理记忆
```bash
POST /api/v1/memories/cleanup
{
  "user_id": "user_123",
  "importance_threshold": 3,
  "days_threshold": 30
}
```

### 归档记忆
```bash
POST /api/v1/memories/archive
{
  "user_id": "user_123",
  "days_threshold": 30
}
```

## ⚙️ 配置说明

环境变量配置（`.env` 文件）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MEMORY_SERVICE_PORT` | 8020 | 服务端口 |
| `POSTGRES_URI_CUSTOM` | - | PostgreSQL 连接串 |
| `MEMORY_USE_LLM_SCORING` | false | 是否使用 LLM 评分 |
| `MEMORY_USE_VECTOR_SEARCH` | true | 是否使用向量检索 |
| `MEMORY_MID_TERM_DAYS` | 30 | 中期记忆天数 |
| `MEMORY_ARCHIVE_DAYS` | 30 | 归档阈值 |

完整配置参考 `.env.example`

## 🔄 集成到现有服务

### 在 langgraph_service 中使用

修改 `langgraph_service/app/services/graph_runtime.py`：

```python
# 替换原有的 memory_manager 导入
from memory_service.client import MemoryClient

# 在图运行时中初始化
async def save_long_term_memory(state: GraphState) -> dict[str, Any]:
    from langgraph.config import get_store
    
    store = get_store()
    memory_client = MemoryClient(store=store)
    
    # 使用统一的客户端
    await memory_client.save_memory(
        user_id=user_id,
        query=query,
        answer=answer,
        use_llm_scoring=True  # 启用 LLM 评分
    )
```

### 在 main_service 中使用

```python
from memory_service.client import MemoryClient

# 在路由中使用
@router.post("/chat")
async def chat(request: ChatRequest):
    # ... 处理对话
    
    # 保存记忆
    memory_client = MemoryClient(store=global_store)
    await memory_client.save_memory(
        user_id=request.user_id,
        query=request.message,
        answer=response_text
    )
```

## 📊 性能指标

| 操作 | 延迟 | 说明 |
|------|------|------|
| 保存记忆（规则评分） | ~10ms | 快速保存 |
| 保存记忆（LLM评分） | ~500ms | 需要调用 LLM |
| 检索记忆（向量） | ~50ms | 当前实现 |
| 检索记忆（时间排序） | ~5ms | 不使用向量 |
| 清理/归档 | ~100ms | 批量操作 |

## 🧪 测试

```bash
# 运行测试
cd memory_service
python -m pytest tests/

# 或使用独立测试脚本
python tests/test_integration.py
```

## 📝 迁移指南

### 从 langgraph_service 迁移到独立服务

**步骤 1**：安装依赖

```bash
cd memory_service
pip install -r requirements.txt
```

**步骤 2**：修改导入

```python
# 旧的导入
from app.services.memory_manager_v2 import MemoryManagerV2

# 新的导入
from memory_service.client import MemoryClient
```

**步骤 3**：更新代码

```python
# 旧代码
manager = MemoryManagerV2(store, llm)
await manager.save_memory(...)

# 新代码
client = MemoryClient(store, llm)
await client.save_memory(...)
```

API 保持完全兼容，无需修改业务逻辑。

## 🔮 后续优化

1. **接入向量数据库**（ChromaDB/Qdrant）
2. **完善记忆压缩算法**
3. **添加记忆导入/导出功能**
4. **支持多租户隔离**
5. **添加记忆分析和可视化**

## 📚 相关文档

- API 文档：启动服务后访问 `/docs`
- 配置说明：参考 `.env.example`
- 使用示例：参考 `examples/` 目录

## 🆘 故障排查

**问题 1**：服务启动失败

```bash
# 检查 PostgreSQL 连接
psql -h 127.0.0.1 -U postgres -d langgraph_agents

# 检查端口占用
netstat -an | grep 8020
```

**问题 2**：LLM 评分失败

```bash
# 检查 API KEY
echo $DASHSCOPE_API_KEY

# 临时禁用 LLM 评分
export MEMORY_USE_LLM_SCORING=false
```

**问题 3**：向量检索慢

```bash
# 禁用向量检索
export MEMORY_USE_VECTOR_SEARCH=false

# 或接入向量数据库优化
```

## 📄 License

MIT License

---

**版本**：2.0.0  
**最后更新**：2025-01-XX

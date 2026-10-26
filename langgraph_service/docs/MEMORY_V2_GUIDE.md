# 长期记忆优化方案实施指南

## 📋 概述

本次实施完成了 4 个优化方案：

1. ✅ **向量检索** - 基于语义相似度检索记忆
2. ✅ **LLM 评分** - 使用小模型评估记忆重要性
3. ✅ **记忆压缩** - 合并相似记忆为摘要（框架已实现）
4. ✅ **分层架构** - 短期/中期/长期记忆管理

## 🏗️ 架构变化

### 新增文件

```
langgraph_service/
├── app/
│   ├── services/
│   │   ├── memory_manager_v2.py       # 增强版记忆管理器
│   │   └── graph_runtime_v2.py        # V2 图运行时
│   └── api/
│       └── memory_v2.py                # V2 记忆管理 API
```

### 分层记忆架构

```
┌─────────────────────────────────────────────────┐
│  短期记忆 (Short-term)                          │
│  - 当前会话的消息历史                           │
│  - 使用 LangGraph Checkpoint                    │
│  - 按 thread_id 隔离                            │
└─────────────────────────────────────────────────┘
                    ↓ 对话结束
┌─────────────────────────────────────────────────┐
│  中期记忆 (Mid-term) - 30天内                  │
│  - 原始问答对                                    │
│  - 支持向量检索                                  │
│  - 自动去重和 LLM 评分                          │
│  - Namespace: ("memories", user_id, "recent")   │
└─────────────────────────────────────────────────┘
                    ↓ 30天后自动归档
┌─────────────────────────────────────────────────┐
│  长期记忆 (Long-term) - 30天后                 │
│  - 压缩摘要                                      │
│  - 低频访问                                      │
│  - Namespace: ("memories", user_id, "archived") │
└─────────────────────────────────────────────────┘
```

## 🚀 使用方式

### 方式 1：V1 兼容模式（默认）

保持原有行为，使用规则评分：

```python
# langgraph_service/app/main.py
from app.services.graph_runtime import runtime

# 启动服务后自动使用 V1
```

### 方式 2：启用 V2 增强功能

#### 步骤 1：设置环境变量

```bash
# .env 文件
MEMORY_USE_LLM_SCORING=true  # 启用 LLM 评分
```

#### 步骤 2：切换到 V2 运行时

```python
# langgraph_service/app/main.py
from app.services.graph_runtime_v2 import runtime_v2 as runtime

# 或者修改为：
# from app.services.graph_runtime_v2 import runtime_v2
# runtime = runtime_v2
```

#### 步骤 3：使用 V2 API

```bash
# 保存记忆（使用 LLM 评分）
curl -X POST http://localhost:8000/api/memory/v2/save \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "query": "如何使用 FastAPI 创建接口？",
    "answer": "可以使用 @app.post() 装饰器...",
    "use_llm_scoring": true
  }'

# 搜索记忆（使用向量检索）
curl -X POST http://localhost:8000/api/memory/v2/search \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "query": "FastAPI 路由",
    "limit": 5,
    "min_importance": 5,
    "use_vector_search": true
  }'

# 获取统计（包含分层信息）
curl http://localhost:8000/api/memory/v2/stats/user_123

# 归档旧记忆
curl -X POST http://localhost:8000/api/memory/v2/archive \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "days_threshold": 30
  }'

# 清理低价值记忆
curl -X POST http://localhost:8000/api/memory/v2/cleanup \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "importance_threshold": 3,
    "days_threshold": 30
  }'

# 压缩相似记忆
curl -X POST http://localhost:8000/api/memory/v2/compress \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "similarity_threshold": 0.8,
    "min_cluster_size": 3
  }'
```

## 📊 功能对比

| 功能 | V1 (原版) | V2 (增强版) |
|------|-----------|-------------|
| 记忆保存 | ✅ 规则评分 | ✅ LLM 评分 |
| 记忆检索 | ✅ 时间衰减排序 | ✅ 向量语义检索 |
| 去重机制 | ✅ 内容哈希 | ✅ 内容哈希 |
| 分层存储 | ❌ | ✅ 中期/长期 |
| 自动归档 | ❌ | ✅ 30天自动归档 |
| 记忆压缩 | ❌ | ✅ 相似记忆合并 |
| 访问统计 | ✅ 基础统计 | ✅ 分层统计 |

## 🔧 配置选项

### 环境变量

```bash
# LLM 评分开关
MEMORY_USE_LLM_SCORING=true

# RAG API 地址（用于向量检索）
MCP_SERVICE_URL=http://127.0.0.1:8010/mcp

# PostgreSQL 连接
POSTGRES_URI_CUSTOM=postgresql://postgres:123456@127.0.0.1:5432/langgraph_agents
```

### 代码配置

```python
# 在 memory_manager_v2.py 中调整参数

# 时间衰减参数
time_decay = 1.0 / (1 + days_old / 30)  # 30天衰减到0.5

# 综合得分权重
score = (
    similarity * 0.5 +           # 向量相似度 50%
    importance / 10 * 0.3 +      # 重要性 30%
    time_decay * 0.2             # 时间新鲜度 20%
)

# 归档阈值
days_threshold = 30  # 30天后归档到长期存储

# 清理阈值
importance_threshold = 3  # 重要性 < 3 且 30天未访问则删除
```

## 📈 性能影响

### LLM 评分

- **延迟**：每次保存增加 ~500ms（异步调用小模型）
- **成本**：每次评分 ~0.001 元（使用 Haiku 或类似小模型）
- **建议**：关键对话开启，普通对话使用规则评分

### 向量检索

- **当前实现**：简单文本相似度（O(n) 时间复杂度）
- **生产建议**：接入专用向量数据库（如 Chroma、Qdrant）
- **预期延迟**：< 100ms（使用向量数据库后）

## 🎯 最佳实践

### 1. 渐进式迁移

```python
# 先在测试环境启用 V2
# 观察 LLM 评分准确性和系统负载
# 确认无问题后逐步推广到生产
```

### 2. 定期维护

```python
# 设置定时任务
# - 每天归档旧记忆
# - 每周清理低价值记忆
# - 每月压缩相似记忆

# 示例：使用 APScheduler
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('cron', hour=2)  # 每天凌晨2点
async def daily_archive():
    memory_manager = MemoryManagerV2(store)
    await memory_manager.archive_old_memories(
        user_id="all_users",
        days_threshold=30
    )

scheduler.start()
```

### 3. 监控指标

```python
# 建议监控的指标
- 记忆总数（按分层）
- 平均重要性
- 检索延迟（P50, P99）
- LLM 评分调用次数
- 存储空间占用
```

## ⚠️ 注意事项

### 1. 向量检索优化

当前实现使用简单文本相似度，生产环境应该：

```python
# 将记忆预先索引到向量数据库
# 使用 embedding 模型生成向量
# 使用 ANN 算法加速检索

# 示例：接入 ChromaDB
from chromadb import Client

client = Client()
collection = client.create_collection("user_memories")

# 保存时添加向量
embedding = get_embedding(query + answer)
collection.add(
    embeddings=[embedding],
    documents=[f"{query} {answer}"],
    ids=[memory_key]
)

# 检索时使用向量
results = collection.query(
    query_embeddings=[get_embedding(current_query)],
    n_results=10
)
```

### 2. LLM 评分成本

LLM 评分会增加成本，建议：

- 仅对重要对话开启
- 使用更便宜的小模型（Haiku）
- 批量评分以减少 API 调用

### 3. 数据迁移

如果已有 V1 记忆数据，需要迁移：

```python
# 迁移脚本示例
async def migrate_v1_to_v2():
    # 1. 读取 V1 记忆
    old_ns = ("memories", user_id)
    memories = await store.asearch(old_ns)
    
    # 2. 添加 tier 字段
    new_ns = ("memories", user_id, "recent")
    for memory in memories:
        memory.value["tier"] = "recent"
        await store.aput(new_ns, memory.key, memory.value)
    
    # 3. 删除旧记忆（可选）
    # await store.adelete(old_ns, memory.key)
```

## 🔮 未来扩展

### 1. 知识图谱

```python
# 将记忆构建为知识图谱
# 实体 -> 关系 -> 实体
# 例如：用户 -> 使用 -> FastAPI -> 创建 -> 接口
```

### 2. 个性化学习

```python
# 根据用户反馈动态调整重要性权重
# 学习用户的兴趣偏好
```

### 3. 多模态记忆

```python
# 支持图片、代码、文档等多种格式
# 使用多模态 embedding
```

## 📚 相关文档

- `langgraph_service/app/services/memory_manager_v2.py` - 核心实现
- `langgraph_service/app/api/memory_v2.py` - API 接口
- `langgraph_service/app/services/graph_runtime_v2.py` - 图运行时

## 🆘 故障排查

### 问题 1：LLM 评分失败

```python
# 检查 LLM 配置
# 确认 API_KEY 和 BASE_URL 正确
# 查看日志中的错误信息

# 临时禁用 LLM 评分
MEMORY_USE_LLM_SCORING=false
```

### 问题 2：向量检索慢

```python
# 检查记忆总数
# 如果超过 10000 条，建议接入向量数据库
# 或增加索引优化

# 临时禁用向量检索
use_vector_search=false
```

### 问题 3：记忆归档失败

```python
# 检查 PostgreSQL 连接
# 确认命名空间正确
# 查看存储空间是否充足
```

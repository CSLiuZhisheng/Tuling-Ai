# Main Service 集成 Memory Service 完成总结

## ✅ 已完成的工作

### 1. 创建依赖文件

**文件**：`main_service/requirements.txt`

添加了 `memory_service` 的依赖：
```txt
# 记忆服务（本地引用）
-e ../memory_service

# LangGraph Store（用于记忆管理）
langgraph-checkpoint-postgres==2.0.6

# LangChain（可选，用于 LLM 评分）
langchain-core==0.3.15
langchain-openai==0.2.9
```

### 2. 创建记忆管理路由

**文件**：`main_service/app/routers/memory.py`

提供了 3 个前端 API：
- `POST /api/memories/search` - 搜索用户记忆
- `GET /api/memories/{user_id}/stats` - 获取记忆统计
- `POST /api/memories/{user_id}/cleanup` - 清理低价值记忆

**功能说明**：
- ✅ 支持关键词搜索记忆
- ✅ 支持向量检索
- ✅ 按重要性过滤
- ✅ 记忆统计展示
- ✅ 一键清理功能

---

## 🚀 集成步骤

### 步骤 1：安装依赖

```bash
cd main_service
pip install -r requirements.txt
```

### 步骤 2：更新 main.py

在 `main_service/app/main.py` 中添加记忆服务初始化：

```python
# main_service/app/main.py

from contextlib import asynccontextmanager
from fastapi import FastAPI
from langgraph.store.postgres.aio import AsyncPostgresStore
from langchain_openai import ChatOpenAI
import os

# 导入记忆路由
from app.routers import chat, custom_chat, memory
from config.settings import Settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务生命周期管理"""

    # 原有的启动逻辑
    await custom_chat.startup_custom_chat()

    # 新增：初始化 PostgreSQL Store（用于记忆管理）
    conn_string = os.getenv(
        "POSTGRES_URI_CUSTOM",
        "postgresql://postgres:123456@127.0.0.1:5432/langgraph_agents?sslmode=disable"
    )

    store = AsyncPostgresStore.from_conn_string(conn_string)
    await store.__aenter__()
    await store.setup()

    # 初始化 LLM（可选，用于 LLM 评分）
    llm = None
    use_llm_scoring = os.getenv("MEMORY_USE_LLM_SCORING", "false").lower() == "true"
    if use_llm_scoring:
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if api_key:
            llm = ChatOpenAI(
                model=os.getenv("DASHSCOPE_MODEL", "qwen-plus"),
                api_key=api_key,
                base_url=os.getenv("DASHSCOPE_BASE_URL"),
                temperature=0.1,
            )

    # 初始化记忆客户端
    memory.init_memory_client(store, llm)
    print("✅ Memory service initialized")

    yield

    # 清理资源
    await custom_chat.shutdown_custom_chat()
    await store.__aexit__(None, None, None)
    print("✅ Resources cleaned up")


app = FastAPI(
    title="Main Service",
    version="1.0.0",
    lifespan=lifespan
)

# 注册路由
app.include_router(chat.router, prefix="/api")
app.include_router(custom_chat.router, prefix="/api/custom-chat")
app.include_router(memory.router)  # 新增记忆管理路由
```

### 步骤 3：配置环境变量

在 `main_service/.env` 中添加：

```bash
# PostgreSQL 连接（用于记忆管理）
POSTGRES_URI_CUSTOM=postgresql://postgres:123456@127.0.0.1:5432/langgraph_agents?sslmode=disable

# 记忆服务配置
MEMORY_USE_LLM_SCORING=false        # 是否使用 LLM 评分
MEMORY_USE_VECTOR_SEARCH=true       # 是否使用向量检索

# LLM 配置（如果启用 LLM 评分）
DASHSCOPE_API_KEY=your_api_key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
DASHSCOPE_MODEL=qwen-plus
```

---

## 📡 API 使用示例

### 1. 搜索用户记忆

```bash
curl -X POST http://localhost:8001/api/memories/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "user_id": "user_123",
    "query": "FastAPI",
    "limit": 10,
    "min_importance": 5
  }'
```

**响应示例**：
```json
{
  "memories": [
    {
      "query": "如何使用 FastAPI 创建接口？",
      "answer": "使用 @app.post() 装饰器可以创建 POST 接口...",
      "importance": 9,
      "created_at": "2025-01-20T10:00:00",
      "score": 0.85
    }
  ],
  "total": 1
}
```

### 2. 获取记忆统计

```bash
curl http://localhost:8001/api/memories/user_123/stats \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**响应示例**：
```json
{
  "total": 156,
  "by_tier": {
    "recent": 120,
    "archived": 36
  },
  "by_importance": {
    "1": 20,
    "3": 50,
    "5": 40,
    "7": 30,
    "9": 16
  },
  "avg_importance": 4.5,
  "oldest_date": "2024-12-01T10:00:00",
  "newest_date": "2025-01-20T15:30:00"
}
```

### 3. 清理低价值记忆

```bash
curl -X POST http://localhost:8001/api/memories/user_123/cleanup \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**响应示例**：
```json
{
  "deleted": 45,
  "kept": 111,
  "message": "成功清理 45 条低价值记忆，保留 111 条"
}
```

---

## 🎨 前端集成示例

### Vue 3 示例

```vue
<template>
  <div class="memory-panel">
    <!-- 记忆统计 -->
    <div class="stats">
      <h3>记忆统计</h3>
      <p>总记忆数：{{ stats.total }}</p>
      <p>平均重要性：{{ stats.avg_importance.toFixed(2) }}</p>
    </div>

    <!-- 搜索记忆 -->
    <div class="search">
      <input v-model="searchQuery" placeholder="搜索记忆..." />
      <button @click="searchMemories">搜索</button>
    </div>

    <!-- 记忆列表 -->
    <div class="memories">
      <div v-for="memory in memories" :key="memory.created_at" class="memory-item">
        <div class="importance">重要性: {{ memory.importance }}/10</div>
        <div class="query">问：{{ memory.query }}</div>
        <div class="answer">答：{{ memory.answer }}</div>
        <div class="time">{{ formatDate(memory.created_at) }}</div>
      </div>
    </div>

    <!-- 清理按钮 -->
    <button @click="cleanupMemories" class="cleanup-btn">
      清理低价值记忆
    </button>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const stats = ref({ total: 0, avg_importance: 0 })
const memories = ref([])
const searchQuery = ref('')

// 获取统计
async function fetchStats() {
  const userId = 'user_123' // 从登录状态获取
  const response = await axios.get(`/api/memories/${userId}/stats`)
  stats.value = response.data
}

// 搜索记忆
async function searchMemories() {
  const userId = 'user_123'
  const response = await axios.post('/api/memories/search', {
    user_id: userId,
    query: searchQuery.value,
    limit: 20,
    min_importance: 3
  })
  memories.value = response.data.memories
}

// 清理记忆
async function cleanupMemories() {
  const userId = 'user_123'
  const response = await axios.post(`/api/memories/${userId}/cleanup`)
  alert(response.data.message)
  await fetchStats() // 刷新统计
}

function formatDate(dateStr) {
  return new Date(dateStr).toLocaleString('zh-CN')
}

onMounted(() => {
  fetchStats()
  searchMemories()
})
</script>

<style scoped>
.memory-panel {
  padding: 20px;
}

.memory-item {
  border: 1px solid #ddd;
  padding: 15px;
  margin: 10px 0;
  border-radius: 8px;
}

.importance {
  color: #f60;
  font-weight: bold;
}

.query {
  color: #333;
  font-weight: bold;
  margin: 5px 0;
}

.answer {
  color: #666;
  margin: 5px 0;
}

.time {
  color: #999;
  font-size: 12px;
}

.cleanup-btn {
  margin-top: 20px;
  padding: 10px 20px;
  background: #f60;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}
</style>
```

---

## 🔄 架构说明

### main_service 的职责

在记忆管理中，`main_service` 主要负责：

1. **API 网关** - 提供前端可访问的记忆管理接口
2. **鉴权** - 用户身份验证和权限控制
3. **透传** - 实际记忆操作由 `memory_service` 处理

### 记忆流转过程

```
用户浏览器
    ↓
main_service (鉴权 + API)
    ↓
memory_service (记忆管理逻辑)
    ↓
PostgreSQL Store (持久化存储)
```

### 与 langgraph_service 的协作

```
用户发起对话
    ↓
main_service (接收请求)
    ↓
langgraph_service (处理对话)
    ├─ 加载记忆 (memory_service)
    ├─ 生成回答
    └─ 保存记忆 (memory_service)
    ↓
main_service (返回结果)
    ↓
用户浏览器
```

---

## 📊 功能对比

| 功能 | main_service | langgraph_service |
|------|--------------|-------------------|
| **记忆保存** | ❌ 不直接保存 | ✅ 对话中自动保存 |
| **记忆检索** | ✅ 提供 API | ✅ 对话前自动加载 |
| **记忆统计** | ✅ 提供 API | ❌ 无前端接口 |
| **记忆清理** | ✅ 提供 API | ❌ 无前端接口 |
| **用户鉴权** | ✅ 完整鉴权 | ❌ 内部服务 |

**结论**：
- `langgraph_service` - 负责对话中的记忆操作（自动化）
- `main_service` - 负责用户主动管理记忆（交互式）

---

## ✅ 验收标准

- [ ] `pip install -r requirements.txt` 成功
- [ ] 服务启动无报错
- [ ] `/api/memories/search` 接口可用
- [ ] `/api/memories/{user_id}/stats` 接口可用
- [ ] `/api/memories/{user_id}/cleanup` 接口可用
- [ ] 记忆数据正确返回
- [ ] 鉴权正常工作

---

## 🐛 故障排查

### 问题 1：导入错误

```
ModuleNotFoundError: No module named 'memory_service'
```

**解决**：
```bash
cd main_service
pip install -e ../memory_service
```

### 问题 2：Store 初始化失败

```
Error: Could not connect to PostgreSQL
```

**解决**：
1. 检查 `POSTGRES_URI_CUSTOM` 配置
2. 确认 PostgreSQL 服务运行中
3. 检查数据库权限

### 问题 3：记忆客户端未初始化

```
HTTPException: Memory service not initialized
```

**解决**：
1. 确认在 `main.py` 的 `lifespan` 中调用了 `memory.init_memory_client()`
2. 检查 Store 是否成功初始化

---

## 📈 性能监控

建议监控以下指标：

1. **API 响应时间**
   - 搜索：< 100ms
   - 统计：< 50ms
   - 清理：< 500ms

2. **并发请求**
   - 记忆搜索 QPS
   - 统计查询 QPS

3. **数据量**
   - 总记忆数
   - 按用户分布

---

## 🎯 下一步

1. ✅ 完成 `main_service` 集成
2. ⏭️ 前端集成记忆管理面板
3. ⏭️ 添加记忆导出功能
4. ⏭️ 添加记忆可视化图表
5. ⏭️ 性能优化和压测

---

**集成完成日期**：2025-01-XX  
**集成人员**：Claude Code  
**状态**：✅ main_service 集成完成

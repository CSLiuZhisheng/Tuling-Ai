# Memory Service 集成测试指南

## 🧪 测试准备

### 前置条件

1. **PostgreSQL 运行中**
   ```bash
   # 检查 PostgreSQL 状态
   psql -h 127.0.0.1 -U postgres -d langgraph_agents -c "SELECT 1"
   ```

2. **Python 环境**
   - Python 3.10+
   - 虚拟环境已激活

---

## 📋 测试步骤

### 步骤 1：安装依赖

```bash
# 1. 安装 memory_service
cd memory_service
pip install -e .

# 2. 安装 langgraph_service 依赖
cd ../langgraph_service
pip install -r requirements.txt

# 3. 安装 main_service 依赖
cd ../main_service
pip install -r requirements.txt
```

### 步骤 2：配置环境变量

创建或更新各服务的 `.env` 文件：

```bash
# langgraph_service/.env
POSTGRES_URI_CUSTOM=postgresql://postgres:123456@127.0.0.1:5432/langgraph_agents?sslmode=disable
LANGGRAPH_POSTGRES_DSN=postgresql://postgres:123456@127.0.0.1:5432/langgraph_agents?sslmode=disable
MEMORY_USE_LLM_SCORING=false
MEMORY_USE_VECTOR_SEARCH=true
DASHSCOPE_API_KEY=your_key  # 如果启用 LLM 评分
```

```bash
# main_service/.env
POSTGRES_URI_CUSTOM=postgresql://postgres:123456@127.0.0.1:5432/langgraph_agents?sslmode=disable
MEMORY_USE_LLM_SCORING=false
MEMORY_USE_VECTOR_SEARCH=true
```

### 步骤 3：运行集成测试

```bash
# 在项目根目录运行
cd E:\TuLinAI-Workspase\Tuling-Ai
python tests/test_memory_integration.py
```

---

## ✅ 快速验证（手动测试）

### 测试 1：Memory Service 基础功能

```python
# test_basic.py
import asyncio
from langgraph.store.postgres.aio import AsyncPostgresStore
from memory_service.client import MemoryClient

async def test_basic():
    conn_string = "postgresql://postgres:123456@127.0.0.1:5432/langgraph_agents?sslmode=disable"
    
    async with AsyncPostgresStore.from_conn_string(conn_string) as store:
        await store.setup()
        
        client = MemoryClient(store=store)
        
        # 保存记忆
        result = await client.save_memory(
            user_id="test_user",
            query="什么是 FastAPI？",
            answer="FastAPI 是一个现代的 Python Web 框架",
            use_llm_scoring=False
        )
        print(f"✅ 保存成功: importance={result.importance}, key={result.key[:8]}...")
        
        # 检索记忆
        memories = await client.search_memories(
            user_id="test_user",
            query="FastAPI",
            limit=5
        )
        print(f"✅ 检索成功: 找到 {len(memories)} 条记忆")
        
        # 获取统计
        stats = await client.get_stats("test_user")
        print(f"✅ 统计成功: 总数 {stats.total}, 平均重要性 {stats.avg_importance:.2f}")

if __name__ == "__main__":
    asyncio.run(test_basic())
```

运行：
```bash
cd langgraph_service
python test_basic.py
```

---

### 测试 2：LangGraph Service 集成

```bash
# 启动服务
cd langgraph_service
python app/main.py
```

发起对话测试：
```bash
# 使用 curl 或 Postman 测试
curl -X POST http://localhost:8000/api/custom-chat/chat/stream \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "query": "如何使用 FastAPI 创建接口？",
    "conversation_id": "test_conv_1"
  }'
```

**验证点**：
- ✅ 服务启动无报错
- ✅ 对话功能正常
- ✅ 日志显示记忆保存成功

---

### 测试 3：Main Service 集成

```bash
# 启动服务
cd main_service
python app/main.py
```

测试记忆 API：

#### 3.1 搜索记忆
```bash
curl -X POST http://localhost:8001/api/memories/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "user_id": "test_user",
    "query": "FastAPI",
    "limit": 10
  }'
```

#### 3.2 获取统计
```bash
curl http://localhost:8001/api/memories/test_user/stats \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### 3.3 清理记忆
```bash
curl -X POST http://localhost:8001/api/memories/test_user/cleanup \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**验证点**：
- ✅ API 返回正常
- ✅ 数据正确
- ✅ 鉴权工作正常

---

### 测试 4：Memory Service 独立服务（可选）

```bash
# 启动独立服务
cd memory_service
python main.py
```

访问 API 文档：
```
http://localhost:8020/docs
```

测试保存记忆：
```bash
curl -X POST http://localhost:8020/api/v1/memories \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
    "query": "测试问题",
    "answer": "测试答案",
    "use_llm_scoring": false
  }'
```

---

## 🔍 故障排查

### 问题 1：ModuleNotFoundError: No module named 'memory_service'

**原因**：未安装 memory_service 包

**解决**：
```bash
cd memory_service
pip install -e .
```

### 问题 2：ModuleNotFoundError: No module named 'langgraph'

**原因**：langgraph 依赖未安装

**解决**：
```bash
cd langgraph_service
pip install -r requirements.txt
```

### 问题 3：Could not connect to PostgreSQL

**原因**：数据库连接配置错误或服务未启动

**解决**：
1. 检查 PostgreSQL 是否运行
2. 验证连接字符串是否正确
3. 检查数据库权限

```bash
# 测试连接
psql -h 127.0.0.1 -U postgres -d langgraph_agents
```

### 问题 4：服务启动报错

**检查步骤**：
1. 查看详细错误日志
2. 确认所有依赖已安装
3. 检查端口是否被占用
4. 验证环境变量配置

---

## 📊 验收标准

### Memory Service
- [ ] `pip install -e .` 成功
- [ ] 导入 `MemoryClient` 无报错
- [ ] 保存记忆功能正常
- [ ] 检索记忆功能正常
- [ ] 统计功能正常

### LangGraph Service
- [ ] 依赖安装成功
- [ ] 服务启动无报错
- [ ] 对话功能正常
- [ ] 记忆自动保存
- [ ] 记忆自动加载

### Main Service
- [ ] 依赖安装成功
- [ ] 服务启动无报错
- [ ] 记忆搜索 API 可用
- [ ] 记忆统计 API 可用
- [ ] 记忆清理 API 可用

---

## 🎯 完整测试流程

### 方案 A：自动化测试（推荐）

```bash
# 1. 确保所有依赖已安装
cd langgraph_service && pip install -r requirements.txt
cd ../main_service && pip install -r requirements.txt
cd ../memory_service && pip install -e .

# 2. 配置环境变量
# 编辑各服务的 .env 文件

# 3. 运行集成测试
cd ..
python tests/test_memory_integration.py
```

### 方案 B：手动测试

```bash
# 终端 1：启动 LangGraph Service
cd langgraph_service
python app/main.py

# 终端 2：启动 Main Service
cd main_service
python app/main.py

# 终端 3：测试 API
# 使用 curl 或 Postman 测试各个接口
```

---

## 📝 测试报告模板

```markdown
# Memory Service 集成测试报告

**测试日期**：2025-01-XX
**测试人员**：[姓名]
**环境**：Windows/Linux/Mac

## 测试结果

### Memory Service
- [x] 基础功能 - 通过
- [x] 规则评分 - 通过
- [ ] LLM 评分 - 未测试（未配置 API Key）
- [x] 向量检索 - 通过
- [x] 去重功能 - 通过

### LangGraph Service
- [x] 服务启动 - 通过
- [x] 对话功能 - 通过
- [x] 记忆保存 - 通过
- [x] 记忆加载 - 通过

### Main Service
- [x] 服务启动 - 通过
- [x] 搜索 API - 通过
- [x] 统计 API - 通过
- [x] 清理 API - 通过

## 问题记录
- 无

## 总结
所有核心功能测试通过，集成成功！
```

---

## 🚀 下一步

测试通过后：

1. **生产部署准备**
   - 接入向量数据库
   - 配置生产环境变量
   - 设置定时清理任务

2. **性能优化**
   - 压力测试
   - 缓存优化
   - 数据库索引优化

3. **监控告警**
   - 添加日志监控
   - 性能指标采集
   - 异常告警配置

---

**文档版本**：1.0
**最后更新**：2025-01-XX

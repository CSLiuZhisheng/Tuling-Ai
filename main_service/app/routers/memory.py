# Main Service 集成 Memory Service 指南

## 📋 集成概述

`main_service` 作为前端接口服务，主要负责用户请求的接收和转发。虽然核心对话逻辑在 `langgraph_service` 中，但 `main_service` 也可以使用 `memory_service` 来：

1. 提供独立的记忆管理 API
2. 在特定场景下直接操作记忆
3. 实现记忆统计和展示功能

---

## ✅ 已完成的集成步骤

### 1. 添加依赖

已创建 `main_service/requirements.txt`，包含：
```txt
# 记忆服务（本地引用）
-e ../memory_service

# LangGraph Store（用于记忆管理）
langgraph-checkpoint-postgres==2.0.6

# LangChain（可选，用于 LLM 评分）
langchain-core==0.3.15
langchain-openai==0.2.9
```

---

## 🚀 集成方案

### 方案 1：仅暴露记忆管理 API（推荐）

`main_service` 只提供记忆管理的 HTTP 接口，实际记忆由 `langgraph_service` 管理。

**优势**：
- ✅ 职责清晰
- ✅ 避免重复逻辑
- ✅ 前端统一入口

**实现步骤**：

#### 步骤 1：创建记忆路由

```python
# main_service/app/routers/memory.py

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from langgraph.store.postgres.aio import AsyncPostgresStore
from memory_service.client import MemoryClient
from langchain_openai import ChatOpenAI
import os

router = APIRouter(prefix="/api/memories", tags=["memories"])

# 全局 store 和 client（在 main.py 中初始化）
_store: Optional[AsyncPostgresStore] = None
_memory_client: Optional[MemoryClient] = None


async def get_memory_client() -> MemoryClient:
    """获取记忆客户端依赖"""
    if _memory_client is None:
        raise HTTPException(status_code=503, detail="Memory service not initialized")
    return _memory_client


class SearchMemoryRequest(BaseModel):
    """搜索记忆请求"""
    user_id: str
    query: Optional[str] = None
    limit: int = 10
    min_importance: int = 3


class MemoryStatsResponse(BaseModel):
    """记忆统计响应"""
    total: int
    by_tier: dict
    by_importance: dict
    avg_importance: float


@router.post("/search")
async def search_memories(
    request: SearchMemoryRequest,
    client: MemoryClient = Depends(get_memory_client)
):
    """
    搜索用户记忆

    前端可以调用此接口展示用户的历史记忆
    """
    try:
        memories = await client.search_memories(
            user_id=request.user_id,
            query=request.query,
            limit=request.limit,
            min_importance=request.min_importance,
            use_vector_search=bool(request.query)
        )

        return {
            "memories": [
                {
                    "query": m.value.query,
                    "answer": m.value.answer[:200] + "..." if len(m.value.answer) > 200 else m.value.answer,
                    "importance": m.value.importance,
                    "created_at": m.value.created_at,
                    "score": m.score
                }
                for m in memories
            ],
            "total": len(memories)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search memories: {str(e)}")


@router.get("/{user_id}/stats")
async def get_memory_stats(
    user_id: str,
    client: MemoryClient = Depends(get_memory_client)
):
    """
    获取用户记忆统计

    前端可以用来展示用户的记忆概览
    """
    try:
        stats = await client.get_stats(user_id)
        return {
            "total": stats.total,
            "by_tier": stats.by_tier,
            "by_importance": stats.by_importance,
            "avg_importance": stats.avg_importance,
            "oldest_date": stats.oldest_date,
            "newest_date": stats.newest_date
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.post("/{user_id}/cleanup")
async def cleanup_memories(
    user_id: str,
    client: MemoryClient = Depends(get_memory_client)
):
    """
    清理用户的低价值记忆

    前端可以提供"清理记忆"按钮
    """
    try:
        result = await client.cleanup(user_id=user_id)
        return {
            "deleted": result.deleted,
            "kept": result.kept,
            "message": f"成功清理 {result.deleted} 条低价值记忆"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cleanup: {str(e)}")


def init_memory_client(store: AsyncPostgresStore, llm=None):
    """初始化记忆客户端（在 main.py 中调用）"""
    global _store, _memory_client
    _store = store
    _memory_client = MemoryClient(store=store, llm=llm)
```

#### 步骤 2：在 main.py 中注册路由

```python
# main_service/app/main.py

from contextlib import asynccontextmanager
from fastapi import FastAPI
from langgraph.store.postgres.aio import AsyncPostgresStore
from langchain_openai import ChatOpenAI
import os

from app.routers import chat, memory
from config.settings import Settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """服务生命周期管理"""

    # 初始化 PostgreSQL Store（用于记忆管理）
    conn_string = os.getenv(
        "POSTGRES_URI_CUSTOM",
        "postgresql://postgres:123456@127.0.0.1:5432/langgraph_agents?sslmode=disable"
    )

    store = AsyncPostgresStore.from_conn_string(conn_string)
    await store.__aenter__()
    await store.setup()

    # 初始化 LLM（可选）
    llm = None
    use_llm_scoring = os.getenv("MEMORY_USE_LLM_SCORING", "false").lower() == "true"
    if use_llm_scoring:
        llm = ChatOpenAI(
            model=os.getenv("DASHSCOPE_MODEL", "qwen-plus"),
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url=os.getenv("DASHSCOPE_BASE_URL"),
            temperature=0.1,
        )

    # 初始化记忆客户端
    memory.init_memory_client(store, llm)

    print("✅ Memory service initialized")

    yield

    # 清理资源
    await store.__aexit__(None, None, None)
    print("✅ Resources cleaned up")


app = FastAPI(
    title="Main Service",
    version="1.0.0",
    lifespan=lifespan
)

# 注册路由
app.include_router(chat.router)
app.include_router(memory.router)
```

---

### 方案 2：代理到 memory_service（独立部署时）

如果 `memory_service` 作为独立服务运行，`main_service` 可以代理请求：

```python
# main_service/app/routers/memory_proxy.py

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/memories", tags=["memories"])

MEMORY_SERVICE_URL = "http://localhost:8020"


@router.post("/search")
async def search_memories_proxy(request: dict):
    """代理到 memory_service"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{MEMORY_SERVICE_URL}/api/v1/memories/search",
            json=request,
            timeout=30.0
        )
        response.raise_for_status()
        return response.json()
```

---

## 📝 完整示例

### 创建记忆管理路由

<function_calls>
<invoke name="Write">
<parameter name="content">"""
Memory Service 路由 - Main Service 版本

为前端提供记忆管理 API
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from langgraph.store.postgres.aio import AsyncPostgresStore
from memory_service.client import MemoryClient

router = APIRouter(prefix="/api/memories", tags=["memories"])

# 全局客户端（在 main.py 中初始化）
_memory_client: Optional[MemoryClient] = None


async def get_memory_client() -> MemoryClient:
    """获取记忆客户端依赖"""
    if _memory_client is None:
        raise HTTPException(status_code=503, detail="Memory service not initialized")
    return _memory_client


class SearchMemoryRequest(BaseModel):
    """搜索记忆请求"""
    user_id: str = Field(..., description="用户ID")
    query: Optional[str] = Field(None, description="搜索关键词")
    limit: int = Field(10, ge=1, le=50, description="返回数量")
    min_importance: int = Field(3, ge=1, le=10, description="最低重要性")


class MemoryItem(BaseModel):
    """记忆项"""
    query: str
    answer: str
    importance: int
    created_at: str
    score: Optional[float] = None


class SearchMemoryResponse(BaseModel):
    """搜索记忆响应"""
    memories: List[MemoryItem]
    total: int


class MemoryStatsResponse(BaseModel):
    """记忆统计响应"""
    total: int
    by_tier: dict
    by_importance: dict
    avg_importance: float
    oldest_date: Optional[str]
    newest_date: Optional[str]


class CleanupResponse(BaseModel):
    """清理响应"""
    deleted: int
    kept: int
    message: str


@router.post("/search", response_model=SearchMemoryResponse)
async def search_memories(
    request: SearchMemoryRequest,
    client: MemoryClient = Depends(get_memory_client)
):
    """
    搜索用户记忆

    **使用场景**：
    - 前端展示用户历史对话记忆
    - 支持关键词搜索
    - 按重要性过滤

    **示例**：
    ```json
    {
      "user_id": "user_123",
      "query": "FastAPI",
      "limit": 10,
      "min_importance": 5
    }
    ```
    """
    try:
        memories = await client.search_memories(
            user_id=request.user_id,
            query=request.query,
            limit=request.limit,
            min_importance=request.min_importance,
            use_vector_search=bool(request.query)
        )

        memory_items = []
        for m in memories:
            # 截断过长的回答
            answer = m.value.answer
            if len(answer) > 200:
                answer = answer[:200] + "..."

            memory_items.append(MemoryItem(
                query=m.value.query,
                answer=answer,
                importance=m.value.importance,
                created_at=m.value.created_at,
                score=m.score
            ))

        return SearchMemoryResponse(
            memories=memory_items,
            total=len(memory_items)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search memories: {str(e)}")


@router.get("/{user_id}/stats", response_model=MemoryStatsResponse)
async def get_memory_stats(
    user_id: str,
    client: MemoryClient = Depends(get_memory_client)
):
    """
    获取用户记忆统计

    **使用场景**：
    - 前端展示用户记忆概览
    - 记忆管理面板

    **返回示例**：
    ```json
    {
      "total": 156,
      "by_tier": {"recent": 120, "archived": 36},
      "by_importance": {"1": 20, "3": 50, "5": 40, "7": 30, "9": 16},
      "avg_importance": 4.5
    }
    ```
    """
    try:
        stats = await client.get_stats(user_id)
        return MemoryStatsResponse(
            total=stats.total,
            by_tier=stats.by_tier,
            by_importance=stats.by_importance,
            avg_importance=stats.avg_importance,
            oldest_date=stats.oldest_date,
            newest_date=stats.newest_date
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.post("/{user_id}/cleanup", response_model=CleanupResponse)
async def cleanup_memories(
    user_id: str,
    importance_threshold: int = 3,
    days_threshold: int = 30,
    client: MemoryClient = Depends(get_memory_client)
):
    """
    清理用户的低价值记忆

    **使用场景**：
    - 前端提供"清理记忆"按钮
    - 定期维护任务

    **参数**：
    - `importance_threshold`: 重要性低于此值才清理（默认3）
    - `days_threshold`: 多少天未访问才清理（默认30天）

    **清理规则**：
    同时满足以下条件的记忆会被删除：
    - 重要性 < importance_threshold
    - 最后访问时间 > days_threshold 天前
    """
    try:
        result = await client.cleanup(
            user_id=user_id,
            importance_threshold=importance_threshold,
            days_threshold=days_threshold
        )

        message = f"成功清理 {result.deleted} 条低价值记忆，保留 {result.kept} 条"

        return CleanupResponse(
            deleted=result.deleted,
            kept=result.kept,
            message=message
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cleanup: {str(e)}")


def init_memory_client(store: AsyncPostgresStore, llm=None):
    """
    初始化记忆客户端

    在 main.py 的 lifespan 中调用

    Args:
        store: PostgreSQL Store 实例
        llm: LLM 实例（可选，用于评分）
    """
    global _memory_client
    _memory_client = MemoryClient(store=store, llm=llm)

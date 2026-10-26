"""
记忆管理 V2 API 端点

新增功能：
1. 向量检索记忆
2. LLM 评分
3. 记忆压缩
4. 分层归档
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.database import get_postgres_store
from app.services.memory_manager_v2 import MemoryManagerV2
from langgraph_service.my_agent.utils.nodes import get_llm

router = APIRouter(prefix="/api/memory/v2", tags=["memory-v2"])


class SaveMemoryRequest(BaseModel):
    """保存记忆请求"""
    user_id: str
    query: str
    answer: str
    use_llm_scoring: bool = False


class SearchMemoryRequest(BaseModel):
    """搜索记忆请求"""
    user_id: str
    query: Optional[str] = None
    limit: int = 10
    min_importance: int = 3
    use_vector_search: bool = True


class CleanupRequest(BaseModel):
    """清理请求"""
    user_id: str
    importance_threshold: int = 3
    days_threshold: int = 30


class CompressRequest(BaseModel):
    """压缩请求"""
    user_id: str
    similarity_threshold: float = 0.8
    min_cluster_size: int = 3


class ArchiveRequest(BaseModel):
    """归档请求"""
    user_id: str
    days_threshold: int = 30


@router.post("/save")
async def save_memory(request: SaveMemoryRequest):
    """
    保存记忆（支持 LLM 评分）

    Args:
        request: 保存请求参数

    Returns:
        保存结果
    """
    try:
        store = get_postgres_store()
        llm = get_llm() if request.use_llm_scoring else None
        memory_manager = MemoryManagerV2(store, llm=llm)

        result = await memory_manager.save_memory(
            user_id=request.user_id,
            query=request.query,
            answer=request.answer,
            use_llm_scoring=request.use_llm_scoring
        )

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save memory: {str(e)}")


@router.post("/search")
async def search_memories(request: SearchMemoryRequest):
    """
    搜索记忆（支持向量检索）

    Args:
        request: 搜索请求参数

    Returns:
        记忆列表
    """
    try:
        store = get_postgres_store()
        memory_manager = MemoryManagerV2(store)

        memories = await memory_manager.search_memories(
            user_id=request.user_id,
            query=request.query,
            limit=request.limit,
            min_importance=request.min_importance,
            use_vector_search=request.use_vector_search
        )

        return {
            "memories": [
                {
                    "key": m["key"],
                    "query": m["value"].get("query"),
                    "answer": m["value"].get("answer"),
                    "importance": m["value"].get("importance"),
                    "tier": m["value"].get("tier"),
                    "created_at": m["value"].get("created_at"),
                    "score": m.get("score"),
                    "similarity": m.get("similarity"),
                    "days_old": m.get("days_old")
                }
                for m in memories
            ],
            "total": len(memories)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search memories: {str(e)}")


@router.get("/stats/{user_id}")
async def get_memory_stats(user_id: str):
    """
    获取用户记忆统计（包含分层统计）

    Args:
        user_id: 用户ID

    Returns:
        记忆统计信息
    """
    try:
        store = get_postgres_store()
        memory_manager = MemoryManagerV2(store)

        stats = await memory_manager.get_memory_stats(user_id)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.post("/cleanup")
async def cleanup_memories(request: CleanupRequest):
    """
    手动清理低价值记忆

    Args:
        request: 清理请求参数

    Returns:
        清理结果统计
    """
    try:
        store = get_postgres_store()
        memory_manager = MemoryManagerV2(store)

        result = await memory_manager.cleanup_low_value_memories(
            user_id=request.user_id,
            importance_threshold=request.importance_threshold,
            days_threshold=request.days_threshold
        )

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cleanup: {str(e)}")


@router.post("/compress")
async def compress_memories(request: CompressRequest):
    """
    压缩相似记忆为摘要

    Args:
        request: 压缩请求参数

    Returns:
        压缩结果统计
    """
    try:
        store = get_postgres_store()
        llm = get_llm()
        memory_manager = MemoryManagerV2(store, llm=llm)

        result = await memory_manager.compress_similar_memories(
            user_id=request.user_id,
            similarity_threshold=request.similarity_threshold,
            min_cluster_size=request.min_cluster_size
        )

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compress: {str(e)}")


@router.post("/archive")
async def archive_memories(request: ArchiveRequest):
    """
    归档旧记忆到长期存储

    Args:
        request: 归档请求参数

    Returns:
        归档结果统计
    """
    try:
        store = get_postgres_store()
        memory_manager = MemoryManagerV2(store)

        result = await memory_manager.archive_old_memories(
            user_id=request.user_id,
            days_threshold=request.days_threshold
        )

        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to archive: {str(e)}")

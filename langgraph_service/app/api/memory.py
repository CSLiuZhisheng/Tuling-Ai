"""
记忆管理 API 端点

提供记忆统计、手动清理等功能
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.database import get_postgres_store
from app.services.memory_manager import MemoryManager

router = APIRouter(prefix="/api/memory", tags=["memory"])


class CleanupRequest(BaseModel):
    """清理请求"""
    user_id: str
    importance_threshold: int = 3
    days_threshold: int = 30


class CleanupResponse(BaseModel):
    """清理响应"""
    deleted: int
    kept: int
    threshold_importance: int
    threshold_days: int


class MemoryStatsResponse(BaseModel):
    """记忆统计响应"""
    total: int
    by_importance: dict[int, int]
    oldest_date: Optional[str]
    newest_date: Optional[str]
    avg_importance: float


@router.get("/stats/{user_id}", response_model=MemoryStatsResponse)
async def get_memory_stats(user_id: str):
    """
    获取用户记忆统计信息

    Args:
        user_id: 用户ID

    Returns:
        记忆统计信息
    """
    try:
        store = get_postgres_store()
        memory_manager = MemoryManager(store)

        stats = await memory_manager.get_memory_stats(user_id)

        return MemoryStatsResponse(
            total=stats["total"],
            by_importance=stats["by_importance"],
            oldest_date=stats["oldest_date"],
            newest_date=stats["newest_date"],
            avg_importance=stats.get("avg_importance", 0.0)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.post("/cleanup", response_model=CleanupResponse)
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
        memory_manager = MemoryManager(store)

        result = await memory_manager.cleanup_low_value_memories(
            user_id=request.user_id,
            importance_threshold=request.importance_threshold,
            days_threshold=request.days_threshold
        )

        return CleanupResponse(
            deleted=result["deleted"],
            kept=result["kept"],
            threshold_importance=result["threshold_importance"],
            threshold_days=result["threshold_days"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cleanup: {str(e)}")


@router.get("/search/{user_id}")
async def search_memories(
    user_id: str,
    limit: int = 10,
    min_importance: int = 3
):
    """
    搜索用户记忆

    Args:
        user_id: 用户ID
        limit: 返回数量
        min_importance: 最低重要性

    Returns:
        记忆列表
    """
    try:
        store = get_postgres_store()
        memory_manager = MemoryManager(store)

        memories = await memory_manager.search_memories(
            user_id=user_id,
            limit=limit,
            min_importance=min_importance
        )

        return {
            "memories": [
                {
                    "key": m["key"],
                    "query": m["value"].get("query"),
                    "answer": m["value"].get("answer"),
                    "importance": m["value"].get("importance"),
                    "created_at": m["value"].get("created_at"),
                    "score": m["score"],
                    "days_old": m["days_old"]
                }
                for m in memories
            ],
            "total": len(memories)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search: {str(e)}")

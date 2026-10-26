"""
Memory Service - API Routes
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Optional

from memory_service.api.schemas import (
    SaveMemoryRequest,
    SearchMemoryRequest,
    CleanupRequest,
    ArchiveRequest,
    CompressRequest,
    SaveMemoryResponse,
    SearchMemoryResponse,
    StatsResponse,
    CleanupResponse,
    ArchiveResponse,
    CompressResponse,
    MemoryResponse,
)
from memory_service.core.manager import MemoryManager
from memory_service.config.settings import MemoryConfig

# 全局管理器（由 main.py 初始化）
_memory_manager: Optional[MemoryManager] = None


def set_memory_manager(manager: MemoryManager):
    """设置全局管理器"""
    global _memory_manager
    _memory_manager = manager


def get_memory_manager() -> MemoryManager:
    """获取管理器依赖"""
    if _memory_manager is None:
        raise HTTPException(status_code=503, detail="Memory manager not initialized")
    return _memory_manager


# 创建路由器
router = APIRouter(prefix="/api/v1", tags=["memory"])


@router.post("/memories", response_model=SaveMemoryResponse)
async def save_memory(
    request: SaveMemoryRequest,
    manager: MemoryManager = Depends(get_memory_manager)
):
    """
    保存记忆

    - 自动去重
    - 智能评分（规则或LLM）
    - 返回保存结果
    """
    try:
        result = await manager.save_memory(
            user_id=request.user_id,
            query=request.query,
            answer=request.answer,
            metadata=request.metadata,
            use_llm_scoring=request.use_llm_scoring
        )
        return SaveMemoryResponse(
            status=result.status,
            key=result.key,
            importance=result.importance,
            reason=result.reason
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save memory: {str(e)}")


@router.post("/memories/search", response_model=SearchMemoryResponse)
async def search_memories(
    request: SearchMemoryRequest,
    manager: MemoryManager = Depends(get_memory_manager)
):
    """
    检索记忆

    - 支持向量检索
    - 综合排序（相似度+重要性+时间）
    - 返回相关记忆列表
    """
    try:
        memories = await manager.search_memories(
            user_id=request.user_id,
            query=request.query,
            limit=request.limit,
            min_importance=request.min_importance,
            use_vector_search=request.use_vector_search
        )

        memory_list = [
            MemoryResponse(
                key=m.key,
                query=m.value.query,
                answer=m.value.answer,
                importance=m.value.importance,
                tier=m.value.tier,
                created_at=m.value.created_at,
                last_seen=m.value.last_seen,
                access_count=m.value.access_count,
                score=m.score,
                similarity=m.similarity,
                days_old=m.days_old
            )
            for m in memories
        ]

        return SearchMemoryResponse(
            memories=memory_list,
            total=len(memory_list)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to search memories: {str(e)}")


@router.get("/memories/{user_id}/stats", response_model=StatsResponse)
async def get_memory_stats(
    user_id: str,
    manager: MemoryManager = Depends(get_memory_manager)
):
    """
    获取记忆统计

    - 总数统计
    - 分层统计
    - 重要性分布
    """
    try:
        stats = await manager.get_memory_stats(user_id)
        return StatsResponse(
            total=stats.total,
            by_tier=stats.by_tier,
            by_importance=stats.by_importance,
            oldest_date=stats.oldest_date,
            newest_date=stats.newest_date,
            avg_importance=stats.avg_importance
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


@router.post("/memories/cleanup", response_model=CleanupResponse)
async def cleanup_memories(
    request: CleanupRequest,
    manager: MemoryManager = Depends(get_memory_manager)
):
    """
    清理低价值记忆

    - 删除条件：重要性 < threshold 且 days 天未访问
    - 返回清理统计
    """
    try:
        result = await manager.cleanup_low_value_memories(
            user_id=request.user_id,
            importance_threshold=request.importance_threshold,
            days_threshold=request.days_threshold
        )
        return CleanupResponse(
            deleted=result.deleted,
            kept=result.kept,
            threshold_importance=result.threshold_importance,
            threshold_days=result.threshold_days
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cleanup: {str(e)}")


@router.post("/memories/archive", response_model=ArchiveResponse)
async def archive_memories(
    request: ArchiveRequest,
    manager: MemoryManager = Depends(get_memory_manager)
):
    """
    归档旧记忆

    - 将超过阈值的记忆移到长期存储
    - 返回归档统计
    """
    try:
        result = await manager.archive_old_memories(
            user_id=request.user_id,
            days_threshold=request.days_threshold
        )
        return ArchiveResponse(
            archived=result.archived,
            threshold_days=result.threshold_days
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to archive: {str(e)}")


@router.post("/memories/compress", response_model=CompressResponse)
async def compress_memories(
    request: CompressRequest,
    manager: MemoryManager = Depends(get_memory_manager)
):
    """
    压缩相似记忆

    - 使用向量聚类识别相似记忆
    - 生成摘要替代原始记忆
    - 返回压缩统计
    """
    try:
        result = await manager.compress_similar_memories(
            user_id=request.user_id,
            similarity_threshold=request.similarity_threshold,
            min_cluster_size=request.min_cluster_size
        )
        return CompressResponse(
            status=result.status,
            compressed=result.compressed,
            reason=result.reason
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to compress: {str(e)}")

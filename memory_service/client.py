"""
Memory Service - Python 客户端

供其他服务直接引用使用，无需通过 HTTP API
"""

from typing import Optional, List
from langgraph.store.base import BaseStore
from langchain_core.language_models import BaseChatModel

from memory_service.core.manager import MemoryManager
from memory_service.core.models import (
    Memory,
    MemoryStats,
    SaveResult,
    CleanupResult,
    ArchiveResult,
    CompressResult,
)
from memory_service.config.settings import MemoryConfig


class MemoryClient:
    """
    记忆服务客户端

    供其他服务引用使用的统一接口

    用法：
        from memory_service.client import MemoryClient

        client = MemoryClient(store=postgres_store, llm=chat_model)
        await client.save_memory(user_id="user_123", query="...", answer="...")
    """

    def __init__(
        self,
        store: BaseStore,
        llm: Optional[BaseChatModel] = None,
        config: Optional[MemoryConfig] = None
    ):
        """
        初始化客户端

        Args:
            store: LangGraph Store 实例
            llm: 用于 LLM 评分的模型（可选）
            config: 配置对象（可选，使用默认配置）
        """
        self.config = config or MemoryConfig()
        self.manager = MemoryManager(store, llm, self.config)

    async def save_memory(
        self,
        user_id: str,
        query: str,
        answer: str,
        metadata: Optional[dict] = None,
        use_llm_scoring: Optional[bool] = None
    ) -> SaveResult:
        """
        保存记忆

        Args:
            user_id: 用户ID
            query: 用户问题
            answer: AI 回答
            metadata: 额外元数据
            use_llm_scoring: 是否使用 LLM 评分

        Returns:
            保存结果
        """
        return await self.manager.save_memory(
            user_id=user_id,
            query=query,
            answer=answer,
            metadata=metadata,
            use_llm_scoring=use_llm_scoring
        )

    async def search_memories(
        self,
        user_id: str,
        query: Optional[str] = None,
        limit: Optional[int] = None,
        min_importance: Optional[int] = None,
        use_vector_search: Optional[bool] = None
    ) -> List[Memory]:
        """
        检索记忆

        Args:
            user_id: 用户ID
            query: 查询关键词（用于向量检索）
            limit: 返回数量
            min_importance: 最低重要性阈值
            use_vector_search: 是否使用向量检索

        Returns:
            记忆列表
        """
        return await self.manager.search_memories(
            user_id=user_id,
            query=query,
            limit=limit,
            min_importance=min_importance,
            use_vector_search=use_vector_search
        )

    async def get_stats(self, user_id: str) -> MemoryStats:
        """
        获取记忆统计

        Args:
            user_id: 用户ID

        Returns:
            统计信息
        """
        return await self.manager.get_memory_stats(user_id)

    async def cleanup(
        self,
        user_id: str,
        importance_threshold: Optional[int] = None,
        days_threshold: Optional[int] = None
    ) -> CleanupResult:
        """
        清理低价值记忆

        Args:
            user_id: 用户ID
            importance_threshold: 重要性阈值
            days_threshold: 天数阈值

        Returns:
            清理结果
        """
        return await self.manager.cleanup_low_value_memories(
            user_id=user_id,
            importance_threshold=importance_threshold,
            days_threshold=days_threshold
        )

    async def archive(
        self,
        user_id: str,
        days_threshold: Optional[int] = None
    ) -> ArchiveResult:
        """
        归档旧记忆

        Args:
            user_id: 用户ID
            days_threshold: 天数阈值

        Returns:
            归档结果
        """
        return await self.manager.archive_old_memories(
            user_id=user_id,
            days_threshold=days_threshold
        )

    async def compress(
        self,
        user_id: str,
        similarity_threshold: float = 0.8,
        min_cluster_size: int = 3
    ) -> CompressResult:
        """
        压缩相似记忆

        Args:
            user_id: 用户ID
            similarity_threshold: 相似度阈值
            min_cluster_size: 最小聚类大小

        Returns:
            压缩结果
        """
        return await self.manager.compress_similar_memories(
            user_id=user_id,
            similarity_threshold=similarity_threshold,
            min_cluster_size=min_cluster_size
        )


# 便捷导出
__all__ = ["MemoryClient", "MemoryConfig"]

"""
Memory Service - 核心记忆管理器

整合了所有记忆管理功能：
1. 保存记忆（LLM评分 + 去重）
2. 检索记忆（向量检索 + 综合排序）
3. 分层管理（中期/长期）
4. 自动清理和归档
5. 记忆压缩
"""

import hashlib
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from uuid import uuid4

from langgraph.store.base import BaseStore
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from memory_service.core.models import (
    Memory,
    MemoryValue,
    MemoryStats,
    SaveResult,
    CleanupResult,
    ArchiveResult,
    CompressResult,
    MemoryTier,
    MemoryImportance,
)
from memory_service.config.settings import MemoryConfig


class MemoryManager:
    """统一记忆管理器"""

    # 无意义对话模式
    TRIVIAL_PATTERNS = [
        "你好", "您好", "hi", "hello",
        "谢谢", "感谢", "thanks", "thank you",
        "好的", "ok", "okay", "嗯", "哦", "啊",
        "再见", "拜拜", "bye", "goodbye"
    ]

    # 重要内容标志
    IMPORTANT_MARKERS = [
        "项目", "project", "代码", "code",
        "bug", "问题", "issue", "error",
        "方案", "设计", "架构", "design",
        "决策", "decision"
    ]

    def __init__(
        self,
        store: BaseStore,
        llm: Optional[BaseChatModel] = None,
        config: Optional[MemoryConfig] = None
    ):
        """
        初始化记忆管理器

        Args:
            store: LangGraph Store 实例
            llm: 用于 LLM 评分的模型（可选）
            config: 配置对象（可选）
        """
        self.store = store
        self.llm = llm
        self.config = config or MemoryConfig()

    def _compute_content_hash(self, query: str, answer: str) -> str:
        """计算内容哈希（用于去重）"""
        normalized_query = re.sub(r'\s+', '', query.lower())
        normalized_answer = re.sub(r'\s+', '', answer.lower())
        content = f"{normalized_query}:{normalized_answer}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _evaluate_importance_rule_based(self, query: str, answer: str) -> int:
        """基于规则评估重要性"""
        query_lower = query.lower()
        answer_lower = answer.lower()

        # 1. 无意义对话
        if any(pattern in query_lower for pattern in self.TRIVIAL_PATTERNS):
            if len(answer) < 50:
                return MemoryImportance.TRIVIAL

        # 2. 包含代码块
        if "```" in answer:
            return MemoryImportance.CRITICAL

        # 3. 包含重要标志
        if any(marker in query_lower or marker in answer_lower
               for marker in self.IMPORTANT_MARKERS):
            return MemoryImportance.IMPORTANT

        # 4. 按回答长度判断
        if len(answer) > 500:
            return MemoryImportance.IMPORTANT
        elif len(answer) > 200:
            return MemoryImportance.USEFUL
        elif len(answer) > 50:
            return MemoryImportance.ROUTINE
        else:
            return MemoryImportance.TRIVIAL

    async def _evaluate_importance_with_llm(self, query: str, answer: str) -> int:
        """使用 LLM 评估重要性"""
        if not self.llm:
            return self._evaluate_importance_rule_based(query, answer)

        try:
            prompt = f"""评估以下对话的重要性，返回 1-10 的数字。

评分标准：
1-2: 无意义寒暄（"你好"、"谢谢"）
3-4: 普通对话
5-6: 有用信息
7-8: 重要讨论（包含技术细节、业务逻辑）
9-10: 关键信息（代码实现、架构决策、项目规划）

对话内容：
用户问：{query[:200]}
AI答：{answer[:500]}

只返回一个 1-10 之间的数字，不要有其他内容。"""

            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content.strip()

            # 提取数字
            match = re.search(r'\b([1-9]|10)\b', content)
            if match:
                return int(match.group(1))

            return self._evaluate_importance_rule_based(query, answer)

        except Exception:
            return self._evaluate_importance_rule_based(query, answer)

    async def save_memory(
        self,
        user_id: str,
        query: str,
        answer: str,
        metadata: Optional[Dict[str, Any]] = None,
        use_llm_scoring: Optional[bool] = None
    ) -> SaveResult:
        """
        保存记忆（带去重和重要性评分）

        Args:
            user_id: 用户ID
            query: 用户问题
            answer: AI 回答
            metadata: 额外的元数据
            use_llm_scoring: 是否使用 LLM 评分（None 则使用配置）

        Returns:
            保存结果
        """
        # 计算内容哈希
        content_hash = self._compute_content_hash(query, answer)

        # 检查是否已存在相同内容
        namespace = ("memories", user_id, MemoryTier.MID_TERM)
        existing_memories = await self.store.asearch(namespace)

        # 查找相同哈希的记忆
        existing_memory = None
        for memory in existing_memories:
            if memory.value.get("content_hash") == content_hash:
                existing_memory = memory
                break

        # 评估重要性
        if use_llm_scoring is None:
            use_llm_scoring = self.config.USE_LLM_SCORING

        if use_llm_scoring and self.llm:
            importance = await self._evaluate_importance_with_llm(query, answer)
        else:
            importance = self._evaluate_importance_rule_based(query, answer)

        now = datetime.now()

        if existing_memory:
            # 已存在，更新最后访问时间和访问次数
            key = existing_memory.key
            value = existing_memory.value
            value["last_seen"] = now.isoformat()
            value["access_count"] = value.get("access_count", 1) + 1

            await self.store.aput(namespace, key, value)

            return SaveResult(
                status="updated",
                key=key,
                importance=value.get("importance", importance),
                reason="duplicate_content"
            )
        else:
            # 新记忆，保存到中期记忆
            key = str(uuid4())
            value = {
                "query": query,
                "answer": answer,
                "content_hash": content_hash,
                "importance": importance,
                "tier": MemoryTier.MID_TERM,
                "created_at": now.isoformat(),
                "last_seen": now.isoformat(),
                "access_count": 1,
                **(metadata or {})
            }

            await self.store.aput(namespace, key, value)

            return SaveResult(
                status="created",
                key=key,
                importance=importance,
                reason="new_memory"
            )

    async def _vector_search_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """使用向量检索记忆（简化实现）"""
        try:
            namespace = ("memories", user_id, MemoryTier.MID_TERM)
            all_memories = await self.store.asearch(namespace)

            if not all_memories:
                return []

            # 简单的文本相似度
            memory_texts = {}
            for memory in all_memories:
                text = f"{memory.value.get('query', '')} {memory.value.get('answer', '')}"
                memory_texts[memory.key] = {
                    "text": text,
                    "memory": memory
                }

            scored_memories = []
            query_lower = query.lower()

            for key, data in memory_texts.items():
                text_lower = data["text"].lower()
                query_words = set(query_lower.split())
                text_words = set(text_lower.split())
                overlap = len(query_words & text_words)
                similarity = overlap / max(len(query_words), 1)

                scored_memories.append({
                    "key": key,
                    "memory": data["memory"],
                    "similarity": similarity
                })

            scored_memories.sort(key=lambda x: x["similarity"], reverse=True)

            return [
                {
                    "key": item["key"],
                    "value": item["memory"].value,
                    "similarity": item["similarity"]
                }
                for item in scored_memories[:limit]
            ]

        except Exception:
            return []

    async def search_memories(
        self,
        user_id: str,
        query: Optional[str] = None,
        limit: Optional[int] = None,
        min_importance: Optional[int] = None,
        use_vector_search: Optional[bool] = None
    ) -> List[Memory]:
        """
        智能检索记忆

        Args:
            user_id: 用户ID
            query: 查询关键词
            limit: 返回数量
            min_importance: 最低重要性阈值
            use_vector_search: 是否使用向量检索

        Returns:
            记忆列表
        """
        if limit is None:
            limit = self.config.DEFAULT_SEARCH_LIMIT
        if min_importance is None:
            min_importance = self.config.MIN_IMPORTANCE
        if use_vector_search is None:
            use_vector_search = self.config.USE_VECTOR_SEARCH

        namespace = ("memories", user_id, MemoryTier.MID_TERM)

        # 向量检索
        if query and use_vector_search:
            vector_results = await self._vector_search_memories(user_id, query, limit * 2)

            if vector_results:
                filtered = [
                    m for m in vector_results
                    if m["value"].get("importance", 0) >= min_importance
                ]

                now = datetime.now()
                scored_memories = []

                for memory in filtered:
                    created_at = datetime.fromisoformat(memory["value"].get("created_at", now.isoformat()))
                    importance = memory["value"].get("importance", 5)
                    similarity = memory.get("similarity", 0.5)

                    days_old = (now - created_at).days
                    time_decay = 1.0 / (1 + days_old / 30)

                    score = (
                        similarity * 0.5 +
                        importance / 10 * 0.3 +
                        time_decay * 0.2
                    )

                    scored_memories.append({
                        "key": memory["key"],
                        "value": memory["value"],
                        "score": score,
                        "similarity": similarity,
                        "days_old": days_old
                    })

                scored_memories.sort(key=lambda x: x["score"], reverse=True)
                return [Memory(**m) for m in scored_memories[:limit]]

        # 时间衰减排序
        memories = await self.store.asearch(namespace)
        filtered_memories = [
            m for m in memories
            if m.value.get("importance", 0) >= min_importance
        ]

        now = datetime.now()
        scored_memories = []

        for memory in filtered_memories:
            created_at = datetime.fromisoformat(memory.value.get("created_at", now.isoformat()))
            importance = memory.value.get("importance", 5)
            access_count = memory.value.get("access_count", 1)

            days_old = (now - created_at).days
            time_decay = 1.0 / (1 + days_old / 30)
            access_boost = min(1.0, access_count / 10)

            score = (
                importance / 10 * 0.5 +
                time_decay * 0.3 +
                access_boost * 0.2
            )

            scored_memories.append({
                "key": memory.key,
                "value": memory.value,
                "score": score,
                "days_old": days_old
            })

        scored_memories.sort(key=lambda x: x["score"], reverse=True)
        return [Memory(**m) for m in scored_memories[:limit]]

    async def cleanup_low_value_memories(
        self,
        user_id: str,
        importance_threshold: Optional[int] = None,
        days_threshold: Optional[int] = None
    ) -> CleanupResult:
        """清理低价值记忆"""
        if importance_threshold is None:
            importance_threshold = self.config.CLEANUP_IMPORTANCE_THRESHOLD
        if days_threshold is None:
            days_threshold = self.config.CLEANUP_DAYS_THRESHOLD

        namespace = ("memories", user_id, MemoryTier.MID_TERM)
        memories = await self.store.asearch(namespace)

        now = datetime.now()
        threshold_date = now - timedelta(days=days_threshold)

        deleted_count = 0
        kept_count = 0

        for memory in memories:
            importance = memory.value.get("importance", 5)
            last_seen = datetime.fromisoformat(
                memory.value.get("last_seen", memory.value.get("created_at", now.isoformat()))
            )

            if importance < importance_threshold and last_seen < threshold_date:
                await self.store.adelete(namespace, memory.key)
                deleted_count += 1
            else:
                kept_count += 1

        return CleanupResult(
            deleted=deleted_count,
            kept=kept_count,
            threshold_importance=importance_threshold,
            threshold_days=days_threshold
        )

    async def archive_old_memories(
        self,
        user_id: str,
        days_threshold: Optional[int] = None
    ) -> ArchiveResult:
        """归档旧记忆到长期存储"""
        if days_threshold is None:
            days_threshold = self.config.ARCHIVE_DAYS

        mid_term_ns = ("memories", user_id, MemoryTier.MID_TERM)
        long_term_ns = ("memories", user_id, MemoryTier.LONG_TERM)

        memories = await self.store.asearch(mid_term_ns)

        now = datetime.now()
        threshold_date = now - timedelta(days=days_threshold)

        archived_count = 0

        for memory in memories:
            created_at = datetime.fromisoformat(
                memory.value.get("created_at", now.isoformat())
            )

            if created_at < threshold_date:
                memory.value["tier"] = MemoryTier.LONG_TERM
                memory.value["archived_at"] = now.isoformat()

                await self.store.aput(long_term_ns, memory.key, memory.value)
                await self.store.adelete(mid_term_ns, memory.key)

                archived_count += 1

        return ArchiveResult(
            archived=archived_count,
            threshold_days=days_threshold
        )

    async def get_memory_stats(self, user_id: str) -> MemoryStats:
        """获取记忆统计信息"""
        stats = {
            "total": 0,
            "by_tier": {},
            "by_importance": {},
            "oldest_date": None,
            "newest_date": None,
            "avg_importance": 0.0
        }

        dates = []
        importance_sum = 0

        # 统计中期记忆
        mid_term_ns = ("memories", user_id, MemoryTier.MID_TERM)
        mid_memories = await self.store.asearch(mid_term_ns)
        stats["by_tier"][MemoryTier.MID_TERM] = len(mid_memories)

        # 统计长期记忆
        long_term_ns = ("memories", user_id, MemoryTier.LONG_TERM)
        long_memories = await self.store.asearch(long_term_ns)
        stats["by_tier"][MemoryTier.LONG_TERM] = len(long_memories)

        all_memories = list(mid_memories) + list(long_memories)
        stats["total"] = len(all_memories)

        if not all_memories:
            return MemoryStats(**stats)

        by_importance = {}
        for memory in all_memories:
            importance = memory.value.get("importance", 5)
            by_importance[importance] = by_importance.get(importance, 0) + 1
            importance_sum += importance

            created_at = memory.value.get("created_at")
            if created_at:
                dates.append(datetime.fromisoformat(created_at))

        stats["by_importance"] = by_importance
        stats["oldest_date"] = min(dates).isoformat() if dates else None
        stats["newest_date"] = max(dates).isoformat() if dates else None
        stats["avg_importance"] = importance_sum / len(all_memories) if all_memories else 0.0

        return MemoryStats(**stats)

    async def compress_similar_memories(
        self,
        user_id: str,
        similarity_threshold: float = 0.8,
        min_cluster_size: int = 3
    ) -> CompressResult:
        """压缩相似记忆（框架）"""
        if not self.llm:
            return CompressResult(
                status="skipped",
                compressed=0,
                reason="LLM not available"
            )

        # TODO: 实现向量聚类和压缩
        return CompressResult(
            status="success",
            compressed=0,
            reason="压缩功能待实现"
        )

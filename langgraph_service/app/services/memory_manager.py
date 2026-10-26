"""
智能记忆管理服务

功能：
1. 记忆去重 - 基于内容哈希避免重复存储
2. 重要性评分 - 区分有价值和无价值记忆
3. 智能检索 - 相似度 + 重要性 + 时间衰减
4. 自动清理 - 定期删除低价值旧记忆
"""

import hashlib
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from uuid import uuid4
import asyncio

from langgraph.store.base import BaseStore


class MemoryImportance:
    """记忆重要性等级"""
    TRIVIAL = 1      # 无意义对话（"你好"、"谢谢"）
    ROUTINE = 3      # 常规对话
    USEFUL = 5       # 有用信息
    IMPORTANT = 7    # 重要讨论
    CRITICAL = 9     # 关键信息（项目、代码、决策）


class MemoryManager:
    """记忆管理器"""

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

    def __init__(self, store: BaseStore):
        """
        初始化记忆管理器

        Args:
            store: LangGraph 的 BaseStore 实例
        """
        self.store = store

    def _compute_content_hash(self, query: str, answer: str) -> str:
        """
        计算内容哈希（用于去重）

        Args:
            query: 用户问题
            answer: AI 回答

        Returns:
            SHA-256 哈希值
        """
        # 规范化文本：去除空格、转小写
        normalized_query = re.sub(r'\s+', '', query.lower())
        normalized_answer = re.sub(r'\s+', '', answer.lower())

        content = f"{normalized_query}:{normalized_answer}"
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def _evaluate_importance(self, query: str, answer: str) -> int:
        """
        评估记忆重要性（1-10）

        规则：
        - 无意义对话（"你好"、"谢谢"）→ 1
        - 包含代码、长回答 → 7-9
        - 包含项目、决策关键词 → 9
        - 普通对话 → 3-5

        Args:
            query: 用户问题
            answer: AI 回答

        Returns:
            重要性分数 (1-10)
        """
        query_lower = query.lower()
        answer_lower = answer.lower()

        # 1. 检查是否是无意义对话
        if any(pattern in query_lower for pattern in self.TRIVIAL_PATTERNS):
            if len(answer) < 50:  # 短回答
                return MemoryImportance.TRIVIAL

        # 2. 检查是否包含代码块
        if "```" in answer:
            return MemoryImportance.CRITICAL

        # 3. 检查是否包含重要标志
        if any(marker in query_lower or marker in answer_lower
               for marker in self.IMPORTANT_MARKERS):
            return MemoryImportance.IMPORTANT

        # 4. 根据回答长度判断
        if len(answer) > 500:  # 长回答通常更有价值
            return MemoryImportance.IMPORTANT
        elif len(answer) > 200:
            return MemoryImportance.USEFUL
        elif len(answer) > 50:
            return MemoryImportance.ROUTINE
        else:
            return MemoryImportance.TRIVIAL

    async def save_memory(
        self,
        user_id: str,
        query: str,
        answer: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        保存记忆（带去重和重要性评分）

        Args:
            user_id: 用户ID
            query: 用户问题
            answer: AI 回答
            metadata: 额外的元数据

        Returns:
            保存结果：{"status": "created"|"updated"|"skipped", "key": str, "importance": int}
        """
        # 计算内容哈希
        content_hash = self._compute_content_hash(query, answer)

        # 检查是否已存在相同内容
        namespace = ("memories", user_id)
        existing_memories = await self.store.asearch(namespace)

        # 查找是否有相同哈希的记忆
        existing_memory = None
        for memory in existing_memories:
            if memory.value.get("content_hash") == content_hash:
                existing_memory = memory
                break

        # 评估重要性
        importance = self._evaluate_importance(query, answer)

        now = datetime.now()

        if existing_memory:
            # 已存在，更新最后访问时间和访问次数
            key = existing_memory.key
            value = existing_memory.value
            value["last_seen"] = now.isoformat()
            value["access_count"] = value.get("access_count", 1) + 1

            await self.store.aput(namespace, key, value)

            return {
                "status": "updated",
                "key": key,
                "importance": value.get("importance", importance),
                "reason": "duplicate_content"
            }
        else:
            # 新记忆，保存
            key = str(uuid4())
            value = {
                "query": query,
                "answer": answer,
                "content_hash": content_hash,
                "importance": importance,
                "created_at": now.isoformat(),
                "last_seen": now.isoformat(),
                "access_count": 1,
                **(metadata or {})
            }

            await self.store.aput(namespace, key, value)

            return {
                "status": "created",
                "key": key,
                "importance": importance,
                "reason": "new_memory"
            }

    async def search_memories(
        self,
        user_id: str,
        query: Optional[str] = None,
        limit: int = 10,
        min_importance: int = 3
    ) -> List[Dict[str, Any]]:
        """
        智能检索记忆

        检索策略：
        1. 过滤低重要性记忆（< min_importance）
        2. 按时间衰减排序
        3. 返回最相关的记忆

        Args:
            user_id: 用户ID
            query: 查询关键词（可选，暂未实现向量检索）
            limit: 返回数量
            min_importance: 最低重要性阈值

        Returns:
            记忆列表，按相关性排序
        """
        namespace = ("memories", user_id)
        memories = await self.store.asearch(namespace)

        # 过滤低重要性记忆
        filtered_memories = [
            m for m in memories
            if m.value.get("importance", 0) >= min_importance
        ]

        # 计算分数（时间衰减 + 重要性）
        now = datetime.now()
        scored_memories = []

        for memory in filtered_memories:
            created_at = datetime.fromisoformat(memory.value.get("created_at", now.isoformat()))
            importance = memory.value.get("importance", 5)
            access_count = memory.value.get("access_count", 1)

            # 时间衰减：30天衰减到0.5
            days_old = (now - created_at).days
            time_decay = 1.0 / (1 + days_old / 30)

            # 访问频率加成
            access_boost = min(1.0, access_count / 10)

            # 综合得分
            score = (
                importance / 10 * 0.5 +    # 重要性占50%
                time_decay * 0.3 +          # 时间新鲜度占30%
                access_boost * 0.2          # 访问频率占20%
            )

            scored_memories.append({
                "key": memory.key,
                "value": memory.value,
                "score": score,
                "days_old": days_old
            })

        # 按分数排序
        scored_memories.sort(key=lambda x: x["score"], reverse=True)

        # 返回前 N 条
        return scored_memories[:limit]

    async def cleanup_low_value_memories(
        self,
        user_id: str,
        importance_threshold: int = 3,
        days_threshold: int = 30
    ) -> Dict[str, int]:
        """
        清理低价值记忆

        删除条件：重要性 < threshold 且 days_threshold 天未访问

        Args:
            user_id: 用户ID
            importance_threshold: 重要性阈值（默认3）
            days_threshold: 天数阈值（默认30天）

        Returns:
            清理统计：{"deleted": 删除数量, "kept": 保留数量}
        """
        namespace = ("memories", user_id)
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

            # 判断是否需要删除
            if importance < importance_threshold and last_seen < threshold_date:
                await self.store.adelete(namespace, memory.key)
                deleted_count += 1
            else:
                kept_count += 1

        return {
            "deleted": deleted_count,
            "kept": kept_count,
            "threshold_importance": importance_threshold,
            "threshold_days": days_threshold
        }

    async def get_memory_stats(self, user_id: str) -> Dict[str, Any]:
        """
        获取记忆统计信息

        Args:
            user_id: 用户ID

        Returns:
            统计信息
        """
        namespace = ("memories", user_id)
        memories = await self.store.asearch(namespace)

        if not memories:
            return {
                "total": 0,
                "by_importance": {},
                "oldest_date": None,
                "newest_date": None
            }

        # 按重要性分组
        by_importance = {}
        dates = []

        for memory in memories:
            importance = memory.value.get("importance", 5)
            by_importance[importance] = by_importance.get(importance, 0) + 1

            created_at = memory.value.get("created_at")
            if created_at:
                dates.append(datetime.fromisoformat(created_at))

        return {
            "total": len(memories),
            "by_importance": by_importance,
            "oldest_date": min(dates).isoformat() if dates else None,
            "newest_date": max(dates).isoformat() if dates else None,
            "avg_importance": sum(
                m.value.get("importance", 5) for m in memories
            ) / len(memories)
        }


# 定期清理任务（可选）
async def scheduled_cleanup_task(memory_manager: MemoryManager, user_id: str):
    """
    定期清理任务（示例）

    Args:
        memory_manager: 记忆管理器实例
        user_id: 用户ID
    """
    while True:
        try:
            result = await memory_manager.cleanup_low_value_memories(user_id)
            print(f"[MemoryCleanup] User {user_id}: deleted={result['deleted']}, kept={result['kept']}")
        except Exception as e:
            print(f"[MemoryCleanup] Error: {e}")

        # 每24小时运行一次
        await asyncio.sleep(24 * 60 * 60)

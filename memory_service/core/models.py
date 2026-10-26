"""
Memory Service - 数据模型定义
"""

from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field


# ==============================
# 记忆分层枚举
# ==============================

class MemoryTier:
    """记忆分层"""
    SHORT_TERM = "checkpoint"  # 当前会话（不在此管理）
    MID_TERM = "recent"        # 30天内原始记忆
    LONG_TERM = "archived"     # 30天后压缩摘要


class MemoryImportance:
    """记忆重要性等级"""
    TRIVIAL = 1      # 无意义对话
    ROUTINE = 3      # 常规对话
    USEFUL = 5       # 有用信息
    IMPORTANT = 7    # 重要讨论
    CRITICAL = 9     # 关键信息


# ==============================
# 核心数据模型
# ==============================

class MemoryValue(BaseModel):
    """记忆值模型"""
    query: str
    answer: str
    content_hash: str
    importance: int = Field(ge=1, le=10)
    tier: str = MemoryTier.MID_TERM
    created_at: str
    last_seen: str
    access_count: int = 1
    metadata: Optional[dict] = None


class Memory(BaseModel):
    """完整记忆模型"""
    key: str
    value: MemoryValue
    namespace: tuple[str, ...]
    score: Optional[float] = None
    similarity: Optional[float] = None
    days_old: Optional[int] = None


# ==============================
# 统计模型
# ==============================

class MemoryStats(BaseModel):
    """记忆统计"""
    total: int
    by_tier: dict[str, int]
    by_importance: dict[int, int]
    oldest_date: Optional[str]
    newest_date: Optional[str]
    avg_importance: float


# ==============================
# 操作结果模型
# ==============================

class SaveResult(BaseModel):
    """保存结果"""
    status: Literal["created", "updated", "skipped"]
    key: str
    importance: int
    reason: str


class CleanupResult(BaseModel):
    """清理结果"""
    deleted: int
    kept: int
    threshold_importance: int
    threshold_days: int


class ArchiveResult(BaseModel):
    """归档结果"""
    archived: int
    threshold_days: int


class CompressResult(BaseModel):
    """压缩结果"""
    status: str
    compressed: int
    reason: Optional[str] = None

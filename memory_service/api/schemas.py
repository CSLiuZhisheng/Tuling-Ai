"""
Memory Service - API Schemas
"""

from typing import Optional, List
from pydantic import BaseModel, Field


# ==============================
# 请求模型
# ==============================

class SaveMemoryRequest(BaseModel):
    """保存记忆请求"""
    user_id: str = Field(..., description="用户ID")
    query: str = Field(..., description="用户问题")
    answer: str = Field(..., description="AI回答")
    metadata: Optional[dict] = Field(None, description="额外元数据")
    use_llm_scoring: Optional[bool] = Field(None, description="是否使用LLM评分")


class SearchMemoryRequest(BaseModel):
    """搜索记忆请求"""
    user_id: str = Field(..., description="用户ID")
    query: Optional[str] = Field(None, description="查询关键词")
    limit: Optional[int] = Field(10, ge=1, le=100, description="返回数量")
    min_importance: Optional[int] = Field(3, ge=1, le=10, description="最低重要性")
    use_vector_search: Optional[bool] = Field(True, description="是否使用向量检索")


class CleanupRequest(BaseModel):
    """清理请求"""
    user_id: str = Field(..., description="用户ID")
    importance_threshold: Optional[int] = Field(3, ge=1, le=10, description="重要性阈值")
    days_threshold: Optional[int] = Field(30, ge=0, description="天数阈值")


class ArchiveRequest(BaseModel):
    """归档请求"""
    user_id: str = Field(..., description="用户ID")
    days_threshold: Optional[int] = Field(30, ge=0, description="天数阈值")


class CompressRequest(BaseModel):
    """压缩请求"""
    user_id: str = Field(..., description="用户ID")
    similarity_threshold: Optional[float] = Field(0.8, ge=0.0, le=1.0, description="相似度阈值")
    min_cluster_size: Optional[int] = Field(3, ge=2, description="最小聚类大小")


# ==============================
# 响应模型
# ==============================

class MemoryResponse(BaseModel):
    """记忆响应"""
    key: str
    query: str
    answer: str
    importance: int
    tier: str
    created_at: str
    last_seen: str
    access_count: int
    score: Optional[float] = None
    similarity: Optional[float] = None
    days_old: Optional[int] = None


class SearchMemoryResponse(BaseModel):
    """搜索记忆响应"""
    memories: List[MemoryResponse]
    total: int


class StatsResponse(BaseModel):
    """统计响应"""
    total: int
    by_tier: dict
    by_importance: dict
    oldest_date: Optional[str]
    newest_date: Optional[str]
    avg_importance: float


class SaveMemoryResponse(BaseModel):
    """保存记忆响应"""
    status: str
    key: str
    importance: int
    reason: str


class CleanupResponse(BaseModel):
    """清理响应"""
    deleted: int
    kept: int
    threshold_importance: int
    threshold_days: int


class ArchiveResponse(BaseModel):
    """归档响应"""
    archived: int
    threshold_days: int


class CompressResponse(BaseModel):
    """压缩响应"""
    status: str
    compressed: int
    reason: Optional[str] = None


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    service: str
    version: str

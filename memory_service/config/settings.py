"""
Memory Service - 核心配置
"""

import os
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class MemoryConfig:
    """记忆服务配置"""

    # 服务基本信息
    SERVICE_NAME: str = "memory_service"
    VERSION: str = "2.0.0"
    HOST: str = os.getenv("MEMORY_SERVICE_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("MEMORY_SERVICE_PORT", "8020"))

    # 数据库配置
    POSTGRES_URI: str = os.getenv(
        "POSTGRES_URI_CUSTOM",
        "postgresql://postgres:123456@127.0.0.1:5432/langgraph_agents?sslmode=disable"
    )

    # LLM 配置（用于评分）
    API_KEY: Optional[str] = os.getenv("DASHSCOPE_API_KEY")
    API_BASE_URL: Optional[str] = os.getenv("DASHSCOPE_BASE_URL")
    MODEL: str = os.getenv("DASHSCOPE_MODEL", "qwen-plus")
    TEMPERATURE: float = float(os.getenv("MODEL_TEMPERATURE", "0.1"))

    # 记忆管理配置
    USE_LLM_SCORING: bool = os.getenv("MEMORY_USE_LLM_SCORING", "false").lower() == "true"
    USE_VECTOR_SEARCH: bool = os.getenv("MEMORY_USE_VECTOR_SEARCH", "true").lower() == "true"

    # 分层记忆阈值
    MID_TERM_DAYS: int = int(os.getenv("MEMORY_MID_TERM_DAYS", "30"))
    ARCHIVE_DAYS: int = int(os.getenv("MEMORY_ARCHIVE_DAYS", "30"))

    # 清理策略
    CLEANUP_IMPORTANCE_THRESHOLD: int = int(os.getenv("MEMORY_CLEANUP_IMPORTANCE", "3"))
    CLEANUP_DAYS_THRESHOLD: int = int(os.getenv("MEMORY_CLEANUP_DAYS", "30"))

    # 检索配置
    DEFAULT_SEARCH_LIMIT: int = int(os.getenv("MEMORY_SEARCH_LIMIT", "10"))
    MIN_IMPORTANCE: int = int(os.getenv("MEMORY_MIN_IMPORTANCE", "3"))

    # 向量检索配置
    RAG_API_URL: str = os.getenv("RAG_API_URL", "http://127.0.0.1:8000")

    # 日志配置
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

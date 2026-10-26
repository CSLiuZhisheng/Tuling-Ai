"""
数据库连接管理

提供 PostgreSQL Store 的单例访问
"""

from langgraph.store.postgres.aio import AsyncPostgresStore
from app.services.graph_runtime import runtime


def get_postgres_store() -> AsyncPostgresStore:
    """
    获取当前运行时的 PostgreSQL Store

    Returns:
        AsyncPostgresStore 实例

    Raises:
        RuntimeError: 如果服务尚未启动
    """
    if runtime.store is None:
        raise RuntimeError("PostgreSQL store has not been initialized. Service not started.")
    return runtime.store

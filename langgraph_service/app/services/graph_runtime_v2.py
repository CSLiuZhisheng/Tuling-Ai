"""FastAPI 部署专用的 PostgreSQL LangGraph 运行时 V2。

增强功能：
1. 支持向量检索的长期记忆加载
2. 支持 LLM 评分的记忆保存
3. 自动归档和清理机制
"""

from __future__ import annotations

from contextlib import AsyncExitStack
import os
from typing import Any

from langchain_core.messages import SystemMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.config import get_store
from langgraph.graph import END, START, StateGraph
from langgraph.store.postgres.aio import AsyncPostgresStore

from config.settings import Settings
from my_agent.utils.nodes import (
    call_writing_subgraph,
    chat_agent,
    fallback_search_agent,
    finalize,
    intent_router,
    knowledge_agent,
    knowledge_guard,
    summarization_node,
    get_llm,
)
from my_agent.utils.state import GraphState


async def load_long_term_memory_v2(state: GraphState) -> dict[str, Any]:
    """
    V2 版本：使用向量检索加载相关的长期记忆

    改进点：
    1. 基于当前问题进行语义相似度检索
    2. 只加载最相关的记忆，避免上下文污染
    3. 支持分层记忆（中期+长期）
    """
    from app.services.memory_manager_v2 import MemoryManagerV2

    user_id = str(state.get("user_id") or "default")

    # 提取当前用户问题
    current_query = ""
    messages = state.get("messages", [])
    if messages:
        last_message = messages[-1]
        message_type = getattr(last_message, "type", None)
        if message_type == "human":
            current_query = str(getattr(last_message, "content", ""))

    if not current_query:
        return {}

    store = get_store()
    memory_manager = MemoryManagerV2(store)

    # 使用向量检索找到最相关的记忆
    memories = await memory_manager.search_memories(
        user_id=user_id,
        query=current_query,
        limit=5,  # 只取最相关的5条
        min_importance=5,  # 只加载重要记忆
        use_vector_search=True
    )

    if not memories:
        return {}

    lines: list[str] = []
    for memory in memories:
        query = memory["value"].get("query", "").strip()
        answer = memory["value"].get("answer", "").strip()
        importance = memory["value"].get("importance", 5)
        similarity = memory.get("similarity", 0)

        if query or answer:
            # 标注记忆的重要性和相似度，帮助模型判断权重
            lines.append(
                f"[重要性: {importance}/10, 相似度: {similarity:.2f}]\n"
                f"用户曾问：{query}\n"
                f"助手曾答：{answer}"
            )

    if not lines:
        return {}

    return {
        "messages": [
            SystemMessage(
                content="以下是与当前问题最相关的历史记忆，按相关性排序：\n\n"
                + "\n\n---\n\n".join(lines)
            )
        ]
    }


async def save_long_term_memory_v2(state: GraphState) -> dict[str, Any]:
    """
    V2 版本：使用 LLM 评分保存记忆

    改进点：
    1. 使用 LLM 更准确地评估记忆重要性
    2. 自动去重
    3. 支持分层存储
    """
    from app.services.memory_manager_v2 import MemoryManagerV2

    user_id = str(state.get("user_id") or "default")
    query = ""

    # 从后往前寻找最近一条 HumanMessage
    for message in reversed(state.get("messages", [])):
        message_type = getattr(message, "type", None)
        if message_type == "human" or (
            isinstance(message, dict) and (message.get("type") or message.get("role")) in {"human", "user"}
        ):
            content = getattr(message, "content", None)
            if content is None and isinstance(message, dict):
                content = message.get("content", "")
            query = str(content or "")
            break

    answer = str(state.get("answer") or "").strip()
    if not query and not answer:
        return {}

    store = get_store()

    # 根据环境变量决定是否使用 LLM 评分
    use_llm_scoring = os.getenv("MEMORY_USE_LLM_SCORING", "false").lower() == "true"
    llm = get_llm() if use_llm_scoring else None

    memory_manager = MemoryManagerV2(store, llm=llm)

    # 智能保存：自动去重 + LLM 评分
    await memory_manager.save_memory(
        user_id=user_id,
        query=query,
        answer=answer,
        metadata={"type": "conversation"},
        use_llm_scoring=use_llm_scoring
    )
    return {}


def build_graph_builder_v2() -> StateGraph:
    """
    构建 V2 版本的 FastAPI 图

    使用增强版的记忆管理：
    - 向量检索
    - LLM 评分
    - 分层架构
    """
    builder = StateGraph(GraphState)
    builder.add_node("load_long_term_memory", load_long_term_memory_v2)
    builder.add_node("summarize", summarization_node)
    builder.add_node("intent_router", intent_router)
    builder.add_node("knowledge_agent", knowledge_agent)
    builder.add_node("fallback_search", fallback_search_agent)
    builder.add_node("writing_workflow", call_writing_subgraph)
    builder.add_node("chat_agent", chat_agent)
    builder.add_node("finalize", finalize)
    builder.add_node("save_long_term_memory", save_long_term_memory_v2)

    builder.add_edge(START, "load_long_term_memory")
    builder.add_edge("load_long_term_memory", "summarize")
    builder.add_edge("summarize", "intent_router")
    builder.add_conditional_edges(
        "intent_router",
        lambda state: state["intent"],
        {
            "knowledge": "knowledge_agent",
            "writing": "writing_workflow",
            "chat": "chat_agent",
        },
    )
    builder.add_conditional_edges(
        "knowledge_agent",
        knowledge_guard,
        {
            "fallback_search": "fallback_search",
            "finalize": "finalize",
        },
    )
    builder.add_edge("fallback_search", "finalize")
    builder.add_edge("writing_workflow", "finalize")
    builder.add_edge("chat_agent", "finalize")
    builder.add_edge("finalize", "save_long_term_memory")
    builder.add_edge("save_long_term_memory", END)
    return builder


class PostgresGraphRuntimeV2:
    """
    V2 版本的图运行时

    支持：
    1. 向量检索记忆加载
    2. LLM 评分记忆保存
    3. 后台自动归档和清理任务
    """

    def __init__(self, conn_string: str | None = None) -> None:
        self.conn_string = (
            conn_string
            or os.getenv("POSTGRES_URI_CUSTOM")
            or Settings.LANGGRAPH_POSTGRES_DSN
        )
        self._stack = AsyncExitStack()
        self.checkpointer: AsyncPostgresSaver | None = None
        self.store: AsyncPostgresStore | None = None
        self.graph: Any = None

    async def startup(self) -> None:
        """启动图运行时，初始化数据库连接和图编译"""
        self.checkpointer = await self._stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(self.conn_string)
        )
        self.store = await self._stack.enter_async_context(
            AsyncPostgresStore.from_conn_string(self.conn_string)
        )

        await self.checkpointer.setup()
        await self.store.setup()

        # 使用 V2 版本的图构建器
        self.graph = build_graph_builder_v2().compile(
            checkpointer=self.checkpointer,
            store=self.store,
        )

        # TODO: 启动后台定时任务
        # - 每天自动归档旧记忆
        # - 每周自动清理低价值记忆
        # - 每月压缩相似记忆

    async def shutdown(self) -> None:
        """关闭图运行时，释放资源"""
        await self._stack.aclose()
        self.checkpointer = None
        self.store = None
        self.graph = None

    def require_graph(self) -> Any:
        """返回已启动的图"""
        if self.graph is None:
            raise RuntimeError("PostgreSQL graph runtime has not started")
        return self.graph


# 导出 V2 运行时（可选择性启用）
runtime_v2 = PostgresGraphRuntimeV2()

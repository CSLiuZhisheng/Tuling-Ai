"""FastAPI 部署专用的 PostgreSQL LangGraph 运行时。

这个模块故意独立于 ``my_agent.agent``：原有 LangGraph CLI 入口继续使用原来的
图和启动方式，本 FastAPI 进程单独建立 PostgreSQL 连接，并重新构建一份图。

这里有两个不同职责的 PostgreSQL 组件：

1. ``AsyncPostgresSaver``：LangGraph checkpointer，保存 thread 级别的 checkpoint，
   也就是短期对话历史、当前图状态以及中断恢复所需的数据。
2. ``AsyncPostgresStore``：LangGraph store，保存跨 thread、按用户隔离的长期记忆。

只有把组件传给 ``builder.compile(checkpointer=..., store=...)``，图节点才能在
执行时使用它们；仅仅创建数据库连接并不会自动启用持久化。
"""

from __future__ import annotations

from contextlib import AsyncExitStack
import os
from typing import Any
from uuid import uuid4

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
)
from my_agent.utils.state import GraphState


async def load_long_term_memory(state: GraphState) -> dict[str, Any]:
    “””
    使用统一的 MemoryClient 加载长期记忆（V2 增强版）

    改进点：
    1. 使用独立的 memory_service 包
    2. 支持向量检索，只加载最相关的记忆
    3. 标注重要性和相似度，帮助模型判断权重
    “””
    from memory_service.client import MemoryClient

    user_id = str(state.get(“user_id”) or “default”)

    # 提取当前用户问题
    current_query = “”
    messages = state.get(“messages”, [])
    if messages:
        last_message = messages[-1]
        message_type = getattr(last_message, “type”, None)
        if message_type == “human”:
            current_query = str(getattr(last_message, “content”, “”))

    if not current_query:
        return {}

    # 使用统一的 MemoryClient
    store = get_store()
    memory_client = MemoryClient(store=store)

    # 使用向量检索找到最相关的记忆
    memories = await memory_client.search_memories(
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
        query = memory.value.query
        answer = memory.value.answer
        importance = memory.value.importance
        similarity = memory.similarity or 0

        # 标注记忆的重要性和相似度，帮助模型判断权重
        lines.append(
            f”[重要性: {importance}/10, 相似度: {similarity:.2f}]\n”
            f”用户曾问：{query}\n”
            f”助手曾答：{answer}”
        )

    if not lines:
        return {}

    return {
        “messages”: [
            SystemMessage(
                content=”以下是与当前问题最相关的历史记忆，按相关性排序：\n\n”
                + “\n\n---\n\n”.join(lines)
            )
        ]
    }


async def save_long_term_memory(state: GraphState) -> dict[str, Any]:
    """
    使用统一的 MemoryClient 保存记忆（V2 增强版）

    改进点：
    1. 使用独立的 memory_service 包
    2. 支持 LLM 评分（可配置）
    3. 自动去重、分层存储
    """
    from memory_service.client import MemoryClient
    from my_agent.utils.nodes import get_llm

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

    # 使用统一的 MemoryClient
    store = get_store()

    # 根据环境变量决定是否使用 LLM 评分
    use_llm_scoring = os.getenv("MEMORY_USE_LLM_SCORING", "false").lower() == "true"
    llm = get_llm() if use_llm_scoring else None

    memory_client = MemoryClient(store=store, llm=llm)

    # 智能保存：自动去重 + LLM 评分
    await memory_client.save_memory(
        user_id=user_id,
        query=query,
        answer=answer,
        metadata={"type": "conversation"},
        use_llm_scoring=use_llm_scoring
    )
    return {}


def build_graph_builder() -> StateGraph:
    """构建 FastAPI 专用图，并保留原有多 Agent 拓扑。

    与原图相比，这份新增图只增加了两个边界节点：

    ``START -> load_long_term_memory``：加载跨 thread 的长期记忆；
    ``finalize -> save_long_term_memory -> END``：保存本轮问答。

    中间的 summarize、路由、知识库、写作、聊天和 finalize 节点保持原有实现，
    这样新增部署方式不会修改或影响原来的 CLI 图。
    """
    builder = StateGraph(GraphState)
    builder.add_node("load_long_term_memory", load_long_term_memory)
    builder.add_node("summarize", summarization_node)
    builder.add_node("intent_router", intent_router)
    builder.add_node("knowledge_agent", knowledge_agent)
    builder.add_node("fallback_search", fallback_search_agent)
    # 通过包装函数调用写作子图。父图只接收包装函数明确返回的
    # answer/sources/messages，不把子图的中间字段写入父图状态。
    builder.add_node("writing_workflow", call_writing_subgraph)
    builder.add_node("chat_agent", chat_agent)
    builder.add_node("finalize", finalize)
    builder.add_node("save_long_term_memory", save_long_term_memory)

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


class PostgresGraphRuntime:
    """管理 FastAPI 进程生命周期内的异步 PostgreSQL 资源。

    一个运行时对象对应一个 FastAPI 进程。启动时创建并初始化 checkpointer/store，
    然后编译图；关闭时通过 ``AsyncExitStack`` 统一释放连接。路由处理函数只通过
    ``require_graph()`` 获取已经准备好的图，不直接管理数据库连接。
    """

    def __init__(self, conn_string: str | None = None) -> None:
        # 优先使用用户在根目录 .env 中配置的 POSTGRES_URI_CUSTOM。
        # 该连接串是 psycopg/LangGraph 使用的 URI 格式，而不是 SQLAlchemy URL。
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
        """打开连接、初始化 PostgreSQL 表结构，并编译持久化图。

        该方法由 FastAPI lifespan 在服务启动阶段调用。``from_conn_string`` 返回
        异步上下文管理器，交给 ``AsyncExitStack`` 后，服务关闭时会自动释放连接。
        ``setup`` 负责创建 LangGraph 所需表结构；最后 compile 得到的 graph 才是
        路由真正执行的对象。
        """
        # 两个对象共享同一 PostgreSQL URI，但用途不同：一个负责可恢复执行
        # 的 checkpoint，一个负责跨会话长期记忆。分别进入 AsyncExitStack，
        # shutdown 时就能成对释放资源。
        self.checkpointer = await self._stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(self.conn_string)
        )
        self.store = await self._stack.enter_async_context(
            AsyncPostgresStore.from_conn_string(self.conn_string)
        )
        # setup() 会创建 LangGraph 所需的表。它是幂等初始化，可以在每次服务启动
        # 时执行，不需要手工先运行 SQL 脚本。
        await self.checkpointer.setup()
        await self.store.setup()

        # checkpointer 负责短期状态，store 负责长期记忆。两者必须在 compile 时
        # 注入，节点内部的 get_store() 才能取得当前执行所绑定的 store。
        # compile 是持久化真正生效的边界。若只建立连接而不传入这两个参数，
        # 图节点中的 get_store() 和 thread checkpoint 都不会连接到 PostgreSQL。
        self.graph = build_graph_builder().compile(
            checkpointer=self.checkpointer,
            store=self.store,
        )

    async def shutdown(self) -> None:
        """关闭所有 PostgreSQL 连接，并清空运行时引用。"""
        await self._stack.aclose()
        self.checkpointer = None
        self.store = None
        self.graph = None

    def require_graph(self) -> Any:
        """返回已启动的图；服务尚未启动时立即抛出明确错误。"""
        if self.graph is None:
            raise RuntimeError("PostgreSQL graph runtime has not started")
        return self.graph


runtime = PostgresGraphRuntime()

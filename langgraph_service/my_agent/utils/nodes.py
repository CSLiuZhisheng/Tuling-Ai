"""主图节点实现和主图与写作子图之间的适配逻辑。

可以把本模块看成一个“业务节点层”：

1. ``intent_router`` 根据显式开关或模型判断请求类型；
2. knowledge/chat/writing 节点分别处理三种业务；
3. ``knowledge_guard`` 在知识库结果不足时切换搜索兜底；
4. ``finalize`` 把内部状态整理成稳定的 answer/sources/intent。

节点返回的是状态增量，不是完整状态。消息历史由 ``add_messages`` 合并，
短期摘要由 ``SummarizationNode`` 维护，避免每个节点各自裁剪历史。
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal
from enum import Enum

from pydantic import BaseModel, Field
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_openai import ChatOpenAI
from langmem.short_term import SummarizationNode
import json
from config.settings import Settings
from my_agent.utils.state import GraphState
from my_agent.utils.tools import call_mcp_tool, web_search


# ==============================
# 意图识别相关模型定义
# ==============================

class IntentType(str, Enum):
    """意图类型枚举"""
    KNOWLEDGE = "knowledge"
    WRITING = "writing"
    CHAT = "chat"


class IntentClassification(BaseModel):
    """意图分类结果"""
    intent: IntentType = Field(description="用户问题的意图类别")
    confidence: float = Field(description="分类置信度 0-1", ge=0, le=1)
    reason: str = Field(description="分类理由，简短说明")


# 用于正常回答的大模型。
def get_llm() -> ChatOpenAI:
    """创建统一的 LLM 实例，供图中各节点复用。"""
    return ChatOpenAI(
        model=Settings.MODEL,
        api_key=Settings.API_KEY,
        base_url=Settings.API_BASE_URL,
        temperature=Settings.TEMPERATURE,
    )


# 用于短期记忆摘要的模型。
# 这里绑定更大的 max_tokens，让摘要更详细。
summarization_model = get_llm().bind(max_tokens=2048)

# 创建原始摘要节点
#
# 参数说明：
# - max_tokens: 摘要后消息总 token 数上限
# - max_tokens_before_summary: 触发摘要的阈值
# - max_summary_tokens: 单次摘要结果的 token 上限
#
# 🔥 紧急修复：针对超大消息历史的防护策略
#
# 问题：当消息历史达到 60万+ tokens 时，摘要节点会失败并返回空摘要
#
# 修复方案：
# 1. 降低触发阈值到 3072，更早触发摘要
# 2. 摘要后保留 2048 tokens，确保有足够的修剪空间
# 3. 单次摘要限制 1536 tokens
# 4. 保持 max_tokens < max_tokens_before_summary，确保有 ~30% 修剪空间
#
# 这样即使历史消息过大，也能强制修剪到可用范围
_original_summarization_node = SummarizationNode(
    token_counter=count_tokens_approximately,
    model=summarization_model,
    max_tokens=2048,                  # 摘要后保留 2048 tokens（降低以增强修剪能力）
    max_tokens_before_summary=3072,   # 3072 tokens 时触发摘要（更早触发）
    max_summary_tokens=1536,          # 单次摘要最多 1536 tokens
)



async def summarization_node_with_debug(state: dict) -> dict:
    """
    摘要节点包装函数：修复空摘要问题和超大消息历史问题。

    主要功能：
    1. 检测并修复空摘要问题（空摘要会导致后续节点失败）
    2. 检测超大消息历史（>100k tokens）并强制修剪
    3. 调用原始摘要节点执行实际逻辑

    紧急修剪策略：
    - 如果消息历史超过 100k tokens，只保留最近 10 条消息
    - 这样可以避免摘要节点因消息过大而失败
    """
    # 检查是否有空摘要问题（会导致后续节点失败）
    input_running_summary = state.get("context", {}).get("running_summary")
    if input_running_summary and hasattr(input_running_summary, 'summary') and input_running_summary.summary == '':
        # 清空 running_summary，让系统重新生成
        if "context" in state and "running_summary" in state["context"]:
            state = {**state, "context": {**state["context"], "running_summary": None}}

    # 🔥 新增：检测超大消息历史并强制修剪
    messages = state.get("messages", [])
    if messages:
        total_tokens = sum(count_tokens_approximately(
            str(getattr(msg, "content", "") if not isinstance(msg, dict) else msg.get("content", ""))
        ) for msg in messages)

        print(f"[summarization_node] 消息历史分析: 共 {len(messages)} 条消息, {total_tokens} tokens")

        # 如果超过 100k tokens，强制只保留最近的消息
        if total_tokens > 100000:
            print(f"⚠️  [summarization_node] 消息历史过大 ({total_tokens} tokens)，执行强制修剪")

            # 策略1: 只保留最近 10 条消息
            keep_count = 10
            trimmed_messages = messages[-keep_count:] if len(messages) > keep_count else messages

            # 计算修剪后的 tokens
            trimmed_tokens = sum(count_tokens_approximately(
                str(getattr(msg, "content", "") if not isinstance(msg, dict) else msg.get("content", ""))
            ) for msg in trimmed_messages)

            print(f"✂️  [summarization_node] 修剪完成: {len(messages)} -> {len(trimmed_messages)} 条消息")
            print(f"✂️  [summarization_node] Token 压缩: {total_tokens} -> {trimmed_tokens} tokens ({trimmed_tokens/total_tokens*100:.1f}%)")

            # 更新 state
            state = {**state, "messages": trimmed_messages}

            # 清空上下文，让摘要重新开始
            if "context" in state:
                state = {**state, "context": {}}

    try:
        result = await _original_summarization_node.ainvoke(state)

        # 检查结果
        result_messages = result.get("summarized_messages", [])
        print(f"[summarization_node] 摘要完成: 输出 {len(result_messages)} 条消息")

        return result
    except Exception as e:
        print(f"❌ [summarization_node] 摘要失败: {e}")
        # 摘要失败时，返回修剪后的消息作为降级方案
        return {
            "summarized_messages": messages[-10:] if len(messages) > 10 else messages,
            "context": {}
        }


# 官方风格的短期记忆摘要节点（带调试）：
# - 当历史消息过长时，自动把旧消息压缩成 running summary
# - 生成 `summarized_messages` 给后续节点使用
summarization_node = summarization_node_with_debug


def get_latest_user_query(state: GraphState) -> str:
    """从 messages 中提取最近一条用户消息，作为当前轮的 query。

    不能直接取 messages 的最后一项，因为历史中可能刚追加了 AIMessage、
    SystemMessage 或写作子图的交互消息；倒序查找 human 消息才能稳定定位本轮
    用户输入。
    """
    messages = state.get("messages", [])
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "\n".join(str(item) for item in content)
            return str(content)
    return ""


def get_model_messages(state: GraphState) -> list:
    """
    获取供节点调用模型时使用的消息。

    优先使用 `summarized_messages`：
    - 这是一份"摘要后的短期记忆 + 最近原始消息"组合
    - 更适合多轮长对话

    如果摘要节点暂时没有提供输出，则退回原始 messages。
    """
    summarized_messages = state.get("summarized_messages")
    if summarized_messages:
        return list(summarized_messages)
    return list(state.get("messages", []))


def _analyze_messages(messages: list, label: str = "消息") -> dict[str, Any]:
    """分析消息列表的详细信息，用于调试和监控。

    返回：
    - total_count: 消息总数
    - by_type: 按类型统计的消息数量
    - total_tokens: 总 token 数（近似值）
    - details: 每条消息的详细信息
    """
    if not messages:
        return {
            "total_count": 0,
            "by_type": {},
            "total_tokens": 0,
            "details": []
        }

    by_type: dict[str, int] = {}
    details = []
    total_tokens = 0

    for idx, msg in enumerate(messages):
        # 获取消息类型
        msg_type = "unknown"
        if isinstance(msg, dict):
            msg_type = msg.get("type", "unknown")
        else:
            msg_type = getattr(msg, "type", "unknown")

        # 获取消息内容
        content = ""
        if isinstance(msg, dict):
            content = msg.get("content", "")
        else:
            content = getattr(msg, "content", "")

        content_str = str(content) if content else ""
        content_length = len(content_str)
        msg_tokens = count_tokens_approximately(content_str)
        total_tokens += msg_tokens

        # 统计类型
        by_type[msg_type] = by_type.get(msg_type, 0) + 1

        # 记录详情（内容截断显示）
        content_preview = content_str[:100] + "..." if content_length > 100 else content_str
        details.append({
            "index": idx,
            "type": msg_type,
            "content_length": content_length,
            "tokens": msg_tokens,
            "preview": content_preview
        })

    return {
        "total_count": len(messages),
        "by_type": by_type,
        "total_tokens": total_tokens,
        "details": details
    }


def _log_messages_analysis(state: GraphState, node_name: str) -> None:
    """在关键节点记录消息分析日志。

    Args:
        state: 当前图状态
        node_name: 节点名称
    """
    print(f"\n{'='*80}")
    print(f"[{node_name}] 消息分析")
    print(f"{'='*80}")

    # 分析原始消息
    raw_messages = state.get("messages", [])
    raw_analysis = _analyze_messages(raw_messages, "原始消息")

    print(f"\n📊 原始消息 (messages):")
    print(f"  - 总数: {raw_analysis['total_count']}")
    print(f"  - 类型分布: {raw_analysis['by_type']}")
    print(f"  - 总 Token 数: {raw_analysis['total_tokens']}")

    # 🔥 新增：找出超大消息
    large_messages = [d for d in raw_analysis['details'] if d['tokens'] > 5000]
    if large_messages:
        print(f"\n⚠️  发现 {len(large_messages)} 条超大消息 (>5000 tokens):")
        for detail in large_messages:
            print(f"  [{detail['index']}] {detail['type']:15s} | {detail['tokens']:6d} tokens | {detail['content_length']:8d} chars")
            print(f"      预览: {detail['preview']}")

    # 分析摘要消息
    summarized_messages = state.get("summarized_messages")
    if summarized_messages:
        summarized_analysis = _analyze_messages(summarized_messages, "摘要消息")
        print(f"\n📊 摘要消息 (summarized_messages):")
        print(f"  - 总数: {summarized_analysis['total_count']}")
        print(f"  - 类型分布: {summarized_analysis['by_type']}")
        print(f"  - 总 Token 数: {summarized_analysis['total_tokens']}")
        print(f"  - Token 压缩率: {summarized_analysis['total_tokens'] / raw_analysis['total_tokens'] * 100:.1f}%" if raw_analysis['total_tokens'] > 0 else "N/A")
    else:
        print(f"\n⚠️  摘要消息不存在，将使用原始消息")

    # 分析实际发送给 LLM 的消息
    model_messages = get_model_messages(state)
    model_analysis = _analyze_messages(model_messages, "LLM输入")

    print(f"\n🤖 实际发送给 LLM 的消息:")
    print(f"  - 总数: {model_analysis['total_count']}")
    print(f"  - 类型分布: {model_analysis['by_type']}")
    print(f"  - 总 Token 数: {model_analysis['total_tokens']}")

    # 检查是否可能超出上下文窗口
    context_window = 128000  # 假设使用的模型上下文窗口
    if model_analysis['total_tokens'] > context_window * 0.8:
        print(f"\n⚠️  警告: Token 数接近上下文窗口上限 ({model_analysis['total_tokens']}/{context_window})")

    # 打印详细消息内容（只打印前5条和后5条，避免刷屏）
    print(f"\n📝 消息详情 (前5条和后5条):")
    for idx, detail in enumerate(model_analysis['details']):
        if idx < 5 or idx >= len(model_analysis['details']) - 5:
            print(f"  [{detail['index']}] {detail['type']:15s} | {detail['tokens']:6d} tokens | {detail['content_length']:8d} chars")
            print(f"      预览: {detail['preview']}")
        elif idx == 5:
            print(f"  ... (省略 {len(model_analysis['details']) - 10} 条消息)")

    # 检查上下文信息
    context = state.get("context", {})
    if context:
        running_summary = context.get("running_summary")
        if running_summary:
            summary_text = getattr(running_summary, "summary", "") if hasattr(running_summary, "summary") else str(running_summary)
            summary_tokens = count_tokens_approximately(summary_text)
            print(f"\n📋 上下文摘要 (running_summary):")
            print(f"  - Token 数: {summary_tokens}")
            if summary_text:
                print(f"  - 内容预览: {summary_text[:200]}..." if len(summary_text) > 200 else f"  - 内容: {summary_text}")
            else:
                print(f"  - ⚠️  摘要为空！")

    # 🔥 新增：检查是否有异常状态
    print(f"\n🔍 异常检测:")
    issues = []

    if raw_analysis['total_tokens'] > 100000:
        issues.append(f"原始消息过大 ({raw_analysis['total_tokens']} tokens)")

    if model_analysis['total_tokens'] < 100 and raw_analysis['total_tokens'] > 1000:
        issues.append(f"摘要压缩过度 (原始 {raw_analysis['total_tokens']} -> 摘要 {model_analysis['total_tokens']})")

    if model_analysis['by_type'].get('system', 0) > model_analysis['total_count'] - 2:
        issues.append(f"几乎全是 SystemMessage，缺少用户对话")

    if issues:
        print(f"  ⚠️  发现以下问题:")
        for issue in issues:
            print(f"     - {issue}")
    else:
        print(f"  ✅ 未发现明显异常")

    print(f"\n{'='*80}\n")


def is_writing_request(query: str) -> bool:
    """快速识别明确的写作请求，避免普通聊天额外调用分类模型。"""
    normalized_query = query.strip().lower()
    writing_markers = (
        "帮我写", "请写", "写一", "写个", "写篇", "写封", "写段",
        "生成", "创作", "撰写", "改写", "润色", "翻译", "编写",
        "写代码", "写个程序", "写一个程序", "write ", "translate ",
    )
    return any(marker in normalized_query for marker in writing_markers)


async def intent_router(state: GraphState) -> GraphState:
    """主智能体：识别当前请求应路由到知识库、写作还是闲聊。"""
    # 如果前端显式指定了 knowledge_bool，直接按用户意图路由。
    # 显式开关优先级高于 LLM 分类，保证用户关闭知识库时不会发生隐藏检索。
    knowledge_bool = state.get("knowledge_bool")
    if knowledge_bool is True:
        return {"intent": "knowledge"}
    if knowledge_bool is False:
        # 用户关闭知识库时，普通聊天不应先等待一次分类模型调用。
        # 明确的写作指令仍进入写作工作流，其余请求直接交给聊天节点。
        query = get_latest_user_query(state)
        return {"intent": "writing" if is_writing_request(query) else "chat"}

    # knowledge_bool 未设置，使用结构化输出进行意图识别
    query = get_latest_user_query(state)
    llm = get_llm()

    # 绑定结构化输出
    structured_llm = llm.with_structured_output(IntentClassification)

    prompt = f"""请将用户问题分类为以下三个类别之一：

分类规则：
- knowledge：知识查询、事实问题、需要外部资料、技术文档查询
- writing：写作、生成、改写、润色、翻译、代码编写、内容创作
- chat：闲聊、观点交流、简单建议、日常对话

用户问题：
{query}

请分析问题类型，给出分类结果、置信度和简短理由。"""

    try:
        # 添加超时保护（30 秒），避免 LLM 调用阻塞
        result: IntentClassification = await asyncio.wait_for(
            structured_llm.ainvoke(prompt),
            timeout=30.0
        )

        # 可选：添加置信度判断逻辑
        # if result.confidence < 0.6:
        #     # 置信度低时，默认使用 chat
        #     return {"intent": "chat", "intent_confidence": result.confidence}

        return {
            "intent": result.intent.value,
            "intent_confidence": result.confidence,
            "intent_reason": result.reason
        }
    except asyncio.TimeoutError:
        # 超时回退到 chat
        print(f"意图识别超时，回退到 chat 模式")
        return {"intent": "chat"}
    except Exception as e:
        # 容错：如果结构化输出失败，回退到 chat
        print(f"意图识别失败: {e}")
        return {"intent": "chat"}


def _extract_sources(raw_sources: Any) -> list[str]:
    """递归提取 sources 列表中的文本内容。"""
    if not raw_sources:
        return []
    if isinstance(raw_sources, str):
        try:
            parsed = json.loads(raw_sources)
            return _extract_sources(parsed)
        except (json.JSONDecodeError, TypeError):
            return [raw_sources]
    if isinstance(raw_sources, dict):
        text = raw_sources.get("text", "")
        if text:
            try:
                inner = json.loads(text)
                return _extract_sources(inner)
            except (json.JSONDecodeError, TypeError):
                return [text]
        return []
    if isinstance(raw_sources, list):
        result = []
        for item in raw_sources:
            result.extend(_extract_sources(item))
        return result
    return [str(raw_sources)]


def _parse_rag_response(response: dict) -> tuple[str, list[str]]:
    """解析 RAG 响应，提取 answer 和 sources。"""
    answer = str(response.get("answer", ""))
    raw_sources = response.get("sources", [])

    # 尝试从 sources 中提取嵌套的 answer
    if isinstance(raw_sources, list):
        for item in raw_sources:
            if isinstance(item, str) and (item.startswith("[") or item.startswith("{")):
                try:
                    parsed = json.loads(item)
                    if isinstance(parsed, dict) and parsed.get("answer"):
                        answer = parsed["answer"]
                except (json.JSONDecodeError, TypeError):
                    pass

    formatted_sources = _extract_sources(raw_sources)
    return answer, formatted_sources or (raw_sources if isinstance(raw_sources, list) else [])


async def knowledge_agent(state: GraphState) -> GraphState:
    """知识库子智能体：通过 MCP 调用现有 RAG。"""

    # 🔍 添加消息分析日志
    _log_messages_analysis(state, "knowledge_agent")

    query = get_latest_user_query(state)
    tool_args: dict = {
        "query": query,
    }

    # knowledge_agent 不直接访问 RAG HTTP；MCP 是 Agent 与检索系统之间的
    # 边界，返回结果在这里解析为统一的 answer/sources。
    try:
        # 添加超时保护（30 秒）
        response = await asyncio.wait_for(
            call_mcp_tool("query_rag", tool_args),
            timeout=30.0
        )
    except asyncio.TimeoutError:
        return {
            "answer": "知识库查询超时，请稍后重试。",
            "timeout": True,
            "messages": [AIMessage(content="知识库查询超时，请稍后重试。")]
        }

    if isinstance(response, dict):
        answer, sources = _parse_rag_response(response)
        # 将sources存储到AIMessage的元数据中，实现消息级别的sources关联
        ai_message = AIMessage(
            content=answer,
            additional_kwargs={"sources": sources}
        )
        return {
            "answer": answer,
            "messages": [ai_message],
        }

    answer = str(response)
    return {
        "answer": answer,
        "messages": [AIMessage(content=answer)],
    }


def knowledge_guard(state: GraphState) -> Literal["fallback_search", "finalize"]:
    """知识库结果守卫：知识库答不好时，切换到搜索兜底。"""
    answer = (state.get("answer") or "").strip()
    if (not answer) or ("查询失败" in answer) or ("不知道" in answer):
        return "fallback_search"
    return "finalize"


async def fallback_search_agent(state: GraphState) -> GraphState:
    """搜索兜底节点。"""
    query = get_latest_user_query(state)
    note = await web_search.ainvoke(query)
    return {
        "answer": note,
        "sources": [],
        "search_notes": [note],
        "messages": [AIMessage(content=note)],
    }


async def chat_agent(state: GraphState) -> GraphState:
    """普通聊天节点。

    现在不再手工 trim 历史消息，
    而是直接使用 `SummarizationNode` 产出的 `summarized_messages`。

    即：
    - 历史完整消息由 `messages + checkpointer` 自动维护
    - 长对话压缩由 `SummarizationNode` 自动维护
    - 当前节点只消费摘要结果并返回新的 AI 消息
    """

    # 🔍 添加消息分析日志
    _log_messages_analysis(state, "chat_agent")

    llm = get_llm()

    # 准备消息
    prompt_messages = [
        SystemMessage(content="你是普通对话子智能体，直接自然回答用户。"),
        *get_model_messages(state),
    ]

    # 流式生成
    answer_parts = []

    async for chunk in llm.astream(prompt_messages):
        if chunk.content:
            answer_parts.append(str(chunk.content))

    answer = "".join(answer_parts)

    return {
        "answer": answer,
        "sources": [],
        "messages": [AIMessage(content=answer)],
    }


def finalize(state: GraphState) -> GraphState:
    """收尾节点：返回业务字段。

    下游节点可能把 sources 放在状态字段，也可能放在 AIMessage 的
    ``additional_kwargs`` 中。这里统一从最终 AI 消息恢复来源，确保知识库
    引用不会因为经过 fallback 或子图包装而丢失。
    """
    # 从最后一条AI消息中提取sources（统一从AIMessage中获取）
    sources = []
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if hasattr(msg, "additional_kwargs") and isinstance(msg.additional_kwargs, dict):
            sources = msg.additional_kwargs.get("sources", []) or []
            break
        elif isinstance(msg, dict):
            additional_kwargs = msg.get("additional_kwargs", {})
            if isinstance(additional_kwargs, dict):
                sources = additional_kwargs.get("sources", []) or []
                break
    
    return {
        "answer": state.get("answer", ""),
        "sources": sources,
        "intent": state.get("intent", "chat"),
    }


# ==============================
# 写作子图包装函数
# ==============================
# 由于父图 (GraphState) 和子图 (WritingState) 的状态结构不同，
# 通过包装函数明确控制父图和子图之间的输入输出边界。


async def call_writing_subgraph(state: GraphState) -> dict:
    """
    写作子图包装函数：调用写作子工作流。

    状态转换说明：
    - 父图 → 子图：将 GraphState 中的字段映射为 WritingState 需要的字段
      - query (用户消息) → query

    - 子图 → 父图：将 WritingState 的输出映射回 GraphState
      - answer → answer
      - sources → sources
      - messages → messages

    Args:
        state: 父图状态 (GraphState)

    Returns:
        更新父图状态的字典
    """
    from my_agent.writing_subgraph import writing_subgraph

    # 父图只把当前用户 query 交给子图；子图内部的 requirements/outline/draft
    # 等中间字段不写入父图，防止两个状态模型互相污染。
    # 从父图状态中提取用户消息作为 query
    query = get_latest_user_query(state)
    print(f"[writing_workflow] 调用写作子图 | query={query[:50]}...")

    # 构造子图输入状态
    subgraph_input = {
        "query": query,
    }

    # 调用子图
    subgraph_output = await writing_subgraph.ainvoke(subgraph_input)

    # 将子图输出映射回父图状态
    print(f"[writing_workflow] 子图执行完成 | answer长度={len(subgraph_output.get('answer', ''))}")

    return {
        "answer": subgraph_output.get("answer", ""),
        "sources": subgraph_output.get("sources", []),
        "messages": subgraph_output.get("messages", []),
    }

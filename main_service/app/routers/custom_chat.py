"""使用自定义 FastAPI LangGraph 服务的独立聊天路由。

旧路由 ``app.routers.chat`` 保持原样；本路由使用 ``/api/custom-chat`` 前缀，
便于先灰度验证，再把前端或网关切到新入口。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.routers.users import get_current_active_user
from app.schemas import ChatMessage, ChatRequest, ChatResponse, ClearRequest, ResumeRequest, User
from app.services.conversation_repository import ConversationRepository
from app.services.custom_langgraph_service import CustomLangGraphService
from db import get_db

router = APIRouter()
_service = CustomLangGraphService()

_INTERNAL_MEMORY_PREFIX = "以下是该用户的长期记忆，仅在与当前问题相关时参考："


async def startup_custom_chat() -> None:
    """预热自定义 LangGraph HTTP 连接池。"""

    await _service.startup()


async def shutdown_custom_chat() -> None:
    """释放自定义 LangGraph HTTP 连接池。"""

    await _service.shutdown()


def _sse(event_type: str, **fields: Any) -> str:
    """将自定义服务事件转换为现有前端使用的精简 SSE。"""

    return f"data: {json.dumps({'type': event_type, **fields}, ensure_ascii=False)}\n\n"


def _conversation_id(req: ChatRequest, user: User, db: Session) -> str:
    """复用 main_service 会话表，确保新旧入口的会话列表可以共存。

    自定义入口不另建会话表；因此用户从旧入口切换到新入口时，仍可使用同一
    conversation_id，只有下游的协议适配方式发生变化。
    """

    if req.conversation_id:
        ConversationRepository(db).touch(req.conversation_id, user.username)
        return req.conversation_id
    title = req.query[:20] + "..." if len(req.query) > 20 else req.query
    return ConversationRepository(db).create(user_id=user.username, title=title).id


def _message_content(event: dict[str, Any]) -> str:
    """从自定义 LangGraph 服务的 ``messages`` 事件中提取文本。

    LangGraph 的 ``messages`` 流事件通常是 ``[message, metadata]``，
    也可能直接是一个消息对象。经过 ``CustomLangGraphService`` 的 JSON
    反序列化后，消息一般表现为字典，因此这里同时兼容字典、列表和普通
    字符串，避免恢复流程把生成内容误读为空字符串。
    """

    value = event.get("data", event.get("content", ""))
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    if isinstance(value, dict):
        value = value.get("content", "")
    return str(value) if value is not None else ""


def _is_internal_content(content: str) -> bool:
    """过滤不应展示给用户的长期记忆上下文。"""

    return content.startswith(_INTERNAL_MEMORY_PREFIX)


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)) -> ChatResponse:
    """非流式业务聊天。"""

    conversation_id = _conversation_id(req, current_user, db)
    try:
        result = await _service.chat(thread_id=current_user.id, conversation_id=conversation_id, query=req.query, knowledge_bool=req.knowledge_bool)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"自定义 LangGraph 服务调用失败: {exc}") from exc
    return ChatResponse(messages=ChatMessage(role="ai", content=str(result.get("answer", "")), sources=result.get("sources", []) or []), conversation_id=conversation_id, is_interrupt=bool(result.get("is_interrupt")))


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request, current_user: User = Depends(get_current_active_user), db: Session = Depends(get_db)) -> StreamingResponse:
    """流式业务聊天。"""

    conversation_id = _conversation_id(req, current_user, db)

    async def events():
        # 代理层把 langgraph_service 的稳定事件映射为旧前端能识别的事件名，
        # 同时在这里做第二层内部长期记忆过滤，避免系统上下文泄漏。
        # 会话 ID 由 main_service 的会话表创建或复用。先发给前端，前端才能在
        # 首次聊天时把后续历史消息、恢复中断和取消请求绑定到同一个会话。
        yield _sse("conversation_id", content=conversation_id)
        try:
            async for event in _service.chat_stream(thread_id=current_user.id, conversation_id=conversation_id, query=req.query, knowledge_bool=req.knowledge_bool):
                if await request.is_disconnected():
                    # 浏览器关闭页面或点击停止后，不能只断开代理连接；还要通知
                    # langgraph_service 取消其正在运行的 asyncio Task，否则图仍会
                    # 继续调用模型并写入 checkpoint。
                    await _service.cancel_runs(thread_id=current_user.id, conversation_id=conversation_id)
                    return
                event_type = event.get("type")
                if event_type == "token":
                    # token 已经在下游按节点做过增量/累计文本去重，这里只做协议
                    # 名称转换：自定义服务的 token -> 旧前端使用的 content。
                    content = str(event.get("content", ""))
                    if content and not _is_internal_content(content):
                        yield _sse("content", content=content, is_display=True)
                elif event_type in {"node_start", "article", "content"}:
                    # 写作节点事件沿用旧前端协议：node_start 更新步骤，
                    # article 更新草稿预览，content 更新最终回答。
                    content = event.get("content")
                    fields = {key: value for key, value in event.items() if key != "type"}
                    if content is None or not _is_internal_content(str(content)):
                        yield _sse(event_type, **fields)
                elif event_type == "update":
                    yield _sse("update", content=event)
                elif event_type == "interrupt":
                    # interrupt 的 content 已在 langgraph_service 规范化为
                    # [{"value": {...}}]，这里保持数组结构转发，前端据此区分
                    # clarification 和 human_review 两种暂停原因。
                    yield _sse("interrupt", content=event.get("content", event))
                elif event_type == "error":
                    yield _sse("error", content=event.get("message", ""), finished=True)
                elif event_type == "complete":
                    yield _sse("complete", finished=True)
        except Exception as exc:
            yield _sse("error", content=str(exc), finished=True)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.get("/history")
async def history(conversation_id: str, current_user: User = Depends(get_current_active_user)) -> list[ChatMessage]:
    """读取当前用户指定会话的短期历史。"""

    messages = await _service.get_history(thread_id=current_user.id, conversation_id=conversation_id)
    result: list[ChatMessage] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        # SystemMessage 可能包含长期记忆、摘要等仅供模型使用的上下文，
        # 不能作为用户可见聊天消息返回给前端。
        # 下游返回 LangChain 的 type，旧前端模型使用 role；这里保留现有
        # 字段值，因为 ChatMessage 已经能接受 human/user/ai/assistant。
        role = str(item.get("type") or item.get("role") or "ai")
        content = str(item.get("content", ""))
        if role == "system" or _is_internal_content(content):
            continue
        additional_kwargs = item.get("additional_kwargs", {})
        sources = item.get("sources", []) or []
        if isinstance(additional_kwargs, dict):
            sources = additional_kwargs.get("sources", sources) or []
        result.append(ChatMessage(role=role, content=content, sources=sources))
    return result


@router.post("/clear")
async def clear(req: ClearRequest, current_user: User = Depends(get_current_active_user)) -> dict[str, str]:
    """清理短期 checkpoint，长期记忆不受影响。"""

    await _service.clear_history(thread_id=current_user.id, conversation_id=req.conversation_id)
    return {"status": "success", "message": "会话已清空"}


@router.post("/chat/resume/stream")
async def resume(req: ResumeRequest, current_user: User = Depends(get_current_active_user)) -> StreamingResponse:
    """恢复 interrupt 流程。"""

    async def events():
        # resume 的事件格式与普通聊天基本相同，额外保留 updates/interrupt
        # 兼容分支，适配下游不同 LangGraph 版本的事件顺序。
        async for event in _service.resume_stream(thread_id=current_user.id, conversation_id=req.conversation_id, action=req.action, content=req.content, answer=req.answer):
            event_type = event.get("type", "update")
            if event_type == "token":
                # 自定义 LangGraph 服务已经把 messages 事件转换成去重后的
                # token；这里映射成现有前端一直使用的 content 事件。
                content = event.get("content", "")
                if content and not _is_internal_content(str(content)):
                    yield _sse("content", content=content, is_display=True)
            elif event_type in {"node_start", "article", "content"}:
                content = event.get("content")
                fields = {key: value for key, value in event.items() if key != "type"}
                if content is None or not _is_internal_content(str(content)):
                    yield _sse(event_type, **fields)
            elif event_type == "messages":
                # 恢复后的文本位于 event.data，而不是 event.content。
                content = _message_content(event)
                if content and not _is_internal_content(content):
                    yield _sse("content", content=content, is_display=True)
            elif event_type == "updates":
                # 节点更新可能携带 interrupt。必须单独转换，否则前端
                # 不会进入审阅或澄清状态，只会一直等待流结束。
                data = event.get("data")
                if isinstance(data, dict) and data.get("__interrupt__"):
                    # 兼容下游仍以原始 updates 形式返回 interrupt 的情况。
                    # 正常情况下它已经是独立 interrupt 事件，这个分支是
                    # 为不同版本/异常事件顺序保留的兜底路径。
                    yield _sse("interrupt", content=data["__interrupt__"])
                else:
                    yield _sse("update", content=data if data is not None else event)
            elif event_type == "interrupt":
                # 正常恢复流程会收到 langgraph_service 单独发出的 interrupt。
                # 这里必须显式转发 content，而不能走最后的通用兜底分支；
                # 兜底分支会把整个 event 再包进 content，前端就无法按
                # content[0].value 读取暂停原因。
                yield _sse("interrupt", content=event.get("content", event))
            elif event_type == "complete":
                yield _sse("complete", finished=True)
            elif event_type == "error":
                yield _sse("error", content=event.get("message", ""), finished=True)
            else:
                yield _sse(event_type, content=event.get("data", event))

    return StreamingResponse(events(), media_type="text/event-stream")

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from app.config import settings

from app.deps import get_rag_service, require_api_key
from app.schemas import ChatRequest, ChatResponse, ChatSessionResponse, ChatTurn
from app.services.llm import LocalLLMError
from app.services.rag import RAGService
from app.services.state_store import StateStore

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(require_api_key)])

CHAT_SESSIONS_LOCK = asyncio.Lock()
STATE_STORE = StateStore(settings.state_db_path)


@router.get("/session/{session_id}", response_model=ChatSessionResponse)
async def get_chat_session(session_id: str, workspace_id: str | None = Query(default=None)) -> ChatSessionResponse:
    resolved_workspace = RAGService.normalize_workspace_id(workspace_id)
    async with CHAT_SESSIONS_LOCK:
        history = await asyncio.to_thread(STATE_STORE.get_chat_history, session_id, resolved_workspace)

    return ChatSessionResponse(session_id=session_id, history=history)


@router.delete("/session/{session_id}", status_code=204)
async def clear_chat_session(session_id: str, workspace_id: str | None = Query(default=None)) -> None:
    resolved_workspace = RAGService.normalize_workspace_id(workspace_id)
    async with CHAT_SESSIONS_LOCK:
        await asyncio.to_thread(STATE_STORE.clear_chat_session, session_id, resolved_workspace)


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, rag_service: RAGService = Depends(get_rag_service)) -> ChatResponse:
    resolved_workspace = rag_service.normalize_workspace_id(payload.workspace_id)
    active_history = payload.history
    if payload.session_id:
        async with CHAT_SESSIONS_LOCK:
            stored_history = await asyncio.to_thread(
                STATE_STORE.get_chat_history,
                payload.session_id,
                resolved_workspace,
            )
            active_history = list(stored_history or payload.history)

    try:
        answer, citations, context_chunks = await rag_service.answer(
            payload.question,
            active_history,
            payload.system_prompt,
            resolved_workspace,
        )
    except LocalLLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if payload.session_id:
        updated_history = [
            *active_history,
            ChatTurn(role="user", content=payload.question),
            ChatTurn(role="assistant", content=answer),
        ]
        updated_history = updated_history[-40:]
        async with CHAT_SESSIONS_LOCK:
            await asyncio.to_thread(
                STATE_STORE.set_chat_history,
                payload.session_id,
                updated_history,
                resolved_workspace,
            )

    return ChatResponse(answer=answer, citations=citations, context_chunks=context_chunks)


@router.post("/stream")
async def chat_stream(payload: ChatRequest, rag_service: RAGService = Depends(get_rag_service)) -> StreamingResponse:
    resolved_workspace = rag_service.normalize_workspace_id(payload.workspace_id)
    active_history = payload.history
    if payload.session_id:
        async with CHAT_SESSIONS_LOCK:
            stored_history = await asyncio.to_thread(
                STATE_STORE.get_chat_history,
                payload.session_id,
                resolved_workspace,
            )
            active_history = list(stored_history or payload.history)

    token_stream, citations, context_chunks = await rag_service.answer_stream(
        payload.question,
        active_history,
        payload.system_prompt,
        resolved_workspace,
    )

    async def event_stream() -> AsyncIterator[str]:
        full_answer_parts: list[str] = []
        try:
            async for token in token_stream:
                full_answer_parts.append(token)
                yield f"data: {json.dumps({'type': 'token', 'token': token})}\n\n"

            answer = "".join(full_answer_parts).strip()
            if payload.session_id:
                updated_history = [
                    *active_history,
                    ChatTurn(role="user", content=payload.question),
                    ChatTurn(role="assistant", content=answer),
                ]
                updated_history = updated_history[-40:]
                async with CHAT_SESSIONS_LOCK:
                    await asyncio.to_thread(
                        STATE_STORE.set_chat_history,
                        payload.session_id,
                        updated_history,
                        resolved_workspace,
                    )

            yield (
                "data: "
                + json.dumps(
                    {
                        "type": "final",
                        "answer": answer,
                        "citations": [citation.model_dump() for citation in citations],
                        "context_chunks": context_chunks,
                    },
                )
                + "\n\n"
            )
        except LocalLLMError as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Unexpected stream error: {exc}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

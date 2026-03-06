from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
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
async def get_chat_session(session_id: str) -> ChatSessionResponse:
    async with CHAT_SESSIONS_LOCK:
        history = await asyncio.to_thread(STATE_STORE.get_chat_history, session_id)

    return ChatSessionResponse(session_id=session_id, history=history)


@router.delete("/session/{session_id}", status_code=204)
async def clear_chat_session(session_id: str) -> None:
    async with CHAT_SESSIONS_LOCK:
        await asyncio.to_thread(STATE_STORE.clear_chat_session, session_id)


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, rag_service: RAGService = Depends(get_rag_service)) -> ChatResponse:
    active_history = payload.history
    if payload.session_id:
        async with CHAT_SESSIONS_LOCK:
            stored_history = await asyncio.to_thread(STATE_STORE.get_chat_history, payload.session_id)
            active_history = list(stored_history or payload.history)

    try:
        answer, citations, context_chunks = await rag_service.answer(payload.question, active_history)
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
            await asyncio.to_thread(STATE_STORE.set_chat_history, payload.session_id, updated_history)

    return ChatResponse(answer=answer, citations=citations, context_chunks=context_chunks)

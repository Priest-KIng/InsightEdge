from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from app.config import settings
from app.schemas import ChatTurn


class LocalLLMError(Exception):
    pass


class LocalLLMService:
    def __init__(self, base_url: str, model_name: str, timeout_seconds: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.timeout_seconds = timeout_seconds

    def _build_prompt(
        self,
        question: str,
        contexts: list[str],
        history: list[ChatTurn] | None = None,
        system_prompt: str | None = None,
    ) -> str:
        history = history or []
        context_blob = "\n\n".join([f"[{i+1}] {c}" for i, c in enumerate(contexts)])
        history_blob = "\n".join([f"{turn.role.upper()}: {turn.content}" for turn in history[-12:]])
        final_system_prompt = (system_prompt or settings.system_prompt).strip()
        return (
            f"{final_system_prompt}\n\n"
            f"Conversation History:\n{history_blob if history_blob else 'None'}\n\n"
            f"Context:\n{context_blob}\n\n"
            f"Question: {question}\n"
            "Answer:"
        )

    async def generate_from_prompt(self, prompt: str, temperature: float = 0.2) -> str:
        return await self.generate_from_prompt_with_model(prompt, temperature=temperature, model_name=None)

    async def generate_from_prompt_with_model(
        self,
        prompt: str,
        temperature: float = 0.2,
        model_name: str | None = None,
    ) -> str:
        selected_model = (model_name or self.model_name).strip()
        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                response = exc.response
                status = response.status_code if response is not None else "unknown"
                body = response.text if response is not None else "<no body>"
                raise LocalLLMError(f"Ollama returned {status}: {body}") from exc
            except Exception as exc:
                raise LocalLLMError(f"Failed to call Ollama: {exc}") from exc

        data = resp.json()
        return data.get("response", "").strip()

    async def generate(
        self,
        question: str,
        contexts: list[str],
        history: list[ChatTurn] | None = None,
        system_prompt: str | None = None,
        model_name: str | None = None,
    ) -> str:
        prompt = self._build_prompt(question, contexts, history, system_prompt)
        selected_model = (model_name or self.model_name).strip()

        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.2,
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                response = exc.response
                status = response.status_code if response is not None else "unknown"
                body = response.text if response is not None else "<no body>"
                raise LocalLLMError(f"Ollama returned {status}: {body}") from exc
            except Exception as exc:
                raise LocalLLMError(f"Failed to call Ollama: {exc}") from exc

        data = resp.json()
        return data.get("response", "").strip()

    async def generate_stream(
        self,
        question: str,
        contexts: list[str],
        history: list[ChatTurn] | None = None,
        system_prompt: str | None = None,
        model_name: str | None = None,
    ) -> AsyncIterator[str]:
        prompt = self._build_prompt(question, contexts, history, system_prompt)
        selected_model = (model_name or self.model_name).strip()
        payload = {
            "model": selected_model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": 0.2,
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                async with client.stream("POST", f"{self.base_url}/api/generate", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        token = str(event.get("response", ""))
                        if token:
                            yield token
            except httpx.HTTPStatusError as exc:
                response = exc.response
                status = response.status_code if response is not None else "unknown"
                body = response.text if response is not None else "<no body>"
                raise LocalLLMError(f"Ollama returned {status}: {body}") from exc
            except Exception as exc:
                raise LocalLLMError(f"Failed to call Ollama: {exc}") from exc

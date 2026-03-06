from __future__ import annotations

import argparse
import time

import httpx


PROMPTS = [
    "Summarize why small quantized models are better for a 4GB VRAM machine in 3 bullet points.",
    "Explain in 4 lines how retrieval-augmented generation works for local documents.",
]


def run_model(base_url: str, model: str, timeout: int) -> None:
    base_url = base_url.rstrip("/")
    with httpx.Client(timeout=timeout) as client:
        for idx, prompt in enumerate(PROMPTS, start=1):
            started = time.perf_counter()
            response = client.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.2},
                },
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            response.raise_for_status()
            payload = response.json()
            text = str(payload.get("response", "")).strip()
            print(f"[{idx}] model={model} latency_ms={elapsed_ms:.1f} chars={len(text)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick local LLM smoke benchmark for Ollama models")
    parser.add_argument("--model", required=True)
    parser.add_argument("--ollama-base-url", default="http://localhost:11434")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    run_model(args.ollama_base_url, args.model, args.timeout)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import time
from uuid import uuid4

import httpx


PROBE_FILENAME = "e2e_probe.txt"
PROBE_PASSPHRASE = "cobalt-lantern-4729"
PROBE_CONTENT = f"""InsightEdge E2E Probe Document

This document verifies the upload and retrieval workflow.
The audit passphrase is {PROBE_PASSPHRASE}.
If ingestion works, the system can retrieve this passphrase from the local vector store.
"""


def wait_for_job(client: httpx.Client, api_base: str, job_id: str, timeout_seconds: float) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    last_payload: dict[str, object] | None = None
    while time.monotonic() < deadline:
        response = client.get(f"{api_base}/ingest/jobs/{job_id}")
        response.raise_for_status()
        payload = response.json()
        last_payload = payload
        if payload.get("status") in {"completed", "failed"}:
            return payload
        time.sleep(0.5)
    raise TimeoutError(f"Timed out waiting for ingest job {job_id}; last status={last_payload}")


def ask_streaming_chat(
    client: httpx.Client,
    api_base: str,
    workspace: str,
    llm_model: str,
    question: str = "What is the audit passphrase in the probe document?",
) -> dict[str, object]:
    streamed_answer = ""
    final_payload: dict[str, object] | None = None
    with client.stream(
        "POST",
        f"{api_base}/chat/stream",
        json={
            "question": question,
            "workspace_id": workspace,
            "llm_model": llm_model,
            "session_id": f"{workspace}-session",
        },
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line.removeprefix("data: "))
            event_type = event.get("type")
            if event_type == "token":
                streamed_answer += str(event.get("token", ""))
            elif event_type == "final":
                final_payload = event
            elif event_type == "error":
                raise RuntimeError(f"Streaming chat returned error event: {event}")

    if final_payload is None:
        raise RuntimeError("Streaming chat ended without a final event")
    final_payload.setdefault("answer", streamed_answer)
    return final_payload


def run_smoke(args: argparse.Namespace) -> dict[str, object]:
    api_base = args.api_base.rstrip("/")
    workspace = args.workspace or f"e2e-smoke-{uuid4().hex[:8]}"

    with httpx.Client(timeout=args.timeout_seconds) as client:
        health = client.get(f"{api_base.replace('/api', '')}/api/health")
        health.raise_for_status()

        started = time.perf_counter()
        upload = client.post(
            f"{api_base}/ingest/files",
            data={"workspace_id": workspace},
            files={"files": (PROBE_FILENAME, PROBE_CONTENT.encode("utf-8"), "text/plain")},
        )
        upload_elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        upload.raise_for_status()
        upload_payload = upload.json()
        job_id = str(upload_payload["job_id"])

        job = wait_for_job(client, api_base, job_id, args.ingest_timeout_seconds)
        if job.get("status") != "completed":
            raise RuntimeError(f"Ingest job failed: {job}")
        if int(job.get("files_processed", 0)) < 1 or int(job.get("chunks_indexed", 0)) < 1:
            raise RuntimeError(f"Ingest job did not process and index the probe document: {job}")

        docs_response = client.get(f"{api_base}/ingest/documents", params={"workspace_id": workspace})
        docs_response.raise_for_status()
        documents = docs_response.json().get("documents", [])
        if not any(doc.get("source") == PROBE_FILENAME for doc in documents):
            raise RuntimeError(f"Uploaded filename not visible in document list: {documents}")

        chat_payload: dict[str, object] | None = None
        if not args.skip_chat:
            chat_payload = ask_streaming_chat(client, api_base, workspace, args.llm_model)
            answer = str(chat_payload.get("answer", ""))
            citations = chat_payload.get("citations", [])
            if PROBE_PASSPHRASE not in answer:
                raise RuntimeError(f"Chat answer did not include expected passphrase: {answer}")
            if not citations or citations[0].get("source") != PROBE_FILENAME:
                raise RuntimeError(f"Chat citations did not include original filename: {citations}")

            generic_chat_payload = ask_streaming_chat(
                client,
                api_base,
                workspace,
                args.llm_model,
                question="What is in the document?",
            )
            generic_citations = generic_chat_payload.get("citations", [])
            if int(generic_chat_payload.get("context_chunks", 0)) < 1:
                raise RuntimeError(f"Generic document query retrieved no chunks: {generic_chat_payload}")
            if not generic_citations or generic_citations[0].get("source") != PROBE_FILENAME:
                raise RuntimeError(
                    f"Generic document query did not cite the uploaded document: {generic_chat_payload}",
                )

    return {
        "ok": True,
        "workspace": workspace,
        "upload_elapsed_ms": upload_elapsed_ms,
        "job": job,
        "documents": documents,
        "chat": chat_payload,
        "generic_document_chat": generic_chat_payload if not args.skip_chat else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an end-to-end InsightEdge document upload and RAG smoke test.")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000/api")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--llm-model", default="llama3.1:8b-instruct-q4_K_M")
    parser.add_argument("--timeout-seconds", type=float, default=240.0)
    parser.add_argument("--ingest-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--skip-chat", action="store_true", help="Verify upload and ingestion only.")
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

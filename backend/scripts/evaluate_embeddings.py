from __future__ import annotations

import argparse
from pathlib import Path
import sys


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.embeddings import EmbeddingService


DOCS = [
    "RTX 3050 4GB VRAM is best paired with lightweight quantized local LLMs.",
    "ChromaDB stores embeddings and metadata for semantic document retrieval.",
    "Ollama can serve both text generation models and embedding models locally.",
    "PDF OCR fallback in InsightEdge uses pytesseract with pdf2image.",
]

QUERIES = [
    ("Which model strategy fits a 4GB GPU?", 0),
    ("Where are vectors persisted for search?", 1),
    ("Can Ollama be used for embeddings?", 2),
    ("How does OCR fallback work for PDFs?", 3),
]


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def evaluate(provider: str, model: str, ollama_base_url: str) -> None:
    service = EmbeddingService(
        model_name=model,
        provider=provider,
        ollama_base_url=ollama_base_url,
    )
    doc_vectors = service.embed(DOCS)
    query_vectors = service.embed([item[0] for item in QUERIES])

    correct = 0
    reciprocal_ranks: list[float] = []
    for q_idx, (_, expected_doc_idx) in enumerate(QUERIES):
        similarities = [
            (doc_idx, dot(query_vectors[q_idx], doc_vector))
            for doc_idx, doc_vector in enumerate(doc_vectors)
        ]
        ranked = sorted(similarities, key=lambda item: item[1], reverse=True)
        if ranked and ranked[0][0] == expected_doc_idx:
            correct += 1
        rank = next((idx + 1 for idx, (doc_idx, _) in enumerate(ranked) if doc_idx == expected_doc_idx), len(DOCS))
        reciprocal_ranks.append(1.0 / rank)

    accuracy = correct / len(QUERIES)
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)
    print(f"provider={provider} model={model}")
    print(f"top1_accuracy={accuracy:.3f}")
    print(f"mrr={mrr:.3f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Quick local embedding quality smoke test")
    parser.add_argument("--provider", default="sentence_transformers", choices=["sentence_transformers", "flagembedding", "ollama"])
    parser.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--ollama-base-url", default="http://localhost:11434")
    args = parser.parse_args()
    evaluate(args.provider, args.model, args.ollama_base_url)


if __name__ == "__main__":
    main()

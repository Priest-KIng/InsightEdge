# InsightEdge Local RAG Evaluation

- Run ID: 20261111T083609Z
- Workspace: eval-ced21a606d
- Fixture documents: 4
- Labeled questions: 16 (questions_paper.json; SHA-256 f40540dc63f750c08b4464d42687ecc9bcefee9df178426915cf2ee416b9d433)
- Ingestion success rate: 1.000
- OCR marker rate: 0.250
- Ingestion P50/P95: 171.27/4777.39 ms

## Comparative Retrieval Table

| Configuration | Recall@k | MRR | nDCG@k | Context P | Context R | Citation P | Source correctness | Chunk correctness | P50 ms | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| dense | 0.812 | 0.812 | 0.812 | 0.677 | 0.797 | 0.677 | 0.677 | 0.479 | 45.12 | 91.85 |
| lexical | 0.688 | 0.688 | 0.688 | 0.635 | 0.672 | 0.635 | 0.635 | 0.552 | 3.91 | 4.69 |
| hybrid | 0.812 | 0.812 | 0.812 | 0.677 | 0.797 | 0.677 | 0.677 | 0.479 | 47.85 | 56.29 |
| hybrid_rerank | 0.812 | 0.812 | 0.812 | 0.677 | 0.797 | 0.677 | 0.677 | 0.479 | 45.85 | 60.53 |
| hybrid_compression | 0.812 | 0.812 | 0.812 | 0.677 | 0.797 | 0.677 | 0.677 | 0.479 | 48.03 | 54.08 |
| router | 0.750 | 0.750 | 0.750 | 0.667 | 0.750 | 0.667 | 0.667 | 0.583 | 47.71 | 61.71 |

## Observed Discussion

Values above are computed from the checked-in local fixture corpus. No broad or state-of-the-art claim is implied.
Use the per-question rows in results.json and metrics.csv to identify which routing or retrieval configuration changed each result.
Groundedness uses deterministic required-term matching and should be treated as a regression signal, not a human or LLM judge.

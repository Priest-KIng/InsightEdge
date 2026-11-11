# Document Scope Contract Evaluation

- Run ID: 20261111T083539Z
- Synthetic near-duplicate documents: 24
- Queries: 24 filename-scoped factual lookups
- Ingestion: 24 files, 24 chunks, 6694.51 ms total
- Comparison: ordinary hybrid top-3 retrieval versus the same retrieval with filename-resolved document-ID filtering
- Generation: disabled; this isolates retrieval and source-scope behavior

| Metric | Unscoped retrieval | Scope constrained |
| --- | ---: | ---: |
| Target document recall@3 | 1.000 | 1.000 |
| Out-of-scope chunk rate | 0.667 | 0.000 |
| Scope contract pass rate | n/a | 1.000 |
| Mean retrieval latency (ms) | 56.50 | 52.54 |
| Scope resolution rate | n/a | 1.000 |

The generated corpus intentionally uses near-duplicate reports with the same vocabulary and source-specific measurements. Results characterize this controlled stress test only; they do not estimate leakage rates for arbitrary user documents.

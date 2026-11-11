# Relevance-gated source-coverage evaluation

This bundle contains the findings reported in **Calibrating Source Coverage for Multi Document Retrieval in InsightEdge**. The evaluation uses document-level evidence labels and does not score generated answers or citation entailment.

## Included files

- `findings_summary.json`: benchmark settings, aggregate metrics, paired-bootstrap results (including direct lexical MMR versus routed-gate comparison), and source metadata.
- `score_gate_cv.json`: five-fold threshold selection, fold assignments, per-query out-of-fold metrics, and bootstrap intervals.
- `enterprise_oof_query_metrics.csv`: query-level OOF predictions for each chunk-share constraint (1%, 2.5%, and 5%).
- `enterprise_query_metrics.csv`: selected per-query EnterpriseRAG retrieval configurations.
- `multihop_query_metrics.csv`: per-query retrieval outcomes on MultiHop-RAG, including the BM25, relevance-gated, lexical MMR, RBSC, and source-diverse policies.
- `backend/scripts/evaluate_enterprise_coverage.py`, `evaluate_relevance_gated_coverage.py`, `evaluate_multihop_coverage.py`, and `plot_paper_findings.py`: evaluation and figure-generation code in the project repository.

## Data and integrity

EnterpriseRAG-Bench v1.0.0 is obtained from the [official release](https://github.com/onyx-dot-app/EnterpriseRAG-Bench/releases/tag/v1.0.0). The archive SHA-256 is `9d1174928696ad08bc15f3f104739519de633c1605a4ec2034e0e3c0087bc5cd`; the 500-item question file SHA-256 is `f9524b9157cd43aae36b99333a124738804306ea6d07f332d49faa6d3d147905`. The full archive contains 511,962 records and is not copied into this repository.

MultiHop-RAG is available from its [official repository](https://github.com/yixuantt/MultiHop-RAG) and [Hugging Face dataset](https://huggingface.co/datasets/yixuantt/MultiHopRAG), under ODC-BY. The corpus JSON SHA-256 is `20b61b5ab84de84a927420c5d265b7ec8d859ae49980699958a787ade9e4d28f`; the question JSON SHA-256 is `03cfb4926461f868684903aadc8024447bdda5bb3f6804741424cce338515bff`. The reported run scored all 2,255 answerable questions. The 301 null-evidence questions are listed in run diagnostics but were not used to evaluate abstention.

## Re-running

Use the Python environment and dependencies described by the project setup guide. Download the official benchmark files and verify the hashes above before running. Full EnterpriseRAG retrieval takes substantially longer than the fixture tests; do not use `--source-limit` for a reported full-corpus result.

```powershell
python backend/scripts/evaluate_enterprise_coverage.py `
  --archive <path-to-all_documents.zip> `
  --questions <path-to-questions.jsonl> `
  --output-root backend/data/eval_enterprise_coverage_score_gated `
  --candidate-k 100 --top-k 8

python backend/scripts/evaluate_relevance_gated_coverage.py `
  --results <full-run-directory>/results.json `
  --output docs/paper_reproducibility/score_gated_coverage/score_gate_cv.json

python backend/scripts/evaluate_multihop_coverage.py `
  --corpus <path-to-corpus.json> `
  --questions <path-to-MultiHopRAG.json> `
  --output-root backend/data/eval_multihop_coverage `
  --relevance-ratio 0.85

python backend/scripts/plot_paper_findings.py
```

The five-fold selector chooses a score ratio from `{0.75, 0.85, 0.90, 0.95, 0.99}` using training queries only. It maximizes document recall subject to a gold-document chunk-share drop bound, then applies the selected ratio to each held-out fold. The primary bound is 2.5 percentage points. The route rule is held fixed and was previously inspected on EnterpriseRAG, so threshold selection is cross-validated but the full router is not independently learned. The MultiHop ratio is frozen at 0.85 and is not tuned on that dataset.

The independent MultiHop comparison includes **lexical** MMR: BM25 relevance combined with token-Jaccard redundancy. It is not a dense semantic MMR implementation. Confidence intervals bootstrap paired questions from fixed retrieval outputs; they do not measure run-to-run model, hardware, or corpus variation.

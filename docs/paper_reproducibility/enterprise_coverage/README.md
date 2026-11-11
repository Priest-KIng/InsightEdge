# EnterpriseRAG-Bench source-coverage evaluation

This bundle documents the retrieval-only ablation used in the InsightEdge paper. It includes the exact question-level output (`results.json`, `metrics.csv`, and `summary.md`), the dataset extraction manifest, and the code needed to reconstruct the corpus index. The 1.2 GB benchmark archive and the derived multi-gigabyte SQLite index are not checked into the repository.

## Data and integrity

Download the v1.0.0 `all_documents.zip` and `questions.jsonl` from the [official EnterpriseRAG-Bench repository and release page](https://github.com/onyx-dot-app/EnterpriseRAG-Bench/releases).

- `all_documents.zip` SHA-256: `9d1174928696ad08bc15f3f104739519de633c1605a4ec2034e0e3c0087bc5cd`
- `questions.jsonl` SHA-256: `f9524b9157cd43aae36b99333a124738804306ea6d07f332d49faa6d3d147905`
- The archive contains 511,962 text files and 511,958 distinct document IDs. Four IDs occur twice in separate source records; the extraction manifest lists the IDs and archive paths.
- The question set has 500 items. The retrieval experiment scores the 470 questions with non-empty `expected_doc_ids`; 92 have more than one distinct expected document ID. One question repeats the same ID in its annotation, so multi-document counts use distinct IDs. The 10 `high_level` and 20 `info_not_found` items without source-ID annotations are not included in document-recall metrics.

## Reproduce on Windows

Run from `backend` after installing the project dependencies. The evaluator reads `.txt` members directly from the archive, so no 512,000-file extraction is required:

```powershell
.\.venv\Scripts\python.exe -u scripts\evaluate_enterprise_coverage.py `
  --archive "$env:TEMP\insightedge-enterpriseragbench-v1\all_documents.zip" `
  --questions "$env:TEMP\insightedge-enterpriseragbench-v1\questions.jsonl" `
  --output-root data\eval_enterprise_coverage_full_zip `
  --candidate-k 100 --top-k 8

python -m pytest -q
```

The direct-archive path streams ZIP members, preserves source labels and flattened filenames, retains the four duplicate-ID records, and records the archive hash and corpus manifest. A full run indexes 511,962 text records into roughly three million chunks and takes tens of minutes on a laptop CPU; it prints progress every 5,000 files. The evaluator stores the FTS5 index and timestamped `results.json`, `metrics.csv`, and `summary.md` under the output directory. Do not commit the index.

An older two-step workflow (extract with `scripts\extract_enterpriserag_corpus.py`, then pass `--corpus-root`) is still supported but creates hundreds of thousands of files and is slower on Windows. If `--source-limit` is used for a smoke test, the run is a sample and must not be reported as full-corpus.

The evaluator uses the project chunker at 1,400 characters with 280-character overlap; FTS5 BM25 returns candidate@100, and each policy selects context@8. The paired confidence intervals resample questions 5,000 times with a fixed seed.

## Metrics and limits

- **Document recall@8:** mean fraction of each question's expected document IDs represented in the selected chunks.
- **Complete evidence-set recall@8:** fraction of questions for which every expected document ID appears in the selected chunks.
- **Gold-document chunk share:** fraction of selected chunks whose document ID is in the question's expected document-ID set. This is a document-label proxy, not passage-level relevance or citation entailment.
- **Unique documents@8:** count of distinct document IDs represented in context.
- **Intent-routed policy:** source selection activates only when the deterministic query-intent helper predicts a cross-source request. The helper combines explicit cross-source/overview cues with a long-compound-question rule (at least 25 words plus a second interrogative clause). That rule was inspected and tuned on this same benchmark, so its reported routing precision and recall are exploratory and need an independent labeled question set.
- **Oracle policy:** uses the gold number of expected document IDs and is an upper bound, not a deployable method.

The experiment evaluates lexical retrieval and context selection only. It does not evaluate generated answer correctness, citation entailment, refusal quality, answer-level faithfulness, or the serving stack's dense-priority hybrid ranking. The rank-window choice and the long-compound router rule were both selected using this benchmark; the full-corpus run is therefore not a held-out confirmation. Confirm the tradeoff with human passage-level judgments and end-to-end answer evaluation before making a general effectiveness claim.

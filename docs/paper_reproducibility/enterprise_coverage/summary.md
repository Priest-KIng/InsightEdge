# EnterpriseRAG-Bench source-coverage experiment

- Run: `20261111T113805Z`
- Corpus: 511,962 documents / 2,522,807 chunks; source slices: confluence, fireflies, github, gmail, google_drive, hubspot, jira, linear, slack
- Supported questions: 470 (all annotated gold document IDs present)
- Question fixture SHA-256: `f9524b9157cd43aae36b99333a124738804306ea6d07f332d49faa6d3d147905`
- Retrieval: SQLite FTS5 BM25, candidate@100, context@8 (build 881.5s; retrieve 2131.1s)

| Policy | Doc recall | Complete evidence set | Gold-doc chunk share | Unique documents@k |
|---|---:|---:|---:|---:|
| global_bm25_topk | 0.633 | 0.566 | 0.195 | 7.04 |
| source_diverse_topk | 0.652 | 0.589 | 0.118 | 8.00 |
| source_cap_2 | 0.641 | 0.574 | 0.163 | 7.33 |
| source_cap_3 | 0.636 | 0.570 | 0.182 | 7.15 |
| bounded_cap2_window_0 | 0.633 | 0.566 | 0.194 | 7.04 |
| bounded_cap2_window_4 | 0.641 | 0.574 | 0.167 | 7.30 |
| bounded_cap2_window_8 | 0.641 | 0.574 | 0.163 | 7.33 |
| bounded_cap2_window_12 | 0.641 | 0.574 | 0.163 | 7.33 |
| bounded_cap2_window_16 | 0.641 | 0.574 | 0.163 | 7.33 |
| bounded_cap2_window_32 | 0.641 | 0.574 | 0.163 | 7.33 |
| bounded_cap2_window_64 | 0.641 | 0.574 | 0.163 | 7.33 |
| intent_routed_source_diverse | 0.644 | 0.579 | 0.159 | 7.46 |
| intent_routed_source_cap_2 | 0.639 | 0.572 | 0.178 | 7.20 |
| oracle_intent_upper_bound | 0.646 | 0.583 | 0.164 | 7.40 |

## Paired bootstrap differences vs global BM25

- `oracle_intent_upper_bound` overall document-recall difference: +0.013, 95% CI [+0.006, +0.020]; multi-gold subset: +0.064, 95% CI [+0.035, +0.098].
- `intent_routed_source_cap_2` overall document-recall difference: +0.006, 95% CI [+0.002, +0.011]; multi-gold subset: +0.029, 95% CI [+0.010, +0.054].
- `bounded_cap2_window_12` overall document-recall difference: +0.008, 95% CI [+0.003, +0.015]; multi-gold subset: +0.029, 95% CI [+0.010, +0.054].
- `intent_routed_source_diverse` overall document-recall difference: +0.010, 95% CI [+0.005, +0.017]; multi-gold subset: +0.052, 95% CI [+0.025, +0.084].
- `source_cap_2` overall document-recall difference: +0.008, 95% CI [+0.003, +0.015]; multi-gold subset: +0.029, 95% CI [+0.010, +0.054].
- `bounded_cap2_window_0` overall document-recall difference: +0.000, 95% CI [+0.000, +0.000]; multi-gold subset: +0.000, 95% CI [+0.000, +0.000].
- `bounded_cap2_window_16` overall document-recall difference: +0.008, 95% CI [+0.003, +0.015]; multi-gold subset: +0.029, 95% CI [+0.010, +0.054].
- `bounded_cap2_window_32` overall document-recall difference: +0.008, 95% CI [+0.003, +0.015]; multi-gold subset: +0.029, 95% CI [+0.010, +0.054].
- `bounded_cap2_window_64` overall document-recall difference: +0.008, 95% CI [+0.003, +0.015]; multi-gold subset: +0.029, 95% CI [+0.010, +0.054].
- `source_diverse_topk` overall document-recall difference: +0.019, 95% CI [+0.010, +0.030]; multi-gold subset: +0.064, 95% CI [+0.035, +0.098].
- `bounded_cap2_window_4` overall document-recall difference: +0.008, 95% CI [+0.003, +0.015]; multi-gold subset: +0.029, 95% CI [+0.010, +0.054].
- `bounded_cap2_window_8` overall document-recall difference: +0.008, 95% CI [+0.003, +0.015]; multi-gold subset: +0.029, 95% CI [+0.010, +0.054].
- `source_cap_3` overall document-recall difference: +0.002, 95% CI [+0.000, +0.006]; multi-gold subset: +0.013, 95% CI [+0.000, +0.029].

## Multi-document retrieval results

| Policy | Queries | Document recall@k | Complete evidence set@k | Gold-doc chunk share@k |
|---|---:|---:|---:|---:|
| global_bm25_topk | 92 | 0.551 | 0.207 | 0.414 |
| source_diverse_topk | 92 | 0.616 | 0.293 | 0.261 |
| source_cap_2 | 92 | 0.581 | 0.239 | 0.351 |
| source_cap_3 | 92 | 0.564 | 0.228 | 0.395 |
| bounded_cap2_window_0 | 92 | 0.551 | 0.207 | 0.414 |
| bounded_cap2_window_4 | 92 | 0.581 | 0.239 | 0.364 |
| bounded_cap2_window_8 | 92 | 0.581 | 0.239 | 0.352 |
| bounded_cap2_window_12 | 92 | 0.581 | 0.239 | 0.351 |
| bounded_cap2_window_16 | 92 | 0.581 | 0.239 | 0.351 |
| bounded_cap2_window_32 | 92 | 0.581 | 0.239 | 0.351 |
| bounded_cap2_window_64 | 92 | 0.581 | 0.239 | 0.351 |
| intent_routed_source_diverse | 92 | 0.604 | 0.272 | 0.334 |
| intent_routed_source_cap_2 | 92 | 0.581 | 0.239 | 0.382 |
| oracle_intent_upper_bound | 92 | 0.616 | 0.293 | 0.261 |

## Scope and limitations

- Only questions with annotated expected_doc_ids are scored; the high_level and info_not_found items without document-ID labels are excluded.
- Expected document IDs are gold at the document level, not at the chunk level; gold-document chunk share is a proxy and does not establish passage-level entailment.
- This experiment isolates chunk retrieval and source selection; it does not evaluate language-model answer correctness or citation entailment.
- The experiment uses SQLite FTS5 BM25; InsightEdge serving also uses dense-priority hybrid candidates, so the BM25 results do not directly establish end-to-end hybrid gains.
- A bounded selector can still trade chunk precision for source recall; retrieval labels do not establish answer correctness or citation entailment.

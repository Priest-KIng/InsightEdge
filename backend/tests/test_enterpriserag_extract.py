from __future__ import annotations

import json
from pathlib import Path
import sys
import zipfile


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from extract_enterpriserag_corpus import extract_corpus


def test_extractor_preserves_duplicate_ids_and_resumes_safely(tmp_path: Path) -> None:
    archive = tmp_path / "mini-benchmark.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(
            "confluence/teams/dsid_same__policy-a.txt",
            "First policy evidence.",
        )
        output.writestr(
            "google_drive/users/dsid_same__policy-b.txt",
            "Second source record with the same ID.",
        )
        output.writestr(
            "slack/channels/dsid_other__message.txt",
            "A separate document.",
        )

    corpus_root = tmp_path / "short" / "corpus"
    first = extract_corpus(archive, corpus_root, "all_documents_slice_0001")

    assert first["document_count"] == 3
    assert first["unique_document_id_count"] == 2
    assert first["duplicate_document_id_instances"] == 1
    assert first["documents_extracted_this_run"] == 3
    assert len(first["duplicate_document_ids"]["dsid_same"]) == 2
    assert (corpus_root / "all_documents_slice_0001" / "confluence" / "dsid_same__policy-a.txt").is_file()
    assert (corpus_root / "all_documents_slice_0001" / "google_drive" / "dsid_same__policy-b.txt").is_file()

    second = extract_corpus(archive, corpus_root, "all_documents_slice_0001")

    assert second["documents_extracted_this_run"] == 0
    assert second["documents_already_present"] == 3
    manifest = json.loads(
        (corpus_root / "all_documents_slice_0001" / "extraction_manifest.json").read_text(encoding="utf-8"),
    )
    assert manifest["archive_sha256"] == first["archive_sha256"]

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import zipfile


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_corpus(archive_path: Path, corpus_root: Path, slice_name: str) -> dict[str, object]:
    """Flatten the official archive to short source/filename paths for Windows-safe indexing."""
    archive_path = archive_path.resolve()
    corpus_root = corpus_root.resolve()
    target_root = (corpus_root / slice_name).resolve()
    if not target_root.is_relative_to(corpus_root):
        raise ValueError("slice_name must resolve inside corpus_root")
    target_root.mkdir(parents=True, exist_ok=True)

    source_counts: Counter[str] = Counter()
    extracted = skipped = total_bytes = longest_path = 0
    seen_ids: Counter[str] = Counter()
    seen_id_paths: dict[str, list[str]] = {}
    seen_targets: set[str] = set()
    duplicate_id_instances = 0
    with zipfile.ZipFile(archive_path) as archive:
        files = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".txt")]
        for number, item in enumerate(files, start=1):
            parts = PurePosixPath(item.filename).parts
            if len(parts) < 2:
                raise ValueError(f"Expected <source>/.../<document>.txt, got {item.filename!r}")
            source_type = parts[0]
            if source_type in {"", ".", ".."} or Path(source_type).is_absolute():
                raise ValueError(f"Unsafe source directory in {item.filename!r}")
            filename = parts[-1]
            document_id = filename.split("__", 1)[0]
            if not document_id.startswith("dsid_"):
                raise ValueError(f"Missing benchmark document ID in {filename!r}")
            if seen_ids[document_id]:
                duplicate_id_instances += 1
                seen_id_paths.setdefault(document_id, []).append(item.filename)
            else:
                seen_id_paths[document_id] = [item.filename]
            seen_ids[document_id] += 1

            target = target_root / source_type / filename
            if not target.resolve().is_relative_to(target_root):
                raise ValueError(f"Archive path escapes extraction root: {item.filename!r}")
            target_key = str(target).casefold()
            if target_key in seen_targets:
                suffix = hashlib.sha256(item.filename.encode("utf-8")).hexdigest()[:10]
                target = target.with_name(f"{target.stem}__archive_{suffix}{target.suffix}")
                target_key = str(target).casefold()
            if target_key in seen_targets:
                raise ValueError(f"Flattened output path collision for {item.filename!r}")
            seen_targets.add(target_key)
            target.parent.mkdir(parents=True, exist_ok=True)
            longest_path = max(longest_path, len(str(target)))
            if target.exists():
                if target.stat().st_size != item.file_size:
                    raise ValueError(f"Existing output has wrong size: {target}")
                skipped += 1
            else:
                partial = target.with_name(target.name + ".partial")
                try:
                    with archive.open(item) as source, partial.open("wb") as destination:
                        shutil.copyfileobj(source, destination, length=1024 * 1024)
                    if partial.stat().st_size != item.file_size:
                        raise IOError(f"Size mismatch while extracting {item.filename}")
                    partial.replace(target)
                finally:
                    partial.unlink(missing_ok=True)
                extracted += 1
            source_counts[source_type] += 1
            total_bytes += item.file_size
            if number % 25000 == 0:
                print(f"processed {number:,}/{len(files):,} files", flush=True)

    manifest = {
        "benchmark": "EnterpriseRAG-Bench v1.0.0",
        "archive_file": archive_path.name,
        "archive_sha256": _sha256(archive_path),
        "corpus_root_label": corpus_root.name,
        "slice_name": slice_name,
        "document_count": len(files),
        "unique_document_id_count": len(seen_ids),
        "duplicate_document_id_instances": duplicate_id_instances,
        "duplicate_document_ids": {
            document_id: paths
            for document_id, paths in sorted(seen_id_paths.items())
            if len(paths) > 1
        },
        "document_bytes": total_bytes,
        "documents_extracted_this_run": extracted,
        "documents_already_present": skipped,
        "longest_output_path_characters": longest_path,
        "documents_by_source": dict(sorted(source_counts.items())),
    }
    (target_root / "extraction_manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract the official EnterpriseRAG-Bench text corpus safely.")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--corpus-root", required=True, type=Path)
    parser.add_argument("--slice-name", default="all_documents_slice_0001")
    args = parser.parse_args()
    print(json.dumps(extract_corpus(args.archive, args.corpus_root, args.slice_name), indent=2))


if __name__ == "__main__":
    main()

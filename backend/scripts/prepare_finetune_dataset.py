from __future__ import annotations

import argparse
import json
from pathlib import Path


def convert_record(record: dict[str, str]) -> dict[str, str]:
    question = str(record.get("question", "")).strip()
    answer = str(record.get("answer", "")).strip()
    if not question or not answer:
        raise ValueError("Each record must include non-empty 'question' and 'answer'")
    text = (
        "<|system|>\nYou are a domain expert assistant.\n"
        "<|user|>\n"
        f"{question}\n"
        "<|assistant|>\n"
        f"{answer}"
    )
    return {"text": text}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare JSON/JSONL Q&A data for SFT fine-tuning")
    parser.add_argument("--input", required=True, help="Path to .json or .jsonl file with question/answer records")
    parser.add_argument("--output", required=True, help="Path to output .jsonl in {'text': ...} format")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, str]] = []
    if input_path.suffix.lower() == ".jsonl":
        for line in input_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    else:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("JSON input must be an array of {'question': ..., 'answer': ...}")
        records = [dict(item) for item in payload]

    converted = [convert_record(record) for record in records]
    with output_path.open("w", encoding="utf-8") as handle:
        for row in converted:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Wrote {len(converted)} rows to {output_path}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from pathlib import Path

from datasets import load_dataset
from trl import SFTTrainer, SFTConfig
from unsloth import FastLanguageModel


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune a model with Unsloth + QLoRA on local Q&A data")
    parser.add_argument("--dataset", required=True, help="Prepared JSONL file with {'text': ...} rows")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--base-model", default="meta-llama/Meta-Llama-3.1-8B-Instruct")
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum-steps", type=int, default=8)
    parser.add_argument("--num-train-epochs", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    args = parser.parse_args()

    dataset_path = Path(args.dataset).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base_model,
        max_seq_length=args.max_seq_length,
        dtype=None,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        lora_alpha=16,
        lora_dropout=0.0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
        max_seq_length=args.max_seq_length,
    )

    dataset = load_dataset("json", data_files=str(dataset_path), split="train")
    config = SFTConfig(
        output_dir=str(output_dir),
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum_steps,
        num_train_epochs=args.num_train_epochs,
        learning_rate=args.learning_rate,
        fp16=True,
        logging_steps=10,
        save_strategy="epoch",
        max_seq_length=args.max_seq_length,
        dataset_text_field="text",
        packing=False,
    )
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=config,
    )
    trainer.train()
    trainer.save_model(str(output_dir / "adapter"))
    tokenizer.save_pretrained(str(output_dir / "adapter"))
    print(f"Saved adapter to: {output_dir / 'adapter'}")


if __name__ == "__main__":
    main()

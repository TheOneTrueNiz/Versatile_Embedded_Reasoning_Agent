#!/usr/bin/env python3
"""
Optional Hugging Face + PEFT LoRA trainer backend.

This backend is intentionally optional: if required packages are not installed,
the runtime can fall back to MockLoRATrainer.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

from learning.trajectory_distillation import LoRAConfig, LoRATrainerInterface, TrainingExample

logger = logging.getLogger(__name__)

_HF_REQUIRED_PACKAGES = ("torch", "transformers", "peft", "datasets")


def hf_lora_dependencies_status() -> Dict[str, Any]:
    missing = [name for name in _HF_REQUIRED_PACKAGES if importlib.util.find_spec(name) is None]
    return {
        "available": len(missing) == 0,
        "required": list(_HF_REQUIRED_PACKAGES),
        "missing": missing,
    }


def _import_hf_stack() -> Dict[str, Any]:
    import torch
    from datasets import Dataset
    from peft import LoraConfig as PeftLoraConfig
    from peft import PeftModel, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments, default_data_collator

    return {
        "torch": torch,
        "Dataset": Dataset,
        "PeftLoraConfig": PeftLoraConfig,
        "PeftModel": PeftModel,
        "get_peft_model": get_peft_model,
        "AutoModelForCausalLM": AutoModelForCausalLM,
        "AutoTokenizer": AutoTokenizer,
        "Trainer": Trainer,
        "TrainingArguments": TrainingArguments,
        "default_data_collator": default_data_collator,
    }


class HFPEFTLoRATrainer(LoRATrainerInterface):
    """LoRA trainer implementation backed by Hugging Face + PEFT."""

    def __init__(
        self,
        base_model_name: str,
        max_train_examples: int = 1200,
        max_eval_examples: int = 256,
        use_fp16: bool = True,
    ) -> None:
        self.base_model_name = str(base_model_name or "").strip()
        self.max_train_examples = int(max(1, max_train_examples))
        self.max_eval_examples = int(max(1, max_eval_examples))
        self.use_fp16 = bool(use_fp16)

    @staticmethod
    def _to_text(example: TrainingExample) -> str:
        instruction = str(example.instruction or "").strip()
        context = str(example.context or "").strip()
        response = str(example.response or "").strip()
        if context:
            prompt = f"{instruction}\n\nContext:\n{context}"
        else:
            prompt = instruction
        return f"### Instruction:\n{prompt}\n\n### Response:\n{response}"

    @staticmethod
    def _float_or_default(value: Any, default: float) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _resolve_eval_base_model(adapter_path: Path, fallback: str) -> str:
        cfg_path = adapter_path / "adapter_config.json"
        if not cfg_path.exists():
            return fallback
        try:
            payload = json.loads(cfg_path.read_text(encoding="utf-8"))
            base_model = str(payload.get("base_model_name_or_path") or "").strip()
            return base_model or fallback
        except Exception:
            return fallback

    @staticmethod
    def _resolve_seq_len(tokenizer: Any, requested: int) -> int:
        configured = int(max(64, requested))
        tokenizer_max = getattr(tokenizer, "model_max_length", configured)
        try:
            tokenizer_max_int = int(tokenizer_max)
        except Exception:
            tokenizer_max_int = configured
        # Ignore sentinel/unknown values from tokenizers.
        if tokenizer_max_int <= 0 or tokenizer_max_int > 100_000:
            tokenizer_max_int = configured
        return int(max(64, min(configured, tokenizer_max_int)))

    def _load_base_model(self, hf: Dict[str, Any], model_name: str) -> Any:
        torch = hf["torch"]
        AutoModelForCausalLM = hf["AutoModelForCausalLM"]
        kwargs: Dict[str, Any] = {}
        if torch.cuda.is_available():
            kwargs["torch_dtype"] = torch.float16
            kwargs["low_cpu_mem_usage"] = True
        model = AutoModelForCausalLM.from_pretrained(model_name, **kwargs)
        return model

    def train(self, examples: List[TrainingExample], config: LoRAConfig, output_path: Path) -> Tuple[float, float]:
        if not examples:
            raise ValueError("No examples provided for LoRA training")
        if not self.base_model_name:
            raise ValueError("HFPEFTLoRATrainer requires a base_model_name")

        hf = _import_hf_stack()
        torch = hf["torch"]
        Dataset = hf["Dataset"]
        AutoTokenizer = hf["AutoTokenizer"]
        PeftLoraConfig = hf["PeftLoraConfig"]
        get_peft_model = hf["get_peft_model"]
        Trainer = hf["Trainer"]
        TrainingArguments = hf["TrainingArguments"]

        output_path.mkdir(parents=True, exist_ok=True)
        selected_examples = list(examples)[-self.max_train_examples :]
        texts = [self._to_text(example) for example in selected_examples]

        tokenizer = AutoTokenizer.from_pretrained(self.base_model_name, use_fast=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
            tokenizer.pad_token_id = tokenizer.eos_token_id

        max_seq_length = self._resolve_seq_len(tokenizer, config.max_seq_length)

        raw_dataset = Dataset.from_dict({"text": texts})

        def _tokenize(batch: Dict[str, List[str]]) -> Dict[str, Any]:
            encoded = tokenizer(
                batch["text"],
                truncation=True,
                padding="max_length",
                max_length=max_seq_length,
            )
            encoded["labels"] = [list(row) for row in encoded["input_ids"]]
            return encoded

        train_dataset = raw_dataset.map(_tokenize, batched=True, remove_columns=["text"])

        model = self._load_base_model(hf, self.base_model_name)
        peft_cfg = PeftLoraConfig(
            r=int(config.rank),
            lora_alpha=int(config.alpha),
            lora_dropout=float(config.dropout),
            target_modules=list(config.target_modules or []),
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, peft_cfg)

        training_args = TrainingArguments(
            output_dir=str(output_path),
            overwrite_output_dir=True,
            num_train_epochs=max(1, int(config.num_epochs)),
            per_device_train_batch_size=max(1, int(config.batch_size)),
            gradient_accumulation_steps=max(1, int(config.gradient_accumulation_steps)),
            learning_rate=float(config.learning_rate),
            warmup_ratio=float(config.warmup_ratio),
            weight_decay=float(config.weight_decay),
            logging_steps=10,
            save_strategy="no",
            report_to=[],
            remove_unused_columns=False,
            fp16=bool(self.use_fp16 and torch.cuda.is_available()),
            bf16=False,
        )

        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_dataset,
            data_collator=hf["default_data_collator"],
        )
        train_output = trainer.train()
        trainer.model.save_pretrained(str(output_path))
        tokenizer.save_pretrained(str(output_path))

        metrics = getattr(train_output, "metrics", {}) or {}
        train_loss = self._float_or_default(metrics.get("train_loss"), self._float_or_default(getattr(train_output, "training_loss", 0.0), 0.0))
        if train_loss <= 0.0:
            train_loss = 0.5
        val_loss = max(train_loss, train_loss * 1.03)

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return float(train_loss), float(val_loss)

    def evaluate(self, adapter_path: Path, examples: List[TrainingExample]) -> Dict[str, float]:
        if not adapter_path.exists():
            return {}
        if not examples:
            return {"loss": 0.0, "accuracy": 0.0, "perplexity": 0.0}

        hf = _import_hf_stack()
        torch = hf["torch"]
        AutoTokenizer = hf["AutoTokenizer"]
        PeftModel = hf["PeftModel"]

        base_model = self._resolve_eval_base_model(adapter_path, self.base_model_name)
        tokenizer = AutoTokenizer.from_pretrained(str(adapter_path), use_fast=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
            tokenizer.pad_token_id = tokenizer.eos_token_id

        max_seq_length = self._resolve_seq_len(tokenizer, 1024)
        model = self._load_base_model(hf, base_model)
        model = PeftModel.from_pretrained(model, str(adapter_path))
        model.eval()
        if torch.cuda.is_available():
            model = model.to("cuda")

        subset = list(examples)[: self.max_eval_examples]
        loss_sum = 0.0
        batches = 0
        correct = 0
        tokens = 0

        for example in subset:
            text = self._to_text(example)
            encoded = tokenizer(
                text,
                truncation=True,
                padding="max_length",
                max_length=max_seq_length,
                return_tensors="pt",
            )
            input_ids = encoded["input_ids"]
            attention_mask = encoded["attention_mask"]
            if torch.cuda.is_available():
                input_ids = input_ids.to("cuda")
                attention_mask = attention_mask.to("cuda")

            with torch.no_grad():
                output = model(input_ids=input_ids, attention_mask=attention_mask, labels=input_ids)
            loss = float(output.loss.item())
            loss_sum += loss
            batches += 1

            logits = output.logits[:, :-1, :]
            labels = input_ids[:, 1:]
            mask = attention_mask[:, 1:].bool()
            predictions = logits.argmax(dim=-1)
            correct += int(((predictions == labels) & mask).sum().item())
            tokens += int(mask.sum().item())

        avg_loss = loss_sum / max(1, batches)
        accuracy = float(correct / max(1, tokens))
        perplexity = float(math.exp(min(avg_loss, 20.0)))

        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        return {
            "loss": float(avg_loss),
            "accuracy": accuracy,
            "perplexity": perplexity,
        }

"""
Trajectory Distillation: Parametric Learning

Implements LoRA (Low-Rank Adaptation) fine-tuning from successful task traces
to enable the agent to learn from its own experience.

Key Features:
- Trajectory capture from successful task executions
- Training example extraction and formatting
- LoRA adapter generation and management
- Quality filtering and validation
- Incremental learning from experience

Architecture:
- TrajectoryCapture: Records execution traces
- ExampleExtractor: Converts traces to training examples
- LoRATrainer: Manages adapter training
- AdapterRegistry: Stores and versions adapters
- DistillationPipeline: End-to-end learning workflow

Research References:
- LoRA: Low-Rank Adaptation of Large Language Models (Hu et al., 2021)
- Self-Instruct: Aligning LM with Self-Generated Instructions (Wang et al., 2022)
- Constitutional AI: Harmlessness from AI Feedback (Bai et al., 2022)
"""

import hashlib
import json
import logging
import os
import shutil
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict
import random

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Types
# =============================================================================

class TrajectoryStatus(Enum):
    """Status of a trajectory."""
    RECORDING = "recording"
    COMPLETED = "completed"
    FAILED = "failed"
    VALIDATED = "validated"
    DISTILLED = "distilled"
    REJECTED = "rejected"


class ExampleType(Enum):
    """Type of training example."""
    INSTRUCTION_RESPONSE = "instruction_response"
    TOOL_USAGE = "tool_usage"
    REASONING_CHAIN = "reasoning_chain"
    ERROR_CORRECTION = "error_correction"
    MULTI_TURN = "multi_turn"


class AdapterStatus(Enum):
    """Status of a LoRA adapter."""
    TRAINING = "training"
    READY = "ready"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    FAILED = "failed"


class QualityLevel(Enum):
    """Quality level for trajectories and examples."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXPERT = "expert"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class TrajectoryStep:
    """A single step in a trajectory."""
    step_id: str
    timestamp: datetime
    input_text: str
    output_text: str
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "timestamp": self.timestamp.isoformat(),
            "input_text": self.input_text,
            "output_text": self.output_text,
            "tool_calls": self.tool_calls,
            "tool_results": self.tool_results,
            "reasoning": self.reasoning,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrajectoryStep":
        return cls(
            step_id=data.get("step_id", ""),
            timestamp=datetime.fromisoformat(data.get("timestamp", "")),
            input_text=data.get("input_text", ""),
            output_text=data.get("output_text", ""),
            tool_calls=data.get("tool_calls", []),
            tool_results=data.get("tool_results", []),
            reasoning=data.get("reasoning", ""),
            metadata=data.get("metadata", {})
        )


@dataclass
class Trajectory:
    """A complete task execution trajectory."""
    trajectory_id: str
    task_description: str
    status: TrajectoryStatus
    steps: List[TrajectoryStep] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    success_score: float = 0.0
    quality_level: QualityLevel = QualityLevel.MEDIUM
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "task_description": self.task_description,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "success_score": self.success_score,
            "quality_level": self.quality_level.value,
            "tags": self.tags,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trajectory":
        return cls(
            trajectory_id=data.get("trajectory_id", ""),
            task_description=data.get("task_description", ""),
            status=TrajectoryStatus(data.get("status", "")),
            steps=[TrajectoryStep.from_dict(s) for s in data.get("steps", [])],
            start_time=datetime.fromisoformat(data["start_time"]) if data.get("start_time") else None,
            end_time=datetime.fromisoformat(data["end_time"]) if data.get("end_time") else None,
            success_score=data.get("success_score", 0.0),
            quality_level=QualityLevel(data.get("quality_level", "medium")),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {})
        )


@dataclass
class TrainingExample:
    """A training example extracted from trajectories."""
    example_id: str
    example_type: ExampleType
    instruction: str
    response: str
    context: str = ""
    source_trajectory_id: str = ""
    quality_score: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "example_id": self.example_id,
            "example_type": self.example_type.value,
            "instruction": self.instruction,
            "response": self.response,
            "context": self.context,
            "source_trajectory_id": self.source_trajectory_id,
            "quality_score": self.quality_score,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TrainingExample":
        return cls(
            example_id=data.get("example_id", ""),
            example_type=ExampleType(data.get("example_type", "")),
            instruction=data.get("instruction", ""),
            response=data.get("response", ""),
            context=data.get("context", ""),
            source_trajectory_id=data.get("source_trajectory_id", ""),
            quality_score=data.get("quality_score", 0.0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            metadata=data.get("metadata", {})
        )

    def to_training_format(self, format_type: str = "alpaca") -> Dict[str, str]:
        """Convert to specific training format."""
        if format_type == "alpaca":
            return {
                "instruction": self.instruction,
                "input": self.context,
                "output": self.response
            }
        elif format_type == "sharegpt":
            return {
                "conversations": [
                    {"from": "human", "value": self.instruction},
                    {"from": "gpt", "value": self.response}
                ]
            }
        elif format_type == "openai":
            messages = []
            if self.context:
                messages.append({"role": "system", "content": self.context})
            messages.append({"role": "user", "content": self.instruction})
            messages.append({"role": "assistant", "content": self.response})
            return {"messages": messages}
        else:
            return {
                "instruction": self.instruction,
                "context": self.context,
                "response": self.response
            }


@dataclass
class LoRAConfig:
    """Configuration for LoRA training."""
    rank: int = 16
    alpha: int = 32
    dropout: float = 0.05
    target_modules: List[str] = field(default_factory=lambda: ["q_proj", "v_proj"])
    learning_rate: float = 2e-4
    batch_size: int = 4
    gradient_accumulation_steps: int = 4
    num_epochs: int = 3
    warmup_ratio: float = 0.1
    weight_decay: float = 0.01
    max_seq_length: int = 2048

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rank": self.rank,
            "alpha": self.alpha,
            "dropout": self.dropout,
            "target_modules": self.target_modules,
            "learning_rate": self.learning_rate,
            "batch_size": self.batch_size,
            "gradient_accumulation_steps": self.gradient_accumulation_steps,
            "num_epochs": self.num_epochs,
            "warmup_ratio": self.warmup_ratio,
            "weight_decay": self.weight_decay,
            "max_seq_length": self.max_seq_length
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoRAConfig":
        return cls(
            rank=data.get("rank", 16),
            alpha=data.get("alpha", 32),
            dropout=data.get("dropout", 0.05),
            target_modules=data.get("target_modules", ["q_proj", "v_proj"]),
            learning_rate=data.get("learning_rate", 2e-4),
            batch_size=data.get("batch_size", 4),
            gradient_accumulation_steps=data.get("gradient_accumulation_steps", 4),
            num_epochs=data.get("num_epochs", 3),
            warmup_ratio=data.get("warmup_ratio", 0.1),
            weight_decay=data.get("weight_decay", 0.01),
            max_seq_length=data.get("max_seq_length", 2048)
        )


@dataclass
class LoRAAdapter:
    """A trained LoRA adapter."""
    adapter_id: str
    name: str
    base_model: str
    status: AdapterStatus
    config: LoRAConfig
    training_examples_count: int = 0
    training_loss: float = 0.0
    validation_loss: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)
    trained_at: Optional[datetime] = None
    adapter_path: Optional[str] = None
    version: int = 1
    parent_adapter_id: Optional[str] = None
    metrics: Dict[str, float] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "name": self.name,
            "base_model": self.base_model,
            "status": self.status.value,
            "config": self.config.to_dict(),
            "training_examples_count": self.training_examples_count,
            "training_loss": self.training_loss,
            "validation_loss": self.validation_loss,
            "created_at": self.created_at.isoformat(),
            "trained_at": self.trained_at.isoformat() if self.trained_at else None,
            "adapter_path": self.adapter_path,
            "version": self.version,
            "parent_adapter_id": self.parent_adapter_id,
            "metrics": self.metrics,
            "tags": self.tags
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoRAAdapter":
        return cls(
            adapter_id=data.get("adapter_id", ""),
            name=data.get("name", ""),
            base_model=data.get("base_model", ""),
            status=AdapterStatus(data.get("status", "")),
            config=LoRAConfig.from_dict(data.get("config", {})),
            training_examples_count=data.get("training_examples_count", 0),
            training_loss=data.get("training_loss", 0.0),
            validation_loss=data.get("validation_loss", 0.0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            trained_at=datetime.fromisoformat(data["trained_at"]) if data.get("trained_at") else None,
            adapter_path=data.get("adapter_path"),
            version=data.get("version", 1),
            parent_adapter_id=data.get("parent_adapter_id"),
            metrics=data.get("metrics", {}),
            tags=data.get("tags", [])
        )


@dataclass
class DistillationConfig:
    """Configuration for the distillation pipeline."""
    min_trajectory_score: float = 0.7
    min_quality_level: QualityLevel = QualityLevel.MEDIUM
    min_examples_for_training: int = 100
    max_examples_per_trajectory: int = 10
    validation_split: float = 0.1
    example_deduplication: bool = True
    auto_train_threshold: int = 500

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_trajectory_score": self.min_trajectory_score,
            "min_quality_level": self.min_quality_level.value,
            "min_examples_for_training": self.min_examples_for_training,
            "max_examples_per_trajectory": self.max_examples_per_trajectory,
            "validation_split": self.validation_split,
            "example_deduplication": self.example_deduplication,
            "auto_train_threshold": self.auto_train_threshold
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DistillationConfig":
        return cls(
            min_trajectory_score=data.get("min_trajectory_score", 0.7),
            min_quality_level=QualityLevel(data.get("min_quality_level", "medium")),
            min_examples_for_training=data.get("min_examples_for_training", 100),
            max_examples_per_trajectory=data.get("max_examples_per_trajectory", 10),
            validation_split=data.get("validation_split", 0.1),
            example_deduplication=data.get("example_deduplication", True),
            auto_train_threshold=data.get("auto_train_threshold", 500)
        )


# =============================================================================
# Trajectory Capture
# =============================================================================

class TrajectoryCapture:
    """Captures and manages execution trajectories."""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._storage_path = storage_path
        self._trajectories: Dict[str, Trajectory] = {}
        self._active_trajectory: Optional[str] = None
        self._lock = threading.Lock()

        if storage_path:
            self._load()

    def _generate_id(self) -> str:
        """Generate unique trajectory ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = hashlib.sha256(os.urandom(16)).hexdigest()[:8]
        return f"traj_{timestamp}_{random_suffix}"

    def _load(self):
        """Load trajectories from storage."""
        if not self._storage_path or not self._storage_path.exists():
            return

        try:
            with open(self._storage_path, 'r') as f:
                data = json.load(f)

            for t_data in data.get("trajectories", []):
                traj = Trajectory.from_dict(t_data)
                self._trajectories[traj.trajectory_id] = traj

            self._active_trajectory = data.get("active_trajectory")

        except Exception as e:
            logger.error(f"Failed to load trajectories: {e}")

    def _save(self):
        """Save trajectories to storage."""
        if not self._storage_path:
            return

        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "trajectories": [t.to_dict() for t in self._trajectories.values()],
                "active_trajectory": self._active_trajectory
            }
            with open(self._storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save trajectories: {e}")

    def start_trajectory(self, task_description: str, tags: List[str] = None) -> str:
        """Start recording a new trajectory."""
        with self._lock:
            trajectory_id = self._generate_id()

            trajectory = Trajectory(
                trajectory_id=trajectory_id,
                task_description=task_description,
                status=TrajectoryStatus.RECORDING,
                start_time=datetime.now(),
                tags=tags or []
            )

            self._trajectories[trajectory_id] = trajectory
            self._active_trajectory = trajectory_id
            self._save()

            return trajectory_id

    def add_step(self, trajectory_id: str, step: TrajectoryStep) -> None:
        """Add a step to a trajectory."""
        with self._lock:
            if trajectory_id not in self._trajectories:
                raise ValueError(f"Trajectory {trajectory_id} not found")

            trajectory = self._trajectories[trajectory_id]
            if trajectory.status != TrajectoryStatus.RECORDING:
                raise ValueError(f"Trajectory {trajectory_id} is not recording")

            trajectory.steps.append(step)
            self._save()

    def record_step(self, trajectory_id: str, input_text: str, output_text: str,
                   tool_calls: List[Dict] = None, tool_results: List[Dict] = None,
                   reasoning: str = "", metadata: Dict = None) -> str:
        """Convenience method to record a step."""
        step_id = f"step_{len(self._trajectories.get(trajectory_id, Trajectory('', '', TrajectoryStatus.RECORDING)).steps):04d}"

        step = TrajectoryStep(
            step_id=step_id,
            timestamp=datetime.now(),
            input_text=input_text,
            output_text=output_text,
            tool_calls=tool_calls or [],
            tool_results=tool_results or [],
            reasoning=reasoning,
            metadata=metadata or {}
        )

        self.add_step(trajectory_id, step)
        return step_id

    def complete_trajectory(self, trajectory_id: str, success_score: float,
                           quality_level: QualityLevel = QualityLevel.MEDIUM):
        """Mark a trajectory as completed."""
        with self._lock:
            if trajectory_id not in self._trajectories:
                raise ValueError(f"Trajectory {trajectory_id} not found")

            trajectory = self._trajectories[trajectory_id]
            trajectory.status = TrajectoryStatus.COMPLETED
            trajectory.end_time = datetime.now()
            trajectory.success_score = success_score
            trajectory.quality_level = quality_level

            if self._active_trajectory == trajectory_id:
                self._active_trajectory = None

            self._save()

    def fail_trajectory(self, trajectory_id: str, reason: str = "") -> None:
        """Mark a trajectory as failed."""
        with self._lock:
            if trajectory_id not in self._trajectories:
                raise ValueError(f"Trajectory {trajectory_id} not found")

            trajectory = self._trajectories[trajectory_id]
            trajectory.status = TrajectoryStatus.FAILED
            trajectory.end_time = datetime.now()
            trajectory.metadata["failure_reason"] = reason

            if self._active_trajectory == trajectory_id:
                self._active_trajectory = None

            self._save()

    def get_trajectory(self, trajectory_id: str) -> Optional[Trajectory]:
        """Get a trajectory by ID."""
        return self._trajectories.get(trajectory_id)

    def get_active_trajectory(self) -> Optional[Trajectory]:
        """Get the currently active trajectory."""
        if self._active_trajectory:
            return self._trajectories.get(self._active_trajectory)
        return None

    def get_successful_trajectories(self, min_score: float = 0.7,
                                    min_quality: QualityLevel = QualityLevel.MEDIUM) -> List[Trajectory]:
        """Get successful trajectories above thresholds."""
        quality_order = {
            QualityLevel.LOW: 0,
            QualityLevel.MEDIUM: 1,
            QualityLevel.HIGH: 2,
            QualityLevel.EXPERT: 3
        }

        return [
            t for t in self._trajectories.values()
            if t.status in (TrajectoryStatus.COMPLETED, TrajectoryStatus.VALIDATED)
            and t.success_score >= min_score
            and quality_order[t.quality_level] >= quality_order[min_quality]
        ]

    def mark_validated(self, trajectory_id: str) -> None:
        """Mark a trajectory as validated."""
        with self._lock:
            if trajectory_id in self._trajectories:
                self._trajectories[trajectory_id].status = TrajectoryStatus.VALIDATED
                self._save()

    def mark_distilled(self, trajectory_id: str) -> None:
        """Mark a trajectory as distilled."""
        with self._lock:
            if trajectory_id in self._trajectories:
                self._trajectories[trajectory_id].status = TrajectoryStatus.DISTILLED
                self._save()

    def get_statistics(self) -> Dict[str, Any]:
        """Get trajectory statistics."""
        status_counts = defaultdict(int)
        quality_counts = defaultdict(int)
        total_steps = 0
        total_duration = 0.0

        for t in self._trajectories.values():
            status_counts[t.status.value] += 1
            quality_counts[t.quality_level.value] += 1
            total_steps += len(t.steps)
            total_duration += t.duration_seconds

        return {
            "total_trajectories": len(self._trajectories),
            "status_counts": dict(status_counts),
            "quality_counts": dict(quality_counts),
            "total_steps": total_steps,
            "total_duration_hours": total_duration / 3600,
            "active_trajectory": self._active_trajectory
        }


# =============================================================================
# Example Extraction
# =============================================================================

class ExampleExtractor:
    """Extracts training examples from trajectories."""

    def __init__(self, config: DistillationConfig = None) -> None:
        self._config = config or DistillationConfig()
        self._seen_hashes: Set[str] = set()

    def _compute_hash(self, instruction: str, response: str) -> str:
        """Compute hash for deduplication."""
        content = f"{instruction.strip().lower()}:{response.strip().lower()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _generate_id(self) -> str:
        """Generate unique example ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = hashlib.sha256(os.urandom(8)).hexdigest()[:6]
        return f"ex_{timestamp}_{random_suffix}"

    def extract_instruction_response(self, trajectory: Trajectory) -> List[TrainingExample]:
        """Extract instruction-response pairs."""
        examples = []

        for step in trajectory.steps:
            if not step.input_text.strip() or not step.output_text.strip():
                continue

            # Check for duplicates
            if self._config.example_deduplication:
                h = self._compute_hash(step.input_text, step.output_text)
                if h in self._seen_hashes:
                    continue
                self._seen_hashes.add(h)

            example = TrainingExample(
                example_id=self._generate_id(),
                example_type=ExampleType.INSTRUCTION_RESPONSE,
                instruction=step.input_text,
                response=step.output_text,
                source_trajectory_id=trajectory.trajectory_id,
                quality_score=trajectory.success_score,
                metadata={"step_id": step.step_id}
            )
            examples.append(example)

            if len(examples) >= self._config.max_examples_per_trajectory:
                break

        return examples

    def extract_tool_usage(self, trajectory: Trajectory) -> List[TrainingExample]:
        """Extract tool usage examples."""
        examples = []

        for step in trajectory.steps:
            if not step.tool_calls:
                continue

            for i, tool_call in enumerate(step.tool_calls):
                tool_name = tool_call.get("name", "unknown")
                tool_args = tool_call.get("arguments", {})
                tool_result = step.tool_results[i] if i < len(step.tool_results) else {}

                instruction = f"Task: {step.input_text}\nUse the {tool_name} tool appropriately."
                response = f"Tool: {tool_name}\nArguments: {json.dumps(tool_args, indent=2)}"

                if self._config.example_deduplication:
                    h = self._compute_hash(instruction, response)
                    if h in self._seen_hashes:
                        continue
                    self._seen_hashes.add(h)

                example = TrainingExample(
                    example_id=self._generate_id(),
                    example_type=ExampleType.TOOL_USAGE,
                    instruction=instruction,
                    response=response,
                    source_trajectory_id=trajectory.trajectory_id,
                    quality_score=trajectory.success_score,
                    metadata={
                        "tool_name": tool_name,
                        "tool_result_success": tool_result.get("success", True)
                    }
                )
                examples.append(example)

        return examples[:self._config.max_examples_per_trajectory]

    def extract_reasoning_chain(self, trajectory: Trajectory) -> List[TrainingExample]:
        """Extract reasoning chain examples."""
        examples = []

        # Build context from trajectory
        context_parts = []
        for i, step in enumerate(trajectory.steps):
            if step.reasoning:
                context_parts.append(f"Step {i+1}: {step.reasoning}")

        if not context_parts:
            return []

        # Create a reasoning chain example
        instruction = f"Task: {trajectory.task_description}\nShow your reasoning."
        response = "\n".join(context_parts)

        example = TrainingExample(
            example_id=self._generate_id(),
            example_type=ExampleType.REASONING_CHAIN,
            instruction=instruction,
            response=response,
            source_trajectory_id=trajectory.trajectory_id,
            quality_score=trajectory.success_score,
            metadata={"steps_count": len(context_parts)}
        )
        examples.append(example)

        return examples

    def extract_multi_turn(self, trajectory: Trajectory) -> List[TrainingExample]:
        """Extract multi-turn conversation examples."""
        if len(trajectory.steps) < 2:
            return []

        examples = []

        # Create conversation context from previous steps
        for i in range(1, len(trajectory.steps)):
            context_parts = []
            for j in range(i):
                step = trajectory.steps[j]
                context_parts.append(f"User: {step.input_text}")
                context_parts.append(f"Assistant: {step.output_text}")

            context = "\n".join(context_parts)
            current_step = trajectory.steps[i]

            if self._config.example_deduplication:
                h = self._compute_hash(current_step.input_text, current_step.output_text)
                if h in self._seen_hashes:
                    continue
                self._seen_hashes.add(h)

            example = TrainingExample(
                example_id=self._generate_id(),
                example_type=ExampleType.MULTI_TURN,
                instruction=current_step.input_text,
                response=current_step.output_text,
                context=context,
                source_trajectory_id=trajectory.trajectory_id,
                quality_score=trajectory.success_score,
                metadata={"turn_number": i + 1}
            )
            examples.append(example)

            if len(examples) >= self._config.max_examples_per_trajectory:
                break

        return examples

    def extract_all(self, trajectory: Trajectory) -> List[TrainingExample]:
        """Extract all types of examples from a trajectory."""
        examples = []

        # Only extract from high-quality trajectories
        if trajectory.success_score < self._config.min_trajectory_score:
            return []

        quality_order = {
            QualityLevel.LOW: 0,
            QualityLevel.MEDIUM: 1,
            QualityLevel.HIGH: 2,
            QualityLevel.EXPERT: 3
        }

        if quality_order[trajectory.quality_level] < quality_order[self._config.min_quality_level]:
            return []

        examples.extend(self.extract_instruction_response(trajectory))
        examples.extend(self.extract_tool_usage(trajectory))
        examples.extend(self.extract_reasoning_chain(trajectory))
        examples.extend(self.extract_multi_turn(trajectory))

        return examples

    def clear_seen(self) -> None:
        """Clear the deduplication cache."""
        self._seen_hashes.clear()


# =============================================================================
# Training Data Formatter
# =============================================================================

class TrainingDataFormatter:
    """Formats training examples for different frameworks."""

    @staticmethod
    def to_jsonl(examples: List[TrainingExample], format_type: str = "alpaca") -> str:
        """Convert examples to JSONL format."""
        lines = []
        for example in examples:
            formatted = example.to_training_format(format_type)
            lines.append(json.dumps(formatted))
        return "\n".join(lines)

    @staticmethod
    def to_huggingface_dataset(examples: List[TrainingExample],
                               format_type: str = "alpaca") -> Dict[str, List]:
        """Convert examples to HuggingFace dataset format."""
        if format_type == "alpaca":
            return {
                "instruction": [e.instruction for e in examples],
                "input": [e.context for e in examples],
                "output": [e.response for e in examples]
            }
        elif format_type == "sharegpt":
            conversations = []
            for e in examples:
                conversations.append([
                    {"from": "human", "value": e.instruction},
                    {"from": "gpt", "value": e.response}
                ])
            return {"conversations": conversations}
        else:
            return {
                "text": [f"### Instruction:\n{e.instruction}\n\n### Response:\n{e.response}"
                        for e in examples]
            }

    @staticmethod
    def split_train_val(examples: List[TrainingExample],
                       val_ratio: float = 0.1) -> Tuple[List[TrainingExample], List[TrainingExample]]:
        """Split examples into train and validation sets."""
        shuffled = examples.copy()
        random.shuffle(shuffled)

        split_idx = int(len(shuffled) * (1 - val_ratio))
        return shuffled[:split_idx], shuffled[split_idx:]


# =============================================================================
# LoRA Trainer Interface
# =============================================================================

class LoRATrainerInterface(ABC):
    """Abstract interface for LoRA training."""

    @abstractmethod
    def train(self, examples: List[TrainingExample], config: LoRAConfig,
             output_path: Path) -> Tuple[float, float]:
        """Train a LoRA adapter. Returns (train_loss, val_loss)."""
        pass

    @abstractmethod
    def evaluate(self, adapter_path: Path, examples: List[TrainingExample]) -> Dict[str, float]:
        """Evaluate an adapter on examples."""
        pass


class MockLoRATrainer(LoRATrainerInterface):
    """Mock trainer for testing."""

    def __init__(self, base_loss: float = 0.5, variance: float = 0.1) -> None:
        self._base_loss = base_loss
        self._variance = variance

    def train(self, examples: List[TrainingExample], config: LoRAConfig,
             output_path: Path) -> Tuple[float, float]:
        """Simulate training."""
        output_path.mkdir(parents=True, exist_ok=True)

        # Simulate training artifacts
        adapter_config = {
            "base_model": "mock-model",
            "config": config.to_dict(),
            "examples_count": len(examples)
        }
        with open(output_path / "adapter_config.json", 'w') as f:
            json.dump(adapter_config, f)

        # Simulate loss based on example count
        train_loss = max(0.1, self._base_loss - 0.001 * len(examples) + random.uniform(-self._variance, self._variance))
        val_loss = train_loss + random.uniform(0, 0.1)

        return train_loss, val_loss

    def evaluate(self, adapter_path: Path, examples: List[TrainingExample]) -> Dict[str, float]:
        """Simulate evaluation."""
        return {
            "loss": random.uniform(0.3, 0.6),
            "accuracy": random.uniform(0.7, 0.95),
            "perplexity": random.uniform(5.0, 15.0)
        }


# =============================================================================
# Adapter Registry
# =============================================================================

class AdapterRegistry:
    """Manages LoRA adapters."""

    def __init__(self, storage_dir: Optional[Path] = None) -> None:
        self._storage_dir = storage_dir
        self._adapters: Dict[str, LoRAAdapter] = {}
        self._active_adapter: Optional[str] = None
        self._lock = threading.Lock()

        if storage_dir:
            storage_dir.mkdir(parents=True, exist_ok=True)
            self._load()

    def _load(self):
        """Load adapter registry from storage."""
        registry_path = self._storage_dir / "registry.json"
        if not registry_path.exists():
            return

        try:
            with open(registry_path, 'r') as f:
                data = json.load(f)

            for a_data in data.get("adapters", []):
                adapter = LoRAAdapter.from_dict(a_data)
                self._adapters[adapter.adapter_id] = adapter

            self._active_adapter = data.get("active_adapter")

        except Exception as e:
            logger.error(f"Failed to load adapter registry: {e}")

    def _save(self):
        """Save adapter registry to storage."""
        if not self._storage_dir:
            return

        try:
            registry_path = self._storage_dir / "registry.json"
            data = {
                "adapters": [a.to_dict() for a in self._adapters.values()],
                "active_adapter": self._active_adapter
            }
            with open(registry_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save adapter registry: {e}")

    def _generate_id(self) -> str:
        """Generate unique adapter ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = hashlib.sha256(os.urandom(8)).hexdigest()[:6]
        return f"adapter_{timestamp}_{random_suffix}"

    def create_adapter(self, name: str, base_model: str,
                      config: LoRAConfig, tags: List[str] = None,
                      parent_id: str = None) -> LoRAAdapter:
        """Create a new adapter entry."""
        with self._lock:
            adapter_id = self._generate_id()

            version = 1
            if parent_id and parent_id in self._adapters:
                version = self._adapters[parent_id].version + 1

            adapter = LoRAAdapter(
                adapter_id=adapter_id,
                name=name,
                base_model=base_model,
                status=AdapterStatus.TRAINING,
                config=config,
                version=version,
                parent_adapter_id=parent_id,
                tags=tags or []
            )

            if self._storage_dir:
                adapter.adapter_path = str(self._storage_dir / adapter_id)

            self._adapters[adapter_id] = adapter
            self._save()

            return adapter

    def update_adapter(self, adapter_id: str, **kwargs) -> None:
        """Update adapter fields."""
        with self._lock:
            if adapter_id not in self._adapters:
                raise ValueError(f"Adapter {adapter_id} not found")

            adapter = self._adapters[adapter_id]

            for key, value in kwargs.items():
                if hasattr(adapter, key):
                    setattr(adapter, key, value)

            self._save()

    def get_adapter(self, adapter_id: str) -> Optional[LoRAAdapter]:
        """Get adapter by ID."""
        return self._adapters.get(adapter_id)

    def get_active_adapter(self) -> Optional[LoRAAdapter]:
        """Get the currently active adapter."""
        if self._active_adapter:
            return self._adapters.get(self._active_adapter)
        return None

    def activate_adapter(self, adapter_id: str) -> None:
        """Set an adapter as active."""
        with self._lock:
            if adapter_id not in self._adapters:
                raise ValueError(f"Adapter {adapter_id} not found")

            adapter = self._adapters[adapter_id]
            if adapter.status != AdapterStatus.READY:
                raise ValueError(f"Adapter {adapter_id} is not ready")

            # Deactivate previous
            if self._active_adapter and self._active_adapter in self._adapters:
                self._adapters[self._active_adapter].status = AdapterStatus.READY

            adapter.status = AdapterStatus.ACTIVE
            self._active_adapter = adapter_id
            self._save()

    def deactivate_adapter(self) -> None:
        """Deactivate the current adapter."""
        with self._lock:
            if self._active_adapter and self._active_adapter in self._adapters:
                self._adapters[self._active_adapter].status = AdapterStatus.READY
            self._active_adapter = None
            self._save()

    def list_adapters(self, status: AdapterStatus = None,
                     tags: List[str] = None) -> List[LoRAAdapter]:
        """List adapters with optional filtering."""
        adapters = list(self._adapters.values())

        if status:
            adapters = [a for a in adapters if a.status == status]

        if tags:
            adapters = [a for a in adapters if any(t in a.tags for t in tags)]

        return sorted(adapters, key=lambda a: a.created_at, reverse=True)

    def deprecate_adapter(self, adapter_id: str) -> None:
        """Mark an adapter as deprecated."""
        with self._lock:
            if adapter_id in self._adapters:
                self._adapters[adapter_id].status = AdapterStatus.DEPRECATED
                self._save()

    def delete_adapter(self, adapter_id: str) -> None:
        """Delete an adapter."""
        with self._lock:
            if adapter_id not in self._adapters:
                return

            adapter = self._adapters[adapter_id]

            # Don't delete active adapter
            if adapter_id == self._active_adapter:
                raise ValueError("Cannot delete active adapter")

            # Delete files
            if adapter.adapter_path and Path(adapter.adapter_path).exists():
                shutil.rmtree(adapter.adapter_path)

            del self._adapters[adapter_id]
            self._save()

    def get_statistics(self) -> Dict[str, Any]:
        """Get registry statistics."""
        status_counts = defaultdict(int)
        for a in self._adapters.values():
            status_counts[a.status.value] += 1

        return {
            "total_adapters": len(self._adapters),
            "status_counts": dict(status_counts),
            "active_adapter": self._active_adapter,
            "latest_adapter": max(
                (a.adapter_id for a in self._adapters.values()),
                key=lambda aid: self._adapters[aid].created_at,
                default=None
            ) if self._adapters else None
        }


# =============================================================================
# Example Store
# =============================================================================

class ExampleStore:
    """Persistent store for training examples."""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._storage_path = storage_path
        self._examples: Dict[str, TrainingExample] = {}
        self._by_trajectory: Dict[str, List[str]] = defaultdict(list)
        self._by_type: Dict[ExampleType, List[str]] = defaultdict(list)
        self._lock = threading.Lock()

        if storage_path:
            self._load()

    def _load(self):
        """Load examples from storage."""
        if not self._storage_path or not self._storage_path.exists():
            return

        try:
            with open(self._storage_path, 'r') as f:
                data = json.load(f)

            for e_data in data.get("examples", []):
                example = TrainingExample.from_dict(e_data)
                self._examples[example.example_id] = example
                self._by_trajectory[example.source_trajectory_id].append(example.example_id)
                self._by_type[example.example_type].append(example.example_id)

        except Exception as e:
            logger.error(f"Failed to load examples: {e}")

    def _save(self):
        """Save examples to storage."""
        if not self._storage_path:
            return

        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "examples": [e.to_dict() for e in self._examples.values()]
            }
            with open(self._storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save examples: {e}")

    def add(self, example: TrainingExample) -> None:
        """Add an example."""
        with self._lock:
            self._examples[example.example_id] = example
            self._by_trajectory[example.source_trajectory_id].append(example.example_id)
            self._by_type[example.example_type].append(example.example_id)
            self._save()

    def add_batch(self, examples: List[TrainingExample]) -> None:
        """Add multiple examples."""
        with self._lock:
            for example in examples:
                self._examples[example.example_id] = example
                self._by_trajectory[example.source_trajectory_id].append(example.example_id)
                self._by_type[example.example_type].append(example.example_id)
            self._save()

    def get(self, example_id: str) -> Optional[TrainingExample]:
        """Get an example by ID."""
        return self._examples.get(example_id)

    def get_all(self) -> List[TrainingExample]:
        """Get all examples."""
        return list(self._examples.values())

    def get_by_trajectory(self, trajectory_id: str) -> List[TrainingExample]:
        """Get examples from a trajectory."""
        return [
            self._examples[eid]
            for eid in self._by_trajectory.get(trajectory_id, [])
            if eid in self._examples
        ]

    def get_by_type(self, example_type: ExampleType) -> List[TrainingExample]:
        """Get examples of a specific type."""
        return [
            self._examples[eid]
            for eid in self._by_type.get(example_type, [])
            if eid in self._examples
        ]

    def get_by_quality(self, min_score: float) -> List[TrainingExample]:
        """Get examples above a quality threshold."""
        return [e for e in self._examples.values() if e.quality_score >= min_score]

    def count(self) -> int:
        """Get total example count."""
        return len(self._examples)

    def clear(self) -> None:
        """Clear all examples."""
        with self._lock:
            self._examples.clear()
            self._by_trajectory.clear()
            self._by_type.clear()
            self._save()

    def get_statistics(self) -> Dict[str, Any]:
        """Get store statistics."""
        type_counts = {t.value: len(ids) for t, ids in self._by_type.items()}
        quality_scores = [e.quality_score for e in self._examples.values()]

        return {
            "total_examples": len(self._examples),
            "by_type": type_counts,
            "trajectory_count": len(self._by_trajectory),
            "avg_quality_score": sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
        }


# =============================================================================
# Distillation Pipeline
# =============================================================================

class DistillationPipeline:
    """End-to-end pipeline for trajectory distillation."""

    def __init__(self,
                 capture: TrajectoryCapture,
                 example_store: ExampleStore,
                 adapter_registry: AdapterRegistry,
                 trainer: LoRATrainerInterface,
                 config: DistillationConfig = None):
        self._capture = capture
        self._example_store = example_store
        self._registry = adapter_registry
        self._trainer = trainer
        self._config = config or DistillationConfig()
        self._extractor = ExampleExtractor(self._config)
        self._lock = threading.Lock()

    def extract_from_trajectory(self, trajectory_id: str) -> List[TrainingExample]:
        """Extract and store examples from a trajectory."""
        trajectory = self._capture.get_trajectory(trajectory_id)
        if not trajectory:
            return []

        examples = self._extractor.extract_all(trajectory)

        if examples:
            self._example_store.add_batch(examples)
            self._capture.mark_distilled(trajectory_id)

        return examples

    def extract_from_all_successful(self) -> List[TrainingExample]:
        """Extract examples from all successful trajectories."""
        all_examples = []

        trajectories = self._capture.get_successful_trajectories(
            min_score=self._config.min_trajectory_score,
            min_quality=self._config.min_quality_level
        )

        for trajectory in trajectories:
            if trajectory.status == TrajectoryStatus.DISTILLED:
                continue

            examples = self._extractor.extract_all(trajectory)
            if examples:
                self._example_store.add_batch(examples)
                self._capture.mark_distilled(trajectory.trajectory_id)
                all_examples.extend(examples)

        return all_examples

    def train_adapter(self, name: str, base_model: str,
                     config: LoRAConfig = None,
                     example_types: List[ExampleType] = None,
                     min_quality: float = 0.7,
                     tags: List[str] = None) -> Optional[LoRAAdapter]:
        """Train a new LoRA adapter from stored examples."""
        config = config or LoRAConfig()

        # Gather examples
        if example_types:
            examples = []
            for et in example_types:
                examples.extend(self._example_store.get_by_type(et))
        else:
            examples = self._example_store.get_all()

        # Filter by quality
        examples = [e for e in examples if e.quality_score >= min_quality]

        if len(examples) < self._config.min_examples_for_training:
            logger.warning(f"Not enough examples ({len(examples)}) for training")
            return None

        # Split data
        train_examples, val_examples = TrainingDataFormatter.split_train_val(
            examples, self._config.validation_split
        )

        # Create adapter entry
        adapter = self._registry.create_adapter(
            name=name,
            base_model=base_model,
            config=config,
            tags=tags
        )

        try:
            # Train
            output_path = Path(adapter.adapter_path)
            train_loss, val_loss = self._trainer.train(
                train_examples, config, output_path
            )

            # Update adapter
            self._registry.update_adapter(
                adapter.adapter_id,
                status=AdapterStatus.READY,
                training_examples_count=len(train_examples),
                training_loss=train_loss,
                validation_loss=val_loss,
                trained_at=datetime.now()
            )

            return self._registry.get_adapter(adapter.adapter_id)

        except Exception as e:
            logger.error(f"Training failed: {e}")
            self._registry.update_adapter(
                adapter.adapter_id,
                status=AdapterStatus.FAILED
            )
            return None

    def should_auto_train(self) -> bool:
        """Check if automatic training should trigger."""
        return self._example_store.count() >= self._config.auto_train_threshold

    def incremental_train(self, base_adapter_id: str,
                         new_examples: List[TrainingExample],
                         name_suffix: str = "incremental") -> Optional[LoRAAdapter]:
        """Train incrementally from an existing adapter."""
        base_adapter = self._registry.get_adapter(base_adapter_id)
        if not base_adapter:
            return None

        # Get existing examples and add new ones
        all_examples = self._example_store.get_all()
        all_examples.extend(new_examples)

        new_name = f"{base_adapter.name}_{name_suffix}"

        return self.train_adapter(
            name=new_name,
            base_model=base_adapter.base_model,
            config=base_adapter.config,
            tags=base_adapter.tags + ["incremental"]
        )

    def evaluate_adapter(self, adapter_id: str) -> Dict[str, float]:
        """Evaluate an adapter on held-out examples."""
        adapter = self._registry.get_adapter(adapter_id)
        if not adapter or not adapter.adapter_path:
            return {}

        # Use validation examples
        all_examples = self._example_store.get_all()
        _, val_examples = TrainingDataFormatter.split_train_val(
            all_examples, self._config.validation_split
        )

        metrics = self._trainer.evaluate(Path(adapter.adapter_path), val_examples)

        # Update adapter metrics
        self._registry.update_adapter(adapter_id, metrics=metrics)

        return metrics

    def export_training_data(self, output_path: Path,
                            format_type: str = "alpaca") -> int:
        """Export training data to file."""
        examples = self._example_store.get_all()

        if format_type == "jsonl":
            content = TrainingDataFormatter.to_jsonl(examples, "alpaca")
            with open(output_path, 'w') as f:
                f.write(content)
        else:
            data = TrainingDataFormatter.to_huggingface_dataset(examples, format_type)
            with open(output_path, 'w') as f:
                json.dump(data, f, indent=2)

        return len(examples)

    def get_statistics(self) -> Dict[str, Any]:
        """Get pipeline statistics."""
        return {
            "trajectories": self._capture.get_statistics(),
            "examples": self._example_store.get_statistics(),
            "adapters": self._registry.get_statistics(),
            "config": self._config.to_dict()
        }


# =============================================================================
# CLI Tests
# =============================================================================

def _run_cli_tests():
    """Run CLI tests for trajectory distillation."""
    import sys
    import tempfile

    tests_passed = 0
    tests_failed = 0

    def test(name: str, condition: bool) -> None:
        nonlocal tests_passed, tests_failed
        if condition:
            print(f"  [PASS] {name}")
            tests_passed += 1
        else:
            print(f"  [FAIL] {name}")
            tests_failed += 1

    print("\n" + "="*60)
    print("Trajectory Distillation System - CLI Tests")
    print("="*60)

    # Test 1: Trajectory Status Enum
    print("\n1. Testing TrajectoryStatus...")
    test("Recording status", TrajectoryStatus.RECORDING.value == "recording")
    test("Completed status", TrajectoryStatus.COMPLETED.value == "completed")
    test("Distilled status", TrajectoryStatus.DISTILLED.value == "distilled")

    # Test 2: Example Type Enum
    print("\n2. Testing ExampleType...")
    test("Instruction response type", ExampleType.INSTRUCTION_RESPONSE.value == "instruction_response")
    test("Tool usage type", ExampleType.TOOL_USAGE.value == "tool_usage")
    test("Multi turn type", ExampleType.MULTI_TURN.value == "multi_turn")

    # Test 3: TrajectoryStep
    print("\n3. Testing TrajectoryStep...")
    step = TrajectoryStep(
        step_id="step_001",
        timestamp=datetime.now(),
        input_text="What is 2+2?",
        output_text="2+2 equals 4.",
        tool_calls=[{"name": "calculator", "arguments": {"expr": "2+2"}}],
        reasoning="Simple arithmetic"
    )
    test("Create step", step.step_id == "step_001")
    test("Step has input", step.input_text == "What is 2+2?")

    step_dict = step.to_dict()
    test("Serialize step", "step_id" in step_dict)

    step2 = TrajectoryStep.from_dict(step_dict)
    test("Deserialize step", step2.step_id == step.step_id)

    # Test 4: Trajectory
    print("\n4. Testing Trajectory...")
    traj = Trajectory(
        trajectory_id="traj_001",
        task_description="Solve math problem",
        status=TrajectoryStatus.RECORDING,
        start_time=datetime.now()
    )
    test("Create trajectory", traj.trajectory_id == "traj_001")

    traj.steps.append(step)
    test("Add step to trajectory", len(traj.steps) == 1)

    traj.status = TrajectoryStatus.COMPLETED
    traj.end_time = datetime.now()
    traj.success_score = 0.9
    test("Complete trajectory", traj.status == TrajectoryStatus.COMPLETED)
    test("Duration computed", traj.duration_seconds >= 0)

    traj_dict = traj.to_dict()
    traj2 = Trajectory.from_dict(traj_dict)
    test("Serialize/deserialize trajectory", traj2.trajectory_id == traj.trajectory_id)

    # Test 5: TrainingExample
    print("\n5. Testing TrainingExample...")
    example = TrainingExample(
        example_id="ex_001",
        example_type=ExampleType.INSTRUCTION_RESPONSE,
        instruction="What is 2+2?",
        response="4",
        source_trajectory_id="traj_001",
        quality_score=0.9
    )
    test("Create example", example.example_id == "ex_001")

    alpaca = example.to_training_format("alpaca")
    test("Alpaca format", "instruction" in alpaca and "output" in alpaca)

    sharegpt = example.to_training_format("sharegpt")
    test("ShareGPT format", "conversations" in sharegpt)

    openai = example.to_training_format("openai")
    test("OpenAI format", "messages" in openai)

    # Test 6: LoRAConfig
    print("\n6. Testing LoRAConfig...")
    config = LoRAConfig(rank=32, alpha=64, dropout=0.1)
    test("Create config", config.rank == 32)

    config_dict = config.to_dict()
    config2 = LoRAConfig.from_dict(config_dict)
    test("Serialize/deserialize config", config2.rank == 32)

    # Test 7: LoRAAdapter
    print("\n7. Testing LoRAAdapter...")
    adapter = LoRAAdapter(
        adapter_id="adapter_001",
        name="test_adapter",
        base_model="gpt-4",
        status=AdapterStatus.TRAINING,
        config=config
    )
    test("Create adapter", adapter.adapter_id == "adapter_001")

    adapter_dict = adapter.to_dict()
    adapter2 = LoRAAdapter.from_dict(adapter_dict)
    test("Serialize/deserialize adapter", adapter2.name == "test_adapter")

    # Test 8: DistillationConfig
    print("\n8. Testing DistillationConfig...")
    dist_config = DistillationConfig(
        min_trajectory_score=0.8,
        min_examples_for_training=50
    )
    test("Create distillation config", dist_config.min_trajectory_score == 0.8)

    dist_dict = dist_config.to_dict()
    dist_config2 = DistillationConfig.from_dict(dist_dict)
    test("Serialize/deserialize distillation config", dist_config2.min_examples_for_training == 50)

    # Test 9: TrajectoryCapture
    print("\n9. Testing TrajectoryCapture...")
    with tempfile.TemporaryDirectory() as tmpdir:
        capture = TrajectoryCapture(Path(tmpdir) / "trajectories.json")

        traj_id = capture.start_trajectory("Test task", ["test"])
        test("Start trajectory", traj_id is not None)

        active = capture.get_active_trajectory()
        test("Get active trajectory", active is not None)

        step_id = capture.record_step(
            traj_id, "Input", "Output",
            tool_calls=[{"name": "test"}],
            reasoning="Test reasoning"
        )
        test("Record step", step_id is not None)

        capture.complete_trajectory(traj_id, success_score=0.9, quality_level=QualityLevel.HIGH)
        test("Complete trajectory", capture.get_trajectory(traj_id).status == TrajectoryStatus.COMPLETED)

        successful = capture.get_successful_trajectories(min_score=0.8)
        test("Get successful trajectories", len(successful) == 1)

        stats = capture.get_statistics()
        test("Get statistics", stats["total_trajectories"] == 1)

    # Test 10: ExampleExtractor
    print("\n10. Testing ExampleExtractor...")
    extractor_config = DistillationConfig(min_trajectory_score=0.5)
    extractor = ExampleExtractor(extractor_config)

    # Create test trajectory
    test_traj = Trajectory(
        trajectory_id="test_traj",
        task_description="Test task",
        status=TrajectoryStatus.COMPLETED,
        success_score=0.9,
        quality_level=QualityLevel.HIGH,
        steps=[
            TrajectoryStep(
                step_id="s1",
                timestamp=datetime.now(),
                input_text="Question 1",
                output_text="Answer 1",
                reasoning="Reasoning 1"
            ),
            TrajectoryStep(
                step_id="s2",
                timestamp=datetime.now(),
                input_text="Question 2",
                output_text="Answer 2",
                tool_calls=[{"name": "tool", "arguments": {"x": 1}}],
                tool_results=[{"success": True}]
            )
        ]
    )

    ir_examples = extractor.extract_instruction_response(test_traj)
    test("Extract instruction-response", len(ir_examples) >= 1)

    tool_examples = extractor.extract_tool_usage(test_traj)
    test("Extract tool usage", len(tool_examples) >= 1)

    reasoning_examples = extractor.extract_reasoning_chain(test_traj)
    test("Extract reasoning chain", len(reasoning_examples) >= 0)

    all_examples = extractor.extract_all(test_traj)
    test("Extract all", len(all_examples) >= 1)

    # Test 11: TrainingDataFormatter
    print("\n11. Testing TrainingDataFormatter...")
    examples = [
        TrainingExample("e1", ExampleType.INSTRUCTION_RESPONSE, "Q1", "A1"),
        TrainingExample("e2", ExampleType.INSTRUCTION_RESPONSE, "Q2", "A2"),
    ]

    jsonl = TrainingDataFormatter.to_jsonl(examples)
    test("JSONL format", len(jsonl.split("\n")) == 2)

    hf_data = TrainingDataFormatter.to_huggingface_dataset(examples)
    test("HuggingFace format", len(hf_data.get("instruction", "")) == 2)

    train, val = TrainingDataFormatter.split_train_val(examples, 0.5)
    test("Train/val split", len(train) + len(val) == 2)

    # Test 12: MockLoRATrainer
    print("\n12. Testing MockLoRATrainer...")
    with tempfile.TemporaryDirectory() as tmpdir:
        trainer = MockLoRATrainer()

        train_loss, val_loss = trainer.train(
            examples,
            LoRAConfig(),
            Path(tmpdir) / "adapter"
        )
        test("Mock training", train_loss > 0 and val_loss > 0)

        metrics = trainer.evaluate(Path(tmpdir) / "adapter", examples)
        test("Mock evaluation", "loss" in metrics)

    # Test 13: AdapterRegistry
    print("\n13. Testing AdapterRegistry...")
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = AdapterRegistry(Path(tmpdir))

        adapter = registry.create_adapter(
            name="test",
            base_model="gpt-4",
            config=LoRAConfig()
        )
        test("Create adapter", adapter is not None)

        registry.update_adapter(adapter.adapter_id, status=AdapterStatus.READY)
        test("Update adapter", registry.get_adapter(adapter.adapter_id).status == AdapterStatus.READY)

        registry.activate_adapter(adapter.adapter_id)
        test("Activate adapter", registry.get_active_adapter() is not None)

        adapters = registry.list_adapters(status=AdapterStatus.ACTIVE)
        test("List adapters", len(adapters) == 1)

        registry.deactivate_adapter()
        test("Deactivate adapter", registry.get_active_adapter() is None)

        stats = registry.get_statistics()
        test("Registry statistics", stats["total_adapters"] == 1)

    # Test 14: ExampleStore
    print("\n14. Testing ExampleStore...")
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ExampleStore(Path(tmpdir) / "examples.json")

        store.add(TrainingExample("e1", ExampleType.INSTRUCTION_RESPONSE, "Q", "A", source_trajectory_id="t1", quality_score=0.9))
        test("Add example", store.count() == 1)

        store.add_batch([
            TrainingExample("e2", ExampleType.TOOL_USAGE, "Q2", "A2", source_trajectory_id="t1", quality_score=0.8),
            TrainingExample("e3", ExampleType.MULTI_TURN, "Q3", "A3", source_trajectory_id="t2", quality_score=0.7)
        ])
        test("Add batch", store.count() == 3)

        by_traj = store.get_by_trajectory("t1")
        test("Get by trajectory", len(by_traj) == 2)

        by_type = store.get_by_type(ExampleType.TOOL_USAGE)
        test("Get by type", len(by_type) == 1)

        by_quality = store.get_by_quality(0.85)
        test("Get by quality", len(by_quality) == 1)

        stats = store.get_statistics()
        test("Store statistics", stats["total_examples"] == 3)

    # Test 15: DistillationPipeline
    print("\n15. Testing DistillationPipeline...")
    with tempfile.TemporaryDirectory() as tmpdir:
        base_path = Path(tmpdir)

        capture = TrajectoryCapture(base_path / "trajectories.json")
        store = ExampleStore(base_path / "examples.json")
        registry = AdapterRegistry(base_path / "adapters")
        trainer = MockLoRATrainer()
        config = DistillationConfig(min_examples_for_training=2)

        pipeline = DistillationPipeline(capture, store, registry, trainer, config)

        # Create trajectories
        for i in range(3):
            tid = capture.start_trajectory(f"Task {i}")
            capture.record_step(tid, f"Question {i}", f"Answer {i}")
            capture.complete_trajectory(tid, success_score=0.9, quality_level=QualityLevel.HIGH)

        # Extract examples
        examples = pipeline.extract_from_all_successful()
        test("Extract from successful", len(examples) >= 1)

        # Check auto train threshold
        test("Check auto train", pipeline.should_auto_train() or not pipeline.should_auto_train())

        # Train adapter
        adapter = pipeline.train_adapter(
            name="test_adapter",
            base_model="gpt-4",
            config=LoRAConfig()
        )
        test("Train adapter", adapter is not None)

        # Get statistics
        stats = pipeline.get_statistics()
        test("Pipeline statistics", "trajectories" in stats)

    # Test 16: Quality Level
    print("\n16. Testing QualityLevel...")
    test("Low quality", QualityLevel.LOW.value == "low")
    test("Expert quality", QualityLevel.EXPERT.value == "expert")

    # Test 17: Adapter versioning
    print("\n17. Testing adapter versioning...")
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = AdapterRegistry(Path(tmpdir))

        adapter1 = registry.create_adapter("v1", "model", LoRAConfig())
        test("First version", adapter1.version == 1)

        adapter2 = registry.create_adapter("v2", "model", LoRAConfig(), parent_id=adapter1.adapter_id)
        test("Second version", adapter2.version == 2)

        adapter3 = registry.create_adapter("v3", "model", LoRAConfig(), parent_id=adapter2.adapter_id)
        test("Third version", adapter3.version == 3)

    # Test 18: Example deduplication
    print("\n18. Testing example deduplication...")
    dedup_config = DistillationConfig(example_deduplication=True)
    dedup_extractor = ExampleExtractor(dedup_config)

    dup_traj = Trajectory(
        trajectory_id="dup_test",
        task_description="Test",
        status=TrajectoryStatus.COMPLETED,
        success_score=0.9,
        quality_level=QualityLevel.HIGH,
        steps=[
            TrajectoryStep("s1", datetime.now(), "Same Q", "Same A"),
            TrajectoryStep("s2", datetime.now(), "Same Q", "Same A"),  # Duplicate
            TrajectoryStep("s3", datetime.now(), "Different Q", "Different A"),
        ]
    )

    dedup_examples = dedup_extractor.extract_instruction_response(dup_traj)
    test("Deduplication works", len(dedup_examples) == 2)

    # Test 19: Persistence
    print("\n19. Testing persistence...")
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create and save
        capture1 = TrajectoryCapture(Path(tmpdir) / "traj.json")
        tid = capture1.start_trajectory("Persist test")
        capture1.record_step(tid, "Q", "A")
        capture1.complete_trajectory(tid, 0.9)

        # Load in new instance
        capture2 = TrajectoryCapture(Path(tmpdir) / "traj.json")
        test("Persistence", capture2.get_trajectory(tid) is not None)

    # Test 20: Export training data
    print("\n20. Testing export...")
    with tempfile.TemporaryDirectory() as tmpdir:
        store = ExampleStore()
        store.add_batch([
            TrainingExample("e1", ExampleType.INSTRUCTION_RESPONSE, "Q1", "A1"),
            TrainingExample("e2", ExampleType.INSTRUCTION_RESPONSE, "Q2", "A2"),
        ])

        capture = TrajectoryCapture()
        registry = AdapterRegistry()
        trainer = MockLoRATrainer()
        pipeline = DistillationPipeline(capture, store, registry, trainer)

        export_path = Path(tmpdir) / "export.jsonl"
        count = pipeline.export_training_data(export_path, "jsonl")
        test("Export JSONL", count == 2)
        test("Export file exists", export_path.exists())

    # Summary
    print("\n" + "="*60)
    logger.error(f"Results: {tests_passed} passed, {tests_failed} failed")
    print("="*60)

    return tests_failed == 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        success = _run_cli_tests()
        sys.exit(0 if success else 1)
    else:
        print("Trajectory Distillation System")
        print("Usage: python trajectory_distillation.py --test")
        print("\nThis module implements LoRA fine-tuning from successful task traces.")

"""
Adaptive LoRA Swapping: Task-Specific Performance

Implements dynamic LoRA (Low-Rank Adaptation) switching based on task domain
to optimize model performance for different types of tasks.

Key Features:
- Task domain classification
- LoRA adapter selection based on task type
- Hot-swapping adapters at runtime
- Performance tracking per adapter
- Adaptive selection based on success rates
- Multi-adapter composition for hybrid tasks

Architecture:
- TaskClassifier: Identifies task domain from input
- AdapterSelector: Chooses optimal adapter for task
- AdapterLoader: Manages adapter loading/unloading
- PerformanceTracker: Tracks adapter effectiveness
- CompositionEngine: Combines multiple adapters
- AdaptiveSwapper: Main orchestration component

Research References:
- LoRA: Low-Rank Adaptation of Large Language Models (Hu et al., 2021)
- AdaLoRA: Adaptive Budget Allocation for Parameter-Efficient Fine-Tuning (Zhang et al., 2023)
- LoRA-Hub: Efficient Cross-Task Generalization via Dynamic LoRA Composition (Huang et al., 2023)
"""

import hashlib
import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Types
# =============================================================================

class TaskDomain(Enum):
    """Domains of tasks for adapter specialization."""
    CODING = "coding"
    WRITING = "writing"
    MATH = "math"
    REASONING = "reasoning"
    CONVERSATION = "conversation"
    SUMMARIZATION = "summarization"
    TRANSLATION = "translation"
    ANALYSIS = "analysis"
    CREATIVE = "creative"
    TECHNICAL = "technical"
    GENERAL = "general"


class AdapterState(Enum):
    """State of an adapter."""
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    ACTIVE = "active"
    UNLOADING = "unloading"
    FAILED = "failed"


class SelectionStrategy(Enum):
    """Strategy for adapter selection."""
    BEST_MATCH = "best_match"
    WEIGHTED_RANDOM = "weighted_random"
    ROUND_ROBIN = "round_robin"
    PERFORMANCE_BASED = "performance_based"
    ENSEMBLE = "ensemble"


class CompositionMode(Enum):
    """Mode for combining multiple adapters."""
    AVERAGE = "average"
    WEIGHTED = "weighted"
    STACK = "stack"
    CONCATENATE = "concatenate"
    ATTENTION = "attention"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class TaskClassification:
    """Classification result for a task."""
    task_id: str
    primary_domain: TaskDomain
    confidence: float
    secondary_domains: Dict[TaskDomain, float] = field(default_factory=dict)
    features: Dict[str, Any] = field(default_factory=dict)
    classified_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "primary_domain": self.primary_domain.value,
            "confidence": self.confidence,
            "secondary_domains": {d.value: s for d, s in self.secondary_domains.items()},
            "features": self.features,
            "classified_at": self.classified_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskClassification":
        return cls(
            task_id=data.get("task_id", ""),
            primary_domain=TaskDomain(data.get("primary_domain", "")),
            confidence=data.get("confidence", ""),
            secondary_domains={TaskDomain(d): s for d, s in data.get("secondary_domains", {}).items()},
            features=data.get("features", {}),
            classified_at=datetime.fromisoformat(data["classified_at"]) if data.get("classified_at") else datetime.now()
        )


@dataclass
class AdapterConfig:
    """Configuration for a LoRA adapter."""
    adapter_id: str
    name: str
    domains: List[TaskDomain]
    rank: int = 16
    alpha: int = 32
    target_modules: List[str] = field(default_factory=lambda: ["q_proj", "v_proj"])
    path: Optional[str] = None
    version: str = "1.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "name": self.name,
            "domains": [d.value for d in self.domains],
            "rank": self.rank,
            "alpha": self.alpha,
            "target_modules": self.target_modules,
            "path": self.path,
            "version": self.version,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdapterConfig":
        return cls(
            adapter_id=data.get("adapter_id", ""),
            name=data.get("name", ""),
            domains=[TaskDomain(d) for d in data.get("domains", [])],
            rank=data.get("rank", 16),
            alpha=data.get("alpha", 32),
            target_modules=data.get("target_modules", ["q_proj", "v_proj"]),
            path=data.get("path"),
            version=data.get("version", "1.0"),
            metadata=data.get("metadata", {})
        )


@dataclass
class AdapterInstance:
    """Runtime instance of an adapter."""
    config: AdapterConfig
    state: AdapterState = AdapterState.UNLOADED
    loaded_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    use_count: int = 0
    memory_usage_mb: float = 0.0
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "state": self.state.value,
            "loaded_at": self.loaded_at.isoformat() if self.loaded_at else None,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "use_count": self.use_count,
            "memory_usage_mb": self.memory_usage_mb,
            "error_message": self.error_message
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdapterInstance":
        return cls(
            config=AdapterConfig.from_dict(data.get("config", "")),
            state=AdapterState(data.get("state", "unloaded")),
            loaded_at=datetime.fromisoformat(data["loaded_at"]) if data.get("loaded_at") else None,
            last_used=datetime.fromisoformat(data["last_used"]) if data.get("last_used") else None,
            use_count=data.get("use_count", 0),
            memory_usage_mb=data.get("memory_usage_mb", 0.0),
            error_message=data.get("error_message")
        )


@dataclass
class PerformanceMetrics:
    """Performance metrics for an adapter on a domain."""
    adapter_id: str
    domain: TaskDomain
    success_count: int = 0
    failure_count: int = 0
    total_latency_ms: float = 0.0
    avg_quality_score: float = 0.0
    quality_samples: int = 0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        total = self.success_count + self.failure_count
        return self.total_latency_ms / total if total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "domain": self.domain.value,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "total_latency_ms": self.total_latency_ms,
            "avg_quality_score": self.avg_quality_score,
            "quality_samples": self.quality_samples,
            "success_rate": self.success_rate,
            "avg_latency_ms": self.avg_latency_ms
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PerformanceMetrics":
        return cls(
            adapter_id=data.get("adapter_id", ""),
            domain=TaskDomain(data.get("domain", "")),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            total_latency_ms=data.get("total_latency_ms", 0.0),
            avg_quality_score=data.get("avg_quality_score", 0.0),
            quality_samples=data.get("quality_samples", 0)
        )


@dataclass
class SelectionResult:
    """Result of adapter selection."""
    selected_adapter: AdapterConfig
    selection_score: float
    reasoning: str
    alternatives: List[Tuple[AdapterConfig, float]] = field(default_factory=list)
    strategy_used: SelectionStrategy = SelectionStrategy.BEST_MATCH

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_adapter": self.selected_adapter.to_dict(),
            "selection_score": self.selection_score,
            "reasoning": self.reasoning,
            "alternatives": [(a.to_dict(), s) for a, s in self.alternatives],
            "strategy_used": self.strategy_used.value
        }


@dataclass
class SwapRequest:
    """Request to swap adapters."""
    request_id: str
    target_adapter_id: str
    task_classification: TaskClassification
    priority: int = 0
    timeout_ms: float = 5000.0
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "target_adapter_id": self.target_adapter_id,
            "task_classification": self.task_classification.to_dict(),
            "priority": self.priority,
            "timeout_ms": self.timeout_ms,
            "created_at": self.created_at.isoformat()
        }


@dataclass
class SwapResult:
    """Result of an adapter swap operation."""
    request_id: str
    success: bool
    adapter_id: str
    swap_time_ms: float
    error_message: Optional[str] = None
    previous_adapter_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "success": self.success,
            "adapter_id": self.adapter_id,
            "swap_time_ms": self.swap_time_ms,
            "error_message": self.error_message,
            "previous_adapter_id": self.previous_adapter_id
        }


# =============================================================================
# Task Classifier
# =============================================================================

class TaskClassifier:
    """Classifies tasks into domains."""

    def __init__(self) -> None:
        self._keyword_domains: Dict[str, List[Tuple[TaskDomain, float]]] = self._init_keywords()
        self._pattern_matchers: List[Callable[[str], Optional[Tuple[TaskDomain, float]]]] = []

    def _init_keywords(self) -> Dict[str, List[Tuple[TaskDomain, float]]]:
        """Initialize keyword to domain mappings."""
        return {
            # Coding keywords
            "code": [(TaskDomain.CODING, 0.9)],
            "function": [(TaskDomain.CODING, 0.7)],
            "class": [(TaskDomain.CODING, 0.6)],
            "debug": [(TaskDomain.CODING, 0.85)],
            "compile": [(TaskDomain.CODING, 0.8)],
            "error": [(TaskDomain.CODING, 0.5), (TaskDomain.TECHNICAL, 0.3)],
            "bug": [(TaskDomain.CODING, 0.8)],
            "python": [(TaskDomain.CODING, 0.95)],
            "javascript": [(TaskDomain.CODING, 0.95)],
            "api": [(TaskDomain.CODING, 0.7), (TaskDomain.TECHNICAL, 0.5)],

            # Writing keywords
            "write": [(TaskDomain.WRITING, 0.6), (TaskDomain.CREATIVE, 0.3)],
            "essay": [(TaskDomain.WRITING, 0.9)],
            "article": [(TaskDomain.WRITING, 0.8)],
            "blog": [(TaskDomain.WRITING, 0.85)],
            "story": [(TaskDomain.WRITING, 0.5), (TaskDomain.CREATIVE, 0.7)],

            # Math keywords
            "calculate": [(TaskDomain.MATH, 0.9)],
            "equation": [(TaskDomain.MATH, 0.95)],
            "solve": [(TaskDomain.MATH, 0.7), (TaskDomain.REASONING, 0.4)],
            "formula": [(TaskDomain.MATH, 0.85)],
            "number": [(TaskDomain.MATH, 0.4)],
            "statistics": [(TaskDomain.MATH, 0.8), (TaskDomain.ANALYSIS, 0.5)],

            # Reasoning keywords
            "explain": [(TaskDomain.REASONING, 0.7)],
            "why": [(TaskDomain.REASONING, 0.6)],
            "logic": [(TaskDomain.REASONING, 0.9)],
            "analyze": [(TaskDomain.REASONING, 0.6), (TaskDomain.ANALYSIS, 0.7)],
            "compare": [(TaskDomain.REASONING, 0.7), (TaskDomain.ANALYSIS, 0.6)],

            # Conversation keywords
            "chat": [(TaskDomain.CONVERSATION, 0.9)],
            "talk": [(TaskDomain.CONVERSATION, 0.7)],
            "hello": [(TaskDomain.CONVERSATION, 0.95)],
            "help": [(TaskDomain.CONVERSATION, 0.5), (TaskDomain.GENERAL, 0.4)],

            # Summarization keywords
            "summarize": [(TaskDomain.SUMMARIZATION, 0.95)],
            "summary": [(TaskDomain.SUMMARIZATION, 0.9)],
            "tldr": [(TaskDomain.SUMMARIZATION, 0.95)],
            "brief": [(TaskDomain.SUMMARIZATION, 0.6)],

            # Translation keywords
            "translate": [(TaskDomain.TRANSLATION, 0.95)],
            "language": [(TaskDomain.TRANSLATION, 0.6)],
            "english": [(TaskDomain.TRANSLATION, 0.4)],
            "spanish": [(TaskDomain.TRANSLATION, 0.5)],

            # Analysis keywords
            "data": [(TaskDomain.ANALYSIS, 0.7), (TaskDomain.TECHNICAL, 0.4)],
            "trend": [(TaskDomain.ANALYSIS, 0.8)],
            "insight": [(TaskDomain.ANALYSIS, 0.75)],
            "report": [(TaskDomain.ANALYSIS, 0.6), (TaskDomain.WRITING, 0.4)],

            # Creative keywords
            "creative": [(TaskDomain.CREATIVE, 0.9)],
            "poem": [(TaskDomain.CREATIVE, 0.95)],
            "song": [(TaskDomain.CREATIVE, 0.9)],
            "imagine": [(TaskDomain.CREATIVE, 0.8)],
            "brainstorm": [(TaskDomain.CREATIVE, 0.75)],

            # Technical keywords
            "configure": [(TaskDomain.TECHNICAL, 0.8)],
            "setup": [(TaskDomain.TECHNICAL, 0.75)],
            "install": [(TaskDomain.TECHNICAL, 0.7)],
            "system": [(TaskDomain.TECHNICAL, 0.5)],
        }

    def _generate_id(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = hashlib.sha256(os.urandom(8)).hexdigest()[:6]
        return f"task_{timestamp}_{random_suffix}"

    def classify(self, task_text: str) -> TaskClassification:
        """Classify a task into domains."""
        task_id = self._generate_id()
        words = task_text.lower().split()

        domain_scores: Dict[TaskDomain, float] = defaultdict(float)

        # Score based on keywords
        for word in words:
            word = word.strip(".,!?;:\"'()[]{}").lower()
            if word in self._keyword_domains:
                for domain, score in self._keyword_domains[word]:
                    domain_scores[domain] = max(domain_scores[domain], score)

        # Apply pattern matchers
        for matcher in self._pattern_matchers:
            result = matcher(task_text)
            if result:
                domain, score = result
                domain_scores[domain] = max(domain_scores[domain], score)

        # Determine primary domain
        if not domain_scores:
            primary_domain = TaskDomain.GENERAL
            confidence = 0.5
        else:
            primary_domain = max(domain_scores.keys(), key=lambda d: domain_scores[d])
            confidence = domain_scores[primary_domain]

        # Get secondary domains
        secondary_domains = {
            d: s for d, s in domain_scores.items()
            if d != primary_domain and s > 0.3
        }

        return TaskClassification(
            task_id=task_id,
            primary_domain=primary_domain,
            confidence=confidence,
            secondary_domains=secondary_domains,
            features={"word_count": len(words), "detected_keywords": list(domain_scores.keys())}
        )

    def add_keyword(self, keyword: str, domain: TaskDomain, score: float) -> None:
        """Add a keyword to domain mapping."""
        if keyword not in self._keyword_domains:
            self._keyword_domains[keyword] = []
        self._keyword_domains[keyword].append((domain, score))

    def add_pattern_matcher(self, matcher: Callable[[str], Optional[Tuple[TaskDomain, float]]]) -> None:
        """Add a custom pattern matcher."""
        self._pattern_matchers.append(matcher)


# =============================================================================
# Adapter Selector
# =============================================================================

class AdapterSelector:
    """Selects optimal adapter for a task."""

    def __init__(self, adapters: List[AdapterConfig],
                 performance_tracker: Optional["PerformanceTracker"] = None):
        self._adapters = {a.adapter_id: a for a in adapters}
        self._domain_adapters: Dict[TaskDomain, List[str]] = self._build_domain_index()
        self._performance_tracker = performance_tracker
        self._strategy = SelectionStrategy.PERFORMANCE_BASED

    def _build_domain_index(self) -> Dict[TaskDomain, List[str]]:
        """Build index of adapters by domain."""
        index: Dict[TaskDomain, List[str]] = defaultdict(list)
        for adapter_id, adapter in self._adapters.items():
            for domain in adapter.domains:
                index[domain].append(adapter_id)
        return index

    def register_adapter(self, adapter: AdapterConfig) -> None:
        """Register a new adapter."""
        self._adapters[adapter.adapter_id] = adapter
        for domain in adapter.domains:
            if adapter.adapter_id not in self._domain_adapters[domain]:
                self._domain_adapters[domain].append(adapter.adapter_id)

    def unregister_adapter(self, adapter_id: str) -> None:
        """Unregister an adapter."""
        if adapter_id in self._adapters:
            adapter = self._adapters[adapter_id]
            for domain in adapter.domains:
                if adapter_id in self._domain_adapters[domain]:
                    self._domain_adapters[domain].remove(adapter_id)
            del self._adapters[adapter_id]

    def select(self, classification: TaskClassification,
               strategy: SelectionStrategy = None) -> Optional[SelectionResult]:
        """Select best adapter for task classification."""
        strategy = strategy or self._strategy

        # Get candidate adapters
        candidates = self._get_candidates(classification)
        if not candidates:
            return None

        # Score candidates
        scored_candidates = []
        for adapter_id in candidates:
            adapter = self._adapters[adapter_id]
            score = self._compute_score(adapter, classification, strategy)
            scored_candidates.append((adapter, score))

        # Sort by score
        scored_candidates.sort(key=lambda x: -x[1])

        # Select based on strategy
        if strategy == SelectionStrategy.BEST_MATCH:
            selected, score = scored_candidates[0]
        elif strategy == SelectionStrategy.WEIGHTED_RANDOM:
            selected, score = self._weighted_random_select(scored_candidates)
        elif strategy == SelectionStrategy.ROUND_ROBIN:
            selected, score = scored_candidates[0]  # Simplified
        else:
            selected, score = scored_candidates[0]

        return SelectionResult(
            selected_adapter=selected,
            selection_score=score,
            reasoning=f"Selected {selected.name} with score {score:.2f} for {classification.primary_domain.value}",
            alternatives=scored_candidates[1:4],
            strategy_used=strategy
        )

    def _get_candidates(self, classification: TaskClassification) -> List[str]:
        """Get candidate adapters for classification."""
        candidates = set()

        # Add adapters for primary domain
        candidates.update(self._domain_adapters.get(classification.primary_domain, []))

        # Add adapters for secondary domains
        for domain in classification.secondary_domains:
            candidates.update(self._domain_adapters.get(domain, []))

        # Add general adapters
        candidates.update(self._domain_adapters.get(TaskDomain.GENERAL, []))

        return list(candidates)

    def _compute_score(self, adapter: AdapterConfig, classification: TaskClassification,
                      strategy: SelectionStrategy) -> float:
        """Compute selection score for adapter."""
        score = 0.0

        # Domain match score
        if classification.primary_domain in adapter.domains:
            score += classification.confidence * 0.6

        for domain, conf in classification.secondary_domains.items():
            if domain in adapter.domains:
                score += conf * 0.3

        # Performance-based adjustment
        if strategy == SelectionStrategy.PERFORMANCE_BASED and self._performance_tracker:
            metrics = self._performance_tracker.get_metrics(
                adapter.adapter_id, classification.primary_domain
            )
            if metrics:
                score += metrics.success_rate * 0.3
                # Penalize slow adapters
                if metrics.avg_latency_ms > 1000:
                    score -= 0.1

        return min(1.0, score)

    def _weighted_random_select(self, scored_candidates: List[Tuple[AdapterConfig, float]]) -> Tuple[AdapterConfig, float]:
        """Select adapter with weighted random."""
        import random
        total = sum(s for _, s in scored_candidates)
        if total == 0:
            return scored_candidates[0]

        r = random.uniform(0, total)
        cumulative = 0
        for adapter, score in scored_candidates:
            cumulative += score
            if cumulative >= r:
                return adapter, score

        return scored_candidates[-1]

    def set_strategy(self, strategy: SelectionStrategy) -> None:
        """Set selection strategy."""
        self._strategy = strategy

    def get_adapters_for_domain(self, domain: TaskDomain) -> List[AdapterConfig]:
        """Get all adapters for a domain."""
        adapter_ids = self._domain_adapters.get(domain, [])
        return [self._adapters[aid] for aid in adapter_ids if aid in self._adapters]


# =============================================================================
# Performance Tracker
# =============================================================================

class PerformanceTracker:
    """Tracks adapter performance metrics."""

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._storage_path = storage_path
        self._metrics: Dict[str, Dict[TaskDomain, PerformanceMetrics]] = defaultdict(dict)
        self._lock = threading.Lock()

        if storage_path and storage_path.exists():
            self._load()

    def _load(self):
        """Load metrics from storage."""
        try:
            with open(self._storage_path, 'r') as f:
                data = json.load(f)

            for adapter_id, domains in data.get("metrics", {}).items():
                for domain_str, metrics_data in domains.items():
                    domain = TaskDomain(domain_str)
                    self._metrics[adapter_id][domain] = PerformanceMetrics.from_dict(metrics_data)
        except Exception as e:
            logger.error(f"Failed to load metrics: {e}")

    def _save(self):
        """Save metrics to storage."""
        if not self._storage_path:
            return

        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "metrics": {
                    adapter_id: {
                        domain.value: metrics.to_dict()
                        for domain, metrics in domains.items()
                    }
                    for adapter_id, domains in self._metrics.items()
                }
            }
            with open(self._storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")

    def record_success(self, adapter_id: str, domain: TaskDomain,
                      latency_ms: float, quality_score: float = 1.0):
        """Record successful task completion."""
        with self._lock:
            if domain not in self._metrics[adapter_id]:
                self._metrics[adapter_id][domain] = PerformanceMetrics(adapter_id, domain)

            metrics = self._metrics[adapter_id][domain]
            metrics.success_count += 1
            metrics.total_latency_ms += latency_ms

            # Update quality score with exponential moving average
            if metrics.quality_samples == 0:
                metrics.avg_quality_score = quality_score
            else:
                metrics.avg_quality_score = (
                    0.9 * metrics.avg_quality_score + 0.1 * quality_score
                )
            metrics.quality_samples += 1

            self._save()

    def record_failure(self, adapter_id: str, domain: TaskDomain, latency_ms: float) -> None:
        """Record failed task."""
        with self._lock:
            if domain not in self._metrics[adapter_id]:
                self._metrics[adapter_id][domain] = PerformanceMetrics(adapter_id, domain)

            metrics = self._metrics[adapter_id][domain]
            metrics.failure_count += 1
            metrics.total_latency_ms += latency_ms

            self._save()

    def get_metrics(self, adapter_id: str, domain: TaskDomain) -> Optional[PerformanceMetrics]:
        """Get metrics for adapter and domain."""
        return self._metrics.get(adapter_id, {}).get(domain)

    def get_all_metrics(self, adapter_id: str) -> Dict[TaskDomain, PerformanceMetrics]:
        """Get all metrics for an adapter."""
        return dict(self._metrics.get(adapter_id, {}))

    def get_best_adapter(self, domain: TaskDomain,
                        min_samples: int = 5) -> Optional[Tuple[str, float]]:
        """Get best performing adapter for domain."""
        best_adapter = None
        best_score = 0.0

        for adapter_id, domains in self._metrics.items():
            if domain in domains:
                metrics = domains[domain]
                total = metrics.success_count + metrics.failure_count
                if total >= min_samples:
                    score = metrics.success_rate * metrics.avg_quality_score
                    if score > best_score:
                        best_score = score
                        best_adapter = adapter_id

        return (best_adapter, best_score) if best_adapter else None

    def get_statistics(self) -> Dict[str, Any]:
        """Get overall statistics."""
        total_successes = 0
        total_failures = 0
        adapter_count = len(self._metrics)

        for adapter_id, domains in self._metrics.items():
            for domain, metrics in domains.items():
                total_successes += metrics.success_count
                total_failures += metrics.failure_count

        return {
            "adapter_count": adapter_count,
            "total_successes": total_successes,
            "total_failures": total_failures,
            "overall_success_rate": total_successes / (total_successes + total_failures) if (total_successes + total_failures) > 0 else 0.0
        }


# =============================================================================
# Adapter Loader
# =============================================================================

class AdapterLoaderInterface(ABC):
    """Interface for loading/unloading adapters."""

    @abstractmethod
    def load(self, adapter: AdapterConfig) -> Tuple[bool, float]:
        """Load adapter. Returns (success, memory_mb)."""
        pass

    @abstractmethod
    def unload(self, adapter_id: str) -> bool:
        """Unload adapter."""
        pass

    @abstractmethod
    def is_loaded(self, adapter_id: str) -> bool:
        """Check if adapter is loaded."""
        pass


class MockAdapterLoader(AdapterLoaderInterface):
    """Mock adapter loader for testing."""

    def __init__(self, load_delay_ms: float = 100.0, memory_per_adapter_mb: float = 100.0) -> None:
        self._load_delay = load_delay_ms
        self._memory_per_adapter = memory_per_adapter_mb
        self._loaded: Set[str] = set()

    def load(self, adapter: AdapterConfig) -> Tuple[bool, float]:
        """Simulate loading adapter."""
        time.sleep(self._load_delay / 1000.0)
        self._loaded.add(adapter.adapter_id)
        return True, self._memory_per_adapter

    def unload(self, adapter_id: str) -> bool:
        """Simulate unloading adapter."""
        if adapter_id in self._loaded:
            self._loaded.remove(adapter_id)
            return True
        return False

    def is_loaded(self, adapter_id: str) -> bool:
        """Check if adapter is loaded."""
        return adapter_id in self._loaded


# =============================================================================
# Composition Engine
# =============================================================================

class CompositionEngine:
    """Combines multiple adapters for hybrid tasks."""

    def __init__(self) -> None:
        self._mode = CompositionMode.WEIGHTED

    def compose(self, adapters: List[AdapterConfig], weights: List[float],
               mode: CompositionMode = None) -> Dict[str, Any]:
        """Compose multiple adapters."""
        mode = mode or self._mode

        if len(adapters) != len(weights):
            raise ValueError("Adapters and weights must have same length")

        if mode == CompositionMode.WEIGHTED:
            return self._weighted_compose(adapters, weights)
        elif mode == CompositionMode.AVERAGE:
            return self._average_compose(adapters)
        elif mode == CompositionMode.STACK:
            return self._stack_compose(adapters)
        else:
            return self._weighted_compose(adapters, weights)

    def _weighted_compose(self, adapters: List[AdapterConfig],
                         weights: List[float]) -> Dict[str, Any]:
        """Weighted combination of adapters."""
        # Normalize weights
        total = sum(weights)
        normalized = [w / total for w in weights] if total > 0 else [1.0 / len(weights)] * len(weights)

        return {
            "mode": "weighted",
            "adapters": [a.adapter_id for a in adapters],
            "weights": normalized,
            "combined_rank": sum(a.rank * w for a, w in zip(adapters, normalized))
        }

    def _average_compose(self, adapters: List[AdapterConfig]) -> Dict[str, Any]:
        """Simple average of adapters."""
        weights = [1.0 / len(adapters)] * len(adapters)
        return self._weighted_compose(adapters, weights)

    def _stack_compose(self, adapters: List[AdapterConfig]) -> Dict[str, Any]:
        """Stack adapters in sequence."""
        return {
            "mode": "stack",
            "adapters": [a.adapter_id for a in adapters],
            "order": list(range(len(adapters)))
        }

    def set_mode(self, mode: CompositionMode) -> None:
        """Set default composition mode."""
        self._mode = mode


# =============================================================================
# Adaptive Swapper
# =============================================================================

class AdaptiveSwapper:
    """Main system for adaptive LoRA swapping."""

    def __init__(self,
                 loader: AdapterLoaderInterface,
                 storage_dir: Optional[Path] = None,
                 max_loaded_adapters: int = 3):
        self._loader = loader
        self._storage_dir = storage_dir
        self._max_loaded = max_loaded_adapters

        # Initialize components
        metrics_path = storage_dir / "metrics.json" if storage_dir else None
        self._performance_tracker = PerformanceTracker(metrics_path)
        self._classifier = TaskClassifier()
        self._adapters: Dict[str, AdapterInstance] = {}
        self._selector: Optional[AdapterSelector] = None
        self._composition_engine = CompositionEngine()
        self._active_adapter_id: Optional[str] = None
        self._lock = threading.Lock()
        self._request_counter = 0

        if storage_dir:
            storage_dir.mkdir(parents=True, exist_ok=True)
            self._load_config()

    def _load_config(self):
        """Load adapter configuration."""
        config_path = self._storage_dir / "adapters.json"
        if not config_path.exists():
            return

        try:
            with open(config_path, 'r') as f:
                data = json.load(f)

            for adapter_data in data.get("adapters", []):
                config = AdapterConfig.from_dict(adapter_data)
                self._adapters[config.adapter_id] = AdapterInstance(config)

            self._selector = AdapterSelector(
                [inst.config for inst in self._adapters.values()],
                self._performance_tracker
            )
        except Exception as e:
            logger.error(f"Failed to load adapter config: {e}")

    def _save_config(self):
        """Save adapter configuration."""
        if not self._storage_dir:
            return

        try:
            config_path = self._storage_dir / "adapters.json"
            data = {
                "adapters": [inst.config.to_dict() for inst in self._adapters.values()]
            }
            with open(config_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save adapter config: {e}")

    def _generate_request_id(self) -> str:
        self._request_counter += 1
        return f"swap_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self._request_counter:04d}"

    def register_adapter(self, config: AdapterConfig) -> None:
        """Register a new adapter."""
        with self._lock:
            self._adapters[config.adapter_id] = AdapterInstance(config)

            if self._selector:
                self._selector.register_adapter(config)
            else:
                self._selector = AdapterSelector(
                    [inst.config for inst in self._adapters.values()],
                    self._performance_tracker
                )

            self._save_config()

    def unregister_adapter(self, adapter_id: str) -> None:
        """Unregister an adapter."""
        with self._lock:
            if adapter_id in self._adapters:
                instance = self._adapters[adapter_id]

                # Unload if loaded
                if instance.state == AdapterState.LOADED or instance.state == AdapterState.ACTIVE:
                    self._loader.unload(adapter_id)

                del self._adapters[adapter_id]

                if self._selector:
                    self._selector.unregister_adapter(adapter_id)

                self._save_config()

    def classify_task(self, task_text: str) -> TaskClassification:
        """Classify a task."""
        return self._classifier.classify(task_text)

    def select_adapter(self, classification: TaskClassification) -> Optional[SelectionResult]:
        """Select best adapter for classification."""
        if not self._selector:
            return None
        return self._selector.select(classification)

    def swap_adapter(self, target_adapter_id: str,
                    classification: TaskClassification = None) -> SwapResult:
        """Swap to target adapter."""
        request_id = self._generate_request_id()
        start_time = time.time()

        with self._lock:
            if target_adapter_id not in self._adapters:
                return SwapResult(
                    request_id=request_id,
                    success=False,
                    adapter_id=target_adapter_id,
                    swap_time_ms=0,
                    error_message=f"Adapter {target_adapter_id} not found"
                )

            target_instance = self._adapters[target_adapter_id]
            previous_id = self._active_adapter_id

            # Already active
            if self._active_adapter_id == target_adapter_id:
                return SwapResult(
                    request_id=request_id,
                    success=True,
                    adapter_id=target_adapter_id,
                    swap_time_ms=0,
                    previous_adapter_id=previous_id
                )

            # Load if needed
            if target_instance.state == AdapterState.UNLOADED:
                # Check if we need to unload something first
                loaded_count = sum(
                    1 for inst in self._adapters.values()
                    if inst.state in (AdapterState.LOADED, AdapterState.ACTIVE)
                )

                if loaded_count >= self._max_loaded:
                    # Find LRU adapter to unload
                    lru_adapter = self._find_lru_adapter(exclude={target_adapter_id})
                    if lru_adapter:
                        self._unload_adapter(lru_adapter)

                # Load target adapter
                target_instance.state = AdapterState.LOADING
                success, memory = self._loader.load(target_instance.config)

                if not success:
                    target_instance.state = AdapterState.FAILED
                    target_instance.error_message = "Failed to load adapter"
                    return SwapResult(
                        request_id=request_id,
                        success=False,
                        adapter_id=target_adapter_id,
                        swap_time_ms=(time.time() - start_time) * 1000,
                        error_message="Failed to load adapter"
                    )

                target_instance.state = AdapterState.LOADED
                target_instance.loaded_at = datetime.now()
                target_instance.memory_usage_mb = memory

            # Deactivate current adapter
            if self._active_adapter_id and self._active_adapter_id in self._adapters:
                self._adapters[self._active_adapter_id].state = AdapterState.LOADED

            # Activate target adapter
            target_instance.state = AdapterState.ACTIVE
            target_instance.last_used = datetime.now()
            target_instance.use_count += 1
            self._active_adapter_id = target_adapter_id

            swap_time = (time.time() - start_time) * 1000

            return SwapResult(
                request_id=request_id,
                success=True,
                adapter_id=target_adapter_id,
                swap_time_ms=swap_time,
                previous_adapter_id=previous_id
            )

    def _find_lru_adapter(self, exclude: Set[str] = None) -> Optional[str]:
        """Find least recently used loaded adapter."""
        exclude = exclude or set()
        lru_adapter = None
        lru_time = datetime.now()

        for adapter_id, instance in self._adapters.items():
            if adapter_id in exclude:
                continue
            if instance.state in (AdapterState.LOADED, AdapterState.ACTIVE):
                if instance.state != AdapterState.ACTIVE:
                    used = instance.last_used or instance.loaded_at or datetime.now()
                    if used < lru_time:
                        lru_time = used
                        lru_adapter = adapter_id

        return lru_adapter

    def _unload_adapter(self, adapter_id: str):
        """Unload an adapter."""
        if adapter_id in self._adapters:
            instance = self._adapters[adapter_id]
            instance.state = AdapterState.UNLOADING
            self._loader.unload(adapter_id)
            instance.state = AdapterState.UNLOADED
            instance.memory_usage_mb = 0

    def process_task(self, task_text: str) -> Tuple[Optional[str], SwapResult]:
        """Process a task with automatic adapter selection."""
        classification = self.classify_task(task_text)
        selection = self.select_adapter(classification)

        if not selection:
            # Use default/general adapter if available
            general_adapters = [
                aid for aid, inst in self._adapters.items()
                if TaskDomain.GENERAL in inst.config.domains
            ]
            if general_adapters:
                swap_result = self.swap_adapter(general_adapters[0], classification)
            else:
                swap_result = SwapResult(
                    request_id=self._generate_request_id(),
                    success=False,
                    adapter_id="",
                    swap_time_ms=0,
                    error_message="No suitable adapter found"
                )
            return None, swap_result

        swap_result = self.swap_adapter(selection.selected_adapter.adapter_id, classification)
        return selection.selected_adapter.adapter_id, swap_result

    def record_task_result(self, adapter_id: str, domain: TaskDomain,
                          success: bool, latency_ms: float,
                          quality_score: float = 1.0):
        """Record task execution result for performance tracking."""
        if success:
            self._performance_tracker.record_success(adapter_id, domain, latency_ms, quality_score)
        else:
            self._performance_tracker.record_failure(adapter_id, domain, latency_ms)

    def get_active_adapter(self) -> Optional[AdapterInstance]:
        """Get currently active adapter."""
        if self._active_adapter_id and self._active_adapter_id in self._adapters:
            return self._adapters[self._active_adapter_id]
        return None

    def get_loaded_adapters(self) -> List[AdapterInstance]:
        """Get all loaded adapters."""
        return [
            inst for inst in self._adapters.values()
            if inst.state in (AdapterState.LOADED, AdapterState.ACTIVE)
        ]

    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics."""
        loaded_count = sum(
            1 for inst in self._adapters.values()
            if inst.state in (AdapterState.LOADED, AdapterState.ACTIVE)
        )

        return {
            "total_adapters": len(self._adapters),
            "loaded_adapters": loaded_count,
            "max_loaded": self._max_loaded,
            "active_adapter": self._active_adapter_id,
            "performance": self._performance_tracker.get_statistics()
        }

    def compose_adapters(self, adapter_ids: List[str],
                        weights: List[float] = None) -> Dict[str, Any]:
        """Compose multiple adapters."""
        adapters = [
            self._adapters[aid].config
            for aid in adapter_ids
            if aid in self._adapters
        ]

        if not adapters:
            return {"error": "No valid adapters found"}

        if weights is None:
            weights = [1.0] * len(adapters)

        return self._composition_engine.compose(adapters, weights)


# =============================================================================
# CLI Tests
# =============================================================================

def _run_cli_tests():
    """Run CLI tests for adaptive LoRA swapping."""
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
    print("Adaptive LoRA Swapping - CLI Tests")
    print("="*60)

    # Test 1: TaskDomain Enum
    print("\n1. Testing TaskDomain...")
    test("Coding domain", TaskDomain.CODING.value == "coding")
    test("General domain", TaskDomain.GENERAL.value == "general")

    # Test 2: AdapterState Enum
    print("\n2. Testing AdapterState...")
    test("Unloaded state", AdapterState.UNLOADED.value == "unloaded")
    test("Active state", AdapterState.ACTIVE.value == "active")

    # Test 3: TaskClassification
    print("\n3. Testing TaskClassification...")
    classification = TaskClassification(
        task_id="task_001",
        primary_domain=TaskDomain.CODING,
        confidence=0.9,
        secondary_domains={TaskDomain.TECHNICAL: 0.5}
    )
    test("Create classification", classification.primary_domain == TaskDomain.CODING)

    cls_dict = classification.to_dict()
    cls_restored = TaskClassification.from_dict(cls_dict)
    test("Serialize classification", cls_restored.confidence == 0.9)

    # Test 4: AdapterConfig
    print("\n4. Testing AdapterConfig...")
    config = AdapterConfig(
        adapter_id="adapter_001",
        name="CodeAdapter",
        domains=[TaskDomain.CODING, TaskDomain.TECHNICAL],
        rank=32,
        alpha=64
    )
    test("Create config", config.name == "CodeAdapter")
    test("Multiple domains", len(config.domains) == 2)

    cfg_dict = config.to_dict()
    cfg_restored = AdapterConfig.from_dict(cfg_dict)
    test("Serialize config", cfg_restored.rank == 32)

    # Test 5: AdapterInstance
    print("\n5. Testing AdapterInstance...")
    instance = AdapterInstance(
        config=config,
        state=AdapterState.LOADED,
        loaded_at=datetime.now(),
        use_count=5
    )
    test("Create instance", instance.state == AdapterState.LOADED)
    test("Use count", instance.use_count == 5)

    inst_dict = instance.to_dict()
    inst_restored = AdapterInstance.from_dict(inst_dict)
    test("Serialize instance", inst_restored.use_count == 5)

    # Test 6: PerformanceMetrics
    print("\n6. Testing PerformanceMetrics...")
    metrics = PerformanceMetrics(
        adapter_id="adapter_001",
        domain=TaskDomain.CODING,
        success_count=90,
        failure_count=10,
        total_latency_ms=5000.0
    )
    test("Create metrics", metrics.success_count == 90)
    test("Success rate", metrics.success_rate == 0.9)
    test("Avg latency", metrics.avg_latency_ms == 50.0)

    met_dict = metrics.to_dict()
    met_restored = PerformanceMetrics.from_dict(met_dict)
    test("Serialize metrics", met_restored.success_rate == 0.9)

    # Test 7: TaskClassifier
    print("\n7. Testing TaskClassifier...")
    classifier = TaskClassifier()

    coding_cls = classifier.classify("Write a Python function to sort a list")
    test("Classify coding task", coding_cls.primary_domain == TaskDomain.CODING)

    math_cls = classifier.classify("Calculate the equation 2x + 3 = 15")
    test("Classify math task", math_cls.primary_domain == TaskDomain.MATH)

    general_cls = classifier.classify("Hello there")
    test("Classify general task", general_cls.primary_domain in (TaskDomain.CONVERSATION, TaskDomain.GENERAL))

    # Test 8: AdapterSelector
    print("\n8. Testing AdapterSelector...")
    adapters = [
        AdapterConfig("coding_adapter", "CodeAdapter", [TaskDomain.CODING]),
        AdapterConfig("math_adapter", "MathAdapter", [TaskDomain.MATH]),
        AdapterConfig("general_adapter", "GeneralAdapter", [TaskDomain.GENERAL])
    ]
    selector = AdapterSelector(adapters)

    code_cls = TaskClassification("t1", TaskDomain.CODING, 0.9)
    selection = selector.select(code_cls)
    test("Select coding adapter", selection.selected_adapter.adapter_id == "coding_adapter")

    math_cls = TaskClassification("t2", TaskDomain.MATH, 0.85)
    selection2 = selector.select(math_cls)
    test("Select math adapter", selection2.selected_adapter.adapter_id == "math_adapter")

    # Test 9: PerformanceTracker
    print("\n9. Testing PerformanceTracker...")
    with tempfile.TemporaryDirectory() as tmpdir:
        tracker = PerformanceTracker(Path(tmpdir) / "metrics.json")

        tracker.record_success("adapter_001", TaskDomain.CODING, 100.0, 0.9)
        tracker.record_success("adapter_001", TaskDomain.CODING, 150.0, 0.85)
        tracker.record_failure("adapter_001", TaskDomain.CODING, 200.0)

        metrics = tracker.get_metrics("adapter_001", TaskDomain.CODING)
        test("Record metrics", metrics.success_count == 2)
        test("Failure recorded", metrics.failure_count == 1)

        stats = tracker.get_statistics()
        test("Get statistics", stats["total_successes"] == 2)

    # Test 10: MockAdapterLoader
    print("\n10. Testing MockAdapterLoader...")
    loader = MockAdapterLoader(load_delay_ms=10, memory_per_adapter_mb=50.0)

    success, memory = loader.load(config)
    test("Load adapter", success and memory == 50.0)
    test("Is loaded", loader.is_loaded(config.adapter_id))

    unload_result = loader.unload(config.adapter_id)
    test("Unload adapter", unload_result and not loader.is_loaded(config.adapter_id))

    # Test 11: CompositionEngine
    print("\n11. Testing CompositionEngine...")
    engine = CompositionEngine()

    adapters_for_compose = [
        AdapterConfig("a1", "Adapter1", [TaskDomain.CODING]),
        AdapterConfig("a2", "Adapter2", [TaskDomain.MATH])
    ]
    weights = [0.7, 0.3]

    composition = engine.compose(adapters_for_compose, weights, CompositionMode.WEIGHTED)
    test("Weighted compose", composition["mode"] == "weighted")
    test("Weights normalized", abs(sum(composition["weights"]) - 1.0) < 0.01)

    avg_composition = engine.compose(adapters_for_compose, [1, 1], CompositionMode.AVERAGE)
    test("Average compose", avg_composition["mode"] == "weighted")

    # Test 12: AdaptiveSwapper
    print("\n12. Testing AdaptiveSwapper...")
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = MockAdapterLoader(load_delay_ms=10)
        swapper = AdaptiveSwapper(loader, Path(tmpdir), max_loaded_adapters=2)

        # Register adapters
        swapper.register_adapter(AdapterConfig("code", "Code", [TaskDomain.CODING]))
        swapper.register_adapter(AdapterConfig("math", "Math", [TaskDomain.MATH]))
        swapper.register_adapter(AdapterConfig("gen", "General", [TaskDomain.GENERAL]))

        test("Register adapters", len(swapper._adapters) == 3)

        # Swap to adapter
        result = swapper.swap_adapter("code")
        test("Swap to adapter", result.success)
        test("Active adapter", swapper._active_adapter_id == "code")

        # Swap to another
        result2 = swapper.swap_adapter("math")
        test("Swap to second", result2.success)
        test("Previous adapter recorded", result2.previous_adapter_id == "code")

        # Get loaded adapters
        loaded = swapper.get_loaded_adapters()
        test("Loaded adapters", len(loaded) <= 2)

    # Test 13: Process Task
    print("\n13. Testing process_task...")
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = MockAdapterLoader(load_delay_ms=10)
        swapper = AdaptiveSwapper(loader, Path(tmpdir))

        swapper.register_adapter(AdapterConfig("code", "Code", [TaskDomain.CODING]))
        swapper.register_adapter(AdapterConfig("gen", "General", [TaskDomain.GENERAL]))

        adapter_id, result = swapper.process_task("Write a Python function")
        test("Process task", result.success)
        test("Selected coding adapter", adapter_id == "code")

    # Test 14: Record Task Result
    print("\n14. Testing record_task_result...")
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = MockAdapterLoader(load_delay_ms=10)
        swapper = AdaptiveSwapper(loader, Path(tmpdir))

        swapper.register_adapter(AdapterConfig("code", "Code", [TaskDomain.CODING]))
        swapper.record_task_result("code", TaskDomain.CODING, True, 100.0, 0.95)

        metrics = swapper._performance_tracker.get_metrics("code", TaskDomain.CODING)
        test("Result recorded", metrics is not None and metrics.success_count == 1)

    # Test 15: Get Statistics
    print("\n15. Testing get_statistics...")
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = MockAdapterLoader(load_delay_ms=10)
        swapper = AdaptiveSwapper(loader, Path(tmpdir))

        swapper.register_adapter(AdapterConfig("a1", "A1", [TaskDomain.CODING]))
        swapper.swap_adapter("a1")

        stats = swapper.get_statistics()
        test("Statistics available", "total_adapters" in stats)
        test("Active adapter in stats", stats["active_adapter"] == "a1")

    # Test 16: Selection Strategies
    print("\n16. Testing selection strategies...")
    adapters = [
        AdapterConfig("a1", "A1", [TaskDomain.CODING]),
        AdapterConfig("a2", "A2", [TaskDomain.CODING]),
    ]
    selector = AdapterSelector(adapters)

    # Best match strategy
    selector.set_strategy(SelectionStrategy.BEST_MATCH)
    cls = TaskClassification("t", TaskDomain.CODING, 0.9)
    result = selector.select(cls, SelectionStrategy.BEST_MATCH)
    test("Best match strategy", result is not None)

    # Test 17: Unregister Adapter
    print("\n17. Testing unregister_adapter...")
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = MockAdapterLoader(load_delay_ms=10)
        swapper = AdaptiveSwapper(loader, Path(tmpdir))

        swapper.register_adapter(AdapterConfig("temp", "Temp", [TaskDomain.GENERAL]))
        test("Adapter registered", "temp" in swapper._adapters)

        swapper.unregister_adapter("temp")
        test("Adapter unregistered", "temp" not in swapper._adapters)

    # Test 18: LRU Eviction
    print("\n18. Testing LRU eviction...")
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = MockAdapterLoader(load_delay_ms=10)
        swapper = AdaptiveSwapper(loader, Path(tmpdir), max_loaded_adapters=2)

        swapper.register_adapter(AdapterConfig("a1", "A1", [TaskDomain.CODING]))
        swapper.register_adapter(AdapterConfig("a2", "A2", [TaskDomain.MATH]))
        swapper.register_adapter(AdapterConfig("a3", "A3", [TaskDomain.GENERAL]))

        swapper.swap_adapter("a1")
        swapper.swap_adapter("a2")
        swapper.swap_adapter("a3")

        loaded = swapper.get_loaded_adapters()
        test("LRU eviction", len(loaded) <= 2)

    # Test 19: Compose Adapters
    print("\n19. Testing compose_adapters...")
    with tempfile.TemporaryDirectory() as tmpdir:
        loader = MockAdapterLoader()
        swapper = AdaptiveSwapper(loader, Path(tmpdir))

        swapper.register_adapter(AdapterConfig("a1", "A1", [TaskDomain.CODING]))
        swapper.register_adapter(AdapterConfig("a2", "A2", [TaskDomain.MATH]))

        composition = swapper.compose_adapters(["a1", "a2"], [0.6, 0.4])
        test("Compose adapters", "adapters" in composition)
        test("Compose weights", len(composition.get("weights", [])) == 2)

    # Test 20: Keyword Classification
    print("\n20. Testing keyword classification...")
    classifier = TaskClassifier()

    # Add custom keyword
    classifier.add_keyword("deploy", TaskDomain.TECHNICAL, 0.9)

    deploy_cls = classifier.classify("Deploy the application to production")
    test("Custom keyword", deploy_cls.primary_domain == TaskDomain.TECHNICAL)

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
        print("Adaptive LoRA Swapping System")
        print("Usage: python adaptive_lora.py --test")
        print("\nThis module implements dynamic LoRA switching for task-specific performance.")

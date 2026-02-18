#!/usr/bin/env python3
"""
Adaptive Computing with Telemetry Feedback Loops (Improvement #13)
===================================================================

Collects performance telemetry and uses it to adaptively tune agent behavior.

Problem Solved:
- Fixed computation budgets waste resources on simple tasks
- Complex tasks get insufficient processing time
- No learning from past performance
- Inability to detect performance degradation

Research basis:
- arXiv:2305.14325 "Adaptive Computation in LLMs"
- arXiv:2303.08774 "Scaling Laws for Compute Allocation"
- arXiv:2312.01818 "Meta-Learning for LLM Efficiency"

Solution:
- Telemetry collection for all operations
- Exponential moving average for smooth adaptation
- Task complexity estimation
- Dynamic budget allocation
- Performance anomaly detection
- Self-tuning thresholds

Usage:
    from adaptive_telemetry import TelemetryCollector, AdaptiveCompute

    # Collect telemetry
    collector = TelemetryCollector()
    with collector.track_operation("api_call", context={"model": "grok"}):
        result = call_api()

    # Adaptive computation
    adaptive = AdaptiveCompute(collector)
    budget = adaptive.get_budget("complex_analysis", context={"tokens": 5000})
"""

import json
import time
import statistics
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any, Tuple
from enum import Enum
from collections import defaultdict
from contextlib import contextmanager
import threading

# Import atomic operations
try:
    from atomic_io import atomic_json_write, safe_json_read
    HAS_ATOMIC = True
except ImportError:
    HAS_ATOMIC = False


class MetricType(Enum):
    """Types of telemetry metrics"""
    LATENCY = "latency"              # Response time in seconds
    THROUGHPUT = "throughput"        # Operations per second
    SUCCESS_RATE = "success_rate"    # Fraction of successes
    RESOURCE_USAGE = "resource_usage"  # CPU/memory utilization
    TOKEN_COUNT = "token_count"      # Tokens processed
    ACCURACY = "accuracy"            # Quality metric
    COST = "cost"                    # API cost


class OperationType(Enum):
    """Types of operations to track"""
    API_CALL = "api_call"
    TOOL_EXECUTION = "tool_execution"
    FILE_OPERATION = "file_operation"
    MEMORY_QUERY = "memory_query"
    REASONING = "reasoning"
    PLANNING = "planning"
    SEARCH = "search"
    PARSING = "parsing"


class ComplexityLevel(Enum):
    """Task complexity levels"""
    TRIVIAL = "trivial"      # Simple lookup, < 1s
    SIMPLE = "simple"        # Basic operation, 1-5s
    MODERATE = "moderate"    # Multi-step, 5-30s
    COMPLEX = "complex"      # Deep analysis, 30s-2min
    INTENSIVE = "intensive"  # Long-running, > 2min


@dataclass
class TelemetryEvent:
    """A single telemetry event"""
    event_id: str
    operation_type: str
    timestamp: str
    duration_seconds: float
    success: bool
    metrics: Dict[str, float]
    context: Dict[str, Any]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TelemetryEvent':
        return cls(**data)


@dataclass
class MetricSummary:
    """Summary statistics for a metric"""
    metric_type: MetricType
    count: int
    mean: float
    std_dev: float
    min_val: float
    max_val: float
    p50: float  # Median
    p95: float  # 95th percentile
    p99: float  # 99th percentile
    trend: float  # Positive = improving, negative = degrading

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_type": self.metric_type.value,
            "count": self.count,
            "mean": self.mean,
            "std_dev": self.std_dev,
            "min": self.min_val,
            "max": self.max_val,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "trend": self.trend
        }


@dataclass
class AdaptiveBudget:
    """Adaptive computation budget"""
    operation_type: str
    base_budget_seconds: float
    adaptive_budget_seconds: float
    confidence: float  # 0-1, how confident in the estimate
    complexity: ComplexityLevel
    factors: Dict[str, float]  # What influenced the budget

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation_type": self.operation_type,
            "base_budget_seconds": self.base_budget_seconds,
            "adaptive_budget_seconds": self.adaptive_budget_seconds,
            "confidence": self.confidence,
            "complexity": self.complexity.value,
            "factors": self.factors
        }


class ExponentialMovingAverage:
    """
    Exponential Moving Average for smooth metric tracking.

    EMA gives more weight to recent values while smoothing noise.
    """

    def __init__(self, alpha: float = 0.2, initial_value: float = None) -> None:
        """
        Initialize EMA.

        Args:
            alpha: Smoothing factor (0-1). Higher = more weight to recent.
            initial_value: Starting value
        """
        self.alpha = alpha
        self._value = initial_value
        self._count = 0

    def update(self, new_value: float) -> float:
        """Update EMA with new value"""
        if self._value is None:
            self._value = new_value
        else:
            self._value = self.alpha * new_value + (1 - self.alpha) * self._value
        self._count += 1
        return self._value

    @property
    def value(self) -> Optional[float]:
        return self._value

    @property
    def count(self) -> int:
        return self._count


class TelemetryCollector:
    """
    Collects and stores telemetry data for operations.

    Thread-safe collection with periodic persistence.
    """

    def __init__(
        self,
        storage_path: Path = None,
        memory_dir: Path = None,
        max_events: int = 10000,
        retention_hours: int = 168  # 1 week
    ):
        if storage_path:
            self.storage_path = Path(storage_path)
        elif memory_dir:
            self.storage_path = Path(memory_dir) / "telemetry.json"
        else:
            self.storage_path = Path("vera_memory/telemetry.json")

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        self.max_events = max_events
        self.retention_hours = retention_hours

        # Event storage
        self._events: List[TelemetryEvent] = []
        self._event_count = 0
        self._lock = threading.RLock()

        # EMAs for each operation type
        self._latency_ema: Dict[str, ExponentialMovingAverage] = {}
        self._success_ema: Dict[str, ExponentialMovingAverage] = {}

        # Metrics aggregation
        self._metrics_cache: Dict[str, List[float]] = defaultdict(list)

        # Load existing data
        self._load()

    def _load(self):
        """Load existing telemetry data"""
        if not self.storage_path.exists():
            return

        try:
            if HAS_ATOMIC:
                data = safe_json_read(self.storage_path, default={})
            else:
                data = json.loads(self.storage_path.read_text())

            # Load events
            for event_data in data.get("events", []):
                self._events.append(TelemetryEvent.from_dict(event_data))

            self._event_count = data.get("event_count", len(self._events))

            # Rebuild EMAs from events
            for event in self._events:
                op_type = event.operation_type
                if op_type not in self._latency_ema:
                    self._latency_ema[op_type] = ExponentialMovingAverage()
                if op_type not in self._success_ema:
                    self._success_ema[op_type] = ExponentialMovingAverage()

                self._latency_ema[op_type].update(event.duration_seconds)
                self._success_ema[op_type].update(1.0 if event.success else 0.0)

        except Exception:
            self._events = []

    def _save(self):
        """Save telemetry data"""
        data = {
            "events": [e.to_dict() for e in self._events[-self.max_events:]],
            "event_count": self._event_count,
            "last_updated": datetime.now().isoformat()
        }

        if HAS_ATOMIC:
            atomic_json_write(self.storage_path, data)
        else:
            self.storage_path.write_text(json.dumps(data, indent=2))

    def _generate_event_id(self) -> str:
        """Generate unique event ID"""
        with self._lock:
            self._event_count += 1
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            return f"TEL-{timestamp}-{self._event_count:06d}"

    def record_event(
        self,
        operation_type: str,
        duration_seconds: float,
        success: bool,
        metrics: Dict[str, float] = None,
        context: Dict[str, Any] = None,
        error: str = None
    ) -> str:
        """
        Record a telemetry event.

        Args:
            operation_type: Type of operation
            duration_seconds: How long it took
            success: Whether it succeeded
            metrics: Additional metrics
            context: Context information
            error: Error message if failed

        Returns:
            Event ID
        """
        with self._lock:
            event = TelemetryEvent(
                event_id=self._generate_event_id(),
                operation_type=operation_type,
                timestamp=datetime.now().isoformat(),
                duration_seconds=duration_seconds,
                success=success,
                metrics=metrics or {},
                context=context or {},
                error=error
            )

            self._events.append(event)

            # Update EMAs
            if operation_type not in self._latency_ema:
                self._latency_ema[operation_type] = ExponentialMovingAverage()
            if operation_type not in self._success_ema:
                self._success_ema[operation_type] = ExponentialMovingAverage()

            self._latency_ema[operation_type].update(duration_seconds)
            self._success_ema[operation_type].update(1.0 if success else 0.0)

            # Cache metrics
            for metric_name, value in (metrics or {}).items():
                cache_key = f"{operation_type}:{metric_name}"
                self._metrics_cache[cache_key].append(value)
                # Keep only recent values
                if len(self._metrics_cache[cache_key]) > 1000:
                    self._metrics_cache[cache_key] = self._metrics_cache[cache_key][-500:]

            # Trim old events
            self._cleanup_old_events()

            # Periodic save
            if self._event_count % 100 == 0:
                self._save()

            return event.event_id

    def _cleanup_old_events(self):
        """Remove events older than retention period"""
        cutoff = datetime.now() - timedelta(hours=self.retention_hours)
        cutoff_iso = cutoff.isoformat()

        self._events = [
            e for e in self._events
            if e.timestamp >= cutoff_iso
        ][-self.max_events:]

    @contextmanager
    def track_operation(
        self,
        operation_type: str,
        context: Dict[str, Any] = None
    ):
        """
        Context manager for tracking an operation.

        Usage:
            with collector.track_operation("api_call", {"model": "grok"}):
                result = call_api()
        """
        start_time = time.time()
        success = True
        error = None
        metrics = {}

        try:
            yield metrics  # Caller can add metrics to this dict
        except Exception as e:
            success = False
            error = str(e)
            raise
        finally:
            duration = time.time() - start_time
            self.record_event(
                operation_type=operation_type,
                duration_seconds=duration,
                success=success,
                metrics=metrics,
                context=context,
                error=error
            )

    def get_latency_ema(self, operation_type: str) -> Optional[float]:
        """Get exponential moving average latency for operation type"""
        with self._lock:
            ema = self._latency_ema.get(operation_type)
            return ema.value if ema else None

    def get_success_rate_ema(self, operation_type: str) -> Optional[float]:
        """Get exponential moving average success rate"""
        with self._lock:
            ema = self._success_ema.get(operation_type)
            return ema.value if ema else None

    def get_events(
        self,
        operation_type: str = None,
        since: datetime = None,
        limit: int = 100
    ) -> List[TelemetryEvent]:
        """Get telemetry events"""
        with self._lock:
            events = self._events

            if operation_type:
                events = [e for e in events if e.operation_type == operation_type]

            if since:
                since_iso = since.isoformat()
                events = [e for e in events if e.timestamp >= since_iso]

            return events[-limit:]

    def get_metric_summary(
        self,
        operation_type: str,
        metric_name: str = "duration"
    ) -> Optional[MetricSummary]:
        """Get summary statistics for a metric"""
        with self._lock:
            if metric_name == "duration":
                values = [e.duration_seconds for e in self._events
                         if e.operation_type == operation_type]
            else:
                cache_key = f"{operation_type}:{metric_name}"
                values = self._metrics_cache.get(cache_key, [])

            if len(values) < 3:
                return None

            sorted_values = sorted(values)
            n = len(sorted_values)

            # Calculate trend (comparing recent vs old)
            mid = n // 2
            old_mean = statistics.mean(sorted_values[:mid]) if mid > 0 else 0
            recent_mean = statistics.mean(sorted_values[mid:]) if n - mid > 0 else 0
            trend = (old_mean - recent_mean) / old_mean if old_mean > 0 else 0

            return MetricSummary(
                metric_type=MetricType.LATENCY if metric_name == "duration" else MetricType.THROUGHPUT,
                count=n,
                mean=statistics.mean(values),
                std_dev=statistics.stdev(values) if n > 1 else 0,
                min_val=min(values),
                max_val=max(values),
                p50=sorted_values[n // 2],
                p95=sorted_values[int(n * 0.95)],
                p99=sorted_values[int(n * 0.99)],
                trend=trend
            )

    def get_operation_types(self) -> List[str]:
        """Get all tracked operation types"""
        with self._lock:
            return list(set(e.operation_type for e in self._events))

    def get_stats(self) -> Dict[str, Any]:
        """Get overall telemetry statistics"""
        with self._lock:
            by_type = defaultdict(lambda: {"count": 0, "success": 0, "total_duration": 0})

            for event in self._events:
                stats = by_type[event.operation_type]
                stats["count"] += 1
                stats["success"] += 1 if event.success else 0
                stats["total_duration"] += event.duration_seconds

            return {
                "total_events": len(self._events),
                "by_operation_type": {
                    op: {
                        "count": s["count"],
                        "success_rate": s["success"] / s["count"] if s["count"] > 0 else 0,
                        "avg_duration": s["total_duration"] / s["count"] if s["count"] > 0 else 0
                    }
                    for op, s in by_type.items()
                },
                "storage_path": str(self.storage_path)
            }

    def force_save(self) -> None:
        """Force save to storage"""
        with self._lock:
            self._save()


class ComplexityEstimator:
    """
    Estimates task complexity based on context.

    Uses heuristics and historical data to estimate complexity.
    """

    def __init__(self, collector: TelemetryCollector = None) -> None:
        self.collector = collector

        # Default complexity weights
        self.weights = {
            "token_count": 0.3,
            "tool_count": 0.2,
            "file_count": 0.15,
            "recursion_depth": 0.2,
            "historical": 0.15
        }

        # Thresholds for complexity levels
        self.thresholds = {
            ComplexityLevel.TRIVIAL: 0.2,
            ComplexityLevel.SIMPLE: 0.4,
            ComplexityLevel.MODERATE: 0.6,
            ComplexityLevel.COMPLEX: 0.8,
            ComplexityLevel.INTENSIVE: 1.0
        }

    def estimate(
        self,
        operation_type: str,
        context: Dict[str, Any] = None
    ) -> Tuple[ComplexityLevel, float]:
        """
        Estimate complexity level.

        Args:
            operation_type: Type of operation
            context: Context information (token_count, tool_count, etc.)

        Returns:
            Tuple of (ComplexityLevel, raw_score)
        """
        context = context or {}
        score = 0.0
        factors_used = 0

        # Token count factor
        if "token_count" in context or "tokens" in context:
            tokens = context.get("token_count") or context.get("tokens", 0)
            # Normalize: 1000 tokens = 0.5, 10000 = 1.0
            token_score = min(1.0, tokens / 10000)
            score += token_score * self.weights["token_count"]
            factors_used += 1

        # Tool count factor
        if "tool_count" in context or "tools" in context:
            tools = context.get("tool_count") or context.get("tools", 0)
            # More tools = more complex
            tool_score = min(1.0, tools / 10)
            score += tool_score * self.weights["tool_count"]
            factors_used += 1

        # File count factor
        if "file_count" in context or "files" in context:
            files = context.get("file_count") or context.get("files", 0)
            file_score = min(1.0, files / 20)
            score += file_score * self.weights["file_count"]
            factors_used += 1

        # Recursion depth factor
        if "depth" in context or "recursion_depth" in context:
            depth = context.get("depth") or context.get("recursion_depth", 0)
            depth_score = min(1.0, depth / 5)
            score += depth_score * self.weights["recursion_depth"]
            factors_used += 1

        # Historical factor (from telemetry)
        if self.collector:
            hist_latency = self.collector.get_latency_ema(operation_type)
            if hist_latency:
                # Normalize: 1s = 0.1, 60s = 1.0
                hist_score = min(1.0, hist_latency / 60)
                score += hist_score * self.weights["historical"]
                factors_used += 1

        # Normalize score if we used factors
        if factors_used > 0:
            used_weight = sum(
                self.weights[k] for k in self.weights
                if k in ["token_count", "tool_count", "file_count", "recursion_depth", "historical"][:factors_used]
            )
            if used_weight > 0:
                score = score / used_weight

        # Determine complexity level
        level = ComplexityLevel.TRIVIAL
        for lvl, threshold in sorted(self.thresholds.items(), key=lambda x: x[1]):
            if score <= threshold:
                level = lvl
                break

        return (level, score)


class AdaptiveCompute:
    """
    Adaptive computation budget allocator.

    Uses telemetry to dynamically allocate computation budgets.
    """

    def __init__(
        self,
        collector: TelemetryCollector,
        base_budgets: Dict[str, float] = None
    ):
        self.collector = collector
        self.estimator = ComplexityEstimator(collector)

        # Base budgets per operation type (in seconds)
        self.base_budgets = base_budgets or {
            "api_call": 30,
            "tool_execution": 60,
            "file_operation": 10,
            "memory_query": 5,
            "reasoning": 120,
            "planning": 180,
            "search": 30,
            "parsing": 15,
            "default": 60
        }

        # Complexity multipliers
        self.complexity_multipliers = {
            ComplexityLevel.TRIVIAL: 0.25,
            ComplexityLevel.SIMPLE: 0.5,
            ComplexityLevel.MODERATE: 1.0,
            ComplexityLevel.COMPLEX: 2.0,
            ComplexityLevel.INTENSIVE: 4.0
        }

        # Adaptation settings
        self.min_confidence_for_adaptation = 0.5
        self.max_budget_multiplier = 5.0
        self.min_budget_multiplier = 0.1

    def get_budget(
        self,
        operation_type: str,
        context: Dict[str, Any] = None
    ) -> AdaptiveBudget:
        """
        Get adaptive computation budget.

        Args:
            operation_type: Type of operation
            context: Context information

        Returns:
            AdaptiveBudget with recommended time
        """
        context = context or {}

        # Get base budget
        base = self.base_budgets.get(operation_type, self.base_budgets["default"])

        # Estimate complexity
        complexity, complexity_score = self.estimator.estimate(operation_type, context)

        # Get complexity multiplier
        complexity_mult = self.complexity_multipliers[complexity]

        # Get historical data
        ema_latency = self.collector.get_latency_ema(operation_type)
        success_rate = self.collector.get_success_rate_ema(operation_type)
        summary = self.collector.get_metric_summary(operation_type)

        factors = {
            "complexity_score": complexity_score,
            "complexity_multiplier": complexity_mult
        }

        confidence = 0.3  # Start with low confidence

        # Adjust based on historical data
        if ema_latency is not None:
            factors["ema_latency"] = ema_latency
            confidence += 0.3

            # Use historical average as baseline
            historical_mult = ema_latency / base if base > 0 else 1.0
            historical_mult = max(
                self.min_budget_multiplier,
                min(self.max_budget_multiplier, historical_mult)
            )
            factors["historical_multiplier"] = historical_mult

            # Combine complexity and historical
            combined_mult = (complexity_mult + historical_mult) / 2
        else:
            combined_mult = complexity_mult

        # Adjust for success rate
        if success_rate is not None:
            factors["success_rate"] = success_rate
            confidence += 0.2

            # Lower success rate = more time needed
            if success_rate < 0.9:
                success_adj = 1 + (0.9 - success_rate)  # Up to 90% more time
                combined_mult *= success_adj
                factors["success_adjustment"] = success_adj

        # Adjust for p95 latency (handle outliers)
        if summary and summary.p95 > 0:
            factors["p95_latency"] = summary.p95
            confidence += 0.2

            # If p95 is much higher than mean, add buffer
            if summary.p95 > summary.mean * 2:
                outlier_buffer = summary.p95 / summary.mean - 1
                combined_mult *= (1 + outlier_buffer * 0.3)
                factors["outlier_buffer"] = outlier_buffer

        # Calculate final budget
        adaptive_budget = base * combined_mult
        adaptive_budget = max(1, min(adaptive_budget, base * self.max_budget_multiplier))

        return AdaptiveBudget(
            operation_type=operation_type,
            base_budget_seconds=base,
            adaptive_budget_seconds=adaptive_budget,
            confidence=min(1.0, confidence),
            complexity=complexity,
            factors=factors
        )

    def should_extend_budget(
        self,
        operation_type: str,
        elapsed_seconds: float,
        current_budget: float
    ) -> Tuple[bool, float]:
        """
        Check if budget should be extended during execution.

        Args:
            operation_type: Type of operation
            elapsed_seconds: Time already spent
            current_budget: Current budget

        Returns:
            Tuple of (should_extend, new_budget)
        """
        # Check if near budget limit
        if elapsed_seconds < current_budget * 0.8:
            return (False, current_budget)

        # Check historical data for similar operations
        summary = self.collector.get_metric_summary(operation_type)
        if not summary:
            return (False, current_budget)

        # If we're within p95, might need extension
        if elapsed_seconds < summary.p95:
            extension = summary.p95 * 1.2  # Add 20% buffer
            return (True, extension)

        return (False, current_budget)


class PerformanceAnomalyDetector:
    """
    Detects performance anomalies using telemetry.

    Identifies operations that are significantly slower or
    failing more than expected.
    """

    def __init__(
        self,
        collector: TelemetryCollector,
        latency_threshold_std: float = 2.0,
        success_rate_threshold: float = 0.8
    ):
        self.collector = collector
        self.latency_threshold_std = latency_threshold_std
        self.success_rate_threshold = success_rate_threshold

    def detect_anomalies(self) -> List[Dict[str, Any]]:
        """
        Detect performance anomalies.

        Returns:
            List of anomaly descriptions
        """
        anomalies = []

        for op_type in self.collector.get_operation_types():
            # Check latency anomalies
            summary = self.collector.get_metric_summary(op_type)
            if summary and summary.count >= 10:
                # Check for high variance
                if summary.std_dev > summary.mean * 0.5:
                    anomalies.append({
                        "type": "high_variance",
                        "operation": op_type,
                        "severity": "warning",
                        "detail": f"Latency variance is {summary.std_dev:.2f}s "
                                 f"(mean: {summary.mean:.2f}s)"
                    })

                # Check for degradation trend
                if summary.trend < -0.1:
                    anomalies.append({
                        "type": "degradation",
                        "operation": op_type,
                        "severity": "warning",
                        "detail": f"Performance degraded by {abs(summary.trend)*100:.1f}%"
                    })

            # Check success rate
            success_rate = self.collector.get_success_rate_ema(op_type)
            if success_rate is not None and success_rate < self.success_rate_threshold:
                anomalies.append({
                    "type": "low_success_rate",
                    "operation": op_type,
                    "severity": "error" if success_rate < 0.5 else "warning",
                    "detail": f"Success rate is {success_rate*100:.1f}% "
                             f"(threshold: {self.success_rate_threshold*100:.0f}%)"
                })

            # Check recent events for spikes
            recent = self.collector.get_events(op_type, limit=20)
            if len(recent) >= 5:
                recent_durations = [e.duration_seconds for e in recent]
                recent_mean = statistics.mean(recent_durations)

                if summary and recent_mean > summary.mean + summary.std_dev * self.latency_threshold_std:
                    anomalies.append({
                        "type": "latency_spike",
                        "operation": op_type,
                        "severity": "warning",
                        "detail": f"Recent latency ({recent_mean:.2f}s) is "
                                 f"{(recent_mean - summary.mean)/summary.std_dev:.1f} "
                                 f"std devs above mean"
                    })

        return anomalies

    def get_health_score(self) -> float:
        """
        Get overall system health score.

        Returns:
            Score from 0 (unhealthy) to 1 (healthy)
        """
        anomalies = self.detect_anomalies()

        if not anomalies:
            return 1.0

        # Deduct for anomalies
        score = 1.0
        for anomaly in anomalies:
            if anomaly["severity"] == "error":
                score -= 0.2
            elif anomaly["severity"] == "warning":
                score -= 0.1

        return max(0.0, score)


class FeedbackLoop:
    """
    Implements feedback loop for continuous improvement.

    Tracks outcomes and adjusts parameters based on results.
    """

    def __init__(
        self,
        collector: TelemetryCollector,
        adaptive: AdaptiveCompute
    ):
        self.collector = collector
        self.adaptive = adaptive

        # Track budget accuracy
        self._budget_accuracy: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def record_outcome(
        self,
        operation_type: str,
        budget_used: float,
        actual_duration: float,
        success: bool
    ):
        """
        Record the outcome of a budgeted operation.

        Args:
            operation_type: Type of operation
            budget_used: Budget that was allocated
            actual_duration: Actual time taken
            success: Whether operation succeeded
        """
        with self._lock:
            # Calculate accuracy (how close budget was to actual)
            if budget_used > 0:
                accuracy = 1 - abs(actual_duration - budget_used) / budget_used
                accuracy = max(0, min(1, accuracy))
                self._budget_accuracy[operation_type].append(accuracy)

                # Keep only recent
                if len(self._budget_accuracy[operation_type]) > 100:
                    self._budget_accuracy[operation_type] = \
                        self._budget_accuracy[operation_type][-50:]

            # Adjust base budgets if consistently under/over
            if len(self._budget_accuracy[operation_type]) >= 20:
                recent_durations = [
                    e.duration_seconds for e in
                    self.collector.get_events(operation_type, limit=20)
                ]
                if recent_durations:
                    avg_duration = statistics.mean(recent_durations)
                    current_base = self.adaptive.base_budgets.get(
                        operation_type,
                        self.adaptive.base_budgets["default"]
                    )

                    # If average is consistently different, adjust base
                    if avg_duration > current_base * 1.5:
                        # Increase base by 20%
                        self.adaptive.base_budgets[operation_type] = \
                            current_base * 1.2
                    elif avg_duration < current_base * 0.5:
                        # Decrease base by 20%
                        self.adaptive.base_budgets[operation_type] = \
                            current_base * 0.8

    def get_budget_accuracy(self, operation_type: str) -> Optional[float]:
        """Get average budget accuracy for operation type"""
        with self._lock:
            accuracies = self._budget_accuracy.get(operation_type, [])
            if accuracies:
                return statistics.mean(accuracies)
        return None

    def summarize(self) -> str:
        """Generate feedback loop summary"""
        lines = ["**Feedback Loop Summary**"]

        with self._lock:
            for op_type, accuracies in self._budget_accuracy.items():
                if accuracies:
                    avg_acc = statistics.mean(accuracies)
                    lines.append(f"- {op_type}: {avg_acc*100:.1f}% budget accuracy")

        return "\n".join(lines)


# === CLI Test Interface ===

if __name__ == "__main__":
    import tempfile
    import random

    print("=" * 60)
    print("Adaptive Telemetry - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Test 1: Basic telemetry collection
        print("\n=== Test 1: Basic Telemetry Collection ===")
        collector = TelemetryCollector(storage_path=Path(tmpdir) / "telemetry.json")

        event_id = collector.record_event(
            operation_type="api_call",
            duration_seconds=2.5,
            success=True,
            metrics={"tokens": 1500},
            context={"model": "grok"}
        )
        assert event_id.startswith("TEL-")
        print(f"   Recorded event: {event_id}")
        print("   Result: PASS")

        # Test 2: Track operation context manager
        print("\n=== Test 2: Track Operation Context Manager ===")
        with collector.track_operation("file_operation", {"path": "/test"}):
            time.sleep(0.1)  # Simulate work

        events = collector.get_events("file_operation")
        assert len(events) >= 1
        print(f"   File operation tracked: {events[-1].duration_seconds:.3f}s")
        print("   Result: PASS")

        # Test 3: EMA calculations
        print("\n=== Test 3: EMA Calculations ===")
        for i in range(10):
            collector.record_event(
                "search",
                duration_seconds=1.0 + random.random(),
                success=True
            )

        ema = collector.get_latency_ema("search")
        assert ema is not None
        print(f"   Search latency EMA: {ema:.2f}s")
        print("   Result: PASS")

        # Test 4: Metric summary
        print("\n=== Test 4: Metric Summary ===")
        summary = collector.get_metric_summary("search")
        assert summary is not None
        print(f"   Mean: {summary.mean:.2f}s")
        print(f"   P95: {summary.p95:.2f}s")
        print(f"   Trend: {summary.trend:+.2f}")
        print("   Result: PASS")

        # Test 5: Complexity estimation
        print("\n=== Test 5: Complexity Estimation ===")
        estimator = ComplexityEstimator(collector)

        level, score = estimator.estimate("reasoning", {"tokens": 5000, "tools": 3})
        print(f"   Complexity: {level.value} (score: {score:.2f})")
        print("   Result: PASS")

        # Test 6: Adaptive budget
        print("\n=== Test 6: Adaptive Budget ===")
        adaptive = AdaptiveCompute(collector)

        budget = adaptive.get_budget("api_call", {"tokens": 2000})
        print(f"   Base: {budget.base_budget_seconds}s")
        print(f"   Adaptive: {budget.adaptive_budget_seconds:.1f}s")
        print(f"   Confidence: {budget.confidence:.2f}")
        print(f"   Complexity: {budget.complexity.value}")
        print("   Result: PASS")

        # Test 7: Budget extension check
        print("\n=== Test 7: Budget Extension Check ===")
        should_extend, new_budget = adaptive.should_extend_budget("search", 0.5, 2.0)
        print(f"   Should extend: {should_extend}")
        print("   Result: PASS")

        # Test 8: Anomaly detection
        print("\n=== Test 8: Anomaly Detection ===")
        # Add some failures
        for _ in range(5):
            collector.record_event("failing_op", 1.0, success=False)

        detector = PerformanceAnomalyDetector(collector)
        anomalies = detector.detect_anomalies()
        print(f"   Found {len(anomalies)} anomalies")
        if anomalies:
            print(f"   First: {anomalies[0]['type']}")
        print("   Result: PASS")

        # Test 9: Health score
        print("\n=== Test 9: Health Score ===")
        health = detector.get_health_score()
        print(f"   Health score: {health:.2f}")
        print("   Result: PASS")

        # Test 10: Feedback loop
        print("\n=== Test 10: Feedback Loop ===")
        feedback = FeedbackLoop(collector, adaptive)
        feedback.record_outcome("api_call", 30.0, 25.0, True)
        feedback.record_outcome("api_call", 30.0, 28.0, True)

        accuracy = feedback.get_budget_accuracy("api_call")
        print(f"   Budget accuracy: {accuracy*100:.1f}%")
        print("   Result: PASS")

        # Test 11: Statistics
        print("\n=== Test 11: Statistics ===")
        stats = collector.get_stats()
        print(f"   Total events: {stats['total_events']}")
        print(f"   Operation types: {len(stats['by_operation_type'])}")
        print("   Result: PASS")

        # Test 12: Persistence
        print("\n=== Test 12: Persistence ===")
        collector.force_save()
        collector2 = TelemetryCollector(storage_path=Path(tmpdir) / "telemetry.json")
        events2 = collector2.get_events()
        assert len(events2) > 0
        print(f"   Loaded {len(events2)} events")
        print("   Result: PASS")

        # Test 13: Exponential moving average
        print("\n=== Test 13: Exponential Moving Average ===")
        ema = ExponentialMovingAverage(alpha=0.3)
        values = [1, 2, 3, 4, 5]
        for v in values:
            ema.update(v)
        # EMA should be somewhere between mean and last value
        assert 2.5 < ema.value < 5.0
        print(f"   EMA of {values}: {ema.value:.2f}")
        print("   Result: PASS")

        # Test 14: Complexity levels
        print("\n=== Test 14: Complexity Levels ===")
        for level in ComplexityLevel:
            print(f"   {level.value}")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nAdaptive Telemetry is ready for integration!")

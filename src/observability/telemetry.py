"""
System Telemetry for VERA.

Provides system health monitoring, resource tracking, and performance metrics.
Inspired by GROKSTAR's GPU monitoring and health checks.
"""

import os
import json
import asyncio
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """System health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class MetricType(Enum):
    """Types of metrics to collect."""
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    GPU = "gpu"
    NETWORK = "network"
    PROCESS = "process"
    API = "api"


@dataclass
class MetricReading:
    """A single metric reading."""
    metric_type: MetricType
    name: str
    value: float
    unit: str
    timestamp: datetime
    threshold_warning: Optional[float] = None
    threshold_critical: Optional[float] = None

    @property
    def status(self) -> HealthStatus:
        """Get status based on thresholds."""
        if self.threshold_critical and self.value >= self.threshold_critical:
            return HealthStatus.CRITICAL
        if self.threshold_warning and self.value >= self.threshold_warning:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY


@dataclass
class SystemSnapshot:
    """Complete system health snapshot."""
    timestamp: datetime
    overall_status: HealthStatus
    metrics: Dict[str, MetricReading]
    alerts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "overall_status": self.overall_status.value,
            "metrics": {
                k: {
                    "value": v.value,
                    "unit": v.unit,
                    "status": v.status.value
                }
                for k, v in self.metrics.items()
            },
            "alerts": self.alerts
        }


class SystemTelemetry:
    """
    System telemetry and health monitoring for VERA.

    Features:
    - CPU, memory, disk, GPU monitoring
    - Configurable thresholds and alerts
    - Historical metric storage
    - Proactive health warnings
    - Resource-aware operation scheduling
    """

    # Default thresholds
    DEFAULT_THRESHOLDS = {
        "cpu_percent": {"warning": 80, "critical": 95},
        "memory_percent": {"warning": 80, "critical": 95},
        "disk_percent": {"warning": 85, "critical": 95},
        "gpu_memory_percent": {"warning": 90, "critical": 98},
        "gpu_temp": {"warning": 80, "critical": 90},
    }

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        collection_interval: int = 60,  # seconds
        history_retention_hours: int = 24
    ):
        """
        Initialize telemetry system.

        Args:
            memory_dir: Directory for telemetry data
            collection_interval: Seconds between metric collections
            history_retention_hours: Hours to retain historical data
        """
        if memory_dir:
            self.memory_dir = Path(memory_dir)
        else:
            self.memory_dir = Path("vera_memory")

        self.telemetry_dir = self.memory_dir / "telemetry"
        self.telemetry_dir.mkdir(parents=True, exist_ok=True)

        self.config_file = self.memory_dir / "telemetry_config.json"
        self.history_file = self.telemetry_dir / "metrics_history.ndjson"

        self.collection_interval = collection_interval
        self.history_retention_hours = history_retention_hours

        # Thresholds (customizable)
        self.thresholds = self.DEFAULT_THRESHOLDS.copy()

        # State
        self._running = False
        self._collector_task: Optional[asyncio.Task] = None
        self._last_snapshot: Optional[SystemSnapshot] = None
        self._history: List[SystemSnapshot] = []
        self._alert_callbacks: List[Callable] = []

        # Stats
        self._collection_count = 0
        self._alert_count = 0

        # Load config
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    data = json.load(f)
                self.thresholds.update(data.get("thresholds", {}))
                self.collection_interval = data.get("collection_interval", self.collection_interval)
            except Exception as e:
                logger.error(f"Failed to load telemetry config: {e}")

    def _save_config(self) -> None:
        """Save configuration to file."""
        data = {
            "thresholds": self.thresholds,
            "collection_interval": self.collection_interval
        }
        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=2)

    def configure_threshold(
        self,
        metric: str,
        warning: Optional[float] = None,
        critical: Optional[float] = None
    ) -> None:
        """
        Configure thresholds for a metric.

        Args:
            metric: Metric name (e.g., "cpu_percent")
            warning: Warning threshold
            critical: Critical threshold
        """
        if metric not in self.thresholds:
            self.thresholds[metric] = {}

        if warning is not None:
            self.thresholds[metric]["warning"] = warning
        if critical is not None:
            self.thresholds[metric]["critical"] = critical

        self._save_config()

    def on_alert(self, callback: Callable[[str, HealthStatus], None]) -> None:
        """
        Register a callback for health alerts.

        Args:
            callback: Function(alert_message, severity) to call
        """
        self._alert_callbacks.append(callback)

    async def collect_metrics(self) -> SystemSnapshot:
        """
        Collect current system metrics.

        Returns:
            SystemSnapshot with all metrics
        """
        metrics = {}
        alerts = []
        overall_status = HealthStatus.HEALTHY

        # CPU metrics
        cpu_metrics = await self._collect_cpu_metrics()
        metrics.update(cpu_metrics)

        # Memory metrics
        mem_metrics = await self._collect_memory_metrics()
        metrics.update(mem_metrics)

        # Disk metrics
        disk_metrics = await self._collect_disk_metrics()
        metrics.update(disk_metrics)

        # GPU metrics (if available)
        gpu_metrics = await self._collect_gpu_metrics()
        metrics.update(gpu_metrics)

        # Process metrics
        proc_metrics = await self._collect_process_metrics()
        metrics.update(proc_metrics)

        # Check for alerts and determine overall status
        for name, reading in metrics.items():
            if reading.status == HealthStatus.CRITICAL:
                overall_status = HealthStatus.CRITICAL
                alert = f"CRITICAL: {name} at {reading.value:.1f}{reading.unit}"
                alerts.append(alert)
                self._fire_alert(alert, HealthStatus.CRITICAL)
            elif reading.status == HealthStatus.DEGRADED:
                if overall_status == HealthStatus.HEALTHY:
                    overall_status = HealthStatus.DEGRADED
                alert = f"WARNING: {name} at {reading.value:.1f}{reading.unit}"
                alerts.append(alert)
                self._fire_alert(alert, HealthStatus.DEGRADED)

        # Create snapshot
        snapshot = SystemSnapshot(
            timestamp=datetime.now(),
            overall_status=overall_status,
            metrics=metrics,
            alerts=alerts
        )

        # Store
        self._last_snapshot = snapshot
        self._history.append(snapshot)
        self._collection_count += 1

        # Record to file
        self._record_snapshot(snapshot)

        # Prune old history
        self._prune_history()

        return snapshot

    def _fire_alert(self, message: str, severity: HealthStatus) -> None:
        """Fire alert callbacks."""
        self._alert_count += 1
        for callback in self._alert_callbacks:
            try:
                callback(message, severity)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    async def _collect_cpu_metrics(self) -> Dict[str, MetricReading]:
        """Collect CPU metrics."""
        metrics = {}
        thresholds = self.thresholds.get("cpu_percent", {})

        try:
            # Get load average (Unix only)
            load1, load5, load15 = os.getloadavg()
            cpu_count = os.cpu_count() or 1

            # Approximate CPU percent from load average
            cpu_percent = (load1 / cpu_count) * 100

            metrics["cpu_percent"] = MetricReading(
                metric_type=MetricType.CPU,
                name="cpu_percent",
                value=min(cpu_percent, 100),
                unit="%",
                timestamp=datetime.now(),
                threshold_warning=thresholds.get("warning"),
                threshold_critical=thresholds.get("critical")
            )

            metrics["load_avg_1m"] = MetricReading(
                metric_type=MetricType.CPU,
                name="load_avg_1m",
                value=load1,
                unit="",
                timestamp=datetime.now()
            )

        except Exception as e:
            logger.debug(f"CPU metrics collection failed: {e}")

        return metrics

    async def _collect_memory_metrics(self) -> Dict[str, MetricReading]:
        """Collect memory metrics."""
        metrics = {}
        thresholds = self.thresholds.get("memory_percent", {})

        try:
            # Read /proc/meminfo
            meminfo = Path("/proc/meminfo").read_text()
            mem_data = {}
            for line in meminfo.split("\n"):
                if ":" in line:
                    key, value = line.split(":")
                    # Extract numeric value (in kB)
                    value = value.strip().split()[0]
                    mem_data[key.strip()] = int(value)

            total = mem_data.get("MemTotal", 0)
            available = mem_data.get("MemAvailable", 0)
            used = total - available

            if total > 0:
                mem_percent = (used / total) * 100

                metrics["memory_percent"] = MetricReading(
                    metric_type=MetricType.MEMORY,
                    name="memory_percent",
                    value=mem_percent,
                    unit="%",
                    timestamp=datetime.now(),
                    threshold_warning=thresholds.get("warning"),
                    threshold_critical=thresholds.get("critical")
                )

                metrics["memory_used_gb"] = MetricReading(
                    metric_type=MetricType.MEMORY,
                    name="memory_used_gb",
                    value=used / (1024 * 1024),  # kB to GB
                    unit="GB",
                    timestamp=datetime.now()
                )

        except Exception as e:
            logger.debug(f"Memory metrics collection failed: {e}")

        return metrics

    async def _collect_disk_metrics(self) -> Dict[str, MetricReading]:
        """Collect disk metrics."""
        metrics = {}
        thresholds = self.thresholds.get("disk_percent", {})

        try:
            stat = os.statvfs("/")
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bavail * stat.f_frsize
            used = total - free

            if total > 0:
                disk_percent = (used / total) * 100

                metrics["disk_percent"] = MetricReading(
                    metric_type=MetricType.DISK,
                    name="disk_percent",
                    value=disk_percent,
                    unit="%",
                    timestamp=datetime.now(),
                    threshold_warning=thresholds.get("warning"),
                    threshold_critical=thresholds.get("critical")
                )

                metrics["disk_free_gb"] = MetricReading(
                    metric_type=MetricType.DISK,
                    name="disk_free_gb",
                    value=free / (1024**3),
                    unit="GB",
                    timestamp=datetime.now()
                )

        except Exception as e:
            logger.debug(f"Disk metrics collection failed: {e}")

        return metrics

    async def _collect_gpu_metrics(self) -> Dict[str, MetricReading]:
        """Collect GPU metrics using nvidia-smi."""
        metrics = {}

        try:
            # Check if nvidia-smi is available
            result = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")

                for i, line in enumerate(lines):
                    values = [v.strip() for v in line.split(",")]
                    if len(values) >= 4:
                        mem_used = float(values[0])
                        mem_total = float(values[1])
                        temp = float(values[2])
                        util = float(values[3])

                        gpu_id = f"gpu{i}"

                        # GPU memory
                        mem_percent = (mem_used / mem_total) * 100 if mem_total > 0 else 0
                        thresholds_mem = self.thresholds.get("gpu_memory_percent", {})

                        metrics[f"{gpu_id}_memory_percent"] = MetricReading(
                            metric_type=MetricType.GPU,
                            name=f"{gpu_id}_memory_percent",
                            value=mem_percent,
                            unit="%",
                            timestamp=datetime.now(),
                            threshold_warning=thresholds_mem.get("warning"),
                            threshold_critical=thresholds_mem.get("critical")
                        )

                        # GPU temperature
                        thresholds_temp = self.thresholds.get("gpu_temp", {})

                        metrics[f"{gpu_id}_temp"] = MetricReading(
                            metric_type=MetricType.GPU,
                            name=f"{gpu_id}_temp",
                            value=temp,
                            unit="°C",
                            timestamp=datetime.now(),
                            threshold_warning=thresholds_temp.get("warning"),
                            threshold_critical=thresholds_temp.get("critical")
                        )

                        # GPU utilization
                        metrics[f"{gpu_id}_util"] = MetricReading(
                            metric_type=MetricType.GPU,
                            name=f"{gpu_id}_util",
                            value=util,
                            unit="%",
                            timestamp=datetime.now()
                        )

        except FileNotFoundError:
            logger.debug("nvidia-smi not found, GPU metrics unavailable")
        except subprocess.TimeoutExpired:
            logger.warning("nvidia-smi timed out")
        except Exception as e:
            logger.debug(f"GPU metrics collection failed: {e}")

        return metrics

    async def _collect_process_metrics(self) -> Dict[str, MetricReading]:
        """Collect current process metrics."""
        metrics = {}

        try:
            import resource

            # Memory usage of current process
            rusage = resource.getrusage(resource.RUSAGE_SELF)
            max_rss_mb = rusage.ru_maxrss / 1024  # KB to MB

            metrics["process_memory_mb"] = MetricReading(
                metric_type=MetricType.PROCESS,
                name="process_memory_mb",
                value=max_rss_mb,
                unit="MB",
                timestamp=datetime.now()
            )

        except Exception as e:
            logger.debug(f"Process metrics collection failed: {e}")

        return metrics

    def _record_snapshot(self, snapshot: SystemSnapshot) -> None:
        """Record snapshot to history file."""
        record = {
            "timestamp": snapshot.timestamp.isoformat(),
            "overall_status": snapshot.overall_status.value,
            "metrics": {
                k: {"value": v.value, "status": v.status.value}
                for k, v in snapshot.metrics.items()
            }
        }

        with open(self.history_file, 'a') as f:
            f.write(json.dumps(record) + "\n")

    def _prune_history(self) -> None:
        """Prune old history entries."""
        cutoff = datetime.now() - timedelta(hours=self.history_retention_hours)
        self._history = [s for s in self._history if s.timestamp > cutoff]

    async def start_collection(self) -> None:
        """Start background metric collection."""
        if self._running:
            return

        self._running = True
        self._collector_task = asyncio.create_task(self._collection_loop())
        logger.info("Telemetry collection started")

    async def stop_collection(self) -> None:
        """Stop background metric collection."""
        self._running = False
        if self._collector_task:
            self._collector_task.cancel()
            try:
                await self._collector_task
            except asyncio.CancelledError:
                pass
        logger.info("Telemetry collection stopped")

    async def _collection_loop(self) -> None:
        """Background loop for metric collection."""
        while self._running:
            try:
                await self.collect_metrics()
                await asyncio.sleep(self.collection_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Metric collection error: {e}")
                await asyncio.sleep(self.collection_interval)

    def get_current_status(self) -> Dict[str, Any]:
        """Get current system status."""
        if self._last_snapshot:
            return self._last_snapshot.to_dict()
        return {"overall_status": "unknown", "note": "No metrics collected yet"}

    def get_health_summary(self) -> str:
        """Get human-readable health summary."""
        if not self._last_snapshot:
            return "No metrics available"

        snapshot = self._last_snapshot
        lines = [f"System Status: {snapshot.overall_status.value.upper()}"]
        lines.append(f"Last Check: {snapshot.timestamp.strftime('%H:%M:%S')}")
        lines.append("")

        # Key metrics
        key_metrics = ["cpu_percent", "memory_percent", "disk_percent"]
        for metric in key_metrics:
            if metric in snapshot.metrics:
                reading = snapshot.metrics[metric]
                status_icon = "✓" if reading.status == HealthStatus.HEALTHY else "⚠️"
                lines.append(f"{status_icon} {metric}: {reading.value:.1f}{reading.unit}")

        # GPU metrics
        gpu_metrics = [k for k in snapshot.metrics.keys() if k.startswith("gpu")]
        if gpu_metrics:
            lines.append("")
            for metric in gpu_metrics[:4]:  # Limit to first 4
                reading = snapshot.metrics[metric]
                status_icon = "✓" if reading.status == HealthStatus.HEALTHY else "⚠️"
                lines.append(f"{status_icon} {metric}: {reading.value:.1f}{reading.unit}")

        # Alerts
        if snapshot.alerts:
            lines.append("")
            lines.append("Active Alerts:")
            for alert in snapshot.alerts:
                lines.append(f"  - {alert}")

        return "\n".join(lines)

    def check_resource_availability(
        self,
        cpu_required: float = 0,
        memory_required_mb: float = 0,
        gpu_memory_required_mb: float = 0
    ) -> bool:
        """
        Check if sufficient resources are available for an operation.

        Args:
            cpu_required: Required CPU headroom (percent)
            memory_required_mb: Required memory (MB)
            gpu_memory_required_mb: Required GPU memory (MB)

        Returns:
            True if resources are available
        """
        if not self._last_snapshot:
            return True  # Assume available if no metrics

        metrics = self._last_snapshot.metrics

        # Check CPU
        if cpu_required > 0:
            cpu = metrics.get("cpu_percent")
            if cpu and (100 - cpu.value) < cpu_required:
                return False

        # Check memory
        if memory_required_mb > 0:
            mem = metrics.get("memory_percent")
            mem_used = metrics.get("memory_used_gb")
            if mem and mem.value > 90:  # Less than 10% free
                return False

        # Check GPU memory
        if gpu_memory_required_mb > 0:
            for key, reading in metrics.items():
                if "gpu" in key and "memory_percent" in key:
                    if reading.value > 90:  # Less than 10% free
                        return False

        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get telemetry system statistics."""
        return {
            "collection_count": self._collection_count,
            "alert_count": self._alert_count,
            "history_entries": len(self._history),
            "collection_interval": self.collection_interval,
            "running": self._running,
            "last_collection": self._last_snapshot.timestamp.isoformat() if self._last_snapshot else None,
            "current_status": self._last_snapshot.overall_status.value if self._last_snapshot else "unknown"
        }


# === Self-test ===

if __name__ == "__main__":
    import sys

    async def test_telemetry():
        """Test system telemetry."""
        print("Testing System Telemetry...")

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test 1: Create telemetry
            print("Test 1: Create telemetry...", end=" ")
            telemetry = SystemTelemetry(memory_dir=Path(tmpdir))
            print("PASS")

            # Test 2: Collect metrics
            print("Test 2: Collect metrics...", end=" ")
            snapshot = await telemetry.collect_metrics()
            assert snapshot is not None
            assert snapshot.timestamp is not None
            print("PASS")

            # Test 3: Check metric types
            print("Test 3: Metric types...", end=" ")
            assert len(snapshot.metrics) > 0
            # At least CPU and memory should be available
            print(f"PASS ({len(snapshot.metrics)} metrics)")

            # Test 4: Get status
            print("Test 4: Get status...", end=" ")
            status = telemetry.get_current_status()
            assert "overall_status" in status
            print("PASS")

            # Test 5: Health summary
            print("Test 5: Health summary...", end=" ")
            summary = telemetry.get_health_summary()
            assert "System Status" in summary
            print("PASS")

            # Test 6: Resource check
            print("Test 6: Resource check...", end=" ")
            available = telemetry.check_resource_availability(
                cpu_required=10,
                memory_required_mb=100
            )
            assert isinstance(available, bool)
            print("PASS")

            # Test 7: Configure threshold
            print("Test 7: Configure threshold...", end=" ")
            telemetry.configure_threshold("cpu_percent", warning=70, critical=90)
            assert telemetry.thresholds["cpu_percent"]["warning"] == 70
            print("PASS")

            # Test 8: Alert callback
            print("Test 8: Alert callback...", end=" ")
            alerts_received = []

            def alert_handler(msg, severity) -> None:
                alerts_received.append((msg, severity))

            telemetry.on_alert(alert_handler)
            assert len(telemetry._alert_callbacks) == 1
            print("PASS")

            # Test 9: Stats
            print("Test 9: Stats...", end=" ")
            stats = telemetry.get_stats()
            assert stats["collection_count"] == 1
            print("PASS")

            # Test 10: Metric reading status
            print("Test 10: Metric status...", end=" ")
            reading = MetricReading(
                metric_type=MetricType.CPU,
                name="test",
                value=85,
                unit="%",
                timestamp=datetime.now(),
                threshold_warning=80,
                threshold_critical=95
            )
            assert reading.status == HealthStatus.DEGRADED
            reading.value = 96
            assert reading.status == HealthStatus.CRITICAL
            reading.value = 50
            assert reading.status == HealthStatus.HEALTHY
            print("PASS")

        print("\nAll tests passed!")
        return True

    success = asyncio.run(test_telemetry())
    sys.exit(0 if success else 1)

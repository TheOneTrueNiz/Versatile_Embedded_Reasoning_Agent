"""
Morning Briefing / Cadence System for VERA.

Provides scheduled briefings and proactive status updates.
Inspired by GROKSTAR's autonomous cycle scheduling.
"""

import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime, time, timedelta
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class BriefingType(Enum):
    """Types of scheduled briefings."""
    MORNING = "morning"     # Daily morning summary
    EVENING = "evening"     # End of day recap
    WEEKLY = "weekly"       # Weekly review
    ADHOC = "adhoc"        # On-demand briefing


class BriefingSection(Enum):
    """Sections included in briefings."""
    TASKS = "tasks"                 # Task summary
    CALENDAR = "calendar"           # Calendar events
    WEATHER = "weather"             # Weather forecast
    NEWS = "news"                   # News headlines
    HEALTH = "health"               # System health
    GOALS = "goals"                 # Goal progress
    REMINDERS = "reminders"         # Pending reminders
    METRICS = "metrics"             # Usage metrics
    CUSTOM = "custom"               # Custom sections


@dataclass
class BriefingConfig:
    """Configuration for a scheduled briefing."""
    name: str
    briefing_type: BriefingType
    schedule_time: time            # Time of day to run
    enabled: bool = True
    days: List[int] = None         # Days of week (0=Mon, 6=Sun). None = daily

    # Content configuration
    sections: List[BriefingSection] = None
    max_items_per_section: int = 5

    # Delivery configuration
    notify_on_complete: bool = True
    save_to_file: bool = True

    def __post_init__(self):
        if self.days is None:
            self.days = [0, 1, 2, 3, 4, 5, 6]  # Daily
        if self.sections is None:
            self.sections = [
                BriefingSection.TASKS,
                BriefingSection.HEALTH,
                BriefingSection.GOALS
            ]


@dataclass
class Briefing:
    """A generated briefing."""
    briefing_id: str
    briefing_type: BriefingType
    generated_at: datetime
    content: Dict[str, Any]
    summary: str
    word_count: int = 0
    generation_time_ms: int = 0


@dataclass
class CadenceStats:
    """Statistics for the cadence system."""
    total_briefings: int = 0
    last_briefing_time: Optional[datetime] = None
    next_scheduled_time: Optional[datetime] = None
    briefings_by_type: Dict[str, int] = field(default_factory=dict)


class MorningBriefingGenerator:
    """
    Generates morning briefings and scheduled updates.

    Features:
    - Configurable briefing schedules
    - Multiple briefing types (morning, evening, weekly)
    - Customizable content sections
    - Persistent history tracking
    - Integration with VERA subsystems
    """

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        vera_instance: Optional[Any] = None
    ):
        """
        Initialize the briefing generator.

        Args:
            memory_dir: Directory for storing briefing history
            vera_instance: VERA instance for data access
        """
        if memory_dir:
            self.memory_dir = Path(memory_dir)
        else:
            self.memory_dir = Path("vera_memory")

        self.briefings_dir = self.memory_dir / "briefings"
        self.briefings_dir.mkdir(parents=True, exist_ok=True)

        self.config_file = self.memory_dir / "cadence_config.json"
        self.history_file = self.memory_dir / "briefing_history.ndjson"

        self.vera = vera_instance

        # Default configurations
        self._configs: Dict[str, BriefingConfig] = {
            "morning": BriefingConfig(
                name="Morning Briefing",
                briefing_type=BriefingType.MORNING,
                schedule_time=time(7, 0),  # 7:00 AM
                sections=[
                    BriefingSection.TASKS,
                    BriefingSection.CALENDAR,
                    BriefingSection.WEATHER,
                    BriefingSection.HEALTH
                ]
            ),
            "evening": BriefingConfig(
                name="Evening Recap",
                briefing_type=BriefingType.EVENING,
                schedule_time=time(18, 0),  # 6:00 PM
                sections=[
                    BriefingSection.TASKS,
                    BriefingSection.METRICS,
                    BriefingSection.GOALS
                ]
            ),
            "weekly": BriefingConfig(
                name="Weekly Review",
                briefing_type=BriefingType.WEEKLY,
                schedule_time=time(9, 0),  # 9:00 AM Sunday
                days=[6],  # Sunday only
                sections=[
                    BriefingSection.GOALS,
                    BriefingSection.METRICS,
                    BriefingSection.TASKS
                ]
            )
        }

        # Stats
        self._stats = CadenceStats()

        # Scheduler state
        self._scheduler_task: Optional[asyncio.Task] = None
        self._running = False

        # Custom section generators
        self._section_generators: Dict[str, Callable] = {}

        # Load saved config
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    data = json.load(f)

                for name, config_data in data.get("configs", {}).items():
                    self._configs[name] = BriefingConfig(
                        name=config_data.get("name", name),
                        briefing_type=BriefingType(config_data.get("type", "morning")),
                        schedule_time=time.fromisoformat(config_data.get("schedule_time", "07:00")),
                        enabled=config_data.get("enabled", True),
                        days=config_data.get("days"),
                        sections=[BriefingSection(s) for s in config_data.get("sections", [])],
                        max_items_per_section=config_data.get("max_items", 5)
                    )

            except Exception as e:
                logger.error(f"Failed to load cadence config: {e}")

    def _save_config(self) -> None:
        """Save configuration to file."""
        data = {"configs": {}}

        for name, config in self._configs.items():
            data.get("configs", "")[name] = {
                "name": config.name,
                "type": config.briefing_type.value,
                "schedule_time": config.schedule_time.isoformat(),
                "enabled": config.enabled,
                "days": config.days,
                "sections": [s.value for s in config.sections],
                "max_items": config.max_items_per_section
            }

        with open(self.config_file, 'w') as f:
            json.dump(data, f, indent=2)

    def configure(
        self,
        name: str,
        config: BriefingConfig
    ) -> None:
        """
        Add or update a briefing configuration.

        Args:
            name: Configuration name
            config: BriefingConfig instance
        """
        self._configs[name] = config
        self._save_config()

    def register_section_generator(
        self,
        section: BriefingSection,
        generator: Callable
    ) -> None:
        """
        Register a custom section generator.

        Args:
            section: Section to generate
            generator: Async function returning section content
        """
        self._section_generators[section.value] = generator

    async def generate_briefing(
        self,
        briefing_type: BriefingType = BriefingType.MORNING,
        config_name: Optional[str] = None
    ) -> Briefing:
        """
        Generate a briefing.

        Args:
            briefing_type: Type of briefing to generate
            config_name: Optional config name to use

        Returns:
            Generated Briefing
        """
        start_time = datetime.now()

        # Get config
        if config_name and config_name in self._configs:
            config = self._configs[config_name]
        else:
            # Find config by type
            config = next(
                (c for c in self._configs.values() if c.briefing_type == briefing_type),
                self._configs.get("morning")
            )

        # Generate each section
        content = {}
        for section in config.sections:
            section_content = await self._generate_section(
                section,
                config.max_items_per_section
            )
            content[section.value] = section_content

        # Generate summary
        summary = self._generate_summary(content, config)

        # Create briefing
        briefing = Briefing(
            briefing_id=f"brief-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            briefing_type=briefing_type,
            generated_at=datetime.now(),
            content=content,
            summary=summary,
            word_count=len(summary.split()),
            generation_time_ms=int((datetime.now() - start_time).total_seconds() * 1000)
        )

        # Save to history
        self._record_briefing(briefing)

        # Save to file if configured
        if config.save_to_file:
            self._save_briefing_file(briefing)

        # Update stats
        self._stats.total_briefings += 1
        self._stats.last_briefing_time = datetime.now()
        self._stats.briefings_by_type[briefing_type.value] = \
            self._stats.briefings_by_type.get(briefing_type.value, 0) + 1

        return briefing

    async def _generate_section(
        self,
        section: BriefingSection,
        max_items: int
    ) -> Dict[str, Any]:
        """Generate content for a section."""

        # Check for custom generator
        if section.value in self._section_generators:
            generator = self._section_generators[section.value]
            if asyncio.iscoroutinefunction(generator):
                return await generator(max_items)
            return generator(max_items)

        # Default generators
        if section == BriefingSection.TASKS:
            return await self._generate_tasks_section(max_items)

        elif section == BriefingSection.HEALTH:
            return await self._generate_health_section()

        elif section == BriefingSection.GOALS:
            return await self._generate_goals_section(max_items)

        elif section == BriefingSection.METRICS:
            return await self._generate_metrics_section()

        elif section == BriefingSection.CALENDAR:
            return await self._generate_calendar_section(max_items)

        elif section == BriefingSection.WEATHER:
            return await self._generate_weather_section()

        elif section == BriefingSection.NEWS:
            return await self._generate_news_section(max_items)

        elif section == BriefingSection.REMINDERS:
            return await self._generate_reminders_section(max_items)

        return {"note": f"Section '{section.value}' not implemented"}

    async def _generate_tasks_section(self, max_items: int) -> Dict[str, Any]:
        """Generate tasks section."""
        if self.vera and hasattr(self.vera, 'master_list'):
            tasks = self.vera.master_list.parse()
            pending = [t for t in tasks if t.status.value == "pending"]
            in_progress = [t for t in tasks if t.status.value == "in_progress"]
            completed_today = [
                t for t in tasks
                if t.status.value == "completed" and
                t.updated.date() == datetime.now().date()
            ]

            # Get overdue
            overdue = [
                t for t in pending
                if t.due and t.due < datetime.now()
            ]

            return {
                "pending_count": len(pending),
                "in_progress_count": len(in_progress),
                "completed_today": len(completed_today),
                "overdue_count": len(overdue),
                "top_pending": [
                    {"id": t.id, "title": t.title, "priority": t.priority.value}
                    for t in sorted(pending, key=lambda x: x.priority.value)[:max_items]
                ],
                "overdue": [
                    {"id": t.id, "title": t.title, "due": t.due.isoformat() if t.due else None}
                    for t in overdue[:max_items]
                ]
            }

        return {
            "pending_count": 0,
            "note": "Task list not available"
        }

    async def _generate_health_section(self) -> Dict[str, Any]:
        """Generate system health section."""
        if self.vera and hasattr(self.vera, 'health_monitor'):
            health = self.vera.health_monitor.get_stats()
            return {
                "status": "healthy" if health.get("healthy", True) else "degraded",
                "uptime_seconds": health.get("uptime_seconds", 0),
                "errors_today": health.get("errors_today", 0),
                "warnings": health.get("warnings", [])
            }

        return {"status": "unknown", "note": "Health monitor not available"}

    async def _generate_goals_section(self, max_items: int) -> Dict[str, Any]:
        """Generate goals progress section."""
        if self.vera and hasattr(self.vera, 'charters'):
            active = self.vera.charters.list_charters(status="in_progress")
            return {
                "active_projects": len(active),
                "projects": [
                    {
                        "id": p.charter_id,
                        "title": p.title,
                        "progress": p.get_progress_percent() if hasattr(p, 'get_progress_percent') else 0
                    }
                    for p in active[:max_items]
                ]
            }

        return {"active_projects": 0, "note": "Project charters not available"}

    async def _generate_metrics_section(self) -> Dict[str, Any]:
        """Generate usage metrics section."""
        metrics = {
            "date": datetime.now().date().isoformat(),
            "briefing_count": self._stats.total_briefings
        }

        if self.vera and hasattr(self.vera, 'cost_tracker'):
            cost_stats = self.vera.cost_tracker.get_stats()
            metrics["budget_used_percent"] = cost_stats.get("budget_used_percent", 0)
            metrics["session_cost"] = cost_stats.get("session_cost", 0)

        if self.vera and hasattr(self.vera, 'decision_ledger'):
            decision_stats = self.vera.decision_ledger.get_stats()
            metrics["decisions_logged"] = decision_stats.get("total_decisions", 0)

        return metrics

    async def _generate_calendar_section(self, max_items: int) -> Dict[str, Any]:
        """Generate calendar section (placeholder)."""
        return {
            "today": datetime.now().date().isoformat(),
            "events": [],
            "note": "Calendar integration not configured"
        }

    async def _generate_weather_section(self) -> Dict[str, Any]:
        """Generate weather section (placeholder)."""
        return {
            "note": "Weather integration not configured",
            "tip": "Configure weather API to enable forecasts"
        }

    async def _generate_news_section(self, max_items: int) -> Dict[str, Any]:
        """Generate news section (placeholder)."""
        return {
            "headlines": [],
            "note": "News integration not configured"
        }

    async def _generate_reminders_section(self, max_items: int) -> Dict[str, Any]:
        """Generate reminders section (placeholder)."""
        return {
            "pending": [],
            "note": "Reminder system not configured"
        }

    def _generate_summary(
        self,
        content: Dict[str, Any],
        config: BriefingConfig
    ) -> str:
        """Generate a natural language summary of the briefing."""
        lines = [f"# {config.name}", ""]
        lines.append(f"Generated: {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}")
        lines.append("")

        # Tasks summary
        if "tasks" in content:
            tasks = content["tasks"]
            lines.append("## Tasks")
            pending = tasks.get("pending_count", 0)
            overdue = tasks.get("overdue_count", 0)

            if pending > 0:
                lines.append(f"- **{pending}** pending tasks")
                if overdue > 0:
                    lines.append(f"- **{overdue}** overdue (!)".upper())

                top_tasks = tasks.get("top_pending", [])
                if top_tasks:
                    lines.append("\nTop priorities:")
                    for t in top_tasks[:3]:
                        lines.append(f"  - [{t['priority']}] {t['title']}")
            else:
                lines.append("- All caught up!")
            lines.append("")

        # Health summary
        if "health" in content:
            health = content["health"]
            status = health.get("status", "unknown")
            lines.append("## System Status")
            if status == "healthy":
                lines.append("- System is healthy and operational")
            else:
                lines.append(f"- System status: {status}")
                for warning in health.get("warnings", []):
                    lines.append(f"  - Warning: {warning}")
            lines.append("")

        # Goals summary
        if "goals" in content:
            goals = content["goals"]
            active = goals.get("active_projects", 0)
            lines.append("## Active Projects")
            if active > 0:
                lines.append(f"- **{active}** projects in progress")
                for p in goals.get("projects", [])[:3]:
                    progress = p.get("progress", 0)
                    lines.append(f"  - {p['title']} ({progress}%)")
            else:
                lines.append("- No active projects")
            lines.append("")

        # Metrics summary
        if "metrics" in content:
            metrics = content["metrics"]
            lines.append("## Metrics")
            if "budget_used_percent" in metrics:
                lines.append(f"- Budget: {metrics['budget_used_percent']:.1f}% used")
            if "decisions_logged" in metrics:
                lines.append(f"- Decisions logged: {metrics['decisions_logged']}")
            lines.append("")

        return "\n".join(lines)

    def _record_briefing(self, briefing: Briefing) -> None:
        """Record briefing to history."""
        record = {
            "briefing_id": briefing.briefing_id,
            "type": briefing.briefing_type.value,
            "generated_at": briefing.generated_at.isoformat(),
            "word_count": briefing.word_count,
            "generation_time_ms": briefing.generation_time_ms
        }

        with open(self.history_file, 'a') as f:
            f.write(json.dumps(record) + "\n")

    def _save_briefing_file(self, briefing: Briefing) -> None:
        """Save briefing to a markdown file."""
        date_str = briefing.generated_at.strftime("%Y-%m-%d")
        filename = f"briefing_{date_str}_{briefing.briefing_type.value}.md"
        filepath = self.briefings_dir / filename

        filepath.write_text(briefing.summary)

    async def start_scheduler(self) -> None:
        """Start the briefing scheduler."""
        if self._running:
            return

        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info("Briefing scheduler started")

    async def stop_scheduler(self) -> None:
        """Stop the briefing scheduler."""
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        logger.info("Briefing scheduler stopped")

    async def _scheduler_loop(self) -> None:
        """Background loop for scheduled briefings."""
        while self._running:
            try:
                now = datetime.now()

                for name, config in self._configs.items():
                    if not config.enabled:
                        continue

                    # Check if it's time
                    if now.weekday() not in config.days:
                        continue

                    scheduled = datetime.combine(now.date(), config.schedule_time)

                    # Check if within 1 minute of scheduled time
                    if abs((now - scheduled).total_seconds()) < 60:
                        # Check if we already ran today
                        if self._should_run_today(config):
                            logger.info(f"Generating scheduled briefing: {name}")
                            await self.generate_briefing(
                                config.briefing_type,
                                config_name=name
                            )

                # Update next scheduled time
                self._update_next_scheduled()

                # Sleep for 30 seconds
                await asyncio.sleep(30)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                await asyncio.sleep(60)

    def _should_run_today(self, config: BriefingConfig) -> bool:
        """Check if briefing should run today."""
        if not self._stats.last_briefing_time:
            return True

        last_date = self._stats.last_briefing_time.date()
        today = datetime.now().date()

        return last_date != today

    def _update_next_scheduled(self) -> None:
        """Calculate next scheduled briefing time."""
        now = datetime.now()
        next_time = None

        for config in self._configs.values():
            if not config.enabled:
                continue

            # Find next occurrence
            for day_offset in range(8):  # Check up to a week ahead
                check_date = now.date() + timedelta(days=day_offset)
                if check_date.weekday() not in config.days:
                    continue

                scheduled = datetime.combine(check_date, config.schedule_time)
                if scheduled > now:
                    if next_time is None or scheduled < next_time:
                        next_time = scheduled
                    break

        self._stats.next_scheduled_time = next_time

    def get_stats(self) -> Dict[str, Any]:
        """Get cadence system statistics."""
        self._update_next_scheduled()

        return {
            "total_briefings": self._stats.total_briefings,
            "last_briefing": self._stats.last_briefing_time.isoformat() if self._stats.last_briefing_time else None,
            "next_scheduled": self._stats.next_scheduled_time.isoformat() if self._stats.next_scheduled_time else None,
            "enabled_configs": sum(1 for c in self._configs.values() if c.enabled),
            "briefings_by_type": self._stats.briefings_by_type,
            "scheduler_running": self._running
        }

    def get_recent_briefings(self, limit: int = 10) -> List[Dict]:
        """Get recent briefing history."""
        if not self.history_file.exists():
            return []

        briefings = []
        with open(self.history_file) as f:
            for line in f:
                try:
                    briefings.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        return briefings[-limit:]


# === Self-test ===

if __name__ == "__main__":
    import sys

    async def test_cadence():
        """Test morning briefing generator."""
        print("Testing Morning Briefing Generator...")

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test 1: Create generator
            print("Test 1: Create generator...", end=" ")
            generator = MorningBriefingGenerator(memory_dir=Path(tmpdir))
            print("PASS")

            # Test 2: Check default configs
            print("Test 2: Default configs...", end=" ")
            assert "morning" in generator._configs
            assert "evening" in generator._configs
            assert "weekly" in generator._configs
            print("PASS")

            # Test 3: Generate morning briefing
            print("Test 3: Generate morning briefing...", end=" ")
            briefing = await generator.generate_briefing(BriefingType.MORNING)
            assert briefing.briefing_id.startswith("brief-")
            assert briefing.briefing_type == BriefingType.MORNING
            assert len(briefing.summary) > 0
            print("PASS")

            # Test 4: Check briefing content
            print("Test 4: Briefing content...", end=" ")
            assert "tasks" in briefing.content
            assert "health" in briefing.content
            print("PASS")

            # Test 5: Check history
            print("Test 5: Briefing history...", end=" ")
            history = generator.get_recent_briefings()
            assert len(history) == 1
            assert history[0]["type"] == "morning"
            print("PASS")

            # Test 6: Check file saved
            print("Test 6: Briefing file...", end=" ")
            files = list(generator.briefings_dir.glob("*.md"))
            assert len(files) == 1
            print("PASS")

            # Test 7: Stats
            print("Test 7: Stats...", end=" ")
            stats = generator.get_stats()
            assert stats["total_briefings"] == 1
            assert stats["enabled_configs"] >= 3
            print("PASS")

            # Test 8: Custom section generator
            print("Test 8: Custom section...", end=" ")

            async def custom_generator(max_items):
                return {"custom_data": "test", "items": max_items}

            generator.register_section_generator(
                BriefingSection.CUSTOM,
                custom_generator
            )

            # Configure briefing with custom section
            generator.configure("test", BriefingConfig(
                name="Test Briefing",
                briefing_type=BriefingType.ADHOC,
                schedule_time=time(12, 0),
                sections=[BriefingSection.CUSTOM]
            ))

            briefing2 = await generator.generate_briefing(
                BriefingType.ADHOC,
                config_name="test"
            )
            assert "custom" in briefing2.content
            assert briefing2.content["custom"]["custom_data"] == "test"
            print("PASS")

            # Test 9: Evening briefing
            print("Test 9: Evening briefing...", end=" ")
            briefing3 = await generator.generate_briefing(BriefingType.EVENING)
            assert briefing3.briefing_type == BriefingType.EVENING
            print("PASS")

            # Test 10: Stats after multiple
            print("Test 10: Final stats...", end=" ")
            stats = generator.get_stats()
            assert stats["total_briefings"] == 3
            assert "morning" in stats["briefings_by_type"]
            print("PASS")

        print("\nAll tests passed!")
        return True

    success = asyncio.run(test_cadence())
    sys.exit(0 if success else 1)

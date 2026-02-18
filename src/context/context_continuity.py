"""
Context Continuity for VERA.

Provides session continuity across restarts, context summarization,
and working memory management.

Inspired by GROKSTAR's sliding window + rolling summary memory architecture.
"""

import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ContextType(Enum):
    """Types of context data."""
    CONVERSATION = "conversation"   # Chat history
    TASK = "task"                  # Task-related context
    FILE = "file"                  # File operations context
    DECISION = "decision"          # Decision context
    USER_PREF = "user_pref"        # User preferences
    SESSION = "session"            # Session metadata


class ContextPriority(Enum):
    """Priority levels for context retention."""
    CRITICAL = 0    # Always keep
    HIGH = 1        # Keep unless space constrained
    MEDIUM = 2      # Summarize when old
    LOW = 3         # Drop when old


@dataclass
class ContextEntry:
    """A single piece of context."""
    context_id: str
    context_type: ContextType
    priority: ContextPriority
    created_at: datetime
    updated_at: datetime
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Token tracking
    token_estimate: int = 0

    # References
    related_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context_id": self.context_id,
            "context_type": self.context_type.value,
            "priority": self.priority.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "content": self.content,
            "metadata": self.metadata,
            "token_estimate": self.token_estimate,
            "related_ids": self.related_ids
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ContextEntry":
        return cls(
            context_id=data.get("context_id", ""),
            context_type=ContextType(data.get("context_type", "")),
            priority=ContextPriority(data.get("priority", "")),
            created_at=datetime.fromisoformat(data.get("created_at", "")),
            updated_at=datetime.fromisoformat(data.get("updated_at", "")),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
            token_estimate=data.get("token_estimate", 0),
            related_ids=data.get("related_ids", [])
        )


@dataclass
class ContextSummary:
    """Summarized context for long-term storage."""
    summary_id: str
    original_ids: List[str]
    context_types: List[ContextType]
    time_range: Tuple[datetime, datetime]
    summary: str
    key_points: List[str]
    token_estimate: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary_id": self.summary_id,
            "original_ids": self.original_ids,
            "context_types": [t.value for t in self.context_types],
            "time_range": [self.time_range[0].isoformat(), self.time_range[1].isoformat()],
            "summary": self.summary,
            "key_points": self.key_points,
            "token_estimate": self.token_estimate
        }


@dataclass
class SessionState:
    """Persistent session state."""
    session_id: str
    started_at: datetime
    last_activity: datetime
    conversation_count: int = 0
    task_count: int = 0
    context_summary: Optional[str] = None

    # Working memory
    active_context_ids: List[str] = field(default_factory=list)
    active_task_ids: List[str] = field(default_factory=list)

    # Session-specific data
    user_name: Optional[str] = None
    current_topic: Optional[str] = None
    pending_actions: List[Dict] = field(default_factory=list)


class ContextContinuityManager:
    """
    Manages context continuity across sessions.

    Features:
    - Sliding window for recent context (full detail)
    - Rolling summaries for older context
    - Session state persistence
    - Context-aware retrieval
    - Token budget management
    """

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        sliding_window_size: int = 20,      # Number of recent entries to keep
        summary_threshold: int = 10,         # Entries before summarization
        max_token_budget: int = 8000        # Token limit for context
    ):
        """
        Initialize context continuity manager.

        Args:
            memory_dir: Directory for persistence
            sliding_window_size: Recent entries to keep in full
            summary_threshold: Entries that trigger summarization
            max_token_budget: Maximum tokens for context window
        """
        if memory_dir:
            self.memory_dir = Path(memory_dir)
        else:
            self.memory_dir = Path("vera_memory")

        self.context_dir = self.memory_dir / "context"
        self.context_dir.mkdir(parents=True, exist_ok=True)

        self.entries_file = self.context_dir / "context_entries.json"
        self.summaries_file = self.context_dir / "context_summaries.json"
        self.session_file = self.context_dir / "session_state.json"

        self.sliding_window_size = sliding_window_size
        self.summary_threshold = summary_threshold
        self.max_token_budget = max_token_budget

        # State
        self._entries: Dict[str, ContextEntry] = {}
        self._summaries: List[ContextSummary] = []
        self._session: Optional[SessionState] = None

        # Load existing state
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state."""
        # Load entries
        if self.entries_file.exists():
            try:
                with open(self.entries_file) as f:
                    data = json.load(f)
                for entry_data in data.get("entries", []):
                    entry = ContextEntry.from_dict(entry_data)
                    self._entries[entry.context_id] = entry
            except Exception as e:
                logger.error(f"Failed to load context entries: {e}")

        # Load summaries
        if self.summaries_file.exists():
            try:
                with open(self.summaries_file) as f:
                    data = json.load(f)
                for summary_data in data.get("summaries", []):
                    self._summaries.append(ContextSummary(
                        summary_id=summary_data.get("summary_id", ""),
                        original_ids=summary_data.get("original_ids", ""),
                        context_types=[ContextType(t) for t in summary_data.get("context_types", "")],
                        time_range=(
                            datetime.fromisoformat(summary_data.get("time_range", "")[0]),
                            datetime.fromisoformat(summary_data.get("time_range", "")[1])
                        ),
                        summary=summary_data.get("summary", ""),
                        key_points=summary_data.get("key_points", []),
                        token_estimate=summary_data.get("token_estimate", 0)
                    ))
            except Exception as e:
                logger.error(f"Failed to load context summaries: {e}")

        # Load session
        if self.session_file.exists():
            try:
                with open(self.session_file) as f:
                    data = json.load(f)
                self._session = SessionState(
                    session_id=data.get("session_id", ""),
                    started_at=datetime.fromisoformat(data.get("started_at", "")),
                    last_activity=datetime.fromisoformat(data.get("last_activity", "")),
                    conversation_count=data.get("conversation_count", 0),
                    task_count=data.get("task_count", 0),
                    context_summary=data.get("context_summary"),
                    active_context_ids=data.get("active_context_ids", []),
                    active_task_ids=data.get("active_task_ids", []),
                    user_name=data.get("user_name"),
                    current_topic=data.get("current_topic"),
                    pending_actions=data.get("pending_actions", [])
                )
            except Exception as e:
                logger.error(f"Failed to load session state: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        # Save entries
        entries_data = {"entries": [e.to_dict() for e in self._entries.values()]}
        with open(self.entries_file, 'w') as f:
            json.dump(entries_data, f, indent=2)

        # Save summaries
        summaries_data = {"summaries": [s.to_dict() for s in self._summaries]}
        with open(self.summaries_file, 'w') as f:
            json.dump(summaries_data, f, indent=2)

        # Save session
        if self._session:
            session_data = {
                "session_id": self._session.session_id,
                "started_at": self._session.started_at.isoformat(),
                "last_activity": self._session.last_activity.isoformat(),
                "conversation_count": self._session.conversation_count,
                "task_count": self._session.task_count,
                "context_summary": self._session.context_summary,
                "active_context_ids": self._session.active_context_ids,
                "active_task_ids": self._session.active_task_ids,
                "user_name": self._session.user_name,
                "current_topic": self._session.current_topic,
                "pending_actions": self._session.pending_actions
            }
            with open(self.session_file, 'w') as f:
                json.dump(session_data, f, indent=2)

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        # Rough estimate: ~4 chars per token
        return len(text) // 4

    def _generate_id(self, prefix: str) -> str:
        """Generate a unique ID."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        hash_input = f"{prefix}-{timestamp}"
        return f"{prefix}-{hashlib.md5(hash_input.encode()).hexdigest()[:12]}"

    def start_session(
        self,
        session_id: Optional[str] = None,
        user_name: Optional[str] = None
    ) -> SessionState:
        """
        Start or resume a session.

        Args:
            session_id: Optional ID for resuming
            user_name: Optional user name

        Returns:
            SessionState object
        """
        if self._session and session_id == self._session.session_id:
            # Resume existing session
            self._session.last_activity = datetime.now()
        else:
            # New session
            self._session = SessionState(
                session_id=session_id or self._generate_id("session"),
                started_at=datetime.now(),
                last_activity=datetime.now(),
                user_name=user_name
            )

        self._save_state()
        return self._session

    def add_context(
        self,
        content: str,
        context_type: ContextType = ContextType.CONVERSATION,
        priority: ContextPriority = ContextPriority.MEDIUM,
        metadata: Optional[Dict] = None,
        related_ids: Optional[List[str]] = None
    ) -> ContextEntry:
        """
        Add a new context entry.

        Args:
            content: Context content
            context_type: Type of context
            priority: Retention priority
            metadata: Optional metadata
            related_ids: Related context IDs

        Returns:
            Created ContextEntry
        """
        entry = ContextEntry(
            context_id=self._generate_id("ctx"),
            context_type=context_type,
            priority=priority,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            content=content,
            metadata=metadata or {},
            token_estimate=self._estimate_tokens(content),
            related_ids=related_ids or []
        )

        self._entries[entry.context_id] = entry

        # Update session
        if self._session:
            self._session.last_activity = datetime.now()
            self._session.active_context_ids.append(entry.context_id)

            if context_type == ContextType.CONVERSATION:
                self._session.conversation_count += 1
            elif context_type == ContextType.TASK:
                self._session.task_count += 1

        # Check if summarization needed
        self._check_summarization_needed()

        self._save_state()
        return entry

    def update_context(
        self,
        context_id: str,
        content: Optional[str] = None,
        priority: Optional[ContextPriority] = None,
        metadata: Optional[Dict] = None
    ) -> Optional[ContextEntry]:
        """
        Update an existing context entry.

        Args:
            context_id: ID of entry to update
            content: New content (optional)
            priority: New priority (optional)
            metadata: Metadata to merge (optional)

        Returns:
            Updated entry or None if not found
        """
        entry = self._entries.get(context_id)
        if not entry:
            return None

        if content is not None:
            entry.content = content
            entry.token_estimate = self._estimate_tokens(content)

        if priority is not None:
            entry.priority = priority

        if metadata is not None:
            entry.metadata.update(metadata)

        entry.updated_at = datetime.now()
        self._save_state()

        return entry

    def get_context(self, context_id: str) -> Optional[ContextEntry]:
        """Get a specific context entry."""
        return self._entries.get(context_id)

    def get_recent_context(
        self,
        limit: int = None,
        context_type: Optional[ContextType] = None
    ) -> List[ContextEntry]:
        """
        Get recent context entries.

        Args:
            limit: Maximum entries to return
            context_type: Filter by type

        Returns:
            List of recent entries
        """
        entries = list(self._entries.values())

        # Filter by type
        if context_type:
            entries = [e for e in entries if e.context_type == context_type]

        # Sort by recency
        entries.sort(key=lambda e: e.updated_at, reverse=True)

        # Apply limit
        if limit:
            entries = entries[:limit]

        return entries

    def _check_summarization_needed(self) -> None:
        """Check if summarization is needed and trigger if so."""
        entries = self.get_recent_context()

        # Check if we have too many low-priority entries
        low_priority = [
            e for e in entries
            if e.priority.value >= ContextPriority.MEDIUM.value
        ]

        if len(low_priority) > self.sliding_window_size + self.summary_threshold:
            self._summarize_old_entries(low_priority)

    def _summarize_old_entries(self, entries: List[ContextEntry]) -> None:
        """Summarize old entries to free space."""
        # Keep recent entries
        entries.sort(key=lambda e: e.updated_at, reverse=True)
        to_summarize = entries[self.sliding_window_size:]

        if len(to_summarize) < self.summary_threshold:
            return

        # Group by day for summarization
        grouped = {}
        for entry in to_summarize:
            date_key = entry.updated_at.date().isoformat()
            if date_key not in grouped:
                grouped[date_key] = []
            grouped[date_key].append(entry)

        for date_key, group in grouped.items():
            if len(group) < 3:  # Don't summarize tiny groups
                continue

            # Create summary
            content_parts = [e.content[:200] for e in group]
            context_types = list(set(e.context_type for e in group))
            time_range = (
                min(e.created_at for e in group),
                max(e.updated_at for e in group)
            )

            summary = ContextSummary(
                summary_id=self._generate_id("sum"),
                original_ids=[e.context_id for e in group],
                context_types=context_types,
                time_range=time_range,
                summary=self._generate_summary_text(group),
                key_points=self._extract_key_points(group),
                token_estimate=self._estimate_tokens(
                    self._generate_summary_text(group)
                )
            )

            self._summaries.append(summary)

            # Remove summarized entries
            for entry in group:
                if entry.priority.value >= ContextPriority.MEDIUM.value:
                    del self._entries[entry.context_id]

    def _generate_summary_text(self, entries: List[ContextEntry]) -> str:
        """Generate summary text from entries."""
        types = set(e.context_type.value for e in entries)
        time_range = f"{entries[-1].created_at.strftime('%H:%M')} - {entries[0].updated_at.strftime('%H:%M')}"

        lines = [
            f"Context summary ({len(entries)} entries, {', '.join(types)})",
            f"Time: {time_range}",
            ""
        ]

        # Sample content from entries
        for entry in entries[:5]:
            preview = entry.content[:100].replace("\n", " ")
            lines.append(f"- [{entry.context_type.value}] {preview}...")

        if len(entries) > 5:
            lines.append(f"- ... and {len(entries) - 5} more entries")

        return "\n".join(lines)

    def _extract_key_points(self, entries: List[ContextEntry]) -> List[str]:
        """Extract key points from entries."""
        key_points = []

        for entry in entries:
            # Extract important-looking content
            if "important" in entry.content.lower():
                key_points.append(entry.content[:100])
            elif "task" in entry.content.lower():
                key_points.append(entry.content[:100])
            elif "decision" in entry.content.lower():
                key_points.append(entry.content[:100])

        return key_points[:5]  # Limit to 5

    def build_context_window(
        self,
        max_tokens: Optional[int] = None,
        include_summaries: bool = True
    ) -> str:
        """
        Build a context window for prompts.

        Args:
            max_tokens: Maximum token budget
            include_summaries: Include historical summaries

        Returns:
            Formatted context string
        """
        max_tokens = max_tokens or self.max_token_budget
        used_tokens = 0
        parts = []

        # Add session context
        if self._session:
            session_context = self._format_session_context()
            session_tokens = self._estimate_tokens(session_context)
            if used_tokens + session_tokens < max_tokens:
                parts.append(session_context)
                used_tokens += session_tokens

        # Add recent context (most important first)
        entries = self.get_recent_context()
        entries.sort(key=lambda e: (e.priority.value, -e.updated_at.timestamp()))

        for entry in entries[:self.sliding_window_size]:
            entry_text = self._format_entry(entry)
            entry_tokens = self._estimate_tokens(entry_text)

            if used_tokens + entry_tokens > max_tokens:
                break

            parts.append(entry_text)
            used_tokens += entry_tokens

        # Add summaries if space
        if include_summaries:
            for summary in reversed(self._summaries[-5:]):
                summary_text = f"[Summary] {summary.summary}"
                summary_tokens = self._estimate_tokens(summary_text)

                if used_tokens + summary_tokens > max_tokens:
                    break

                parts.append(summary_text)
                used_tokens += summary_tokens

        return "\n\n".join(parts)

    def _format_session_context(self) -> str:
        """Format session context."""
        if not self._session:
            return ""

        lines = ["=== Session Context ==="]

        if self._session.user_name:
            lines.append(f"User: {self._session.user_name}")

        lines.append(f"Session: {self._session.session_id}")
        lines.append(f"Duration: {(datetime.now() - self._session.started_at).seconds // 60} minutes")

        if self._session.current_topic:
            lines.append(f"Current topic: {self._session.current_topic}")

        if self._session.pending_actions:
            lines.append(f"Pending actions: {len(self._session.pending_actions)}")

        return "\n".join(lines)

    def _format_entry(self, entry: ContextEntry) -> str:
        """Format a context entry for display."""
        age = datetime.now() - entry.updated_at
        if age.total_seconds() < 60:
            age_str = "just now"
        elif age.total_seconds() < 3600:
            age_str = f"{int(age.total_seconds() / 60)}m ago"
        else:
            age_str = f"{int(age.total_seconds() / 3600)}h ago"

        return f"[{entry.context_type.value}] ({age_str}) {entry.content}"

    def set_current_topic(self, topic: str) -> None:
        """Set the current conversation topic."""
        if self._session:
            self._session.current_topic = topic
            self._save_state()

    def add_pending_action(self, action: Dict) -> None:
        """Add a pending action to track."""
        if self._session:
            self._session.pending_actions.append(action)
            self._save_state()

    def complete_pending_action(self, action_id: str) -> None:
        """Mark a pending action as complete."""
        if self._session:
            self._session.pending_actions = [
                a for a in self._session.pending_actions
                if a.get("id") != action_id
            ]
            self._save_state()

    def get_session_summary(self) -> str:
        """Get a summary of the current session."""
        if not self._session:
            return "No active session"

        duration = datetime.now() - self._session.started_at
        mins = duration.seconds // 60

        lines = [
            f"Session: {self._session.session_id}",
            f"Duration: {mins} minutes",
            f"Conversations: {self._session.conversation_count}",
            f"Tasks: {self._session.task_count}",
        ]

        if self._session.current_topic:
            lines.append(f"Current topic: {self._session.current_topic}")

        if self._session.pending_actions:
            lines.append(f"Pending actions: {len(self._session.pending_actions)}")

        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """Get context continuity statistics."""
        return {
            "total_entries": len(self._entries),
            "total_summaries": len(self._summaries),
            "session_active": self._session is not None,
            "session_id": self._session.session_id if self._session else None,
            "token_estimate": sum(e.token_estimate for e in self._entries.values()),
            "max_token_budget": self.max_token_budget,
            "context_types": {
                t.value: sum(1 for e in self._entries.values() if e.context_type == t)
                for t in ContextType
            }
        }


# === Self-test ===

if __name__ == "__main__":
    import sys

    def test_continuity():
        """Test context continuity manager."""
        print("Testing Context Continuity Manager...")

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test 1: Create manager
            print("Test 1: Create manager...", end=" ")
            manager = ContextContinuityManager(memory_dir=Path(tmpdir))
            print("PASS")

            # Test 2: Start session
            print("Test 2: Start session...", end=" ")
            session = manager.start_session(user_name="Test User")
            assert session.session_id is not None
            assert session.user_name == "Test User"
            print("PASS")

            # Test 3: Add context
            print("Test 3: Add context...", end=" ")
            entry = manager.add_context(
                "User asked about weather",
                context_type=ContextType.CONVERSATION
            )
            assert entry.context_id is not None
            assert entry.token_estimate > 0
            print("PASS")

            # Test 4: Get recent context
            print("Test 4: Get recent context...", end=" ")
            recent = manager.get_recent_context(limit=5)
            assert len(recent) == 1
            assert recent[0].context_id == entry.context_id
            print("PASS")

            # Test 5: Update context
            print("Test 5: Update context...", end=" ")
            updated = manager.update_context(
                entry.context_id,
                priority=ContextPriority.HIGH
            )
            assert updated.priority == ContextPriority.HIGH
            print("PASS")

            # Test 6: Set topic
            print("Test 6: Set topic...", end=" ")
            manager.set_current_topic("Weather discussion")
            assert manager._session.current_topic == "Weather discussion"
            print("PASS")

            # Test 7: Add multiple contexts
            print("Test 7: Multiple contexts...", end=" ")
            for i in range(5):
                manager.add_context(
                    f"Context entry {i}",
                    context_type=ContextType.CONVERSATION
                )
            assert len(manager._entries) == 6
            print("PASS")

            # Test 8: Build context window
            print("Test 8: Context window...", end=" ")
            window = manager.build_context_window(max_tokens=1000)
            assert len(window) > 0
            assert "Session Context" in window
            print("PASS")

            # Test 9: Pending actions
            print("Test 9: Pending actions...", end=" ")
            manager.add_pending_action({"id": "action1", "type": "reminder"})
            assert len(manager._session.pending_actions) == 1
            manager.complete_pending_action("action1")
            assert len(manager._session.pending_actions) == 0
            print("PASS")

            # Test 10: Session summary
            print("Test 10: Session summary...", end=" ")
            summary = manager.get_session_summary()
            assert "Session:" in summary
            assert "Weather discussion" in summary
            print("PASS")

            # Test 11: Stats
            print("Test 11: Stats...", end=" ")
            stats = manager.get_stats()
            assert stats["total_entries"] == 6
            assert stats["session_active"] == True
            print("PASS")

            # Test 12: Persistence
            print("Test 12: Persistence...", end=" ")
            manager2 = ContextContinuityManager(memory_dir=Path(tmpdir))
            assert len(manager2._entries) == 6
            assert manager2._session.session_id == session.session_id
            print("PASS")

        print("\nAll tests passed!")
        return True

    success = test_continuity()
    sys.exit(0 if success else 1)

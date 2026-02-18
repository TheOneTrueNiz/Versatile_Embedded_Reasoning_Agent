"""
Conversation Bookmarks for VERA.

Allows users to save and recall important conversation moments,
decisions, and context for future reference.
"""

import json
import hashlib
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class BookmarkType(Enum):
    """Types of bookmarks."""
    IMPORTANT = "important"      # General important moment
    DECISION = "decision"        # A decision was made
    ACTION_ITEM = "action_item"  # Something to follow up on
    REFERENCE = "reference"      # Reference information
    IDEA = "idea"               # An idea to remember
    QUESTION = "question"       # Question to revisit
    MILESTONE = "milestone"     # Project milestone
    CUSTOM = "custom"          # User-defined type


@dataclass
class Bookmark:
    """A saved conversation bookmark."""
    bookmark_id: str
    bookmark_type: BookmarkType
    created_at: datetime
    title: str
    content: str

    # Context
    conversation_id: Optional[str] = None
    message_index: Optional[int] = None
    context_before: Optional[str] = None
    context_after: Optional[str] = None

    # Organization
    tags: List[str] = field(default_factory=list)
    priority: int = 2  # 0-3
    starred: bool = False

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bookmark_id": self.bookmark_id,
            "bookmark_type": self.bookmark_type.value,
            "created_at": self.created_at.isoformat(),
            "title": self.title,
            "content": self.content,
            "conversation_id": self.conversation_id,
            "message_index": self.message_index,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "tags": self.tags,
            "priority": self.priority,
            "starred": self.starred,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "Bookmark":
        return cls(
            bookmark_id=data.get("bookmark_id", ""),
            bookmark_type=BookmarkType(data.get("bookmark_type", "")),
            created_at=datetime.fromisoformat(data.get("created_at", "")),
            title=data.get("title", ""),
            content=data.get("content", ""),
            conversation_id=data.get("conversation_id"),
            message_index=data.get("message_index"),
            context_before=data.get("context_before"),
            context_after=data.get("context_after"),
            tags=data.get("tags", []),
            priority=data.get("priority", 2),
            starred=data.get("starred", False),
            metadata=data.get("metadata", {})
        )

    def matches_query(self, query: str) -> bool:
        """Check if bookmark matches search query."""
        query = query.lower()
        return (
            query in self.title.lower() or
            query in self.content.lower() or
            any(query in tag.lower() for tag in self.tags)
        )


class BookmarkManager:
    """
    Manages conversation bookmarks for VERA.

    Features:
    - Create bookmarks from conversation moments
    - Tag and categorize bookmarks
    - Search and filter bookmarks
    - Export to markdown
    - Integration with conversation context
    """

    def __init__(self, memory_dir: Optional[Path] = None) -> None:
        """
        Initialize bookmark manager.

        Args:
            memory_dir: Directory for persistence
        """
        if memory_dir:
            self.memory_dir = Path(memory_dir)
        else:
            self.memory_dir = Path("vera_memory")

        self.bookmarks_dir = self.memory_dir / "bookmarks"
        self.bookmarks_dir.mkdir(parents=True, exist_ok=True)

        self.storage_file = self.bookmarks_dir / "bookmarks.json"

        # State
        self._bookmarks: Dict[str, Bookmark] = {}

        # Load state
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state."""
        if self.storage_file.exists():
            try:
                with open(self.storage_file) as f:
                    data = json.load(f)

                for bookmark_data in data.get("bookmarks", []):
                    bookmark = Bookmark.from_dict(bookmark_data)
                    self._bookmarks[bookmark.bookmark_id] = bookmark

            except Exception as e:
                logger.error(f"Failed to load bookmarks: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        data = {
            "bookmarks": [b.to_dict() for b in self._bookmarks.values()]
        }

        with open(self.storage_file, 'w') as f:
            json.dump(data, f, indent=2)

    def _generate_id(self) -> str:
        """Generate a unique bookmark ID."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
        hash_input = f"bookmark-{timestamp}"
        return f"bm-{hashlib.md5(hash_input.encode()).hexdigest()[:8]}"

    def create_bookmark(
        self,
        title: str,
        content: str,
        bookmark_type: BookmarkType = BookmarkType.IMPORTANT,
        tags: Optional[List[str]] = None,
        priority: int = 2,
        conversation_id: Optional[str] = None,
        context_before: Optional[str] = None,
        context_after: Optional[str] = None,
        metadata: Optional[Dict] = None
    ) -> Bookmark:
        """
        Create a new bookmark.

        Args:
            title: Bookmark title
            content: Main content to save
            bookmark_type: Type of bookmark
            tags: Optional tags for organization
            priority: Priority level (0-3)
            conversation_id: Associated conversation
            context_before: Context from before the moment
            context_after: Context from after
            metadata: Optional metadata

        Returns:
            Created Bookmark
        """
        bookmark = Bookmark(
            bookmark_id=self._generate_id(),
            bookmark_type=bookmark_type,
            created_at=datetime.now(),
            title=title,
            content=content,
            conversation_id=conversation_id,
            context_before=context_before,
            context_after=context_after,
            tags=tags or [],
            priority=priority,
            metadata=metadata or {}
        )

        self._bookmarks[bookmark.bookmark_id] = bookmark
        self._save_state()

        return bookmark

    def get_bookmark(self, bookmark_id: str) -> Optional[Bookmark]:
        """Get a bookmark by ID."""
        return self._bookmarks.get(bookmark_id)

    def update_bookmark(
        self,
        bookmark_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None,
        priority: Optional[int] = None,
        starred: Optional[bool] = None
    ) -> Optional[Bookmark]:
        """
        Update an existing bookmark.

        Args:
            bookmark_id: ID of bookmark to update
            title: New title (optional)
            content: New content (optional)
            tags: New tags (optional)
            priority: New priority (optional)
            starred: New starred status (optional)

        Returns:
            Updated bookmark or None
        """
        bookmark = self._bookmarks.get(bookmark_id)
        if not bookmark:
            return None

        if title is not None:
            bookmark.title = title
        if content is not None:
            bookmark.content = content
        if tags is not None:
            bookmark.tags = tags
        if priority is not None:
            bookmark.priority = priority
        if starred is not None:
            bookmark.starred = starred

        self._save_state()
        return bookmark

    def delete_bookmark(self, bookmark_id: str) -> bool:
        """
        Delete a bookmark.

        Args:
            bookmark_id: ID of bookmark to delete

        Returns:
            True if deleted
        """
        if bookmark_id in self._bookmarks:
            del self._bookmarks[bookmark_id]
            self._save_state()
            return True
        return False

    def star_bookmark(self, bookmark_id: str, starred: bool = True) -> Optional[Bookmark]:
        """Toggle starred status."""
        return self.update_bookmark(bookmark_id, starred=starred)

    def add_tag(self, bookmark_id: str, tag: str) -> Optional[Bookmark]:
        """Add a tag to a bookmark."""
        bookmark = self._bookmarks.get(bookmark_id)
        if not bookmark:
            return None

        if tag not in bookmark.tags:
            bookmark.tags.append(tag)
            self._save_state()

        return bookmark

    def remove_tag(self, bookmark_id: str, tag: str) -> Optional[Bookmark]:
        """Remove a tag from a bookmark."""
        bookmark = self._bookmarks.get(bookmark_id)
        if not bookmark:
            return None

        if tag in bookmark.tags:
            bookmark.tags.remove(tag)
            self._save_state()

        return bookmark

    def search(
        self,
        query: Optional[str] = None,
        bookmark_type: Optional[BookmarkType] = None,
        tags: Optional[List[str]] = None,
        starred_only: bool = False,
        limit: int = 50
    ) -> List[Bookmark]:
        """
        Search bookmarks.

        Args:
            query: Text search query
            bookmark_type: Filter by type
            tags: Filter by tags (any match)
            starred_only: Only starred bookmarks
            limit: Maximum results

        Returns:
            List of matching bookmarks
        """
        results = list(self._bookmarks.values())

        # Filter by query
        if query:
            results = [b for b in results if b.matches_query(query)]

        # Filter by type
        if bookmark_type:
            results = [b for b in results if b.bookmark_type == bookmark_type]

        # Filter by tags
        if tags:
            results = [
                b for b in results
                if any(tag in b.tags for tag in tags)
            ]

        # Filter by starred
        if starred_only:
            results = [b for b in results if b.starred]

        # Sort by priority then date
        results.sort(key=lambda b: (b.priority, -b.created_at.timestamp()))

        return results[:limit]

    def get_recent(self, limit: int = 10) -> List[Bookmark]:
        """Get most recent bookmarks."""
        bookmarks = list(self._bookmarks.values())
        bookmarks.sort(key=lambda b: b.created_at, reverse=True)
        return bookmarks[:limit]

    def get_by_type(self, bookmark_type: BookmarkType) -> List[Bookmark]:
        """Get all bookmarks of a specific type."""
        return [
            b for b in self._bookmarks.values()
            if b.bookmark_type == bookmark_type
        ]

    def get_starred(self) -> List[Bookmark]:
        """Get all starred bookmarks."""
        return [b for b in self._bookmarks.values() if b.starred]

    def get_all_tags(self) -> Dict[str, int]:
        """Get all tags with counts."""
        tags = {}
        for bookmark in self._bookmarks.values():
            for tag in bookmark.tags:
                tags[tag] = tags.get(tag, 0) + 1
        return dict(sorted(tags.items(), key=lambda x: -x[1]))

    def export_markdown(
        self,
        bookmarks: Optional[List[Bookmark]] = None,
        include_context: bool = True
    ) -> str:
        """
        Export bookmarks to markdown format.

        Args:
            bookmarks: Specific bookmarks to export (all if None)
            include_context: Include conversation context

        Returns:
            Markdown formatted string
        """
        if bookmarks is None:
            bookmarks = list(self._bookmarks.values())

        lines = [
            "# VERA Bookmarks",
            f"Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"Total: {len(bookmarks)} bookmarks",
            "",
            "---",
            ""
        ]

        # Group by type
        by_type = {}
        for b in bookmarks:
            t = b.bookmark_type.value
            if t not in by_type:
                by_type[t] = []
            by_type[t].append(b)

        for type_name, type_bookmarks in by_type.items():
            lines.append(f"## {type_name.title()}")
            lines.append("")

            for b in type_bookmarks:
                star = "⭐ " if b.starred else ""
                lines.append(f"### {star}{b.title}")
                lines.append(f"*{b.created_at.strftime('%Y-%m-%d %H:%M')}*")

                if b.tags:
                    lines.append(f"Tags: {', '.join(b.tags)}")

                lines.append("")
                lines.append(b.content)

                if include_context:
                    if b.context_before:
                        lines.append("")
                        lines.append("> Context before:")
                        lines.append(f"> {b.context_before[:200]}...")

                    if b.context_after:
                        lines.append("")
                        lines.append("> Context after:")
                        lines.append(f"> {b.context_after[:200]}...")

                lines.append("")
                lines.append("---")
                lines.append("")

        return "\n".join(lines)

    def save_export(
        self,
        filename: Optional[str] = None,
        bookmarks: Optional[List[Bookmark]] = None
    ) -> Path:
        """
        Save bookmark export to file.

        Args:
            filename: Output filename (auto-generated if None)
            bookmarks: Specific bookmarks to export

        Returns:
            Path to saved file
        """
        if filename is None:
            filename = f"bookmarks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

        filepath = self.bookmarks_dir / filename
        content = self.export_markdown(bookmarks)
        filepath.write_text(content)

        return filepath

    def get_stats(self) -> Dict[str, Any]:
        """Get bookmark statistics."""
        bookmarks = list(self._bookmarks.values())

        type_counts = {}
        for b in bookmarks:
            t = b.bookmark_type.value
            type_counts[t] = type_counts.get(t, 0) + 1

        return {
            "total_bookmarks": len(bookmarks),
            "starred_count": sum(1 for b in bookmarks if b.starred),
            "types": type_counts,
            "total_tags": len(self.get_all_tags()),
            "recent_bookmark": bookmarks[-1].created_at.isoformat() if bookmarks else None
        }


# === Self-test ===

if __name__ == "__main__":
    import sys

    def test_bookmarks():
        """Test bookmark manager."""
        print("Testing Bookmark Manager...")

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test 1: Create manager
            print("Test 1: Create manager...", end=" ")
            manager = BookmarkManager(memory_dir=Path(tmpdir))
            print("PASS")

            # Test 2: Create bookmark
            print("Test 2: Create bookmark...", end=" ")
            bm1 = manager.create_bookmark(
                title="Important Decision",
                content="We decided to use Python for the project",
                bookmark_type=BookmarkType.DECISION,
                tags=["python", "architecture"]
            )
            assert bm1.bookmark_id is not None
            print("PASS")

            # Test 3: Get bookmark
            print("Test 3: Get bookmark...", end=" ")
            retrieved = manager.get_bookmark(bm1.bookmark_id)
            assert retrieved.title == "Important Decision"
            print("PASS")

            # Test 4: Update bookmark
            print("Test 4: Update bookmark...", end=" ")
            updated = manager.update_bookmark(
                bm1.bookmark_id,
                title="Very Important Decision",
                priority=0
            )
            assert updated.title == "Very Important Decision"
            assert updated.priority == 0
            print("PASS")

            # Test 5: Star bookmark
            print("Test 5: Star bookmark...", end=" ")
            starred = manager.star_bookmark(bm1.bookmark_id)
            assert starred.starred == True
            print("PASS")

            # Test 6: Add more bookmarks
            print("Test 6: Add more bookmarks...", end=" ")
            bm2 = manager.create_bookmark(
                title="API Reference",
                content="Check the API docs at ...",
                bookmark_type=BookmarkType.REFERENCE,
                tags=["api", "docs"]
            )
            bm3 = manager.create_bookmark(
                title="Follow up on testing",
                content="Need to write unit tests",
                bookmark_type=BookmarkType.ACTION_ITEM,
                tags=["testing"]
            )
            assert len(manager._bookmarks) == 3
            print("PASS")

            # Test 7: Search bookmarks
            print("Test 7: Search bookmarks...", end=" ")
            results = manager.search(query="python")
            assert len(results) == 1
            assert results[0].bookmark_id == bm1.bookmark_id
            print("PASS")

            # Test 8: Search by type
            print("Test 8: Search by type...", end=" ")
            refs = manager.get_by_type(BookmarkType.REFERENCE)
            assert len(refs) == 1
            print("PASS")

            # Test 9: Get starred
            print("Test 9: Get starred...", end=" ")
            starred_list = manager.get_starred()
            assert len(starred_list) == 1
            print("PASS")

            # Test 10: Get all tags
            print("Test 10: Get all tags...", end=" ")
            tags = manager.get_all_tags()
            assert "python" in tags
            assert "api" in tags
            print("PASS")

            # Test 11: Export markdown
            print("Test 11: Export markdown...", end=" ")
            md = manager.export_markdown()
            assert "# VERA Bookmarks" in md
            assert "Important Decision" in md
            print("PASS")

            # Test 12: Save export
            print("Test 12: Save export...", end=" ")
            export_path = manager.save_export()
            assert export_path.exists()
            print("PASS")

            # Test 13: Stats
            print("Test 13: Stats...", end=" ")
            stats = manager.get_stats()
            assert stats["total_bookmarks"] == 3
            assert stats["starred_count"] == 1
            print("PASS")

            # Test 14: Delete bookmark
            print("Test 14: Delete bookmark...", end=" ")
            deleted = manager.delete_bookmark(bm2.bookmark_id)
            assert deleted
            assert len(manager._bookmarks) == 2
            print("PASS")

            # Test 15: Persistence
            print("Test 15: Persistence...", end=" ")
            manager2 = BookmarkManager(memory_dir=Path(tmpdir))
            assert len(manager2._bookmarks) == 2
            print("PASS")

        print("\nAll tests passed!")
        return True

    success = test_bookmarks()
    sys.exit(0 if success else 1)

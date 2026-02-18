#!/usr/bin/env python3
"""
Stream Processor for VERA
==========================

Real-time pattern detection and event handling for LLM streams.
Inspired by midstream Rust crate's approach to streaming pattern matching.

Features:
- Pattern matching on streaming text chunks
- Event-driven callbacks for pattern matches
- Buffered streaming for cross-chunk matching
- Token accumulation and windowing
- Async-compatible design

Usage:
    processor = StreamProcessor()

    # Add patterns with callbacks
    processor.add_pattern("```python", on_code_start)
    processor.add_pattern("```", on_code_end)
    processor.add_pattern("TOOL:", on_tool_call)

    # Process streaming chunks
    async for chunk in stream:
        events = processor.process(chunk)
        for event in events:
            print(f"Pattern matched: {event.pattern} at {event.position}")
"""

import re
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
from enum import Enum

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of stream events."""
    PATTERN_MATCH = "pattern_match"
    BUFFER_FULL = "buffer_full"
    STREAM_END = "stream_end"
    CHUNK_RECEIVED = "chunk_received"


@dataclass
class PatternMatch:
    """A matched pattern in the stream."""
    pattern: str
    position: int
    matched_text: str
    context_before: str = ""
    context_after: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class StreamEvent:
    """An event from the stream processor."""
    event_type: EventType
    data: Any
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Pattern:
    """A pattern to match in the stream."""
    pattern: str
    callback: Optional[Callable] = None
    is_regex: bool = False
    context_window: int = 50  # Characters before/after match to include


class PatternMatcher:
    """
    Efficient pattern matcher for streaming text.

    Handles cross-chunk matching by maintaining a sliding window buffer.
    """

    def __init__(self, max_buffer_size: int = 10000) -> None:
        """
        Initialize pattern matcher.

        Args:
            max_buffer_size: Maximum buffer size for cross-chunk matching
        """
        self.patterns: List[Pattern] = []
        self.buffer = ""
        self.max_buffer_size = max_buffer_size
        self.position = 0  # Total position in stream
        self._last_match_positions: Dict[str, int] = {}  # Track last match for each pattern

    def add_pattern(
        self,
        pattern: str,
        callback: Optional[Callable] = None,
        is_regex: bool = False,
        context_window: int = 50
    ) -> None:
        """
        Add a pattern to match.

        Args:
            pattern: Pattern string or regex
            callback: Optional callback function for matches
            is_regex: Whether pattern is a regex
            context_window: Characters of context to capture
        """
        self.patterns.append(Pattern(
            pattern=pattern,
            callback=callback,
            is_regex=is_regex,
            context_window=context_window
        ))

    def remove_pattern(self, pattern: str) -> bool:
        """Remove a pattern. Returns True if found and removed."""
        for i, p in enumerate(self.patterns):
            if p.pattern == pattern:
                self.patterns.pop(i)
                return True
        return False

    def process(self, chunk: str) -> List[PatternMatch]:
        """
        Process a chunk of text and return any matches.

        Args:
            chunk: Text chunk to process

        Returns:
            List of pattern matches found
        """
        # Append to buffer
        self.buffer += chunk
        self.position += len(chunk)

        # Trim buffer if too large (keep most recent)
        if len(self.buffer) > self.max_buffer_size:
            trim_amount = len(self.buffer) - self.max_buffer_size
            self.buffer = self.buffer[trim_amount:]

        matches = []

        for pattern_obj in self.patterns:
            pattern = pattern_obj.pattern

            if pattern_obj.is_regex:
                # Regex matching
                for match in re.finditer(pattern, self.buffer):
                    start = match.start()
                    end = match.end()

                    # Check if we've already matched at this position
                    last_pos = self._last_match_positions.get(pattern, -1)
                    if start <= last_pos:
                        continue

                    self._last_match_positions[pattern] = end

                    # Extract context
                    ctx_start = max(0, start - pattern_obj.context_window)
                    ctx_end = min(len(self.buffer), end + pattern_obj.context_window)

                    matches.append(PatternMatch(
                        pattern=pattern,
                        position=self.position - len(self.buffer) + start,
                        matched_text=match.group(),
                        context_before=self.buffer[ctx_start:start],
                        context_after=self.buffer[end:ctx_end]
                    ))
            else:
                # Literal string matching
                search_start = 0
                while True:
                    pos = self.buffer.find(pattern, search_start)
                    if pos == -1:
                        break

                    # Check if we've already matched at this position
                    last_pos = self._last_match_positions.get(pattern, -1)
                    if pos <= last_pos:
                        search_start = pos + 1
                        continue

                    self._last_match_positions[pattern] = pos + len(pattern)

                    # Extract context
                    ctx_start = max(0, pos - pattern_obj.context_window)
                    ctx_end = min(len(self.buffer), pos + len(pattern) + pattern_obj.context_window)

                    matches.append(PatternMatch(
                        pattern=pattern,
                        position=self.position - len(self.buffer) + pos,
                        matched_text=pattern,
                        context_before=self.buffer[ctx_start:pos],
                        context_after=self.buffer[pos + len(pattern):ctx_end]
                    ))

                    search_start = pos + 1

        return matches

    def reset(self) -> None:
        """Reset the matcher state."""
        self.buffer = ""
        self.position = 0
        self._last_match_positions.clear()

    def get_buffer(self) -> str:
        """Get current buffer contents."""
        return self.buffer


class StreamProcessor:
    """
    High-level stream processor with event handling.

    Combines pattern matching with event dispatch and callbacks.
    """

    def __init__(
        self,
        max_buffer_size: int = 10000,
        emit_chunk_events: bool = False
    ):
        """
        Initialize stream processor.

        Args:
            max_buffer_size: Maximum buffer size for matching
            emit_chunk_events: Whether to emit events for each chunk
        """
        self.matcher = PatternMatcher(max_buffer_size)
        self.emit_chunk_events = emit_chunk_events
        self._callbacks: Dict[str, List[Callable]] = {}
        self._global_callbacks: List[Callable] = []
        self._accumulated_text = ""
        self._token_count = 0

    def add_pattern(
        self,
        pattern: str,
        callback: Optional[Callable] = None,
        is_regex: bool = False
    ) -> None:
        """
        Add a pattern to detect.

        Args:
            pattern: Pattern string or regex
            callback: Callback function(match: PatternMatch)
            is_regex: Whether pattern is a regex
        """
        self.matcher.add_pattern(pattern, callback, is_regex)

        if callback:
            if pattern not in self._callbacks:
                self._callbacks[pattern] = []
            self._callbacks[pattern].append(callback)

    def on_match(self, callback: Callable) -> None:
        """
        Add a global callback for all pattern matches.

        Args:
            callback: Callback function(match: PatternMatch)
        """
        self._global_callbacks.append(callback)

    def process(self, chunk: str) -> List[StreamEvent]:
        """
        Process a text chunk and return events.

        Args:
            chunk: Text chunk from stream

        Returns:
            List of stream events
        """
        events = []
        self._accumulated_text += chunk
        self._token_count += 1

        # Emit chunk event if enabled
        if self.emit_chunk_events:
            events.append(StreamEvent(
                event_type=EventType.CHUNK_RECEIVED,
                data={"chunk": chunk, "token_count": self._token_count}
            ))

        # Check for pattern matches
        matches = self.matcher.process(chunk)

        for match in matches:
            events.append(StreamEvent(
                event_type=EventType.PATTERN_MATCH,
                data=match
            ))

            # Execute pattern-specific callbacks
            if match.pattern in self._callbacks:
                for callback in self._callbacks[match.pattern]:
                    try:
                        callback(match)
                    except Exception as e:
                        logger.error(f"Callback error for pattern '{match.pattern}': {e}")

            # Execute global callbacks
            for callback in self._global_callbacks:
                try:
                    callback(match)
                except Exception as e:
                    logger.error(f"Global callback error: {e}")

        return events

    def finish(self) -> StreamEvent:
        """
        Signal end of stream.

        Returns:
            Stream end event with accumulated text
        """
        return StreamEvent(
            event_type=EventType.STREAM_END,
            data={
                "total_text": self._accumulated_text,
                "token_count": self._token_count,
                "final_buffer": self.matcher.get_buffer()
            }
        )

    def reset(self) -> None:
        """Reset processor state."""
        self.matcher.reset()
        self._accumulated_text = ""
        self._token_count = 0

    def get_accumulated_text(self) -> str:
        """Get all accumulated text."""
        return self._accumulated_text

    def get_token_count(self) -> int:
        """Get total token count."""
        return self._token_count

    def get_stats(self) -> Dict[str, Any]:
        """Get processor statistics."""
        return {
            "token_count": self._token_count,
            "text_length": len(self._accumulated_text),
            "buffer_size": len(self.matcher.buffer),
            "pattern_count": len(self.matcher.patterns),
            "callback_count": sum(len(cbs) for cbs in self._callbacks.values())
        }


# === Factory Function ===

def create_stream_processor(
    patterns: Optional[Dict[str, Callable]] = None,
    max_buffer_size: int = 10000
) -> StreamProcessor:
    """
    Create a stream processor with optional patterns.

    Args:
        patterns: Dict of pattern -> callback
        max_buffer_size: Maximum buffer size

    Returns:
        Configured StreamProcessor
    """
    processor = StreamProcessor(max_buffer_size=max_buffer_size)

    if patterns:
        for pattern, callback in patterns.items():
            processor.add_pattern(pattern, callback)

    return processor


# === Self-test ===

if __name__ == "__main__":
    print("Testing Stream Processor...")
    print("=" * 50)

    # Test 1: Basic pattern matching
    print("Test 1: Basic pattern matching...", end=" ")
    processor = StreamProcessor()
    processor.add_pattern("TOOL:")

    events = processor.process("Hello world TOOL: do_something")
    assert len(events) == 1
    assert events[0].event_type == EventType.PATTERN_MATCH
    assert events[0].data.pattern == "TOOL:"
    print("PASS")

    # Test 2: Cross-chunk matching
    print("Test 2: Cross-chunk matching...", end=" ")
    processor.reset()
    processor.add_pattern("COMPLETE")

    events1 = processor.process("Almost COM")
    events2 = processor.process("PLETE now")

    assert len(events1) == 0
    assert len(events2) == 1
    assert events2[0].data.pattern == "COMPLETE"
    print("PASS")

    # Test 3: Regex matching
    print("Test 3: Regex matching...", end=" ")
    processor.reset()
    processor.add_pattern(r"\d{3}-\d{4}", is_regex=True)

    events = processor.process("Call me at 555-1234 please")
    assert len(events) == 1
    assert events[0].data.matched_text == "555-1234"
    print("PASS")

    # Test 4: Callbacks
    print("Test 4: Pattern callbacks...", end=" ")
    processor.reset()
    callback_data = []

    def on_error(match) -> None:
        callback_data.append(match.matched_text)

    processor.add_pattern("ERROR:", on_error)
    processor.process("Something ERROR: bad happened")

    assert len(callback_data) == 1
    assert callback_data[0] == "ERROR:"
    print("PASS")

    # Test 5: Multiple patterns
    print("Test 5: Multiple patterns...", end=" ")
    processor.reset()
    processor.add_pattern("START")
    processor.add_pattern("END")

    events = processor.process("START ... middle ... END")
    assert len(events) == 2
    print("PASS")

    # Test 6: Context capture
    print("Test 6: Context capture...", end=" ")
    processor.reset()
    processor.matcher.add_pattern("KEY", context_window=5)

    events = processor.process("before KEY after")
    match = events[0].data
    assert "ore " in match.context_before
    assert " aft" in match.context_after
    print("PASS")

    # Test 7: Stream end
    print("Test 7: Stream end...", end=" ")
    processor.reset()
    processor.process("Hello ")
    processor.process("World")
    end_event = processor.finish()

    assert end_event.event_type == EventType.STREAM_END
    assert end_event.data["total_text"] == "Hello World"
    assert end_event.data["token_count"] == 2
    print("PASS")

    # Test 8: Stats
    print("Test 8: Statistics...", end=" ")
    stats = processor.get_stats()
    assert "token_count" in stats
    assert "text_length" in stats
    print("PASS")

    # Test 9: Factory function
    print("Test 9: Factory function...", end=" ")
    proc = create_stream_processor({
        "ALERT:": lambda m: None,
        "WARNING:": lambda m: None
    })
    assert len(proc.matcher.patterns) == 2
    print("PASS")

    print("\n" + "=" * 50)
    print("All tests passed!")

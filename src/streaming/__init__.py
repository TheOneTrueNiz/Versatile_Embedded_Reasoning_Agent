#!/usr/bin/env python3
"""
Real-time Streaming Module for VERA
=====================================

Provides real-time pattern detection and event handling for LLM streams.
Inspired by midstream Rust crate's pattern detection approach.

Features:
- Pattern matching on streaming text
- Event-driven callbacks for matches
- Trigger word detection
- Streaming response buffering
- Token-by-token processing

Usage:
    from streaming import StreamProcessor, PatternMatcher

    # Create processor with patterns
    processor = StreamProcessor()
    processor.add_pattern("TOOL_CALL:", on_tool_call)
    processor.add_pattern("ERROR:", on_error)

    # Process streaming tokens
    async for token in llm_stream:
        events = processor.process(token)
        for event in events:
            await handle_event(event)
"""

from .processor import (
    StreamProcessor,
    PatternMatcher,
    StreamEvent,
    PatternMatch,
    create_stream_processor
)

__all__ = [
    'StreamProcessor',
    'PatternMatcher',
    'StreamEvent',
    'PatternMatch',
    'create_stream_processor',
]

#!/usr/bin/env python3
"""
VERA Configuration
==================

Configuration management for VERA system.

Loads settings from:
- Environment variables
- Command-line arguments
- Default values
"""

import os

from .genome_config import apply_runtime_settings_from_genome


class VERAConfig:
    """VERA configuration"""

    def __init__(self) -> None:
        apply_runtime_settings_from_genome()
        # Modes
        self.interactive = True
        self.autonomous = False
        self.debug = os.getenv("VERA_DEBUG", "0") == "1"
        self.dry_run = os.getenv("VERA_DRY_RUN", "0") == "1"
        self.observability = os.getenv("VERA_OBSERVABILITY", "0") == "1"

        # Memory system
        try:
            self.fast_network_buffer_size = int(os.getenv("VERA_FAST_BUFFER", "100"))
        except (ValueError, TypeError):
            self.fast_network_buffer_size = 100
        self.fast_network_threshold = float(os.getenv("VERA_FAST_THRESHOLD", "0.4"))
        self.slow_network_interval = float(os.getenv("VERA_SLOW_INTERVAL", "60.0"))
        self.slow_network_threshold = float(os.getenv("VERA_SLOW_THRESHOLD", "0.3"))
        self.slow_network_retention_threshold = float(os.getenv("VERA_RETENTION_THRESHOLD", "0.5"))
        self.retention_staleness_hours = float(os.getenv("VERA_RETENTION_STALENESS_HOURS", "48.0"))
        try:
            self.memvid_promotion_min = int(os.getenv("VERA_MEMVID_PROMOTION_MIN", "20"))
        except (ValueError, TypeError):
            self.memvid_promotion_min = 20

        # RAG cache
        self.rag_cache_size = int(os.getenv("VERA_RAG_CACHE_MB", "100")) * 1024 * 1024
        self.rag_cache_similarity = float(os.getenv("VERA_RAG_SIMILARITY", "0.7"))

        # Archival
        try:
            self.archive_recent_max = int(os.getenv("VERA_ARCHIVE_RECENT", "1000"))
        except (ValueError, TypeError):
            self.archive_recent_max = 1000
        self.archive_weekly_max = int(os.getenv("VERA_ARCHIVE_WEEKLY", "5000"))

        # Fault tolerance
        self.fault_tolerance = os.getenv("VERA_FAULT_TOLERANCE", "1") == "1"
        try:
            self.checkpoint_interval = int(os.getenv("VERA_CHECKPOINT_INTERVAL", "300"))
        except (ValueError, TypeError):
            self.checkpoint_interval = 300

        # Performance
        self.max_tool_concurrency = int(os.getenv("VERA_MAX_TOOL_CONCURRENCY", "10"))

    def from_args(self, args):
        """Update config from command line args"""
        if hasattr(args, 'auto') and args.auto:
            self.autonomous = True
            self.interactive = False

        if hasattr(args, 'debug') and args.debug:
            self.debug = True

        return self

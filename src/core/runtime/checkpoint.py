#!/usr/bin/env python3
import logging
"""
VERA Checkpoint
===============

Checkpointing for fault recovery and state persistence.

Uses atomic writes to prevent checkpoint corruption.
"""

import time
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Import atomic write
_src_path = Path(__file__).parent.parent
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

from atomic_io import atomic_json_write, safe_json_read
logger = logging.getLogger(__name__)


class VERACheckpoint:
    """
    Checkpointing for recovery

    Stores system state for fault recovery.
    Uses atomic writes to prevent corruption.
    """

    def __init__(self, checkpoint_dir: Path) -> None:
        self.checkpoint_dir = checkpoint_dir
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.last_health_check = time.time()  # For compatibility

    def save(self, state: Dict[str, Any]) -> None:
        """Save checkpoint atomically"""
        checkpoint_file = self.checkpoint_dir / f"checkpoint_{int(time.time())}.json"

        # Use atomic write to prevent corruption
        atomic_json_write(checkpoint_file, state)

        # Keep only last 5 checkpoints
        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
        for old_checkpoint in checkpoints[:-5]:
            try:
                old_checkpoint.unlink()
            except OSError:
                logger.debug("Suppressed OSError in checkpoint")
                pass  # Ignore cleanup errors

        # Update last health check time
        self.last_health_check = time.time()

    def load_latest(self) -> Optional[Dict[str, Any]]:
        """Load latest checkpoint with safe read"""
        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))

        if not checkpoints:
            return None

        latest = checkpoints[-1]

        # Use safe read with locking
        return safe_json_read(latest, default=None)

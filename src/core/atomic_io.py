#!/usr/bin/env python3
"""
Atomic I/O Shim - Re-exports from memory.persistence.atomic_io

This shim allows imports from src/core/ while the actual implementation
lives in memory/persistence/atomic_io.py
"""

import sys
from pathlib import Path

# Ensure src/ is in path for the real module
_src_path = Path(__file__).parent.parent
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

from memory.persistence.atomic_io import (
    atomic_write,
    safe_read,
    atomic_json_write,
    safe_json_read,
    FileTransaction,
    MergeStrategy,
    ConflictError,
)

__all__ = [
    'atomic_write',
    'safe_read',
    'atomic_json_write',
    'safe_json_read',
    'FileTransaction',
    'MergeStrategy',
    'ConflictError',
]

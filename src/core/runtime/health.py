#!/usr/bin/env python3
"""
VERA Health Monitor
===================

Health monitoring and fault detection for VERA system.

Based on:
- Byzantine fault tolerance
- Reliability monitoring framework
"""

import time
from datetime import datetime
from typing import Dict, Any


class VERAHealthMonitor:
    """
    Health monitoring and fault detection

    Tracks:
    - Error accumulation
    - System heartbeats
    - Health state
    """

    def __init__(self, max_errors: int = 10) -> None:
        self.healthy = True
        self.last_health_check = time.time()
        self.errors = []
        self.max_errors = max_errors
        self.heartbeats = 0

    @property
    def error_count(self) -> int:
        """Get current error count"""
        return len(self.errors)

    def is_healthy(self) -> bool:
        """Check if system is healthy"""
        # Check error rate
        if len(self.errors) >= self.max_errors:
            return False

        # Check last health check time
        if time.time() - self.last_health_check > 300:  # 5 minutes
            return False

        return self.healthy

    def record_error(self, error: Exception, context: str = "") -> None:
        """Record an error"""
        self.errors.append({
            "error": str(error),
            "context": context,
            "timestamp": datetime.now().isoformat()
        })

        # Trim errors list
        if len(self.errors) > self.max_errors:
            self.errors = self.errors[-self.max_errors:]

        # Update health
        if len(self.errors) >= self.max_errors:
            self.healthy = False

    def heartbeat(self) -> None:
        """Record heartbeat"""
        self.last_health_check = time.time()
        self.heartbeats += 1

    def get_stats(self) -> Dict[str, Any]:
        """Get health statistics"""
        return {
            "healthy": self.healthy,
            "total_errors": len(self.errors),
            "max_errors": self.max_errors,
            "heartbeats": self.heartbeats,
            "last_health_check": self.last_health_check,
            "recent_errors": self.errors[-5:] if self.errors else []
        }

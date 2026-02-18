"""
VERA Core Modules.

Contains:
- foundation/: Critical infrastructure (panic button, master list, bootloader)
- performance/: Optimization modules (lazy loading, storage, embeddings)
- runtime/: Main VERA orchestrator and config
- services/: Support services (observability, memory, event bus)
"""

# Use lazy imports to avoid circular dependencies and broken imports
# Modules are imported when accessed, not at package load time

__all__ = [
    'foundation',
    'performance',
    'runtime',
    'services',
]

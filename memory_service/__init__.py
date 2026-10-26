"""Memory Service Core Package"""

from memory_service.client import MemoryClient
from memory_service.core.manager import MemoryManager
from memory_service.config.settings import MemoryConfig

__version__ = "2.0.0"
__author__ = "TuLing AI Team"
__all__ = [
    "MemoryClient",
    "MemoryManager",
    "MemoryConfig",
]

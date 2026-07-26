"""Check a Sims 4 Mods folder for broken, misplaced or conflicting mods."""

from .scanner import ERROR, INFO, WARNING, Issue, ScanResult, scan

__version__ = "1.0.0"
__all__ = ["scan", "Issue", "ScanResult", "ERROR", "WARNING", "INFO", "__version__"]

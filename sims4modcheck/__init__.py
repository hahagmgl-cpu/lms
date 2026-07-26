"""sims4modcheck -- find broken mods in a Sims 4 Mods folder."""

from .scanner import BROKEN, INFO, WARNING, Finding, ScanResult, scan

__version__ = "0.1.0"

__all__ = ["scan", "ScanResult", "Finding", "BROKEN", "WARNING", "INFO"]

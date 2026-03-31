"""Shared utilities for export scripts."""
import re
from pathlib import Path


def sanitize_name(name: str) -> str:
    """Remove invalid characters from filename."""
    return re.sub(r'[\\/*?:"<>|]', "", name)


def get_output_directory(
    root: str | Path,
    city: str,
    job: str,
    brand: str,
) -> Path:
    """Create and return output directory path."""
    directory = Path(root) / city / job / brand
    directory.mkdir(parents=True, exist_ok=True)
    return directory

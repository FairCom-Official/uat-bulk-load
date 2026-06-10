"""Shared progress-bar helper so every loader renders an identical bar."""
from __future__ import annotations

try:
    from tqdm import tqdm
except ImportError:  # progress bar is optional
    tqdm = None

# One bar format used by every engine so the output looks the same.
_BAR_FORMAT = "  {desc} {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"

# Fixed-width labels keep the bars vertically aligned across engines.
_LABEL_WIDTH = 14


def make_bar(label: str, total: int):
    """Return a tqdm bar (or None if tqdm is unavailable) with shared styling."""
    if tqdm is None:
        return None
    return tqdm(
        total=total,
        desc=f"{label:<{_LABEL_WIDTH}}",
        unit="rows",
        unit_scale=True,
        bar_format=_BAR_FORMAT,
    )

# coding: utf-8
"""Screen-space scaling helpers."""

from __future__ import annotations


def fit_scale(
    available_width: int,
    available_height: int,
    design_width: int,
    design_height: int,
    *,
    margin: int = 16,
) -> float:
    """Return a downscale factor that keeps the design within screen bounds."""
    if min(available_width, available_height, design_width, design_height) <= 0:
        return 1.0
    width_scale = max(0, available_width - margin) / design_width
    height_scale = max(0, available_height - margin) / design_height
    return min(1.0, max(0.5, min(width_scale, height_scale)))

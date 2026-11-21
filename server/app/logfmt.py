"""Lignes de log `event=… clé=valeur`, lisibles en direct pendant la démo."""

from __future__ import annotations

import re
from typing import Any

_BROWSERS = (  # ordre important : Edge et Opera se déclarent aussi « Chrome »
    ("Edge", r"Edg/(\d+)"),
    ("Opera", r"OPR/(\d+)"),
    ("Firefox", r"Firefox/(\d+)"),
    ("Chrome", r"(?:Chrome|CriOS)/(\d+)"),
    ("Safari", r"Version/(\d+).*Safari/"),
)
_PLATFORMS = ("Android", "iPhone", "iPad", "Windows", "Mac OS X", "Linux")


def _format(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return f"{value:.2f}"
    text = str(value)
    return f'"{text}"' if not text or " " in text else text


def kv(event: str, **fields: Any) -> str:
    return " ".join([f"event={event}", *(f"{key}={_format(val)}" for key, val in fields.items())])


def short_browser(user_agent: str) -> str:
    browser = next(
        (
            f"{name}/{m.group(1)}"
            for name, pattern in _BROWSERS
            if (m := re.search(pattern, user_agent))
        ),
        "?",
    )
    platform = next((p for p in _PLATFORMS if p in user_agent), "?")
    return f"{browser} {platform.replace('Mac OS X', 'Mac')}"

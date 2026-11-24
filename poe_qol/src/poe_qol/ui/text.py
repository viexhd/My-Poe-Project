"""Capitalising UI text.

The app's style is a capital first letter on every word of visible
labels, buttons, status lines and messages ("Fetch Failed", "Show In
Game"). Units stay as players write them (c, div/h, px, ms), and the
rest of each word is left alone, so "PoE", "Ctrl+C" and "can't" survive.
"""
from __future__ import annotations

import re

# Units and short tokens that stay lowercase.
_KEEP = {"c", "c/h", "div/h", "px", "ms", "x", "vs", "e.g."}
_WORD = re.compile(r"(\s+)")


def capitalise(text: str) -> str:
    """Capitalise the first letter of every word in ``text``."""
    if not text:
        return text
    out = []
    for part in _WORD.split(text):
        if not part or part.isspace():
            out.append(part)
            continue
        lead = len(part) - len(part.lstrip("([\"'“‘"))
        word = part[lead:]
        bare = word.rstrip(".,:;!?)]\"'”’").lower()
        if word[:1].isalpha() and word[:1].islower() and bare not in _KEEP:
            word = word[0].upper() + word[1:]
        out.append(part[:lead] + word)
    return "".join(out)

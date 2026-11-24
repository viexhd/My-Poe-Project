"""Keeps the OAuth token between runs.

On Windows the file is encrypted with DPAPI (``CryptProtectData``), so
only the same Windows user on the same PC can read it. Elsewhere (tests,
Linux dev boxes) it is stored with ``0600`` permissions. Passwords are
never stored: the app never sees one.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from .oauth import Token

log = logging.getLogger("poe_qol.ggg.token_store")

_ENTROPY = b"twice-corrupted/ggg-oauth/v1"


def _dpapi(data: bytes, protect: bool) -> bytes:  # pragma: no cover - Windows
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(b: bytes) -> BLOB:
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
    src, ent, out = blob(data), blob(_ENTROPY), BLOB()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(src), None, ctypes.byref(ent), None, None,
            0x01, ctypes.byref(out))          # CRYPTPROTECT_UI_FORBIDDEN
    if not ok:
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


class TokenStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.encrypted = sys.platform == "win32"

    def load(self) -> Token | None:
        try:
            raw = self.path.read_bytes()
        except OSError:
            return None
        try:
            if self.encrypted:
                raw = _dpapi(raw, protect=False)
            return Token.from_dict(json.loads(raw.decode("utf-8")))
        except Exception as e:  # noqa: BLE001
            log.warning("ignoring unreadable token file: %s", e)
            return None

    def save(self, token: Token) -> None:
        raw = json.dumps(token.to_dict()).encode("utf-8")
        if self.encrypted:
            raw = _dpapi(raw, protect=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        os.replace(tmp, self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

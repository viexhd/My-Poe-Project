"""Tiny HTTP seam so the GGG client can be tested without a network.

``Transport`` takes ``(method, url, headers, body)`` and returns a
:class:`Response`. :func:`urllib_transport` is the real one.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Response:
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def header(self, name: str, default: str | None = None) -> str | None:
        low = name.lower()
        for k, v in self.headers.items():
            if k.lower() == low:
                return v
        return default

    def json(self):
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))


Transport = Callable[[str, str, dict, bytes | None], Response]


def urllib_transport(timeout: float = 20.0) -> Transport:
    def send(method: str, url: str, headers: dict, body: bytes | None) -> Response:
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return Response(r.status, dict(r.headers.items()), r.read())
        except urllib.error.HTTPError as e:
            try:
                data = e.read()
            except Exception:  # noqa: BLE001
                data = b""
            return Response(e.code, dict(e.headers.items()) if e.headers else {}, data)
    return send

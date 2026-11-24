"""Client side of GGG's dynamic rate limits.

Every API response carries, per policy::

    X-Rate-Limit-Policy: stash-request-limit
    X-Rate-Limit-Rules: Account,Ip
    X-Rate-Limit-Account: 30:300:300,10:10:60      # hits:period:penalty
    X-Rate-Limit-Account-State: 3:300:0,1:10:0     # hits:period:restricted

GGG asks clients to read these instead of hard-coding numbers, to stay
under them, and to honour ``Retry-After`` on HTTP 429. This limiter
learns each policy's rules from the headers, keeps its own timestamps
of requests sent, and tells the caller how long to wait before the next
request so the limit is never actually hit.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Rule:
    hits: int
    period: float
    penalty: float = 0.0


def parse_rules(value: str | None) -> list[Rule]:
    out: list[Rule] = []
    for part in (value or "").split(","):
        bits = part.strip().split(":")
        if len(bits) < 2:
            continue
        try:
            out.append(Rule(int(bits[0]), float(bits[1]),
                            float(bits[2]) if len(bits) > 2 else 0.0))
        except ValueError:
            continue
    return out


@dataclass
class _Policy:
    rules: list[Rule] = field(default_factory=list)
    sent: deque = field(default_factory=deque)       # monotonic timestamps
    blocked_until: float = 0.0


class RateLimiter:
    # One request of headroom under every rule: other tools on the same
    # account or IP share the limit with us.
    SAFETY = 1

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._policies: dict[str, _Policy] = {}
        self._endpoint_policy: dict[str, str] = {}

    def _policy(self, name: str) -> _Policy:
        return self._policies.setdefault(name, _Policy())

    def policy_for(self, endpoint: str) -> str:
        return self._endpoint_policy.get(endpoint, endpoint)

    def wait_time(self, endpoint: str) -> float:
        with self._lock:
            p = self._policy(self.policy_for(endpoint))
            now = self._clock()
            wait = max(0.0, p.blocked_until - now)
            longest = max((r.period for r in p.rules), default=0.0)
            while p.sent and now - p.sent[0] > longest:
                p.sent.popleft()
            for r in p.rules:
                cap = max(1, r.hits - self.SAFETY)
                recent = [t for t in p.sent if now - t < r.period]
                if len(recent) >= cap:
                    # wait until enough old requests leave the window
                    oldest = recent[len(recent) - cap]
                    wait = max(wait, oldest + r.period - now)
            return wait

    def acquire(self, endpoint: str, cancelled: Callable[[], bool] | None = None,
                on_wait: Callable[[float], None] | None = None) -> bool:
        """Block until a request may be sent, then record it.
        Returns False when ``cancelled()`` became true while waiting."""
        while True:
            w = self.wait_time(endpoint)
            if w <= 0:
                break
            if on_wait:
                on_wait(w)
            step = min(w, 0.5)
            self._sleep(step)
            if cancelled and cancelled():
                return False
        with self._lock:
            self._policy(self.policy_for(endpoint)).sent.append(self._clock())
        return True

    def update(self, endpoint: str, headers, status: int = 200) -> None:
        """Learn from a response's headers (``headers.get`` case-insensitive
        or a plain dict)."""
        get = _getter(headers)
        name = get("X-Rate-Limit-Policy")
        now = self._clock()
        with self._lock:
            if name:
                # requests recorded under the endpoint key move to the policy
                old_key = self.policy_for(endpoint)
                self._endpoint_policy[endpoint] = name
                p = self._policy(name)
                if old_key != name and old_key in self._policies:
                    p.sent.extend(self._policies.pop(old_key).sent)
                    p.sent = deque(sorted(p.sent))
                rules: list[Rule] = []
                for rule_name in (get("X-Rate-Limit-Rules") or "").split(","):
                    rule_name = rule_name.strip()
                    if not rule_name:
                        continue
                    limits = parse_rules(get(f"X-Rate-Limit-{rule_name}"))
                    states = parse_rules(get(f"X-Rate-Limit-{rule_name}-State"))
                    rules.extend(limits)
                    for st in states:
                        # server-side state: hits counted, restricted seconds
                        if st.penalty > 0:
                            p.blocked_until = max(p.blocked_until, now + st.penalty)
                        ours = sum(1 for t in p.sent if now - t < st.period)
                        for _ in range(max(0, st.hits - ours)):
                            p.sent.append(now)
                if rules:
                    p.rules = rules
            else:
                p = self._policy(self.policy_for(endpoint))
            if status == 429:
                try:
                    retry = float(get("Retry-After") or 60)
                except ValueError:
                    retry = 60.0
                p.blocked_until = max(p.blocked_until, now + retry)


def _getter(headers):
    if hasattr(headers, "header"):
        return lambda k: headers.header(k)
    low = {str(k).lower(): v for k, v in dict(headers or {}).items()}
    return lambda k: low.get(k.lower())

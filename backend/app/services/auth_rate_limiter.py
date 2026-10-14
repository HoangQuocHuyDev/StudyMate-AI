"""Small in-process rate limiter for public authentication endpoints."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from hashlib import sha256
import hmac
from math import ceil
from secrets import token_bytes
from threading import Lock
from time import monotonic


LOGIN_IP_LIMIT = 20
LOGIN_IP_USERNAME_LIMIT = 5
LOGIN_WINDOW_SECONDS = 5 * 60
REGISTER_IP_LIMIT = 5
REGISTER_WINDOW_SECONDS = 10 * 60
DEFAULT_MAX_TRACKED_KEYS = 50_000


class AuthenticationRateLimitExceeded(Exception):
    """Raised before expensive authentication work when a limit is exceeded."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("Authentication request rate limit exceeded.")
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class _Limit:
    key: str
    requests: int
    window_seconds: int


class AuthenticationRateLimiter:
    """Thread-safe sliding-window limiter with bounded, expiring state."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        key_secret: bytes | None = None,
        max_tracked_keys: int = DEFAULT_MAX_TRACKED_KEYS,
    ) -> None:
        if max_tracked_keys < 3:
            raise ValueError("max_tracked_keys must be at least 3.")
        self._clock = clock
        self._key_secret = key_secret or token_bytes(32)
        self._max_tracked_keys = max_tracked_keys
        self._events: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check_login(self, *, client_host: str, username: str) -> None:
        """Consume one login request from both IP and IP/username budgets."""

        normalized_host = self._normalize_value(client_host, "client_host")
        normalized_username = self._normalize_value(username, "username").casefold()
        host_key = self._digest("client", normalized_host)
        username_key = self._digest("username", normalized_username)
        self._check_and_record(
            (
                _Limit(
                    key=f"login:ip:{host_key}",
                    requests=LOGIN_IP_LIMIT,
                    window_seconds=LOGIN_WINDOW_SECONDS,
                ),
                _Limit(
                    key=f"login:pair:{host_key}:{username_key}",
                    requests=LOGIN_IP_USERNAME_LIMIT,
                    window_seconds=LOGIN_WINDOW_SECONDS,
                ),
            )
        )

    def check_register(self, *, client_host: str) -> None:
        """Consume one registration request from its per-IP budget."""

        normalized_host = self._normalize_value(client_host, "client_host")
        host_key = self._digest("client", normalized_host)
        self._check_and_record(
            (
                _Limit(
                    key=f"register:ip:{host_key}",
                    requests=REGISTER_IP_LIMIT,
                    window_seconds=REGISTER_WINDOW_SECONDS,
                ),
            )
        )

    def reset(self) -> None:
        """Clear volatile state; intended for isolated tests and shutdown hooks."""

        with self._lock:
            self._events.clear()

    def _check_and_record(self, limits: Sequence[_Limit]) -> None:
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            retry_after = 0
            for limit in limits:
                events = self._events.get(limit.key)
                if events is not None:
                    cutoff = now - limit.window_seconds
                    while events and events[0] <= cutoff:
                        events.popleft()
                    if not events:
                        del self._events[limit.key]
                        events = None
                if events is not None and len(events) >= limit.requests:
                    remaining = limit.window_seconds - (now - events[0])
                    retry_after = max(retry_after, max(1, ceil(remaining)))
            if retry_after:
                raise AuthenticationRateLimitExceeded(retry_after)

            self._ensure_capacity(tuple(limit.key for limit in limits))
            for limit in limits:
                self._events.setdefault(limit.key, deque()).append(now)

    def _purge_expired(self, now: float) -> None:
        oldest_allowed = now - max(LOGIN_WINDOW_SECONDS, REGISTER_WINDOW_SECONDS)
        stale_keys: list[str] = []
        for key, events in self._events.items():
            while events and events[0] <= oldest_allowed:
                events.popleft()
            if not events:
                stale_keys.append(key)
        for key in stale_keys:
            del self._events[key]

    def _ensure_capacity(self, keys: Sequence[str]) -> None:
        new_keys = set(keys) - self._events.keys()
        required_evictions = max(
            0,
            len(self._events) + len(new_keys) - self._max_tracked_keys,
        )
        if required_evictions == 0:
            return
        eviction_candidates = sorted(
            (candidate for candidate in self._events if candidate not in keys),
            key=lambda candidate: self._events[candidate][-1],
        )
        for oldest_key in eviction_candidates[:required_evictions]:
            del self._events[oldest_key]

    def _digest(self, namespace: str, value: str) -> str:
        payload = f"{namespace}\0{value}".encode("utf-8")
        return hmac.new(self._key_secret, payload, sha256).hexdigest()

    @staticmethod
    def _normalize_value(value: str, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string.")
        return value.strip()


_authentication_rate_limiter = AuthenticationRateLimiter()


def get_authentication_rate_limiter() -> AuthenticationRateLimiter:
    """Return the process-local authentication limiter dependency."""

    return _authentication_rate_limiter

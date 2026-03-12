"""
Circuit breaker wrapping run_triage() ProcessPoolExecutor calls.
Prevents cascade failure if the triage engine hangs or throws repeatedly.

State machine:
  CLOSED   → normal operation, requests pass through
  OPEN     → failing, requests rejected immediately
  HALF_OPEN → recovery probe, one request allowed through

Transitions:
  CLOSED   → OPEN       after failure_threshold consecutive failures
  OPEN     → HALF_OPEN  after recovery_timeout seconds
  HALF_OPEN → CLOSED    on success
  HALF_OPEN → OPEN      on failure
"""
from enum import Enum
from time import monotonic


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when circuit is OPEN — caller should surface to agent as retryable error."""


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 60.0):
        self.state = CircuitState.CLOSED
        self._failures = 0
        self._threshold = failure_threshold
        self._timeout = recovery_timeout
        self._opened_at: float | None = None

    async def call(self, coro):
        """Wrap an awaitable. Raises CircuitOpenError if OPEN and timeout not elapsed."""
        if self.state == CircuitState.OPEN:
            elapsed = monotonic() - self._opened_at
            if elapsed >= self._timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                # Cancel Future or close coroutine to prevent resource leak
                if hasattr(coro, "cancel"):
                    coro.cancel()   # asyncio.Future from run_in_executor
                elif hasattr(coro, "close"):
                    coro.close()    # native coroutine
                raise CircuitOpenError(
                    f"Triage engine unavailable — circuit open, retry after "
                    f"{self._timeout - elapsed:.0f}s"
                )
        try:
            result = await coro
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        self._failures = 0
        self.state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self.state = CircuitState.OPEN
            self._opened_at = monotonic()


# Module-level instance — shared across all requests
triage_circuit = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)

"""
circuit_breaker.py – Pure-Python circuit breaker dla wywołań LLM.

Stany:
  CLOSED    → normalna praca, calls przechodzą
  OPEN      → zbyt wiele błędów, calls blokowane (rzuca FootStatsCircuitOpenError)
  HALF_OPEN → po recovery_timeout, testuje jeden call; sukces → CLOSED, błąd → OPEN

Użycie:
    cb = CircuitBreaker("groq", failure_threshold=5, recovery_timeout=60)

    @cb.protect
    def wywołaj_groq(prompt):
        ...

    # lub bezpośrednio:
    try:
        with cb:
            wynik = groq_api_call(prompt)
    except FootStatsCircuitOpenError:
        wynik = fallback()
"""

import logging
import threading
import time
from enum import Enum
from typing import Callable, TypeVar

from footstats.core.exceptions import FootStatsCircuitOpenError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class _Stan(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Thread-safe circuit breaker."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._stan = _Stan.CLOSED
        self._failures = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    # ── Publiczne API ────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return self._stan == _Stan.OPEN and not self._moze_przejsc_do_half_open()

    def protect(self, func: Callable[..., T]) -> Callable[..., T]:
        """Dekorator: opakowuje funkcję circuit breakerem."""
        import functools

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            self._przed_wywolaniem()
            try:
                wynik = func(*args, **kwargs)
                self._po_sukcesie()
                return wynik
            except FootStatsCircuitOpenError:
                raise
            except Exception as exc:
                self._po_bledzie(exc)
                raise

        return wrapper

    def __enter__(self) -> "CircuitBreaker":
        self._przed_wywolaniem()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            self._po_sukcesie()
        elif exc_type is not FootStatsCircuitOpenError:
            self._po_bledzie(exc_val)
        return False

    def reset(self) -> None:
        """Ręczny reset do stanu CLOSED (np. po restarcie serwisu)."""
        with self._lock:
            self._stan = _Stan.CLOSED
            self._failures = 0
            self._last_failure_time = 0.0
            logger.info("[CB:%s] Ręcznie zresetowany → CLOSED", self.name)

    @property
    def stan(self) -> str:
        return self._stan.value

    # ── Wewnętrzna logika ────────────────────────────────────────────

    def _moze_przejsc_do_half_open(self) -> bool:
        return (
            self._stan == _Stan.OPEN
            and time.monotonic() - self._last_failure_time >= self.recovery_timeout
        )

    def _przed_wywolaniem(self) -> None:
        with self._lock:
            if self._stan == _Stan.CLOSED:
                return
            if self._moze_przejsc_do_half_open():
                self._stan = _Stan.HALF_OPEN
                logger.info("[CB:%s] OPEN → HALF_OPEN (testowy call)", self.name)
                return
            if self._stan == _Stan.OPEN:
                retry_after = self.recovery_timeout - (
                    time.monotonic() - self._last_failure_time
                )
                raise FootStatsCircuitOpenError(
                    model=self.name, retry_after=max(0.0, retry_after)
                )

    def _po_sukcesie(self) -> None:
        with self._lock:
            if self._stan == _Stan.HALF_OPEN:
                logger.info("[CB:%s] HALF_OPEN → CLOSED (sukces)", self.name)
            self._stan = _Stan.CLOSED
            self._failures = 0

    def _po_bledzie(self, exc: Exception) -> None:
        with self._lock:
            self._failures += 1
            self._last_failure_time = time.monotonic()
            logger.warning(
                "[CB:%s] Błąd #%d/%d: %s",
                self.name, self._failures, self.failure_threshold, exc,
            )
            if self._stan == _Stan.HALF_OPEN or self._failures >= self.failure_threshold:
                poprzedni = self._stan
                self._stan = _Stan.OPEN
                if poprzedni != _Stan.OPEN:
                    logger.error(
                        "[CB:%s] %s → OPEN (próg=%d, timeout=%ds)",
                        self.name, poprzedni.value,
                        self.failure_threshold, int(self.recovery_timeout),
                    )


# Singletons dla każdego modelu AI
groq_circuit = CircuitBreaker("groq", failure_threshold=5, recovery_timeout=60)
ollama_circuit = CircuitBreaker("ollama", failure_threshold=3, recovery_timeout=30)

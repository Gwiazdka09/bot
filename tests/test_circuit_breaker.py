"""Testy core/circuit_breaker.py i core/exceptions.py."""

import time

import pytest

from footstats.core.circuit_breaker import CircuitBreaker, _Stan
from footstats.core.exceptions import (
    FootStatsCircuitOpenError,
    FootStatsDatabaseError,
    FootStatsLLMError,
    FootStatsScraperError,
)


class TestExceptions:
    def test_bazowy_wyjatek_ma_pola(self) -> None:
        exc = FootStatsScraperError("Timeout", error_code="TIMEOUT", url="http://x.pl")
        assert exc.error_code == "TIMEOUT"
        assert exc.url == "http://x.pl"
        assert exc.timestamp

    def test_llm_error_ma_model(self) -> None:
        exc = FootStatsLLMError("fail", model="groq")
        assert exc.model == "groq"

    def test_db_error_ma_query(self) -> None:
        exc = FootStatsDatabaseError("fail", query="SELECT 1")
        assert exc.query == "SELECT 1"

    def test_circuit_open_error_ma_retry_after(self) -> None:
        exc = FootStatsCircuitOpenError(model="groq", retry_after=45.0)
        assert exc.retry_after == 45.0

    def test_str_zawiera_kod(self) -> None:
        exc = FootStatsDatabaseError("brak tabeli", error_code="TABLE_MISSING")
        assert "TABLE_MISSING" in str(exc)


class TestCircuitBreaker:
    def _zrob_cb(self, threshold: int = 3, timeout: float = 999.0) -> CircuitBreaker:
        return CircuitBreaker("test", failure_threshold=threshold, recovery_timeout=timeout)

    def test_poczatkowo_closed(self) -> None:
        cb = self._zrob_cb()
        assert cb.stan == "CLOSED"
        assert not cb.is_open

    def test_sukces_zostaje_closed(self) -> None:
        cb = self._zrob_cb()
        with cb:
            pass
        assert cb.stan == "CLOSED"

    def test_bledy_otwieraja_circuit(self) -> None:
        cb = self._zrob_cb(threshold=3)
        for _ in range(3):
            try:
                with cb:
                    raise ValueError("fail")
            except ValueError:
                pass
        assert cb.stan == "OPEN"

    def test_open_blokuje_call(self) -> None:
        cb = self._zrob_cb(threshold=2)
        for _ in range(2):
            try:
                with cb:
                    raise ValueError("fail")
            except ValueError:
                pass
        with pytest.raises(FootStatsCircuitOpenError):
            with cb:
                pass

    def test_protect_dekorator(self) -> None:
        cb = self._zrob_cb(threshold=2)

        @cb.protect
        def zawsze_blad():
            raise RuntimeError("boom")

        for _ in range(2):
            with pytest.raises(RuntimeError):
                zawsze_blad()

        with pytest.raises(FootStatsCircuitOpenError):
            zawsze_blad()

    def test_half_open_po_timeout(self) -> None:
        cb = CircuitBreaker("test_timeout", failure_threshold=1, recovery_timeout=0.05)
        try:
            with cb:
                raise ValueError("fail")
        except ValueError:
            pass
        assert cb.stan == "OPEN"
        time.sleep(0.1)
        # call powinien przejść (HALF_OPEN)
        with cb:
            pass
        assert cb.stan == "CLOSED"

    def test_half_open_blad_wraca_do_open(self) -> None:
        cb = CircuitBreaker("test_ho", failure_threshold=1, recovery_timeout=0.05)
        try:
            with cb:
                raise ValueError("fail")
        except ValueError:
            pass
        time.sleep(0.1)
        try:
            with cb:
                raise ValueError("fail again")
        except ValueError:
            pass
        assert cb.stan == "OPEN"

    def test_reset_wraca_do_closed(self) -> None:
        cb = self._zrob_cb(threshold=1)
        try:
            with cb:
                raise ValueError()
        except ValueError:
            pass
        assert cb.stan == "OPEN"
        cb.reset()
        assert cb.stan == "CLOSED"

    def test_is_open_false_gdy_timeout_minal(self) -> None:
        cb = CircuitBreaker("test_io", failure_threshold=1, recovery_timeout=0.05)
        try:
            with cb:
                raise ValueError()
        except ValueError:
            pass
        assert cb.is_open
        time.sleep(0.1)
        assert not cb.is_open

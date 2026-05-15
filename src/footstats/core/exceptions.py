"""
exceptions.py – Strukturowane wyjątki FootStats.
"""

from datetime import datetime


class FootStatsError(Exception):
    """Bazowy wyjątek FootStats z error_code i timestamp."""

    def __init__(self, message: str, error_code: str = "UNKNOWN") -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.timestamp = datetime.now().isoformat()

    def __str__(self) -> str:
        return f"[{self.error_code}] {self.message} (at {self.timestamp})"


class FootStatsScraperError(FootStatsError):
    """Błąd scrapera — Playwright, HTTP, parsowanie."""

    def __init__(self, message: str, error_code: str = "SCRAPER_ERROR",
                 url: str = "") -> None:
        super().__init__(message, error_code)
        self.url = url


class FootStatsLLMError(FootStatsError):
    """Błąd modelu językowego — Groq, Ollama, timeout."""

    def __init__(self, message: str, error_code: str = "LLM_ERROR",
                 model: str = "") -> None:
        super().__init__(message, error_code)
        self.model = model


class FootStatsDatabaseError(FootStatsError):
    """Błąd operacji bazodanowej — SQLite, zapis, odczyt."""

    def __init__(self, message: str, error_code: str = "DB_ERROR",
                 query: str = "") -> None:
        super().__init__(message, error_code)
        self.query = query


class FootStatsCircuitOpenError(FootStatsLLMError):
    """Circuit breaker otwarty — zbyt wiele błędów LLM, przełączamy na fallback."""

    def __init__(self, model: str = "", retry_after: float = 0.0) -> None:
        super().__init__(
            f"Circuit breaker otwarty dla '{model}'. Retry za {retry_after:.0f}s.",
            error_code="CIRCUIT_OPEN",
            model=model,
        )
        self.retry_after = retry_after

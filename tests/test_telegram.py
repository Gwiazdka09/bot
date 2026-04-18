"""
test_telegram.py – Testy integracji modułu telegram_notify.

Wersja: v3.2
Sprawdza dostępność Telegramu i wysyłanie testowych wiadomości.

SETUP:
  1. Dodaj do .env:
       TELEGRAM_BOT_TOKEN=<twój_token_od_BotFather>
       TELEGRAM_CHAT_ID=<twoje_chat_id>
  2. Uruchom test: pytest tests/test_telegram.py -v -s
"""

import os
import pytest
from dotenv import load_dotenv

# Import modułu Telegramu
from footstats.utils.telegram_notify import (
    telegram_dostepny,
    send_message,
    send_kupon,
    send_wynik_update,
    send_draft_kupon,
)

load_dotenv()


class TestTelegramAvailability:
    """Weryfikacja dostępu do Telegramu."""

    def test_telegram_credentials_exist(self):
        """Sprawdza czy TELEGRAM_BOT_TOKEN i TELEGRAM_CHAT_ID są w .env."""
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

        if not token or not chat_id:
            pytest.skip("Telegram credentials not configured in .env")

        assert token, "TELEGRAM_BOT_TOKEN must be set"
        assert chat_id, "TELEGRAM_CHAT_ID must be set"

    def test_telegram_dostepny_returns_true(self):
        """Zwraca True jeśli kredencjały są dostępne."""
        if not os.getenv("TELEGRAM_BOT_TOKEN"):
            pytest.skip("Telegram not configured")

        result = telegram_dostepny()
        assert result is True, "telegram_dostepny() should return True when credentials exist"


class TestTelegramMessaging:
    """Testy wysyłania wiadomości."""

    @pytest.mark.integration
    def test_send_simple_message(self):
        """Wysyła prostą testową wiadomość."""
        if not telegram_dostepny():
            pytest.skip("Telegram not available")

        result = send_message(
            "🤖 <b>FootStats Test</b>\n"
            "Test integracji Telegramu — wiadomość testowa\n"
            "Jeśli widzisz tę wiadomość, Telegram jest skonfigurowany poprawnie ✅"
        )
        assert result is True, "send_message() should return True on success"

    @pytest.mark.integration
    def test_send_kupon_test_data(self):
        """Wysyła testowy kupon na Telegram."""
        if not telegram_dostepny():
            pytest.skip("Telegram not available")

        test_kupon = {
            "kupon_a": {
                "zdarzenia": [
                    {
                        "nr": 1,
                        "mecz": "Arsenal - Chelsea",
                        "typ": "Over 2.5",
                        "kurs": 1.85,
                        "_verified": True,
                    },
                    {
                        "nr": 2,
                        "mecz": "Liverpool - Man City",
                        "typ": "Over 2.5",
                        "kurs": 1.75,
                        "_verified": True,
                    },
                ],
                "kurs_laczny": 3.24,
                "szansa_wygranej_pct": 78,
            },
            "kupon_b": {
                "zdarzenia": [
                    {
                        "nr": 1,
                        "mecz": "Arsenal - Chelsea",
                        "typ": "Over 1.5",
                        "kurs": 1.45,
                        "_verified": True,
                    },
                ],
                "kurs_laczny": 1.45,
                "szansa_wygranej_pct": 85,
            },
            "top3": [
                {"mecz": "Man United - Tottenham", "typ": "Over 2.5", "kurs": 1.80, "ev_netto": 12.5},
                {"mecz": "Brighton - Aston Villa", "typ": "1", "kurs": 2.10, "ev_netto": 8.3},
                {"mecz": "West Ham - Newcastle", "typ": "2", "kurs": 1.95, "ev_netto": 5.2},
            ],
            "ostrzezenia": "Test message — ignore this",
        }

        result = send_kupon(test_kupon, stawka_a=10.0, stawka_b=5.0)
        assert result is True, "send_kupon() should return True on success"

    @pytest.mark.integration
    def test_send_wynik_update_test(self):
        """Wysyła testowe powiadomienie wyniku."""
        if not telegram_dostepny():
            pytest.skip("Telegram not available")

        result = send_wynik_update(
            match_id=1,
            mecz="Arsenal - Chelsea",
            ai_tip="Over 2.5",
            actual_result="3:2",
            tip_correct=1,
        )
        assert result is True, "send_wynik_update() should return True on success"

    @pytest.mark.integration
    def test_send_draft_kupon_test(self):
        """Wysyła testowe powiadomienie DRAFT kuponu."""
        if not telegram_dostepny():
            pytest.skip("Telegram not available")

        test_legs = [
            {
                "mecz": "Arsenal - Chelsea",
                "typ": "Over 2.5",
                "kurs": 1.85,
                "decision_score": 0.87,
            },
            {
                "mecz": "Liverpool - Man City",
                "typ": "Over 2.5",
                "kurs": 1.75,
                "decision_score": 0.92,
            },
        ]

        result = send_draft_kupon(
            coupon_id=999,
            legs=test_legs,
            total_odds=3.24,
        )
        assert result is True, "send_draft_kupon() should return True on success"


class TestTelegramWithoutCredentials:
    """Testy działania bez skonfigurowanych kredencjałów."""

    @pytest.mark.unit
    def test_telegram_dostepny_returns_false_without_token(self, monkeypatch):
        """Zwraca False jeśli brak tokenu."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

        result = telegram_dostepny()
        assert result is False, "telegram_dostepny() should return False without credentials"

    @pytest.mark.unit
    def test_send_message_returns_false_without_token(self, monkeypatch):
        """Zwraca False przy wysłaniu bez kredencjałów."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

        result = send_message("test")
        assert result is False, "send_message() should return False without credentials"

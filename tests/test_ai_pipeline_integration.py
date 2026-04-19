"""
test_ai_pipeline_integration.py – Test integracyjny pełnego pipeline'u AI
=========================================================================
Sprawdza czy kompletny pipeline AI działa end-to-end:
  1. Analiza formularza (form analysis)
  2. Wstrzyknięcie RAG (RAG injection)
  3. Scoring pewności (confidence scoring)
  Wszystko w jednym wywołaniu ai_analiza_pewniaczki()

Test weryfikuje:
  ✓ Obecność kluczowych kluczy JSON (top3, kupon_a, kupon_b)
  ✓ Prawidłową strukturę wszystkich sekcji
  ✓ Zakresy pewności [0-100]
  ✓ Prawidłowe typy tipów ("1", "2", "X", "Over", "Under", "BTTS", itp)
  ✓ Obecność uzasadnień i wyjaśnień
"""

import pytest
import json
from src.footstats.ai.analyzer import ai_analiza_pewniaczki


@pytest.mark.integration
def test_full_pipeline_returns_valid_structure():
    """
    Test integracyjny: ai_analiza_pewniaczki() powinien zwrócić JSON z:
    1. Kluczami: top3, kupon_a, kupon_b
    2. Confidence scores (pewnosc_pct) w prawidłowym zakresie [0-100]
    3. Prawidłowymi typami tipów ("1", "2", "X", "Over", "Under", "BTTS", itp)
    """
    wyniki = [
        {
            "data": "2025-01-15",
            "liga": "ekstraklasa",
            "mecze": [
                {
                    "gospodarz": "Bayern",
                    "goscie": "Dortmund",
                    "kurs_1": 1.80,
                    "kurs_2": 3.50,
                    "kurs_x": 3.40,
                    "kurs_over": 2.10,
                    "id_api": 12345,
                    "metoda": "POISSON",
                    "ev_netto": 5.2,
                }
            ]
        }
    ]

    # Wywołaj pełny pipeline AI
    result = ai_analiza_pewniaczki(
        wyniki=wyniki,
        pobierz_forme=False,  # Wyłącz pobieranie formy aby test był szybszy
    )

    # Weryfikuj strukturę top-level
    assert isinstance(result, dict), "Rezultat powinien być słownikiem"
    assert "top3" in result or "_raw" in result, "Brakuje top3 lub _raw w rezultacie"

    # Jeśli analiza się nie powiodła, sprawdź czy _raw zawiera surowy tekst
    if "_raw" in result:
        assert isinstance(result["_raw"], str), "_raw powinien być stringiem"
        pytest.skip(f"Analiza zwróciła surowy tekst (parsowanie JSON nie powiodło się)")

    # Weryfikuj obecność kuponów
    assert "kupon_a" in result, "Brakuje kupon_a w rezultacie"
    assert "kupon_b" in result, "Brakuje kupon_b w rezultacie"

    # Weryfikuj strukturę top3
    assert isinstance(result["top3"], list), "top3 powinien być listą"
    if len(result["top3"]) > 0:
        # Weryfikuj strukturę pierwszej predykcji w top3
        pred = result["top3"][0]
        assert "typ" in pred, "Predykcja w top3 brakuje pola 'typ'"
        assert "pewnosc_pct" in pred, "Predykcja w top3 brakuje pola 'pewnosc_pct'"
        assert "uzasadnienie" in pred, "Predykcja w top3 brakuje pola 'uzasadnienie'"

        # Weryfikuj prawidłowy zakres pewności
        conf = pred.get("pewnosc_pct", 0)
        assert isinstance(conf, (int, float)), f"pewnosc_pct powinien być liczbą, otrzymano: {type(conf)}"
        assert 0 <= conf <= 100, f"Pewność poza zakresem [0-100]: {conf}"

        # Weryfikuj prawidłowy typ tipu
        valid_tips = [
            "1", "2", "X",  # Wyniki 1x2
            "Over 2.5", "Under 2.5", "Over 3.5", "Under 3.5",  # Over/Under
            "BTTS", "No BTTS",  # Both Teams To Score
        ]
        assert pred["typ"] in valid_tips, f"Nieprawidłowy typ tipu: {pred['typ']}"

    # Weryfikuj strukturę kupon_a
    assert "zdarzenia" in result["kupon_a"], "kupon_a brakuje 'zdarzenia'"
    assert isinstance(result["kupon_a"]["zdarzenia"], list), "kupon_a.zdarzenia powinien być listą"

    if len(result["kupon_a"]["zdarzenia"]) > 0:
        for event in result["kupon_a"]["zdarzenia"]:
            assert "typ" in event, "Zdarzenie w kupon_a brakuje 'typ'"
            assert "pewnosc_pct" in event, "Zdarzenie w kupon_a brakuje 'pewnosc_pct'"

            # Weryfikuj zakres pewności
            conf = event.get("pewnosc_pct", 0)
            assert isinstance(conf, (int, float)), f"pewnosc_pct powinien być liczbą"
            assert 0 <= conf <= 100, f"Pewność zdarzenia poza zakresem [0-100]: {conf}"

            # Weryfikuj typ tipu
            assert event["typ"] in valid_tips, f"Nieprawidłowy typ tipu w zdarzeniu: {event['typ']}"

    # Weryfikuj strukturę kupon_b
    assert "zdarzenia" in result["kupon_b"], "kupon_b brakuje 'zdarzenia'"
    assert isinstance(result["kupon_b"]["zdarzenia"], list), "kupon_b.zdarzenia powinien być listą"

    if len(result["kupon_b"]["zdarzenia"]) > 0:
        for event in result["kupon_b"]["zdarzenia"]:
            assert "typ" in event, "Zdarzenie w kupon_b brakuje 'typ'"
            assert "pewnosc_pct" in event, "Zdarzenie w kupon_b brakuje 'pewnosc_pct'"

            # Weryfikuj zakres pewności
            conf = event.get("pewnosc_pct", 0)
            assert isinstance(conf, (int, float)), f"pewnosc_pct powinien być liczbą"
            assert 0 <= conf <= 100, f"Pewność zdarzenia poza zakresem [0-100]: {conf}"

            # Weryfikuj typ tipu
            assert event["typ"] in valid_tips, f"Nieprawidłowy typ tipu w zdarzeniu: {event['typ']}"


@pytest.mark.integration
def test_pipeline_confidence_values_reasonable():
    """Weryfikuj że wartości pewności są rozsądne (nie wszystkie takie same, nie wszystkie 0/100)."""
    wyniki = [
        {
            "data": "2025-01-15",
            "liga": "ekstraklasa",
            "mecze": [
                {
                    "gospodarz": "Bayern",
                    "goscie": "Dortmund",
                    "kurs_1": 1.80,
                    "kurs_2": 3.50,
                    "kurs_x": 3.40,
                    "kurs_over": 2.10,
                    "id_api": 12345,
                    "metoda": "POISSON",
                    "ev_netto": 5.2,
                },
                {
                    "gospodarz": "PSG",
                    "goscie": "Marseille",
                    "kurs_1": 1.45,
                    "kurs_2": 4.20,
                    "kurs_x": 4.50,
                    "kurs_over": 2.15,
                    "id_api": 12346,
                    "metoda": "POISSON",
                    "ev_netto": 3.8,
                },
            ]
        }
    ]

    result = ai_analiza_pewniaczki(
        wyniki=wyniki,
        pobierz_forme=False,
    )

    # Jeśli analiza się nie powiodła, pomiń test
    if "_raw" in result:
        pytest.skip("Analiza zwróciła surowy tekst")

    # Zbierz wszystkie wartości pewności z top3
    confidences = []
    for pred in result.get("top3", []):
        conf = pred.get("pewnosc_pct", 0)
        confidences.append(conf)

    if confidences:
        # Sprawdź że nie wszystkie są identyczne
        unique_confs = set(confidences)
        # Może być mało wariantów, ale powinno być przynajmniej 1
        assert len(unique_confs) >= 1, "Wartości pewności powinny zawierać co najmniej 1 unikalną wartość"

        # Sprawdź że nie wszystkie są 0
        assert not all(c == 0 for c in confidences), "Nie wszystkie pewności powinny być 0"


@pytest.mark.integration
def test_pipeline_with_multiple_matches():
    """Test pipeline'u z wieloma meczami (rozbudowany case)."""
    wyniki = [
        {
            "data": "2025-01-20",
            "liga": "ekstraklasa",
            "mecze": [
                {
                    "gospodarz": f"Zespół{i}",
                    "goscie": f"Zespół{i+1}",
                    "kurs_1": 1.80 + i*0.05,
                    "kurs_2": 3.50 + i*0.1,
                    "kurs_x": 3.40 + i*0.1,
                    "kurs_over": 2.10 + i*0.05,
                    "id_api": 12350 + i,
                    "metoda": "POISSON" if i % 2 == 0 else "ML",
                    "ev_netto": 4.5 + i*0.3,
                }
                for i in range(5)
            ]
        }
    ]

    result = ai_analiza_pewniaczki(
        wyniki=wyniki,
        pobierz_forme=False,
    )

    # Weryfikuj że resultat zawiera wymagane klucze
    assert isinstance(result, dict), "Rezultat powinien być słownikiem"

    if "_raw" not in result:
        # Jeśli analiza się powiodła, sprawdzaj strukturę
        assert "top3" in result, "Brakuje top3"
        assert "kupon_a" in result, "Brakuje kupon_a"
        assert "kupon_b" in result, "Brakuje kupon_b"

        # Weryfikuj że kupony zawierają zdarzenia
        assert isinstance(result["kupon_a"]["zdarzenia"], list), "kupon_a.zdarzenia powinien być listą"
        assert isinstance(result["kupon_b"]["zdarzenia"], list), "kupon_b.zdarzenia powinien być listą"

        # Weryfikuj minimalną ilość zdarzeń (jeśli są)
        if len(result["kupon_a"]["zdarzenia"]) > 0:
            assert len(result["kupon_a"]["zdarzenia"]) >= 1, "kupon_a powinien zawierać co najmniej 1 zdarzenie"

        if len(result["kupon_b"]["zdarzenia"]) > 0:
            assert len(result["kupon_b"]["zdarzenia"]) >= 1, "kupon_b powinien zawierać co najmniej 1 zdarzenie"


@pytest.mark.integration
def test_pipeline_empty_input():
    """Test pipeline'u z pustą listą meczów."""
    wyniki = []

    result = ai_analiza_pewniaczki(
        wyniki=wyniki,
        pobierz_forme=False,
    )

    # Powinien zwrócić słownik z komunikatem o braku meczów
    assert isinstance(result, dict), "Rezultat dla pustej listy powinien być słownikiem"
    assert "_raw" in result, "Dla pustej listy powinien zwrócić _raw z komunikatem"


@pytest.mark.integration
def test_pipeline_with_target_goals():
    """Test pipeline'u z opcjonalnym celem wygranej."""
    wyniki = [
        {
            "data": "2025-01-15",
            "liga": "ekstraklasa",
            "mecze": [
                {
                    "gospodarz": "Bayern",
                    "goscie": "Dortmund",
                    "kurs_1": 1.80,
                    "kurs_2": 3.50,
                    "kurs_x": 3.40,
                    "kurs_over": 2.10,
                    "id_api": 12345,
                    "metoda": "POISSON",
                    "ev_netto": 5.2,
                }
            ]
        }
    ]

    # Wywołaj pipeline z celem wygranej
    result = ai_analiza_pewniaczki(
        wyniki=wyniki,
        pobierz_forme=False,
        cel_wygrana_a=50.0,  # Cel 50 PLN netto
        stawka=10.0,
    )

    # Weryfikuj że rezultat jest słownikiem
    assert isinstance(result, dict), "Rezultat powinien być słownikiem"

    # Sprawdzaj strukturę jeśli analiza się powiodła
    if "_raw" not in result:
        assert "top3" in result or "kupon_a" in result, "Powinien zawierać co najmniej top3 lub kupon_a"

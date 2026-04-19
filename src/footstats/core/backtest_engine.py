"""
backtest_engine.py – Silnik backtestowania historycznych meczów z feedback do RAG.

Proces:
1. Pobiera mecze w zadanym przedziale dat
2. Dla każdego meczu uruchamia `ai_analiza_pewniaczki()` (simulacja live)
3. Porównuje tip AI z rzeczywistym wynikiem
4. Zapisuje feedback do tabeli `ai_feedback` w SQLite
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Ścieżka do bazy danych
DB_PATH = Path(__file__).parents[2] / "data" / "footstats_backtest.db"


class BacktestEngine:
    """Silnik backtestowania historycznych meczów z RAG feedback."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._ensure_db()

    def _ensure_db(self):
        """Upewnia się, że tabele ai_feedback istnieją."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Tabela ai_feedback: przechowuje wnioski z przegranego kuponów
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT,
                actual_result TEXT,
                ai_prediction TEXT,
                lesson TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

    def backtest_date_range(
        self,
        start_date: str,  # "YYYY-MM-DD"
        end_date: str,    # "YYYY-MM-DD"
        write_feedback: bool = True
    ) -> Dict[str, any]:
        """
        Backtestuje mecze w przedziale dat.

        Args:
            start_date: Data początkowa ("2026-01-01")
            end_date: Data końcowa ("2026-01-07")
            write_feedback: Czy zapisywać feedback do DB

        Returns:
            {
                "total_matches": int,
                "analyzed": int,
                "correct_predictions": int,
                "accuracy": float,
                "matches": [
                    {
                        "match_id": str,
                        "home": str,
                        "away": str,
                        "prediction": str,
                        "actual_result": str,
                        "correct": bool,
                        "lesson": str or None
                    }
                ]
            }
        """
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Daty muszą być w formacie YYYY-MM-DD")

        # Pobierz historyczne mecze z API Football lub bazy
        historical_matches = self._fetch_historical_matches(start, end)

        if not historical_matches:
            logger.warning(f"Brak meczów dla zakresu {start_date} do {end_date}")
            return {
                "total_matches": 0,
                "analyzed": 0,
                "correct_predictions": 0,
                "accuracy": 0.0,
                "matches": []
            }

        results = []
        correct_count = 0

        for match_data in historical_matches:
            match_id = match_data.get("id")
            home_team = match_data.get("home", "")
            away_team = match_data.get("away", "")
            actual_result = match_data.get("result")  # "1", "X", "2", "O2.5", etc.

            try:
                # Symuluj analizę AI (jak gdyby mecz był na żywo)
                prediction = self._simulate_ai_analysis(match_data)

                # Sprawdź czy predykcja była poprawna
                is_correct = prediction == actual_result
                if is_correct:
                    correct_count += 1

                # Jeśli predykcja błędna, wygeneruj lesson
                lesson = None
                if not is_correct and write_feedback:
                    lesson = self._generate_lesson(
                        home_team, away_team, prediction, actual_result
                    )
                    if lesson:
                        self._save_feedback(match_id, actual_result, prediction, lesson)

                results.append({
                    "match_id": match_id,
                    "home": home_team,
                    "away": away_team,
                    "prediction": prediction,
                    "actual_result": actual_result,
                    "correct": is_correct,
                    "lesson": lesson
                })

            except Exception as e:
                logger.error(f"Błąd analizy meczu {match_id}: {e}")
                continue

        accuracy = (correct_count / len(results) * 100) if results else 0.0

        return {
            "total_matches": len(historical_matches),
            "analyzed": len(results),
            "correct_predictions": correct_count,
            "accuracy": round(accuracy, 2),
            "matches": results
        }

    def _fetch_historical_matches(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """
        Pobiera historyczne mecze z zakresu dat.

        TODO: Integruj z API Football lub lokalną bazą wyników.
        Teraz zwraca pusty placeholder.
        """
        # Placeholder: w przyszłości pobierz z API-Football lub db
        # Struktura: {"id", "home", "away", "result": "1"/"X"/"2"/"O2.5"/etc., "date", "league"}
        return []

    def _simulate_ai_analysis(self, match_data: Dict) -> Optional[str]:
        """
        Symuluje analizę AI dla historycznego meczu.

        TODO: Integruj z `ai.analyzer.ai_analiza_pewniaczki()`.
        Teraz zwraca placeholder.

        Returns:
            Predykcja ("1", "X", "2", "O2.5", "BTTS", itd.) lub None
        """
        # Placeholder: w przyszłości wywołaj ai_analiza_pewniaczki()
        # z danymi meczu i pobierz `tip` z odpowiedzi
        return None

    def _generate_lesson(
        self,
        home: str,
        away: str,
        prediction: str,
        actual_result: str
    ) -> Optional[str]:
        """
        Generuje lekcję z przegranej predykcji.

        TODO: Integruj z Groq dla bardziej głębokich analiz.
        """
        lesson = (
            f"Mecz {home} vs {away}: "
            f"Przewidzieliśmy {prediction}, ale wynik to {actual_result}. "
            f"Analizować różnicę w podejściu."
        )
        return lesson

    def _save_feedback(
        self,
        match_id: str,
        actual_result: str,
        prediction: str,
        lesson: str
    ):
        """Zapisuje feedback do tabeli ai_feedback."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO ai_feedback (match_id, actual_result, ai_prediction, lesson)
            VALUES (?, ?, ?, ?)
        """, (match_id, actual_result, prediction, lesson))
        conn.commit()
        conn.close()
        logger.info(f"Feedback zapisany dla meczu {match_id}")

    def get_feedback_summary(self, limit: int = 10) -> List[Dict]:
        """Pobiera podsumowanie ostatnich feedbacków."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM ai_feedback ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]


def backtest_period(
    start_date: str,
    end_date: str,
    write_feedback: bool = True
) -> Dict:
    """
    Uruchamia backtest na okresie.

    Usage:
        result = backtest_period("2026-01-01", "2026-01-07", write_feedback=True)
        print(f"Dokładność: {result['accuracy']}%")
    """
    engine = BacktestEngine()
    return engine.backtest_date_range(start_date, end_date, write_feedback)


if __name__ == "__main__":
    # Przykład użycia
    logging.basicConfig(level=logging.INFO)
    result = backtest_period("2026-01-01", "2026-01-07", write_feedback=True)
    print(f"\nBacktest Result:")
    print(f"  Total matches: {result['total_matches']}")
    print(f"  Analyzed: {result['analyzed']}")
    print(f"  Correct predictions: {result['correct_predictions']}")
    print(f"  Accuracy: {result['accuracy']}%")

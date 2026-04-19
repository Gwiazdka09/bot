#!/usr/bin/env python
"""
run_backtest.py – CLI do uruchamiania backtestów FootStats AI.

Użycie:
    python scripts/run_backtest.py --days 7
    python scripts/run_backtest.py --days 14 --stawka 10 --dry-run
    python scripts/run_backtest.py --days 3 --batch 5
"""

import sys
import os
import argparse
import logging

# Dodaj src/ do path żeby importy footstats działały
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# Załaduj .env
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass


def main():
    parser = argparse.ArgumentParser(
        description="FootStats AI Backtest — analiza historycznych meczów z RAG feedback",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Przykłady:
  python scripts/run_backtest.py --days 7          # Ostatnie 7 dni
  python scripts/run_backtest.py --days 14 --stawka 10  # 14 dni, stawka 10 PLN
  python scripts/run_backtest.py --days 3 --dry-run     # Podgląd bez zapisu do DB
        """,
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Ile dni wstecz analizować (domyślnie 7)",
    )
    parser.add_argument(
        "--stawka", type=float, default=5.0,
        help="Stawka PLN na zakład (domyślnie 5.0)",
    )
    parser.add_argument(
        "--batch", type=int, default=5,
        help="Ile meczów w jednym batchu do Groq (domyślnie 5)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Tylko wyświetl mecze — nie uruchamiaj AI ani nie zapisuj do DB",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Szczegółowe logi",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Sprawdź wymagane klucze
    if not os.getenv("APISPORTS_KEY", "").strip():
        print("\n❌ Brak APISPORTS_KEY w .env — backtest wymaga API-Football")
        print("   Dodaj do .env: APISPORTS_KEY=twoj_klucz_api")
        sys.exit(1)

    if not os.getenv("GROQ_API_KEY", "").strip():
        print("\n❌ Brak GROQ_API_KEY w .env — backtest wymaga Groq")
        print("   Dodaj do .env: GROQ_API_KEY=twoj_klucz_groq")
        sys.exit(1)

    print(f"\n🔄 Uruchamiam backtest: ostatnie {args.days} dni, stawka {args.stawka} PLN")
    if args.dry_run:
        print("   (tryb DRY RUN — bez zapisu do DB)")

    # Langfuse info
    if os.getenv("LANGFUSE_PUBLIC_KEY", "").strip():
        print("   📊 Langfuse aktywny — trace'y będą logowane")
    else:
        print("   ℹ️  Langfuse nieaktywny (opcjonalny — dodaj klucze do .env)")

    print()

    from footstats.core.backtest_engine import backtest_period, print_report

    result = backtest_period(
        days_back=args.days,
        stawka=args.stawka,
        batch_size=args.batch,
        dry_run=args.dry_run,
    )

    print_report(result)

    # Exit code: 0 jeśli sukces, 1 jeśli error
    sys.exit(1 if "error" in result else 0)


if __name__ == "__main__":
    main()

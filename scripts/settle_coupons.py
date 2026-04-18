#!/usr/bin/env python
"""
settle_coupons.py – Rozlicza zaległe ACTIVE kupony.

Skrypt do ręcznego rozliczenia kuponów z wczoraj, gdy API-Football
nie zwrócił wyników. Fallback na FlashScore + RAG feedback dla porażek.

Użycie:
    python scripts/settle_coupons.py [--days 3] [--dry]

Opcje:
    --days N   ile dni wstecz sprawdzać (domyślnie 3)
    --dry      test bez zmian w bazie (domyślnie False)
"""

import sys
import argparse


def main():
    parser = argparse.ArgumentParser(
        description="Rozliczanie zaległych kuponów FootStats",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3,
        help="Ile dni wstecz sprawdzać (domyślnie 3)",
    )
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Test bez zmian w bazie",
    )

    args = parser.parse_args()

    from footstats.core.coupon_settlement import settle_active_coupons

    print(f"\n[CouponSettler] Rozliczanie kuponów sprzed {args.days} dni...")
    if args.dry:
        print("[CouponSettler] Uruchomienie w trybie DRY-RUN (bez zmian)\n")

    stats = settle_active_coupons(
        days_back=args.days,
        dry_run=args.dry,
        verbose=True,
    )

    print(f"\n[CouponSettler] Wynik: {stats}\n")

    if not args.dry and (stats.get("settled", 0) > 0 or stats.get("errors", 0) > 0):
        print("[CouponSettler] Kupony zostały rozliczone. Sprawdź STATUS.md\n")

    return 0 if stats.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

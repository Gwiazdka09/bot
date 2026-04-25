"""
kelly.py – Fractional Kelly Criterion dla FootStats.

Kelly oblicza optymalną stawkę jako % bankrollu żeby zmaksymalizować
długoterminowy wzrost kapitału przy danym edge'u.

Używamy Fractional Kelly (f*/FRACTION) bo pełny Kelly jest bardzo agresywny
i wymaga perfekcyjnej kalibracji prawdopodobieństwa.

Użycie:
    from footstats.core.kelly import kelly_stake, kelly_kupon

    stake = kelly_stake(p=0.65, odds=2.10, bankroll=200, fraction=3)
    # → optymalna stawka w PLN
"""

from footstats.config import AGENT_BANKROLL, AGENT_KELLY_FRACTION


def kelly_stake(
    p: float,
    odds: float,
    bankroll: float = AGENT_BANKROLL,
    fraction: int = AGENT_KELLY_FRACTION,
    min_stake: float = 2.0,
    max_stake: float = 50.0,
) -> float:
    """
    Zwraca optymalną stawkę w PLN (fractional Kelly).

    p        – prawdopodobieństwo wygranej (0–1)
    odds     – kurs bukmachera (np. 2.10)
    bankroll – całkowity bankroll (PLN)
    fraction – dzielnik bezpieczeństwa (3 = f*/3, konserwatywny)

    Wzór: f* = (b*p - q) / b   gdzie b = odds-1, q = 1-p
    Ujemne f* = brak edge = stawka 0.
    """
    if odds <= 1.01 or p <= 0.0 or p >= 1.0:
        return 0.0

    b = odds - 1.0  # zysk netto na 1 PLN
    q = 1.0 - p
    f_star = (b * p - q) / b

    if f_star <= 0:
        return 0.0

    raw = bankroll * f_star / fraction
    return round(max(min_stake, min(raw, max_stake)), 1)


def kelly_kupon(
    zdarzenia: list[dict],
    bankroll: float = AGENT_BANKROLL,
    fraction: int = AGENT_KELLY_FRACTION,
) -> float:
    """
    Kelly dla kuponu AKO.

    Dla kuponu traktujemy go jako jedno zdarzenie:
      p_kupon = iloczyn pewności wszystkich nóg
      odds_kupon = iloczyn kursów

    zdarzenia: lista słowników z kluczami 'pewnosc_pct' i 'kurs'
    """
    if not zdarzenia:
        return 0.0

    p_kupon = 1.0
    odds_kupon = 1.0
    for z in zdarzenia:
        p = z.get("pewnosc_pct", 50) / 100.0
        k = z.get("kurs", 1.0)
        p_kupon   *= p
        odds_kupon *= k

    return kelly_stake(p_kupon, odds_kupon, bankroll, fraction)


def dynamic_stake(
    confidence_pct: int,
    odds: float,
    base_stake: float = 10.0,
) -> float:
    """
    Uproszczony mnożnik stawki bazujący na pewności i kursie.
    
    Wzór:
    - >= 80%  -> x1.5
    - 75-79%  -> x1.2
    - 70-74%  -> x1.0 (baza)
    - 65-69%  -> x0.7
    - < 65%   -> x0.5
    
    Dodatkowo: cap 0.8x jeśli kurs > 2.50 (ochrona przed wysoką zmiennością).
    """
    if confidence_pct >= 80:
        multiplier = 1.5
    elif confidence_pct >= 75:
        multiplier = 1.2
    elif confidence_pct >= 70:
        multiplier = 1.0
    elif confidence_pct >= 65:
        multiplier = 0.7
    else:
        multiplier = 0.5
        
    # Risk adjustment for high odds
    try:
        o = float(odds)
        if o > 2.50:
            multiplier = min(multiplier, 0.8)
    except (ValueError, TypeError):
        pass
        
    return round(base_stake * multiplier, 1)


def ev_netto(p: float, odds: float, podatek: float = 0.12) -> float:
    """
    Expected Value po podatku (Polska: 12% zryczałtowany).
    EV_netto = p * odds * (1 - podatek) - 1
    Wynik > 0 = typ ma wartość.
    """
    return round(p * odds * (1.0 - podatek) - 1.0, 4)


def format_kelly_info(
    p: float,
    odds: float,
    bankroll: float = AGENT_BANKROLL,
    fraction: int = AGENT_KELLY_FRACTION,
) -> str:
    """Zwraca sformatowany string Kelly do wyświetlenia w terminalu."""
    stake  = kelly_stake(p, odds, bankroll, fraction)
    ev     = ev_netto(p, odds)
    sign   = "+" if ev >= 0 else ""
    return f"Kelly={stake:.1f}PLN  EV={sign}{ev*100:.1f}%"

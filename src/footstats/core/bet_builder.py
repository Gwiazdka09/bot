from __future__ import annotations

import math
import numpy as np

def _poisson_prob(k: int, lambd: float) -> float:
    """Zwraca P(X=k) dla rozkładu Poissona."""
    if lambd < 0:
        return 0.0
    return (lambd ** k) * math.exp(-lambd) / math.factorial(k)

def _dixon_coles_tau(x: int, y: int, lh: float, la: float, rho: float) -> float:
    """Korekta Dixon-Coles na niskie wyniki zjawiska (np. niedoszacowane 0-0)."""
    if x == 0 and y == 0:
        return 1.0 - (lh * la * rho)
    elif x == 0 and y == 1:
        return 1.0 + (lh * rho)
    elif x == 1 and y == 0:
        return 1.0 + (la * rho)
    elif x == 1 and y == 1:
        return 1.0 - rho
    return 1.0

def probability_matrix(lh: float, la: float, rho: float = -0.05, max_goals: int = 7) -> np.ndarray:
    """
    Kalkuluje macierz Bivariate Poisson max_goals x max_goals (od 0:0 do 7+).
    Zazwyczaj rho = -0.05 zwiększa trochę wagę niskobramkowych remisów.
    """
    mat = np.zeros((max_goals + 1, max_goals + 1))
    
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            prob = _poisson_prob(h, lh) * _poisson_prob(a, la) * _dixon_coles_tau(h, a, lh, la, rho)
            mat[h, a] = max(0.0, prob)  # korekta ujemna
            
    # Normalize matrix to 1.0 just in case top-end goals cut off residuals
    total = np.sum(mat)
    if total > 0:
        mat = mat / total
        
    return mat

def estimate_lambdas_from_probs(pw: float, pp: float, o25: float) -> tuple[float, float]:
    """Estymuje parametry lambda (home, away) aby minimalizować błąd względem podanych prawdopodobieństw z modelu (np. Bzzoiro)."""
    best_lh, best_la = 1.0, 1.0
    best_loss = 999.0
    
    # Przeszukujemy bazowe wartości dla oczekiwanych goli
    lambdas = np.linspace(0.1, 3.5, 35)
    for lh in lambdas:
        for la in lambdas:
            mat = probability_matrix(lh, la, rho=-0.05)
            
            sim_pw = np.sum(np.tril(mat, -1))
            sim_pp = np.sum(np.triu(mat, 1))
            sim_o25 = sum(mat[h, a] for h in range(7) for a in range(7) if h+a > 2.5)
                    
            loss = (sim_pw - pw)**2 + (sim_pp - pp)**2 + (sim_o25 - o25)**2
            if loss < best_loss:
                best_loss = loss
                best_lh = lh
                best_la = la
                
    return round(float(best_lh), 2), round(float(best_la), 2)

def get_card_suggestions(ref_avg_yellow: float | None) -> list[str]:
    """Zwraca sugestie zakładów na kartki na podstawie rygorystyczności sędziego."""
    if not ref_avg_yellow or ref_avg_yellow <= 0:
        return []
    
    sugestie = []
    # Heurystyka na podstawie średniej ligowej/sędziowskiej
    if ref_avg_yellow > 4.5:
        sugestie.append(f"Powyżej 3.5 kartek (Sędzia avg: {ref_avg_yellow})")
    if ref_avg_yellow > 5.5:
        sugestie.append(f"Powyżej 4.5 kartek (Sędzia avg: {ref_avg_yellow})")
    if ref_avg_yellow < 3.2:
        sugestie.append(f"Poniżej 4.5 kartek (Sędzia avg: {ref_avg_yellow})")
    
    return sugestie

def get_betbuilder_suggestions(lh: float, la: float, max_goals: int = 7, ref_avg_yellow: float | None = None) -> list[str]:
    """
    Na podstawie (lambda_home, lambda_away) zwraca stringi z sugestiami BetBuildera.
    Proponuje tylko te zdarzenia, które statystycznie mają >50% szans na wejście.
    Opcjonalnie uwzględnia statystyki sędziego dla rynku kartek.
    """
    if lh <= 0 or la <= 0:
        return []

    mat = probability_matrix(lh, la, max_goals=max_goals)
    sugestie = []
    
    # 1. 1 & Over 1.5 (Gospodarz wygrywa + >1.5 goli w meczu)
    p_1_o15 = sum(mat[h, a] for h in range(max_goals+1) for a in range(max_goals+1) if h > a and h + a > 1.5)
    # 2. 1 & BTTS (Gospodarz wygrywa + Oba strzelą)
    p_1_btts = sum(mat[h, a] for h in range(max_goals+1) for a in range(max_goals+1) if h > a and h >= 1 and a >= 1)
    # 3. 2 & Over 1.5 (Gość wygrywa + >1.5 goli w meczu)
    p_2_o15 = sum(mat[h, a] for h in range(max_goals+1) for a in range(max_goals+1) if a > h and h + a > 1.5)
    # 4. BTTS & Over 2.5
    p_btts_o25 = sum(mat[h, a] for h in range(1, max_goals+1) for a in range(1, max_goals+1) if h + a > 2.5)
    # 5. X | U3.5 (Remis, poniżej 3.5 gola) - czyli głównie padnie 0:0 lub 1:1
    p_x_u35 = sum(mat[h, a] for h in range(max_goals+1) for a in range(max_goals+1) if h == a and h + a < 3.5)

    if p_1_o15 > 0.35:
        sugestie.append(f"1 & Over 1.5 (Szansa: {int(p_1_o15 * 100)}%)")
    if p_1_btts > 0.25: # BTTS win jest bardzo lukratywny
        sugestie.append(f"1 & BTTS (Szansa: {int(p_1_btts * 100)}%)")
    if p_2_o15 > 0.35:
        sugestie.append(f"2 & Over 1.5 (Szansa: {int(p_2_o15 * 100)}%)")
    if p_btts_o25 > 0.40:
        sugestie.append(f"BTTS & Over 2.5 (Szansa: {int(p_btts_o25 * 100)}%)")
    if p_x_u35 > 0.25: 
        sugestie.append(f"X & Under 3.5 (Szansa: {int(p_x_u35 * 100)}%)")

    # 6. Handicap -1 (Gospodarz wygrywa różnicą >= 2 goli)
    p_hc_m1 = sum(mat[h, a] for h in range(max_goals+1) for a in range(max_goals+1) if (h - a) >= 2)
    # 7. Handicap +1 gość (Gość wygrywa lub remis po dodaniu 1 gola)
    p_hc_p1_away = sum(mat[h, a] for h in range(max_goals+1) for a in range(max_goals+1) if (a + 1) >= h)
    # 8. Over 1.5 (>1.5 goli w meczu)
    p_o15 = sum(mat[h, a] for h in range(max_goals+1) for a in range(max_goals+1) if h + a > 1.5)
    # 9. Under 2.5
    p_u25 = sum(mat[h, a] for h in range(max_goals+1) for a in range(max_goals+1) if h + a < 2.5)
    # 10. Over 3.5
    p_o35 = sum(mat[h, a] for h in range(max_goals+1) for a in range(max_goals+1) if h + a > 3.5)
    # 11. Home Over 0.5 (Gospodarz strzeli >= 1)
    p_home_o05 = sum(mat[h, a] for h in range(1, max_goals+1) for a in range(max_goals+1))
    # 12. Away Over 0.5 (Gość strzeli >= 1)
    p_away_o05 = sum(mat[h, a] for h in range(max_goals+1) for a in range(1, max_goals+1))
    # 13. Home Over 1.5 (Gospodarz strzeli >= 2)
    p_home_o15 = sum(mat[h, a] for h in range(2, max_goals+1) for a in range(max_goals+1))
    # 14. 1.połowa Over 0.5 (uproszczona estymacja ~60% of full-time goals in 1H)
    lh_1h, la_1h = lh * 0.45, la * 0.45
    mat_1h = probability_matrix(lh_1h, la_1h, max_goals=4)
    p_1h_o05 = sum(mat_1h[h, a] for h in range(5) for a in range(5) if h + a > 0.5)
    # 15. 1.połowa BTTS
    p_1h_btts = sum(mat_1h[h, a] for h in range(1, 5) for a in range(1, 5))

    if p_hc_m1 > 0.30:
        sugestie.append(f"Handicap -1 Gospodarz (Szansa: {int(p_hc_m1 * 100)}%)")
    if p_hc_p1_away > 0.60:
        sugestie.append(f"Handicap +1 Gość (Szansa: {int(p_hc_p1_away * 100)}%)")
    if p_o15 > 0.80:
        sugestie.append(f"Over 1.5 (Szansa: {int(p_o15 * 100)}%)")
    if p_u25 > 0.45:
        sugestie.append(f"Under 2.5 (Szansa: {int(p_u25 * 100)}%)")
    if p_o35 > 0.40:
        sugestie.append(f"Over 3.5 (Szansa: {int(p_o35 * 100)}%)")
    if p_home_o05 > 0.75:
        sugestie.append(f"Gospodarz strzeli 0.5+ (Szansa: {int(p_home_o05 * 100)}%)")
    if p_away_o05 > 0.70:
        sugestie.append(f"Gość strzeli 0.5+ (Szansa: {int(p_away_o05 * 100)}%)")
    if p_home_o15 > 0.45:
        sugestie.append(f"Gospodarz strzeli 1.5+ (Szansa: {int(p_home_o15 * 100)}%)")
    if p_1h_o05 > 0.70:
        sugestie.append(f"1.Połowa Over 0.5 (Szansa: {int(p_1h_o05 * 100)}%)")
    if p_1h_btts > 0.20:
        sugestie.append(f"1.Połowa BTTS (Szansa: {int(p_1h_btts * 100)}%)")

    # Dodaj sugestie kartek jeśli sędzia jest znany
    if ref_avg_yellow:
        sugestie.extend(get_card_suggestions(ref_avg_yellow))

    return sugestie


def get_corner_suggestions(lh: float, la: float) -> list[str]:
    """Corner suggestions based on expected goal-scoring activity."""
    sugestie = []
    total_lambda = lh + la
    # Heuristic: ~3.5 corners per expected goal (league average ~10 corners per match)
    est_corners = total_lambda * 3.5
    if est_corners > 10.5:
        sugestie.append(f"Rzuty rożne Over 10.5 (Est: {est_corners:.1f})")
    if est_corners > 9.5:
        sugestie.append(f"Rzuty rożne Over 9.5 (Est: {est_corners:.1f})")
    if est_corners < 8.5:
        sugestie.append(f"Rzuty rożne Under 9.5 (Est: {est_corners:.1f})")
    # Dominant attack → more corners for that team
    if lh > la * 1.5:
        sugestie.append(f"Gospodarz rożne Over 5.5 (Atak dominujący)")
    if la > lh * 1.5:
        sugestie.append(f"Gość rożne Over 5.5 (Atak dominujący)")
    return sugestie


def get_all_market_suggestions(lh: float, la: float, ref_avg_yellow: float | None = None) -> dict[str, list[str]]:
    """
    Returns all market suggestions grouped by category.
    Categories: BetBuilder, Kartki, Rożne, Handicap, Połowy, Gole
    """
    bb = get_betbuilder_suggestions(lh, la, ref_avg_yellow=ref_avg_yellow)
    corners = get_corner_suggestions(lh, la)
    cards = get_card_suggestions(ref_avg_yellow) if ref_avg_yellow else []

    markets = {}
    if bb:
        markets["BetBuilder"] = bb
    if corners:
        markets["Rzuty rożne"] = corners
    if cards:
        markets["Kartki"] = cards

    return markets

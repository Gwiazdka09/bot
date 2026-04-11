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

    # Dodaj sugestie kartek jeśli sędzia jest znany
    if ref_avg_yellow:
        sugestie.extend(get_card_suggestions(ref_avg_yellow))

    return sugestie

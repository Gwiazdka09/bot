#!/usr/bin/env python
"""lambda_czy_ksztalt.py — czy mylimy się w OCZEKIWANEJ LICZBIE GOLI, czy w rozkładzie.

===========================  PRE-REJESTRACJA  ===============================
Spisana 2026-09-04, PRZED policzeniem czegokolwiek.

DLACZEGO TO PYTANIE JEST NASTĘPNE W KOLEJCE. Wiemy już bardzo dużo o TYM, ŻE
model przegrywa, i nic o TYM, GDZIE. Zmierzone: gorszy od ceny w 39 ligach na
39, gorszy na rynku golowym w 22 na 22, dołożony do ceny — szkodzi, a jego
niezgoda z ceną jest błędna tym bardziej, im większa. Wszystkie te pomiary
traktują model jak jedną bryłę.

A model to dwie warstwy złożone szeregowo:
    oceny sił drużyn  →  (λ_gospodarz, λ_gość)  →  macierz Poissona  →  1X2
Zepsuta może być każda z osobna i naprawia się je zupełnie inaczej. Bez tego
rozdzielenia każda dalsza praca nad modelem to zgadywanie.

JAK ROZDZIELAMY, BEZ ZAKŁADANIA CZEGOKOLWIEK O NASZYM KODZIE. Nasze 1X2
powstało Z λ przez macierz, więc λ da się z niego odzyskać: dwa stopnie
swobody rozkładu 1X2 odpowiadają dokładnie dwóm parametrom. Tak samo odzyskujemy
λ IMPLIKOWANE PRZEZ CENĘ — co daje parę porównywalnych oczekiwań bramkowych,
naszą i rynku, dla tych samych meczów.

TRZY POMIARY:

  1. CZYJE λ LEPIEJ PRZEWIDUJE GOLE. Log-wiarygodność Poissona faktycznych
     `hg`/`ag` pod λ_model i pod λ_rynek, sparowana po meczach. To jest test
     samych ocen sił drużyn, zupełnie w oderwaniu od tego, co potem robimy
     z macierzą. Jeśli przegrywamy tutaj — problemem są RATINGI.

  2. CZY KSZTAŁT W OGÓLE WYSTARCZA. Do λ dopasowanego do 1X2 RYNKU liczymy
     implikowane Over 2.5 i porównujemy z realnym rynkiem Over 2.5 (22 ligi
     europejskie, gdzie mamy `odds_over25_pinn`). Rynek jest wewnętrznie
     spójny; jeśli Poisson z jego własnym λ NIE odtwarza jego Over 2.5, to
     znaczy, że rozkład Poissona nie mieści tego, co rynek wie — i wtedy sufit
     stoi w KSZTAŁCIE, nie w ratingach.

  3. PODSTAWIENIE KRZYŻOWE, czyli ile realnie da się ugrać. Bierzemy λ RYNKU
     i przepuszczamy przez NASZĄ macierz. Powstałe 1X2 porównujemy Brierem
     z naszym i z rynkowym. Odpowiada wprost: gdybyśmy mieli oczekiwania
     bramkowe rynku, a resztę zostawili jak jest, ile z luki −0.0235 by zniknęło.

MACIERZ. Ta sama co w produkcji: bivariate Poisson z korektą Dixona-Colesa
przy `rho=-0.05` i obcięciem na 7 golach (`core/bet_builder.probability_matrix`).
Tutaj policzona wektorowo, bo tamta wersja buduje 8x8 pętlą i przy 100 tys.
meczów razy setki iteracji dopasowania byłaby nie do przejścia. Zgodność obu
implementacji ma test — bez niego mierzyłbym inny model niż produkcyjny.

PRÓBA. Losowe 20 000 meczów ze zrzutu walk-forward (ziarno 20260904), bo
dopasowanie λ to optymalizacja per mecz. Przy sparowanych różnicach i n=20 000
wykrywamy efekty o rząd wielkości mniejsze niż mierzone luki, więc pełna próba
niczego by nie zmieniła. Gole doklejane z `full_dataset` — odsetek dopasowania
raportowany, poniżej 90% przerywamy.

REGUŁA DECYZYJNA, ZAMROŻONA:
  * pomiar 1, z <= −2 (λ rynku lepsze) ORAZ pomiar 3 zamyka >= 1/3 luki
        → wąskim gardłem są OCENY SIŁ DRUŻYN. Praca idzie w estymator:
          okno `.tail(30)`, zanik czasowy, przewaga gospodarza — wszystkie
          wpisane z ręki i nigdy niedopasowane.
  * pomiar 1 |z| < 2 (λ porównywalne)
        → ratingi nie są problemem; luka siedzi dalej w łańcuchu.
  * pomiar 2 pokazuje duży rozjazd Over 2.5
        → Poisson z korektą DC nie mieści tego, co rynek wie o rozkładzie.
          Wtedy strojenie ratingów nie pomoże i trzeba ruszyć KSZTAŁT.
  * pomiar 3 zamyka < 1/3 luki mimo lepszego λ rynku
        → nawet doskonałe oczekiwania bramkowe nie wystarczą; to najmocniejsza
          możliwa forma tezy o suficie.

CZEGO TO NIE ZMIENIA: model dalej przegrywa z ceną. To pomiar lokalizujący,
nie naprawa.
=============================================================================

    python scripts/lambda_czy_ksztalt.py --zrzut sciezka/zrzut*.parquet
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import minimize  # noqa: E402
from scipy.stats import poisson as _poisson  # noqa: E402

from przewaga_nad_rynkiem import brier_wieloklasowy, sparowana_roznica  # noqa: E402

ZIARNO = 20260904
PROBA = 20000
MAX_GOLI = 7
RHO = -0.05
MIN_JOIN = 0.90
WYNIK_NA_INDEKS = {"H": 0, "D": 1, "A": 2}
KOL_PINN = ("odds_h_pinn", "odds_d_pinn", "odds_a_pinn")


def macierz(lh: float, la: float) -> np.ndarray:
    """Bivariate Poisson z korektą Dixona-Colesa — wektorowo.

    Odpowiednik `core/bet_builder.probability_matrix`, ale bez pętli po 64
    komórkach. Zgodność pilnuje `tests/test_lambda_czy_ksztalt.py`; gdyby się
    rozjechały, mierzylibyśmy inny model niż ten, który gra na produkcji.
    """
    h = np.arange(MAX_GOLI + 1)
    m = np.outer(_poisson.pmf(h, lh), _poisson.pmf(h, la))
    tau = np.ones_like(m)
    tau[0, 0] = 1.0 - lh * la * RHO
    tau[0, 1] = 1.0 + lh * RHO
    tau[1, 0] = 1.0 + la * RHO
    tau[1, 1] = 1.0 - RHO
    m = np.maximum(m * tau, 0.0)
    s = m.sum()
    return m / s if s > 0 else m


def _wyjscia(m: np.ndarray) -> tuple[float, float, float]:
    """(p_gospodarz, p_gosc, p_over25) z macierzy wynikow."""
    pw = float(np.tril(m, -1).sum())
    pp = float(np.triu(m, 1).sum())
    h = np.arange(MAX_GOLI + 1)
    over = float(m[(h[:, None] + h[None, :]) > 2.5].sum())
    return pw, pp, over


def dopasuj_lambdy(pw: float, pp: float) -> tuple[float, float]:
    """λ odtwarzające zadane 1X2. Dwa parametry, dwa cele — układ wyznaczony.

    Start z grubego przybliżenia, potem Nelder-Mead: siatka 35x35 z
    `estimate_lambdas_from_probs` daje krok 0.1 i przy 20 tys. meczów jest
    zarówno wolniejsza, jak i mniej dokładna.
    """
    def strata(x: np.ndarray) -> float:
        lh, la = float(np.clip(x[0], 0.05, 6.0)), float(np.clip(x[1], 0.05, 6.0))
        s_pw, s_pp, _ = _wyjscia(macierz(lh, la))
        return (s_pw - pw) ** 2 + (s_pp - pp) ** 2

    res = minimize(strata, np.array([1.4, 1.1]), method="Nelder-Mead",
                   options={"xatol": 1e-3, "fatol": 1e-8, "maxiter": 300})
    return float(np.clip(res.x[0], 0.05, 6.0)), float(np.clip(res.x[1], 0.05, 6.0))


def wczytaj(wzorce: list[str]) -> pd.DataFrame:
    pliki: list[str] = []
    for w in wzorce:
        pliki += sorted(glob.glob(w))
    if not pliki:
        raise SystemExit(f"Zero plikow dla {wzorce}")
    df = pd.concat([pd.read_parquet(p) for p in pliki], ignore_index=True)
    df = df[df["actual_res"].isin(WYNIK_NA_INDEKS)]
    k = df[list(KOL_PINN)].to_numpy(dtype=float)
    df = df[np.isfinite(k).all(axis=1) & (k > 1.0).all(axis=1)]

    from footstats.data.historical_loader import load_cached
    baza = load_cached()
    baza["match_date"] = pd.to_datetime(baza["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    gole = baza[["league", "match_date", "home", "away", "hg", "ag",
                 "odds_over25_pinn", "odds_under25_pinn"]]
    df = df.merge(gole, on=["league", "match_date", "home", "away"],
                  how="left", validate="m:1")
    udane = float(df[["hg", "ag"]].notna().all(axis=1).mean())
    print(f"Zrzut: {len(df)} meczow | gole doklejone do {100 * udane:.1f}%")
    if udane < MIN_JOIN:
        raise SystemExit(f"Join ponizej {MIN_JOIN:.0%} — przerywam.")
    return df[df[["hg", "ag"]].notna().all(axis=1)].reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--zrzut", nargs="+", required=True)
    ap.add_argument("--proba", type=int, default=PROBA)
    args = ap.parse_args()

    df = wczytaj(args.zrzut)
    rng = np.random.default_rng(ZIARNO)
    if len(df) > args.proba:
        df = df.iloc[rng.choice(len(df), args.proba, replace=False)].reset_index(drop=True)
    print(f"Do pomiaru: {len(df)} meczow, {df['league'].nunique()} lig")

    p_mod = df[["pw", "pr", "pp"]].to_numpy(dtype=float) / 100.0
    inv = 1.0 / df[list(KOL_PINN)].to_numpy(dtype=float)
    p_ryn = inv / inv.sum(axis=1, keepdims=True)
    y = df["actual_res"].map(WYNIK_NA_INDEKS).to_numpy(dtype=int)
    hg = df["hg"].to_numpy(dtype=float)
    ag = df["ag"].to_numpy(dtype=float)

    lam_mod = np.array([dopasuj_lambdy(p[0], p[2]) for p in p_mod])
    lam_ryn = np.array([dopasuj_lambdy(p[0], p[2]) for p in p_ryn])

    raport_1(lam_mod, lam_ryn, hg, ag)
    raport_2(df, lam_ryn)
    raport_3(lam_ryn, p_mod, p_ryn, y)


def _log_wiar(lam: np.ndarray, hg: np.ndarray, ag: np.ndarray) -> np.ndarray:
    """Log-wiarygodność faktycznych goli pod danymi λ, per mecz."""
    return (_poisson.logpmf(hg, lam[:, 0]) + _poisson.logpmf(ag, lam[:, 1]))


def raport_1(lam_mod, lam_ryn, hg, ag) -> None:
    print("\n" + "=" * 92)
    print("  POMIAR 1 — czyje OCZEKIWANIA BRAMKOWE lepiej przewiduja gole")
    print("=" * 92)
    ll_m = _log_wiar(lam_mod, hg, ag)
    ll_r = _log_wiar(lam_ryn, hg, ag)
    d = sparowana_roznica(ll_m, ll_r)      # dodatnie = NASZE lambda lepsze
    print(f"  srednia log-wiarygodnosc:  model {ll_m.mean():+.5f}"
          f"   rynek {ll_r.mean():+.5f}")
    print(f"  sparowana roznica (model - rynek) {d['roznica']:+.5f}"
          f"  SE {d['se']:.5f}  z {d['z']:+.2f}")
    print(f"\n  srednie lambda:  model {lam_mod[:, 0].mean():.3f} / {lam_mod[:, 1].mean():.3f}"
          f"   rynek {lam_ryn[:, 0].mean():.3f} / {lam_ryn[:, 1].mean():.3f}")
    roz = np.abs(lam_mod - lam_ryn).mean(axis=0)
    print(f"  srednia |roznica| lambda:  gospodarz {roz[0]:.3f}  gosc {roz[1]:.3f}")


def raport_2(df: pd.DataFrame, lam_ryn: np.ndarray) -> None:
    print("\n" + "=" * 92)
    print("  POMIAR 2 — czy Poisson z lambda RYNKU odtwarza Over 2.5 RYNKU")
    print("=" * 92)
    kol = ["odds_over25_pinn", "odds_under25_pinn"]
    k = df[kol].to_numpy(dtype=float)
    ok = np.isfinite(k).all(axis=1) & (k > 1.0).all(axis=1)
    if ok.sum() < 1000:
        print("  Za malo meczow z cena Over/Under — pomijam.")
        return
    ia, ib = 1.0 / k[ok, 0], 1.0 / k[ok, 1]
    over_ryn = ia / (ia + ib)
    over_poi = np.array([_wyjscia(macierz(*l))[2] for l in lam_ryn[ok]])
    d = over_poi - over_ryn
    print(f"  n={int(ok.sum())}   Over 2.5 rynku {over_ryn.mean():.4f}"
          f"   z Poissona {over_poi.mean():.4f}")
    print(f"  srednie obciazenie {d.mean():+.4f}   srednie |odchylenie| {np.abs(d).mean():.4f}")
    print("  Rynek jest wewnetrznie spojny. Duzy rozjazd znaczy, ze rozklad")
    print("  Poissona NIE MIESCI tego, co rynek wie — sufit w KSZTALCIE.")


def raport_3(lam_ryn, p_mod, p_ryn, y) -> None:
    print("\n" + "=" * 92)
    print("  POMIAR 3 — lambda RYNKU przepuszczone przez NASZA macierz")
    print("=" * 92)
    hyb = np.zeros_like(p_mod)
    for i, l in enumerate(lam_ryn):
        pw, pp, _ = _wyjscia(macierz(*l))
        hyb[i] = [pw, max(0.0, 1.0 - pw - pp), pp]

    b_mod = brier_wieloklasowy(p_mod, y)
    b_ryn = brier_wieloklasowy(p_ryn, y)
    b_hyb = brier_wieloklasowy(hyb, y)
    luka = float(b_mod.mean() - b_ryn.mean())
    zamkniete = float(b_mod.mean() - b_hyb.mean())
    print(f"  Brier:  model {b_mod.mean():.4f}   hybryda {b_hyb.mean():.4f}"
          f"   rynek {b_ryn.mean():.4f}")
    print(f"  luka model-rynek {luka:+.5f}"
          f"   zamkniete przez sama podmiane lambda {zamkniete:+.5f}"
          f"   ({100 * zamkniete / luka if luka else 0:.0f}%)")
    d = sparowana_roznica(b_mod, b_hyb)
    print(f"  sparowane model-hybryda {d['roznica']:+.5f}  SE {d['se']:.5f}"
          f"  z {d['z']:+.2f}")

    print("\n  REGULA DECYZYJNA (zamrozona przed przebiegiem):")
    udzial = zamkniete / luka if luka else 0.0
    if udzial >= 1 / 3:
        print("    Podmiana samych lambd zamyka >= 1/3 luki -> waskim gardlem sa")
        print("    OCENY SIL DRUZYN. Praca idzie w estymator: okno .tail(30),")
        print("    zanik czasowy, przewaga gospodarza — nigdy niedopasowane.")
    else:
        print("    Podmiana lambd zamyka < 1/3 luki -> nawet doskonale oczekiwania")
        print("    bramkowe nie wystarcza. Najmocniejsza forma tezy o suficie.")


if __name__ == "__main__":
    main()

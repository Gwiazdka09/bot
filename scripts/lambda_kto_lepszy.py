#!/usr/bin/env python
"""lambda_kto_lepszy.py — przeliczenie pomiaru 1 z 04.09 na poprawnej macierzy.

===========================  PRE-REJESTRACJA  ===============================
Spisana 2026-09-05, PRZED policzeniem czegokolwiek.

CO PROSTUJEMY. Pomiar z 04.09 (`lambda_czy_ksztalt.py`) orzekł, że oczekiwania
bramkowe rynku biją nasze — sparowana log-wiarygodność faktycznych goli
−0.09404, SE 0.00398, z=−23.65. Ta liczba stała się podstawą całej dalszej
pracy nad estymatorem. Ma jednak wadę narzędzia:

  * λ MODELU nie było czytane, tylko ODZYSKIWANE z jego 1X2;
  * odzyskiwanie szło macierzą Dixona-Colesa przy `rho=-0.05`;
  * a produkcja generuje to 1X2 przy `rho=0` — `USE_DC_TAU` jest wyłączone,
    `poisson._macierz` to czysty iloczyn zewnętrzny.

Macierz odzyskująca była inna niż generująca. Zmierzone na 400 losowych parach:
zawyża λ o +7.2% / +7.9%. Odzyskane λ modelu (1.573/1.264) było więc zawyżone,
a prawdziwe, odczytane wprost ścieżką ligową, wynosi 1.4726/1.1666 przy
faktycznych 1.4883/1.1790.

DLACZEGO TO NIE JEST KOSMETYKA. Skażenie było OBUSTRONNE (obie λ odzyskiwane tą
samą złą macierzą), więc kierunek mógł przeżyć — ale nie wiadomo tego bez
policzenia. A jeśli po poprawce różnica zniknie, to cała teza „wąskim gardłem są
ratingi" nie ma pod sobą pomiaru.

CO ROBIMY INACZEJ:
  1. λ MODELU CZYTAMY, nie odzyskujemy. Ścieżka ligowa produkcji
     (`form.sily_ligowe` → `_baza_ligowa`), odtworzona w `estymator_lambda.py`
     i pilnowana 22 testami parytetu. Zero błędu odzyskiwania po naszej stronie.
  2. λ RYNKU odzyskujemy przy `rho=0` — TĄ macierzą, którą produkcja realnie
     liczy 1X2. Rynek nie ma „prawdziwego λ", więc odzyskanie jest tu rzutem
     z konieczności; ale rzut ma iść na tę samą przestrzeń, w której siedzi nasz
     model, inaczej porównujemy dwie różne rzeczy.
  3. Konfiguracja estymatora PRODUKCYJNA (okno 30, płaskie wagi, bez ściągania,
     `WAGA_STRZALOW=0.7`). Pytamy o model, który gra, nie o dopasowany wczoraj.

PRÓBA: wszystkie mecze z zamknięciem Pinnacle i kompletem ratingów, cała
historia. Nic tu nie jest dopasowywane, więc podział na trening i holdout nie ma
czego chronić; osobno raportujemy rozbicie po ligach.

POMIAR A — CZYJE λ LEPIEJ PRZEWIDUJE GOLE.
Sparowana różnica log-wiarygodności Poissona faktycznych `hg`/`ag`, model minus
rynek. To jest dokładnie pytanie pomiaru 1, tylko bez błędu narzędzia.

POMIAR B — POZIOMY. Średnie λ obu stron kontra faktyczne średnie gole, plus
średni błąd bezwzględny. Odpowiada, czy któraś strona jest obciążona i w którą
stronę — pytanie, na które wczoraj odpowiedziałem źle.

POMIAR C — CZY POISSON MIEŚCI TO, CO RYNEK WIE (powtórka pomiaru 2 przy rho=0).
Z λ rynku liczymy implikowane Over 2.5 i porównujemy z rynkowym Over 2.5 tam,
gdzie mamy `odds_over25_pinn`. Wczorajsza wersja szła przy `rho=-0.05` i dała
obciążenie −0.0326; przy rho=0 rozkład jest inny, więc liczba może być inna.

REGUŁA DECYZYJNA, ZAMROŻONA:
  * pomiar A, z <= −3  → rynek ma lepsze oczekiwania bramkowe. Teza „wąskim
    gardłem są ratingi" STOI, mimo błędu wczorajszego narzędzia.
  * pomiar A, |z| < 3  → różnica nie przeżyła poprawki. Wtedy wniosek z 04.09
    był artefaktem macierzy i trzeba go wycofać w całości, razem z kierunkiem
    dalszej pracy.
  * pomiar A, z >= +3  → to NASZE λ jest lepsze, a wczorajszy wynik był
    odwrócony przez narzędzie. Wynik równie ważny jak poprzedni i wymagałby
    osobnego wyjaśnienia, skąd wtedy przewaga rynku w 1X2.
  * pomiar B rozstrzygamy opisowo — to nie jest test hipotezy, tylko poziomy.

CZEGO TO NIE ZMIENIA. Model dalej przegrywa z ceną w Brierze 1X2 i to jest
zmierzone niezależnie od tego pomiaru, na dużo większej próbie.
=============================================================================

    python scripts/lambda_kto_lepszy.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

_KORZEN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_KORZEN / "src"))
sys.path.insert(0, str(_KORZEN / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import poisson as _poisson  # noqa: E402

from estymator_lambda import (  # noqa: E402
    KLUCZE, MAX_GOLI, PROD, _sklej, devig, lambdy, logwiar_goli,
    maska_uzywalnych, p_1x2, sparowana, zbierz,
)

MAX_ITER = 40
TOL = 1e-10
# Pudelko fizycznie sensownych lambd. Gorna granica jest tu istotna: powyzej
# niej obciecie na MAX_GOLI czyni rozklad niezaleznym od lambdy i rodzi
# pierwiastki pozorne (patrz `odzyskaj_lambdy`).
LAM_MIN, LAM_MAX = 0.05, 6.0
STARTY = ((1.5, 1.2), (0.6, 0.6), (2.5, 1.0), (1.0, 2.5), (0.4, 1.8), (1.8, 0.4))
KOL_OVER = ("odds_over25_pinn", "odds_under25_pinn")


def over25_z_lambd(lg: np.ndarray, la: np.ndarray) -> np.ndarray:
    """P(suma goli > 2.5) z macierzy Poissona przy rho=0 — jak `poisson._macierz`."""
    h = np.arange(MAX_GOLI)
    pg = _poisson.pmf(h[None, :], lg[:, None])
    pa = _poisson.pmf(h[None, :], la[:, None])
    pg /= pg.sum(axis=1, keepdims=True)
    pa /= pa.sum(axis=1, keepdims=True)
    m = pg[:, :, None] * pa[:, None, :]
    suma = h[:, None] + h[None, :]
    return m[:, suma > 2.5].sum(axis=1)


def _newton(pw_c: np.ndarray, pp_c: np.ndarray,
            start: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    """Jeden przebieg Newtona po `log λ` z jednego punktu startu.

    Wektorowo dla wszystkich meczów naraz — Nelder-Mead per mecz przy 100 tys.
    wierszy byłby liczony godzinami. Log zapewnia dodatniość λ.
    """
    x = np.stack([np.full(len(pw_c), np.log(start[0])),
                  np.full(len(pw_c), np.log(start[1]))], axis=1)
    eps = 1e-5
    lo, hi = np.log(LAM_MIN), np.log(LAM_MAX)
    for _ in range(MAX_ITER):
        lam = np.exp(x)
        p = p_1x2(lam[:, 0], lam[:, 1])
        f = np.stack([p[:, 0] - pw_c, p[:, 2] - pp_c], axis=1)
        if np.nanmax(np.abs(f)) < TOL:
            break
        # Jakobian numeryczny: dwie kolumny, każda jedno przesunięcie w log λ.
        j = np.empty((len(x), 2, 2))
        for k in range(2):
            xp = x.copy()
            xp[:, k] += eps
            lp = np.exp(xp)
            pk = p_1x2(lp[:, 0], lp[:, 1])
            j[:, 0, k] = (pk[:, 0] - p[:, 0]) / eps
            j[:, 1, k] = (pk[:, 2] - p[:, 2]) / eps
        det = j[:, 0, 0] * j[:, 1, 1] - j[:, 0, 1] * j[:, 1, 0]
        osobliwe = np.abs(det) < 1e-12
        det = np.where(osobliwe, 1.0, det)
        krok = np.stack([
            (j[:, 1, 1] * f[:, 0] - j[:, 0, 1] * f[:, 1]) / det,
            (-j[:, 1, 0] * f[:, 0] + j[:, 0, 0] * f[:, 1]) / det,
        ], axis=1)
        # Tłumienie: pełny krok Newtona potrafi wystrzelić λ w kosmos przy
        # prawdopodobieństwach bliskich krawędzi.
        krok = np.clip(krok, -0.5, 0.5)
        x = np.where(osobliwe[:, None], x, np.clip(x - krok, lo, hi))

    lam = np.exp(x)
    p = p_1x2(lam[:, 0], lam[:, 1])
    trafia = (np.abs(p[:, 0] - pw_c) < 1e-6) & (np.abs(p[:, 2] - pp_c) < 1e-6)
    # Rozwiązanie NA krawędzi pudełka to zwykle nie rozwiązanie, tylko miejsce,
    # w którym Newton się zatrzymał — odrzucamy je jak niezbieżne.
    w_srodku = (lam > LAM_MIN * 1.01).all(axis=1) & (lam < LAM_MAX * 0.99).all(axis=1)
    return lam, trafia & w_srodku


def odzyskaj_lambdy(pw_c: np.ndarray, pp_c: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """λ odtwarzające zadane (p_gospodarz, p_gość) przy `rho=0`.

    UWAGA, TO NIE JEST UKŁAD JEDNOZNACZNY. Macierz produkcyjna obcina na
    `MAX_GOLI=8` i renormalizuje, więc dla dużych λ cała masa siedzi w ogonie
    i rozkład przestaje zależeć od λ. Skutek: para (4.39, 21.64) daje 1X2 co do
    szóstego miejsca identyczne z (0.5, 2.9). Pojedynczy Newton potrafi
    wylądować na tej drugiej gałęzi i zwrócić λ bez sensu fizycznego, meldując
    zbieżność — dokładnie ta pułapka, której 04.09 nie zauważyłem.

    Stąd: kilka startów, odrzucenie rozwiązań na krawędzi pudełka i wybór
    pierwiastka o NAJMNIEJSZEJ sumie λ. Gałąź pozorna wymaga λ tak dużych, że
    obcięcie zdążyło zjeść rozkład, więc zawsze leży wyżej.

    Zwraca (λ_gosp, λ_gość, zbieglo). Wiersze niezbieżne wypadają z pomiaru
    i są raportowane — cicha rozbieżność udawałaby dane.
    """
    najlepsze = np.full((len(pw_c), 2), np.nan)
    zbieglo = np.zeros(len(pw_c), dtype=bool)
    suma = np.full(len(pw_c), np.inf)
    for start in STARTY:
        lam, ok = _newton(pw_c, pp_c, start)
        s = lam.sum(axis=1)
        lepsze = ok & (s < suma)
        najlepsze[lepsze] = lam[lepsze]
        suma[lepsze] = s[lepsze]
        zbieglo |= ok
    return najlepsze[:, 0], najlepsze[:, 1], zbieglo


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wynik", default=None)
    args = ap.parse_args()

    from footstats.data.historical_loader import load_cached

    df = load_cached()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "hg", "ag"])

    print("Licze ratingi w konfiguracji PRODUKCYJNEJ...", flush=True)
    zb = zbierz(df, (PROD["okno"],), (PROD["polowicz"],))
    d = _sklej(zb["zestawy"][(PROD["okno"], PROD["polowicz"])], zb["meta"], KLUCZE)
    lg_m, la_m = lambdy(d, PROD["k"], PROD["skala_g"], PROD["skala_a"])

    p_ryn = devig(d["odds_h_pinn"], d["odds_d_pinn"], d["odds_a_pinn"])
    ok = maska_uzywalnych(d) & np.isfinite(p_ryn).all(axis=1)
    print(f"Meczow z ratingami i zamknieciem Pinnacle: {int(ok.sum())}", flush=True)

    print("Odzyskuje lambda RYNKU przy rho=0...", flush=True)
    lg_r, la_r, zb_ok = odzyskaj_lambdy(p_ryn[ok, 0], p_ryn[ok, 2])
    print(f"  zbieglo: {zb_ok.mean():.4%}", flush=True)

    idx = np.flatnonzero(ok)[zb_ok]
    hg, ag = d["hg"][idx], d["ag"][idx]
    lg_m_s, la_m_s = lg_m[idx], la_m[idx]
    lg_r_s, la_r_s = lg_r[zb_ok], la_r[zb_ok]

    kreska = "=" * 88
    print(f"\n{kreska}\n  POMIAR A — czyje lambda lepiej przewiduje gole\n{kreska}")
    ll_m = logwiar_goli(lg_m_s, la_m_s, hg, ag)
    ll_r = logwiar_goli(lg_r_s, la_r_s, hg, ag)
    sr, se, z = sparowana(ll_m - ll_r)
    print(f"  n = {len(idx)}")
    print(f"  srednia log-wiarygodnosc:  model {ll_m.mean():.5f}   rynek {ll_r.mean():.5f}")
    print(f"  sparowana roznica (model - rynek) {sr:+.5f}  SE {se:.5f}  z={z:+.2f}")
    print("\n  DLA POROWNANIA, pomiar z 04.09 na zlej macierzy:"
          "  -0.09404  SE 0.00398  z=-23.65")

    print(f"\n{kreska}\n  POMIAR B — poziomy\n{kreska}")
    print(f"  faktyczne gole   {hg.mean():.4f} / {ag.mean():.4f}")
    print(f"  lambda modelu    {lg_m_s.mean():.4f} / {la_m_s.mean():.4f}"
          f"   blad {lg_m_s.mean() - hg.mean():+.4f} / {la_m_s.mean() - ag.mean():+.4f}")
    print(f"  lambda rynku     {lg_r_s.mean():.4f} / {la_r_s.mean():.4f}"
          f"   blad {lg_r_s.mean() - hg.mean():+.4f} / {la_r_s.mean() - ag.mean():+.4f}")
    print(f"  srednia |roznica| miedzy nami a rynkiem:"
          f"  gospodarz {np.abs(lg_m_s - lg_r_s).mean():.4f}"
          f"  gosc {np.abs(la_m_s - la_r_s).mean():.4f}")

    print(f"\n{kreska}\n  POMIAR C — czy Poisson (rho=0) miesci Over 2.5 rynku\n{kreska}")
    wynik_c = None
    if all(k in d for k in KOL_OVER):
        o_over, o_under = d["odds_over25_pinn"][idx], d["odds_under25_pinn"][idx]
        ma = np.isfinite(o_over) & np.isfinite(o_under) & (o_over > 1.0) & (o_under > 1.0)
        if ma.sum() > 100:
            inv_o, inv_u = 1.0 / o_over[ma], 1.0 / o_under[ma]
            p_over_ryn = inv_o / (inv_o + inv_u)
            p_over_poi = over25_z_lambd(lg_r_s[ma], la_r_s[ma])
            obc = float((p_over_poi - p_over_ryn).mean())
            wynik_c = {"n": int(ma.sum()), "rynek": float(p_over_ryn.mean()),
                       "z_poissona": float(p_over_poi.mean()), "obciazenie": obc,
                       "sr_abs": float(np.abs(p_over_poi - p_over_ryn).mean())}
            print(f"  n={wynik_c['n']}   rynek {wynik_c['rynek']:.4f}"
                  f"   z Poissona {wynik_c['z_poissona']:.4f}")
            print(f"  obciazenie {obc:+.4f}   srednie |odchylenie| {wynik_c['sr_abs']:.4f}")
            print("  Dla porownania, ta sama liczba przy rho=-0.05 (04.09): -0.0326")
        else:
            print("  Za malo meczow z kursami Over/Under — pomiar pominiety.")
    else:
        print("  Brak kolumn Over/Under w zbiorze — pomiar pominiety.")

    print(f"\n{kreska}\n  ROZBICIE PO LIGACH (n >= 300)\n{kreska}")
    ligi = d["league"][idx]
    per_liga = []
    ujemne = wszystkie = 0
    for liga in sorted(set(ligi)):
        m = ligi == liga
        if m.sum() < 300:
            continue
        s_l, _, z_l = sparowana((ll_m - ll_r)[m])
        wszystkie += 1
        ujemne += int(s_l < 0)
        per_liga.append({"liga": liga, "n": int(m.sum()), "d": s_l, "z": z_l})
        print(f"  {liga:28s} n={int(m.sum()):6d}   {s_l:+.5f}  z={z_l:+6.1f}")
    print(f"\n  Lig, w ktorych rynek ma lepsze lambda: {ujemne}/{wszystkie}")

    print(f"\n{kreska}\n  REGULA DECYZYJNA (zamrozona przed przebiegiem)\n{kreska}")
    if z <= -3:
        print(f"  z={z:+.2f} <= -3  ->  rynek ma lepsze oczekiwania bramkowe.")
        print("  Teza o waskim gardle w RATINGACH stoi mimo bledu wczorajszego narzedzia.")
    elif z >= 3:
        print(f"  z={z:+.2f} >= +3  ->  to NASZE lambda jest lepsze.")
        print("  Wczorajszy wynik byl ODWROCONY przez macierz. Wymaga osobnego")
        print("  wyjasnienia, skad przy lepszych lambdach przegrana w Brierze 1X2.")
    else:
        print(f"  |z|={abs(z):.2f} < 3  ->  roznica NIE PRZEZYLA poprawki narzedzia.")
        print("  Wniosek z 04.09 byl artefaktem macierzy — wycofac w calosci.")

    if args.wynik:
        Path(args.wynik).write_text(json.dumps({
            "n": len(idx),
            "pomiar_A": {"ll_model": float(ll_m.mean()), "ll_rynek": float(ll_r.mean()),
                         "d": sr, "se": se, "z": z},
            "pomiar_B": {"hg": float(hg.mean()), "ag": float(ag.mean()),
                         "lambda_model": [float(lg_m_s.mean()), float(la_m_s.mean())],
                         "lambda_rynek": [float(lg_r_s.mean()), float(la_r_s.mean())]},
            "pomiar_C": wynik_c,
            "per_liga": per_liga,
            "ligi_rynek_lepszy": ujemne, "ligi_all": wszystkie,
            "odniesienie_04_09": {"d": -0.09404, "se": 0.00398, "z": -23.65},
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nZapisane: {args.wynik}")


if __name__ == "__main__":
    main()

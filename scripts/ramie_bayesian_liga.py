#!/usr/bin/env python
"""ramie_bayesian_liga.py — czy ramię bayesian ma liczyć siłę WOBEC WŁASNEJ LIGI.

===========================  PRE-REJESTRACJA  ===============================
Spisana 2026-09-06, PRZED policzeniem czegokolwiek.

OSTATNIA DUŻA DZIURA W TYM RAMIENIU. Po naprawie pięciu stałych (commit
42e3e50dc) λ ramienia wynosi 1.4943 / 1.1933 przy faktycznych 1.5087 / 1.2146,
czyli jednostki się zgadzają. Zostaje coś, czego naprawa jednostek nie ruszyła:

    `poisson_bayesian` NIGDY nie filtruje ligi.

`_league_averages(df)` liczy średnią goli z CAŁEJ przekazanej ramki, a
`quick_picks` przekazuje pełną historię — 40 lig naraz. `_compute_ratings`
tak samo: bierze wszystkie mecze drużyny z tej ramki, bez oglądania się na
rozgrywki. Siła napastnika Premier League jest więc mierzona wobec średniej
wspólnej z MLS, Ekstraklasą i chińską Super League.

DLACZEGO SPODZIEWAM SIĘ, ŻE TO DUŻO. Dokładnie tę samą poprawkę zrobiono kiedyś
po stronie ramienia classic i jest zmierzona — `form.sily_ligowe` liczy siłę
WOBEC LIGI właśnie z tego powodu, a jej docstring podaje:

    Brier 0.6557 -> 0.6089   (4 ligi top)
    Brier 0.6639 -> 0.6142   (6 innych lig)

To był największy pojedynczy skok w historii tego modelu. Ramię bayesian tej
poprawki nadal nie ma. Nie znaczy to, że da tyle samo — classic dostał ją
razem z rozdzieleniem dom/wyjazd, którego bayesian już używa, a poza tym
ramię wchodzi do blendu z wagą 0.49, nie 1.0. Ale rząd wielkości jest inny
niż wszystko, co mierzyłem w tej serii.

DWIE RZECZY ZMIENIAJĄ SIĘ NARAZ I TO JEST ŚWIADOME. Filtrowanie ligi dotyka
jednocześnie średnich ligowych i zbioru meczów drużyny — nie da się ich
rozdzielić, bo to jedna operacja: „licz tę drużynę w rozgrywkach, w których
gra". Rozbijanie tego na dwa ramiona dałoby konfigurację, której nikt nigdy
nie wdroży (średnie z jednej ligi, mecze z czterdziestu).

CZEGO NADAL NIE RUSZAMY: braku okna (cała historia od 2012, waga 3x tylko dla
ostatnich pięciu meczów) ani obcięcia macierzy na 8 komórkach. Osobne pomiary.

RAMIONA:
  A. OBECNA PRODUKCJA — ramię naprawione, bez filtra ligi, waga 0.49.
  B. Z FILTREM LIGI — średnie ligowe i mecze drużyny liczone WYŁĄCZNIE
     w lidze rozgrywanego meczu; waga dopasowana od nowa na treningu.

PRÓG WEJŚCIA. Drużyna, która w swojej lidze ma mniej niż `MIN_MECZOW_LIGA=4`
meczów na danej stronie boiska, nie ma z czego liczyć ratingu. Produkcja
w takim wypadku i tak dostaje coś z globalnej próbki, więc żeby porównanie
było uczciwe, mecz wypada z pomiaru w OBU ramionach. Liczba odrzuconych
raportowana — jeśli filtr wycina dużo, to jest realny koszt tej zmiany
i musi być widoczny.

POMIARY:
  0. λ obu ramion kontra faktyczne gole (opisowo).
  1. Waga ramienia z filtrem, dopasowana na TRENINGU (<2024-01-01).
  2. Sparowany Brier 1X2 na holdoucie: produkcja kontra filtr ligi.

REGUŁA DECYZYJNA, ZAMROŻONA — te same dwa progi co od 05.09:
  1. ISTOTNOŚĆ: sparowana różnica Briera na holdoucie z >= +3;
  2. ROZMIAR: ta sama różnica PO ROZCIEŃCZENIU ceną przy wadze rynku 0.70
     >= **0.0005** Briera;
  3. REPLIKACJA: >= 2/3 lig z n >= 300 w tę samą stronę.
Wszystkie trzy — inaczej produkcja bez zmian.

TYM RAZEM BEZ FURTKI. Poprzednia pre-rejestracja miała klauzulę „naprawię
niezależnie od wyniku", bo tam chodziło o błąd jednostek. Tutaj chodzi
o wybór projektowy: liczyć wobec ligi czy wobec wszystkiego. Jeśli reguła
odrzuci, kod zostaje jak jest, i nie będę tego obchodził.

CZEGO TO NIE ZMIENIA. Model dalej przegrywa z ceną w 39 ligach na 39.
=============================================================================

    python scripts/ramie_bayesian_liga.py --holdout 2024-01-01
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

from estymator_lambda import (  # noqa: E402
    KLUCZE, PROD, _sklej, brier_z_p, devig, lambdy, maska_uzywalnych,
    sparowana, zbierz,
)
from ksztalt_dc import pmf_obciete, wyjscia_dc  # noqa: E402
from ramie_bayesian import (  # noqa: E402
    MIN_LIGA, MIN_ROZMIAR, blenduj, p1x2_bayes, ratingi_bayes,
)
from ramie_bayesian_naprawa import lambdy_bayes_naprawione  # noqa: E402

MIN_MECZOW_LIGA = 4


def ratingi_bayes_ligowe(df: pd.DataFrame) -> tuple[dict, np.ndarray]:
    """Ratingi ramienia bayesian liczone OSOBNO W KAŻDEJ LIDZE.

    Zwraca `(ratingi, dosc_meczow)`. Druga wartość mówi, dla których wierszy
    obie drużyny mają w swojej lidze przynajmniej `MIN_MECZOW_LIGA` meczów na
    właściwej stronie boiska — poniżej tego rating jest szumem udającym wiedzę.

    Ta sama arytmetyka co `ratingi_bayes`, tylko puszczona per liga i sklejona
    z powrotem po pozycji w ramce wejściowej. Dzięki temu jedyną różnicą między
    ramionami jest ZAKRES danych, a nie sposób liczenia.
    """
    n = len(df)
    puste = np.full(n, np.nan)
    out = {k: puste.copy() for k in
           ("liga_dom", "liga_wyj", "att_dom", "def_dom", "n_dom",
            "att_wyj", "def_wyj", "n_wyj")}
    dosc = np.zeros(n, dtype=bool)

    for _, gl in df.groupby("league", sort=False):
        gl = gl.sort_values("date", kind="stable")
        poz = gl.index.to_numpy()
        if len(gl) < 20:
            continue
        r = ratingi_bayes(gl.reset_index(drop=True))
        for k in out:
            out[k][poz] = r[k]
        dosc[poz] = (r["n_dom"] >= MIN_MECZOW_LIGA) & (r["n_wyj"] >= MIN_MECZOW_LIGA)
    return out, dosc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--holdout", default="2024-01-01")
    ap.add_argument("--wynik", default=None)
    args = ap.parse_args()

    from footstats.config import DC_RHO_CLASSIC, W_BAYESIAN
    from footstats.data.historical_loader import load_cached

    df = load_cached()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "hg", "ag"]).sort_values(
        "date", kind="stable").reset_index(drop=True)
    df["idx"] = np.arange(len(df), dtype=float)

    print("Ramie bayesian GLOBALNE (jak produkcja)...", flush=True)
    lg_g, la_g = lambdy_bayes_naprawione(ratingi_bayes(df))

    print("Ramie bayesian PER LIGA...", flush=True)
    r_lig, dosc = ratingi_bayes_ligowe(df)
    lg_l, la_l = lambdy_bayes_naprawione(r_lig)
    print(f"  wierszy z kompletem ratingow ligowych: {int(dosc.sum())} "
          f"z {len(df)} ({dosc.mean():.1%})")

    print("Ramie classic (konfiguracja produkcyjna)...", flush=True)
    zb = zbierz(df, (PROD["okno"],), (PROD["polowicz"],))
    d = _sklej(zb["zestawy"][(PROD["okno"], PROD["polowicz"])], zb["meta"], KLUCZE)
    lgc, lac = lambdy(d, PROD["k"], PROD["skala_g"], PROD["skala_a"])
    p_classic = wyjscia_dc(pmf_obciete(lgc), pmf_obciete(lac),
                           lgc, lac, DC_RHO_CLASSIC)["p1x2"]

    kot = d["idx"].astype(int)
    p_glob = p1x2_bayes(lg_g[kot], la_g[kot])
    p_lig = p1x2_bayes(lg_l[kot], la_l[kot])

    ok = (maska_uzywalnych(d) & dosc[kot]
          & np.isfinite(p_glob).all(axis=1) & np.isfinite(p_lig).all(axis=1))
    granica = pd.Timestamp(args.holdout)
    tren, hold = ok & (d["date"] < granica), ok & (d["date"] >= granica)
    y = d["wynik"]
    odrzucone = int((maska_uzywalnych(d) & ~dosc[kot]).sum())
    print(f"Uzywalnych: {int(ok.sum())}  (trening {int(tren.sum())}, "
          f"holdout {int(hold.sum())});  odrzuconych przez prog ligowy: {odrzucone}")

    kreska = "=" * 88
    print(f"\n{kreska}\n  POMIAR 0 — lambda obu ramion (opisowo)\n{kreska}")
    print(f"  faktyczne          {d['hg'][hold].mean():.4f} / {d['ag'][hold].mean():.4f}")
    print(f"  classic            {lgc[hold].mean():.4f} / {lac[hold].mean():.4f}")
    print(f"  bayesian GLOBALNE  {lg_g[kot][hold].mean():.4f} / "
          f"{la_g[kot][hold].mean():.4f}")
    print(f"  bayesian PER LIGA  {lg_l[kot][hold].mean():.4f} / "
          f"{la_l[kot][hold].mean():.4f}")
    print("\n  rozrzut lambda gospodarza (odchylenie std) — miara ROZDZIELCZOSCI:")
    print(f"    globalne {lg_g[kot][hold].std():.4f}   per liga {lg_l[kot][hold].std():.4f}")

    print(f"\n{kreska}\n  POMIAR 1 — waga ramienia PER LIGA\n{kreska}")
    siatka = []
    for w in np.round(np.arange(0.0, 1.01, 0.1), 2):
        bt = brier_z_p(blenduj(p_classic[tren], p_lig[tren], w), y[tren]).mean()
        bh = brier_z_p(blenduj(p_classic[hold], p_lig[hold], w), y[hold]).mean()
        siatka.append({"w": float(w), "trening": float(bt), "holdout": float(bh)})
        print(f"  w={w:.2f}   trening {bt:.5f}   holdout {bh:.5f}")
    gesta = np.linspace(0.0, 1.0, 101)
    w_opt = float(min(gesta, key=lambda w: brier_z_p(
        blenduj(p_classic[tren], p_lig[tren], w), y[tren]).mean()))
    print(f"\n  waga dopasowana na TRENINGU: {w_opt:.3f}  (produkcja {W_BAYESIAN})")

    print(f"\n{kreska}\n  POMIAR 2 — produkcja kontra filtr ligi\n{kreska}")
    b_prod = brier_z_p(blenduj(p_classic[hold], p_glob[hold], W_BAYESIAN), y[hold])
    b_lig = brier_z_p(blenduj(p_classic[hold], p_lig[hold], w_opt), y[hold])
    s1, se1, z1 = sparowana(b_prod - b_lig)
    print(f"  produkcja {b_prod.mean():.5f}   per liga {b_lig.mean():.5f}")
    print(f"  sparowana roznica {s1:+.5f}  SE {se1:.5f}  z={z1:+.2f}")

    print(f"\n{kreska}\n  ROZMIAR PO ROZCIENCZENIU CENA\n{kreska}")
    p_ryn = devig(d["odds_h_pinn"], d["odds_d_pinn"], d["odds_a_pinn"])
    mix = hold & np.isfinite(p_ryn).all(axis=1)
    print(f"  Meczow z zamknieciem Pinnacle: {int(mix.sum())} z {int(hold.sum())}")
    pp_ = blenduj(p_classic[mix], p_glob[mix], W_BAYESIAN)
    pl_ = blenduj(p_classic[mix], p_lig[mix], w_opt)
    rozm = {}
    for w_r in (0.0, 0.30, 0.70, 1.0):
        bp = brier_z_p((1 - w_r) * pp_ + w_r * p_ryn[mix], y[mix])
        bl = brier_z_p((1 - w_r) * pl_ + w_r * p_ryn[mix], y[mix])
        sw, sew, zw = sparowana(bp - bl)
        rozm[w_r] = {"d": sw, "se": sew, "z": zw}
        print(f"  waga rynku {w_r:.2f}   produkcja {bp.mean():.5f}   "
              f"per liga {bl.mean():.5f}   roznica {sw:+.5f}  z={zw:+.2f}")

    print(f"\n{kreska}\n  REPLIKACJA PO LIGACH (holdout, n >= {MIN_LIGA})\n{kreska}")
    plus = wszystkie = 0
    per_liga = []
    for liga in sorted(set(d["league"][hold])):
        m = hold & (d["league"] == liga)
        if m.sum() < MIN_LIGA:
            continue
        sl, _, zl = sparowana(
            brier_z_p(blenduj(p_classic[m], p_glob[m], W_BAYESIAN), y[m])
            - brier_z_p(blenduj(p_classic[m], p_lig[m], w_opt), y[m]))
        wszystkie += 1
        plus += int(sl > 0)
        per_liga.append({"liga": liga, "n": int(m.sum()), "d": sl, "z": zl})
        print(f"  {liga:28s} n={int(m.sum()):5d}   {sl:+.5f}  z={zl:+5.1f}")
    print(f"\n  Lig na korzysc filtra: {plus}/{wszystkie}"
          f"  (prog: {int(np.ceil(2 * wszystkie / 3))})")

    print(f"\n{kreska}\n  REGULA DECYZYJNA (zamrozona, bez furtki)\n{kreska}")
    d70 = rozm[0.70]["d"]
    r1 = np.isfinite(z1) and z1 >= 3.0
    r2 = np.isfinite(d70) and d70 >= MIN_ROZMIAR
    r3 = wszystkie > 0 and plus >= np.ceil(2 * wszystkie / 3)
    print(f"  1. istotnosc  z >= +3            : {'TAK' if r1 else 'NIE'}  (z={z1:+.2f})")
    print(f"  2. rozmiar przy w=0.70 >= {MIN_ROZMIAR}  : "
          f"{'TAK' if r2 else 'NIE'}  ({d70:+.5f})")
    print(f"  3. >= 2/3 lig                    : {'TAK' if r3 else 'NIE'}  "
          f"({plus}/{wszystkie})")
    if r1 and r2 and r3:
        print(f"\n  WNIOSEK: liczyc ramie bayesian PER LIGA, waga {w_opt:.3f}.")
    else:
        print("\n  WNIOSEK: warunki NIE spelnione — kod bez zmian. Bez furtki.")

    if args.wynik:
        Path(args.wynik).write_text(json.dumps({
            "holdout": args.holdout, "n_holdout": int(hold.sum()),
            "odrzucone_prog_ligowy": odrzucone,
            "w_opt": w_opt, "w_prod": float(W_BAYESIAN), "siatka": siatka,
            "lambda": {"fakt": [float(d["hg"][hold].mean()), float(d["ag"][hold].mean())],
                       "globalne": [float(lg_g[kot][hold].mean()),
                                    float(la_g[kot][hold].mean())],
                       "per_liga": [float(lg_l[kot][hold].mean()),
                                    float(la_l[kot][hold].mean())],
                       "std_globalne": float(lg_g[kot][hold].std()),
                       "std_per_liga": float(lg_l[kot][hold].std())},
            "brier_prod": float(b_prod.mean()), "brier_lig": float(b_lig.mean()),
            "d": s1, "se": se1, "z": z1,
            "rozmiar": {str(k): v for k, v in rozm.items()},
            "per_liga_tabela": per_liga, "ligi_plus": plus, "ligi_all": wszystkie,
            "regula": {"r1": bool(r1), "r2": bool(r2), "r3": bool(r3)},
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nZapisane: {args.wynik}")


if __name__ == "__main__":
    main()

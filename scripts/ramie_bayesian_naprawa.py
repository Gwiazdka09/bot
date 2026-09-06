#!/usr/bin/env python
"""ramie_bayesian_naprawa.py — czy naprawa pięciu stałych ratuje ramię bayesian.

===========================  PRE-REJESTRACJA  ===============================
Spisana 2026-09-06, PRZED policzeniem czegokolwiek.

CO JUŻ WIEMY (`ramie_bayesian.py`, commit 0ff676fd1). Ramię blendowane dotąd
w 50% ma λ **2.1585 / 0.9515** przy faktycznych 1.5087 / 1.2146. Waga zeszła
z 0.5 na 0.13 i to dało +0.00134 Briera po rozcieńczeniu ceną — ale to jest
obejście, nie naprawa. Ramię dalej liczy bzdurne λ, tylko mniej znaczy.

BŁĄD JEST DIMENSIONALNY I DA SIĘ GO POKAZAĆ BEZ ŻADNEGO MODELU.
W `poisson_bayesian.predict_match_bayesian`:

  * `away_away["def"]` to gole, które gość TRACI NA WYJEŹDZIE — czyli gole
    GOSPODARZY. Kod ściąga tę wielkość do `league_away` i dzieli przez
    `league_away`. Obie powinny być `league_home`;
  * `home_home["def"]` to gole, które gospodarz TRACI U SIEBIE — czyli gole
    GOŚCI. Kod ściąga do `league_home` i dzieli przez `league_home`. Obie
    powinny być `league_away`;
  * `BONUS_DOMOWY = 1.15` mnoży λ gospodarza, choć `home_att` jest już liczone
    ze średniej goli GOSPODARZY, która atut własnego boiska zawiera. Atut jest
    więc policzony dwa razy. Dokładnie ten sam błąd jest jawnie opisany
    i naprawiony w docstringu `form.sily_ligowe` — po drugiej stronie kodu.

Odtworzone na samych średnich (lig_dom 1.4883, lig_wyj 1.1790):

    kod produkcyjny              2.1197 / 0.9563   (zmierzone 2.1585 / 0.9515)
    prior po właściwej stronie   1.4883 / 1.1790
    faktyczne                    1.5087 / 1.2146

PIĘĆ ZMIAN, wszystkie w jednej funkcji:

    away_def  prior  league_away -> league_home
    home_def  prior  league_home -> league_away
    lambda_h  mianownik  league_away -> league_home
    lambda_a  mianownik  league_home -> league_away
    home_advantage  1.15 -> 1.0

CZEGO NIE RUSZAMY W TYM POMIARZE, choć jest zepsute:
  * ramię nie filtruje ligi — `_league_averages` liczy średnią z 40 lig naraz;
  * nie ma żadnego okna — cała historia od 2012, waga 3x tylko dla ostatnich 5;
  * jego macierz obcina na 8 komórkach, główna ścieżka na 9.
To są trzy osobne zmiany projektowe. Mieszanie ich z naprawą jednostek
zamazałoby, co właściwie zadziałało.

POMIAR:
  0. λ ramienia naprawionego kontra faktyczne gole (opisowo). Jeśli po naprawie
     λ dalej odjeżdża, to znaczy, że diagnoza była niepełna i trzeba wrócić.
  1. Waga ramienia naprawionego dopasowana na TRENINGU (<2024-01-01),
     siatka {0, 0.1, ..., 1.0} plus dopasowanie ciągłe. Ocena na holdoucie.
  2. Sparowany Brier 1X2 na holdoucie: OBECNA PRODUKCJA (ramię zepsute, w=0.13)
     kontra ramię naprawione przy wadze dopasowanej.

REGUŁA DECYZYJNA, ZAMROŻONA — dwa progi, jak od 05.09:
  1. ISTOTNOŚĆ: sparowana różnica Briera na holdoucie z >= +3;
  2. ROZMIAR: ta sama różnica PO ROZCIEŃCZENIU ceną przy wadze rynku 0.70
     >= **0.0005** Briera;
  3. REPLIKACJA: >= 2/3 lig z n >= 300 w tę samą stronę.
Wszystkie trzy — inaczej produkcja bez zmian, a wynik zostaje pomiarem.

CO ZROBIĘ NIEZALEŻNIE OD WYNIKU. Pięć stałych po złej stronie boiska to błąd
jednostek, nie wybór projektowy, i zostanie naprawione tak czy inaczej —
kod, który dzieli gole gospodarzy przez średnią goli gości, jest po prostu zły.
Ten pomiar rozstrzyga wyłącznie, JAKĄ WAGĘ dostanie naprawione ramię i czy
w ogóle warto je trzymać. Gdyby naprawa nie pomogła, właściwym wnioskiem jest
`USE_DIXON_COLES=0`, a nie zostawienie błędu.

CZEGO TO NIE ZMIENIA. Model dalej przegrywa z ceną w 39 ligach na 39.
=============================================================================

    python scripts/ramie_bayesian_naprawa.py --holdout 2024-01-01
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
    MIN_LIGA, MIN_ROZMIAR, _sciagnij, blenduj, lambdy_bayes, p1x2_bayes,
    ratingi_bayes,
)

W_ZEPSUTE_PROD = 0.13       # to, co gra od commita 0ff676fd1


def lambdy_bayes_naprawione(r: dict) -> tuple[np.ndarray, np.ndarray]:
    """λ ramienia bayesian po naprawie pięciu stałych.

    Różnice wobec `lambdy_bayes` — wszystkie wynikają z tego, po której stronie
    boiska padły gole, a nie z żadnego wyboru modelowego:

      * obrona gościa NA WYJEŹDZIE to gole gospodarzy → prior i mianownik
        `liga_dom`, nie `liga_wyj`;
      * obrona gospodarza U SIEBIE to gole gości → prior i mianownik `liga_wyj`;
      * brak `BONUS_DOMOWY` — `att_dom` jest liczone ze średniej goli
        gospodarzy, która atut własnego boiska już zawiera.

    Sprawdzian, który to weryfikuje bez danych: gdy wszystkie ratingi są równe
    swoim średnim ligowym, λ musi wyjść dokładnie (liga_dom, liga_wyj).
    """
    lig_d, lig_w = r["liga_dom"], r["liga_wyj"]
    att_g = _sciagnij(r["att_dom"], r["n_dom"], lig_d)
    def_a = _sciagnij(r["def_wyj"], r["n_wyj"], lig_d)   # gole GOSPODARZY
    att_a = _sciagnij(r["att_wyj"], r["n_wyj"], lig_w)
    def_g = _sciagnij(r["def_dom"], r["n_dom"], lig_w)   # gole GOSCI
    lg = np.maximum(0.05, att_g * (def_a / lig_d))
    la = np.maximum(0.05, att_a * (def_g / lig_w))
    return lg, la


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--holdout", default="2024-01-01")
    ap.add_argument("--wynik", default=None)
    args = ap.parse_args()

    from footstats.config import DC_RHO_CLASSIC
    from footstats.data.historical_loader import load_cached

    df = load_cached()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "hg", "ag"]).sort_values(
        "date", kind="stable").reset_index(drop=True)
    df["idx"] = np.arange(len(df), dtype=float)

    print("Ratingi ramienia bayesian...", flush=True)
    rb = ratingi_bayes(df)
    lg_z, la_z = lambdy_bayes(rb)                 # zepsute, jak na produkcji
    lg_n, la_n = lambdy_bayes_naprawione(rb)      # po naprawie pieciu stalych

    print("Ramie classic (konfiguracja produkcyjna)...", flush=True)
    zb = zbierz(df, (PROD["okno"],), (PROD["polowicz"],))
    d = _sklej(zb["zestawy"][(PROD["okno"], PROD["polowicz"])], zb["meta"], KLUCZE)
    lgc, lac = lambdy(d, PROD["k"], PROD["skala_g"], PROD["skala_a"])
    p_classic = wyjscia_dc(pmf_obciete(lgc), pmf_obciete(lac),
                           lgc, lac, DC_RHO_CLASSIC)["p1x2"]

    kot = d["idx"].astype(int)
    p_zep = p1x2_bayes(lg_z[kot], la_z[kot])
    p_nap = p1x2_bayes(lg_n[kot], la_n[kot])

    ok = maska_uzywalnych(d) & np.isfinite(p_zep).all(axis=1) \
        & np.isfinite(p_nap).all(axis=1)
    granica = pd.Timestamp(args.holdout)
    tren, hold = ok & (d["date"] < granica), ok & (d["date"] >= granica)
    y = d["wynik"]
    print(f"Uzywalnych: {int(ok.sum())}  (trening {int(tren.sum())}, "
          f"holdout {int(hold.sum())})")

    kreska = "=" * 88
    print(f"\n{kreska}\n  POMIAR 0 — lambda po naprawie (opisowo)\n{kreska}")
    print(f"  faktyczne          {d['hg'][hold].mean():.4f} / {d['ag'][hold].mean():.4f}")
    print(f"  classic            {lgc[hold].mean():.4f} / {lac[hold].mean():.4f}")
    print(f"  bayesian ZEPSUTE   {lg_z[kot][hold].mean():.4f} / "
          f"{la_z[kot][hold].mean():.4f}")
    print(f"  bayesian NAPRAWIONE{lg_n[kot][hold].mean():.4f} / "
          f"{la_n[kot][hold].mean():.4f}")

    print(f"\n{kreska}\n  POMIAR 1 — waga ramienia NAPRAWIONEGO\n{kreska}")
    siatka = []
    for w in np.round(np.arange(0.0, 1.01, 0.1), 2):
        bt = brier_z_p(blenduj(p_classic[tren], p_nap[tren], w), y[tren]).mean()
        bh = brier_z_p(blenduj(p_classic[hold], p_nap[hold], w), y[hold]).mean()
        siatka.append({"w": float(w), "trening": float(bt), "holdout": float(bh)})
        print(f"  w={w:.2f}   trening {bt:.5f}   holdout {bh:.5f}")
    gesta = np.linspace(0.0, 1.0, 101)
    w_opt = float(min(gesta, key=lambda w: brier_z_p(
        blenduj(p_classic[tren], p_nap[tren], w), y[tren]).mean()))
    print(f"\n  waga dopasowana na TRENINGU: {w_opt:.3f}")

    print(f"\n{kreska}\n  POMIAR 2 — produkcja (zepsute, w=0.13) kontra naprawione\n{kreska}")
    b_prod = brier_z_p(blenduj(p_classic[hold], p_zep[hold], W_ZEPSUTE_PROD), y[hold])
    b_nowe = brier_z_p(blenduj(p_classic[hold], p_nap[hold], w_opt), y[hold])
    s1, se1, z1 = sparowana(b_prod - b_nowe)
    print(f"  produkcja {b_prod.mean():.5f}   naprawione {b_nowe.mean():.5f}")
    print(f"  sparowana roznica {s1:+.5f}  SE {se1:.5f}  z={z1:+.2f}")

    print(f"\n{kreska}\n  ROZMIAR PO ROZCIENCZENIU CENA\n{kreska}")
    p_ryn = devig(d["odds_h_pinn"], d["odds_d_pinn"], d["odds_a_pinn"])
    mix = hold & np.isfinite(p_ryn).all(axis=1)
    print(f"  Meczow z zamknieciem Pinnacle: {int(mix.sum())} z {int(hold.sum())}")
    pp_ = blenduj(p_classic[mix], p_zep[mix], W_ZEPSUTE_PROD)
    pn_ = blenduj(p_classic[mix], p_nap[mix], w_opt)
    rozm = {}
    for w_r in (0.0, 0.30, 0.70, 1.0):
        bp = brier_z_p((1 - w_r) * pp_ + w_r * p_ryn[mix], y[mix])
        bn = brier_z_p((1 - w_r) * pn_ + w_r * p_ryn[mix], y[mix])
        sw, sew, zw = sparowana(bp - bn)
        rozm[w_r] = {"d": sw, "se": sew, "z": zw}
        print(f"  waga rynku {w_r:.2f}   produkcja {bp.mean():.5f}   "
              f"naprawione {bn.mean():.5f}   roznica {sw:+.5f}  z={zw:+.2f}")

    print(f"\n{kreska}\n  REPLIKACJA PO LIGACH (holdout, n >= {MIN_LIGA})\n{kreska}")
    plus = wszystkie = 0
    per_liga = []
    for liga in sorted(set(d["league"][hold])):
        m = hold & (d["league"] == liga)
        if m.sum() < MIN_LIGA:
            continue
        sl, _, zl = sparowana(
            brier_z_p(blenduj(p_classic[m], p_zep[m], W_ZEPSUTE_PROD), y[m])
            - brier_z_p(blenduj(p_classic[m], p_nap[m], w_opt), y[m]))
        wszystkie += 1
        plus += int(sl > 0)
        per_liga.append({"liga": liga, "n": int(m.sum()), "d": sl, "z": zl})
        print(f"  {liga:28s} n={int(m.sum()):5d}   {sl:+.5f}  z={zl:+5.1f}")
    print(f"\n  Lig na korzysc naprawy: {plus}/{wszystkie}"
          f"  (prog: {int(np.ceil(2 * wszystkie / 3))})")

    print(f"\n{kreska}\n  REGULA DECYZYJNA (zamrozona, DWA progi)\n{kreska}")
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
        print(f"\n  WNIOSEK: naprawic piec stalych i ustawic W_BAYESIAN = {w_opt:.3f}.")
    else:
        print("\n  WNIOSEK: naprawa NIE daje mierzalnego zysku ponad obejscie."
              "\n  Stale i tak naprawiamy (blad jednostek), ale wage zostawiamy"
              f"\n  na {W_ZEPSUTE_PROD} albo rozwazamy USE_DIXON_COLES=0.")

    if args.wynik:
        Path(args.wynik).write_text(json.dumps({
            "holdout": args.holdout, "n_holdout": int(hold.sum()),
            "w_opt": w_opt, "siatka": siatka,
            "lambda": {"fakt": [float(d["hg"][hold].mean()), float(d["ag"][hold].mean())],
                       "zepsute": [float(lg_z[kot][hold].mean()),
                                   float(la_z[kot][hold].mean())],
                       "naprawione": [float(lg_n[kot][hold].mean()),
                                      float(la_n[kot][hold].mean())]},
            "brier_prod": float(b_prod.mean()), "brier_nowe": float(b_nowe.mean()),
            "d": s1, "se": se1, "z": z1,
            "rozmiar": {str(k): v for k, v in rozm.items()},
            "per_liga": per_liga, "ligi_plus": plus, "ligi_all": wszystkie,
            "regula": {"r1": bool(r1), "r2": bool(r2), "r3": bool(r3)},
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nZapisane: {args.wynik}")


if __name__ == "__main__":
    main()

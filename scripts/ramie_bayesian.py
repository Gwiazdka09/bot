#!/usr/bin/env python
"""ramie_bayesian.py — czy ramię „Dixon-Coles" w ogóle pomaga, i przy jakiej wadze.

===========================  PRE-REJESTRACJA  ===============================
Spisana 2026-09-06, PRZED policzeniem czegokolwiek.

CO TU SIEDZI. `quick_picks` liczy 1X2 jako blend pół na pół:

    p = 0.5 * predict_match (classic)  +  0.5 * predict_match_bayesian

pod flagą `USE_DIXON_COLES` (domyślnie 1) i z wagą `W_BAYESIAN=0.5`. Waga jest
wpisana z ręki i nigdy nie była dopasowana. To jest połowa naszej prognozy 1X2.

DLACZEGO PODEJRZEWAM, ŻE TO RAMIĘ SZKODZI — i to na podstawie kodu, nie przeczuć:

  * `poisson_bayesian` NIGDY nie filtruje ligi. `_league_averages` liczy średnią
    goli z CAŁEJ przekazanej ramki, a `quick_picks` przekazuje pełną historię —
    40 lig naraz. Siła napastnika Premier League jest więc mierzona wobec
    średniej wspólnej dla Ekstraklasy, MLS i chińskiej Super League;
  * `_compute_ratings` nie ma ŻADNEGO okna. Bierze wszystkie mecze drużyny na
    danej stronie boiska, od 2012 roku, z wagą 3x tylko dla ostatnich pięciu;
  * jego macierz obcina na `arange(MAX_GOLE)` = 8 komórek, podczas gdy główna
    ścieżka woła `_macierz(..., MAX_GOLE + 1)` = 9. Różnica sięga 2.6e-3 w p(1);
  * przy `USE_DC_TAU=0` liczy `rho=0`, więc „ramię Dixona-Colesa" nie zawiera
    korekty Dixona-Colesa. Od 05.09 główna ścieżka MA `rho=-0.04`, więc te dwa
    ramiona różnią się teraz także kształtem.

Żadna z tych czterech rzeczy nie jest dowodem, że ramię szkodzi. Razem
wystarczają, żeby to zmierzyć, zanim zacznę poprawiać jego macierz.

PYTANIE: jaka waga ramienia bayesian minimalizuje Brier 1X2, i czy produkcyjne
0.5 jest od niej istotnie gorsze.

ARMIE: `W_BAYESIAN` ∈ {0.00, 0.25, 0.50, 0.75, 1.00} plus waga dopasowana
ciągle na TRENINGU (<2024-01-01). Ocena na holdoucie (>=2024-01-01).

CLASSIC: konfiguracja produkcyjna po 05.09 — okno 30, płaskie wagi, bez
ściągania, `WAGA_STRZALOW=0.7`, macierz 9 komórek z `rho=-0.04`.
BAYESIAN: odtworzony wiernie, RAZEM ZE WSZYSTKIMI CZTEREMA WADAMI WYŻEJ.
Mierzymy to, co gra, nie to, co dałoby się z tego zrobić.

BLEND: liniowy po pw/pr/pp i renormalizacja — dokładnie `blend_dixon_coles`.

REGUŁA DECYZYJNA, ZAMROŻONA — z DWOMA progami, nie jednym.
Lekcja z 05.09: tego dnia dwa efekty po +0.00003 Briera dostały przeciwne
werdykty, bo próg patrzył wyłącznie na `z`. Próg istotności odpowiada na
pytanie „czy efekt jest niezerowy", a nie na to, które naprawdę zadaję.

  1. ISTOTNOŚĆ: sparowana różnica Briera na holdoucie (produkcyjne 0.5 minus
     najlepsza waga) musi mieć z >= +3.
  2. ROZMIAR: ta sama różnica, liczona PO ROZCIEŃCZENIU ceną przy wadze rynku
     0.70, musi wynosić co najmniej **0.0005** Briera. To jest ~15x efekt
     korekty τ z 05.09 i mniej więcej granica, poniżej której nie warto ruszać
     produkcji, bo zmiany nikt nie zobaczy.
  3. REPLIKACJA: >= 2/3 lig z n >= 300 na holdoucie w tę samą stronę.

Oba progi muszą przejść. Jeśli przejdzie istotność, a nie przejdzie rozmiar —
raportuję jako „zmierzone, nie warte zmiany" i zostawiam produkcję w spokoju.

CZEGO TO NIE ZMIENIA. Model dalej przegrywa z ceną w 39 ligach na 39.
=============================================================================

    python scripts/ramie_bayesian.py --holdout 2024-01-01
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
    KLUCZE, PROD, _sklej, _srednie_kroczace, brier_z_p, devig, lambdy,
    maska_uzywalnych, sparowana, zbierz,
)
from ksztalt_dc import pmf_obciete, wyjscia_dc  # noqa: E402

# Parytet z `poisson_bayesian`: 3x waga dla ostatnich pieciu meczow, prior o sile
# trzech pseudo-meczow, brak okna, `BONUS_DOMOWY` tylko po stronie gospodarza.
W_SWIEZE, W_STARE, N_SWIEZYCH = 3.0, 1.0, 5
SILA_PRIORU = 3.0
BONUS_DOMOWY = 1.15
MAX_GOLI_BAYES = 8          # `arange(MAX_GOLE)` — INNE obciecie niz classic
OKNO_BEZ_OKNA = 600         # „brak okna" wektorowo; asercja pilnuje, ze starczy
WAGI_SIATKA = (0.0, 0.25, 0.50, 0.75, 1.0)
MIN_ROZMIAR = 0.0005        # prog rozmiaru efektu, patrz pre-rejestracja
MIN_LIGA = 300


def wagi_bayes(okno: int = OKNO_BEZ_OKNA) -> np.ndarray:
    """Wagi pozycyjne: ostatnie `N_SWIEZYCH` po 3.0, wcześniejsze po 1.0."""
    w = np.full(okno, W_STARE)
    w[-N_SWIEZYCH:] = W_SWIEZE
    return w


def ratingi_bayes(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Walk-forward odpowiednik `poisson_bayesian._compute_ratings` + średnich.

    GLOBALNIE, bez podziału na ligi — bo tak liczy produkcja i to jest właśnie
    ta cecha, o którą pytamy. `df` musi być posortowane po dacie.
    """
    daty = df["date"].to_numpy()
    hg, ag = df["hg"].to_numpy(float), df["ag"].to_numpy(float)
    n = len(df)

    # Srednie „ligowe" — w rzeczywistosci srednie ze WSZYSTKICH lig naraz.
    przed = np.searchsorted(daty, daty, side="left")
    cs_h = np.concatenate([[0.0], np.cumsum(hg)])
    cs_a = np.concatenate([[0.0], np.cumsum(ag)])
    with np.errstate(invalid="ignore", divide="ignore"):
        sr_h = np.where(przed > 0, cs_h[przed] / np.maximum(przed, 1), np.nan)
        sr_a = np.where(przed > 0, cs_a[przed] / np.maximum(przed, 1), np.nan)
    out = {"liga_dom": np.maximum(sr_h, 0.5), "liga_wyj": np.maximum(sr_a, 0.5)}

    wagi = wagi_bayes()
    for strona, kol in (("dom", "home"), ("wyj", "away")):
        att = np.full(n, np.nan)
        dfn = np.full(n, np.nan)
        licz = np.zeros(n)
        zdob, strac = (hg, ag) if strona == "dom" else (ag, hg)
        wart = df[kol].to_numpy()
        for druzyna in pd.unique(wart):
            gdzie = np.flatnonzero(wart == druzyna)
            gd = daty[gdzie]
            ile = np.searchsorted(gd, daty[gdzie], side="left")
            assert ile.max(initial=0) <= OKNO_BEZ_OKNA, (
                "druzyna ma wiecej meczow niz OKNO_BEZ_OKNA — podnies stala, "
                "bo produkcja nie ma tu zadnego okna")
            a_, c_ = _srednie_kroczace(zdob[gdzie], ile, OKNO_BEZ_OKNA, wagi)
            d_, _ = _srednie_kroczace(strac[gdzie], ile, OKNO_BEZ_OKNA, wagi)
            att[gdzie], dfn[gdzie], licz[gdzie] = a_, d_, c_
        out[f"att_{strona}"] = att
        out[f"def_{strona}"] = dfn
        out[f"n_{strona}"] = licz
    return out


def _sciagnij(obs: np.ndarray, n: np.ndarray, prior: np.ndarray) -> np.ndarray:
    """`_bayesian_shrink`: (n*obs + 3*prior) / (n + 3)."""
    return (n * obs + SILA_PRIORU * prior) / (n + SILA_PRIORU)


def lambdy_bayes(r: dict) -> tuple[np.ndarray, np.ndarray]:
    """λ ramienia bayesian — wiernie, razem z priorem po niewłaściwej stronie.

    `predict_match_bayesian` ściąga obronę gospodarza do średniej goli
    GOSPODARZY, choć obrona u siebie to gole STRACONE, czyli bliżej średniej
    gości. Tak jest w kodzie produkcyjnym i tak zostaje — mierzymy to, co gra.
    """
    lig_d, lig_w = r["liga_dom"], r["liga_wyj"]
    att_g = _sciagnij(r["att_dom"], r["n_dom"], lig_d)
    def_a = _sciagnij(r["def_wyj"], r["n_wyj"], lig_w)
    att_a = _sciagnij(r["att_wyj"], r["n_wyj"], lig_w)
    def_g = _sciagnij(r["def_dom"], r["n_dom"], lig_d)
    lg = np.maximum(0.05, att_g * (def_a / lig_w) * BONUS_DOMOWY)
    la = np.maximum(0.05, att_a * (def_g / lig_d))
    return lg, la


def p1x2_bayes(lg: np.ndarray, la: np.ndarray) -> np.ndarray:
    """1X2 z macierzy ramienia bayesian: 8 komórek, rho=0 (`USE_DC_TAU=0`)."""
    h = np.arange(MAX_GOLI_BAYES)
    pg = _poisson.pmf(h[None, :], lg[:, None])
    pa = _poisson.pmf(h[None, :], la[:, None])
    pg /= pg.sum(axis=1, keepdims=True)
    pa /= pa.sum(axis=1, keepdims=True)
    kum = np.cumsum(pa, axis=1)
    p_mniej = np.concatenate([np.zeros((len(pg), 1)), kum[:, :-1]], axis=1)
    pw = (pg * p_mniej).sum(axis=1)
    pr = (pg * pa).sum(axis=1)
    return np.stack([pw, pr, 1.0 - pw - pr], axis=1)


def blenduj(p_classic: np.ndarray, p_bayes: np.ndarray, w: float) -> np.ndarray:
    """Liniowo po pw/pr/pp i renormalizacja — jak `blend_dixon_coles`."""
    p = (1.0 - w) * p_classic + w * p_bayes
    return p / p.sum(axis=1, keepdims=True)


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

    print("Ramie bayesian (globalnie, bez podzialu na ligi)...", flush=True)
    rb = ratingi_bayes(df)
    lg_b_all, la_b_all = lambdy_bayes(rb)

    print("Ramie classic (konfiguracja produkcyjna)...", flush=True)
    zb = zbierz(df, (PROD["okno"],), (PROD["polowicz"],))
    d = _sklej(zb["zestawy"][(PROD["okno"], PROD["polowicz"])], zb["meta"], KLUCZE)
    lg_c, la_c = lambdy(d, PROD["k"], PROD["skala_g"], PROD["skala_a"])
    p_classic = wyjscia_dc(pmf_obciete(lg_c), pmf_obciete(la_c),
                           lg_c, la_c, DC_RHO_CLASSIC)["p1x2"]

    kotwica = d["idx"].astype(int)
    p_bayes = p1x2_bayes(lg_b_all[kotwica], la_b_all[kotwica])

    ok = maska_uzywalnych(d) & np.isfinite(p_bayes).all(axis=1)
    granica = pd.Timestamp(args.holdout)
    tren, hold = ok & (d["date"] < granica), ok & (d["date"] >= granica)
    y = d["wynik"]
    print(f"Uzywalnych: {int(ok.sum())}  (trening {int(tren.sum())}, "
          f"holdout {int(hold.sum())})")

    kreska = "=" * 88
    print(f"\n{kreska}\n  LAMBDA OBU RAMION kontra faktyczne gole (opisowo)\n{kreska}")
    print(f"  faktyczne   {d['hg'][hold].mean():.4f} / {d['ag'][hold].mean():.4f}")
    print(f"  classic     {lg_c[hold].mean():.4f} / {la_c[hold].mean():.4f}")
    print(f"  bayesian    {lg_b_all[kotwica][hold].mean():.4f} / "
          f"{la_b_all[kotwica][hold].mean():.4f}")

    print(f"\n{kreska}\n  SIATKA WAG — Brier 1X2\n{kreska}")
    siatka = []
    for w in WAGI_SIATKA:
        bt = brier_z_p(blenduj(p_classic[tren], p_bayes[tren], w), y[tren]).mean()
        bh = brier_z_p(blenduj(p_classic[hold], p_bayes[hold], w), y[hold]).mean()
        siatka.append({"w": w, "trening": float(bt), "holdout": float(bh)})
        print(f"  w={w:.2f}   trening {bt:.5f}   holdout {bh:.5f}"
              f"{'   <- produkcja' if w == 0.5 else ''}")

    gesta = np.linspace(0.0, 1.0, 101)
    w_opt = float(min(gesta, key=lambda w: brier_z_p(
        blenduj(p_classic[tren], p_bayes[tren], w), y[tren]).mean()))
    print(f"\n  waga dopasowana na TRENINGU: {w_opt:.3f}  (produkcja 0.5)")

    b_prod = brier_z_p(blenduj(p_classic[hold], p_bayes[hold], 0.5), y[hold])
    b_opt = brier_z_p(blenduj(p_classic[hold], p_bayes[hold], w_opt), y[hold])
    s1, se1, z1 = sparowana(b_prod - b_opt)
    print(f"  holdout: produkcja {b_prod.mean():.5f}   dopasowane {b_opt.mean():.5f}")
    print(f"  sparowana roznica {s1:+.5f}  SE {se1:.5f}  z={z1:+.2f}")

    print(f"\n{kreska}\n  ROZMIAR PO ROZCIENCZENIU CENA\n{kreska}")
    p_ryn = devig(d["odds_h_pinn"], d["odds_d_pinn"], d["odds_a_pinn"])
    mix = hold & np.isfinite(p_ryn).all(axis=1)
    print(f"  Meczow z zamknieciem Pinnacle: {int(mix.sum())} z {int(hold.sum())}")
    pp_ = blenduj(p_classic[mix], p_bayes[mix], 0.5)
    po_ = blenduj(p_classic[mix], p_bayes[mix], w_opt)
    rozm = {}
    for w_r in (0.0, 0.30, 0.70, 1.0):
        bp = brier_z_p((1 - w_r) * pp_ + w_r * p_ryn[mix], y[mix])
        bo = brier_z_p((1 - w_r) * po_ + w_r * p_ryn[mix], y[mix])
        sw, sew, zw = sparowana(bp - bo)
        rozm[w_r] = {"d": sw, "se": sew, "z": zw}
        print(f"  waga rynku {w_r:.2f}   produkcja {bp.mean():.5f}   "
              f"dopasowane {bo.mean():.5f}   roznica {sw:+.5f}  z={zw:+.2f}")

    print(f"\n{kreska}\n  REPLIKACJA PO LIGACH (holdout, n >= {MIN_LIGA})\n{kreska}")
    plus = wszystkie = 0
    per_liga = []
    for liga in sorted(set(d["league"][hold])):
        m = hold & (d["league"] == liga)
        if m.sum() < MIN_LIGA:
            continue
        sl, _, zl = sparowana(
            brier_z_p(blenduj(p_classic[m], p_bayes[m], 0.5), y[m])
            - brier_z_p(blenduj(p_classic[m], p_bayes[m], w_opt), y[m]))
        wszystkie += 1
        plus += int(sl > 0)
        per_liga.append({"liga": liga, "n": int(m.sum()), "d": sl, "z": zl})
        print(f"  {liga:28s} n={int(m.sum()):5d}   {sl:+.5f}  z={zl:+5.1f}")
    print(f"\n  Lig na korzysc zmiany: {plus}/{wszystkie}"
          f"  (prog: {int(np.ceil(2 * wszystkie / 3))})")

    print(f"\n{kreska}\n  REGULA DECYZYJNA (zamrozona, DWA progi)\n{kreska}")
    d70 = rozm[0.70]["d"]
    r1 = np.isfinite(z1) and z1 >= 3.0
    r2 = np.isfinite(d70) and d70 >= MIN_ROZMIAR
    r3 = wszystkie > 0 and plus >= np.ceil(2 * wszystkie / 3)
    print(f"  1. istotnosc  z >= +3          : {'TAK' if r1 else 'NIE'}  (z={z1:+.2f})")
    print(f"  2. rozmiar przy w=0.70 >= {MIN_ROZMIAR}: "
          f"{'TAK' if r2 else 'NIE'}  ({d70:+.5f})")
    print(f"  3. >= 2/3 lig                  : {'TAK' if r3 else 'NIE'}  "
          f"({plus}/{wszystkie})")
    if r1 and r2 and r3:
        print(f"\n  WNIOSEK: zmienic W_BAYESIAN 0.5 -> {w_opt:.3f}.")
    elif r1 and r3:
        print("\n  WNIOSEK: efekt zmierzony i istotny, ale ZA MALY po rozcienczeniu."
              "\n  Zmierzone, nie warte zmiany — produkcja bez zmian.")
    else:
        print("\n  WNIOSEK: warunki NIE spelnione — produkcja bez zmian.")

    if args.wynik:
        Path(args.wynik).write_text(json.dumps({
            "holdout": args.holdout, "n_holdout": int(hold.sum()),
            "w_opt": w_opt, "siatka": siatka,
            "holdout_prod": float(b_prod.mean()), "holdout_opt": float(b_opt.mean()),
            "d": s1, "se": se1, "z": z1,
            "rozmiar": {str(k): v for k, v in rozm.items()},
            "per_liga": per_liga, "ligi_plus": plus, "ligi_all": wszystkie,
            "regula": {"r1": bool(r1), "r2": bool(r2), "r3": bool(r3)},
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nZapisane: {args.wynik}")


if __name__ == "__main__":
    main()

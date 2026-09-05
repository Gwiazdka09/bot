#!/usr/bin/env python
"""ksztalt_dc.py — czy korekta Dixona-Colesa poprawia nasz rozkład wyników.

===========================  PRE-REJESTRACJA  ===============================
Spisana 2026-09-05, PRZED policzeniem czegokolwiek.

SKĄD TO PYTANIE. `lambda_kto_lepszy.py` (05.09) pokazał, że λ odtwarzające 1X2
rynku daje przy NASZEJ macierzy Over 2.5 = 0.4205, podczas gdy rynek wycenia
0.4987 — niedobór 7.8 punktu procentowego na n=47 039. Ta sama liczba liczona
przy `rho=-0.05` spadała do 3.3 pp. Rynek jest wewnętrznie spójny, więc to nasz
rozkład nie mieści obu jego liczb naraz.

CO PRODUKCJA REALNIE LICZY, bo to nie jest oczywiste i sam się na tym pomyliłem:

  * główna ścieżka `poisson.predict_match` → `poisson._macierz` NIE MA korekty
    τ w ogóle. To czysty iloczyn zewnętrzny dwóch rozkładów Poissona, obcięty
    na `MAX_GOLE=8`, ze śladowym wygładzaniem 1e-8 i renormalizacją. Nie ma
    tam nawet flagi — `rho` w tym pliku nie występuje;
  * `USE_DC_TAU` (domyślnie 0) i `DC_RHO` (-0.13) sięgają WYŁĄCZNIE
    `poisson_bayesian.predict_match_bayesian`;
  * `quick_picks` blenduje to ramię pod flagą `USE_DIXON_COLES` (domyślnie 1)
    z wagą `W_BAYESIAN=0.5`. Czyli produkcja miesza pół na pół z czymś, co
    nazywa się „ramieniem Dixona-Colesa", a co przy `USE_DC_TAU=0` również
    liczy `rho=0`. **Ramię Dixona-Colesa bez korekty Dixona-Colesa.**

CO ROBI τ. Mnoży dokładnie cztery komórki macierzy:

    τ(0,0) = 1 - λ_g*λ_a*ρ     τ(0,1) = 1 + λ_g*ρ
    τ(1,0) = 1 + λ_a*ρ         τ(1,1) = 1 - ρ

Przy ρ<0 rosną 0-0 i 1-1, maleją 1-0 i 0-1. Poisson notorycznie zaniża remisy
niskobramkowe i po to ta korekta powstała (Dixon i Coles 1997).

POPRAWKA DO WŁASNEJ PRE-REJESTRACJI, wpisana PRZED jakimkolwiek przebiegiem.
Pierwsza wersja miała pomiar 2 w postaci „strażnika Over 2.5": τ przesuwa masę
na niskie remisy, więc mogłaby zepsuć rynek golowy. Test kierunkowy pokazał, że
to jest bzdura, i to bzdura dowodliwa. Dla nieobciętego Poissona:

    d(0,0) = -K*λ*μ*ρ    d(0,1) = +K*λ*μ*ρ
    d(1,0) = +K*λ*μ*ρ    d(1,1) = -K*λ*μ*ρ        gdzie K = e^(-λ-μ)

Suma poprawek jest TOŻSAMOŚCIOWO ZEROWA. τ nie dodaje ani nie zabiera masy,
tylko przekłada ją między czterema komórkami — wszystkie o sumie goli <= 2.
**Over 2.5 przy stałym λ nie zmienia się w ogóle.** Sprawdzone liczbowo: różnica
rzędu 1e-16.

Wynika z tego coś więcej niż poprawka testu. Niedobór 7.8 pp na Over 2.5
z `lambda_kto_lepszy.py` **nie jest naprawialny korektą τ**. Tamten pomiar
odzyskiwał λ, a przy `rho=-0.05` wychodziły λ WYŻSZE (1.434/1.122 zamiast
1.3389/1.0323) i to one dawały więcej goli — nie τ. Zdanie „włączenie DC
domknie lukę golową" jest fałszywe i nie wolno go stawiać.

Zostaje pytanie węższe, ale nadal warte pomiaru: czy τ poprawia 1X2, czyli
podział masy między wygraną, remis a porażkę. Pomiar 2 zamieniony na strażnika,
który realnie coś mierzy — log-wiarygodność FAKTYCZNEGO WYNIKU MECZU na
holdoucie, czyli wielkość, którą τ modeluje.

POMIAR 0 (opisowy, liczony pierwszy): średnie przewidywane p(1)/p(X)/p(2) oraz
Over 2.5 kontra faktyczne częstości, przy obecnym `rho=0`. Jeśli nasze p(X) NIE
jest zaniżone, to cała hipoteza upada zanim się zacznie i trzeba to powiedzieć
wprost.

POMIAR 1: `rho` dopasowane na TRENINGU (<2024-01-01), potem holdout.
  Funkcja celu dopasowania: log-wiarygodność FAKTYCZNEGO WYNIKU MECZU, czyli
  pary (hg, ag) pod pełną macierzą. To jest to, co τ modeluje, i jest to INNA
  wielkość niż metryka oceny — Brier 1X2 mierzy tylko trzy zlepione komórki.
  Dopasowanie do Briera byłoby dopasowaniem do własnego egzaminu.

  Ocena na holdoucie: sparowany Brier 1X2, dopasowane ρ kontra ρ=0.

POMIAR 2 (strażnik): sparowana log-wiarygodność FAKTYCZNEGO WYNIKU MECZU na
  holdoucie. To jest wielkość, którą τ modeluje wprost, i jest niezależna od
  Briera 1X2 — poprawa 1X2 przy pogorszeniu rozkładu wyników znaczyłaby, że
  trafiliśmy w metrykę, a nie w rzeczywistość. Wymagane z >= +3.
  Przy okazji raportujemy różnicę Over 2.5, która z dowodu wyżej ma wyjść
  numerycznym zerem — jeśli nie wyjdzie, arytmetyka jest zepsuta.

ZAKRES: ρ ∈ [-0.30, 0.30]. Obejmuje wpisane z ręki -0.13 i -0.05 oraz zero,
i pozwala wyjść na dodatnie, gdyby dane mówiły coś odwrotnego.

λ BEZ ZMIAN: konfiguracja estymatora produkcyjna (okno 30, płaskie wagi, bez
ściągania, `WAGA_STRZALOW=0.7`). Zmieniamy WYŁĄCZNIE kształt — dopasowany
wczoraj estymator zostaje poza tym pomiarem, żeby nie mieszać dwóch zmian.

ANEKS O ROZCIEŃCZENIU, wpisany od razu, bo bez niego wynik jest niepełny.
Poprawka kształtu dotyka ramienia classic, a produkcja rozcieńcza je DWA razy:

  1. blendem 50/50 z ramieniem bayesian, którego ta zmiana nie dotyczy;
  2. ensemblem z ceną, na API z wagą rynku 0.70.

Liczymy więc Brier mieszanki dla w ∈ {0.00, 0.30, 0.70, 1.00}, w dwóch
wariantach strony modelowej:
  * CZYSTY:    p_model = p_nowe
  * OSTROŻNY:  p_model = 0.5*p_nowe + 0.5*p_stare
Wariant ostrożny przybliża blend z niezmienionym ramieniem bayesian, podstawiając
za nie nasze własne stare 1X2. To przybliżenie — tamto ramię ma inny estymator
sił — ale kierunek rozcieńczenia oddaje, a bez niego zysk byłby raportowany
dwukrotnie za wysoko.

REGUŁA DECYZYJNA, ZAMROŻONA:
  1. holdout, sparowany Brier 1X2 (ρ=0 minus ρ dopasowane), z >= +3;
  2. STRAŻNIK: sparowana log-wiarygodność wyniku meczu na holdoucie, z >= +3;
  3. >= 2/3 lig z n >= 300 na holdoucie dodatnie;
  4. ANEKS: wariant OSTROŻNY przy w=0.70 musi mieć z >= +2.
Wszystkie cztery muszą przejść, żeby ruszać `poisson._macierz`. To jest rdzeń
modelu i dotyka każdej predykcji, jaką ten system wypuszcza.

CZEGO TO NIE ZMIENIA. Model dalej przegrywa z ceną w 39 ligach na 39, a jego λ
dalej są gorsze od rynkowych (z=-48.38). To jest praca nad kształtem rozkładu,
nie nad przewagą.
=============================================================================

    python scripts/ksztalt_dc.py --holdout 2024-01-01
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
    KLUCZE, MAX_GOLI, PROD, _sklej, brier_z_p, devig, lambdy,
    maska_uzywalnych, sparowana, zbierz,
)

RHO_MIN, RHO_MAX = -0.30, 0.30
MIN_LIGA = 300


def pmf_obciete(lam: np.ndarray) -> np.ndarray:
    """Rozkład Poissona obcięty na `MAX_GOLI` i renormalizowany — jak produkcja."""
    h = np.arange(MAX_GOLI)
    p = _poisson.pmf(h[None, :], lam[:, None])
    return p / p.sum(axis=1, keepdims=True)


def _tau(lg: np.ndarray, la: np.ndarray, rho: float) -> tuple[np.ndarray, ...]:
    """Cztery współczynniki τ, obcięte od dołu na zerze — jak `tau_dixon_coles`."""
    z = np.zeros_like(lg)
    return (np.maximum(z, 1.0 - lg * la * rho),   # (0,0)
            np.maximum(z, 1.0 + lg * rho),        # (0,1)
            np.maximum(z, 1.0 + la * rho),        # (1,0)
            np.maximum(z, 1.0 - rho))             # (1,1)


def wyjscia_dc(pg: np.ndarray, pa: np.ndarray, lg: np.ndarray, la: np.ndarray,
               rho: float, hg: np.ndarray | None = None,
               ag: np.ndarray | None = None) -> dict:
    """1X2, Over 2.5 i prawdopodobieństwo faktycznego wyniku, przy korekcie τ.

    Liczone BEZ budowania macierzy 8x8 na mecz. τ dotyka czterech komórek, więc
    wystarczy poprawić o nie liczniki i wspólny mianownik; przy 134 tys. meczów
    razy siatka ρ pełna macierz kosztowałaby gigabajty za nic.
    """
    if rho == 0.0:
        t00 = t01 = t10 = t11 = np.ones_like(lg)
    else:
        t00, t01, t10, t11 = _tau(lg, la, rho)

    d00 = pg[:, 0] * pa[:, 0] * (t00 - 1.0)
    d01 = pg[:, 0] * pa[:, 1] * (t01 - 1.0)
    d10 = pg[:, 1] * pa[:, 0] * (t10 - 1.0)
    d11 = pg[:, 1] * pa[:, 1] * (t11 - 1.0)
    s = 1.0 + d00 + d01 + d10 + d11

    kum_a = np.cumsum(pa, axis=1)
    p_mniej = np.concatenate([np.zeros((len(pg), 1)), kum_a[:, :-1]], axis=1)
    pw0 = (pg * p_mniej).sum(axis=1)
    pr0 = (pg * pa).sum(axis=1)
    h = np.arange(MAX_GOLI)
    m0 = pg[:, :, None] * pa[:, None, :]
    over0 = m0[:, (h[:, None] + h[None, :]) > 2.5].sum(axis=1)

    # Komorki (1,0) -> wygrana gospodarza; (0,0) i (1,1) -> remis; (0,1) -> gosc.
    # Wszystkie cztery maja sume goli <= 2, wiec licznik Over 2.5 jest nietkniety.
    pw = (pw0 + d10) / s
    pr = (pr0 + d00 + d11) / s
    out = {"p1x2": np.stack([pw, pr, 1.0 - pw - pr], axis=1), "over25": over0 / s}

    if hg is not None and ag is not None:
        i, j = hg.astype(int), ag.astype(int)
        wiersz = np.arange(len(pg))
        p_wyn = pg[wiersz, np.clip(i, 0, MAX_GOLI - 1)] * pa[wiersz, np.clip(j, 0, MAX_GOLI - 1)]
        korekta = np.ones(len(pg))
        for (ii, jj), t in (((0, 0), t00), ((0, 1), t01), ((1, 0), t10), ((1, 1), t11)):
            korekta = np.where((i == ii) & (j == jj), t, korekta)
        out["p_wynik"] = p_wyn * korekta / s
    return out


def dopasuj_rho(pg, pa, lg, la, hg, ag) -> float:
    """ρ maksymalizujące log-wiarygodność faktycznych wyników. Siatka + zagęszczenie.

    Jeden parametr na ograniczonym odcinku — siatka jest tu uczciwsza niż
    optymalizator, bo pokazuje cały przebieg i nie da się utknąć w minimum
    lokalnym, którego nikt nie zobaczy.
    """
    def ll(rho: float) -> float:
        p = wyjscia_dc(pg, pa, lg, la, rho, hg, ag)["p_wynik"]
        return float(np.mean(np.log(np.maximum(p, 1e-300))))

    siatka = np.linspace(RHO_MIN, RHO_MAX, 25)
    najlepsze = max(siatka, key=ll)
    krok = siatka[1] - siatka[0]
    gesta = np.linspace(max(RHO_MIN, najlepsze - krok), min(RHO_MAX, najlepsze + krok), 21)
    return float(max(gesta, key=ll))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--holdout", default="2024-01-01")
    ap.add_argument("--wynik", default=None)
    args = ap.parse_args()

    from footstats.data.historical_loader import load_cached

    df = load_cached()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "hg", "ag"])

    print("Licze ratingi w konfiguracji PRODUKCYJNEJ...", flush=True)
    zb = zbierz(df, (PROD["okno"],), (PROD["polowicz"],))
    d = _sklej(zb["zestawy"][(PROD["okno"], PROD["polowicz"])], zb["meta"], KLUCZE)
    lg, la = lambdy(d, PROD["k"], PROD["skala_g"], PROD["skala_a"])
    uz = maska_uzywalnych(d)
    granica = pd.Timestamp(args.holdout)
    tren, hold = uz & (d["date"] < granica), uz & (d["date"] >= granica)
    print(f"Uzywalnych: {int(uz.sum())}  (trening {int(tren.sum())}, holdout {int(hold.sum())})")

    pg, pa = pmf_obciete(lg), pmf_obciete(la)
    hg, ag = d["hg"], d["ag"]
    wynik = d["wynik"]
    over_fakt = ((hg + ag) > 2.5).astype(float)

    kreska = "=" * 88

    # ── POMIAR 0 ──────────────────────────────────────────────────────────
    print(f"\n{kreska}\n  POMIAR 0 — czy zanizamy remisy (opisowy, rho=0)\n{kreska}")
    p0 = wyjscia_dc(pg, pa, lg, la, 0.0)["p1x2"]
    etyk = ("gospodarz", "remis", "gosc")
    zanizamy = None
    for i, nazwa in enumerate(etyk):
        przew = float(p0[uz, i].mean())
        fakt = float((wynik[uz] == i).mean())
        print(f"  {nazwa:10s}  przewidywane {przew:.4f}   faktyczne {fakt:.4f}"
              f"   roznica {przew - fakt:+.4f}")
        if nazwa == "remis":
            zanizamy = przew < fakt
    o_przew = float(wyjscia_dc(pg, pa, lg, la, 0.0)["over25"][uz].mean())
    print(f"  {'Over 2.5':10s}  przewidywane {o_przew:.4f}"
          f"   faktyczne {float(over_fakt[uz].mean()):.4f}"
          f"   roznica {o_przew - float(over_fakt[uz].mean()):+.4f}")
    print(f"\n  Remisy {'ZANIZANE' if zanizamy else 'NIE zanizane'} — hipoteza tau"
          f" {'ma sens' if zanizamy else 'traci podstawe'}.")

    # ── POMIAR 1 ──────────────────────────────────────────────────────────
    print(f"\n{kreska}\n  POMIAR 1 — rho dopasowane na treningu\n{kreska}")
    rho = dopasuj_rho(pg[tren], pa[tren], lg[tren], la[tren], hg[tren], ag[tren])
    print(f"  rho dopasowane: {rho:+.4f}   (produkcja 0.0; wpisane z reki: -0.13, -0.05)")

    n0 = wyjscia_dc(pg, pa, lg, la, 0.0, hg, ag)
    nr = wyjscia_dc(pg, pa, lg, la, rho, hg, ag)
    b0 = brier_z_p(n0["p1x2"][hold], wynik[hold])
    br = brier_z_p(nr["p1x2"][hold], wynik[hold])
    s1, se1, z1 = sparowana(b0 - br)
    print(f"  Brier 1X2 na holdoucie:  rho=0 {b0.mean():.5f}   rho={rho:+.4f} {br.mean():.5f}")
    print(f"  sparowana roznica {s1:+.5f}  SE {se1:.5f}  z={z1:+.2f}  (n={int(hold.sum())})")

    # ── POMIAR 2 ──────────────────────────────────────────────────────────
    print(f"\n{kreska}\n  POMIAR 2 — log-wiarygodnosc WYNIKU MECZU (straznik)\n{kreska}")
    ll0 = np.log(np.maximum(n0["p_wynik"][hold], 1e-300))
    llr = np.log(np.maximum(nr["p_wynik"][hold], 1e-300))
    s2, se2, z2 = sparowana(llr - ll0)
    print(f"  log-wiar wyniku:  rho=0 {ll0.mean():.5f}   rho={rho:+.4f} {llr.mean():.5f}")
    print(f"  sparowana roznica {s2:+.5f}  SE {se2:.5f}  z={z2:+.2f}")
    d_over = float(np.abs(nr["over25"][hold] - n0["over25"][hold]).max())
    print(f"\n  Kontrola: max |roznica Over 2.5| = {d_over:.2e}"
          f"  (z dowodu ma byc zerem; tau zachowuje mase)")

    # ── ANEKS ─────────────────────────────────────────────────────────────
    print(f"\n{kreska}\n  ANEKS — rozcienczenie (blend 50/50 + cena)\n{kreska}")
    p_ryn = devig(d["odds_h_pinn"], d["odds_d_pinn"], d["odds_a_pinn"])
    mix = hold & np.isfinite(p_ryn).all(axis=1)
    print(f"  Meczow z zamknieciem Pinnacle: {int(mix.sum())} z {int(hold.sum())}")
    p_st, p_no, p_rn, y = n0["p1x2"][mix], nr["p1x2"][mix], p_ryn[mix], wynik[mix]
    p_ostr = 0.5 * p_no + 0.5 * p_st
    aneks = []
    for nazwa, p_mod in (("CZYSTY", p_no), ("OSTROZNY", p_ostr)):
        for w in (0.0, 0.30, 0.70, 1.0):
            bs = brier_z_p((1 - w) * p_st + w * p_rn, y)
            bn = brier_z_p((1 - w) * p_mod + w * p_rn, y)
            sw, sew, zw = sparowana(bs - bn)
            aneks.append({"wariant": nazwa, "w": w, "d": sw, "se": sew, "z": zw})
            print(f"  {nazwa:9s} w={w:.2f}   stare {bs.mean():.5f}   nowe {bn.mean():.5f}"
                  f"   roznica {sw:+.5f}  z={zw:+.2f}")
    z_ostr = next(a["z"] for a in aneks if a["wariant"] == "OSTROZNY" and a["w"] == 0.70)

    # ── ligi ──────────────────────────────────────────────────────────────
    print(f"\n{kreska}\n  REPLIKACJA PO LIGACH (holdout, n >= {MIN_LIGA})\n{kreska}")
    plus = wszystkie = 0
    per_liga = []
    for liga in sorted(set(d["league"][hold])):
        m = hold & (d["league"] == liga)
        if m.sum() < MIN_LIGA:
            continue
        sl, _, zl = sparowana(brier_z_p(n0["p1x2"][m], wynik[m])
                              - brier_z_p(nr["p1x2"][m], wynik[m]))
        wszystkie += 1
        plus += int(sl > 0)
        per_liga.append({"liga": liga, "n": int(m.sum()), "d": sl, "z": zl})
        print(f"  {liga:28s} n={int(m.sum()):5d}   {sl:+.5f}  z={zl:+5.1f}")
    print(f"\n  Lig dodatnich: {plus}/{wszystkie}  (prog: {int(np.ceil(2 * wszystkie / 3))})")

    # ── reguła ────────────────────────────────────────────────────────────
    print(f"\n{kreska}\n  REGULA DECYZYJNA (zamrozona przed przebiegiem)\n{kreska}")
    r1 = np.isfinite(z1) and z1 >= 3.0
    r2 = np.isfinite(z2) and z2 >= 3.0
    r3 = wszystkie > 0 and plus >= np.ceil(2 * wszystkie / 3)
    r4 = np.isfinite(z_ostr) and z_ostr >= 2.0
    for opis, ok, z_ in (("1. Brier 1X2 z >= +3", r1, z1),
                         ("2. log-wiar wyniku z >= +3", r2, z2),
                         ("3. >= 2/3 lig dodatnie", r3, float(plus)),
                         ("4. aneks OSTROZNY w=0.70 z >= +2", r4, z_ostr)):
        print(f"  {opis:36s} : {'TAK' if ok else 'NIE'}  ({z_:+.2f})")
    if r1 and r2 and r3 and r4:
        print(f"\n  WNIOSEK: wlaczyc korekte tau w poisson._macierz z rho={rho:+.4f}.")
    else:
        print("\n  WNIOSEK: warunki NIE spelnione — poisson._macierz bez zmian.")

    if args.wynik:
        Path(args.wynik).write_text(json.dumps({
            "rho": rho, "holdout": args.holdout, "n_holdout": int(hold.sum()),
            "pomiar_0": {n: {"przew": float(p0[uz, i].mean()),
                             "fakt": float((wynik[uz] == i).mean())}
                         for i, n in enumerate(etyk)},
            "pomiar_1": {"brier_rho0": float(b0.mean()), "brier_rho": float(br.mean()),
                         "d": s1, "se": se1, "z": z1},
            "pomiar_2": {"ll_rho0": float(ll0.mean()), "ll_rho": float(llr.mean()),
                         "d": s2, "se": se2, "z": z2,
                         "max_d_over25": d_over},
            "aneks": aneks, "per_liga": per_liga,
            "ligi_plus": plus, "ligi_all": wszystkie,
            "regula": {"r1": bool(r1), "r2": bool(r2), "r3": bool(r3), "r4": bool(r4)},
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nZapisane: {args.wynik}")


if __name__ == "__main__":
    main()

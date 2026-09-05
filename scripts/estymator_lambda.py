#!/usr/bin/env python
"""estymator_lambda.py — dopasowanie hiperparametrów estymatora sił drużyn.

===========================  PRE-REJESTRACJA  ===============================
Spisana 2026-09-05, PRZED policzeniem czegokolwiek.

DLACZEGO TERAZ. Pomiar z 04.09 (`lambda_czy_ksztalt.py`) rozłożył model na dwie
warstwy szeregowe — oceny sił → λ → macierz Poissona → 1X2 — i pokazał, że obie
prognozy, nasza i rynku, leżą na tej samej dwuparametrowej rozmaitości (reszty
dopasowania ~8e-5). W wymiarze 1X2 nie ma więc między nami RÓŻNICY KSZTAŁTU,
jest wyłącznie różnica λ. Sparowana log-wiarygodność faktycznych goli:
model −2.96048, rynek −2.86644, różnica −0.09404 (SE 0.00398, z=−23.65).

SPROSTOWANIE DO TAMTEGO RAPORTU, ZANIM COKOLWIEK Z NIEGO WYNIKNIE. Napisałem
tam, że nasze λ jest za wysokie o ~0.28 gola. To był porównanie z λ ODTWORZONYM
Z CENY, a nie z golami. Sędzią są gole (n=140 221):

    faktyczne     1.4872 / 1.1782   suma 2.6654
    nasze         1.573  / 1.264    suma 2.837    +6.5%
    rynek (odtw.) 1.434  / 1.122    suma 2.556    -4.1%

Rynkowe λ jest obciążone W DRUGĄ STRONĘ, bo powstaje z rzutu jego 1X2 na
Poissona — i pomiar 2 pokazał dokładnie ten niedobór (Over 2.5 z tego λ 0.4667
przy 0.4993 w cenie). Nasze przeszacowanie wynosi +6.5%, nie 0.28 gola.

CO DOKŁADNIE DOPASOWUJEMY. Ścieżka produkcyjna λ to
`predict_match` → `_baza_ligowa` → `form.sily_ligowe` → `form._tabela_ratingow`:

    λ_gosp = atak_dom(G) * obrona_wyj(A) * sr_dom
    λ_gosc = atak_wyj(A) * obrona_dom(G) * sr_wyj

gdzie `atak_dom(G)` = średnia goli G u siebie z OSTATNICH 30 jego meczów
domowych, podzielona przez ligową średnią goli gospodarza. Cztery rzeczy w tym
wzorze są wpisane z ręki i NIGDY nie były dopasowane na treningu z holdoutem:

  * `OKNO_LIGOWE = 30` — komentarz w kodzie mówi „15 za szumne, 60 ciągnie
    nieaktualną formę", ale w repo nie ma pomiaru, który by to rozstrzygał;
  * ZANIK CZASOWY — nie ma go wcale. Mecz sprzed dwóch lat waży tyle samo,
    co zeszłotygodniowy, dopóki mieści się w oknie;
  * ŚCIĄGANIE DO ŚREDNIEJ — też nie ma. Jest tylko twardy próg
    `MIN_MECZOW_LIGOWYCH = 6`; drużyna z sześcioma meczami dostaje rating
    liczony tak samo pewnie jak drużyna z trzydziestoma;
  * SKALA λ — brak. Zmierzone +6.5% obciążenia nikt nigdy nie korygował.

PARAMETRY I ICH ZAKRESY (zamrożone przed przebiegiem):
    okno       ∈ {10, 15, 20, 30, 45, 60, 90}        (produkcja: 30)
    polowicz   ∈ {∞, 60, 30, 15, 8} meczów           (produkcja: ∞ = płaskie)
    k_shrink   ∈ [0, 40] ciągle                       (produkcja: 0)
    skala_g    ∈ [0.7, 1.3] ciągle                    (produkcja: 1.0)
    skala_a    ∈ [0.7, 1.3] ciągle                    (produkcja: 1.0)

`k_shrink` ściąga rating do 1.0 po bayesowsku: r' = (n*r + k)/(n + k), gdzie n
to liczba meczów, z których rating powstał. `polowicz` to połowiczny zanik po
POZYCJI: k-ty od końca mecz waży 0.5^(k/polowicz).

CZEGO NIE RUSZAMY, ŻEBY NIE MIESZAĆ DWÓCH ZMIAN NARAZ:
  * `WAGA_STRZALOW = 0.7` — zostaje 0.7 w OBU ramionach. Domieszka strzałów
    była mierzona osobno i to nie jest pytanie tego pomiaru;
  * kształt macierzy (`rho`, `USE_DC_TAU=0`) — pomiar 04.09 pokazał, że w 1X2
    kształt nie różnicuje; ruszanie go tutaj byłoby drugą zmianą naraz;
  * warstwy mnożników z `predict_match` (importance, H2H, forteca, zmęczenie) —
    w walk-forwardzie i tak są 1.0.

FUNKCJA CELU I DLACZEGO NIE BRIER. Dopasowujemy na średniej log-wiarygodności
Poissona FAKTYCZNYCH goli. Brier 1X2 jest metryką, po której ten model będzie
oceniony, więc dopasowanie do niego byłoby dopasowaniem do własnego egzaminu.
Log-wiarygodność goli mierzy dokładnie tę warstwę, którą stroimy, i jest inną
wielkością niż ta, którą raportujemy na holdoucie.

PODZIAŁ. Trening: mecze przed 2024-01-01. Holdout: 2024-01-01 i później
(~32 tys. meczów). Podział PO DACIE, nie losowy — losowy przepuściłby przyszłość
do ratingów przez drużyny grające w obu połowach.

RATINGI SĄ WALK-FORWARD W OBU OKRESACH: dla każdego meczu wchodzą wyłącznie
mecze o dacie ŚCIŚLE WCZEŚNIEJSZEJ, także w treningu. Bez tego dopasowanie
optymalizowałoby wyciek, nie estymator.

REGUŁA DECYZYJNA, ZAMROŻONA:
  1. PIERWOTNA: sparowana różnica log-wiarygodności goli na HOLDOUCIE,
     dopasowane minus produkcyjne. Wymagane z >= +3.
  2. STRAŻNIK: sparowana różnica Briera 1X2 na holdoucie nie może być gorsza
     od produkcyjnej z z <= −2. Pogorszenie Briera UNIEWAŻNIA zmianę,
     niezależnie od log-wiarygodności — bo to Brier decyduje o produkcie.
  3. REPLIKACJA PO LIGACH: co najmniej 2/3 lig z n >= 300 na holdoucie musi
     mieć dodatnią różnicę. Poniżej — „nie replikuje się", zero zmian.
  4. CO NIESIE EFEKT: osobno liczymy ramię SAMA SKALA (okno 30, płaskie wagi,
     bez ściągania, dopasowane wyłącznie skala_g/skala_a). Jeśli sama skala
     zbiera >= 80% zysku pełnego dopasowania, rekomendacją są DWIE LICZBY,
     nie przebudowa estymatora. Najmniejsza zmiana, która robi robotę.

ANEKS, dopisany 2026-09-05 PO zobaczeniu wyniku ramienia głównego, ale PRZED
policzeniem czegokolwiek z tego, co opisuje.

DLACZEGO ANEKS W OGÓLE. Ramię główne mierzy model W IZOLACJI. Produkcja tak nie
gra: `predict_match` idzie potem przez `ensemble_probs`, gdzie miesza się z
devigiem kursów — na API z wagą rynku 0.70. Jeśli poprawka estymatora znika po
zmieszaniu, jest wynikiem laboratoryjnym i nie ma po co jej wdrażać. Bez tego
sprawdzenia zamieniałbym cztery stałe na produkcji za zero.

CO LICZYMY: Brier 1X2 mieszanki (1-w)*model + w*rynek na holdoucie, dla
w ∈ {0.00, 0.30, 0.70, 1.00}, osobno dla estymatora produkcyjnego i dopasowanego.
Rynek to devig proporcjonalny z ZAMKNIĘCIA Pinnacle (`odds_*_pinn`) — najostrzejsza
cena, jaką mamy. To jest wybór KONSERWATYWNY: im ostrzejszy partner w mieszance,
tym mniej zostaje do dołożenia modelowi. Kurs bukmacherski, z którym produkcja
miesza realnie, jest słabszy, więc zysk przy nim może być tylko większy.

REGUŁA ANEKSU, ZAMROŻONA: zmiana idzie na produkcję tylko wtedy, gdy przy
w = 0.70 — czyli wadze, którą API realnie ma ustawioną — sparowana różnica
Briera (produkcja minus dopasowane) ma z >= +2. Poniżej: wynik zostaje
pomiarem, kod produkcyjny bez zmian.

CZEGO TO NIE ZMIENIA. Model dalej przegrywa z ceną w 39 ligach na 39. Nawet
pełne domknięcie luki λ nie czyni z niego przewagi nad rynkiem; to jest praca
nad JAKOŚCIĄ prognozy, nie nad zyskiem.

PARYTET Z PRODUKCJĄ. Ratingi liczy tutaj własna implementacja wektorowa, bo
`sily_ligowe` przeliczana per mecz przy 140 tys. meczów razy 35 kombinacji
siatki jest nie do przejścia. Zgodności obu pilnuje
`tests/test_estymator_lambda.py` — bez niego stroiłbym inny estymator niż ten,
który gra na produkcji.
=============================================================================

    python scripts/estymator_lambda.py --holdout 2024-01-01
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.optimize import minimize  # noqa: E402
from scipy.stats import poisson as _poisson  # noqa: E402

PODZIAL = "2024-01-01"
OKNA = (10, 15, 20, 30, 45, 60, 90)
POLOWICZE = (np.inf, 60.0, 30.0, 15.0, 8.0)
MIN_MECZOW_LIGOWYCH = 6      # parytet z form.MIN_MECZOW_LIGOWYCH
WAGA_STRZALOW = 0.7          # parytet z config.WAGA_STRZALOW — NIE dopasowywana
# Liczba KOMOREK na strone. Produkcja wola `_macierz(..., MAX_GOLE + 1)`,
# czyli gole 0..8 = 9 komorek. Osiem komorek (blad do 2026-09-05) roznilo
# sie od produkcji nawet o 2.6e-3 w p(1) przy wysokich lambdach — wiecej
# niz efekty, ktore tu mierzymy.
MAX_GOLI = 9
PROD = {"okno": 30, "polowicz": np.inf, "k": 0.0, "skala_g": 1.0, "skala_a": 1.0}
MIN_LIGA_HOLDOUT = 300       # próg ligi w replikacji (reguła 3)


# ─────────────────────────────  ratingi  ─────────────────────────────────────

def wagi_okna(okno: int, polowicz: float) -> np.ndarray:
    """Wagi pozycyjne okna: ostatni element = najświeższy mecz, waga 1.0.

    `polowicz=inf` daje same jedynki, czyli dokładnie płaską średnią produkcji.
    """
    k = np.arange(okno - 1, -1, -1, dtype=float)   # odległość od teraźniejszości
    if not np.isfinite(polowicz):
        return np.ones(okno)
    return 0.5 ** (k / polowicz)


def _srednie_kroczace(x: np.ndarray, licznik: np.ndarray, okno: int,
                      wagi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Ważona średnia z OKNA ostatnich wpisów przed pozycją `licznik`.

    `x` to seria wartości drużyny (np. jej gole u siebie) w kolejności dat.
    `licznik[i]` mówi, ile wpisów tej serii było ŚCIŚLE PRZED i-tym zapytaniem.
    Zwraca (średnia, liczba realnie użytych wpisów) — druga wartość karmi
    ściąganie do średniej, bo rating z 6 meczów i z 30 to nie to samo.
    """
    pad = np.concatenate([np.full(okno, np.nan), x])
    okna = np.lib.stride_tricks.sliding_window_view(pad, okno)   # (len(x)+1, okno)
    wyc = okna[licznik]
    maska = ~np.isnan(wyc)
    w = np.where(maska, wagi[None, :], 0.0)
    suma_w = w.sum(axis=1)
    suma = np.nansum(np.where(maska, wyc, 0.0) * w, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        sr = np.where(suma_w > 0, suma / np.maximum(suma_w, 1e-12), np.nan)
    return sr, maska.sum(axis=1).astype(float)


def _tabela_kolumn(df: pd.DataFrame, kol_dom: str, kol_wyj: str,
                   okno: int, wagi: np.ndarray) -> dict[str, np.ndarray] | None:
    """Walk-forward ratingi dom/wyjazd dla JEDNEJ pary kolumn, dla całej ligi.

    Odpowiednik `form._tabela_ratingow`, tyle że policzony dla wszystkich
    meczów ligi naraz i wyłącznie z przeszłości każdego z nich.
    """
    dane = df.dropna(subset=[kol_dom, kol_wyj])
    if dane.empty:
        return None
    d = dane["date"].to_numpy()
    kol_daty = df["date"].to_numpy()

    # Średnie ligowe: rozszerzające się, z meczów ściśle wcześniejszych.
    przed = np.searchsorted(d, kol_daty, side="left")
    cs_dom = np.concatenate([[0.0], np.cumsum(dane[kol_dom].to_numpy(float))])
    cs_wyj = np.concatenate([[0.0], np.cumsum(dane[kol_wyj].to_numpy(float))])
    with np.errstate(invalid="ignore", divide="ignore"):
        sr_dom = np.where(przed > 0, cs_dom[przed] / np.maximum(przed, 1), np.nan)
        sr_wyj = np.where(przed > 0, cs_wyj[przed] / np.maximum(przed, 1), np.nan)

    out = {"sr_dom": sr_dom, "sr_wyj": sr_wyj}
    for strona, kol_druzyny in (("dom", "home"), ("wyj", "away")):
        atak = np.full(len(df), np.nan)
        obr = np.full(len(df), np.nan)
        n_uz = np.zeros(len(df))
        # `kol_zdobyte` z perspektywy tej drużyny na tej stronie boiska.
        kol_zdob, kol_strac = (kol_dom, kol_wyj) if strona == "dom" else (kol_wyj, kol_dom)
        for druzyna, grupa in dane.groupby(kol_druzyny, sort=False):
            gd = grupa["date"].to_numpy()
            zdob = grupa[kol_zdob].to_numpy(float)
            strac = grupa[kol_strac].to_numpy(float)
            # Mecze tej drużyny, o które pytamy — na TEJ stronie boiska.
            gdzie = np.flatnonzero(df[kol_druzyny].to_numpy() == druzyna)
            if gdzie.size == 0:
                continue
            licz = np.searchsorted(gd, kol_daty[gdzie], side="left")
            sr_z, n = _srednie_kroczace(zdob, licz, okno, wagi)
            sr_s, _ = _srednie_kroczace(strac, licz, okno, wagi)
            atak[gdzie], obr[gdzie], n_uz[gdzie] = sr_z, sr_s, n
        out[f"atak_{strona}"] = atak
        out[f"obrona_{strona}"] = obr
        out[f"n_{strona}"] = n_uz
    return out


def liczniki_druzyn(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Ile meczów KAŻDA z drużyn rozegrała u siebie i na wyjeździe PRZED meczem.

    Produkcja przepuszcza drużynę przy `len(dom) + len(wyj) >= 6` — łącznie,
    nie na każdej stronie z osobna. Bez tych czterech liczb nie da się odtworzyć
    tego progu, a jego zaostrzenie wycięłoby z próby dokładnie te mecze, o które
    estymator ociera się najczęściej: początek sezonu i beniaminków.
    """
    daty = df["date"].to_numpy()
    n = len(df)
    out = {k: np.zeros(n) for k in ("n_dom_g", "n_wyj_g", "n_dom_a", "n_wyj_a")}
    dom_map = {t: g["date"].to_numpy() for t, g in df.groupby("home", sort=False)}
    wyj_map = {t: g["date"].to_numpy() for t, g in df.groupby("away", sort=False)}
    pusty = np.empty(0, dtype=daty.dtype)
    for kol, (kl_dom, kl_wyj) in (("home", ("n_dom_g", "n_wyj_g")),
                                  ("away", ("n_dom_a", "n_wyj_a"))):
        wart = df[kol].to_numpy()
        for druzyna in pd.unique(wart):
            gdzie = np.flatnonzero(wart == druzyna)
            out[kl_dom][gdzie] = np.searchsorted(
                dom_map.get(druzyna, pusty), daty[gdzie], side="left")
            out[kl_wyj][gdzie] = np.searchsorted(
                wyj_map.get(druzyna, pusty), daty[gdzie], side="left")
    return out


def _na_ilorazy(t: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Surowe średnie → ratingi wobec ligi (parytet z `_tabela_ratingow`)."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return {
            "atak_dom": t["atak_dom"] / t["sr_dom"],
            "obrona_dom": t["obrona_dom"] / t["sr_wyj"],
            "atak_wyj": t["atak_wyj"] / t["sr_wyj"],
            "obrona_wyj": t["obrona_wyj"] / t["sr_dom"],
        }


def ratingi_ligi(df: pd.DataFrame, okno: int, polowicz: float) -> dict | None:
    """Pełny zestaw ratingów jednej ligi: gole + domieszka strzałów, jak prod.

    Zwraca słownik tablic równoległych do wierszy `df` (posortowanego po dacie).
    """
    wagi = wagi_okna(okno, polowicz)
    z_goli = _tabela_kolumn(df, "hg", "ag", okno, wagi)
    if z_goli is None:
        return None
    r = _na_ilorazy(z_goli)

    if WAGA_STRZALOW > 0 and {"hst", "ast"} <= set(df.columns):
        ze_strzalow = _tabela_kolumn(df, "hst", "ast", okno, wagi)
        if ze_strzalow is not None:
            rs = _na_ilorazy(ze_strzalow)
            for k in r:
                # Drużyna bez strzałów ZOSTAJE na ratingu golowym — tak samo
                # jak `form._domieszaj` pomija drużynę nieobecną w tabeli.
                r[k] = np.where(np.isnan(rs[k]), r[k],
                                WAGA_STRZALOW * rs[k] + (1 - WAGA_STRZALOW) * r[k])

    r["sr_dom"], r["sr_wyj"] = z_goli["sr_dom"], z_goli["sr_wyj"]
    # Liczba meczów W OKNIE — to ona karmi ściąganie do średniej, bo rating
    # z sześciu meczów i z trzydziestu nie zasługuje na tę samą wiarę.
    r["n_gosp"], r["n_gosc"] = z_goli["n_dom"], z_goli["n_wyj"]

    # Drużyna bez ani jednego meczu na tej stronie boiska dostaje rating 1.0 —
    # parytet z `form._tabela_ratingow` (`if len(dom) else 1.0`).
    lic = liczniki_druzyn(df)
    r.update(lic)
    for kolumny, licznik in ((("atak_dom", "obrona_dom"), lic["n_dom_g"]),
                             (("atak_wyj", "obrona_wyj"), lic["n_wyj_a"])):
        for k in kolumny:
            r[k] = np.where(licznik == 0, 1.0, r[k])
    return r


# ─────────────────────────────  λ i metryki  ─────────────────────────────────

def lambdy(r: dict, k: float, skala_g: float, skala_a: float) -> tuple[np.ndarray, np.ndarray]:
    """(λ_gospodarz, λ_gość) z ratingów, przy zadanych ściąganiu i skali."""
    def sciagnij(rating: np.ndarray, n: np.ndarray) -> np.ndarray:
        if k <= 0:
            return rating
        return (n * rating + k) / (n + k)

    ad = sciagnij(r["atak_dom"], r["n_gosp"])
    ow = sciagnij(r["obrona_wyj"], r["n_gosc"])
    aw = sciagnij(r["atak_wyj"], r["n_gosc"])
    od = sciagnij(r["obrona_dom"], r["n_gosp"])
    lg = np.clip(skala_g * ad * ow * r["sr_dom"], 0.05, 12.0)
    la = np.clip(skala_a * aw * od * r["sr_wyj"], 0.05, 12.0)
    return lg, la


def logwiar_goli(lg: np.ndarray, la: np.ndarray,
                 hg: np.ndarray, ag: np.ndarray) -> np.ndarray:
    """Log-wiarygodność Poissona faktycznych goli, per mecz (obie strony)."""
    return _poisson.logpmf(hg, lg) + _poisson.logpmf(ag, la)


def p_1x2(lg: np.ndarray, la: np.ndarray) -> np.ndarray:
    """(n, 3) prawdopodobieństw 1X2 z macierzy Poissona (rho=0, jak produkcja).

    `USE_DC_TAU` jest na produkcji wyłączone, więc macierz to czysty iloczyn
    zewnętrzny obciety na `MAX_GOLI` i renormalizowany.
    """
    h = np.arange(MAX_GOLI)
    pg = _poisson.pmf(h[None, :], lg[:, None])
    pa = _poisson.pmf(h[None, :], la[:, None])
    pg /= pg.sum(axis=1, keepdims=True)
    pa /= pa.sum(axis=1, keepdims=True)
    kum_a = np.cumsum(pa, axis=1)
    # p(gosp) = Σ_i p_g(i) * P(a < i);  p(remis) = Σ_i p_g(i) * p_a(i)
    p_mniej = np.concatenate([np.zeros((len(lg), 1)), kum_a[:, :-1]], axis=1)
    pw = (pg * p_mniej).sum(axis=1)
    pr = (pg * pa).sum(axis=1)
    pp = 1.0 - pw - pr
    return np.stack([pw, pr, pp], axis=1)


def brier_z_p(p: np.ndarray, wynik: np.ndarray) -> np.ndarray:
    """Brier wieloklasowy per mecz z gotowych prawdopodobieństw."""
    y = np.zeros_like(p)
    y[np.arange(len(wynik)), wynik] = 1.0
    return ((p - y) ** 2).sum(axis=1)


def brier_1x2(lg: np.ndarray, la: np.ndarray, wynik: np.ndarray) -> np.ndarray:
    """Brier 1X2 wprost z λ — skrót na `brier_z_p(p_1x2(...))`."""
    return brier_z_p(p_1x2(lg, la), wynik)


def devig(o_h: np.ndarray, o_d: np.ndarray, o_a: np.ndarray) -> np.ndarray:
    """(n, 3) prawdopodobieństw z kursów, metodą proporcjonalną — jak produkcja.

    Kurs <= 1.0 albo brak daje wiersz NaN; taki mecz wypada z porównania
    mieszanek, w obu ramionach naraz.
    """
    o = np.stack([o_h, o_d, o_a], axis=1).astype(float)
    zle = ~np.isfinite(o).all(axis=1) | (o <= 1.0).any(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        inv = 1.0 / o
        p = inv / inv.sum(axis=1, keepdims=True)
    p[zle] = np.nan
    return p


def sparowana(d: np.ndarray) -> tuple[float, float, float]:
    """(średnia, SE, z) sparowanej różnicy."""
    d = d[np.isfinite(d)]
    if len(d) < 2:
        return float("nan"), float("nan"), float("nan")
    sr = float(d.mean())
    se = float(d.std(ddof=1) / np.sqrt(len(d)))
    return sr, se, (sr / se if se > 0 else float("nan"))


# ─────────────────────────────  przebieg  ────────────────────────────────────

def zbierz(df: pd.DataFrame, okna, polowicze) -> dict:
    """Ratingi dla całej próby, dla każdej kombinacji (okno, połowicz).

    Liczone raz; dopasowanie `k`/skali to potem już tylko arytmetyka na
    gotowych tablicach.
    """
    zestawy: dict[tuple, list] = {(o, p): [] for o in okna for p in polowicze}
    meta = []
    for liga, gl in df.groupby("league", sort=True):
        gl = gl.sort_values("date", kind="stable").reset_index(drop=True)
        if len(gl) < 50:
            continue
        for o in okna:
            for p in polowicze:
                r = ratingi_ligi(gl, o, p)
                zestawy[(o, p)].append(r if r is not None else None)
        meta.append((liga, gl))
    return {"zestawy": zestawy, "meta": meta}


def _sklej(zestawy_lista, meta, klucze) -> dict:
    """Skleja per-ligowe tablice w jedną, dorzucając gole/wynik/ligę/datę."""
    out = {k: [] for k in klucze}
    out.update({"hg": [], "ag": [], "wynik": [], "league": [], "date": []})
    out.update({k: [] for k in KOL_KURSOW})
    for r, (liga, gl) in zip(zestawy_lista, meta):
        if r is None:
            continue
        for k in klucze:
            out[k].append(r[k])
        for k in KOL_KURSOW:
            out[k].append(gl[k].to_numpy(float) if k in gl.columns
                          else np.full(len(gl), np.nan))
        out["hg"].append(gl["hg"].to_numpy(float))
        out["ag"].append(gl["ag"].to_numpy(float))
        wyn = np.where(gl["hg"] > gl["ag"], 0, np.where(gl["hg"] == gl["ag"], 1, 2))
        out["wynik"].append(wyn)
        out["league"].append(np.full(len(gl), liga, dtype=object))
        out["date"].append(gl["date"].to_numpy())
    return {k: np.concatenate(v) for k, v in out.items()}


# 1X2 Pinnacle karmi aneks o mieszance; Over/Under jest niesione OBOK, bo
# pyta o nie `lambda_kto_lepszy.py` (pomiar C) i bez tego cicho go pomija.
KOL_KURSOW = ("odds_h_pinn", "odds_d_pinn", "odds_a_pinn",
              "odds_over25_pinn", "odds_under25_pinn")

KLUCZE = ("atak_dom", "obrona_dom", "atak_wyj", "obrona_wyj",
          "sr_dom", "sr_wyj", "n_gosp", "n_gosc",
          "n_dom_g", "n_wyj_g", "n_dom_a", "n_wyj_a")


def maska_uzywalnych(d: dict) -> np.ndarray:
    """Mecze, które produkcja realnie policzyłaby ścieżką ligową.

    Warunek `MIN_MECZOW_LIGOWYCH` na obu drużynach + komplet ratingów. Poniżej
    tego progu `_baza_ligowa` zwraca None i produkcja spada do starej ścieżki —
    taki mecz nie należy do tego pomiaru w ŻADNYM ramieniu.
    """
    ok = np.isfinite(d["sr_dom"]) & np.isfinite(d["sr_wyj"])
    for k in ("atak_dom", "obrona_dom", "atak_wyj", "obrona_wyj"):
        ok &= np.isfinite(d[k])
    ok &= (d["n_dom_g"] + d["n_wyj_g"]) >= MIN_MECZOW_LIGOWYCH
    ok &= (d["n_dom_a"] + d["n_wyj_a"]) >= MIN_MECZOW_LIGOWYCH
    ok &= np.isfinite(d["hg"]) & np.isfinite(d["ag"])
    return ok


def dopasuj(d: dict, tren: np.ndarray, tylko_skala: bool) -> dict:
    """Dopasowuje (k, skala_g, skala_a) na treningu, maksymalizując log-wiar. goli."""
    sub = {k: v[tren] for k, v in d.items()}

    def cel(x: np.ndarray) -> float:
        k = 0.0 if tylko_skala else float(np.clip(x[0], 0.0, 40.0))
        sg = float(np.clip(x[1], 0.7, 1.3))
        sa = float(np.clip(x[2], 0.7, 1.3))
        lg, la = lambdy(sub, k, sg, sa)
        ll = logwiar_goli(lg, la, sub["hg"], sub["ag"])
        return -float(np.mean(ll[np.isfinite(ll)]))

    start = np.array([0.0 if tylko_skala else 5.0, 1.0, 1.0])
    res = minimize(cel, start, method="Nelder-Mead",
                   options={"xatol": 1e-4, "fatol": 1e-7, "maxiter": 600})
    x = res.x
    return {"k": 0.0 if tylko_skala else float(np.clip(x[0], 0.0, 40.0)),
            "skala_g": float(np.clip(x[1], 0.7, 1.3)),
            "skala_a": float(np.clip(x[2], 0.7, 1.3)),
            "ll_tren": -float(res.fun)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--holdout", default=PODZIAL)
    ap.add_argument("--ligi", default=None, help="po przecinku; domyslnie wszystkie")
    ap.add_argument("--wynik", default=None, help="sciezka JSON z wynikiem")
    args = ap.parse_args()

    from footstats.data.historical_loader import load_cached

    df = load_cached()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "hg", "ag"])
    if args.ligi:
        df = df[df["league"].isin([x.strip() for x in args.ligi.split(",")])]
    granica = pd.Timestamp(args.holdout)
    print(f"Wczytane: {len(df)} meczow, {df['league'].nunique()} lig, "
          f"podzial {args.holdout}", flush=True)

    print("Licze ratingi dla siatki (okno x polowicz)...", flush=True)
    zb = zbierz(df, OKNA, POLOWICZE)
    meta = zb["meta"]

    # ── produkcja jako punkt odniesienia ──────────────────────────────────
    d_prod = _sklej(zb["zestawy"][(PROD["okno"], PROD["polowicz"])], meta, KLUCZE)
    uz = maska_uzywalnych(d_prod)
    tren = uz & (d_prod["date"] < granica)
    hold = uz & (d_prod["date"] >= granica)
    print(f"Uzywalnych: {int(uz.sum())}  (trening {int(tren.sum())}, "
          f"holdout {int(hold.sum())})", flush=True)

    lg_p, la_p = lambdy(d_prod, PROD["k"], PROD["skala_g"], PROD["skala_a"])
    ll_p = logwiar_goli(lg_p, la_p, d_prod["hg"], d_prod["ag"])
    br_p = brier_1x2(lg_p[hold], la_p[hold], d_prod["wynik"][hold])

    print(f"\nPRODUKCJA na holdoucie:  log-wiar {ll_p[hold].mean():.5f}   "
          f"Brier {br_p.mean():.5f}")
    print(f"  srednie lambda {lg_p[hold].mean():.4f} / {la_p[hold].mean():.4f}"
          f"   faktyczne {d_prod['hg'][hold].mean():.4f} / "
          f"{d_prod['ag'][hold].mean():.4f}")

    # ── siatka: wybor (okno, polowicz) WYLACZNIE po treningu ──────────────
    print("\nDopasowanie na TRENINGU (holdout nietkniety):", flush=True)
    najlepszy = None
    siatka = []
    for (o, p), lista in zb["zestawy"].items():
        d = _sklej(lista, meta, KLUCZE)
        m = maska_uzywalnych(d)
        t = m & (d["date"] < granica)
        if t.sum() < 1000:
            continue
        fit = dopasuj(d, t, tylko_skala=False)
        siatka.append({"okno": o, "polowicz": (None if not np.isfinite(p) else p), **fit})
        print(f"  okno {o:3d}  polowicz {'inf' if not np.isfinite(p) else f'{p:.0f}':>4}"
              f"  ->  k={fit['k']:.2f}  skala {fit['skala_g']:.4f}/{fit['skala_a']:.4f}"
              f"  ll_tren {fit['ll_tren']:.5f}", flush=True)
        if najlepszy is None or fit["ll_tren"] > najlepszy["fit"]["ll_tren"]:
            najlepszy = {"okno": o, "polowicz": p, "fit": fit, "dane": d, "maska": m}

    if najlepszy is None:
        raise SystemExit("Zero kombinacji z wystarczajaca proba treningowa.")

    # ── ramie SAMA SKALA (regula 4) ───────────────────────────────────────
    fit_skala = dopasuj(d_prod, tren, tylko_skala=True)

    # ── HOLDOUT ───────────────────────────────────────────────────────────
    d_n = najlepszy["dane"]
    hold_n = najlepszy["maska"] & (d_n["date"] >= granica)
    f = najlepszy["fit"]
    lg_n, la_n = lambdy(d_n, f["k"], f["skala_g"], f["skala_a"])
    ll_n = logwiar_goli(lg_n, la_n, d_n["hg"], d_n["ag"])
    br_n = brier_1x2(lg_n[hold_n], la_n[hold_n], d_n["wynik"][hold_n])

    lg_s, la_s = lambdy(d_prod, 0.0, fit_skala["skala_g"], fit_skala["skala_a"])
    ll_s = logwiar_goli(lg_s, la_s, d_prod["hg"], d_prod["ag"])
    br_s = brier_1x2(lg_s[hold], la_s[hold], d_prod["wynik"][hold])

    kreska = "=" * 92
    print(f"\n{kreska}\n  HOLDOUT — sparowane roznice wobec produkcji\n{kreska}")

    # Ramie pelne moze miec inna maske (inne okno -> inne progi), wiec
    # sparowanie idzie po WSPOLNYCH meczach: te same (liga, data, wynik).
    wspolne = hold & hold_n
    d_ll_pelne = (ll_n - ll_p)[wspolne]
    sr, se, z = sparowana(d_ll_pelne)
    pol_txt = ("inf" if not np.isfinite(najlepszy["polowicz"])
               else f"{najlepszy['polowicz']:.0f}")
    print(f"\n  PELNE DOPASOWANIE  okno {najlepszy['okno']}  polowicz {pol_txt}"
          f"  k={f['k']:.2f}  skala {f['skala_g']:.4f}/{f['skala_a']:.4f}")
    print(f"    log-wiar goli  {ll_n[hold_n].mean():.5f}  vs prod "
          f"{ll_p[hold].mean():.5f}")
    print(f"    sparowana roznica {sr:+.5f}  SE {se:.5f}  z={z:+.2f}  (n={int(wspolne.sum())})")

    br_p_w = brier_1x2(lg_p[wspolne], la_p[wspolne], d_prod["wynik"][wspolne])
    br_n_w = brier_1x2(lg_n[wspolne], la_n[wspolne], d_n["wynik"][wspolne])
    sr_b, se_b, z_b = sparowana(br_p_w - br_n_w)   # dodatnie = my lepsi
    print(f"    Brier 1X2  {br_n[np.isfinite(br_n)].mean():.5f}  vs prod "
          f"{br_p[np.isfinite(br_p)].mean():.5f}")
    print(f"    sparowana roznica (prod - nowe) {sr_b:+.5f}  SE {se_b:.5f}  z={z_b:+.2f}")

    sr_s, se_s, z_s = sparowana((ll_s - ll_p)[hold])
    sr_bs, se_bs, z_bs = sparowana((br_p - br_s))
    print(f"\n  SAMA SKALA  skala {fit_skala['skala_g']:.4f}/{fit_skala['skala_a']:.4f}"
          f"  (okno 30, plaskie wagi, bez sciagania)")
    print(f"    log-wiar goli  {ll_s[hold].mean():.5f}")
    print(f"    sparowana roznica {sr_s:+.5f}  SE {se_s:.5f}  z={z_s:+.2f}")
    print(f"    Brier 1X2  {br_s.mean():.5f}   sparowana (prod - skala) "
          f"{sr_bs:+.5f}  SE {se_bs:.5f}  z={z_bs:+.2f}")
    print(f"    srednie lambda {lg_s[hold].mean():.4f} / {la_s[hold].mean():.4f}")

    udzial = (sr_s / sr) if (np.isfinite(sr) and sr > 0) else float("nan")
    print(f"\n  Udzial samej skali w zysku pelnego dopasowania: {udzial:.1%}")

    # ── rozklad na czynniki (POST-HOC, opisowy) ───────────────────────────
    # Regula 4 pytala tylko o skale i odpowiedz brzmi „nic". Zostaje pytanie,
    # ktore z DWOCH pozostalych zmian niesie zysk — a od tego zalezy, czy
    # produkcja dostaje jedna nowa stala, czy trzy. To jest ROZKLAD OPISOWY
    # dopisany PO zobaczeniu wyniku; nie ma i nie moze miec mocy rozstrzygania.
    print(f"\n{kreska}\n  ROZKLAD NA CZYNNIKI — POST-HOC, bez mocy decyzyjnej\n{kreska}")
    fit_k = dopasuj(d_prod, tren, tylko_skala=False)
    lg_k, la_k = lambdy(d_prod, fit_k["k"], fit_k["skala_g"], fit_k["skala_a"])
    ll_k = logwiar_goli(lg_k, la_k, d_prod["hg"], d_prod["ag"])
    br_k = brier_1x2(lg_k[wspolne], la_k[wspolne], d_prod["wynik"][wspolne])

    lg_o, la_o = lambdy(d_n, 0.0, 1.0, 1.0)      # samo okno+zanik, bez sciagania
    ll_o = logwiar_goli(lg_o, la_o, d_n["hg"], d_n["ag"])
    br_o = brier_1x2(lg_o[wspolne], la_o[wspolne], d_n["wynik"][wspolne])

    ramiona = [
        ("samo SCIAGANIE (okno 30, plaskie)", ll_k, br_k, f"k={fit_k['k']:.2f}"),
        ("samo OKNO+ZANIK (bez sciagania)", ll_o, br_o,
         f"okno {najlepszy['okno']}, polowicz {pol_txt}"),
        ("OBA (pelne dopasowanie)", ll_n, br_n_w, "j.w. + k"),
    ]
    for nazwa, ll_x, br_x, opis in ramiona:
        s_x, _, z_x = sparowana((ll_x - ll_p)[wspolne])
        s_bx, _, z_bx = sparowana(br_p_w - br_x)
        czesc = (s_x / sr) if (np.isfinite(sr) and sr > 0) else float("nan")
        print(f"  {nazwa:36s} {opis:26s}  ll {s_x:+.5f} (z={z_x:+6.2f})"
              f"  {czesc:6.1%}   Brier {s_bx:+.5f} (z={z_bx:+6.2f})")

    # ── ANEKS: czy zysk przezywa zmieszanie z cena ────────────────────────
    print(f"\n{kreska}\n  ANEKS — Brier mieszanki (1-w)*model + w*rynek, holdout\n{kreska}")
    p_rynek = devig(d_prod["odds_h_pinn"], d_prod["odds_d_pinn"], d_prod["odds_a_pinn"])
    ma_cene = np.isfinite(p_rynek).all(axis=1)
    mix_maska = wspolne & ma_cene
    print(f"  Meczow z zamknieciem Pinnacle: {int(mix_maska.sum())} "
          f"z {int(wspolne.sum())} ({mix_maska.sum() / max(wspolne.sum(), 1):.1%})")
    p_prod_h = p_1x2(lg_p[mix_maska], la_p[mix_maska])
    p_now_h = p_1x2(lg_n[mix_maska], la_n[mix_maska])
    p_ryn_h = p_rynek[mix_maska]
    wyn_h = d_prod["wynik"][mix_maska]
    aneks = []
    for w in (0.0, 0.30, 0.70, 1.0):
        b_pr = brier_z_p((1 - w) * p_prod_h + w * p_ryn_h, wyn_h)
        b_no = brier_z_p((1 - w) * p_now_h + w * p_ryn_h, wyn_h)
        s_w, se_w, z_w = sparowana(b_pr - b_no)
        aneks.append({"w": w, "brier_prod": float(b_pr.mean()),
                      "brier_nowe": float(b_no.mean()),
                      "d": s_w, "se": se_w, "z": z_w})
        print(f"  w={w:.2f}   prod {b_pr.mean():.5f}   nowe {b_no.mean():.5f}"
              f"   roznica {s_w:+.5f}  SE {se_w:.5f}  z={z_w:+.2f}")
    z_prod = next(a["z"] for a in aneks if a["w"] == 0.70)
    aneks_ok = np.isfinite(z_prod) and z_prod >= 2.0
    print(f"\n  REGULA ANEKSU (w=0.70, waga API): z={z_prod:+.2f}  ->  "
          f"{'wdrozenie uzasadnione' if aneks_ok else 'ZOSTAJE POMIAREM, prod bez zmian'}")

    # ── replikacja po ligach (regula 3) ───────────────────────────────────
    print(f"\n{kreska}\n  REPLIKACJA PO LIGACH (holdout, n >= {MIN_LIGA_HOLDOUT})\n{kreska}")
    ligi_plus = ligi_all = 0
    per_liga = []
    for liga in sorted(set(d_prod["league"][hold])):
        m = wspolne & (d_prod["league"] == liga)
        if m.sum() < MIN_LIGA_HOLDOUT:
            continue
        s_l, _, z_l = sparowana((ll_n - ll_p)[m])
        s_sk, _, z_sk = sparowana((ll_s - ll_p)[m])
        ligi_all += 1
        ligi_plus += int(s_l > 0)
        per_liga.append({"liga": liga, "n": int(m.sum()), "d_pelne": s_l,
                         "z_pelne": z_l, "d_skala": s_sk, "z_skala": z_sk})
        print(f"  {liga:28s} n={int(m.sum()):5d}   pelne {s_l:+.5f} (z={z_l:+5.1f})"
              f"   skala {s_sk:+.5f} (z={z_sk:+5.1f})")
    print(f"\n  Lig z dodatnia roznica: {ligi_plus}/{ligi_all}"
          f"  (prog reguly 3: {int(np.ceil(2 * ligi_all / 3))})")

    # ── reguła decyzyjna ──────────────────────────────────────────────────
    print(f"\n{kreska}\n  REGULA DECYZYJNA (zamrozona przed przebiegiem)\n{kreska}")
    r1 = np.isfinite(z) and z >= 3.0
    r2 = not (np.isfinite(z_b) and z_b <= -2.0)
    r3 = ligi_all > 0 and ligi_plus >= np.ceil(2 * ligi_all / 3)
    print(f"  1. log-wiar goli z >= +3        : {'TAK' if r1 else 'NIE'}  (z={z:+.2f})")
    print(f"  2. Brier nie gorszy (z > -2)    : {'TAK' if r2 else 'NIE'}  (z={z_b:+.2f})")
    print(f"  3. >= 2/3 lig dodatnie          : {'TAK' if r3 else 'NIE'}  "
          f"({ligi_plus}/{ligi_all})")
    print(f"  A. mieszanka w=0.70 z >= +2      : {'TAK' if aneks_ok else 'NIE'}  "
          f"(z={z_prod:+.2f})")
    if r1 and r2 and r3 and not aneks_ok:
        print("\n  WNIOSEK: estymator jest lepszy w izolacji, ale zysk NIE przezywa\n"
              "  zmieszania z cena przy wadze, ktora API realnie ma. Zostaje pomiarem.")
    elif r1 and r2 and r3:
        if np.isfinite(udzial) and udzial >= 0.80:
            print("\n  WNIOSEK: zmiana potwierdzona, ale niesie ja SAMA SKALA "
                  f"({udzial:.0%}).\n  Rekomendacja: dwie liczby "
                  f"({fit_skala['skala_g']:.4f} / {fit_skala['skala_a']:.4f}), "
                  "bez przebudowy estymatora.")
        else:
            print("\n  WNIOSEK: pelne dopasowanie potwierdzone i sama skala go NIE "
                  "wyczerpuje.\n  Rekomendacja: okno/zanik/sciaganie tez wchodza.")
    else:
        print("\n  WNIOSEK: warunki NIE spelnione — zero zmian w produkcji.")

    if args.wynik:
        Path(args.wynik).write_text(json.dumps({
            "holdout": args.holdout,
            "n_holdout": int(wspolne.sum()),
            "produkcja": {"ll": float(ll_p[hold].mean()), "brier": float(br_p.mean()),
                          "lambda_g": float(lg_p[hold].mean()),
                          "lambda_a": float(la_p[hold].mean())},
            "faktyczne": {"hg": float(d_prod["hg"][hold].mean()),
                          "ag": float(d_prod["ag"][hold].mean())},
            "pelne": {"okno": najlepszy["okno"],
                      "polowicz": (None if not np.isfinite(najlepszy["polowicz"])
                                   else najlepszy["polowicz"]),
                      **{k: v for k, v in f.items()},
                      "d_ll": sr, "se_ll": se, "z_ll": z,
                      "d_brier": sr_b, "z_brier": z_b},
            "sama_skala": {**fit_skala, "d_ll": sr_s, "z_ll": z_s,
                           "d_brier": sr_bs, "z_brier": z_bs,
                           "udzial": udzial},
            "aneks_mieszanka": aneks,
            "aneks_ok": bool(aneks_ok),
            "siatka": siatka,
            "per_liga": per_liga,
            "ligi_plus": ligi_plus, "ligi_all": ligi_all,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nZapisane: {args.wynik}")


if __name__ == "__main__":
    main()

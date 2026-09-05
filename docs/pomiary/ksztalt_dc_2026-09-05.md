# Korekta τ Dixona-Colesa w głównej ścieżce — wynik, 2026-09-05

Pre-rejestracja: `scripts/ksztalt_dc.py` (commit `4e0591ab1`).
Wynik liczbowy: `docs/pomiary/ksztalt_dc_2026-09-05.json`.

## Stan przed zmianą

Główna ścieżka `poisson.predict_match` → `poisson._macierz` **nie miała korekty
τ w ogóle** — słowo `rho` nie występowało w tym pliku. `USE_DC_TAU` (0) i
`DC_RHO` (−0.13) sięgały wyłącznie `poisson_bayesian`, które `quick_picks`
blenduje 50/50 pod `USE_DIXON_COLES=1`. Czyli produkcja mieszała pół na pół
z „ramieniem Dixona-Colesa", które przy `USE_DC_TAU=0` również liczyło `rho=0`.

## POMIAR 0 — remisy są zaniżone

```
gospodarz   przewidywane 0.4408   faktyczne 0.4399   roznica +0.0009
remis       przewidywane 0.2484   faktyczne 0.2620   roznica -0.0136
gosc        przewidywane 0.3108   faktyczne 0.2981   roznica +0.0127
Over 2.5    przewidywane 0.4819   faktyczne 0.5010   roznica -0.0191
```

Zaniżamy remisy o 1.36 pp i o tyleż zawyżamy wygraną gościa. To jest dokładnie
ten błąd, po który Dixon i Coles wymyślili τ.

## POMIAR 1 — ρ dopasowane, holdout

```
rho dopasowane na treningu (<2024): -0.0400
   (produkcja 0.0; wpisane z reki w repo: -0.13 i -0.05)

Brier 1X2 na holdoucie (n=31 628):  rho=0 0.62077   rho=-0.04 0.62044
   sparowana roznica +0.00032  SE 0.00007  z=+4.76
```

Dopasowanie szło na log-wiarygodności **faktycznych wyników meczów**, nie na
Brierze — Brier jest metryką oceny i strojenie pod niego byłoby strojeniem pod
własny egzamin.

## POMIAR 2 — strażnik

```
log-wiarygodnosc wyniku meczu:  rho=0 -2.93569   rho=-0.04 -2.93510
   sparowana roznica +0.00059  SE 0.00018  z=+3.32
```

## Replikacja i reguła

31 lig na 38 dodatnich (próg 26). Wszystkie cztery zamrożone warunki spełnione.

## Aneks — i tu uczciwie o skali

```
Brier mieszanki, n=23 070 z zamknieciem Pinnacle

  CZYSTY    w=0.00  +0.00033 (z=+4.21)     w=0.30  +0.00018 (z=+3.22)
            w=0.70  +0.00004 (z=+1.88)     w=1.00   0
  OSTROZNY  w=0.00  +0.00020 (z=+4.98)     w=0.30  +0.00010 (z=+3.75)
            w=0.70  +0.00003 (z=+2.11)     w=1.00   0
```

Wariant OSTROŻNY (`0.5·nowe + 0.5·stare`) przybliża blend z niezmienionym
ramieniem bayesian. Przy w=0.70 — wadze, którą API realnie ma — zysk to
**+0.00003 Briera**. Reguła wymagała z≥+2 i dostała z=+2.11, więc formalnie
przechodzi. Ale **to jest liczba, której nikt nie zobaczy**.

**Wada moich własnych reguł, którą trzeba nazwać.** Progi na `z` mierzą
PRECYZJĘ, nie WAŻNOŚĆ. Przy n=23 070 i zmianie deterministycznej o małej
wariancji z=+2 wychodzi przy efekcie rzędu 1e-5. Dla porównania: dopasowanie
estymatora z tego samego dnia dawało przy w=0.70 **+0.00003** i **nie przeszło**
progu (z=+0.17) — praktycznie ten sam efekt, inna wariancja. Przyszłe reguły
powinny mieć **minimalny rozmiar efektu**, nie tylko próg istotności.

Wdrożone mimo znikomej skali, bo: jest darmowe, ma 28 testów, zgadza się
z kierunkiem zmierzonego błędu kalibracji i poprawia KAŻDĄ zmierzoną wielkość.
Nie dlatego, że cokolwiek zmienia w wynikach użytkownika.

## Czego τ NIE robi — dowód, nie przypuszczenie

Poprawki czterech komórek sumują się tożsamościowo do zera:

```
d(0,0) = -K*λ*μ*ρ    d(0,1) = +K*λ*μ*ρ
d(1,0) = +K*λ*μ*ρ    d(1,1) = -K*λ*μ*ρ      K = e^(-λ-μ)
```

Wszystkie cztery mają sumę goli ≤ 2, więc licznik Over 2.5 jest nietknięty,
a mianownik nie drgnie. **Over 2.5 i BTTS są od ρ całkowicie niezależne** —
zmierzone: max |różnica| = 2.2e-16.

Wniosek, którego to nie pozwala postawić: niedobór 7.8 pp na Over 2.5
z `lambda_kto_lepszy.py` **nie jest naprawialny korektą τ**. Tamten pomiar
odzyskiwał λ, a przy `rho=-0.05` wychodziły λ WYŻSZE i to one dawały więcej
goli — nie τ. Pierwsza wersja tej pre-rejestracji zakładała coś przeciwnego
i została poprawiona przed jakimkolwiek przebiegiem, bo złapał to test.

## Drugi rozjazd w repo, znaleziony przy okazji

`poisson.predict_match` woła `_macierz(λ, μ, MAX_GOLE + 1)` → **9 komórek**,
a `poisson_bayesian.macierz_dixon_coles` liczy `arange(MAX_GOLE)` → **8**.
Dwie macierze produkcyjne obcinają w innym miejscu. Różnica sięga **2.6e-3**
w p(1) przy wysokich λ — czyli **więcej niż efekt mierzony tutaj**.

Mój harness liczył 8 komórek i tym samym mierzył nie ten model, co produkcja.
Poprawione (`MAX_GOLI = 9`), wszystko przeliczone od nowa; decyzja się nie
zmieniła. Rozjazd między dwiema macierzami produkcyjnymi **zostaje** — pilnuje
go teraz `test_dwie_macierze_produkcyjne_obcinaja_inaczej`, żeby nikt nie
przeoczył go po raz drugi.

## Wdrożenie

`config.DC_RHO_CLASSIC = -0.04` (env-owalne, `=0` wraca do zachowania sprzed
05.09). `_macierz` przyjmuje `rho` jako czwarty argument — **część klucza
`lru_cache`**, bo inaczej pierwsze wywołanie zatrułoby wszystkie następne.

## Zarzut ze starego komentarza — sprawdzony

`.env.example` przy `USE_DC_TAU=0` twierdził: „rho doprowadzające średni remis
do realnych 25% obniża trafność" (pomiar 09.08.2026 na **600 meczach**).
Nie mierzyłem trafności, więc sprawdziłem osobno na holdoucie (n=31 628):

```
trafnosc typu:  rho=0  0.4793     rho=-0.04  0.4791
sparowana roznica -0.00019  SE 0.00024  z=-0.79
typow zmienionych: 82 z 31 628
```

Nie do odróżnienia od zera. Tamten zarzut dotyczył ρ dużo mocniejszego —
takiego, który dociąga średni remis do 25%; `rho=-0.04` podnosi go z 0.2484
do ~0.2590 i prawie nie rusza argmaxu.

Przy okazji, liczba niezależna od τ i warta zapamiętania:

```
udzial typu X:  rho=0  0.0045     rho=-0.04  0.0071     faktycznie  0.2637
```

Model typuje remis w **0.45% meczów**, a remisy padają w 26.4%. To jest ta sama
stronniczość 2-way, którą zmierzyliśmy 17.08 — argmax po surowym p praktycznie
nigdy nie wskaże wyjścia o najmniejszej masie. τ tego nie rusza i nie miało.

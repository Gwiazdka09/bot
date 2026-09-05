# Czyje λ lepiej przewiduje gole — przeliczenie na właściwej macierzy, 2026-09-05

Pre-rejestracja: `scripts/lambda_kto_lepszy.py` (commit `77b71215b`).
Wynik liczbowy: `docs/pomiary/lambda_kto_lepszy_2026-09-05.json`.

Powód: pomiar 1 z 04.09 miał **dwie** wady narzędzia, obie w odzyskiwaniu λ.
Ta liczba (z=−23.65) była podstawą całej pracy nad estymatorem, więc musiała
zostać przeliczona, zanim cokolwiek dalej z niej wyniknie.

## Wynik: teza PRZEŻYŁA i wzmocniła się

```
POMIAR A — sparowana log-wiarygodnosc faktycznych goli, n=125 497

  model  -2.94244      rynek  -2.87523
  roznica (model - rynek)  -0.06721   SE 0.00139   z=-48.38

  04.09, na zlej macierzy: -0.09404  SE 0.00398  z=-23.65
```

**Wszystkie 39 lig ujemne**, od −0.020 (GER-Bundesliga, z=−2.4) do −0.227
(ARG-Copa De La Liga, z=−7.4). Efekt jest o jedną trzecią mniejszy, niż
mówił skażony pomiar, ale próba jest sześciokrotnie większa i kierunek nie
budzi wątpliwości.

> Oczekiwania bramkowe rynku są lepsze od naszych. Praca w estymator sił
> drużyn ma sens — wczorajszy błąd narzędzia nie unieważnił kierunku.

## POMIAR B — i tu jest niespodzianka

```
faktyczne gole   1.4848 / 1.1764
lambda modelu    1.4697 / 1.1647   blad -0.0152 / -0.0117
lambda rynku     1.3389 / 1.0323   blad -0.1459 / -0.1442
srednia |roznica| miedzy nami a rynkiem:  gospodarz 0.2975   gosc 0.2611
```

Nasze λ jest praktycznie **nieobciążone**. Rynkowe (po rzucie na Poissona)
jest zaniżone o ~10%. A mimo to rynkowe wygrywa w log-wiarygodności.

Rachunek, ile kosztuje samo obciążenie poziomu: przy λ zaniżonym o 10% strata
wynosi λ·(ln(1/0.9) − 0.1) ≈ 0.008 na stronę, czyli ~0.016 na mecz. Rynek
przegrywa te 0.016 i mimo to wychodzi 0.067 do przodu — więc jego przewaga
w ROZRÓŻNIANIU meczów jest warta ~0.083.

**To nie jest problem poziomu, tylko rozdzielczości.** Zgodne z pomiarem
z 04.09 o dekompozycji Murphy'ego: 81% luki siedzi w rozdzielczości.

## POMIAR C — kształt macierzy jest zły, i to mocno

```
n=47 039   Over 2.5 rynku 0.4987   z Poissona przy rho=0: 0.4205
obciazenie -0.0782   srednie |odchylenie| 0.0800

ta sama liczba przy rho=-0.05 (04.09): -0.0326
```

Bierzemy λ, które odtwarza 1X2 rynku, i pytamy, ile goli z niego wychodzi.
Przy macierzy, którą produkcja realnie liczy (`rho=0`, `USE_DC_TAU` wyłączone),
wychodzi **7.8 punktu procentowego za mało**.

Rynek jest wewnętrznie spójny — to nasz rozkład nie mieści obu jego liczb
naraz. Dokładnie to, do czego służy korekta Dixona-Colesa: `rho<0` dokłada
masy niskim remisom, więc to samo 1X2 da się utrzymać przy WYŻSZYM λ, a więc
przy większej liczbie goli. Przy `rho=-0.05` niedobór spadał do −0.033.

**`USE_DC_TAU` jest na produkcji wyłączone, a `DC_RHO=-0.13` nigdy nie było
dopasowane.** To jest następne miejsce do zmierzenia.

## Dwa błędy narzędzia z 04.09 — do zapamiętania

1. **Zła macierz.** Odzyskiwanie szło przy `rho=-0.05` (`bet_builder`),
   generowanie przy `rho=0` (`poisson._macierz`). Zawyża λ o +7.2%/+7.9%.
   Dwie macierze w jednym repo, docstring twierdził, że to ta sama.
2. **Niejednoznaczność odzyskiwania.** Obcięcie na `MAX_GOLI=8` sprawia, że
   dla dużych λ rozkład przestaje od λ zależeć: para (4.39, 21.64) daje 1X2
   identyczne co do szóstego miejsca z (0.5, 2.9). Pojedynczy optymalizator
   ląduje na tej gałęzi i **melduje zbieżność**. Naprawione multi-startem,
   odrzuceniem rozwiązań na krawędzi i wyborem pierwiastka o najmniejszej
   sumie λ. Regresja w `tests/test_lambda_kto_lepszy.py`.

Reguła na przyszłość: **λ się CZYTA, a nie odzyskuje** — zawsze, gdy jest po
naszej stronie. Odzyskiwanie zostawiamy tylko rynkowi, który innego wyjścia
nie daje, i zawsze z testem round-trip.

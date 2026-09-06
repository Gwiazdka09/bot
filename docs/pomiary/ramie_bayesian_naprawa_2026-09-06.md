# Naprawa pięciu stałych w ramieniu bayesian — wynik, 2026-09-06

Pre-rejestracja: `scripts/ramie_bayesian_naprawa.py` (commit `215950690`).
Wynik liczbowy: `docs/pomiary/ramie_bayesian_naprawa_2026-09-06.json`.

## λ po naprawie

```
faktyczne             1.5087 / 1.2146
classic               1.5120 / 1.1951
bayesian ZEPSUTE      2.1585 / 0.9515
bayesian NAPRAWIONE   1.4943 / 1.1933
```

Ramię przestało odjeżdżać. Λ jest teraz na poziomie ramienia classic.

## Waga dopasowana od nowa

```
Brier 1X2      trening    holdout
  w=0.00       0.62414    0.62044
  w=0.20       0.62132    0.61815
  w=0.40       0.61994    0.61759   <- minimum holdoutu
  w=0.49       (dopasowane na treningu)
  w=0.50       0.61979    0.61797
  w=1.00       0.62445    0.62640
```

Optimum na treningu **0.49**, minimum holdoutu 0.40 — dopasowanie generalizuje.
Dla porównania: przy ramieniu zepsutym optimum wynosiło 0.13.

```
POMIAR 2 — produkcja (zepsute, w=0.13) kontra naprawione (w=0.49)
  0.61991  ->  0.61791
  sparowana +0.00200  SE 0.00042  z=+4.79        29 lig na 38
```

## Reguła — i gdzie się potknęła

```
1. istotnosc  z >= +3               TAK   (z=+4.79)
2. rozmiar przy w=0.70 >= 0.0005    NIE   (+0.00024, z=+1.65)
3. >= 2/3 lig                       TAK   (29/38)
```

**Próg rozmiaru odrzucił.** Po rozcieńczeniu ceną przy wadze rynku, którą API
realnie ma, zostaje +0.00024 — połowa mojego własnego progu widoczności.

### Sprzeczność w mojej własnej pre-rejestracji

Napisałem tam dwie rzeczy, które nie mogą być prawdziwe naraz:

* „pięć stałych zostanie naprawione **niezależnie od wyniku** — to błąd
  jednostek, nie wybór projektowy";
* „wszystkie trzy warunki — inaczej **produkcja bez zmian**".

Po naprawie stałych waga 0.13 przestaje być „bez zmian": jest wagą dopasowaną
do ramienia, którego już nie ma. Rozstrzygnąłem tak, jak pre-rejestracja
przypisała temu pomiarowi zadanie („rozstrzyga wyłącznie, JAKĄ WAGĘ dostanie
naprawione ramię"):

* **stałe naprawione** — bezwarunkowo, bo kod dzielił gole gospodarzy przez
  średnią goli gości;
* **waga 0.49** — dopasowana na treningu dla naprawionego ramienia;
* **nie twierdzę, że to widoczna poprawa produkcyjna.** Próg rozmiaru,
  który sam postawiłem, odrzucił i tego nie omijam.

## Co dokładnie zmienione w kodzie

`poisson_bayesian.predict_match_bayesian`:

```
away_def   prior  league_away -> league_home     (gole tracone NA WYJEZDZIE = gole gospodarzy)
home_def   prior  league_home -> league_away     (gole tracone U SIEBIE     = gole gosci)
lambda_h   mianownik  league_away -> league_home
lambda_a   mianownik  league_home -> league_away
home_advantage  BONUS_DOMOWY (1.15) -> 1.0       (atut liczony drugi raz)
```

`config.W_BAYESIAN` 0.13 → 0.49.

## Test, który to łapie bez żadnych danych

Drużyna doskonale przeciętna — każda jej wielkość równa swojej średniej
ligowej — musi dostać λ dokładnie `(league_home, league_away)`, przy **każdej**
liczbie meczów. Stara wersja dawała tam 1.42× średniej gospodarza.

`tests/test_ramie_bayesian_naprawa.py` sprawdza tę tożsamość dla n ∈ {0, 1, 6,
30, 300} i ma osobną kontrolę, że stara arytmetyka ją łamie.

## Co dalej jest zepsute w tym ramieniu

Nietknięte, bo to trzy osobne zmiany projektowe:

* **nie filtruje ligi** — `_league_averages` liczy średnią z całej ramki,
  a produkcja przekazuje 40 lig naraz;
* **nie ma okna** — cała historia od 2012, waga 3× tylko dla ostatnich pięciu;
* **obcina macierz na 8 komórkach**, główna ścieżka na 9.

Pierwsza z nich jest najpoważniejsza i to ona jest naturalnym następnym
pomiarem — siła drużyny mierzona wobec średniej z 40 lig to nie jest drobiazg.

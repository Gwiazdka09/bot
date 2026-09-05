# Estymator λ — dopasowanie hiperparametrów, 2026-09-05

Pre-rejestracja: `scripts/estymator_lambda.py` (commit `ecce58d0f`), aneks `d2c6eeb2d`.
Wynik liczbowy: `docs/pomiary/estymator_lambda_2026-09-05.json`.

Dopasowywane cztery rzeczy, wszystkie dotąd wpisane z ręki i nigdy nietrenowane:
okno `OKNO_LIGOWE=30`, zanik czasowy (brak), ściąganie ratingu do średniej (brak),
skala λ (brak). Trening < 2024-01-01, holdout ≥ 2024-01-01 (n=31 628).

## Wynik główny — estymator DA SIĘ poprawić

```
PRODUKCJA na holdoucie   log-wiar goli -2.93607   Brier 1X2 0.62074
PELNE DOPASOWANIE        okno 90, polowicz 30 meczow, k=14.21, skala 1.0067/1.0106
                         log-wiar goli -2.91779   Brier 1X2 0.61884

  sparowana log-wiar  +0.01828  SE 0.00122  z=+15.04
  sparowany Brier     +0.00190  SE 0.00050  z= +3.80
  ligi dodatnie       36/38     (prog reguly 3: 26)
```

Wszystkie trzy zamrożone warunki spełnione.

## Rozkład na czynniki (POST-HOC, opisowy)

```
samo SCIAGANIE   (okno 30, plaskie)     ll +0.01466 (z=+12.80)  80.2%   Brier -0.00024 (z=-0.52)
samo OKNO+ZANIK  (bez sciagania)        ll +0.01039 (z=+12.24)  56.8%   Brier +0.00170 (z=+4.62)
OBA                                     ll +0.01828 (z=+15.04) 100.0%   Brier +0.00190 (z=+3.80)
```

Dwie zmiany robią dwie różne rzeczy: ściąganie kupuje log-wiarygodność goli i ani
grama Briera, okno z zanikiem kupuje CAŁY Brier. Gdyby wdrażać jedną, to okno.

**Skala λ nie niesie nic** (z=−0.77) i psuje Brier (z=−5.51). Dopasowana wychodzi
1.014/1.008 — czyli chce λ minimalnie WYŻSZE, nie niższe.

## Aneks — i to on rozstrzygnął

Ramię główne mierzy model w izolacji; produkcja miesza go z ceną.

```
Brier mieszanki (1-w)*model + w*rynek, n=23 070 z zamknieciem Pinnacle

  w=0.00   prod 0.62078   nowe 0.61873   +0.00205  z=+3.42
  w=0.30   prod 0.61029   nowe 0.60944   +0.00085  z=+2.05
  w=0.70   prod 0.60184   nowe 0.60181   +0.00003  z=+0.17
  w=1.00   prod 0.59965   nowe 0.59965   +0.00000
```

Przy wadze rynku 0.70 — tej, którą API realnie ma ustawioną — zysk wynosi
**+0.00003, z=+0.17**. Cena wchłania całą poprawkę. Reguła aneksu zamrożona przed
przebiegiem wymagała z ≥ +2, więc:

> **Estymator jest lepszy, ale kod produkcyjny zostaje bez zmian.**

Warto odnotować, bo to prawdziwa dana, a nie podstawa decyzji: przy w=0.30 —
domyślnej wadze, z jaką chodzą JOBY (`ENSEMBLE_MARKET_WEIGHT` ustawione tylko na
API) — różnica to +0.00085, z=+2.05. Reguła mówiła o w=0.70 i tego się trzymam;
gdyby kiedyś zapadła decyzja o obniżeniu wagi rynku, ten pomiar trzeba odczytać
na nowo.

## Sprostowanie do pomiaru z 04.09 — λ NIE jest zawyżone

Wczoraj napisałem, że nasze λ przeszacowuje gole o +6.5%. To jest nieprawda i
przyczyna jest w narzędziu, nie w modelu.

Zmierzone tutaj, ścieżką ligową produkcji, wprost — bez żadnego odzyskiwania:

```
trening (<2024)    n=102 702   lambda 1.4604 / 1.1578   fakt 1.4820 / 1.1680   blad -0.0216 / -0.0102
holdout (>=2024)   n= 31 628   lambda 1.5120 / 1.1951   fakt 1.5087 / 1.2146   blad +0.0033 / -0.0195
calosc             n=134 330   lambda 1.4726 / 1.1666   fakt 1.4883 / 1.1790   blad -0.0157 / -0.0124
```

Średnie λ estymatora jest praktycznie nieobciążone, a jeśli już — minimalnie
ZANIŻONE. Zgadza się to z dopasowaną skalą 1.014/1.008, która chciała λ podnieść.

Skąd zatem wczorajsze 1.573/1.264. `lambda_czy_ksztalt.py` nie CZYTAŁO λ modelu,
tylko odzyskiwało je z jego 1X2, macierzą Dixona-Colesa przy `rho=-0.05`. A
produkcja generuje to 1X2 przy `rho=0` — `USE_DC_TAU` jest wyłączone. Macierz
odzyskująca była inna niż generująca. Sprawdzone liczbowo na 400 losowych parach λ:

```
prawdziwe srednie lambda   1.5786 / 1.3264
odzyskane przy rho=-0.05   1.6921 / 1.4313
zawyzenie                  +7.2% / +7.9%
```

Czyli dokładnie ten „+6.5% obciążenia", który wczoraj zaraportowałem jako
własność modelu. Był własnością mojego pomiaru.

Docstring `lambda_czy_ksztalt.py` twierdził „ta sama macierz co w produkcji" i
powoływał się na `core/bet_builder.probability_matrix` — ale dump powstał z
`poisson.predict_match`, które używa `_macierz` z `rho=0`. Dwie macierze w jednym
repo, wybrana nie ta.

**Co z tego przeżywa:** pomiar 1 z 04.09 (sparowana log-wiarygodność, z=−23.65)
porównywał obie λ z FAKTYCZNYMI golami i obie były odzyskiwane tą samą, błędną
macierzą — więc kierunek prawdopodobnie stoi, ale wielkość jest skażona i nasze λ
było degradowane bez potrzeby, skoro dało się je odczytać wprost. Wymaga
przeliczenia: prawdziwe λ modelu kontra λ rynku odzyskane przy `rho=0`.

**Co NIE przeżywa:** zdanie „model systematycznie przeszacowuje liczbę goli".
Nie przeszacowuje.

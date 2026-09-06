# Filtr ligi w ramieniu bayesian — WYNIK NEGATYWNY, 2026-09-06

Pre-rejestracja: `scripts/ramie_bayesian_liga.py` (commit `c59bf2fd8`).
Wynik liczbowy: `docs/pomiary/ramie_bayesian_liga_2026-09-06.json`.

## Reguła odrzuciła wszystkie trzy warunki

```
1. istotnosc  z >= +3            NIE   (z=+1.64)
2. rozmiar przy w=0.70 >= 0.0005 NIE   (+0.00017)
3. >= 2/3 lig                    NIE   (22/38)
```

```
Brier 1X2 holdout (n=31 462):  produkcja 0.61775   per liga 0.61727
sparowana roznica +0.00048  SE 0.00029  z=+1.64
```

**Kod bez zmian.** Pre-rejestracja mówiła „tym razem bez furtki" i tego się
trzymam.

## Moje oczekiwanie było błędne i warto wiedzieć dlaczego

Spodziewałem się dużego efektu przez analogię do ramienia classic, gdzie ta
sama poprawka dała Brier 0.6557 → 0.6089. Nie powtórzyła się. Pierwszy sygnał,
że coś jest inaczej, przyszedł od razu:

```
rozrzut lambda gospodarza (odchylenie std)
  globalne 0.4470   per liga 0.4293
```

Rozrzut **spadł**, a analogia przewidywała wzrost. Ramię ma mniej rozdzielczości
z filtrem, nie więcej — bo historia drużyny w jednej lidze to podzbiór jej
historii globalnej, więc ratingi robią się szumniejsze i ściąganie do średniej
bije mocniej.

Różnica wobec ramienia classic: tam problemem było dzielenie przez średnią
liczoną **z tej samej garstki meczów** (sygnał sam się kasował). Tutaj mianownik
był od początku stabilny — globalny. Filtr ligi wymienia więc *obciążenie* na
*wariancję*, a nie „nic" na „coś".

## Obciążenie JEST realne i duże — tylko nie tam, gdzie mierzymy

Błąd λ gospodarza wobec faktycznych goli, w kubełkach po golowości ligi
(holdout, n≈7 900 na kubełek):

```
kubelek golowosci ligi        blad GLOB    blad LIGA
najmniej golowe                -0.1148      -0.0168
nisko                          -0.0517      -0.0114
wysoko                         -0.0627      -0.0577
najbardziej golowe             +0.1753      -0.0051
```

Wersja globalna rozjeżdża się o **0.29 gola** między ligami najmniej i najbardziej
golowymi. Filtr ligi ścina ten rozjazd do 0.05 — **sześciokrotnie**.

A mimo to średni błąd bezwzględny prawie nie drgnął (0.9691 → 0.9625) i Brier
1X2 też nie. Powód jest strukturalny: obciążenie ligowe skaluje **obie** λ
podobnie, więc rusza przede wszystkim SUMĘ goli, a 1X2 zależy głównie od
ich stosunku.

## POST-HOC (opisowe, bez mocy decyzyjnej)

Skoro obciążenie idzie w sumę goli, sprawdziłem rynek golowy tego ramienia:

```
Over 2.5, n=31 463
  przewidywane  GLOB 0.4949   LIGA 0.4932   faktycznie 0.5164
  Brier dwuwyjsciowy  GLOB 0.49743   LIGA 0.49538
  sparowana roznica +0.00205  SE 0.00063  z=+3.24
```

Cztery razy większy efekt niż na 1X2 i istotny. **Ale to nic nie zmienia w
produkcji**: `blend_dixon_coles` dotyka wyłącznie `pw/pr/pp`, a `bt`/`o25`
zostają z ramienia classic. Ramię bayesian nigdy nie karmi rynku golowego.

To jest trop na osobną, pre-rejestrowaną pracę — nie sposób na uratowanie tego
pomiaru. Reguła była o 1X2 i przegrała.

## Koszt filtra, dla porządku

Próg `MIN_MECZOW_LIGA=4` odrzucił **2009 meczów** (1.6%) — drużyny bez czterech
meczów w danej lidze na danej stronie boiska. Odrzucone w OBU ramionach, więc
porównanie zostaje uczciwe, ale przy wdrożeniu byłby to realny ubytek pokrycia.

## Co to zamyka

Trzy dziury w ramieniu bayesian: pięć stałych po złej stronie boiska
(**naprawione**, `42e3e50dc`), brak filtra ligi (**zmierzone, nie wdrażamy**),
brak okna i obcięcie 8 vs 9 (**nietknięte**).

Po dzisiejszej serii ramię liczy poprawne jednostki i ma dopasowaną wagę.
Dalsza praca nad nim ma malejący zwrot — jego λ jest już na poziomie ramienia
classic, a oba przegrywają z ceną.

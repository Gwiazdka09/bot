# Ramię „Dixon-Coles" — czy w ogóle pomaga, 2026-09-06

Pre-rejestracja: `scripts/ramie_bayesian.py` (commit `37ea730aa`).
Wynik liczbowy: `docs/pomiary/ramie_bayesian_2026-09-06.json`.

## Co mierzyliśmy

`quick_picks` liczył 1X2 jako blend **pół na pół**:

```
p = 0.5 * predict_match (classic)  +  0.5 * predict_match_bayesian
```

`W_BAYESIAN=0.5` było wpisane z ręki i nigdy niedopasowane. To była połowa
naszej prognozy 1X2.

## Wynik — ramię jest mocno zepsute

```
lambda kontra faktyczne gole (holdout, n=31 628)

  faktyczne   1.5087 / 1.2146
  classic     1.5120 / 1.1951
  bayesian    2.1585 / 0.9515      <- +43% gospodarz, -22% gosc
```

```
Brier 1X2

  waga    trening    holdout
  0.00    0.62414    0.62044
  0.25    0.62378    0.62186
  0.50    0.63388    0.63344   <- produkcja
  0.75    0.65446    0.65517
  1.00    0.68552    0.68706
```

Waga dopasowana na treningu: **0.130**.

```
holdout:  produkcja 0.63344   dopasowane 0.61991
sparowana roznica +0.01352   SE 0.00071   z=+19.14
37 lig na 38 (jedyna przeciw: FIN-Veikkausliiga)
```

## Rozmiar po rozcieńczeniu ceną

```
waga rynku 0.00   +0.01368  z=+16.59
waga rynku 0.30   +0.00681  z=+11.94
waga rynku 0.70   +0.00134  z= +5.53      <- waga, ktora API realnie ma
waga rynku 1.00    0.00000
```

**+0.00134 to ~45× efekt korekty τ z 05.09** i pierwsza zmiana w tej serii,
która przeżywa rozcieńczenie z zapasem. Próg rozmiaru wpisany do
pre-rejestracji wynosił 0.0005 — przekroczony 2.7-krotnie.

Wszystkie trzy zamrożone warunki spełnione (istotność, rozmiar, replikacja).

## Przyczyna — trzy stałe po złej stronie boiska

Odtworzone na samych średnich, bez żadnego modelu:

```
lig_dom = 1.4883   lig_wyj = 1.1790     (srednie globalne)

kod produkcyjny:               2.1197 / 0.9563     (zmierzone 2.1585 / 0.9515)
prior po WLASCIWEJ stronie:    1.4883 / 1.1790
faktyczne:                     1.5087 / 1.2146
```

W `poisson_bayesian.predict_match_bayesian`:

* **obrona gościa na wyjeździe to gole GOSPODARZA.** Jej prior i mianownik
  powinny być `league_home`, a są `league_away`. Symetrycznie dla obrony
  gospodarza. Ściąganie pcha więc rating w złą stronę, a dzielenie przez złą
  średnią mnoży błąd;
* **`BONUS_DOMOWY=1.15` dokłada atut gospodarza drugi raz** — średnia goli
  gospodarzy już go zawiera. Ten sam błąd jest jawnie opisany w docstringu
  `form.sily_ligowe`, gdzie został kiedyś naprawiony po drugiej stronie kodu.

Do tego dwie rzeczy strukturalne, które osobno mierzyliśmy:

* ramię **nigdy nie filtruje ligi** — `_league_averages` liczy średnią z całej
  ramki, czyli z 40 lig naraz. Siła napastnika Premier League jest mierzona
  wobec średniej wspólnej z MLS i chińską Super League;
* `_compute_ratings` **nie ma żadnego okna** — cała historia od 2012, z wagą 3×
  tylko dla ostatnich pięciu meczów.

## Co wdrożone

`W_BAYESIAN` 0.5 → **0.13**. Bez naprawy samego ramienia — to jest osobna
zmiana i wymaga osobnego pomiaru.

Waga 0 jest po zmieszaniu z ceną **nie do odróżnienia** od 0.13 (+0.00000,
z=+0.04); w czystym modelu 0.13 wygrywa o +0.00053 (z=+2.14). Zostaje 0.13,
bo tyle wyszło z dopasowania na treningu.

**0.13 jest dopasowane do ramienia Z BŁĘDEM.** Po naprawie trzech stałych wagę
trzeba dopasować od nowa — stara wartość będzie bez sensu. Pilnuje tego
`test_lambda_ramienia_jest_zepsuta_i_to_jest_udokumentowane`, który ma UPAŚĆ
w dniu naprawy.

## Kontekst: dlaczego to nie zostało złapane wcześniej

Komentarz przy `USE_DIXON_COLES` mówił „zwalidowane offline +1.7pp". Ta
walidacja porównywała blend z samym classic na małej próbie i mierzyła
trafność, nie Brier. Trafność argmaxu jest ślepa na to, że λ gospodarza jest
o 43% za wysokie, dopóki argmax nie zmienia strony — a przy przeszacowanym
gospodarzu on się właśnie nie zmienia, tylko robi się nadmiernie pewny.

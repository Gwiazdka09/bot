# Lambda czy ksztalt — wynik, 2026-09-04

Pre-rejestracja: `scripts/lambda_czy_ksztalt.py` (commit 1466b12b6).

```
Zrzut: 111804 meczow | gole doklejone do 100.0%
Do pomiaru: 20000 meczow, 39 lig

============================================================================================
  POMIAR 1 — czyje OCZEKIWANIA BRAMKOWE lepiej przewiduja gole
============================================================================================
  srednia log-wiarygodnosc:  model -2.96048   rynek -2.86644
  sparowana roznica (model - rynek) -0.09404  SE 0.00398  z -23.65

  srednie lambda:  model 1.573 / 1.264   rynek 1.434 / 1.122
  srednia |roznica| lambda:  gospodarz 0.319  gosc 0.277

============================================================================================
  POMIAR 2 — czy Poisson z lambda RYNKU odtwarza Over 2.5 RYNKU
============================================================================================
  n=8573   Over 2.5 rynku 0.4993   z Poissona 0.4667
  srednie obciazenie -0.0326   srednie |odchylenie| 0.0421
  Rynek jest wewnetrznie spojny. Duzy rozjazd znaczy, ze rozklad
  Poissona NIE MIESCI tego, co rynek wie — sufit w KSZTALCIE.

============================================================================================
  POMIAR 3 — lambda RYNKU przepuszczone przez NASZA macierz
============================================================================================
  Brier:  model 0.6264   hybryda 0.6002   rynek 0.6002
  luka model-rynek +0.02626   zamkniete przez sama podmiane lambda +0.02626   (100%)
  sparowane model-hybryda +0.02626  SE 0.00132  z +19.96

  REGULA DECYZYJNA (zamrozona przed przebiegiem):
    Podmiana samych lambd zamyka >= 1/3 luki -> waskim gardlem sa
    OCENY SIL DRUZYN. Praca idzie w estymator: okno .tail(30),
    zanik czasowy, przewaga gospodarza — nigdy niedopasowane.

[exited with code 0]
```

## Reszty dopasowania (liczone osobno, n=3000)

```
nasz model   srednia 0.00008   95pc 0.00008   max 0.03375
rynek        srednia 0.00007   95pc 0.00008   max 0.01953
```

Obie prognozy leza na tej samej dwuparametrowej rozmaitosci Poissona-DC
z dokladnoscia do 1e-4. To jest warunek, ktory czyni pomiar 1 sensownym.

## POMIAR 3 BYL TAUTOLOGICZNY

Lambdy rynku dopasowano tak, ZEBY odtwarzaly jego 1X2, po czym przepuszczono
je przez te sama macierz — hybryda musiala wyjsc rowna rynkowi. „100%" jest
konsekwencja konstrukcji, nie odkryciem. Blad byl w pre-rejestracji.

## SPROSTOWANIE 2026-09-05 — POZIOMY λ W TYM POMIARZE SĄ ZAWYŻONE

Ten skrypt nie CZYTAŁ λ modelu, tylko odzyskiwał je z jego 1X2 macierzą
Dixona-Colesa przy `rho=-0.05`. Produkcja generuje to 1X2 przy `rho=0`
(`USE_DC_TAU` wyłączone, `poisson._macierz`). Macierz odzyskująca była inna
niż generująca, a docstring twierdził, że to ta sama.

Skala błędu, zmierzona na 400 losowych parach λ:

```
prawdziwe srednie lambda   1.5786 / 1.3264
odzyskane przy rho=-0.05   1.6921 / 1.4313      +7.2% / +7.9%
```

Prawdziwe λ estymatora, odczytane wprost ścieżką ligową produkcji
(`estymator_lambda.py`, n=134 330): **1.4726 / 1.1666** przy faktycznych
**1.4883 / 1.1790** — czyli praktycznie bez obciążenia, jeśli już to minimalnie
zaniżone. Nie 1.573 / 1.264.

**Zdanie „model systematycznie przeszacowuje liczbę goli" jest FAŁSZYWE** i nie
wolno go dalej cytować.

Pomiar 1 (sparowana log-wiarygodność, z=−23.65) porównywał obie λ z faktycznymi
golami, obie odzyskane tą samą błędną macierzą — kierunek prawdopodobnie stoi,
wielkość jest skażona. Wymaga przeliczenia na prawdziwych λ modelu.

Szczegóły: `docs/pomiary/estymator_lambda_2026-09-05.md`.

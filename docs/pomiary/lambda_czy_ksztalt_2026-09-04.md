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

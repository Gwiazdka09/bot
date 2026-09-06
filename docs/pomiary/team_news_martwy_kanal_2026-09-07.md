# Team news — kanał był martwy na trzech poziomach naraz, 2026-09-07

Nie pomiar, tylko śledztwo. Punkt wyjścia: team news miały być pierwszym **nowym**
źródłem informacji (wszystko inne mierzone do tej pory to informacja publiczna,
którą rynek już wycenił). Flaga `FOOTSTATS_TEAM_NEWS=1` chodziła od 05.09.

## Co pokazały dane

```
model_log            1078 wierszy, 78 od wlaczenia flagi
p_over_abs           0
edge_absencje        0
rynek_p_over         0
absencje_pewne_home  0
```

Zero na 1078. Przy czym wszystko po drodze wyglądało zdrowo:

* flaga `=1` na `footstats-api`, `footstats-final` i `footstats-evening`;
* FotMob odpowiada 200 i oddaje **121 meczów** na dzisiaj;
* dla drużyn z naszego słownika dopasowanie nazw działa **dokładnie**;
* **74%** wierszy `model_log` to mecze grane tego samego dnia, więc horyzont
  też nie jest wąskim gardłem;
* przebiegi jobów kończą się `EXECUTION_SUCCEEDED`.

## Trzy niezależne blokady

### 1. Dziennik zapisuje się PRZED policzeniem pól

`daily_agent.main()`:

```
linia ~1038   zapisz_partie(wyniki)           <- INSERT do model_log
linia ~1089   _enrichuj_finalna_faza(wyniki)  <- dopiero TU powstaja pola
```

Cztery kolumny są w INSERT-cie od 04.09 i pilnuje ich osobny plik testów
(`test_model_log_absencje.py`). Nikt nie sprawdził, czy INSERT biegnie **po** ich
policzeniu. Nie biegnie — o pięćdziesiąt linii.

Przeniesienie zapisu niżej odpada: pomiędzy stoją cztery filtry (28 → 6 na
przebiegu 06.09), a `model_log` istnieje po to, żeby widzieć **wszystkie** oceny,
nie te ~5%, które przetrwały filtr wartości.

**Fix:** INSERT zostaje, po wzbogaceniu leci UPDATE po `id` zapamiętanym przy
zapisie. Plus test czytający kolejność wywołań w źródle — ten błąd przeżył
już dwie naprawy.

### 2. `player_stats` nie istnieje w kontenerze

```
player_db: nie moge odczytac goli AZ Alkmaar/2026
(OperationalError: no such table: player_stats) — goal_share = 0
```

**105 takich wpisów w jednym przebiegu**, na `stderr` — dlatego pierwsze
zapytanie po `stdout` ich nie widziało.

`data/footstats_backtest.db` jest wykluczony i z `.dockerignore` (linia 11),
i z `.gcloudignore` (`/data/*`). sqlite3 tworzy wtedy pusty plik, a pierwszy
odczyt pada. Skutek sięga dalej niż korekta λ za kontuzje:
`_policz_edge_absencji` wychodzi na `continue`, więc `p_over_abs` i
`edge_absencje` nie powstają **nigdy**.

**Fix:** `scripts/eksport_player_stats.py` → `data/player_stats.json`
(2913 graczy, 252 drużyny, sezony 2024-2026, 210 KB), shipowany w obu obrazach
jak `team_mappings.json`, plus zapasowa ścieżka w `player_db`.

Zrzut wchodzi **wyłącznie gdy baza padła** — nie gdy po prostu nie zna drużyny.
Inaczej świeżo założona, pusta baza po cichu dostawałaby zamrożone liczby
i nikt by nie zauważył. To był pierwszy odruch i był błędny; złapał go
`test_unknown_team_empty`.

### 3. Cena ginęła przy okazji

`k["rynek_p_over"] = rynek` stało **pod** bramką `if not ud_h and not ud_a:
continue`. Bramka wypada zawsze, gdy `player_db` jest puste — czyli w kontenerze
zawsze. Komentarz dwie linie niżej sam argumentuje, że to zła kolejność:
„bez ceny, wobec której liczyliśmy przewagę, nie da się później orzec, kto miał
rację. To jest cała wartość tego wpisu."

Cena nie zależy od udziałów golowych — zależy od kursów, które już trzymamy
w ręku. **Fix:** zapis przeniesiony nad bramkę.

## Dwie ciche ścieżki domknięte przy okazji (J1)

* `_wzbogac_team_news`: gdy źródło oddaje pustą listę albo **żaden** kandydat
  się nie dopasuje, jedynym śladem był `log.debug`. Przebieg `footstats-final`
  z 06.09 nie zostawił w 258 liniach stdout ani jednej wzmianki o team-news.
  Podniesione do WARNING z liczbą kandydatów bez danych.
* `player_db`: ostrzeżenie o martwym `goal_share` leciało przy **każdym**
  odczycie (105×/przebieg) dla stanu stałego. Zawężone do przypadku, w którym
  padła baza **i** nie ma zrzutu — czyli gdy korekta λ faktycznie umiera.
  Szum niszczy alarmy tak samo skutecznie jak cisza.

## Czego to NIE naprawia

`_wzbogac_team_news` pobiera listę FotMoba **wyłącznie na dziś**
(`_date.today()`), a kandydaci są z okna 72h. Przy 74% meczów granych tego
samego dnia to nie jest główna strata, ale jedna czwarta kandydatów pozostaje
poza zasięgiem. Osobna zmiana, osobny pomiar.

## Jak to sprawdzić po wdrożeniu

Po pierwszym przebiegu `footstats-final`:

```sql
SELECT COUNT(*) FROM model_log WHERE absencje_pewne_home IS NOT NULL;  -- > 0
SELECT COUNT(*) FROM model_log WHERE rynek_p_over IS NOT NULL;         -- > 0
SELECT COUNT(*) FROM model_log WHERE p_over_abs IS NOT NULL;           -- > 0
```

Trzecia liczba jest testem blokady #2: jeśli zostanie zerem przy dwóch
pierwszych niezerowych, znaczy że zrzut nie dojechał do obrazu.

`scripts/sklady_pomiar.py` odmawia analizy poniżej 500 rozliczonych wierszy —
przy ~30 kandydatach dziennie to około dwóch miesięcy zbierania.

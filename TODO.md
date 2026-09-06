# FootStats TODO — Lipiec 2026

> **🎯 PIVOT 2026-07-06:** zero monetyzacji/użytkowników → **czysta predykcja do doskonałości**. Strategia + 16 pomysłów → **`docs/PREDICTION_ROADMAP.md`**. Empiria: static value-betting na publicznych danych OBALONE (nie bije rynku O/U ani 1X2). Kierunek: **ścieżka A kalibracja** (best predyktor, metryka log-loss/Brier) lub **ścieżka B edge informacyjny** (player-availability delta/live/CLV). P3 monetyzacja → ARCHIWUM.
>
> **🔧 NAPRAWIONE 07-06 (największy lever):** audyt 104 settled — Groq nadpisywał model i psuł (1X2 model argmax 60% vs Groq 48%, +12pp). Fix: `GROQ_TIP_OVERRIDE` flip ON + threshold 33 (1X2) + 45 (O/U/BTTS `koryguj_tip_ou_btts`). **LLM (llama-3.1-8b) odsunięty od WSZYSTKICH picków → tylko analiza/podsumowania.** Model wybiera. TODO: zakładka GUI "analiza LLM"; rozważyć GROQ_MODEL=70b (reasoning). Inne dławiki: 65% predykcji bez modelu (off-season egzotyka/WC → LEAGUE_GATING celuje w złe ligi), confidence odwrócony (80%+→19%, nie włączać selekcji).

> **🎯 KIERUNEK 2026-07-21:** produkt = **dziennik kuponów + śledzenie postępu ludzi** (nie tylko surowa predykcja). NIE bukmacher, **zero obsługi pieniędzy** (jednostki, nie PLN przez nas). Predykcja = sygnał zaufania w dzienniku, nie sprzedawany edge. Plan → sekcja `📓 DZIENNIK KUPONÓW` niżej. Omija KILL rady ROAST (dziennik ≠ konkurent devigu rynku).

> **🎯 KIERUNEK 2026-07-27:** produkt zostaje na **użytek prywatny + beta-testerzy (znajomi)**. Priorytet = **żeby bot się uczył** (pętla predykcja→settle→kalibracja→RAG). Zero monetyzacji, zero publicznego launchu. Plan wykonawczy → sekcja `🎯 PLAN P0-P3` niżej.

**Aktualizacja:** 2026-08-14 · v3.4-stable
**Accuracy (live, `model_log` 13.08):** **poisson-dc 65.2%** (15/23) · bzzoiro-ml 50.0% (41/82) — próba mała, ale poisson-dc realnie gra i prowadzi
**Accuracy (offline):** Brier 0.6064 po fiksie rozdzielczości (było 0.6454); rynek 0.5912 — **wciąż nad nami**
**Cel M1:** 55% win rate (mierzony na 1X2 — **do rewizji**, patrz werdykt per rynek) · **Suite:** 4375 testów
**LIVE:** pipeline **PC-off w chmurze** — Cloud Run Jobs (final 11:00 + evening 23:00) + Scheduler (draft 07:30, settle 06:00/21:30). Szczegóły → `docs/cloud_migration.md`.
**⚠️ INCYDENT 27.07 (naprawiony):** redeploy zgubił env Cloud Run (`JWT_SECRET` itd.) → login zwracał 500 udający „złe hasło". Fix: rev 00313-mf5 + malformed-hash guard (401 nie 500) + `/mcp` off w prod + CD re-asertuje krytyczne sekrety + LoginView rozróżnia błąd serwera/limit/sieć od złych danych. Audyt auth: 6 znalezisk, rdzeń szczelny.
**⚠️ INCYDENT 14-20.07 (naprawiony 07-20):** potrójna awaria — Neon quota-block → **DB = Supabase free** (session pooler); image jobów bez `footstats.data` (`.gcloudignore` fix); kupon=None crash. **Luka w danych 14-20.07** (zero predykcji/settled). Dane 1-17.07 uwięzione w Neonie do **1.08**. Szczegóły → `CHANGELOG.md` 07-20.
**Zbudowane flag-OFF (flip po walidacji):** `SELECTION_MIN_CONF` (#1) · `LEAGUE_GATING` (#2). Już LIVE: `ENSEMBLE_MARKET_WEIGHT=0.70` (reweight ku rynkowi).

> **📦 Ukończone → `CHANGELOG.md`.** 23.08 przeniesiono stamtąd 40 zamkniętych pozycji
> (729 → 403 linie). Ten plik trzyma **wyłącznie to, co otwarte** — jeśli szukasz, jak coś
> zostało naprawione, szukaj w CHANGELOG-u albo w `git log`.

---

## 🎯 PLAN P0-P3 — PĘTLA UCZENIA (2026-07-27, DO WYKONANIA)

> **Cel nadrzędny:** bot ma się **uczyć**, a nie tylko generować. Dziś pętla jest przerwana w trzech miejscach naraz: gra nie ten model, nie ma danych, RAG dostaje puste faktory.
> **Kolejność usera: A → C → B.** Wszystko model-critical → walk-forward + zgoda usera przed każdym flipem.

| # | Zadanie | Kod | Blokada | Status |
|---|---------|-----|---------|--------|
| **P0** | **Model musi realnie grać live** — parquet w obrazach jobów i API → Poisson-DC zamiast `bzzoiro-ml` | **A** | — | ✅ **13.08** — `poisson-dc` 65.2% (15/23) w `model_log` |
| **P1** | **Pętla settle→kalibracja** — `calibration_monitor.py` + `flip_advisor` co 2-3 dni → progi flipów | — | zob. werdykt 26.08 niżej | 🟡 **werdykt modelu NIEROZSTRZYGNIĘTY** |
| **P2** | **Więcej danych → lepsze λ** — backfill Neon→Supabase | **B** | — | ✅ **14.08** — backfill był już zrobiony, reszta danych odpuszczona |
| **P3** | **RAG feedback domyka sygnał** — puste `factors` | **C** | — | ✅ **13.08 NIE bug** — wąskie gardło = liczba predykcji |

> Szczegóły zamkniętych P0/P2/P3 → `CHANGELOG.md` (13-14.08).
> Zostaje z P3 do zapamiętania: TWIERDZA wymaga serii ≥5 (`FORTRESS_MECZE`), a na losowej próbce
> 300 meczów tagi zapalają się w 31.7% — mechanizm żyje, po prostu potrzebuje wolumenu.

> **⚠️ 26.08 — KOREKTA wpisu P1.** Wcześniejsza wersja mówiła „brakuje 7 rozliczonych poisson-dc
> do progu 30 — JEDYNA ŻYWA BLOKADA". Nieprawda. `python -m scripts.porownaj_modele` (26.08):
> `predictions`: bzzoiro-ml 50/129 = 38,8% [30,8–47,4], poisson-dc 16/29 = 55,2% [37,5–71,6]
> → brakuje **1**, nie 7. `model_log`: bzzoiro-ml 154/300 = 51,3% [45,7–56,9], poisson-dc
> 68/127 = 53,5% [44,9–62,0] → **przedziały ufności się nakładają, różnica może być szumem**.
> **P0 („model musi realnie grać live") nie dał dotąd mierzalnej poprawy na poziomie modelu** —
> oba modele są dziś statystycznie nie do odróżnienia. Nawet gdy `predictions` dobije do 30,
> przedziały najpewniej dalej się nałożą, więc werdykt zostanie nierozstrzygnięty. Dochodzi
> confound z **D11**: Poisson liczy ~10% meczów, więc te 29 predykcji to wyselekcjonowany
> podzbiór, nie losowa próbka.

---

## 📓 DZIENNIK KUPONÓW + POSTĘP LUDZI (kierunek 2026-07-21)

> **Cel:** produkt = miejsce gdzie ludzie zapisują swoje kupony (obstawione GDZIE INDZIEJ), a system podsumowuje zysk/stratę i śledzi postęp w czasie. Predykcja modelu = sygnał obok wyboru usera. **Zero obsługi pieniędzy, nie bukmacher.**
> **Dlaczego to żyje (a "best predyktor" nie):** dziennik NIE ściga się z devigiem rynku — wartość = rekord, dyscyplina, accountability, ranking grupy. Rada ROAST zabiła "predyktor jako produkt", nie "dziennik z predykcją jako feature".

### Fundament (JUŻ istnieje — nie budować od zera)
- `core/coupon_tracker.py` — CRUD kuponów per `user_id` (`save_coupon`/`update_coupon_status`/`get_active_coupons`/`get_coupon_legs`/`promote_to_active`).
- `core/coupon_settlement.py` — auto-rozliczanie po wyniku meczu · `core/bankroll.py` — saldo jednostek · `core/system_coupons.py` · `core/clv_tracker.py`.
- GUI: `HistoryView`+`HistoryCouponRow` (historia), `LeaderboardView` (ranking ludzi), `DashboardHome`, `LoginView`/multi-user, `AdminPanelView`, `SettingsView`.
- Dowód działania: 10 kuponów Admin_JG rozliczone (CHANGELOG 07-03/04).

### Luki do domknięcia (bite-size, TDD + design-system, w tej kolejności)

### 🔗 Match-linking (fundament J6+J4c, kierunek 2026-07-21) — DONE
> Free-form mecz → nasze dane. Odblokowało oba: podgląd sygnału (J6) + auto-settle (J4c).

### Silnik sygnału (dotychczasowa praca = wartość dziennika)
Kalibracja/selekcja (P0/P1 niżej) NIE jest już celem samym w sobie — to **feature zaufania w dzienniku**: uczciwa pewność, której blind-tipster nie da. P0 walidacja dalej ważna, ale jako **jakość sygnału**, nie jako "bicie rynku".

### Non-goals (twarde — blok scope-creep)
- ❌ Płatności / wypłaty / realny PLN przez nas — tylko **jednostki**. ❌ Przyjmowanie zakładów (nie bukmacher). ❌ Sprzedawanie edge / ściganie rynku jako produkt.

### 🐞 Znalezione przy J1-J4 (osobne taski, NIE blokują dziennika)
- **CSS cascade-layer bug (app-wide):** `gui/src/index.css` `button {color:inherit;background:transparent}` jest POZA `@layer` → w Tailwind v4 bije utility-klasy, więc `text-*`/`bg-*` na KAŻDYM `<button>` się nie stosują (przyciski bezbarwne). Obejście w dzienniku: inline `style var()`. Fix globalny = owinąć reset w `@layer base` + pełna regresja wizualna przycisków.
- ~~**Auto-settle hybryda „co mamy — my":**~~ ✅ ZROBIONE (match-linking A+C wyżej). Zostaje decyzja enablement `/cron/settle-manual`.
- **Testy widzą prod przez `.env`:** `config.py` robi `load_dotenv` → `DATABASE_URL` z `.env` (dziś Supabase, nie martwy Neon). Guard w `tests/conftest.py` **przerywa całą suitę**, gdy URL wskazuje prod — to zadziałało i zadziałać ma. Zostaje uciążliwość: na Windowsie `$env:DATABASE_URL=""` kasuje zmienną zamiast ustawić pustą, więc guard i tak czyta `.env`. Docelowo marker `@pytest.mark.integration` + test-DB; doraźnie patrz „Dług testowy" w Następnych krokach.

---

## Milestones

| Milestone | Cel | Status | Warunek |
|-----------|-----|--------|---------|
| **M1** | 55% win rate | 🔴 W toku | ~88 świeżych settled → selekcja 65%+ conf (offline=68%) + gating lig |
| **M2** | 60% win rate | ⏸️ | Po M1 — tuning |
| **M3** | 65% selected | ⏸️ | Po M2 |
| **BETA** | Testerzy | ⏸️ | Po M1 |

---

## 🔬 WALIDACJA — szczegóły P1/P2 (blokuje M1, PASYWNE — NIE dokładaj zmian λ)

> Root-cause'y Cel B usunięte. Kalibracja OFF (`CALIBRATION_ENABLED`), auto-refit czeka na dane (D2).
> STOP na nowe λ aż zbierzemy świeże settled — zmiana teraz zaciemnia czy fixy działają.
> **Zbieranie leci PC-niezależnie** (cloud draft 07:30 + settle) — brak wąskiego gardła danych.

- [ ] **Co kilka dni:** `python scripts/stan_uczenia.py` (read-only) — licznik do werdyktu, teraz z `model_log`. Uzupełniająco `scripts/calibration_monitor.py` + flip-advisor (`core/flip_advisor.py`): rekomenduje flip `SELECTION_MIN_CONF` i ligi do `LEAGUE_GATING` (<50%, n≥8).
- [ ] **26.08 — kalibracja 1X2 i przewaga nad kursem zmierzone po raz pierwszy wprost (zadanie S).** `raport_kalibracji_1x2` + `raport_przewagi_nad_kursem` w `stan_uczenia.py`. Kalibracja n=427: 38,8/42,9/60,5/69,8/71,4% — krzywa **ROŚNIE** (rozpiętość 32,6 pp), ale nierówno: model niedoszacowany w środku skali (deklaruje 54,6%, trafia 60,5%), zbyt pewny na górze (76,3% deklarowane vs 71,4% trafień). Przewaga nad kursem bukmachera n=133: BTTS −18,3% (p=0,058 → 0,213 po korekcie Šidáka) — **żaden rynek nie bije ceny** po korekcie. Do decyzji: czy krzywa kalibracji uzasadnia już ruch progu `SELECTION_MIN_CONF`, czy n=427 to wciąż za mało.
- [ ] **26.08 — remisy zmierzone po raz pierwszy (zadanie R), samodzielny sygnał otwarty do dalszej obserwacji.** `draw_correct` backfillowane 0→424 wierszy. Baza 23,6%; koszyki po `prob_draw`: 20,0/24,4/17,7/24,1/**45,5%** — krzywa NIE rośnie monotonicznie, ale koszyk `30%+` (n=33, 15 remisów) bije bazę o 21,9 pp (dokładny test dwumianowy p=0,0048 → p=0,024 po korekcie Šidáka). Próba mała — obserwować, nie budować na tym flagi.
- [ ] **D3 — pełna decyzja a/b/c** (próg guardu, czy argmax na stałe) — po ~20 ŚWIEŻYCH settled z zapisanym prob. Zwaliduj że guard pomaga, dostrój próg. (D3 cz.1+2 prob+guard ZROBIONE 06-22.)
- [ ] **Po ~88 settled → D2 auto-refit sam** (delta +30 od n_train); gdy krzywa zdrowa → włącz `CALIBRATION_ENABLED=1`.
- [x] **Dług testowy — ZAMKNIĘTE 28.08, ale opis był NIEAKTUALNY.** Sam wyciek („testy biją
  w `DATABASE_URL` z `.env`") zamknął się już po incydencie 29.07: `pytest_configure`
  w `tests/conftest.py` przerywa sesję, gdy URL wskazuje produkcję. Uwaga do `config.py`
  też mija się z kodem — `load_dotenv(ENV_FILE)` w linii 343 jest **bez** `override`,
  więc zmienna ze środowiska wygrywa (na tym stoi `DATABASE_URL=""`); `override=True`
  siedzi w osobnej funkcji przeładowującej.
  **Co było realnie zepsute:** guard był **denylistą** trzech znanych hostów
  (`supabase.co`, `supabase.com`, `neon.tech`). Taka lista gnije w jedną stronę —
  baza przeprowadziła się już raz (Neon → Supabase 18.07) i lista przetrwała tylko
  dlatego, że ktoś ją dopisał ręcznie. Po następnej przeprowadzce guard dalej wyglądałby
  na działający i nie chroniłby przed niczym.
  **Fix:** odwrócony na **allowlistę** (`_powod_odmowy`): wolno tylko brak URL, host
  lokalny albo baza z „test" w nazwie; wszystko inne wymaga `FOOTSTATS_ALLOW_PROD_DB=1`.
  Nieznany host jest teraz blokowany domyślnie. Komunikat pokazuje host i nazwę bazy,
  **nigdy loginu ani hasła** (leci na stdout CI).
  **Plus:** `tests/test_guard_bazy_testowej.py` — pierwszy test tego mechanizmu w ogóle.
  Jedyna rzecz chroniąca całą suitę przed zapisem do proda sama nie była niczym pilnowana.
  - ✅ **Zrobione 07-29:** `DATABASE_URL` wskazuje już Supabase (prod), stary Neon zachowany jako `DATABASE_URL_NEON` (źródło backfillu). Naprawia narzędzia/skrypty diagnostyczne, które dotąd trafiały w martwego Neona.
  - ⚠️ **KOREKTA:** to NIE jest fix długu testowego. Część tych testów **pisze** (`test_auth` zakłada userów, `test_settle_*` zmienia statusy kuponów) — uruchomienie ich teraz celowałoby w PRODUKCJĘ. Suitę dalej odpalamy z `DATABASE_URL=""` (guard sieciowy w `conftest`).
  - Fix docelowy bez zmian: marker `@pytest.mark.integration` + oddzielny test-DB.

---

## 🟠 M1 LEVERS — szczegóły P1 (zbudowane flag-OFF → flip po ~88 fresh settled)

> Kalibracja: **65%+ conf = 68%** (robustnie). Per-liga: NED 56/SCO 55/ITA 54/ENG 54 ≥M1; POL 44/ESP 49/FRA 49 w dół.
> Wniosek M1 (zgodny z Cel B): model OK, droga = **SELEKCJA** (65%+ subset) + **gating lig**.

- [ ] **Flip `SELECTION_MIN_CONF=65`** po walidacji — podnosi próg `najlepszy_typ` do pasma high-conf. Zwaliduj że live trzyma kalibrację. (Wpływa na System paper + cloud-draft.)
- [ ] **Flip `LEAGUE_GATING=1`** po walidacji — odrzuca `LIGI_SLABE` (POL/ESP/FRA <50%), faworyzuje NED/SCO/ITA/ENG.
- [ ] **Monitoruj reweight 30/70** (`ENSEMBLE_MARKET_WEIGHT=0.70`, rev 00274 LIVE) — calibration check (log-loss) na świeżych settled. Escape-hatch: zmień/usuń env.
- [ ] (opcj.) re-optymalizacja per-league wag ku rynkowi (`ensemble_optimizer`).

---

## 🟡 SIERPIEŃ (restart lig klubowych) — okno wykonania P0/A

> Teraz off-season = mecze kadr (WC) → Poisson nie ma historii reprezentacji (dataset = ligi klubowe). Realny zysk dopiero na restart lig.

---

## 🚀 PLAN WYPUSZCZENIA (darmowe, ustalone 2026-08-24)

Kierunek: **za darmo, bez firmy, bez reklam na starcie.** Prawo i podatki nie są blokadą
(patrz `.claude/rules/wypuszczenie-pl.md`). Blokadą jest gotowość: cztery drobne braki
formalne i niezawodność.

### Faza 1 — formalności — ZROBIONA 24.08 (poza danymi osobowymi)
- ~~**L2**~~ ✅ §5 przepisany na „Nieodpłatność Serwisu”.
- ~~**L3**~~ ✅ §7 bez wyłączenia odpowiedzialności; dodane zdanie o braku przewagi nad rynkiem.
- ~~**F8**~~ ✅ było już zrobione (`legalUrl()`), wpis nieaktualny.
- ~~**L1**~~ ✅ **ZAMKNIĘTE 25.08.** Imię, nazwisko i e-mail w obu dokumentach. Adres pocztowy **nie jest wymagany przy serwisie darmowym** — patrz L1 niżej; wpis z 24.08 o blokadzie był błędny.

**Znalezione przy okazji i naprawione, poza pierwotną listą:**
- Regulamin **nie miał trybu reklamacyjnego**, którego wymaga art. 8 ustawy o świadczeniu usług drogą elektroniczną. Dodany: zgłoszenie e-mailem, odpowiedź w 14 dni, brak odpowiedzi = uznanie reklamacji.
- §10 narzucał **sąd właściwy dla siedziby Operatora** — wobec konsumenta odbiera mu sąd miejsca zamieszkania. Zastąpione właściwością ustawową plus wzmianka o ODR.
- Polityka prywatności wskazywała **Neon.tech** jako hosting bazy, a produkcja stoi na **Supabase** od 18.07 (zweryfikowane 24.08 na produkcji: host `*.pooler.supabase.com`). Wskazanie nieprawdziwego podprocesora jest poważniejsze niż nieaktualna wzmianka o płatnościach — RODO wymaga, by lista odbiorców odpowiadała stanowi faktycznemu. Poprawione, dopisany też Vercel.
- Polityka wymieniała **Lemon Squeezy / Paddle** jako procesora płatności, który nie dostaje żadnych danych, i podawała okres retencji **„przez czas trwania subskrypcji”** — nieistniejącej. Oba zastąpione stanem faktycznym, z opisem, co dokładnie robi „Usuń konto”.
- Polityka żądała **NIP-u** w danych administratora. Osoba nieprowadząca działalności go nie ma.

Pilnuje tego `tests/test_strony_prawne.py` (20 testów) — sprawdza stan, nie brzmienie.

## 🔴 DO SPRAWDZENIA PO NAJBLIŻSZYM PRZEBIEGU (07.09.2026)

Kanał team-news był martwy na **trzech poziomach naraz** — naprawione w `01ae305f7`,
szczegóły w `docs/pomiary/team_news_martwy_kanal_2026-09-07.md`. Po pierwszym
`footstats-final` po deployu:

```sql
SELECT COUNT(*) FROM model_log WHERE absencje_pewne_home IS NOT NULL;  -- > 0
SELECT COUNT(*) FROM model_log WHERE rynek_p_over IS NOT NULL;         -- > 0
SELECT COUNT(*) FROM model_log WHERE p_over_abs IS NOT NULL;           -- > 0
```

Trzecia liczba jest testem tego, czy `data/player_stats.json` dojechał do obrazu:
jeśli zostanie zerem przy dwóch pierwszych niezerowych — zrzut nie doszedł.

- [ ] **Zostało nienaprawione:** `_wzbogac_team_news` pobiera listę FotMoba tylko
  na DZIŚ (`_date.today()`), a kandydaci są z okna 72h. Przy 74% meczów granych
  tego samego dnia to nie jest główna strata, ale ~1/4 kandydatów jest poza
  zasięgiem. Osobna zmiana, osobny pomiar.
- [ ] **Odświeżanie zrzutu:** `scripts/eksport_player_stats.py` przed budową obrazu,
  kiedy `player_stats` było niedawno aktualizowane. Zrzut się starzeje —
  `team_goal_shares_recent` sięga tylko `lookback` sezonów wstecz.
- [ ] `scripts/sklady_pomiar.py` odmawia analizy poniżej 500 rozliczonych wierszy.
  Przy ~30 kandydatach dziennie to około dwóch miesięcy zbierania.

---

### Faza 2 — niezawodność (zanim wejdą ludzie)
- **J1** — 271 z 546 `except` milczy. **Zakres na teraz, nie wszystkie 271:** strażnik z baselinem
  (żeby nie przybywało nowych) + naprawa ścieżek, które widzi użytkownik i którymi jedzie potok.
  Uzasadnienie: 24.08 w jeden dzień pięć cichych awarii wyglądających na zdrowy system
  (kupony stały 8 dni przy `exit=0`, próg selekcji nigdy nie działał, football-data nigdy nie
  odpowiadało, CI świeciło czerwono aż przestało znaczyć, alarm miał wyć codziennie).
  Przy jednym użytkowniku to koszt czasu. Przy stu — ktoś inny patrzy na pustą stronę.
  - **07.09: strażnik z baselinem już istnieje** (`test_ciche_except_audit.py`, 255/555).
    Domknięte dwie ścieżki potoku: `_wzbogac_team_news` przy pustym źródle logowało
    DEBUG (przebieg 06.09 zostawił 258 linii stdout i zero wzmianek o team-news) → WARNING;
    `player_db` odwrotnie — ostrzegało 105×/przebieg dla stanu stałego → zawężone do
    momentu, w którym korekta λ faktycznie umiera. Szum niszczy alarmy tak samo jak cisza.

### Faza 3 — dopiero po tym publikacja
- Wypuszczenie, obserwacja: czy ktokolwiek wraca.
- **L5** (co sprzedajemy) i **L8** (reklamy) rozstrzygamy na podstawie ruchu, nie przed nim.

### Świadomie NIE na starcie
F4 (PWA), F10/F11 (dostępność), F5, J2/J3/J5 — realne, ale nie blokują pierwszych użytkowników.

## 🌍 WYPUSZCZENIE BEZ FIRMY (kierunek 2026-08-24)

Darmowe udostępnienie **nie wymaga rejestracji działalności** — działalność gospodarcza jest z definicji *zarobkowa* (Prawo przedsiębiorców, art. 3). Ścieżka na drobne pieniądze bez JDG to działalność nierejestrowana (art. 5, próg 75% minimalnego wynagrodzenia, brak działalności przez 60 mies.).

**Realne ryzyko to nie brak firmy, tylko reklama zakładów wzajemnych** (ustawa o grach hazardowych, art. 29) — dotyczy osoby fizycznej tak samo jak spółki. Serwis predykcyjny tego nie narusza (nie przyjmujemy zakładów). Stan na 24.08: **zero linków afiliacyjnych**, nazwy bukmacherów tylko jako lista wyboru w dzienniku („gdzie postawiłeś") = pole danych, nie promocja. **Nie dodawać afiliacji ani zachęt do gry.**

RODO obowiązuje niezależnie od formy prawnej — mamy konta, więc jesteśmy administratorem danych.

### Reklamy — sprawdzone 2026-08-24, wynik: NIE na starcie

**Art. 29 nie zabrania wszystkiego.** Reklama zakładów wzajemnych jest dozwolona dla operatorów
z zezwoleniem, na warunkach art. 29b: bez kierowania do małoletnich, bez łączenia gry z łatwą
wygraną, z obowiązkowym komunikatem o ryzyku i o posiadaniu zezwolenia. Ograniczenie godzinowe
6:00–22:00 dotyczy TV, radia, kin i teatrów — nie internetu. Problem w tym, że **warunki dotyczą
treści reklamy**, a przy sieci reklamowej nie kontrolujemy, co się wyświetli.

**AdSense: Polski nie ma na liście.** „Publisher Restrictions” dopuszczają reklamy na treściach
hazardowych w 17 krajach (AU, BR, CA, CO, FR, DE, GR, IE, IT, JP, MX, NL, PH, KR, ES, TR, UK, US).
Polski tam nie ma. Definicja „gambling content” mówi o treściach *umożliwiających* grę na pieniądze
(kasyna, bukmacherzy, „aggregator or affiliate sites that promote online gambling pages”) — my
niczego nie umożliwiamy i nie mamy afiliacji, więc literalnie się nie łapiemy. Ale polityka
reklamodawcza Google osobno wymienia „sports odds aggregator sites” jako treść ograniczoną,
a egzekwowanie AdSense bywa zachowawcze. Realne ryzyko: odrzucenie zgłoszenia albo ograniczone
wyświetlanie, bez możliwości odwołania.

**Da się zabezpieczyć, ale kosztem sensu.** AdSense pozwala per-witryna zablokować kategorię
„Gambling & Betting (18+)” (Brand Safety → Blocking Controls → Sensitive Categories). To zdejmuje
ekspozycję na art. 29, ale usuwa jedyną kategorię, która na takim ruchu płaci cokolwiek.

**Podatkowo reklamy są prostsze niż subskrypcja:** przychód osoby prywatnej z AdSense rozlicza się
jako „przychody z innych źródeł” w rocznym PIT, według skali. Bez zaliczek miesięcznych,
bez VAT-u, bez rejestracji VAT-UE.

**Wniosek:** przy dzisiejszym ruchu (≈0) reklamy dają zero złotych i niezerowe ryzyko, a psują
produkt, którego przewagą ma być uczciwość. Wracamy do tematu, kiedy będzie ruch — wtedy
subskrypcja na dziennik jest i tak lepszym interesem niż CPM.

- [ ] **L8 — (odłożone) reklamy.** Wrócić dopiero przy realnym ruchu. Jeśli tak: zablokować kategorię
  „Gambling & Betting (18+)”, nigdy nie dodawać afiliacji, a przychód liczyć jako „inne źródła” w PIT.
- [ ] **L9 — (opcjonalne, czyste) wsparcie dobrowolne.** Naffy / BuyCoffee zamiast reklam: zero polityk
  reklamowych, zero ekspozycji na art. 29, działa dla osoby prywatnej. Nie wpływa na treść produktu.

### Jeśli subskrypcja (rozważane 2026-08-24)

Działalność nierejestrowana obejmuje też sprzedaż — **nie trzeba zakładać firmy**. Warunki: brak działalności przez ostatnie 60 miesięcy oraz limit przychodu, który **od 2026 liczy się KWARTALNIE** (225% minimalnego wynagrodzenia, ok. 10 813,50 zł brutto — kwotę sprawdzać na bieżąco, zmienia się co rok). Liczy się wpłata brutto klienta, przed prowizją operatora. Do tego ewidencja wpłat i PIT-36 raz w roku.

**Merchant of Record vs własna bramka.** Lemon Squeezy / Paddle / naffy sprzedają formalnie we własnym imieniu i biorą na siebie VAT klientów z UE — jedna zbiorcza wypłata, zero rejestracji zagranicznych. Stripe daje pełną kontrolę, ale sprzedaż B2C do UE wymaga VAT-OSS, a sama prowizja Stripe (spółka irlandzka) to import usług → VAT-R z VAT-UE i miesięczne VAT-9M. Przy jednoosobowym projekcie MoR jest wyraźnie tańszy w papierologii.

- [ ] **L5 — DECYZJA: co dokładnie sprzedajemy.** Waży więcej niż forma prawna. Model **nie bije rynku** — zmierzone: 14.08 n=15 460, 52 podzbiory, **zero przeżyło holdout**; 24.08 wszystkie 6 kuponów serii 4 ma EV ujemne liczone prawdopodobieństwami NASZEGO modelu (−21,5% łącznie). Sprzedawanie „nasze typy wygrywają” byłoby sprzedażą czegoś, co według własnych pomiarów przegrywa. Kierunek z 21.07 (dziennik kuponów + śledzenie postępu) **da się sprzedawać uczciwie**: narzędzie do mierzenia SIEBIE, nie obietnica wygranych. Przy okazji bezpieczniejsze wobec art. 29.
- [ ] **L6 — pytanie do prawnika, nie do księgowej.** Płatny serwis z typami stoi bliżej zakazu reklamy i promocji zakładów wzajemnych (art. 29 ustawy o grach hazardowych) niż darmowe statystyki. Nie jest zakazany, ale przy pobieraniu opłat lepiej mieć to potwierdzone przed startem niż po.
- [ ] **L7 — ewidencja wpłat.** Prosty rejestr każdej wpłaty (data, kwota brutto) do pilnowania limitu kwartalnego. Da się wyprowadzić z webhooków operatora płatności.

- [x] ✅ **L1 — ZAMKNIĘTE 25.08. Blokada publikacji była MOJĄ POMYŁKĄ, nie wymogiem prawa.**

  24.08 wpisałem, że brak adresu pocztowego blokuje publikację, i wyceniłem to na skrytkę za 120 zł plus opóźnienie. **Czytałem art. 5 uśude bez definicji z art. 2.** Art. 5 nakłada obowiązki na **usługodawcę**, a art. 2 pkt 6 definiuje go jako osobę, która *prowadząc, chociażby ubocznie, **działalność zarobkową lub zawodową**, świadczy usługi drogą elektroniczną*. Serwis w całości nieodpłatny, bez reklam i bez afiliacji, tej przesłanki **nie spełnia**. Grzywna z art. 23 też dotyczy wyłącznie usługodawcy.

  RODO obowiązuje niezależnie od formy prawnej, ale wymaga „tożsamości i **danych kontaktowych**" administratora — imię, nazwisko i działający e-mail to spełniają. Adres pocztowy jest tam dobrą praktyką, nie literą przepisu.

  **Stan dokumentów:** §1.2 regulaminu i §1 polityki podają imię, nazwisko i e-mail, bez placeholderów. Skrytka **niepotrzebna**. To nie jest porada prawna — przy pierwszej realnej wpłacie potwierdzić u prawnika.

  **PRÓG, KTÓRY TO ODWRACA — zakodowany, nie zapisany na kartce:** reklamy (L8), subskrypcje/płatności (L5) albo afiliacja czynią działalność **zarobkową**, wtedy art. 5 stosuje się w pełni i adres staje się wymagany. Pilnuje tego `test_adres_wymagany_dopiero_gdy_serwis_zarabia` — gdy w regulaminie pojawi się znacznik zarobkowości, test zażąda adresu. Sam detektor ma 9 własnych testów, bo dwa razy pomylił się na naszym regulaminie: łapał „**reklamacje**" z §10 (tryb wymagany przez art. 8, nic wspólnego z zarobkiem) i „**Nieodpłatność**" z §5, czyli deklarację dokładnie odwrotną.

  **Mail:** działający `jakubgwiazdowski12@gmail.com` w obu dokumentach (dane operatora, reklamacje §10, żądania z RODO). Przenosiny na skrzynkę z własnej domeny — patrz L10, nie blokuje.

- [ ] **L10 — własna domena + mail z domeny.** Decyzja z 24.08. ⚠️ **Poprawka 26.08:** to zdanie brzmiało „nie zdejmuje wymogu adresu z L1 — skrytka dalej potrzebna" i było nieaktualne od **25.08** — L1 niżej jest **zamknięte**, adres pocztowy **nie jest wymagany**, dopóki serwis jest darmowy (art. 2 pkt 6 uśude — brak przesłanki działalności zarobkowej/zawodowej). Domena i mail projektowy to osobna, niezależna decyzja (wygoda/profesjonalizm, nie wymóg prawny).

  **Pułapka cenowa, ważniejsza niż cena startowa:** rejestracja .pl bywa za 5-10 zł, a odnowienie od 51 do 295 zł/rok. NASK bierze 40 zł netto hurtowo, więc uczciwe detaliczne to ~59-99 zł. **Sprawdzać cenę ODNOWIENIA, nie pierwszego roku.** Skrajny przykład z rynku: rejestracja 6,15 zł, odnowienie 246 zł.

  **WHOIS nie wycieka danych** — NASK domyślnie ukrywa dane osoby fizycznej, widać tylko rejestratora, daty i serwery nazw. Domena nie jest kanałem ujawnienia adresu.

  **Skrzynka musi UMIEĆ ODPISAĆ**, nie tylko odbierać — §10 wymaga odpowiedzi na reklamację w 14 dni. Samo przekierowanie (Cloudflare Email Routing) daje odbiór za darmo, ale odpowiedź wyszłaby z prywatnego Gmaila. Warianty: Zoho Mail free (prawdziwa skrzynka na domenie, 5 GB, ale bez IMAP/POP — tylko webmail/apka) albo przekierowanie + „wyślij jako" w Gmailu przez darmowy SMTP.

  **Uwaga, której strażnik NIE złapie:** regulamin i polityka są serwowane przez **API na Cloud Run**, nie przez Vercela — GUI linkuje je helperem `legalUrl()` wyliczanym z `VITE_API_BASE`. Samo wpięcie domeny w Vercela zostawi je pod `…run.app`, więc §1.1 mówiłby „footstats.pl", a dokument leżałby pod zupełnie innym adresem. Do rozstrzygnięcia przy zakupie: mapowanie domeny na Cloud Run (`gcloud run domain-mappings create`, opisane w `docs/cloud_migration.md`) albo przepisanie ścieżek `/regulamin` i `/polityka-prywatnosci` przez Vercela, żeby dokumenty wisiały pod główną domeną.

  **Przeprowadzka dotyka 7 plików** (regulamin §1.1, `gui/index.html` canonical+og:url, `sitemap.xml`, `robots.txt`, oba README, STATUS). Pilnuje tego `tests/test_adres_publiczny_spojny.py`: zmieniasz `ADRES_PUBLICZNY` na nową domenę, testy wypunktują każdy pominięty plik. Zweryfikowane symulacją — strażnik wskazuje wszystkie 7 plików, stary host i rozjazd w regulaminie.
- [x] **L2 — ZROBIONE 24.08.** §5 „Subskrypcje i płatności” zastąpione przez „Nieodpłatność Serwisu”: wprost, że nie ma opłat, sprzedaży, subskrypcji, reklam ani odesłań afiliacyjnych, a wprowadzenie odpłatności wymaga zmiany regulaminu w trybie §9. Usunięta definicja „Subskrypcja”, dodana definicja „Dziennik kuponów” z zastrzeżeniem, że Serwis nie pośredniczy w zawieraniu zakładów.
- [x] **L3 — ZROBIONE 24.08.** §7 nie ogranicza już odpowiedzialności do „opłat z ostatnich 30 dni” (przy darmowym = do zera). Zamiast tego zasady ogólne prawa polskiego plus klauzula, że nic w regulaminie nie ogranicza praw konsumenta z przepisów bezwzględnie obowiązujących. Dopisany też punkt mówiący wprost, że **model nie wykazuje przewagi nad kursami bukmacherskimi** — to samo, co mierzymy, powiedziane użytkownikowi.
- [x] **L4 — BYŁO BŁĘDNE, już zrobione.** Pierwotny wpis powstał z przejrzenia samego `admin_users.py`. W rzeczywistości istnieje `DELETE /api/auth/me` (anonimizuje username, kasuje e-mail, losuje hash hasła, `is_active = FALSE`; kupony i predykcje zostają dla rozliczeń pod zanonimizowanym userem), wystawione w GUI jako „Potwierdzam — usuń konto” w `SettingsView.jsx`. Publiczna rejestracja `POST /auth/register` oraz reset hasła też działają, a regulamin i polityka są linkowane ze stopki i z CookieConsent.

## ⚪ OPCJONALNE

- [ ] **Scrapery — ocena per-stabilność/anti-bot:** Soccer24 (klon FlashScore, skip), Meczyki/LiveScore (anti-bot), Transfermarkt (squad/value nie wyniki). 4 źródła już wpięte (AF/football-data.co.uk/FlashScore/TheSportsDB).

---

## 🚫 Zbadane → odrzucone (NIE wracać)

- **ImportanceIndex** (crude ±20%): A/B −0.1pp, high-stakes −0.59pp → ślepa uliczka. `core/standings.py` zostaje jako CECHY do ML.
- **LightGBM / własny model ML:** 51.6% (z kursami) < rynek 53.1% < baseline. Rynek nieprzekraczalny (jak literatura). `core/ml_features.py` zostaje jako infra. Jedyny owoc = reweight ensemble ku rynkowi.
- **Schedule-adjusted ratings** (M1 lever #5): offline A/B +0.20pp (szum, se~0.92pp), +57% wolniej. Flag `SCHEDULE_ADJUSTED_RATINGS` zostaje OFF; kod+7 testów jako infra.
- **FBref jako źródło xG** (sprawdzone 2026-07-29): HTTP **403 z normalnym User-Agentem**, a przez headless chromium wraca **strona challenge Cloudflare**. Przepuszczenie wymagałoby stealth/anti-detekcji — wysoki koszt utrzymania, kruche. NIE wracać bez nowego powodu.
- **StatsBomb open-data jako źródło xG** (sprawdzone 2026-07-29): API działa bez anti-bota, ale **nie nadaje się do tego projektu**. Twarde liczby: `matches.json` **nie zawiera xG** (tylko wyniki) — xG jest wyłącznie w `events/{match_id}.json` po **~2.6 MB na mecz**. Pokrycie to wyłącznie historia (najnowsze: Bundesliga 2023/24 = **34 mecze**, La Liga 2020/21, MŚ 2022), **zero sezonu bieżącego** → nie nakarmi live λ. Do walidacji offline próbka o 3 rzędy wielkości za mała (walk-forward chodzi na 25k+ meczów). Koszt ~90 MB za jedną niepełną konkurencję.

---

## 📨 API-Football — odwolanie WYSLANE 30.08 20:28

Konto `Gwiazdka09` / `jakubgwiazdowski12@gmail.com`, zawieszone od 01.08.
Mejl poszedl na `support@api-sports.io` — pytanie o powod i o to, co zmienic,
zeby konto wrocilo. Tresc i kontekst: `docs/robocze/2026-08-30-apifootball-odwolanie.md`.

- [ ] **Czekamy na odpowiedz.** Gdyby dopytali o ruch: mamy licznik zuzycia
  w aplikacji, cache dyskowy 24 h i logi produkcyjne z tym samym komunikatem
  codziennie od 01.08.
- **Potok NIE stoi juz na tym koncie** — sklady, absencje, sedzia i pozycje ida
  z FotMoba (30.08), a FlashScore przestal byc zablokowany za martwym AF.
  Powrot konta bylby cross-walidacja, nie warunkiem dzialania.

## 📡 INWENTARZ ŹRÓDEŁ — stan zmierzony 30.08

Sprawdzone na logach produkcyjnych (26-30.08) i sondami HTTP, nie z pamięci.

| źródło | technika | co daje | stan |
|---|---|---|---|
| football-data.co.uk | CSV | historia 40 lig → `full_dataset.parquet` | ✅ żyje |
| Bzzoiro | API | terminarz, ML, kursy | ✅ żyje |
| **FotMob** (nowe 30.08) | `requests` | przewidywany XI, absencje, sędzia+staty | ✅ żyje, flaga OFF |
| Understat | `requests` | xG, tabele lig | ✅ żyje (5 lig dziennie w logach) |
| odds_snapshot / The Odds API | API | kursy, snapshoty | ✅ żyje |
| FlashScore (mobi) | `requests` | wyniki | ✅ żyje |
| FlashScore (mecz) | Playwright | sędzia, absencje | ⚠️ **odblokowane 30.08** — stało za `continue` |
| TheSportsDB | `requests` | wyniki reprezentacji/turniejów | ✅ żyje |
| clubelo | `requests` | ratingi Elo | ✅ żyje |
| **SofaScore** | Playwright | forma, H2H, **kontuzje Z POZYCJĄ** | 🔴 **403 na każde zapytanie** |
| **API-Football** | API | składy, sędzia, kursy, wyniki | 🔴 **konto suspended od 01.08** |

- [x] ✅ **FlashScore odblokowany 30.08.** Wywołanie stało NIŻEJ w tej samej pętli
  co `continue` na braku meczu w API-Football, więc od zawieszenia konta AF nie
  odpalało się ani razu. Fallback zabezpieczony za martwym źródłem głównym.
  Dołożony limit `_MAX_FLASHSCORE_NA_PRZEBIEG = 6` (Playwright = przeglądarka
  na mecz); wcześniej koszt nie istniał, bo ścieżka była martwa.

- [x] ✅ **Pozycje odzyskane 30.08 — z FotMoba, nie z SofaScore.**
  `/api/data/teams?id=` oddaje skład pogrupowany (keepers/defenders/midfielders/
  attackers → G/D/M/F, 1:1 z kodami modelu). Smoke na żywym źródle: **37 z 37
  pewnych absencji dostało pozycję, zero bez dopasowania** (M=14, F=10, D=13).
  Dwustronna korekta λ ma wejście pierwszy raz od blokady SofaScore. Skład
  pobierany tylko dla meczów z absencjami, cache per drużyna.

- [ ] 🟡 **SofaScore: `HTTP 403` na KAŻDE wyszukiwanie drużyny**, także przez
  Playwrighta (logi joba 26-30.08: Villarreal, Liverpool FC, Wisła Płock,
  Nottingham Forest, Metz, Korona Kielce...). Skutek jest szerszy niż brak formy:
  **SofaScore to jedyne źródło kontuzji Z POZYCJĄ**, a `injury_lambda_factors`
  klasyfikuje właśnie po pozycji (`_POZ_ATAK` / `_POZ_OBRONA`). Bez pozycji
  `injuries_home`/`injuries_away` są puste, więc `_apply_injury_corrections`
  **nigdy nie odpala** — cała dwustronna korekta λ za kontuzje jest martwa.
  **Pozycje załatwione inaczej (patrz punkt wyżej), więc to już nie blokuje
  modelu.** Zostaje strata formy i H2H. Zmierzone 30.08: `requests` dostaje 403
  także na stronie głównej, Playwright lokalnie 200, Playwright z Cloud Runa 403
  — czyli blokada dotyczy klientów nieprzeglądarkowych ORAZ zakresu datacenter.
  Nagłówki, stealth i rozgrzewka sesji nie pomagają (sprawdzone wszystkie
  kombinacje). Realna opcja to tylko inne wyjście sieciowe albo inne źródło formy.

## ✅ NAPRAWIONE 31.08 — faza final znowu buduje kupony

Kupony `phase='final'` stanęły **15.08**. Przyczyny były DWIE i obie milczały.

**1. Wycofana nazwa modelu — TRZECI raz ten sam kształt.** Log joba, codziennie:

```
Wyspecjalizowany typer Groq zawiodl (NotFoundError: 404 - The model
`llama-3.1-8b-instant` does not exist) - przechodze na fallback zapytaj_ai
```

Naprawa z 22.08 objęła tylko `ai/client.py`. `ai/analyzer.py` i `ai/trainer.py`
miały **własne, zaszyte** nazwy w PIĘCIU miejscach — dwa żywe wywołania
w analyzerze, dwa w trainerze i etykieta Langfuse raportująca nieprawdę. Żadne
nie ustawiało `reasoning_effort` ani nie skalowało `max_tokens`, więc sama
podmiana nazwy i tak spaliłaby budżet `gpt-oss` na rozumowanie.
Nazwa mieszka teraz w `client.parametry_modelu()`; strażnik
`test_nazwa_modelu_nie_jest_zaszyta_poza_clientem` znalazł trzy z pięciu miejsc,
o których nie wiedziałem.

**2. Prompt systemowy walczył z promptem użytkownika.** `SYSTEM_TYPER` kończył
się blokiem „JSON SCHEMA (OBOWIĄZKOWY)" opisującym POJEDYNCZY typ, a
`ai_analiza_pewniaczki` parsuje `top3`/`kupon_a`. Żywy dowód po naprawie punktu 1:
model oddał `{"typ": "1", "kurs": 1.95, "risks_analysis": [...]}`.
Dlaczego dopiero teraz: `llama-3.1-8b` słabo trzymała się promptu systemowego,
`gpt-oss-120b` trzyma się go ściśle — **podmiana modelu zmieniła, który prompt
wygrywa**. Konflikt istniał wcześniej, ale był nieszkodliwy.

Dowód końcowy (żywy Groq, realna ścieżka): fallback A1 nieużyty, `top3=3`,
`kupon_a` z kursem łącznym.

**Przy okazji, dwie ścieżki obiecujące odporność bez pokrycia w kodzie:**
`_pobierz_podobne_mecze` (RAG) zabijał całą analizę przy padniętej bazie mimo
komentarza „nie blokuje predykcji"; `_wymusz_40pct` wywalał się na
`"kupon_a": null`, bo `dict.get(k, {})` nie działa, gdy klucz istnieje z `None`.

**Wdrożone:** obraz `sha256:8165e33f…` tag `77df454ec`, zbudowany 31.08 18:17.

- [ ] **Do sprawdzenia po przebiegu 01.09 11:00 UTC:** czy w `coupons` pojawił się
  wiersz `phase='final'` (pierwszy od 15.08).

## 🟢 FOOTSTATS_TEAM_NEWS WŁĄCZONE 31.08

Ustawione w trzech miejscach (`footstats-final`, `footstats-evening`,
`footstats-api`) przez `--update-env-vars`; liczba kluczy env wzrosła dokładnie
o 1 w każdym (14→15, 14→15, 18→19), więc nic nie zginęło — kontrola po
incydencie z `JWT_SECRET` 27.07.

Smoke lokalny na żywym FotMobie tego samego dnia, 3 kandydaci:
3/3 wzbogacone, wszystkie `predicted`, sędziowie ze statystykami
(`avg_red` 0,026-0,081 na mecz), absencje **z pozycją** → `injuries_*`
wypełnione → dwustronna korekta λ ma wejście. Udziały w golach dopasowane
w `player_db` dla **7 z 14** absencji — licznik `absencje_bez_udzialu` działa.

Nowa wartość `lineupType` u źródła: **`standard`** (skład faktyczny, nie
prognoza). DTO obsługuje poprawnie — `sklad_jest_prognoza` daje `False`.

- [x] **Sprawdzone 31.08 wieczorem** — `team-news: 3/4 kandydatow wzbogaconych
  (1 predicted, 2 lastStarting11)` w pełnym przebiegu fazy final (dry-run).
  Wcześniejszy smoke na 16 kandydatach Bzzoiro: **12/16**, składy 11+11,
  absencje z pozycjami, sędziowie ze statystykami. Ścieżka żyje end-to-end.

---

## 🔧 NAPRAWIONE 31.08 wieczorem — cztery ciche no-opy

Znalezione **smoke'em na 12 żywych kandydatach**, nie z przeglądu kodu.

1. **`edge_absencje` zawsze `None`.** `market_p_over` nie było ustawiane
   NIGDZIE w `src/` — tylko czytane w `_policz_edge_absencji` i podstawiane
   ręcznie w testach. Pole istniało wyłącznie w testach, więc całe porównanie
   z rynkiem nie działało. Rynek liczony teraz z kursów kandydata
   (`over_2_5`/`under_2_5`) przez `devig_two_way`. Sam kurs Over nie wystarcza:
   `1/kurs` zawiera vig → edge wychodziłby systematycznie zaniżony.

2. **SofaScore kasował absencje FotMoba.** Kolejność: FotMob zapisuje
   `injuries_*` z pozycjami (`daily_agent:1010`) → `_wzbogac_forme_top`
   nadpisuje je BEZWARUNKOWO (`:1032`) → korekta λ czyta puste (`:1036`).
   Zablokowany SofaScore zwraca `_empty_form` z `injuries: []`, nie wyjątek.
   Objawem byłoby zero korekty przy poprawnie pobranych składach.

3. **`0/46` w KROK 3b znaczyło trzy rzeczy naraz** — padnięte źródło, rozjazd
   nazw albo stojący rynek. Pierwsze dwa dostają teraz WARNING. Funkcja nie
   miała dotąd żadnego testu.

4. **`--dry-run` miał ścieżkę ZAPISU do prod DB.** `get_current_bankroll` woła
   `init_bankroll_tables`, które INSERT-uje brakujący wiersz — przed każdą
   bramką dry-run. Plus `get_loss_streak` i `check_weekly_alert` wymuszały
   połączenie z bazą. Dry-run bierze teraz neutralne wartości z configu.

**Bonus:** furtka `FOOTSTATS_ALLOW_LIVE=1` w `guard_live_ops` nie działała
w formie, którą sam hook podawał w komunikacie błędu — czytał `os.environ`
własnego procesu, a prefiks `VAR=1 cmd` tam nie dociera. Hook nie miał
żadnego testu, mimo że jest bramką przed podwójnymi kuponami na Telegramie.

### Zmierzone i ODRZUCONE (nie wracać)

Podejrzenie, że konflikt „prompt systemowy vs prompt użytkownika" psuje też
trzy pozostałe wywołania `_zapytaj_typera`. **Zmierzone na żywym Groqu 31.08
— NIE psuje:**

- **scout** (`oceń_kupon`): dostał prozę z linią `SCORE: 48`, sparsowaną poprawnie;
- **superbet betbuilder**: dostał **dokładnie swój** schemat
  (`ocena_ogolna`/`komentarz`/`betbuilder_wykryty`), nie systemowy.

Konflikt gryzie tylko wtedy, gdy OBIE strony żądają JSON-a — tak było w głównej
ścieżce kuponu (`top3`/`kupon_a`) i to jest już naprawione. Gdy prompt
użytkownika prosi o inną modalność (proza + linia `SCORE:`), wygrywa on.

### Zamknięte tego samego wieczoru

- [x] **`--dry-run` przechodzi CAŁY potok bez bazy.** Zmierzone: przebieg
  dojechał od KROK 0 do `RUN SUMMARY`, zbudował KUPON A (`Kurs łączny 1.57`)
  i zaraportował `DRY-RUN: pominięto zapis kuponu do DB`. Po drodze zamknięte
  trzy blokady: odczyt sędziego (teraz degraduje z jednym ostrzeżeniem),
  saldo bankrolla, oraz **Krok 0d, który PISAŁ do bazy** przez `upsert_referee`
  także w podglądzie.
- [x] **KROK 3b rozstrzygnięty — i przyczyna była inna niż stojący rynek.**
  `BzzoiroClient._get` trzyma odpowiedzi w cache'u RAM, `CACHE_TTL_MIN = 30`,
  a KROK 1 i KROK 3b chodzą w TYM SAMYM procesie kilka-kilkanaście minut po
  sobie. Drugie zapytanie trafiało w cache i porównywało dane samo ze sobą —
  `0/46` było gwarantowane konstrukcją.

  **Pomiar po naprawie** (11 meczów, cache czyszczony przed każdą próbką):

  | okno | zmienionych |
  |------|-------------|
  | 5 min | 0/9 |
  | 10 min | **2/9** |
  | 15 min | 2/9 |

  Kursy ruszają się, ale skromnie: obie zmiany dotyczyły **wyłącznie `btts`**
  (2.11→2.12 i 1.93→1.91), a 1X2 i Over/Under nie drgnęły przez 15 minut.
  Krok zostaje — teraz faktycznie działa, a nowy log INFO zacznie zbierać
  `updated` przez kolejne dni. Próba mała i z niedzielnego wieczoru
  (mecze południowoamerykańskie), więc to jeden punkt, nie wniosek.

### ⚠️ KOREKTA PRZESŁANKI — „susza kuponów final" była opisana za mocno

Sprawdzone w `coupons` 01.09, bo cała ta linia pracy zakładała regresję:

| faza | ile | okres |
|---|---|---|
| `system` | **296** | 31.07 – 31.08, codziennie |
| `final` | **7** | 05.08 – 15.08 |
| `manual` | 6 | 24.08 |

Z tych 7 ostatni (15.08) ma `kupon_type=manual` — nie pochodzi z potoku.
**Automatycznych było PIĘĆ, na DWÓCH dniach** (05.08 i 10.08). Kursy: 5.10,
23.70, 54.95, 3.43, 77.29. Statusy: LOST, VOID, VOID, LOST, VOID.

Czyli nie było stałego strumienia, który by się urwał. Były dwa dni z kuponami
o kursach akumulacyjnych — same przepadły albo zostały unieważnione.

To nie unieważnia trzech naprawionych błędów (wycofana nazwa modelu, konflikt
schematu, budżet TPM) — one realnie blokowały ścieżkę. Ale cel „kupon final
ma powstawać codziennie" **nigdy nie był stanem, do którego wracamy.**

### Czwarta przyczyna: model ODMAWIA i ma rację

Sonda na realnym prompcie (01.09). Model oddał kompletny, poprawny JSON:

```
"top3": [],
"ostrzezenia": "pewnosc (52% dla 1) jest nizsza niz wymog 60% dla
  pojedynczej nogi. Nie mozna skonstruowac zadnego sensownego kuponu."
```

Reguła `Every leg: pewnosc_pct >= 60%` stoi w `SYSTEM_TYPER_BAZA`
(`prompts.py:260`). Kandydaci po filtrach wartości mają `pw` około 52%.

**ROZSTRZYGNIĘTE 01.09 przez użytkownika: obniżyć do 40-50%.**
Wdrożone **50%** jako `KUPON_MIN_PEWNOSC_PCT` (pokrętło, nie stała).

Dlaczego 50, a nie 45/40: linia obok w TYM SAMYM prompcie mówi `<50%: avoid`.
Niższy próg postawiłby dwie reguły w sprzeczności — a zmierzone zachowanie
przy 40% było dokładnie takie, model zaczynał cytować progi, których nikt
nie ustawił (63%).

Zmierzone na żywym modelu (liczba typów w `top3`, jedna próbka na komórkę,
warunek `4 slips` poluzowany jednakowo we wszystkich wierszach):

| próg | 1 mecz | 3 mecze | 5 meczów |
|---|---|---|---|
| 60 | 0 | 0 | 3 |
| **50** | **1** | **3** | 3 |
| 45 | 1 | 3 | 3 |
| 40 | 0 | 1 | 3 |

Druga reguła blokowała niezależnie od progu: `4 slips = 4 different matches`
przy 1-3 kandydatach jest niewykonalna. Teraz model wypełnia tyle kuponów,
ilu ma kwalifikujących się meczów. **Zakaz akumulatorów zostaje** — poprzednie
pięć kuponów `final` miało kursy do 77 i wszystkie przepadły lub zostały
unieważnione.

- [ ] **Zmierzyć skutek po ~20 rozliczonych kuponach.** Obniżenie progu ma
      zwiększyć liczbę kuponów; czy nie kosztem trafności — nie wiadomo,
      i tego nie da się przewidzieć, tylko rozliczyć.

Log przestał już mylić: świadoma odmowa idzie na INFO z zacytowanym powodem,
awaria warstwy LLM zostaje WARNING.

### ✅ KUPON LLM SKLADA SIE — 01.09, po czterech naprawach

Zweryfikowane offline na zywym Groqu (pelny potok, `--dry-run`):

```
KUPON A: Bromley vs Leyton Orient | typ 1 | kurs 2.50 | pewnosc 55% | Kelly 6.3 PLN
         Kurs laczny 2.50 | Wygrana netto 22.00 PLN | Szansa 55.0%
KUPON B: Kurs laczny 1.86 | Wygrana netto 8.18 PLN  | Szansa 53.0%
```

**Zero fallbacku A1** — typy pochodza z LLM-a, nie z modelu. Noga ma pewnosc
**55%**, czyli dokladnie to, co prog 60% blokowal.

Cztery przyczyny, kazda zmierzona osobno, zadna zgadnieta:

1. wycofana nazwa modelu zaszyta poza `ai/client.py` → 404 pochlaniany fallbackiem
2. prompt systemowy narzucal schemat, ktorego wolajacy nie parsuje
3. sufit `max_tokens` liczyl sie tylko z wyjscia → 413 przy 3 kandydatach
4. prompt zadal CZTERECH kuponow niezaleznie od liczby meczow → odpowiedz sie
   urywala, a siec ratunkowa (`_kontynuuj_uciety_json`) sama wpadala w 413,
   bo tez nie liczyla wejscia

- [ ] **Potwierdzic na produkcji.** Offline dziala; wiersz `phase='final'`
  w `coupons` bedzie pierwszy od 15.08. Nastepny przebieg planowy: 09:00 UTC.

### Naprawione 01.09 — `kalibracja-rozlicz` klamal w monitoringu

`status.code: 4` przy zdrowym przebiegu. Handler jest `def`, wiec leci w watku
puli — `asyncio.wait_for` anulowal korutyne, nie watek, a praca konczyla sie
30 minut po tym, jak Scheduler dostal 504 z naszego `_TimeoutMiddleware`.

Dopisanie sciezki do `_LONG_RUNNING_PATHS` NIE wystarczyloby: 120 s przy pracy
trwajacej 30 minut i `attemptDeadline` o maksimum 30 minut. Endpoint oddaje
teraz 202 od razu, praca leci w tle, liczniki ida do logu. Niezmiennik
"awaria nie moze byc cicha" zostaje — zmienil sie kanal na ERROR w logu.

### Limit TPM — zmierzone na produkcji 31.08 20:25

Przebieg `footstats-final-h6gg8` odpalony ręcznie. Wynik: **kupon `phase='final'`
dalej NIE powstał** (`coupons` = 0 wierszy). Ale przyczyna jest już policzona,
nie zgadywana:

```
Typer Groq: 413 — ponawiam z promptem krotszym o polowe    ← moja obsługa 413 zadziałała
[AI] Model jezykowy nie zwrocil typow — 3 typow z modelu   ← i to nie pomogło
Faza final: kupon NIE zostal zapisany (kupon_a.zdarzenia puste)
```

413 przyszło przy **trzech** kandydatach, więc masa nie siedziała w opisach
meczów. Rozkład promptu (`szacuj_tokeny`):

| składnik | tokeny |
|---|---|
| `SYSTEM_TYPER_BAZA` | 2475 |
| kalibracja | 86 |
| statystyki lig | 484 |
| **prompt systemowy razem** | **3045** |
| `effective_max_tokens(1500)` | **3750** ← 47% całego limitu |
| limit TPM | 8000 |
| **zostaje na opisy meczów** | **1205** |

`effective_max_tokens` liczyło sufit jako 75% TPM patrząc **wyłącznie na wyjście**,
a TPM obejmuje wejście i wyjście razem. Ratunek przez przycinanie promptu
użytkownika bił w złe miejsce — wycinał opisy meczów, czyli jedyną rzecz,
której model potrzebuje, i zostawiał balast. Stąd „nie zwrócił typów"
tuż po **udanym** ponowieniu.

Naprawione: `effective_max_tokens(base, model, prompt_tokens)` domyka rachunek,
typer podaje sumę systemowego i użytkownika. Podłoga 400 tok.

### Zostaje otwarte

- [x] ~~**Prompt systemowy typera waży 2475 tok**~~ ✅ **1463 tok (−41%)**, 01.09.
  Nie przez cięcie na ślepo: wyleciały wyłącznie instrukcje dotyczące rynków,
  których NIE wyceniamy (handicap, kartki, rożne, BetBuilder, Over 1.5, 1X/X2)
  oraz cała era AKO (pasma kursowe z progiem 1.80, budowanie akumulatora,
  stawki dla kuponów 11-14x). Każda z tych sekcji uczyła model typować coś,
  co bramka `TYP_DO_ODDS_KEY` i tak kasuje jako halucynację — więc usunięcie
  ich POPRAWIA jakość typów, zamiast ją ryzykować.
- [x] ~~**`SYSTEM_TYPER_BAZA` niesie CZWARTĄ kopię reguł AKO**~~ ✅ usunięta 01.09
  razem ze skróceniem promptu (pozycja wyżej). Oryginalna notatka poniżej.
  ~~**Czwarta kopia** — `ZASADA SINGLA:
  single dozwolony tylko gdy kurs >= 1.80`, `== BUDOWANIE KUPONU AKO ==
  Optymalna liczba: 4-6 zdarzen`, `Max 6 nog w AKO`. Przeczy wprost blokowi
  ZAKAZÓW (`EXACTLY 1 leg`, `No accumulators`, `odds < 1.20: NEVER`).
  01.09 zmierzone: **nie blokuje** — po naprawie kursów rynków kupon powstał
  mimo tej sprzeczności, więc nie ruszam jej pod presją. Ale to ten sam
  materiał, który trzeba i tak wyciąć przy skracaniu promptu systemowego
  (pozycja wyżej) — wycięcie sekcji AKO załatwia oba naraz.
- [ ] **Zweryfikować kupon `phase='final'` po najbliższym przebiegu.** Nadal
  zero od 15.08 — pięć przyczyn naprawionych (nazwa modelu, konflikt schematu,
  budżet TPM, `np.float64` w SQL, brak kursów rynków >50% w opisie meczu),
  żadna jeszcze nie potwierdzona zapisanym kuponem na produkcji.

## 🔴 ZNALEZIONE 30.08 — faza final nie zapisuje kuponu OD 16.08

**Zmierzone na produkcji, nie podejrzenie.** Kupony `phase='final'` w bazie kończą
się na **15.08**. Job chodzi codziennie (`model_log` ma 10-49 wierszy dziennie,
godzina 9 UTC), więc potok z zewnątrz wygląda zdrowo.

Lejek z logów joba (29.08):

```
Bzzoiro: 40 kandydatów w oknie 72h
Pre-filtr lig (blacklist):      40 → 33
Pre-filtr value bet (EV/Kelly): 33 → 6
Final enrichment:              0/6 kandydatów wzbogacono
[AI] Model jezykowy nie zwrocil typow — 3 typy zbudowane z modelu
RUN SUMMARY: kandydaci=40, po filtrach=6, System kupony=0
```

- [x] ✅ **Cisza załatana 30.08.** Zapis stał za gołym `if zdarzenia_db:` bez gałęzi
  `else`; odrzucenie przez próg i udany zapis były logowane, a jedyny NIElogowany
  przypadek okazał się tym, który zachodzi codziennie. `_zgloś_brak_kuponu_do_zapisu`
  rozróżnia „typy są, kuponu nie ma" od „zero typów". 5 testów, 3 mutacje.

- [x] ✅ **`Final enrichment: 0/6` załatane 30.08** — FotMob zastąpił zawieszone
  API-Football (`scrapers/teamnews/`). Flaga `FOOTSTATS_TEAM_NEWS` nadal **OFF**.

- [ ] 🔴 **NIENAPRAWIONE: warstwa LLM codziennie nie zwraca struktury kuponu.**
  `[AI] Model jezykowy nie zwrocil typow` leci w każdym przebiegu od 16.08.
  Fallback A1 (`typy_awaryjne_z_modelu`) ratuje TYPY — trafiają do `predictions`,
  stąd 2-7 wierszy dziennie — ale nie buduje `kupon_a.zdarzenia`, więc kupon nie
  powstaje. `GROQ_MODEL=openai/gpt-oss-120b` jest ustawiony na jobie.
  Do sprawdzenia: czy `gpt-oss-120b` dostaje `reasoning_effort=low` (bez tego
  model zużywa budżet na rozumowanie i nie dochodzi do odpowiedzi), oraz czy
  prompt/parser oczekuje kształtu, którego ten model nie produkuje.
  **To jest teraz największy pojedynczy dławik potoku** — model liczy 40 meczów
  dziennie, a kupon nie powstaje ani razu.

- [ ] **`system_paper.py:170` wpisuje `int(prob)` do kolumny `decision_score`.**
  Kolumna nazwana „decision score" trzyma prawdopodobieństwo modelu, więc rozkładów
  faz `system` i `final` nie wolno porównywać wprost. Myli przy każdej analizie —
  kosztowało to jeden błędny wniosek 30.08. Zmiana nazwy wymaga migracji.

## 🚨 AWARIA 16-22.08 — Groq wycofał model (naprawione 22.08)

**Potok stał 6 dni przy `exit=0`.** `llama-3.1-8b-instant` zniknął z API Groqa →
404 NotFoundError → brak odpowiedzi → zero predykcji. Dostawca nie ostrzegł.

### ⚠️ ZNALEZIONE PRZY OKAZJI — Groq zmyśla pewność
Zmierzone (3 próby na zestaw, `gpt-oss-120b`):

| dane wejściowe | wynik |
|---|---|
| żaden rynek nie sięga 60% | `top3=0` · `top3=3 [68,62,65]` · `top3=3 [71,68,66]` |
| rynki powyżej 60% | `top3=3` za każdym razem |

Gdy dane nie dają żadnego typu powyżej progu, model **albo poprawnie zwraca pustkę,
albo wymyśla pewności** (68%, 71%) nieistniejące w danych. Losowo, ~1 na 3.

**To NIE jest groźne dla typów** — potok i tak nadpisuje `pewnosc_pct`
prawdopodobieństwem modelu (`_nadpisz_pewnosc_modelem`), podmienia kurs na realny
(KROK 4) i nadpisuje tip argmaxem (`GROQ_TIP_OVERRIDE`). Groq jest tylko warstwą
opisu, nie decyduje.

**Groźne jest co innego:** gdy Groq zwróci pustkę, przebieg zapisuje ZERO predykcji —
mimo że Poisson policzył je niezależnie. Potok jest uzależniony od LLM-a w tym,
żeby *wypisał listę*, choć typy powstają bez niego.

### 🔎 ZNALEZIONE NA PIERWSZYM PRZEBIEGU PO A1 (23.08, `footstats-final-pptp4`)

Przebieg planowy 11:00: 32 kandydatów → 14 po filtrach → Groq odpowiedział poprawnie
→ **5 predykcji w bazie**. A1 słusznie się nie uruchomił. Wyszły trzy inne rzeczy.

- [x] ✅ **D9 — 20 kuponów z 15.08 miało zniknąć po cichu. ZMIERZONE I ZAŁATANE 24.08.** Wisiały ACTIVE z wszystkimi nogami `result: null`. Mecze miały 9 dni, `HORYZONT_ZRODEL_DNI = 7`, więc żadne źródło już ich nie oddawało; 25.08 mijało `VOID_AFTER_DAYS = 10` i wszystkie 20 wypadłyby z accuracy oraz ROI.

  **Sam VOID był poprawny** — wyniku naprawdę nie było skąd wziąć. Suchy przebieg to potwierdził: rozliczyło się 5 kuponów, wszystkie z dzisiejszej puli (Osasuna, Botoșani, Bologna, Brøndby, Malmö), a żaden z 15.08. Błędem była cisza: ścieżka „dogrywka/karne" woła `log.warning`, ścieżka „brak wyniku po N dniach" robiła wyłącznie `print` pod `verbose`, a obie zliczały się do tego samego `voided`. Nie dało się odróżnić serii dogrywek od awarii źródeł.

  **Naprawione:** osobny licznik `voided_brak_wyniku`, `log.warning` z numerem kuponu i meczem, nowy alarm `kupony_przepadly()` podpięty do `/cron/settle` i wystawiony w odpowiedzi endpointu. Alarm jest **niezależny** od `rozliczanie_stoi`: tamten pyta „czy coś, co JESZCZE da się zdobyć, nie zostało rozliczone" i dla tych kuponów milczy poprawnie — właśnie dlatego przepadały bez sygnału. 8 testów.

  **Hipoteza, która się NIE potwierdziła:** że selekcja bierze ligi spoza pokrycia źródeł. `_pre_filtruj_ligi` istnieje i działa (dziś ciął 25 kandydatów → 6), a dzisiejsze mecze z tych samych źródeł rozliczyły się bez problemu. Prawdziwa przyczyna to udokumentowane w `rozliczanie_stoi` osiem dni `settled: 0` (16–23.08) przy wynikach **wciąż w zasięgu** — zanim ktokolwiek zauważył, okno się zamknęło.

- [x] ✅ **D10 — źródła wyników: trzy naprawy, jeden realny bug. 25.08.**

  **1. `Sheffield United` == `Sheffield Wednesday` (0.800) i `Bristol City` == `Bristol Rovers` (0.696).** To NIE było szukane — strażnik nowych testów złapał to przy okazji. Oba wyniki **powyżej progów rozliczeń** (0.6 w `evening_agent`, 0.70 w `_znajdz_wynik`), czyli wynik jednego klubu mógł rozliczyć kupon na drugi. Mechanizm: aliasy skracają nazwy do `sheffield weds` / `bristol rvs`, a te skróty nie były członami odróżniającymi, więc reguła „ta sama baza + różne człony = różne kluby" **w ogóle się nie odpalała** i decydował wspólny przedrostek. Ten sam błąd co naprawiany 31.07, wpuszczony innymi drzwiami — nie przez listę sufiksów, tylko przez aliasy. Naprawione: `wednesday` do `_ROZROZNIAJACE`, `rvs`/`weds` do `_ROZ_SKROTY`. Oba spadły do 0.00.

  **2. Alias `Bolton Wanderers` → `Bolton` — DODANY I WYCOFANY tego samego wieczoru.** Suita wykazała, że `test_normalize_kolizje.py` **wprost zabrania** tego sklejenia, traktując je tak samo jak `Newcastle United`/`Newcastle`, `Cardiff City`/`Cardiff`, `Ipswich Town`/`Ipswich`. To świadoma reguła fail-closed z 31.07: bez listy klubów nie da się odróżnić „Bolton" (jednoznaczne) od „Manchester" czy „Sheffield" (po dwa kluby), więc odmawiamy wszystkich krótkich form.

  **Kod jest w tym punkcie wewnętrznie sprzeczny** — komentarz w `normalize.py` sugeruje alias dla Boltonu, test go zakazuje. Nie rozstrzygałem tego przy okazji, w module z historią błędnych rozliczeń, dla jednego kuponu za 2 zł. **Do decyzji osobno:** jawna, przejrzana lista aliasów dla jednoznacznych krótkich form (Bolton, Cardiff, Ipswich, Newcastle) kontra utrzymanie reguły ogólnej. Koszt reguły jest zmierzony i spisany w `test_kolizje_skrotow_klubow.py`.

  **3. `E2`/`E3`/`EC` do `KODY_LIG`.** Pobieraliśmy 10 dywizji, z Anglii tylko Premier League i Championship, choć selekcja typuje kluby z League One/Two. Dla 15.08: **25 → 61 meczów**.

  **Efekt na przepadających kuponach: 2 z 20 odzyskane** (#122 i #141, oba przegrane) zamiast zera. #124 był wygrany i przepada przez regułę krótkich form — to zmierzona cena tej reguły. Reszta to Carabao Cup i mecze azjatyckie, których CSV nie obejmuje.

  **Licznik kandydatów bez nazwy ligi — hipoteza OBALONA.** Podejrzewałem, że puchary wchodzą do kuponów przez udokumentowany wyjątek „kandydaci bez nazwy ligi są zawsze zachowywani". Pomiar tego samego dnia: 48 kandydatów → 44 odrzucone, w tym **Carabao Cup (20)**, a ostrzeżenie o omijaniu whitelisty **nie padło ani razu**. Filtr działa, flaga `LIGA_WHITELIST_ENFORCE` jest włączona (nieustawiona w env jobu = domyślne 1), a `_pre_filtruj_ligi` woła zarówno `cloud_draft`, jak i `system_paper`. **Jak 20 pucharowych kuponów powstało 15.08 — nie wiem.** Licznik zostaje jako WARNING i rozstrzygnie, jeśli się powtórzy.

- [ ] **D11 — model pokrywa 10% tego, na czym typujemy. ZMIERZONE 25.08, DIAGNOSTYKA WDROŻONA, decyzja otwarta.**

  `/cron/draft` melduje `model_source: poisson-dc`, bo `_wykryj_model_source()` sprawdza **wyłącznie, czy parquet się ładuje**. Realnie, z `model_log` (etykieta jest per mecz i uczciwa — `quick_picks.py:336`):

  | data | poisson-dc | bzzoiro-ml | Poisson |
  |---|---|---|---|
  | 25.08 | 2 | 19 | **9%** |
  | 24.08 | 7 | 18 | 28% |
  | 23.08 | 19 | 29 | 39% |
  | 20.08 | 11 | 38 | 22% |

  Przebieg na żywo po wdrożeniu logu: **„Poisson policzył 5 z 48 meczów (10%). Powody: `predict_match: brak wyniku`: 43"**.

  **To nie jest wyjątek ani awaria** — licznik wyjątków jest pusty. `predict_match` po prostu nic nie zwraca dla 43 z 48 par. Przyczyna jest strukturalna: selekcja bierze fixtures Bzzoiro z całego świata (chińska, japońska, brazylijska, turecka), a parquet Poissona zna głównie czołowe ligi europejskie. **Dwa różne wszechświaty meczów, nakładające się w 10%.**

  Do 25.08 było to całkowicie niewidoczne: handler blendu to było gołe `pass`, a `quick_picks.py` **nie miał nawet loggera**. Naprawione — log zbiorczy raz na przebieg (nie per mecz, bo to byłby szum), z liczbami i powodami; osobny WARNING gdy parquet nie wstaje wcale i Poisson pada dla całego przebiegu.

  **Decyzja do podjęcia, nie do zaimplementowania od ręki:** albo zawęzić selekcję do lig, które model zna (mniej kuponów, ale liczonych naszym modelem), albo rozszerzyć dataset o ligi spoza Europy, albo świadomie przyjąć, że większość kuponów liczy Bzzoiro-ML i przestać nazywać to „naszym modelem". Wiąże się z Celem B.

  **POMIAR 28.08 — ta sama luka widziana od strony `factors`, i ostrzejszy.** Pytanie brzmiało „dlaczego `predictions.factors` są puste". Odpowiedź: **nie są** — 9 z 255 wierszy ma wartość (5× `TWIERDZA`, 4× `ZEMSTA`), więc łańcuch RAG z P3/C działa. Puste są dlatego, że **nie mamy historii drużyn, na które typujemy**:

  | pokrycie pary w parquecie (244 pliki, 1062 drużyny) | n | puste `factors` |
  |---|---|---|
  | obie drużyny znane | 35 | 26 (74%) |
  | jedna znana | 57 | 57 (**100%**) |
  | **obie nieznane** | **163** | 163 (**100%**) |

  **64% predykcji dotyczy par, których obu drużyn nie ma w historii ani razu.** Największe ligi w `predictions`: World Cup 2026 (46), Brasileirão Serie B (44), Botola Pro (38), International Friendly (29), USL Championship (15). Żadnej z top-5 europejskich. Kontrola na realnej historii Premier League (n=400, ten sam kod `wyciagnij_faktory`): **31% meczów dostaje niepusty `factors`** (TWIERDZA 20%, ZEMSTA 6,8%, PATENT 5,2%) — czyli dokładnie tyle, ile widzimy w kubełku „obie znane" (26%). Kod robi swoje wszędzie tam, gdzie ma z czego.

  **Dwa tagi są martwe STRUKTURALNIE, nie przez przypadek:** `ROTACJA` i `ZMĘCZENIE` zapaliły się 0 razy na 400 meczach. `ROTACJA` wymaga kolumny `competition` (`fatigue.py:79`), której dataset football-data nie ma; `ZMĘCZENIE` wymaga poprzedniego meczu w oknie godzinowym, a terminarze ligowe go nie dają. Statusy `ImportanceIndex` są puste świadomie (`quick_picks.py:377`, TODO A1). Realnie mamy **3 tagi z 5**, i tylko na meczach z historii.

  **Konsekwencja dla decyzji wyżej:** „rozszerzyć dataset" i „zawęzić selekcję" to nie są równoważne opcje kosmetycznie — bez jednego z nich RAG uczy się z 3,5% predykcji, a nie z 31%.

- [x] **A4 — ZAMKNIĘTE 28.08 bez ruszania proda. Wpis był nieaktualny, a liczba obok BŁĘDNA.**
  Sprawdzone na produkcji (read-only): **zero** wierszy z nietypowym `actual_result`
  (wzorzec `^[0-9]+-[0-9]+`) i **zero** z `tip_correct IS NULL` mimo zapisanego wyniku.
  Martwy wiersz `2 (wygrana gościa)` zniknął przy backfillu `uzupelnij_tip_correct`
  z 27.08 — nie ma czego sprzątać.
  ⚠️ **„3 wiersze z `odds_verified=0`" to była pomyłka rzędu wielkości.** Realnie:
  **236 z 257** predykcji (92%) ma kurs niezweryfikowany, z czego **146 jest już
  rozliczonych**. To nie jest resztka do zamiecenia, tylko cały wpis D3 — i tam
  zostaje jako decyzja (backfill kursów vs trwałe wykluczenie z raportów).
  **Sprawdzone przy okazji, że to NIE cieknie do liczb:** `clv_tracker` filtruje
  `odds_verified = 1` (linia 121) i osobno zlicza zera (134), a ROI z rankingu rynków
  liczy się z `coupons.total_odds`, nie z `predictions.odds` — inna ścieżka danych.
  Jedyne, co robi `stan_uczenia`, to **wypisuje ostrzeżenie** („ROI i CLV licz wyłącznie
  na zweryfikowanych") — rada dla czytającego, nie filtr. Wystarczy, dopóki żaden raport
  nie liczy ROI z `predictions`.

### Sprawdzone i odrzucone
- **Podział promptu na warstwy** (reguły w wiadomości systemowej, potem kontekst →
  mecze → polecenie): A/B po 3 próby. Tokeny wejścia 1285 vs 1289, ta sama
  częstość pustego `top3`. **Bez mierzalnej korzyści** — nie wdrażać.
- `qwen/qwen3.6-27b` — wypluwa `<think>` do treści, parser nie ma szans.
- `groq/compound-mini` — działa (top3=3), ale zjada 3423 tokeny zamiast 1550.
  Rezerwa: 70K tok/min i brak dziennego limitu tokenów (za to 250 req/dzień).

## 🔍 AUDYT 2026-08-17 — 23 znaleziska (0 krytycznych)

> Pełny raport z dowodami: artefakt „Audyt FootStats". Poniżej lista do odhaczania.
> Zakres: 172 pliki .py (37 636 linii), 3381 linii JSX, 4463 testy / **80% pokrycia**, prod DB + GCP.

### 🔴 Wysokie
- ~~**F7 — opis pierwotny**~~ (zostawiony dla kontekstu):
  1. **Baner twierdzi**: „używamy NIEZBĘDNYCH plików cookie / local storage (np. token sesji)".
  2. **Realnie**: `main.jsx:13-14` montuje `<Analytics />` i `<SpeedInsights />` (Vercel) **bezwarunkowo**. Dowód: przy `fs_cookie_consent = null` i widocznym banerze oba skrypty są już w DOM (`/_vercel/insights/script.js`, `/_vercel/speed-insights/script.js`).
  3. **Polityka prywatności** nie wspomina o analityce ani słowem (jest tylko „cookies").
  - Flaga `fs_cookie_consent` jest **czytana wyłącznie przez sam baner** — przycisk „Rozumiem" nie włącza ani nie wyłącza niczego.
  - Pod RODO/ePrivacy: cookies *ściśle niezbędne* zgody NIE wymagają, ale analityka **wymaga** i nie może odpalać przed zgodą. Obecny stan jest gorszy niż brak banera — to komunikat, który nie opisuje tego, co aplikacja robi.
  - **Do decyzji:** (A) usunąć Vercel Analytics — najprościej i zgodne z kierunkiem „prywatny użytek + znajomi", wtedy treść banera staje się prawdziwa i wystarczy jednolinijkowa notka zamiast paska; (B) bramkować analitykę zgodą i dopisać ją do polityki; (C) zostawić i tylko poprawić treść — najsłabsze, bo dalej brak bramki.
- [x] **F8 — BYŁO JUŻ ZROBIONE.** Sprawdzone 24.08: istnieje helper `legalUrl()` (`gui/src/lib/api.js`), wszystkie trzy linki go używają, a w GUI nie ma ani jednego surowego adresu `run.app`. Wpis w TODO był nieaktualny.
- [ ] **F10 — sześć klikalnych `<div>` do konwersji.** `HistoryCouponRow` (rozwijanie wiersza), `LeaderboardView` (wiersz rankingu), `ui.jsx`, `CouponWizard` (3×). Niedostępne z klawiatury i bez roli dla czytnika. Każdy wymaga `role="button"` + `tabIndex` + obsługi Enter/Spacji albo przepisania na `<button>`. Próg w strażniku obniżyć po każdej konwersji.
- [ ] **F11 — reszta widoków bez audytu dostępności.** Zrobione: `LoginView`, `ManualCouponForm` (zamykanie), `App` (menu). Zostają: `SettingsView`, `AdminPanelView`, `CouponWizard`, `StatsView`, `LeaderboardView`, `TerminarzView`, `MatchAnalysisView` — głównie powiązanie etykiet z polami.
- [ ] **F9 — inline'owe kolory to pozostałość po bugu CSS z F1.** ⚠️ **KOREKTA ZAKRESU 23.08:**
  wpis mówił „trzy miejsca". Policzone: **79 wystąpień `style={{` w 8 plikach** —
  `HistoryCouponRow`, `HistoryView`, `LeaderboardView`, `ManualCouponForm`,
  `MatchAnalysisView`, `ProgressChart`, `StatsView`, `TerminarzView`. To duża zmiana
  z realnym ryzykiem regresji wizualnej, nie drobiazg na kwadrans.
  **Uzasadnienie „to odblokuje CSP" jest już SŁABSZE, niż sam napisałem przy B5:**
  23.08 rozdzieliłem `style-src-elem` (zaciśnięty, blokuje wstrzyknięty `<style>`)
  od `style-src-attr` (`'unsafe-inline'` dla Reacta). Zysk bezpieczeństwa jest więc
  **już wzięty**, bez ruszania tych 79 miejsc. Zostaje wyłącznie:
  (a) spójność z design-systemem, (b) Firefox — nie zna `style-src-elem/attr`
  i spada na zapasowy `style-src`, więc tam `'unsafe-inline'` dalej obowiązuje.
- [x] ✅ **M5 — ZMIERZONE 23.08. Flaga `SELECTION_SKIP_BTTS` zbudowana, DOMYŚLNIE OFF.**
  ⚠️ **KOREKTA WŁASNEGO WPISU — premisa M5 była błędnym cytatem.** Poprzednia wersja
  brzmiała: „Symulacja BEZ BTTS dała −10,7%, a produkcja z BTTS −13,5%". Źródłem jest
  `CHANGELOG.md` (M1, 17.08), gdzie **−10,7% / −13,5% / −14,7% to TRZY REGUŁY SELEKCJI
  na tych samych danych** — argmax p (czyli produkcja), argmax EV, argmax przewagi nad
  rynkiem. Żadna z nich nie jest wariantem „bez BTTS". **Pomiar uzasadniający M5 nigdy
  nie istniał.**
  **Zmierzone na produkcji 23.08** (wspólne okno 2026-05-06..2026-08-16). ⚠️ Surowa próba
  n=147 jest **skażona zmyślonymi kursami**: 17 wierszy ma kurs >10, w tym wielokrotnie
  **52,58** — liczba zapisana jako halucynacja Groqa (patrz D3, `odds_verified=0`).
  Po odsianiu, **n=130**:

  | rynek | n | mediana kursu | próg opłacalności | trafność | ROI |
  |---|---|---|---|---|---|
  | 1X2 | 85 | 2,10 | 50,8% | 38,8% | −14,6% |
  | O/U 2.5 | 27 | 1,75 | 60,2% | 55,6% | **+19,7%** |
  | BTTS | 12 | 1,68 | **62,6%** | 25,0% | −47,9% |
  | razem | 130 | — | — | 41,5% | −11,7% |
  | bez BTTS | 118 | — | — | 43,2% | −8,0% (+3,7 pp) |

  **Kierunek zgadza się z M5, ale to NIE jest dowód:** przy n=12-13 jeden trafiony zakład
  przesuwa ROI o **14,5 pp**, a test dwumianowy — po korekcie na to, że BTTS wybrano jako
  najgorszy z czterech rynków — daje **p=0,111** (surowe 0,028 × 4).

  **🔬 MECHANIZM (ustalony 23.08 — to jest sedno, nie ROI):**
  1. **Selekcja może obstawić wyłącznie „BTTS TAK".** `_ODDS_KEY` w `system_paper.py` ma
     jeden wpis `"BTTS": "btts"` — strony NIE tam nie ma. Rynek jednostronny z definicji.
  2. **TAK to droga strona.** Przy medianie 1,68 i podatku 12% próg opłacalności to **62,6%**,
     a częstość bazowa BTTS w futbolu **~54,4%** → **8 punktów dziury, zanim model się odezwie.**
  3. **Model nie ma czym jej zasypać:** n=15 460 → 53,2% przy bazie 54,4% (Brier 0,2496 vs
     0,2480). „Zawsze BTTS tak" **bije model**.
  4. **A argmax i tak go wybiera** — rynki 2-way wygrywają argmax w 74% meczów, bo jedna
     strona zawsze ma ≥50% z definicji.

  **Dowód kontrolny obok:** O/U 2.5 ma niemal identyczny próg (60,2%), ale selekcja ma
  **obie** strony (`Over`/`Under`) i może wziąć tańszą — i to **jedyny rynek z dodatnim ROI**.
  Różnica nie leży w rynku, tylko w braku wyboru strony przy BTTS.

  **Hipoteza obalona po drodze:** podejrzenie, że brak korekty Dixona-Colesa **zawyża** BTTS
  (`poisson.py:43` liczy `(1−P(g=0))·(1−P(a=0))` z niezależnych rozkładów, a `quick_picks.py:255`
  mówi wprost „DC dotyka TYLKO 1X2"). Policzone dla realnych λ przy ρ=−0,13: DC **zawyża**
  BTTS TAK o ~1,5 pp, czyli obecny wzór **zaniża**. To osobny, mniejszy problem — spycha
  graniczne mecze na stronę NIE, której selekcja i tak nie umie obstawić.
  **Czego NIE dało się policzyć:** prawdziwego kontrfaktu („co selektor wybrałby zamiast
  BTTS"). `predictions.match_stats` to statystyki PO meczu, a prawdopodobieństw pozostałych
  rynków baza nie trzyma — to samo ograniczenie opisuje **D4**. Odblokowanie tego pomiaru
  = dopisać `p_over25`/`p_btts` do `model_log`.
  +13 testów. Flip dopiero po próbce, jak `SELECTION_MIN_CONF` i `LEAGUE_GATING`.

### 🟡 Średnie
- [x] **CI czerwone od 23.08 — NAPRAWIONE 24.08.** Przyczyna: `Dockerfile.api`/`Dockerfile.jobs` startują z `python:3.12-slim`, oba locki kompilowane pod 3.12, a wszystkie trzy joby `ci.yml` stały na **3.11**. Krok `pip-audit` padał, odkąd B9 (23.08) przestawiło skan z ręcznego `requirements.txt` na locki — lock pisany pod 3.12 nie musi się rozwiązać na 3.11. Lokalnie ten sam skan: `No known vulnerabilities found`, exit 0.
  - **Drugi, cichszy skutek:** job `test` też jechał na 3.11, więc suita potwierdzała interpreter, którego nigdzie nie uruchamiamy.
  - **Skutek uboczny gorszy od samego błędu:** czerwień bez przerwy = brak sygnału. 24.08 dwa moje deploye padły i wyszło to dopiero przy ręcznym sprawdzeniu produkcji.
  - Strażnik `test_ci_wersja_pythona.py`: CI == obraz, CI == lock, oba obrazy równe.
  - ⚠️ **Zostaje do obserwacji:** job `secrets` (gitleaks) pada NIEregularnie — 2 z 12 ostatnich przebiegów, bez związku z treścią commita. Wygląda na flaki/limit po stronie akcji, nie na wyciek. Jeśli się powtórzy, dopiąć `GITHUB_TOKEN` do kroku i sprawdzić log.
- [x] **26.08 — niestabilna suita: ODTWORZONA, ZDIAGNOZOWANA I NAPRAWIONA 28.08.**
  Dwa pełne przebiegi pytest naraz na wspólnym stanie: **4 czerwone i 2 czerwone,
  za każdym razem INNE testy**. Te same przebiegi izolowane: 0 i 0. Po fiksie ta
  sama konfiguracja daje **5342/5342 dwa razy**. Żaden z winowajców nie był
  „flaky testem" — oba to realne współdzielenie stanu:
  1. `tests/test_next_final_parse.py` pisał do **prawdziwego** `data/next_final.txt`
     w repo i przywracał backup w `finally`. Jeden proces przywracał, gdy drugi
     czytał. `_zapisz_next_final_txt` przyjmuje teraz opcjonalny `katalog` (tylko
     dla testów), testy piszą do `tmp_path`, a osobny test broni domyślnej ścieżki
     produkcyjnej — żeby udogodnienie testowe jej nie przesunęło.
  2. `test_python_syntax_valid` wołał `subprocess python -m py_compile` na każdym
     pliku, a `py_compile` **zapisuje bajtkod** do wspólnego `__pycache__`. Objawem
     był `UnicodeDecodeError` (komunikat Pythona przychodzi w cp1250, nie UTF-8),
     więc wyglądało to na uszkodzone źródło przy zdrowym źródle. `compile()`
     w procesie sprawdza to samo, nic nie zapisuje i zdejmuje **ponad 170 procesów**
     z jednego testu.
  **Prewencja na trzecią klasę tego samego błędu:** 18 katalogów cache było stałymi
  MODULOWYMI (`Path("cache/kursy")` itd.), więc żadna zmienna środowiskowa nie mogła
  ich przekierować. `utils/paths.py` + `FOOTSTATS_CACHE_ROOT`, conftest daje każdemu
  procesowi własny korzeń. Domyślne ścieżki bez zmian (produkcja tej zmiennej nie
  ustawia), `CHECKPOINT_DIR` dalej wygrywa. Pilnuje `tests/test_izolacja_cache.py`
  (25 testów) + ratchet na nowe `Path("cache/...")` z palca.
  **Dwaj podejrzani z 26.08 — oba przypadki wyjaśnione, żaden nie był losowy:**
  `test_recovery_list_most_recent` padał, ZANIM powstała fikstura `clean_checkpoint_dir`
  (`845fac1b9`, 26.08 21:39) — naprawione tego samego dnia.
  `test_blokada_konta_po_serii_bledow_DZIALA` czyta źródło `auth.py` przez
  `inspect.getsource`, a `auth.py` był edytowany 26.08 **20:49** (`911069486`, +33
  linie) — suita czytała drzewo w trakcie edycji. Stąd reguła: **nie edytować drzewa,
  gdy leci suita** (ta sama, co przy pętlach mutacyjnych).
  ⚠️ `-p no:randomly`, którego używaliśmy „dla determinizmu", jest **no-opem** —
  `pytest-randomly` nie jest zainstalowany, kolejność testów i tak jest deterministyczna.
  ⚠️ Zostaje drobiazg poza zakresem: `flashscore_results.CACHE_DIR` domyślnie celuje
  w `src/cache/flashscore` (kotwica `parent.parent.parent` z `scrapers/` to `src/`),
  a nie w `cache/` repo jak reszta. Nie ruszam przy okazji — przeniesienie przesuwa
  produkcyjny cache i jest osobną decyzją.

- [ ] **J1c — oba audyty ciszy mają wspólną ślepą plamkę: `return` po nieudanej
  walidacji.** Znalezione 28.08 przy `oblicz_tip_correct`: cichy był NIE `except`,
  tylko `if not val_match: return None` linijkę wyżej. Zwykły `return` nie jest
  handlerem, więc ani `test_ciche_except_audit`, ani `test_silent_swallow_audit`
  go nie widzą — a to on realnie przechwytywał ten przypadek (handler pod nim
  okazał się nieosiągalny). Ten sam kształt co `return []`/`return False`
  z incydentów 24.08.
  **Nie rozszerzam audytu teraz i to jest świadome:** trafień byłyby setki,
  a większość uzasadnionych (`if not x: return None` na pustym wejściu to
  normalna walidacja, nie awaria). Rozsądny zakres do przemyślenia: tylko
  `return` po nieudanym PARSOWANIU (regex/int/float/fromisoformat), nie po
  sprawdzeniu pustki. Wymaga pomiaru, ile to realnie miejsc, zanim powstanie
  jakikolwiek baseline.

- [ ] **D7 — 21 kuponów z 14-15.08 jest nie do odzyskania** z darmowych źródeł
  (duńska, japońska, chińska liga + angielskie niższe — poza pokryciem football-data,
  poza oknem AF, poza 7 dniami FlashScore). Zejdą przez VOID 24-25.08. Do decyzji:
  pogodzić się ze stratą 20 punktów paper-tradingu czy szukać źródła z historią.

- [x] **D5 — ZROBIONE 24.08.** `MANUAL_SETTLE_EXTERNAL=1` otwiera `_find_leg_result` dla nóg dziennika bez własnej predykcji. Nasze dane zachowują pierwszeństwo (darmowe, z tego samego przebiegu co typ), all-legs-or-nothing bez zmian, cache źródeł dzielony ponad pętlą kuponów, licznik `z_zewnatrz` w odpowiedzi endpointu. Domyślnie OFF — kosztuje limit planu. Regresji trybu domyślnego pilnuje `test_settle_manual_coupons.py` (fikstura wysadza test przy wywołaniu `_find_leg_result`). 15 testów.
- [ ] **D3 — 231 predykcji z `odds_verified=0`** (kurs od Groqa) → ROI/CLV z historii nic nie znaczą. Decyzja: backfill kursów czy trwałe wykluczenie z raportów.
- [x] **I2 — ZROBIONE 28.08.** `tiktoken` (encoding `o200k_base`, rodzina używana przez
  `openai/gpt-oss-120b`) zamiast stałej znak/token. Zmierzone tokenizerem modelu:

  | próbka | znaków | tiktoken | heurystyka 1,4 |
  |---|---|---|---|
  | szkielet PL | 64 | **25** (2,56 zn/tok) | 46 — **+84%** |
  | diakrytyki | 67 | **31** (2,16) | 48 |
  | emoji + liczby | 53 | **36** (1,47) | 38 |

  **Oba wcześniejsze pomiary były prawdziwe, dla różnej treści** — stała 1,4 powstała
  po awarii 413 na opisach meczów z emoji i dla nich jest trafna; dla zwykłego tekstu
  przeszacowuje o 84%. Żadna stała nie obsłuży obu naraz.
  **Naprawione DWA miejsca, nie jedno:** `szacuj_tokeny` (licznik) oraz
  `dopasuj_do_budzetu`, który przeliczał budżet tokenów na znaki po tej samej stałej —
  czyli tnie do ~55% przyznanego budżetu. Teraz przelicznik bierze się Z TEGO promptu,
  a wynik jest **weryfikowany i dociskany**, bo gęstość tokenów nie jest równomierna
  (emoji siedzą w opisach meczów, nie w instrukcji).
  **Degradacja zamiast awarii:** `tiktoken` ciągnie plik BPE z sieci (zmierzone 3,8 s
  przy pierwszym użyciu) — w jobie to zapytanie do internetu w środku przebiegu.
  Enkoder ładuje się **raz**, nieudana próba **nie jest ponawiana**, a brak paczki albo
  brak sieci schodzi na starą heurystykę **z WARNING-iem**. Dwa szerokie handlery
  w `ai/client.py` są zamierzone i opisane w baselinie audytu (2 → 4).
  Paczka w extra `[ai]`, więc wchodzi do obrazu jobów; obraz API zostaje bez niej
  (ten sam wybór co przy `scikit-learn`).
- [ ] **J1 — połowa `except` milczy. STRAŻNIK ZROBIONY 24.08, zostało schodzenie w dół.** Zmierzone analizą AST: **255 z 555** handlerów bez logu, bez `raise` i bez odwołania do złapanego wyjątku. `tests/test_ciche_except_audit.py` zamraża ten dług baselinem per plik, wymaga **zera w nowych plikach** i twardego zera w funkcjach alarmowych.

  **Znalezione przy okazji, najostrzejsze w całym audycie:** `check_and_alert_agent_down` i `check_and_alert_accuracy` kończyły się `except (...): pass` + `return False`, a `False` znaczy „nie wysłano alertu", czyli w praktyce „jest dobrze". Padnięte zapytanie do bazy dawało odpowiedź „zdrowo" **bez jednej linijki w logach** — czujnik dymu meldował spokój, paląc się. Naprawione, `utils/telegram_notify.py` zszedł z 5 do 1.

  **POSTĘP 28.08 — dwa najgrubsze pliki zeszły z 27 do 10.** `ai/analyzer.py` **12 → 1**,
  `cli.py` **15 → 9**. Globalny `PROG` w `test_silent_swallow_audit.py`: **72 → 56**.
  Przepływ sterowania bez zmian nigdzie — każdy handler dalej połyka ten sam wyjątek
  w tym samym miejscu, doszedł wyłącznie log (leniwe `%s`, poziom dobrany do skutku).

  **Najgroźniejszy z udźwięcznionych:** `_zapytaj_typera` w `analyzer.py` — `except
  Exception:` przełączające całe zapytanie na inny klient AI bez śladu. To dokładnie
  ten kształt awarii, który 22.08 zatrzymał potok na **sześć dni**: Groq wycofał
  `llama-3.1-8b-instant`, 404 znikały w fallbacku, joby kończyły się `exit=0`.
  Blisko za nim `_get_kalibracja_blok` i `_get_liga_statystyki_blok` — każdy błąd
  cicho zdejmował całą sekcję z KAŻDEGO promptu do Groqa przez całą sesję.

  **Świadomie zostają ciche:** 9 w `cli.py` (jednorazowe `int()/float()` z prompta
  interaktywnego, spadające na wartość domyślną albo natychmiast drukujące „Zły
  numer" — awaria widoczna dla użytkownika w tej samej sekundzie, log byłby szumem)
  i 1 w `analyzer.py` (parsowanie kursu do EV w pętli 5 rynków × N meczów — brak
  kursu na BTTS/O2.5 to stan normalny, nie awaria).

  **Zostaje do zejścia:** `core/quick_picks.py` **7** (było 10, −1 dziś przy okazji
  `factors`), `core/daily_phases.py` 9, `daily_agent.py` 8, `api/auth.py` 4,
  `api/main.py` 4, `core/coupon_settlement.py` 4. Plus 1 świadomy w `telegram_notify`
  (`except FileNotFoundError` przy pierwszym odczycie dedup — brak pliku to norma).
- [x] **J2 — ZROBIONE 28.08. Zakres był wąski NIE Z WYBORU — mypy był zepsuty.**
  `python_version = "3.11"` w `[tool.mypy]` przy stubach numpy w składni 3.12 dawało
  `Type statement is only supported in Python 3.12 and greater` i **przerywało analizę
  przy pierwszym module importującym numpy**. `scrapers/sources/` przechodziło jako
  jedyne dlatego, że jako jedyne numpy nie dotyka. Wpis 3.11 był zwyczajnie stary:
  CI, oba obrazy (`python:3.12-slim`) i oba locki są na 3.12.
  **Po naprawie widać prawdziwy dług:** `core` 69 błędów, `scrapers` 36, `utils` 17,
  `ai` 11, `api` 3, `db` 0.
  **Bramka CI rozszerzona** z 1 do 3 katalogów: `scrapers/sources/` + `db/` + `api/`
  (22 pliki, zero błędów). `api` domknięte przy okazji — z 3 błędów jeden był
  **realny**: `m.get("gosp")` może być `None`, a `get_team_stats` przyjmuje `str`,
  więc zdarzenie bez nazw drużyn szło do wyszukiwania statystyk jako `None`. Teraz
  pomijane, z logiem. Drugi to kontrawariancja handlera Starlette vs slowapi —
  wyciszona punktowo z kodem błędu.
  **Zostaje:** `core`/`scrapers`/`utils`/`ai` do spłacenia, potem kolejny ratchet.
- [x] **J3 — CZĘŚĆ PRODUKCYJNA ZROBIONA 28.08, testowa dalej otwarta.** Wpis mówił
  o schematach w testach; szukając ich znalazłem ten sam problem w PRODUKCJI, i gorszy.
  `predictions` było definiowane w **dwóch** miejscach piszących do **tej samej** bazy
  (`utils.db.connect` jest wyłącznie Postgresem): `api/main._init_db` (8 tabel, bez
  `prob_home/prob_draw/prob_away/settle_attempts/odds_verified`) i `core/backtest.init_db`
  (2 tabele, z tymi kolumnami, ale z `REFERENCES coupons(id)` przy braku `coupons`).
  Na pustej bazie wygrywała ta, która wykonała się pierwsza — a wykonuje się RÓŻNA
  zależnie od obrazu: `api/main` nie jest importowany w obrazie jobs, gdzie
  `backtest.init_db()` wołają evening_agent, ai/rag, post_match_analyzer,
  results_updater ×2 i coupon_settlement ×2.
  **Dlaczego nie wybuchło:** dwa niezależne przypadki naraz — baza produkcyjna już
  istnieje, a Postgres ma `ADD COLUMN IF NOT EXISTS`. Gałąź SQLite tego nie ma.
  DDL → `db/schema.py`, oba bootstrapy go wołają. Strażnik znalazł jeszcze **trzy
  kopie**: `wf_results`, `coupons`, `ai_feedback_embeddings`; kopia `coupons` miała
  `bookmaker` i `user_id`, których wersja w `api/main` nie miała.
  ⚠️ **Niezmiennik jest celowo słabszy niż „jedna definicja":** `wf_results`
  w `walkforward.py` to INNY magazyn (własny `_connect` na SQLite, `AUTOINCREMENT`
  zamiast `SERIAL`), więc dialekt musi się różnić. Pilnowany jest **zestaw kolumn**.
  4 testy, 4 mutacje, wszystkie złapane.
- [ ] **J3b — schematy w TESTACH (pierwotny zakres wpisu).** 33 pliki testowe mają
  własne `CREATE TABLE`. Teraz jest do czego je podłączyć (`db.schema.SCHEMAT_BAZOWY`),
  ale to SQLite, a wspólne DDL jest postgresowe (`SERIAL`, `BYTEA`) — potrzebny
  przekład dialektu albo fikstura budująca z migracji. Nie robię tego jednym ruchem
  na 33 plikach bez pomiaru, które z nich realnie kopiują produkcyjny schemat,
  a które trzymają własne, celowo minimalne tabelki.
- [ ] **M2 — trzy flagi czekały na walidację:** `SELECTION_MIN_CONF=65`, `LEAGUE_GATING=1`, `BTTS_TWO_WAY`. **Dla BTTS dane są od 24.08 (D4) i mówią: NIE FLIPOWAĆ.** Live n=385 nie pokazuje uporządkowania — koszyk <45% daje realnie 52,8%, a 50–55% tylko 45,5%. Offline (n=15 460) krzywa była monotoniczna, więc to kolejny rozjazd live vs offline, nie nowy wynik na korzyść flagi. Dwie pozostałe flagi dalej bez danych.
  ⚠️ **26.08 — INNA flaga, nie mylić z powyższą.** `SELECTION_SKIP_BTTS` (zbudowana 23.08 jako M5, domyślnie OFF) została **włączona na produkcji** (`footstats-api` rew. `00474-dlg` + oba joby, `--update-env-vars`, zweryfikowane 17→18 / 13→14 zmiennych). Podstawa: zadanie D (ranking 7 rynków) pokazało, że BTTS jako typ główny modelu ma przewagę **−3,3 pp** (n=134), replikującą się w obu połowach chronologicznych (−2,5 / −5,0 pp); po wyrzuceniu BTTS wskakuje Over 2.5 (112/136), przewaga na tych samych meczach **−3,3 pp → +5,0 pp**. `BTTS_TWO_WAY` **zostaje OFF bez zmian** — to osobna decyzja (granie strony NIE), a dane dalej mówią „nie flipować". Do sprawdzenia **27.08 po 05:31 UTC**: czy w kuponach faktycznie nie ma BTTS.
- [ ] **M3 — cel M1 mierzy rynek, który przegrywa.** „55% win rate" liczone na 1X2, gdzie przy niezgodzie rynek 42,9% vs model 29,8%. Rozważyć ROI zamiast trafności.

### ⚪ Niskie
- [x] ✅ **B6 — ZROBIONE 23.08. Walidacja identyfikatorów przed sklejeniem SQL.**
  `player_db.py` `ALTER TABLE ... ADD COLUMN {col} {typ}` musi iść f-stringiem —
  SQLite **nie pozwala parametryzować identyfikatorów** (`?` działa dla wartości,
  nie dla nazw kolumn), więc parametryzacja jest tu fizycznie niemożliwa i jedyną
  obroną jest walidacja. `_sprawdz_identyfikator` przepuszcza wyłącznie nazwę
  pasującą do `^[a-z_][a-z0-9_]*$` i typ z zamkniętej listy `{REAL, INTEGER, TEXT}`.
  Sprawdzane są **oba** pola — walidacja samej nazwy zostawiałaby drugą połowę
  zapytania otwartą. +21 testów, bandit czysty.
  **Uczciwie: to nie była podatność.** `_OPTIONAL_COLS` to stała w module, nie dane
  z zewnątrz — nic nie dało się wstrzyknąć. Zmiana zamienia „bezpieczne, bo nikt
  tego nie zmienił" na „bezpieczne, bo sprawdzane", co zaczyna mieć znaczenie
  dopiero w dniu, w którym ktoś weźmie listę kolumn z konfiguracji albo ze źródła.
  Jeden z testów sprawdza SKUTEK, nie sam wyjątek: po próbie wstrzyknięcia tabela
  `player_stats` ma dalej istnieć.
- [x] ✅ **D4 — ZROBIONE 24.08. Rynki golowe zmierzone po raz pierwszy, n=385.** Premisa wpisu była częściowo błędna: `model_log` **od początku zapisywał** `prob_over25` i `prob_btts` (wszystkie 595 wierszy je ma). Brakowało wyłącznie strony wynikowej — `tip_correct` mierzył sam argmax 1X2. A ponieważ `actual_result` trzyma pełny wynik (`"3-1"`), całość dało się policzyć **wstecznie, bez jednego nowego meczu**.

  Doszły kolumny `over25_correct` i `btts_correct` (idempotentny ALTER — tabela żyje na produkcji), czysta funkcja `oceny_rynkow()` licząca trzy rynki z jednego wyniku, `uzupelnij_rynki_golowe()` z `dry_run` i sekcja w `stan_uczenia.py`. Uzupełnione **385 wierszy, 3 pominięte** (mecze po karnych — nie dostają zer, bo „nie wiemy" to nie „model się pomylił"). 14 testów.

  **WYNIK — Over 2.5 rozróżnia mecze, BTTS nie.**

  | koszyk | Over 2.5 model → realnie | BTTS model → realnie |
  |---|---|---|
  | <45% | 40,4% → **40,9%** | 41,7% → **52,8%** |
  | 45-50% | 47,1% → 53,0% | 48,1% → 50,6% |
  | 50-55% | 52,2% → 53,6% | 52,5% → **45,5%** |
  | 55-60% | 57,0% → 62,9% | 57,5% → 63,5% |
  | 60%+ | 65,1% → **66,7%** | 63,9% → 60,3% |

  Over 2.5: krzywa **monotoniczna**, rozpiętość 25,8 pp, trafia w obu końcach. Pierwszy rynek w tym projekcie z realną ROZDZIELCZOŚCIĄ — a to właśnie ją PLAN Bundesliga wskazał jako wąskie gardło, nie kalibrację. BTTS: brak uporządkowania, koszyk najniższy daje więcej niż środkowy.

  **Koryguje wcześniejszy wniosek z 15.08** o „realnym sygnale BTTS": sam szczyt 60%+ faktycznie daje 60,3%, ale to efekt ogona, nie uporządkowanie. Zobacz M5.

  **Czego to NIE dowodzi:** porównanie jest z WYNIKIEM, nie z rynkiem. Model może być świetnie skalibrowany i dalej przegrywać z kursami — dokładnie to wyszło dla 1X2 na n=15 460. Następny krok to zestawienie `prob_over25` z kursem zamykającym.
- [ ] **F4 — PWA nie działa, ale NIE dlatego, że jej nie ma.** Backend serwuje OBA:
  `/manifest.json` (`main.py:455`) i `/sw.js` z pełnym cyklem install/activate/fetch.
  Problem jest węższy: **front ich nie podłącza**. W `gui/index.html` nie ma
  `<link rel="manifest">`, a w całym `gui/src` nie pada ani razu `serviceWorker`.
  Kod jest napisany i osierocony, więc fix to dwie linijki (link + rejestracja),
  nie `vite-plugin-pwa` od zera.
  ⚠️ **Uwaga o duplikacie (23.08):** „odkryłem" to ponownie i dopisałem drugi wpis,
  choć audyt 17.08 zapisał to samo. Wpisy scalone tutaj; stary miał nieaktualny
  numer linii (`main.py:411`). Ostrzeżenie na przyszłość: przed dopisaniem
  „korekty" sprawdź, czy korekta już nie istnieje.
- [ ] **F5 — `CouponWizard.jsx` 437 linii**, `SettingsView.jsx` 377 (limit 400).
- [ ] **I3 — brak Sentry na froncie** (backend ma).
- [x] **I4 — ZROBIONE 28.08.** `DATABASE_URL_NEON` usunięty z lokalnego `.env` (45 → 44
  linie). Bezpieczne: backfill Neon → Supabase zamknięty 14.08, a wersja sekretu
  z Neonem wyłączona — martwy kredencjal w pliku to była już tylko powierzchnia ataku.
  Placeholder w `.env.example` **zostaje**: dwa jednorazowe skrypty migracyjne
  (`backfill_users_from_neon.py`, `import_neon_do_supabase.py`) dalej go dokumentują,
  a bez zmiennej zgłoszą jasny błąd zamiast trafić w niewłaściwą bazę.
- [x] ✅ **I5 — ZROBIONE 23.08. Rejestr obrazów: 94,7 GB → 6,3 GB.** `footstats-api`
  424 obrazy / 68,8 GB, `footstats-jobs` 45 / 25,9 GB. Darmowy limit Artifact Registry
  to 0,5 GB → ~0,10 USD/GB/mies. **Zrobione 23.08** (zmierzone przed/po):
  `footstats-jobs` 109 → **30** wpisów, atestacje 65 → **0**, bez taga 15 → **0**,
  25,9 → **20,1 GB**; `footstats-api` 430 → **419**, atestacje 6 → **0**, bez taga
  7 → **2**, 68,8 → **68,6 GB**. Razem skasowane 71 atestacji + 20 obrazów bez taga,
  **zwolnione 6,0 GB**. Polityka czyszczenia ustawiona w trybie **NA SUCHO**
  (`trzymaj 30 najnowszych` + `kasuj nieotagowane starsze niż 30 dni`).
  Uwaga operacyjna: `gcloud artifacts docker images delete` pisze „Delete request
  issued… done." na **stderr** i podnosi kod wyjścia — skrypt liczył 3 udane
  kasowania jako błędy. Sprawdzaj stan faktyczny (`describe`), nie kod wyjścia.
  **DLACZEGO NA SUCHO, a nie od razu na ostro:** Artifact Registry **nie widzi
  referencji Cloud Run**. Zmierzone: dwa obrazy API są nieotagowane, a mimo to
  wskazywane przez żywe rewizje (`:latest` przewędrował dalej, digest został) —
  reguła „kasuj nieotagowane" skasowałaby działający obraz. **W tym projekcie
  nieotagowany ≠ nieużywany.**
  **DOMKNIĘTE 23.08 wieczorem — retencja 10 stron + 5 pipeline (decyzja użytkownika).**
  Skasowane 426 rewizji Cloud Run (436 → 11, rewizja z ruchem chroniona) i 434 obrazy.
  **94,7 GB → 6,3 GB (−93%)**, koszt ~35 zł → ~2,3 zł/mies. Produkcja żyje: `/health` 200,
  oba joby wskazują ten sam, istniejący digest.
  **Darmowy limit 0,5 GB jest NIEOSIĄGALNY** — jeden obraz jobów waży 691 MB (chromium
  + sklearn/pandas/pyarrow), więc sam przekracza limit. Obraz API to 161 MB.
  Dwie pułapki narzędziowe zapisane, obie kosztowały przebieg:
  1. `gcloud artifacts docker images delete` pisze „Delete request issued… done." na
     **stderr** i podnosi kod wyjścia → skrypt liczył udane kasowania jako błędy.
     Sprawdzaj stan faktyczny (`describe`), nie kod wyjścia.
  2. **`--delete-tags` jest konieczne** dla obrazu z tagiem („Cannot delete image …
     because it is tagged"). Bez niego pierwszy przebieg dał **434 błędy na 436 prób**.
- [x] ✅ **I8 — ZROBIONE 24.08. Monitoring, który realnie widzi całą pętlę.**
  Po I7 najważniejsze pytanie brzmiało nie „czemu padło", tylko **„czemu nikt się nie
  dowiedział przez 8 dni"**. Odpowiedź: monitoring był ślepy w dwóch miejscach naraz.
  **1. `pipeline-health` nie widział kuponów w ogóle.** Sprawdzał wiek najnowszej
  predykcji i zaległości w rozliczeniach. Predykcje płynęły (pisze je job), więc oba
  warunki były spełnione i alarm milczał. Sygnał `stale_days` **istniał**, ale mieszkał
  WEWNĄTRZ draftu — czyli wewnątrz tego, co było zepsute. Endpoint, który umiera, nie
  zgłosi, że umarł. To ten sam błąd architektoniczny, przed którym ostrzega nagłówek
  `status.py` („monitor nie może żyć w tym, co monitoruje"), tylko o poziom wyżej.
  Trzeci wymiar pyta o kupony sam, po skutku, progiem `PROG_STALE_DNI` współdzielonym
  z `draft_health`. **+7 testów.**
  **2. Alarm o zaległościach palił się non stop i nigdy by nie zgasł.** Zmierzone:
  liczył **25** przy progu 10, a z tych 25 **ZERO** było w zasięgu źródeł — najstarsze
  to mecze z **maja 2026**. Wykluczenie działało po liczbie prób, więc utknęły w limbo:
  za stare, żeby się rozliczyć, za mało prób, żeby przestać się liczyć. Kryterium
  zmienione na osiągalność źródła (`HORYZONT_ZRODEL_DNI`), okno ma teraz obie granice.
  **To prawdopodobnie współprzyczyna I7:** alarm świecący zawsze uczy go ignorować.
  Po naprawie: `ok: True, nierozliczone: 0`. **+2 testy.**
- [x] ✅ **I9 — ZROBIONE 24.08. Codzienny raport przebiegu na Telegram (14:00).**
  `POST /api/cron/raport-dzienny` + zadanie `footstats-raport-dzienny`. Liczby z ostatniej
  doby: kupony, predykcje, rozliczone. **Zero kuponów jawnie oznaczone `ok: false`** —
  to dokładnie obraz I7. Jedna wiadomość dziennie, nie trzy. **+13 testów.**
  **Różni się od alarmu celem:** alarm odpowiada „czy coś jest zepsute" i milczy, gdy
  dobrze — słusznie. Ale cisza nie odróżnia „poszło dobrze" od „monitor też padł".
  Raport odpowiada „ile dziś powstało"; spadek z 14 kuponów na 2 nie jest awarią
  i alarmu nie wywoła, ale jest sygnałem.
  ⚠️ **ODRZUCONY WARIANT — zaplanowany agent Claude w chmurze.** Użytkownik go wybrał,
  ale okazał się niewykonalny: agent startuje z czystym checkoutem, **bez `gcloud`, bez
  `DATABASE_URL`, bez `CRON_SECRET`**, a każdy endpoint mówiący cokolwiek o stanie wymaga
  uwierzytelnienia (jedyny publiczny `/health` zwraca samo „żyję"). Zadziałałby tylko po
  wklejeniu sekretu do przechowywanej konfiguracji rutyny — ten sam błąd, przez który
  14.08 `CRON_SECRET` wyciekł i wymagał rotacji.
- [x] ✅ **ROTACJA `CRON_SECRET` — 24.08.** Wypisałem wartość sekretu w treści sesji przy
  odczycie nagłówków Schedulera. Rotacja wykonana od razu: nowa wersja w Secret Manager
  → redeploy usługi (`:latest`) → podmiana nagłówka w **6 zadaniach** (dwa triggery jobów
  idą przez OAuth, nie przez nagłówek). **Zweryfikowane trzema niezależnymi dowodami:**
  nowy sekret → 200, stary → **401**, a wywołanie z `Google-Cloud-Scheduler` → 200.
  Lekcja narzędziowa: `gcloud scheduler jobs describe --format="value(httpTarget.headers)"`
  wypisuje **wartości** nagłówków. Do sprawdzenia OBECNOŚCI sekretu używać JSON-a
  i patrzeć na klucze, nigdy na wartości.
- [x] ✅ **I7 — ZROBIONE 23.08. Kupony nie powstawały od 8 dni: `/api/cron/draft` padał na OOM.**
  Znalezione przy pytaniu „czy wszystko działa produkcyjnie". Łańcuch urywał się na
  **trzecim ogniwie**: pobieranie ✅, analiza ✅, typowanie ✅ (13 predykcji dziś,
  `poisson-dc`), ale **ZERO kuponów od 15.08** — ostatni `#149`.
  **Dowód, jedna linia w logach:** `Memory limit of 512 MiB exceeded with 512 MiB used`.
  Draft ładuje parquet Poissona i liczy `quick_picks`, kontener ginie, Scheduler dostaje
  **503**. Działo się **codziennie o 05:30 nieprzerwanie od co najmniej 17.08** (dalej
  nie sięga okno logów).
  **Dlaczego nikt tego nie zauważył — dwie warstwy maskujące:**
  1. **Joby kończą się `exit=0`** i wyglądają zdrowo, bo kupony robi API, nie job.
     Ta sama rodzina co awaria Groqa stojąca 6 dni przy zerowym kodzie wyjścia.
  2. **Predykcje dalej powstawały**, więc z zewnątrz „bot działa" — brakowało wyłącznie
     tej części, która MIERZY, czy typy były trafne.
  **Fix:** limit pamięci usługi 512 MiB → **1 GiB** (rew. `00441-cwj`).
  **Zweryfikowane:** `/api/cron/draft?dry_run=false` zwraca teraz **200 w 12,5 s**
  zamiast 503, w logach zero OOM.
  ⚠️ **NIEDOKOŃCZONE — powstawanie kuponów NIE jest jeszcze udowodnione.** Wywołanie
  o 21:38 dało `Pobrano 50 wydarzen` → `candidates: 0` (zero **przed** filtrem lig,
  `after_league_filter: 0`), więc 50 meczów ginie wewnątrz `szybkie_pewniaczki_2dni`.
  Hipoteza: pora doby — o 21:40 okno 48h obejmuje mecze rozpoczęte, a ta sama funkcja
  o 09:05 dała 13 predykcji. **Do sprawdzenia przy przebiegu 05:30** — jeśli dalej 0,
  to osobny bug w progu `AGENT_KANDYDAT_PROG=0.55` albo w oknie czasowym.
- [x] **I6 — ZROBIONE 28.08.** `paths-ignore` w `cd-jobs.yml`: `**.md`, `docs/**`,
  `tests/**`. Obawa z tego wpisu była słuszna, więc filtr NIE jest pilnowany czyimś
  oglądem, tylko testem: `test_filtr_sciezek_nie_odcina_niczego_z_obrazu` bierze
  pliki **śledzone przez git** spod ścieżek, które `Dockerfile.jobs` realnie kopiuje
  (`src`, `scripts/run_job.sh`, `data/*.json`, parquet, `pyproject.toml`,
  `requirements-jobs.lock`) i wymaga zera kolizji z listą ignorowanych. Dopisanie
  `src/README.md` albo rozszerzenie filtra do `src/**` zapala się w CI, a nie na
  produkcji za trzy dni. Dwie kontrole domykają: dokumentacja MUSI być ignorowana
  (inaczej zmiana bez efektu), `src/`, `scripts/run_job.sh`, `Dockerfile.jobs`
  i lockfile MUSZĄ nie być (inaczej filtr da się rozszerzyć do `**`).
  ⚠️ Test od razu wyłapał realną kolizję — pierwsza wersja chodziła po dysku
  i łapała tysiące `README.md` z `node_modules`. Zbiorem właściwym jest `git ls-files`:
  tylko to, co może wejść w pusha.
- [x] **J4 — ZROBIONE 24.08.** Bramka `--cov-fail-under` podniesiona 72 → **78**. Pomiar z logu CI (run 2a86f2309): **80,31%**, lokalnie 81%. Przy progu 72 dało się skasować 8 pp pokrycia bez czerwonego builda — bramka chroniła przed katastrofą, nie przed regresją. 78 zostawia ~2,3 pp na wahania między przebiegami. Najsłabsze moduły bez zmian, do osobnej roboty: `football_data.py` 21%, `flashscore_results.py` 42%, `utils/cache.py` 56%, `utils/db.py` 69%.
- [ ] **J5 — 4 pliki > 800 linii:** `daily_agent.py` 1022, `superbet.py` 867, `coupons.py` 832, `analyzer.py` 814.

### 🛡️ Odporność na ataki — ZMIERZONA 17.08 (`tests/test_odpornosc_ataki.py`, 25 testów)

| atak | werdykt | dowód |
|---|---|---|
| **Wstrzyknięcie SQL** (`' OR 1=1 --`, `UNION SELECT`, `DROP TABLE`) | ✅ **odporni** | 14 ładunków × 2 pola → wszystkie 401. Ładunek trafia do bazy jako **parametr**, nigdy do tekstu zapytania |
| **Brute-force z jednego IP** | ✅ **blokowany** | 15 prób zgadywania → limiter ucina po 10. Ta sama odpowiedź dla złego hasła i nieistniejącego konta (brak enumeracji) |
| **Brute-force z wielu IP** | ✅ **naprawione (B7, 23.08)** | licznik `failed_attempts` + `locked_until`: po 5 błędach konto zamyka się na rosnące okno (1 → 15 min). Zablokowane konto **nie sprawdza hasła**, więc nie działa jak wyrocznia. Limit per-adres realnie działa od naprawy B2 |
| **Podrobiony token** | ✅ **odrzucany** | obcy sekret → 401; wygasły → 401; bez `uid` → 401 |
| **Skradziony token** | 🟡 **da się uciąć, nie da się wykryć (B10, 23.08)** | `POST /auth/logout-all` unieważnia wszystkie wydane tokeny bez zmiany hasła — wołający dostaje świeży, więc nie odcina sam siebie. **Wykrycie kopii pozostaje niemożliwe i jest to świadomy non-goal:** token jest bezstanowy i wygląda identycznie u właściciela i u napastnika, a powiązanie z IP wylogowywałoby prawdziwych użytkowników przy każdym przejściu LTE↔wifi. Non-goal przypięty testem `test_brak_wiazania_tokenu_z_adresem` |
| **Zmiana hasła po przejęciu konta** | ✅ **naprawione (B1, 17.08)** | `_uniewaznij_sesje` podbija `token_version` przy zmianie hasła ([auth.py:339](src/footstats/api/auth.py#L339)) i przy resecie ([auth.py:435](src/footstats/api/auth.py#L435)) — wszystkie wydane tokeny padają natychmiast |

- [x] ✅ **B10 — ZROBIONE 23.08 w części, która jest wykonalna. `POST /auth/logout-all`.**
  Wyciekłą kopię tokenu da się teraz uciąć bez zmiany hasła — jedno żądanie podbija
  `token_version`, a wołający dostaje świeży token, żeby nie odciął sam siebie
  (bez tego przycisk wylogowywałby też osobę, która go klika, więc nikt by go nie
  używał). +8 testów.
  **CZEGO NIE DA SIĘ ZROBIĆ — i dlaczego to nie jest wymówka:** wykrycie kopii tokenu
  wymaga zapisywania adresu/przeglądarki przy KAŻDYM żądaniu. Token jest bezstanowy
  i u napastnika wygląda identycznie jak u właściciela. Powiązanie z IP **sprawdzone
  i odrzucone**: komórka zmienia adres przy każdym przejściu LTE↔wifi, więc prawdziwi
  użytkownicy wylatywaliby po kilka razy dziennie — zabezpieczenie, które psuje się
  samo, uczy ignorować własne komunikaty, a napastnik w tej samej sieci i tak je omija.
  Non-goal przypięty testem `test_brak_wiazania_tokenu_z_adresem`.
  **Odrzucone w trakcie — `last_login_at`.** Wydawało się tanie i sensowne („zobaczysz
  logowanie o 3 w nocy"), ale **nie dotyczy tej luki**: skradziony TOKEN nigdy się nie
  loguje, złodziej używa gotowej kopii, więc znacznik ani drgnie. Byłaby to kolumna
  wyglądająca jak zabezpieczenie i nim niebędąca — migracja 16 napisana i wycofana.
  Dwa testy-strażniki (`test_token_dziala_z_DOWOLNEGO_adresu…`, `test_token_niesie_wersje_ale_NIE_odcisk…`)
  **zostają zielone i tak ma być** — opisują stan faktyczny, którego świadomie nie zmieniam.
- Trzy testy są celowo zielone WOBEC LUK (`test_BRAK_blokady_konta…`, `test_token_dziala_z_DOWOLNEGO…`, `test_zmiana_hasla_NIE_uniewaznia…`). Po naprawie **padną** — to ich zadanie: wymuszają aktualizację audytu zamiast cichego rozjazdu dokumentacji.

### ✅ Sprawdzone i w porządku
SQL parametryzowany (1 wyjątek wyżej) · JWT fail-closed · bcrypt+gensalt, min. 8 znaków w walidatorach ·
limity 10/5/60 na minutę · nagłówki bezpieczeństwa · CORS z jawnej listy (nie `*`) · `/mcp` off na prodzie ·
CI blokujące (ruff+bandit+pip-audit+coverage) · backup DB codziennie 07:00 · zero sekretów w kodzie ·
klikalne elementy to `<button>`, nie `<div>`.

---

## 📋 Następne kroki (zweryfikowane na produkcji 2026-08-14)

1. **Obserwować budżet API-Football.** 14.08 zjechał do **17/100** — nadrabianie zaległości kosztuje ~8 requestów na przebieg. Przy dwóch przebiegach dziennie może nie starczyć. Regulacja bez redeploya: `LIMIT_NADRABIANIA` (domyślnie 15).
2. **Dobić 7 rozliczonych poisson-dc** → próg 30 → `scripts/porownaj_modele.py` wydaje werdykt. Licznik: `python scripts/stan_uczenia.py`.
3. ✅ **Podzbiory BTTS i O/U rozbite 14.08** — żaden nie przeżył sprawdzenia poza próbą. Szczegóły niżej.
4. ✅ **Migracja 13 (`odds_verified`) WDROŻONA 15.08** — kolumna weszła przez CD (API rew. 00402), joby przebudowane osobno (digest z tagiem `89ae6a28`; dwa nowsze były bez tagu = atestacja BuildKita). **Do sprawdzenia po przebiegu 11:00:** czy pojawiają się wiersze `odds_verified = 1` i czy w logach nie ma WARNINGA „Uzgodniono kursy dla X z Y" (= rozjazd nazw między zapisem a weryfikacją).
5. **Kosmetyka:** usunąć `DATABASE_URL_NEON` z lokalnego `.env` (Neon zbędny; rotacja wymagałaby ich konsoli, brak `NEON_API_KEY`).

> Zamknięte 14.08 (szczegóły → `CHANGELOG.md`): rozjazd wag ensemble · `CRON_SECRET` → `secretKeyRef`
> · backfill Neon + wyłączenie wersji 1 sekretu `DATABASE_URL` · okno rozliczeń · lekcje RAG z trafień
> · diagnostyka blacklisty lig.

### 🎯 Werdykt per rynek (14.08, n=3586, 3 niezależne grupy lig) — TRZY RÓŻNE ODPOWIEDZI
| rynek | werdykt | dowód |
|---|---|---|
| **1X2** | 🔴 przegrany | ROI ~−20% przy każdej wadze; przy niezgodzie rynek 42.9% vs model 29.8% |
| **BTTS** | 🔴 **szkodliwy** | model 53.2% / Brier 0.2496 vs częstość bazowa 54.4% / 0.2480. „Zawsze BTTS tak" **bije model**. Grupa C: 50.5% vs 54.2%. Prod potwierdza: BTTS 18.2% (2/11) |
| **Over/Under 2.5** | 🟡 **jedyna nadzieja** | ROI przy 30/70: A **+9.2%** (106 zakł.), B −3.8%, C −15.5%, **razem −0.2%** (na zero PO podatku). Przy niezgodzie na ligach czołowych model **wygrywa 52.1% do 47.9%** |

**Wnioski do decyzji:**
1. ✅ **Hipoteza „model działa na specyficznych meczach" SPRAWDZONA 14.08 — nie potwierdza się.** Patrz sekcja niżej.
2. ⚠️ **+9,2% na ligach czołowych NIE replikuje się** — patrz sekcja niżej. Tę liczbę trzeba uznać za szum.
3. ⚠️ **Nieaktualne od D4 (24.08), tym bardziej od 26.08.** Wpis mówił, że `model_log` śledzi wyłącznie argmax 1X2 i rynków golowych nie da się dziś zweryfikować live. Dziś mierzymy live: 1X2, Over 2.5, BTTS (D4), remisy (R, `draw_correct`) oraz ranking wszystkich 7 rynków z przewagą nad bazą własnego rynku (D) — szczegóły `CHANGELOG.md` 26.08.

### 🔬 Test podzbiorów BTTS i O/U (14.08, n=15 460, 39 lig) — NIC NIE PRZEŻYŁO
Metoda: próba podzielona **po dacie**. Podzbiory szukane wyłącznie na starszej części
(DISCOVERY, 9226 meczów do 03.01.2026), liczone na nowszej (HOLDOUT, 6234), której szukanie
nie widziało. Bez tego każde dostatecznie drobne cięcie znajduje „przewagę" — tak powstają
strategie działające wyłącznie wstecz.

Wymiary cięcia: liga · pasmo pewności BTTS · suma λ (profil golowy) · λ słabszej strony ·
rozjazd z rynkiem · zgoda/niezgoda z rynkiem. Razem **52 podzbiory**.

| rynek | kandydaci na DISCOVERY | przeżyli HOLDOUT |
|---|---|---|
| **BTTS** | 5 (RUS +5.2pp, BEL +3.2pp, ENG-PL +1.9pp, rozjazd 3-6pp, BRA) | **0** |
| **O/U** | 2 z dodatnim ROI (+8.5%, +7.4%) | **0** |

Oba dodatnie ROI mieściły się w granicy błędu (±11,7pp i ±11,2pp przy 73 i 80 zakładach).
Na HOLDOUT: −6,1% i −4,2%.

**Ligi czołowe (te same 4 co wczoraj), test wczorajszego +9,2%:**
DISCOVERY **−11,4%** (55 zakładów) · HOLDOUT **+12,1%** (61 zakładów) — obie w granicy błędu
(±13,5 i ±12,8), **znak się odwraca**. Wczorajsze +9,2% na 106 zakładach to jedno losowanie
z tego rozkładu, nie przewaga. Lig dodatnich w OBU połowach: **0**.

**Co z tego wynika:** hipoteza „model działa na specyficznych meczach/drużynach, a średnia
to zaciera" została sprawdzona na 4× większej próbie i się nie broni — wzdłuż żadnego
z sześciu wymiarów. To nie zamyka tematu na zawsze (można próbować innych cech, np. formy
czy H2H), ale zamyka drogę „potnijmy istniejące predykcje na kawałki i znajdźmy dobry".

### 🎯 BTTS dwustronne (pomysł usera 15.08) — sygnał REALNY, ale nie bije rynku
**Diagnoza usera trafna:** ścieżka selekcji (`system_paper._ODDS_KEY`) zna wyłącznie
„BTTS" = TAK. Skoro BTTS pada w ~54%, model był strukturalnie wepchnięty w klasę
większościową i nie mógł zagrać tam, gdzie jest pewny, że gole po obu stronach NIE padną.
Wczorajszy werdykt „gorszy od stałej" był więc częściowo artefaktem pomiaru.
(`markets.py:92` ma „BTTS NIE" w katalogu BetBuildera — selekcja go nie widzi.)

**Sygnał istnieje i REPLIKUJE SIĘ** — krzywa monotoniczna w obu połowach:
`p_btts` 0-40% → BTTS pada 48.7% / 51.2%; 65%+ → **60.7% / 64.1%**.
Gra dwustronna przy marginesie 15pp bije stałą odpowiedź w obu połowach:
TAK +7.0/+8.4pp, NIE +6.3/+6.6pp.

**Ale przeciw rynkowi przegrywa** (rynkowe BTTS wyliczone z dopasowania λ do cen O/U,
bo kursów BTTS w datasecie nie ma): Brier model 0.2524/0.2508 vs rynek **0.2503/0.2460**;
przy niezgodzie rynek 52.2%/53.0% vs model 47.8%/47.0%.
**Arytmetyka progu:** NIE trafia 50.8% → wymaga kursu **2.10**, a rynek na „BTTS nie"
w takim meczu daje ~1.6. Nie domyka się.

✅ **ZROBIONE 15.08 (`b51ea5519`)** — przy okazji wyszło, że dwustronność **już istniała**,
tylko potok ją kasował. `koryguj_tip_ou_btts` od dawna przerzuca typ na `"BTTS NO"`, ale:
1. `prob_modelu` nie znało tego typu → pewność zapisywana jako **50 zamiast 100−bt**,
   i to akurat dla typów, których model był NAJPEWNIEJSZY;
2. `_TYP_DO_ODDS_KEY` nie znało → noga kasowana...
3. ...i podpisywana jako **halucynacja Groqa**, choć Groq nie miał z nią nic wspólnego;
4. API-Football i SofaScore zwracają OBIE strony, a parsery brały tylko „yes" — więc nie
   było czym wycenić (`match_tips.py` czytał `btts_no` i dostawał wyłącznie kurs teoretyczny).

Granie strony NIE zostaje za flagą **`BTTS_TWO_WAY` (default OFF)** — typ jest liczony,
wyceniany i logowany, ale nie wchodzi do kuponu. Flip po zebraniu realnych kursów `btts_no`
i zmierzeniu ROI na nich. Pełna tabela dowodów w `.env.example`.

Zastrzeżenie metody: zbieracz nie zapisał kursów 1X2, więc λ rynku dopasowane tylko do O/U.

### 🔍 Ustalone 13-14.08 — nie zgubić
- **`model_log` to główne źródło danych o modelu**, nie `predictions`. Ta druga dostaje wiersz dopiero PO filtrach wartości. `scripts/stan_uczenia.py` czyta już obie.
- **Rozliczenia mają DWIE ścieżki i żadna nie pokrywała wszystkiego:** `cron_settle` rozlicza KUPONY, a wszystkie predykcje System mają `coupon_id IS NULL`. Predykcje luzem rozlicza wyłącznie `update_pending` z jobów.
- **Okno rozliczeń gubiło dane bezpowrotnie** (naprawione 14.08, commit `3d678f557`): filtr domknięty z obu stron zostawił 95 sierot, mecze od 7 maja. Odzyskiwalne było 13, reszta przepadła. Teraz zaległości wracają paczkami po 15 z limitem 5 prób.
- **Odzyskiwalne były NAJSTARSZE, nie najnowsze** — pierwsza paczka (15 najnowszych) odzyskała 0. Założenie „źródła pamiętają świeższe mecze" nie potwierdziło się na tych ligach.
- **`run_migrations()` odpalało wyłącznie API.** Joby dostały to samo 14.08 — wcześniej poprawność zależała od niepisanej kolejności wdrożenia, a brak kolumny wywalał CAŁY dzienny przebieg (KROK 0), nie same rozliczenia.
- **CLV zależy od rozliczeń.** Blok CLV siedzi wewnątrz pętli rozliczania — bez rozliczonej nogi w ogóle nie startuje. Zero wypełnionych przy zerze rozliczeń to stan oczekiwany, nie bug.
- **API-Football zawieszone** (konto suspended) → brak składów i sędziego → sufit DECISION SCORE 70/100. Dla starych meczów zwraca „Brak w API", ale część zapytań przechodzi.
- **Logi jobów idą w `jsonPayload`, nie `textPayload`** (JSON formatter). `severity` też się nie mapuje — pytaj `jsonPayload.level`.
- **Dług testowy:** `$env:DATABASE_URL=""` w PowerShellu KASUJE zmienną (guard widzi `.env` → prod i przerywa suitę). Działa: `python -c "import os,sys; os.environ['DATABASE_URL']=''; import pytest; sys.exit(pytest.main(['tests/','-q']))"`.
- **Schematy testowe dublują produkcyjny** (`test_backtest_db.py`, `test_evening_agent.py` mają własne `CREATE TABLE`) — każda migracja wymaga ręcznego dociągnięcia, inaczej test sprawdza tabelę, której nigdzie nie ma.

---

> **Ukończone → `CHANGELOG.md` + `git log`.** Ostatnie (07-03/04): reset hasła + panel Model vs Live + Kontuzje v2 (rdzeń) + kalibracja health-gate + **cloud migration** (pipeline PC-off) + 10 kuponów Admin_JG (3/3 WON) + Claude setup hardening (guard hook). Wcześniej (06-24/26): OWASP hardening + CI lint/security/coverage gate + cloud-draft live + reweight ku rynkowi + M1 lewary #1/#2 + 4 źródła danych + Daily DB Backup + walk-forward A/B (DC 51.8%). Jeszcze wcześniej: Cel A/B/C, D1-D7, multi-source, RODO, multi-user.

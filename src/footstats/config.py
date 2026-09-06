import os
from pathlib import Path
from dotenv import dotenv_values, load_dotenv, set_key
from footstats.utils.console import console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

# ================================================================
#  STALE
# ================================================================
VERSION         = "v3.4-stable"
DB_PATH         = Path(__file__).parents[2] / "data" / "footstats_backtest.db"
MAX_GOLE        = 8
OSTATNIE_N      = 15
BONUS_DOMOWY    = 1.15
SLEEP_KOLEJKA   = 6.0
SLEEP_LOOP      = 6.0
CACHE_TTL_MIN   = 30

ROTACJA_DNI     = 4
ROTACJA_KARA    = 0.80
ZMECZ_GODZ      = 72
ZMECZ_KARA_OBR  = 0.85
ZEMSTA_MIN_GOLE = 3
ZEMSTA_BONUS    = 1.15

H2H_OKNO_DNI       = 730
H2H_MIN_MECZE      = 2
PATENT_BONUS       = 1.10
FORTRESS_MECZE     = 5
FORTRESS_BONUS_OBR = 1.10
IMP2_PROG_FINAL    = 5
IMP2_BONUS_FINAL   = 1.20
IMP2_WAKACJE       = 0.90
CONFIDENCE_H2H_MAX = 5

REWANZ_OKNO_DNI    = 14
REWANZ_VABANK      = 1.30
REWANZ_PARKING_BUS = 0.75
REWANZ_FORT_OBR    = 1.20
FINAL_REMIS_BOOST  = 1.25

_FINAL_STAGES = {"FINAL", "THIRD_PLACE", "GROUP_STAGE", "PRELIMINARY_ROUND"}
_SINGLE_MATCH_COMPS = {"EC", "WC"}

# ── v2.7 NOWE STALE – MultiSource & Intelligence ───────────────────
PEWNIACZEK_PROG    = 40.0  # min. prawdopodobienstwto (%) dla Pewniaczka (kalibracja: raw 70%→40% realnej)
PEWNIACZEK_DNI     = 7     # ile dni do przodu szukamy (tydzien)
DOMWYJAZD_MIN_M    = 5     # min. mecze dom/wyjazd do analizy
DOMWYJAZD_PODROZNIK= 0.20  # min. roznica wyjazd-dom w pkt/mecz -> "Podroznik"
BZZOIRO_MAX_ROZN   = 20.0  # max. roznica (%) Poisson vs Bzzoiro ML bez alarmu
# Prog pewnosci kandydata dla daily_agent / cloud_draft. SKALA PROCENTOWA (0-100),
# ta sama co PEWNIACZEK_PROG powyzej i MIN_PROB w `system_paper` — wartosc trafia do
# `_typy_pewne`, ktore porownuje ja z pw/pr/pp/bt/o25/u25 wyrazonymi w procentach.
#
# BYLO `0.55` i to NIE byl prog 55%, tylko 0,55% — filtr kandydatow nie odrzucal
# NICZEGO, a `/api/settings` mnozyl te wartosc przez 100 i pokazywal "55.0", wiec
# panel raportowal prog, ktorego nie bylo. Zaden test tego toru nie dotykal.
# Realnie odsiewal dopiero `najlepszy_typ` (MIN_PROB=40) juz na etapie selekcji.
AGENT_KANDYDAT_PROG = float(os.getenv("AGENT_KANDYDAT_PROG", "50"))

# Minimalna pewnosc POJEDYNCZEJ nogi w prompcie kuponu (`build_pewniaczki_prompt`).
# Bylo zaszyte 60% i blokowalo kupon `final` przy 1-3 kandydatach, ktorzy zostaja
# po filtrach wartosci — zmierzone 01.09 na zywym modelu:
#
#     prog | 1 mecz | 3 mecze | 5 meczow      (liczba typow w `top3`)
#       60 |   0    |    0    |    3
#       50 |   1    |    3    |    3
#       45 |   1    |    3    |    3
#       40 |   0    |    1    |    3
#
# 50, nie 45 ani 40, bo linia obok w TYM SAMYM prompcie mowi `<50%: avoid`.
# Nizszy prog postawilby dwie reguly w sprzecznosci, a przy 40% model zaczynal
# cytowac progi, ktorych nikt nie ustawil (63%).
KUPON_MIN_PEWNOSC_PCT = int(os.getenv("KUPON_MIN_PEWNOSC_PCT", "50"))

AGENT_BANKROLL      = 100.0 # bankroll do Kelly Criterion (PLN)
AGENT_KELLY_FRACTION = 4    # bezpieczny fractional Kelly: f*/4 (bardziej konserwatywny dla 100 PLN)

# ── Cel C: Dixon-Coles w produkcji (zwalidowane offline +1.7pp, kalibracja monotoniczna) ──
# Domyslnie ON — blend graceful (DC None -> classic bez zmian), env toggle bez redeploya.
USE_DIXON_COLES = os.getenv("USE_DIXON_COLES", "1").strip() not in ("0", "false", "False", "")

# WAGA OBNIZONA 0.5 -> 0.13 dnia 06.09.2026 (`scripts/ramie_bayesian.py`,
# pre-rejestracja 37ea730aa, holdout >=2024, n=31 628). Waga 0.5 byla wpisana
# z reki i nigdy niedopasowana, a ramie bayesian jest MOCNO zepsute:
#
#     lambda ramienia   2.1585 / 0.9515      przy faktycznych 1.5087 / 1.2146
#
# Gospodarz przeszacowany o 43%, gosc zanizony o 22%. Przyczyna jest w trzech
# stalych po zlej stronie boiska w `poisson_bayesian.predict_match_bayesian`:
# obrona gosca NA WYJEZDZIE to gole gospodarza, wiec jej prior i mianownik
# powinny byc `league_home`, a sa `league_away` (i symetrycznie dla obrony
# gospodarza). Do tego `BONUS_DOMOWY` dokłada atut własnego boiska DRUGI raz,
# bo srednia goli gospodarzy juz go zawiera. Odtworzone na sredniach:
# kod produkcyjny daje 2.12/0.96, a prior po wlasciwej stronie 1.4883/1.1790.
#
# Zmierzone skutki obnizenia wagi (Brier 1X2, holdout):
#     w=0.00  0.62044     w=0.13  0.61991     w=0.50  0.63344  (bylo)
#     sparowana 0.5 -> 0.13:  +0.01352  (z=+19.14), 37 lig na 38
#     po zmieszaniu z cena przy wadze rynku 0.70:  +0.00134  (z=+5.53)
#
# To jest ~45x efekt korekty tau z 05.09 i jedyna zmiana w tej serii, ktora
# realnie widac. Waga 0 jest po zmieszaniu z cena NIE DO ODROZNIENIA od 0.13
# (+0.00000, z=+0.04) — 0.13 zostaje, bo tyle wyszlo z dopasowania na treningu.
#
# UWAGA NA PRZYSZLOSC: 0.13 jest dopasowane do ramienia Z BLEDEM. Po naprawie
# trzech stalych wage trzeba dopasowac OD NOWA — stara wartosc bedzie bez sensu.
W_BAYESIAN      = float(os.getenv("W_BAYESIAN", "0.13"))  # waga ramienia DC (0=classic, 1=pelny DC)

# ── P4 (09.08.2026): korekta τ Dixona-Colesa — DOMYSLNIE WYLACZONA ──
# Ramie nazywane dotad "Dixon-Coles" liczylo `np.outer(pmf_h, pmf_a)`, czyli dwa
# NIEZALEZNE rozklady Poissona. Cala tresc pracy Dixona i Colesa (1997) to
# obserwacja, ze przy niskich wynikach ta niezaleznosc nie zachodzi: 0-0 i 1-1
# padaja czesciej, a 1-0 i 0-1 rzadziej. Bez tej korekty model zaniza remis,
# a remis to jeden z trzech rynkow, na ktorych gramy.
#
# ZMIERZONE 09.08.2026 walk-forwardem na 600 meczach (Bundesliga, PL, La Liga,
# Serie A), historia zawsze sprzed daty meczu:
#
#     rho    Brier     log-loss   trafnosc   sr. P(remis)   [realnie remisow: 25.0%]
#     0.00   0.6833    1.1328     45.5%      18.5%
#    -0.13   0.6803    1.1342     45.5%      20.6%
#    -0.25   0.6789    1.1396     45.5%      22.6%
#    -0.40   0.6786    1.1500     44.8%      25.1%
#
# Wniosek: tau poprawia Brier o grosze i PSUJE log-loss, a przy rho, ktore
# doprowadza sredni remis do realnych 25%, spada tez trafnosc. Innymi slowy
# model zaniza remisy nie dlatego, ze zle liczy zaleznosc niskich wynikow, tylko
# dlatego, ze nie umie wskazac, KTORE mecze skoncza sie remisem. To problem
# rozdzielczosci, nie kalibracji — tau go nie rozwiazuje.
#
# Dlatego flaga zostaje WYLACZONA. Kod jest, pomiar jest, nie trzeba go
# powtarzac; wlaczyc ma sens dopiero, gdy model zyska realna rozdzielczosc.
USE_DC_TAU = os.getenv("USE_DC_TAU", "0").strip() not in ("0", "false", "False", "")
DC_RHO     = float(os.getenv("DC_RHO", "-0.13"))

# ── Korekta tau w GLOWNEJ sciezce (05.09.2026) ──────────────────────────────
# `USE_DC_TAU`/`DC_RHO` wyzej siegaja WYLACZNIE `poisson_bayesian`. Glowna
# sciezka `poisson.predict_match` -> `poisson._macierz` do 05.09.2026 nie miala
# korekty tau w ogole — slowo `rho` w tym pliku nie wystepowalo.
#
# Zmierzone (`scripts/ksztalt_dc.py`, pre-rejestracja 4e0591ab1, holdout >=2024,
# n=31 628): przy rho=0 zanizamy remisy o 1.36 pp (0.2484 wobec 0.2620). rho
# dopasowane na treningu na log-wiarygodnosci FAKTYCZNYCH WYNIKOW wychodzi
# -0.04 i na holdoucie daje Brier 1X2 0.62077 -> 0.62044 (sparowane +0.00032,
# z=+4.76), log-wiarygodnosc wyniku +0.00059 (z=+3.32), 31 lig na 38 dodatnich.
#
# UCZCIWIE O SKALI: po rozcienczeniu blendem 50/50 z ramieniem bayesian i cena
# przy wadze rynku 0.70 zostaje +0.00003 Briera (z=+2.11). Istotne, ale nikt
# tego nie zobaczy. Wdrozone, bo jest darmowe, przetestowane i zgodne z
# kierunkiem bledu — nie dlatego, ze cokolwiek zmienia w wynikach.
#
# tau NIE RUSZA Over 2.5 ani BTTS: poprawki czterech komorek sumuja sie
# tozsamosciowo do zera, a wszystkie maja sume goli <= 2.
# Escape-hatch: `DC_RHO_CLASSIC=0` wraca do zachowania sprzed 05.09.2026.
DC_RHO_CLASSIC = float(os.getenv("DC_RHO_CLASSIC", "-0.04"))

# ── Sila druzyny liczona TEZ ze strzalow celnych (13.08.2026) ──
# Gol to zdarzenie rzadkie (~1.4 na druzyne), wiec srednia z 30 meczow jest
# szumna — to jest zrodlo braku ROZDZIELCZOSCI modelu. Strzal celny pada 4-5x
# czesciej, wiec ta sama probka daje stabilniejsza ocene sily.
#
# ZMIERZONE walk-forwardem na DWOCH niezaleznych probach (waga 0 = stan poprzedni):
#     waga   Brier top-4   Brier 6 innych lig   trafnosc
#     0.0    0.6062        0.6290               47.4-48.6%
#     0.5    0.6020        0.6197               48.0-50.3%
#     0.7    0.6032        0.6180               48.1-50.8%
#     1.0    0.6081        0.6176               48.3-48.4%
#     rynek  0.5919        0.5978               52.2-52.7%
#
# Obie proby zgadzaja sie co do kierunku, roznia sie optimum (czolowe 0.5,
# nizsze 1.0). 0.7 jest bliskie najlepszego na obu i unika ryzyka czystych
# strzalow, ktore na ligach czolowych wypadaly gorzej. WAGA_STRZALOW=0 wraca
# do samych goli bez redeploya.
WAGA_STRZALOW = float(os.getenv("WAGA_STRZALOW", "0.7"))

# Waga warstwy xG w `form.sily_ligowe`, domieszywanej PO strzalach.
# DOMYSLNIE 0 = WYLACZONE. Wlaczenie jest zmiana warstwy predykcji i ma nastapic
# dopiero po zmierzeniu A/B, nie przy okazji wdrozenia. Kolumny `xg_home`/
# `xg_away` nie sa jeszcze promowane do ramki modelu (patrz `data/af_stats.py`:
# kolumna bez czytelnika predzej czy pozniej zostanie uzyta bez pomiaru) — ten
# kod JEST tym czytelnikiem, powstalym przed promocja i przed pomiarem.
WAGA_XG = float(os.getenv("WAGA_XG", "0"))

# ── C2 / Cel B bug 2: override REALNEGO tipu Groq argmaxem modelu ──
# Gdy Groq wybierze 1X2 o prob modelu <15% → podmiana na argmax (konserwatywny).
# FLIP ON 2026-07-06: walidacja zebrana (104 settled) — model argmax 60% vs Groq 48%
# na 1X2 z modelem (+12pp), guard@33 łapie pełny zysk. Groq (llama-3.1-8b) demonstracyjnie
# gorszy od kalibrowanego modelu w wyborze 1X2. Odwracalne: GROQ_TIP_OVERRIDE=0.
GROQ_TIP_OVERRIDE = os.getenv("GROQ_TIP_OVERRIDE", "1").strip() in ("1", "true", "True")
# Próg guardu: Groq tip przetrwa tylko gdy model daje mu >= prog%; inaczej → argmax.
# Audyt 07-06 (104 settled): model argmax 60% vs Groq 48%; guard@15 bezużyteczny
# (48%=48%), guard@33 łapie pełny +12pp (plateau). Default 33 (env-tunable).
GROQ_TIP_OVERRIDE_THRESHOLD = float(os.getenv("GROQ_TIP_OVERRIDE_THRESHOLD", "33"))
# Rynki 2-way (Over/Under, BTTS): flip na stronę modelu gdy prob picku Groq < prog.
# LLM odsunięty od wszystkich picków — tylko analiza/podsumowania. Audyt: BTTS 14%.
GROQ_TIP_OVERRIDE_2WAY = float(os.getenv("GROQ_TIP_OVERRIDE_2WAY", "45"))
# Czy typ "BTTS NIE" moze faktycznie wejsc do kuponu. Default OFF — zmierzone 15.08
# (walk-forward n=15460, proba dzielona po dacie): sygnal `p_btts` jest REALNY
# (krzywa monotoniczna w obu polowach, 65%+ → BTTS pada w 60.7%/64.1%), ale strona
# NIE trafia 50.8%, wiec do zera potrzebuje kursu 2.10, a rynek daje ~1.6.
# Wlaczamy dopiero, gdy zbierzemy realne kursy `btts_no` i zmierzymy ROI na nich.
# Do tego czasu typ jest LICZONY i LOGOWANY, tylko nie gra — jak SELECTION_MIN_CONF.
BTTS_TWO_WAY = os.getenv("BTTS_TWO_WAY", "0").strip() in ("1", "true", "True")

# ── A1: typy powstaja z modelu takze wtedy, gdy warstwa LLM nic nie zwrocila ──
# Poisson/ensemble liczy prawdopodobienstwa i wybiera typ bez udzialu Groqa, ale
# do 08.2026 caly przebieg zapisywal ZERO predykcji, gdy model jezykowy nie wypisal
# listy `top3`. Zdarzylo sie dwa razy w tygodniu: 15.08 (JSON nie sparsowany) i
# 16-22.08 (Groq wycofal `llama-3.1-8b-instant`, 404 przez 6 dni przy exit=0).
# Default ON — awaria, ktora to naprawia, jest calkowita. TYPY_BEZ_LLM=0 cofa
# zapis bez redeploya; wiersze sa oznaczone `kupon_type='model'`, wiec daja sie
# odsiac i zmierzyc osobno od typow, ktore przeszly przez opis LLM-a.
TYPY_BEZ_LLM = os.getenv("TYPY_BEZ_LLM", "1").strip() in ("1", "true", "True")

# Konto docelowe: daily_agent, operator_agent, zapis kuponów systemowych
OPERATOR_ADMIN_USERNAME = os.getenv("OPERATOR_ADMIN_USERNAME", "Admin_JG").strip() or "Admin_JG"
OPERATOR_STAWKA_A = float(os.getenv("OPERATOR_STAWKA_A", "10"))
OPERATOR_STAWKA_B = float(os.getenv("OPERATOR_STAWKA_B", "5"))
OPERATOR_SMOKE_TIMEOUT = int(os.getenv("OPERATOR_SMOKE_TIMEOUT", "120"))

# Ligi do śledzenia (API-Football IDs) są teraz zdefiniowane w results_updater.py

# ── 11.4: Top-5 lig dla Poissona (auto-loop + Understat prefetch) ────────────
# FDCO kod → nazwa ligi (jak w df_mecze["liga"])
LIGI_POISSON_TOP5: dict[str, str] = {
    "E0":  "ENG-Premier League",
    "SP1": "ESP-La Liga",
    "D1":  "GER-Bundesliga",
    "F1":  "FRA-Ligue 1",
    "I1":  "ITA-Serie A",
}

# ── Liga Edge Filter ─────────────────────────────────────────────────────────
#
# Ligi obecne w `data/hist_cache/full_dataset.parquet` → nazwy, pod jakimi
# widzi je źródło predykcji. TYLKO dla nich Poisson ma z czego liczyć λ.
#
# Po co osobna mapa zamiast wpisania nazw wprost do whitelisty: oba zbiory
# rozjechały się po cichu. Dataset ma belgijską ligę jako "BEL-First Division A"
# (2805 meczów), whitelist znała ją wyłącznie jako "Jupiler Pro League",
# a źródło nazywa ją "Pro League" — belgijski mecz przeszedł przez przebieg
# 07.08 i wypadł na samej nazwie, mimo pełnej historii. Szkockiej nie było
# w whiteliście w ogóle. `tests/test_whitelist_pokrycie_datasetu.py` wiąże te
# zbiory: nowa liga w parquecie bez wpisu tutaj = czerwony test.
#
# Warianty szkocki i austriacki wpisane "na zapas" — obie ligi wystartowały
# pod koniec lipca, ale żaden ich mecz nie przeszedł jeszcze przez pipeline,
# więc dokładnego zapisu źródła nie znamy. Nadmiarowy alias nic nie psuje
# (whitelist to test przynależności), brakujący kosztuje całą ligę.
LIGI_DATASETU: tuple[str, ...] = (
    # football-data.co.uk, pliki sezonowe
    "ENG-Premier League", "ENG-Championship", "ENG-League One", "ENG-League Two",
    "ENG-National League",
    "SCO-Premiership", "SCO-Championship", "SCO-League One", "SCO-League Two",
    "GER-Bundesliga", "GER-2. Bundesliga",
    "ITA-Serie A", "ITA-Serie B",
    "ESP-La Liga", "ESP-Segunda Division",
    "FRA-Ligue 1", "FRA-Ligue 2",
    "NED-Eredivisie", "BEL-First Division A",
    "POR-Primeira Liga", "TUR-Super Lig", "GRE-Super League",
    # football-data.co.uk, pliki `new/`
    "POL-Ekstraklasa", "AUT-Bundesliga",
    "ARG-Liga Profesional", "ARG-Copa De La Liga Profesional",
    "BRA-Serie A", "CHN-Super League", "DNK-Superliga", "FIN-Veikkausliiga",
    "IRL-Premier Division", "JPN-J1 League", "MEX-Liga MX", "NOR-Eliteserien",
    "ROU-Superliga", "RUS-Premier League", "SWE-Allsvenskan",
    "SWZ-Super League", "SWZ-Challenge League", "USA-MLS",
)

# Nazwy, pod którymi widzi te ligi ŹRÓDŁO PREDYKCJI — tylko tam, gdzie różnią
# się od samej nazwy po prefiksie kraju. Zebrane z realnych wierszy `model_log`
# tam, gdzie mecz danej ligi już przez pipeline przeszedł; reszta na zapas.
_ALIASY_ZRODLA: dict[str, tuple[str, ...]] = {
    "BEL-First Division A": ("Pro League", "Jupiler Pro League", "Belgian Pro League"),
    "SCO-Premiership":      ("Scottish Premiership",),
    "AUT-Bundesliga":       ("Austrian Bundesliga", "Admiral Bundesliga"),
    "POL-Ekstraklasa":      ("PKO BP Ekstraklasa",),
    "CHN-Super League":     ("Chinese Super League",),
    "DNK-Superliga":        ("Danish Superliga",),
    "BRA-Serie A":          ("Brasileirão Serie A", "Brasileirao Serie A"),
    "ARG-Liga Profesional": ("Liga Profesional de Fútbol", "Liga Profesional de Futbol"),
    "POR-Primeira Liga":    ("Liga Portugal Betclic", "Liga Portugal"),
    "USA-MLS":              ("MLS", "Major League Soccer"),
    "RUS-Premier League":   ("Russian Premier League",),
    "GRE-Super League":     ("Greek Super League",),
    "SWZ-Super League":     ("Swiss Super League",),
    "TUR-Super Lig":        ("Süper Lig",),
    "ESP-Segunda Division": ("LaLiga 2",),
    "GER-2. Bundesliga":    ("2. Bundesliga",),
}


def _aliasy_ligi(liga: str) -> tuple[str, ...]:
    """Pełna nazwa z datasetu + nazwa bez prefiksu kraju + warianty źródła.

    Nazwa bez prefiksu bywa niejednoznaczna („Premier League" to Anglia ORAZ
    Rosja, „Super League" to Grecja ORAZ Szwajcaria). Dla whitelisty to bez
    znaczenia — sprawdza przynależność, więc oba warianty i tak przechodzą.
    """
    krotka = liga.split("-", 1)[1] if "-" in liga else liga
    return tuple(dict.fromkeys((liga, krotka, *_ALIASY_ZRODLA.get(liga, ()))))


LIGI_DATASET_ALIASY: dict[str, tuple[str, ...]] = {
    liga: _aliasy_ligi(liga) for liga in LIGI_DATASETU
}

# Ligi, dla których przepuszczamy kandydatów. Aliasy datasetu dochodzą sumą
# zbiorów — inaczej dopisanie ligi do danych znów mogłoby minąć się z filtrem.
# Pozostałe pozycje to ligi BEZ historii w parquecie: Poisson ich nie policzy,
# predykcja przyjdzie z Bzzoiro-ML i będzie tak oznaczona (`model_source`).
# Zostają świadomie — to wciąż materiał do nauki, tylko cudzego modelu.
LIGI_WHITELIST: frozenset[str] = frozenset({
    *(alias for aliasy in LIGI_DATASET_ALIASY.values() for alias in aliasy),
    # Poniżej WYŁĄCZNIE ligi bez historii w parquecie — nazwy lig z danymi
    # trzymamy w jednym miejscu (LIGI_DATASET_ALIASY), żeby nie mogły się
    # rozjechać po raz drugi.
    "Primeira Liga",
    "Super Lig",
    "Championship",
    "Serie B",
    "Brasileirao Serie A",
    "Liga MX",
    # 2026-06-19: aktywne ligi klubowe (lato — Europa off-season) by System paper-trading
    # zbierał dane teraz.
    "Brasileirao Serie B",
    "USL Championship",
    "Segunda Division",
    "Botola Pro",
    # 2026-06-20 (D1a): MŚ dodane decyzją usera — więcej danych teraz mimo że kadry ≠ model
    # klubowy (świadomy szum walidacji M1). Kwalifikacje MŚ NADAL odrzucane (blacklist "WC Qual").
    "World Cup 2026",
    "World Cup",
    "Mundial",
})

# Słowa kluczowe → odrzuć nawet jeśli liga nie jest w blackliście
LIGI_BLACKLIST_KEYWORDS: tuple[str, ...] = (
    "friendl",          # Friendlies International, Friendly
    "towarzysk",        # polskie towarzyskie
    "Africa Cup",
    "AFCON",
    "CAF",
    "AFC Asian",
    "AFC Qual",
    "CONCACAF",
    "Gold Cup",
    "Copa America",     # bez danych historycznych
    "Nations League A", # tylko jeśli nie mamy danych
    "World Cup Qual",
    "WC Qual",
    "Oceania",
    "OFC",
    "COSAFA",
    "CECAFA",
    "WAFU",
    "UNAF",
    "AFF",              # ASEAN Football Federation
    "SAFF",             # South Asian
)

# M1 lever #2 — gating słabych lig. Ligi z offline accuracy <50% (walk-forward A/B 06-25:
# POL ~44%, ESP ~49%, FRA ~49-50%). Gdy LEAGUE_GATING=1 (env, default OFF) — _pre_filtruj_ligi
# odrzuca te ligi, faworyzując NED/SCO/ITA/ENG (≥M1). Domyślnie OFF = zero zmiany prod;
# flip po walidacji (~88 świeżych settled). Porównanie znormalizowane (akcenty/prefiks/case).
LIGI_SLABE: frozenset[str] = frozenset({
    "Ekstraklasa", "PKO BP Ekstraklasa",          # POL ~44%
    "La Liga", "ESP-La Liga", "Segunda Division",  # ESP ~49-51%
    "Ligue 1", "FRA-Ligue 1",                      # FRA ~49-50%
})

# Jeśli True, daily_agent odrzuca mecze bez danych Poissona
LIGA_FILTER_ENABLED: bool = True

# FAZA 17.4: jeśli True, przepuszczane są TYLKO ligi z LIGI_WHITELIST
# (wcześniej whitelist była no-op — każda liga przechodziła). Wyłącz przez
# LIGA_WHITELIST_ENFORCE=0 w .env jeśli wolumen kandydatów spada za nisko.
LIGA_WHITELIST_ENFORCE: bool = os.getenv("LIGA_WHITELIST_ENFORCE", "1") == "1"

# Klucze .env – nazwy zmiennych srodowiskowych
ENV_FOOTBALL   = "FOOTBALL_API_KEY"   # football-data.org
ENV_APISPORTS  = "APISPORTS_KEY"      # api-sports.io (API-Football)
ENV_BZZOIRO    = "BZZOIRO_KEY"        # sports.bzzoiro.com

# ================================================================
#  MODUL 0 - BEZPIECZENSTWO + MULTI-KEY MANAGER (v2.7)
# ================================================================

ENV_FILE       = Path(".env")
GITIGNORE_FILE = Path(".gitignore")

_GITIGNORE = """\
.env
.env.*
FootStats_*.pdf
__pycache__/
*.py[cod]
venv/
.venv/
.vscode/
.idea/
"""

def _stworz_gitignore():
    if not GITIGNORE_FILE.exists():
        GITIGNORE_FILE.write_text(_GITIGNORE, encoding="utf-8")
        console.print("[dim green]Utworzono .gitignore[/dim green]")

def _wczytaj_lub_stworz_env() -> str:
    """Wczytuje klucz football-data.org (obowiazkowy). Pyta o pozostale."""
    _stworz_gitignore()
    load_dotenv(ENV_FILE)

    klucz = os.getenv(ENV_FOOTBALL, "").strip().strip('"').strip("'")
    if not klucz:
        console.print(Panel(
            "[bold yellow]Nie znaleziono klucza football-data.org![/bold yellow]\n\n"
            "FootStats v2.7 obsluguje [bold]3 darmowe zrodla danych[/bold]:\n\n"
            "  [cyan]1. football-data.org[/cyan]    [dim](obowiazkowy) 10 req/min, 12 lig TOP[/dim]\n"
            "     Rejestracja: [bold]https://www.football-data.org/client/register[/bold]\n\n"
            "  [yellow]2. api-sports.io[/yellow]       [dim](opcjonalny) 100 req/dzien, 1200+ lig![/dim]\n"
            "     Rejestracja: [bold]https://dashboard.api-football.com/register[/bold]\n\n"
            "  [green]3. sports.bzzoiro.com[/green]  [dim](opcjonalny) BEZ LIMITU! ML + kursy[/dim]\n"
            "     Rejestracja: [bold]https://sports.bzzoiro.com/register/[/bold]",
            border_style="yellow", title="[bold yellow]FootStats v2.7 – Pierwsze uruchomienie[/bold yellow]",
            padding=(1, 3)
        ))
        klucz = Prompt.ask("[bold cyan]Klucz football-data.org (obowiazkowy)[/bold cyan]").strip()
        if not ENV_FILE.exists():
            ENV_FILE.write_text("", encoding="utf-8")
        set_key(str(ENV_FILE), ENV_FOOTBALL, klucz)

        # Opcjonalny API-Football
        if Confirm.ask("[yellow]Dodac klucz api-sports.io? (1200+ lig, Ekstraklasa!)[/yellow]",
                       default=False):
            k2 = Prompt.ask("[bold yellow]Klucz api-sports.io[/bold yellow]").strip()
            if k2:
                set_key(str(ENV_FILE), ENV_APISPORTS, k2)

        # Opcjonalny Bzzoiro
        if Confirm.ask("[green]Dodac klucz Bzzoiro? (ML predictions, kursy, BEZ LIMITU)[/green]",
                       default=False):
            k3 = Prompt.ask("[bold green]Klucz sports.bzzoiro.com[/bold green]").strip()
            if k3:
                set_key(str(ENV_FILE), ENV_BZZOIRO, k3)

        load_dotenv(ENV_FILE, override=True)
        klucz = os.getenv(ENV_FOOTBALL, "").strip().strip('"').strip("'")
        console.print(f"[green]Klucze zapisane: {ENV_FILE.resolve()}[/green]\n")

    return klucz

def _czytaj_wszystkie_klucze() -> dict:
    """
    Klucze API: pierwszeństwo ma środowisko, `.env` uzupełnia braki.

    Wcześniej było tu `load_dotenv(ENV_FILE, override=True)`, co nadpisywało CAŁE
    `os.environ` zawartością `.env` — nie tylko trzy klucze poniżej. Konsekwencje:

    * w testach: wystarczyło, że dowolny test dotknął źródła danych (ta funkcja jest
      wołana m.in. z `af_source`, `fetch_odds_af`, `fixtures_fallback`), i testowy
      `FOOTSTATS_PASSWORD_HASH` / `JWT_SECRET` był podmieniany na wartości z `.env`
      — kolejne logowania dostawały 401. Stąd 12 „losowych" failure w pełnej suicie,
      których nie było przy uruchamianiu plików osobno.
    * na produkcji: gdyby `.env` kiedykolwiek trafił do obrazu, przykrywałby
      prawdziwe sekrety wstrzyknięte przez Cloud Run.

    Teraz czytamy plik BEZ mutowania `os.environ` (12-factor: środowisko wygrywa).
    """
    z_pliku = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}

    def _wartosc(nazwa: str) -> str | None:
        surowa = os.getenv(nazwa) or z_pliku.get(nazwa) or ""
        return surowa.strip().strip('"').strip("'") or None

    return {
        ENV_FOOTBALL:  _wartosc(ENV_FOOTBALL),
        ENV_APISPORTS: _wartosc(ENV_APISPORTS),
        ENV_BZZOIRO:   _wartosc(ENV_BZZOIRO),
    }

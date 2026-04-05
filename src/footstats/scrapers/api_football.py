import time
import requests
import pandas as pd
from datetime import datetime
from footstats.utils.cache import (
    _af_cache_get, _af_cache_set, af_budget_use, af_budget_status,
    _af_load_disk_cache, _af_budget_load, _af_budget_save,
    AF_BUDGET_DAILY, AF_WARN_THRESHOLD, AF_BLOCK_THRESHOLD,
)
from footstats.utils.console import console
from footstats.utils.helpers import _s
from footstats.config import ENV_APISPORTS
from rich.panel import Panel

# ================================================================
#  MODUL 4b – API-FOOTBALL (api-sports.io) v2.7
#  Darmowy plan: 100 req/dzien, 1200+ lig (Ekstraklasa, MLS, Saudi...)
# ================================================================

# Mapowanie nazw lig API-Football na wewnetrzne kody i id
_APISPORTS_LIGI = {
    # id : {kod_wewn, nazwa, kraj, druzyny}
    39:  {"kod": "PL",  "nazwa": "Premier League",        "kraj": "England",     "druzyny": 20},
    140: {"kod": "PD",  "nazwa": "Primera Division",       "kraj": "Spain",       "druzyny": 20},
    135: {"kod": "SA",  "nazwa": "Serie A",                "kraj": "Italy",       "druzyny": 20},
    78:  {"kod": "BL1", "nazwa": "Bundesliga",             "kraj": "Germany",     "druzyny": 18},
    61:  {"kod": "FL1", "nazwa": "Ligue 1",                "kraj": "France",      "druzyny": 18},
    94:  {"kod": "PPL", "nazwa": "Primeira Liga",          "kraj": "Portugal",    "druzyny": 18},
    88:  {"kod": "DED", "nazwa": "Eredivisie",             "kraj": "Netherlands", "druzyny": 18},
    40:  {"kod": "ELC", "nazwa": "Championship",           "kraj": "England",     "druzyny": 24},
    2:   {"kod": "CL",  "nazwa": "UEFA Champions League",  "kraj": "Europe",      "druzyny": 36},
    71:  {"kod": "BSA", "nazwa": "Brasileirao Serie A",    "kraj": "Brazil",      "druzyny": 20},
    106: {"kod": "EKS", "nazwa": "PKO BP Ekstraklasa",     "kraj": "Poland",      "druzyny": 18},
    253: {"kod": "MLS", "nazwa": "MLS",                    "kraj": "USA",         "druzyny": 29},
    307: {"kod": "SPL", "nazwa": "Saudi Pro League",       "kraj": "Saudi Arabia","druzyny": 18},
    262: {"kod": "LMX", "nazwa": "Liga MX",                "kraj": "Mexico",      "druzyny": 18},
    144: {"kod": "PRO", "nazwa": "Pro League",             "kraj": "Belgium",     "druzyny": 18},
    179: {"kod": "SPO", "nazwa": "Scottish Premiership",   "kraj": "Scotland",    "druzyny": 12},
}

class APIFootball:
    """
    Klient api-sports.io (API-Football).
    Darmowy: 100 req/dzien, wszystkie endpointy, 1200+ lig.
    Header: x-apisports-key: KEY
    """
    BASE = "https://v3.football.api-sports.io"

    def __init__(self, api_key: str):
        self.headers = {"x-apisports-key": api_key}
        self._valid: bool | None = None
        self._req_today: int = 0

    def waliduj(self) -> tuple[bool, str]:
        """
        Sprawdza klucz przez /status endpoint (1 req).
        Pobiera tez aktualny licznik reqow z serwera (nadrzedny vs nasz lokalny).
        """
        try:
            r = requests.get(f"{self.BASE}/status",
                             headers=self.headers, timeout=10)
            if r.status_code == 200:
                d    = r.json().get("response", {})
                used = d.get("requests", {}).get("current", 0)
                lim  = d.get("requests", {}).get("limit_day", 100)
                self._req_today = used
                self._valid = True

                # Zsynchronizuj lokalny licznik z serwerowym (serwer jest prawda)
                bud = _af_budget_load()
                if used > bud.get("uzyto", 0):
                    bud["uzyto"] = used
                    _af_budget_save(bud)

                pozostalo = lim - used
                kol = "green" if pozostalo > AF_WARN_THRESHOLD else (
                      "yellow" if pozostalo > AF_BLOCK_THRESHOLD else "red")
                return True, (f"[{kol}]OK – {used}/{lim} req/dzien | "
                              f"pozostalo: {pozostalo}[/{kol}]")

            elif r.status_code == 401:
                self._valid = False
                return False, "Nieprawidlowy klucz API-Football (401)"
            else:
                self._valid = False
                return False, f"HTTP {r.status_code}"
        except Exception as e:
            self._valid = False
            return False, str(e)

    def info_cache_i_budzet(self) -> str:
        """Krotki opis cache i budzetu do wyswietlenia w menu."""
        from footstats.utils.cache import af_budget_status, af_cache_info
        bud  = af_budget_status()
        info = af_cache_info()
        kol  = "green" if not bud["ostrzezenie"] else ("yellow" if not bud["krytyczny"] else "red")
        return (
            f"[{kol}]{bud['pozostalo']}/{bud['limit']} req pozostalo[/{kol}] | "
            f"Cache: {info['wpisy']} wpisow ({info['rozmiar_kb']}KB)"
        )

    def _get(self, endpoint: str, params: dict = None,
             force_network: bool = False) -> dict | None:
        """
        Pobiera dane z API-Football z pelna strategia oszczedzania:
          1. Sprawdz disk cache (TTL 24h) – bez zadnego requesta
          2. Jesli cache wazny: uzyj bez pytania sieci
          3. Jesli cache wygasl / brak:
             a. Sprawdz budzet (< AF_BLOCK_THRESHOLD = blokada)
             b. Wyslij request, zrejestruj w budzecie
             c. Zapisz na dysk (porownaj z starym przed nadpisaniem)
        force_network=True: pomija cache i pobiera swiezo (uzywa requesta).
        """
        cache_key = f"af:{endpoint}:{params}"

        # 1. Disk cache – zawsze proba
        if not force_network:
            cached = _af_cache_get(cache_key)
            if cached is not None:
                return cached

        # 2. Sprawdz budzet zanim wykonamy request
        bud = af_budget_status()
        if bud["krytyczny"]:
            # Krytyczny budzet: zwroc co mamy (nawet wygasle), albo None
            stare = _af_load_disk_cache().get(cache_key, {}).get("data")
            if stare:
                console.print(
                    "[yellow]⚠️  Krytyczny budzet AF – uzywam wygaslych danych z cache.[/yellow]"
                )
                return stare
            console.print("[bold red]⛔ Brak cache i budzet krytyczny – pominięto.[/bold red]")
            return None

        # 3. Wyslij request
        try:
            pozostalo = af_budget_use(endpoint)
        except RuntimeError:
            # Budzet zablokowany – sprobuj wygasle dane
            stare = _af_load_disk_cache().get(cache_key, {}).get("data")
            return stare

        try:
            r = requests.get(
                f"{self.BASE}{endpoint}",
                headers=self.headers, params=params, timeout=15
            )
            self._req_today += 1

            if r.status_code == 200:
                data = r.json()
                # Sprawdz stare dane przed zapisem
                stare = _af_load_disk_cache().get(cache_key, {}).get("data")
                _af_cache_set(cache_key, data, stare)
                console.print(
                    f"[dim]AF req uzyto: {bud['uzyto']+1}/{AF_BUDGET_DAILY} "
                    f"| pozostalo ~{pozostalo-1}[/dim]"
                )
                return data

            elif r.status_code == 429:
                console.print(
                    "[bold red]API-Football HTTP 429 – limit dzienny wyczerpany na serwerze![/bold red]\n"
                    "[dim]Dane beda dostepne jutro. Uzywam cache jesli dostepny.[/dim]"
                )
                stare = _af_load_disk_cache().get(cache_key, {}).get("data")
                return stare

            elif r.status_code in (401, 403):
                self._valid = False
                console.print(f"[red]API-Football: blad autoryzacji ({r.status_code})[/red]")
                return None

            return None

        except requests.exceptions.Timeout:
            console.print("[yellow]API-Football: timeout – uzywam cache.[/yellow]")
            stare = _af_load_disk_cache().get(cache_key, {}).get("data")
            return stare
        except Exception as e:
            console.print(f"[yellow]API-Football blad sieci: {e}[/yellow]")
            return None

    def ligi_dodatkowe(self) -> list:
        """Zwraca liste lig dostepnych przez API-Football (z predefiniowanej mapy)."""
        wynik = []
        for api_id, info in _APISPORTS_LIGI.items():
            wynik.append({
                "nazwa":   info["nazwa"],
                "kod":     info["kod"],
                "kraj":    info["kraj"],
                "druzyny": info["druzyny"],
                "api_id":  api_id,
                "zrodlo":  "api-sports.io",
            })
        return sorted(wynik, key=lambda x: x["nazwa"])

    def wyniki_liga(self, api_id: int, sezon: int = None) -> pd.DataFrame | None:
        """Pobiera wyniki dla ligi po api_id."""
        if sezon is None:
            sezon = datetime.now().year if datetime.now().month > 6 else datetime.now().year - 1
        dane = self._get("/fixtures", params={
            "league": api_id, "season": sezon, "status": "FT", "last": 100
        })
        if not dane:
            return None
        mecze = []
        for m in dane.get("response", []):
            goals = m.get("goals", {})
            gg, ga = goals.get("home"), goals.get("away")
            if gg is None or ga is None:
                continue
            teams = m.get("teams", {})
            gosp = _s(teams.get("home", {}).get("name"))
            gosc = _s(teams.get("away", {}).get("name"))
            date_str = m.get("fixture", {}).get("date", "")[:10]
            mecze.append({
                "data":        date_str,
                "data_full":   m.get("fixture", {}).get("date", date_str),
                "gospodarz":   gosp,
                "goscie":      gosc,
                "gole_g":      int(gg),
                "gole_a":      int(ga),
                "kolejka":     m.get("league", {}).get("round"),
                "stage":       "REGULAR_SEASON",
                "competition": _APISPORTS_LIGI.get(api_id, {}).get("kod", str(api_id)),
            })
        return pd.DataFrame(mecze) if mecze else None

    def nadchodzace_liga(self, api_id: int, sezon: int = None) -> pd.DataFrame | None:
        """Pobiera nadchodzace mecze dla ligi."""
        if sezon is None:
            sezon = datetime.now().year if datetime.now().month > 6 else datetime.now().year - 1
        dane = self._get("/fixtures", params={
            "league": api_id, "season": sezon, "status": "NS", "next": 40
        })
        if not dane:
            return None
        mecze = []
        for m in dane.get("response", []):
            teams   = m.get("teams", {})
            gosp    = _s(teams.get("home", {}).get("name"))
            gosc    = _s(teams.get("away", {}).get("name"))
            date_str= m.get("fixture", {}).get("date", "")[:10]
            mecze.append({
                "data":        date_str,
                "data_full":   m.get("fixture", {}).get("date", date_str),
                "godzina":     m.get("fixture", {}).get("date", "")[:16] + " UTC",
                "gospodarz":   gosp,
                "goscie":      gosc,
                "kolejka":     m.get("league", {}).get("round"),
                "stage":       "REGULAR_SEASON",
                "first_leg_g": None,
                "first_leg_a": None,
            })
        return pd.DataFrame(mecze) if mecze else None

    def tabela_liga(self, api_id: int, sezon: int = None) -> pd.DataFrame | None:
        """Pobiera tabele dla ligi."""
        if sezon is None:
            sezon = datetime.now().year if datetime.now().month > 6 else datetime.now().year - 1
        dane = self._get("/standings", params={"league": api_id, "season": sezon})
        if not dane:
            return None
        try:
            tabela = dane["response"][0]["league"]["standings"][0]
        except (IndexError, KeyError):
            return None
        wiersze = []
        for w in tabela:
            wiersze.append({
                "Poz.":    w["rank"],
                "Druzyna": _s(w["team"].get("name")),
                "M":       w["all"]["played"],
                "W":       w["all"]["win"],
                "R":       w["all"]["draw"],
                "P":       w["all"]["lose"],
                "BZ":      w["all"]["goals"]["for"],
                "BS":      w["all"]["goals"]["against"],
                "Bramki":  f"{w['all']['goals']['for']}:{w['all']['goals']['against']}",
                "+/-":     w["goalsDiff"],
                "Pkt":     w["points"],
            })
        return pd.DataFrame(wiersze) if wiersze else None

    def kandydaci_liga(
        self,
        api_id: int,
        godziny: int = 72,
        prog_pw: float = 0.50,
    ) -> list[dict]:
        """
        Pobiera nadchodzące mecze ligi + predykcje API-Football.
        Zwraca listę w formacie kompatybilnym z Bzzoiro (pw/pr/pp/o25/bt itd.)
        gotową do połączenia z wynikami szybkie_pewniaczki_2dni().

        api_id   – id ligi w API-Football (np. 106 = Ekstraklasa)
        godziny  – ile godzin do przodu (72 = 3 dni)
        prog_pw  – minimalny prog prawdopodobieństwa (0.50 = 50%)
        """
        from datetime import timezone
        sezon = datetime.now().year if datetime.now().month > 6 else datetime.now().year - 1

        # 1. Pobierz nadchodzące mecze
        dane = self._get("/fixtures", params={
            "league": api_id, "season": sezon, "status": "NS", "next": 20
        })
        if not dane:
            return []

        now_utc = datetime.now(timezone.utc)
        wyniki  = []

        for m in dane.get("response", []):
            # Filtruj po oknie czasowym
            date_str = m.get("fixture", {}).get("date", "")
            if not date_str:
                continue
            try:
                match_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                diff_h   = (match_dt - now_utc).total_seconds() / 3600
                if diff_h < 0 or diff_h > godziny:
                    continue
            except ValueError:
                continue

            fix_id   = m.get("fixture", {}).get("id")
            teams    = m.get("teams", {})
            gosp     = _s(teams.get("home", {}).get("name", ""))
            gosc     = _s(teams.get("away", {}).get("name", ""))
            liga_str = _APISPORTS_LIGI.get(api_id, {}).get("nazwa", str(api_id))

            # 2. Pobierz predykcje dla tego meczu (1 req/mecz)
            pred_data = self._get("/predictions", params={"fixture": fix_id})
            pw = pr = pp = o25 = bt = 50.0
            odds: dict = {}

            if pred_data:
                pred_list = pred_data.get("response", [])
                if pred_list:
                    p = pred_list[0]
                    pct = p.get("predictions", {}).get("percent", {})
                    try:
                        pw  = float((pct.get("home", "50%") or "50%").replace("%", ""))
                        pr  = float((pct.get("draw", "25%") or "25%").replace("%", ""))
                        pp  = float((pct.get("away", "25%") or "25%").replace("%", ""))
                    except (ValueError, TypeError):
                        pass

                    # Kursy z predykcji API (jeśli dostępne)
                    comp = p.get("comparison", {})
                    # Brak kursów w /predictions – zostawiamy puste

            # Filtruj po progu
            max_p = max(pw, pr, pp) / 100.0
            if max_p < prog_pw:
                continue

            wyniki.append({
                "gospodarz": gosp,
                "goscie":    gosc,
                "liga":      liga_str,
                "data":      date_str[:10],
                "godzina":   date_str[11:16],
                "pw":        pw,
                "pr":        pr,
                "pp":        pp,
                "o25":       o25,
                "bt":        bt,
                "odds":      odds,
                "metoda":    "API-Football",
                "typy": [
                    ("1", pw / 100),
                    ("X", pr / 100),
                    ("2", pp / 100),
                ],
            })

        return wyniki


"""
footstats_logging.py – Modul logowania i obslugi bledow dla FootStats v2.7

Zamiast modyfikowac 5000-liniowy skrypt w jednym miejscu, ten modul
patchuje kluczowe funkcje przez monkey-patching i context managery.

UZYCIE:
    # Na poczatku footstats.cli dodaj:
    from footstats.utils import logging as footstats_logging
    footstats_logging.inicjalizuj()

    # Albo uruchom sam (testuje handler):
    python -m footstats.utils.logging

ARCHITEKTURA LOGOWANIA:
    Poziomy:
      DEBUG   – szczegoly cache, parsowania, normalizacji
      INFO    – kazdá operacja sieciowa, zaladowanie ligi, wynik analizy
      WARNING – dane niepelne, format nieznany, prog budzetu
      ERROR   – blad HTTP, blad parsowania, brakujacy plik
      CRITICAL– wyczerpany budzet AF, brak polaczenia, crash

    Wyjscia:
      footstats.log   – plik obrotowy (max 2 MB x 3 kopie)
      stderr          – tylko WARNING+ (nie zaglusza Rich UI)
"""

import logging
import logging.handlers
import functools
import traceback
import time
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Callable

# ── Konfiguracja ────────────────────────────────────────────────────

LOG_FILE    = Path("footstats.log")
LOG_LEVEL   = logging.DEBUG          # do pliku
CONS_LEVEL  = logging.WARNING        # do stderr (nie zakłóca Rich UI)
MAX_BYTES   = 2 * 1024 * 1024        # 2 MB
BACKUP_CNT  = 3                      # 3 kopie rotacyjne

# Singleton – zainicjalizowany tylko raz
_logger_ready = False
logger = logging.getLogger("footstats")


def inicjalizuj(log_file: Path = LOG_FILE,
                file_level: int = LOG_LEVEL,
                console_level: int = CONS_LEVEL) -> logging.Logger:
    """
    Inicjalizuje system logowania.
    Bezpieczny do wywolania wielokrotnie (idempotentny).

    Returns:
        Logger glowny 'footstats'
    """
    global _logger_ready
    if _logger_ready:
        return logger

    logger.setLevel(logging.DEBUG)

    # ── Handler: plik rotacyjny ─────────────────────────────────────
    fmt_plik = logging.Formatter(
        fmt="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    try:
        fh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_CNT,
            encoding="utf-8"
        )
        fh.setLevel(file_level)
        fh.setFormatter(fmt_plik)
        logger.addHandler(fh)
    except OSError as e:
        print(f"[WARN] Nie mozna otworzyc pliku logow {log_file}: {e}", file=sys.stderr)

    # ── Handler: stderr (tylko WARNING+, nie zakloca Rich) ──────────
    fmt_cons = logging.Formatter("[%(levelname)s] %(message)s")
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(console_level)
    sh.setFormatter(fmt_cons)
    logger.addHandler(sh)

    logger.propagate = False
    _logger_ready = True
    logger.info("FootStats logger zainicjalizowany | plik: %s", log_file.resolve())
    return logger


# ════════════════════════════════════════════════════════════════════
#  DEKORATORY OBSLUGI BLEDOW
# ════════════════════════════════════════════════════════════════════

def bezpieczna_funkcja(
    fallback=None,
    log_poziom: int = logging.ERROR,
    opis: str = ""
):
    """
    Dekorator: lapie WSZYSTKIE wyjatki, loguje je i zwraca fallback.

    Przyklad:
        @bezpieczna_funkcja(fallback=None, opis="parsowanie ML")
        def _bzz_parse_prob(pred_ml): ...
    """
    def dekorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                nazwa = opis or func.__name__
                logger.log(log_poziom,
                    "Blad w [%s]: %s | args=%s",
                    nazwa, exc, _skroc_args(args, kwargs),
                    exc_info=True
                )
                return fallback() if callable(fallback) else fallback
        return wrapper
    return dekorator


def mierz_czas(prog_next: str = ""):
    """
    Dekorator: loguje czas wykonania funkcji na poziomie DEBUG.
    Przyklad: @mierz_czas("pobieranie danych")
    """
    def dekorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            wynik = func(*args, **kwargs)
            dt = time.perf_counter() - t0
            logger.debug("%s() zakonczona w %.3fs", func.__name__, dt)
            return wynik
        return wrapper
    return dekorator


def _skroc_args(args: tuple, kwargs: dict, max_len: int = 120) -> str:
    """Bezpieczna reprezentacja argumentow (do logow)."""
    try:
        s = str(args[:2])[1:-1] + (", " + str(list(kwargs.keys())) if kwargs else "")
        return s[:max_len] + "…" if len(s) > max_len else s
    except Exception:
        return "(nieczytelne args)"


# ════════════════════════════════════════════════════════════════════
#  WZORCE TRY-EXCEPT DLA KLUCZOWYCH OBSZAROW
# ════════════════════════════════════════════════════════════════════

class BladPolaczenia(Exception):
    """Rzucany gdy HTTP request calkowicie sie nie powiodl."""
    pass


class BladBudzetu(Exception):
    """Rzucany gdy dzienny budzet API-Football < AF_BLOCK_THRESHOLD."""
    pass


class BladDanych(Exception):
    """Rzucany gdy dane z API maja nieznany format lub sa puste."""
    pass


# ── HTTP GET – z logowaniem i retry ────────────────────────────────

class BezpiecznyHTTP:
    """
    Context manager / helper do bezpiecznych zapytan HTTP.

    Uzycie zamiast nagiega requests.get():
        wynik = BezpiecznyHTTP.get(url, params, headers, retries=2)
    """

    @staticmethod
    def get(url: str,
            params: dict = None,
            headers: dict = None,
            timeout: int = 15,
            retries: int = 2) -> dict | None:
        """
        Bezpieczne GET z retry i pelnym logowaniem.

        Returns:
            Slownik JSON lub None przy bledzie.

        Raises:
            BladPolaczenia – gdy wszystkie retry sie nie powiodly
        """
        import requests

        for prob in range(retries + 1):
            try:
                logger.debug("HTTP GET [proba %d/%d]: %s | params=%s",
                             prob + 1, retries + 1, url, params)

                r = requests.get(url, headers=headers, params=params, timeout=timeout)
                logger.debug("HTTP %d <- %s (%.2fs)",
                             r.status_code, url, r.elapsed.total_seconds())

                if r.status_code == 200:
                    dane = r.json()
                    logger.info("OK: %s | %d bajtow", url, len(r.content))
                    return dane

                elif r.status_code == 429:
                    czekaj = 62
                    logger.warning("429 Rate Limit: %s | czekam %ds...", url, czekaj)
                    time.sleep(czekaj)
                    continue  # retry po oczekiwaniu

                elif r.status_code == 401:
                    logger.error("401 Unauthorized: %s | sprawdz klucz API", url)
                    return None

                elif r.status_code == 403:
                    logger.error("403 Forbidden: %s | zly klucz lub plan", url)
                    return None

                elif r.status_code == 404:
                    logger.warning("404 Not Found: %s", url)
                    return None

                elif r.status_code >= 500:
                    logger.error("Blad serwera %d: %s", r.status_code, url)
                    if prob < retries:
                        time.sleep(5 * (prob + 1))
                        continue
                    return None

                else:
                    logger.warning("Nieoczekiwany HTTP %d: %s", r.status_code, url)
                    return None

            except requests.exceptions.ConnectionError as e:
                logger.error("Brak polaczenia z internetem (proba %d/%d): %s",
                             prob + 1, retries + 1, e)
                if prob < retries:
                    time.sleep(3)
                    continue
                raise BladPolaczenia(f"Brak polaczenia: {url}") from e

            except requests.exceptions.Timeout:
                logger.warning("Timeout %ds (proba %d/%d): %s",
                               timeout, prob + 1, retries + 1, url)
                if prob < retries:
                    continue
                return None

            except requests.exceptions.JSONDecodeError as e:
                logger.error("Blad parsowania JSON: %s | %s", url, e)
                return None

            except Exception as e:
                logger.critical("Nieoczekiwany blad HTTP: %s | %s",
                                url, e, exc_info=True)
                return None

        return None


# ── Cache – z logowaniem ────────────────────────────────────────────

class BezpiecznyCache:
    """
    Bezpieczny wrapper do operacji cache (RAM + dysk).
    Wszystkie bledy loguje zamiast crashowac program.
    """

    @staticmethod
    def wczytaj_json(sciezka: Path) -> dict | None:
        """Wczytuje JSON z dysku z pelna obsługa błędów."""
        if not sciezka.exists():
            logger.debug("Cache miss (brak pliku): %s", sciezka)
            return None
        try:
            import json
            dane = json.loads(sciezka.read_text(encoding="utf-8"))
            logger.debug("Cache HIT (dysk): %s", sciezka)
            return dane
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Uszkodzony cache JSON %s: %s | usuwam", sciezka, e)
            try:
                sciezka.unlink(missing_ok=True)
            except OSError:
                pass
            return None
        except PermissionError as e:
            logger.error("Brak uprawnien do cache %s: %s", sciezka, e)
            return None
        except OSError as e:
            logger.error("Blad I/O cache %s: %s", sciezka, e)
            return None

    @staticmethod
    def zapisz_json(sciezka: Path, dane: dict) -> bool:
        """Zapisuje JSON na dysk atomowo (przez plik tymczasowy)."""
        import json
        tmp = sciezka.with_suffix(".tmp")
        try:
            sciezka.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(dane, ensure_ascii=False, indent=None,
                           separators=(',', ':')),
                encoding="utf-8"
            )
            tmp.replace(sciezka)  # atomowa podmiana na Windows i Linux
            logger.debug("Cache zapisany: %s (%d bajtow)",
                         sciezka, sciezka.stat().st_size)
            return True
        except PermissionError as e:
            logger.error("Brak uprawnien do zapisu cache %s: %s", sciezka, e)
        except OSError as e:
            logger.error("Blad zapisu cache %s: %s", sciezka, e)
        except Exception as e:
            logger.critical("Nieoczekiwany blad zapisu cache: %s", e, exc_info=True)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        return False


# ── Parsowanie danych – z logowaniem ───────────────────────────────

def bezpieczny_parse_prob(pred_ml: dict) -> tuple | None:
    """
    Wersja _bzz_parse_prob z pelnym logowaniem.
    Zastepuje oryginal przy wlaczeniu modulu.

    Edge cases ktore logujemy:
      - pred_ml = None → DEBUG
      - Pusty slownik {} → DEBUG
      - Suma prawdopodobienstw < 5 → WARNING (dane niespojne)
      - Nieznany format → WARNING
      - Wyjatki → ERROR z traceback
    """
    if not pred_ml:
        logger.debug("_bzz_parse_prob: pred_ml jest None/pusty")
        return None

    if not isinstance(pred_ml, dict):
        logger.warning("_bzz_parse_prob: oczekiwano dict, dostano %s: %r",
                       type(pred_ml).__name__, str(pred_ml)[:80])
        return None

    logger.debug("_bzz_parse_prob: parsowanie | klucze=%s", list(pred_ml.keys())[:8])

    def p(v):
        if v is None:
            return 0.0
        try:
            f = float(str(v).strip().rstrip('%'))
            if f < 0 or f > 1000:
                logger.warning("_bzz_parse_prob: podejrzana wartosc %r → 0", v)
                return 0.0
            # Scisle < 1.0: 1.0 to 1%, nie 100%
            return f * 100 if 0 < f < 1.0 else f
        except (ValueError, TypeError) as e:
            logger.debug("_bzz_parse_prob: nie mozna skonwertowac %r: %s", v, e)
            return 0.0

    def norm(pw, pr, pp, bt=0.0, o25=0.0):
        s = pw + pr + pp
        if s < 5:
            logger.warning("_bzz_parse_prob: suma 1X2=%.1f < 5 → dane niespojne", s)
            return None
        if abs(s - 100) > 50:
            logger.warning("_bzz_parse_prob: suma=%.1f mocno odstaje od 100%%", s)
        return (round(pw/s*100, 1), round(pr/s*100, 1),
                round(100 - pw/s*100 - pr/s*100, 1),
                round(min(max(bt, 0), 100), 1),
                round(min(max(o25, 0), 100), 1))

    try:
        # Format A: percent.home/draw/away (glowny)
        pct = pred_ml.get("percent") or pred_ml.get("percentages")
        if isinstance(pct, dict):
            pw, pr, pp = p(pct.get("home")), p(pct.get("draw")), p(pct.get("away"))
            if pw + pr + pp > 5:
                logger.debug("_bzz_parse_prob: Format A | 1=%.1f X=%.1f 2=%.1f", pw, pr, pp)
                bt  = p(pct.get("btts") or pred_ml.get("btts", 0))
                o25 = p(pct.get("over_2_5") or pred_ml.get("over_2_5", 0))
                return norm(pw, pr, pp, bt, o25)

        # Format B: home_win_prob / draw_prob / away_win_prob
        if "home_win_prob" in pred_ml:
            pw = p(pred_ml.get("home_win_prob"))
            pr = p(pred_ml.get("draw_prob"))
            pp = p(pred_ml.get("away_win_prob"))
            if pw + pr + pp > 5:
                logger.debug("_bzz_parse_prob: Format B | 1=%.1f X=%.1f 2=%.1f", pw, pr, pp)
                return norm(pw, pr, pp,
                            p(pred_ml.get("btts", 0)),
                            p(pred_ml.get("over_2_5", 0)))

        # Format C: home/draw/away bezposrednio
        if all(k in pred_ml for k in ("home", "draw", "away")):
            pw, pr, pp = p(pred_ml["home"]), p(pred_ml["draw"]), p(pred_ml["away"])
            if pw + pr + pp > 5:
                logger.debug("_bzz_parse_prob: Format C | 1=%.1f X=%.1f 2=%.1f", pw, pr, pp)
                return norm(pw, pr, pp)

        # Format D: zagniezdzone
        nested = pred_ml.get("predictions") or pred_ml.get("prediction")
        if isinstance(nested, dict):
            logger.debug("_bzz_parse_prob: Format D (zagniezdzone), deleguje rekurencyjnie")
            return bezpieczny_parse_prob(nested)

        logger.warning("_bzz_parse_prob: nieznany format | klucze=%s",
                       list(pred_ml.keys())[:10])
        return None

    except RecursionError:
        logger.error("_bzz_parse_prob: za duze zagniezdzone (max glebokosc)")
        return None
    except Exception as e:
        logger.error("_bzz_parse_prob: nieoczekiwany blad: %s", e, exc_info=True)
        return None


# ── Budzet API-Football – z logowaniem ─────────────────────────────

def bezpieczny_budget_use(endpoint: str,
                          budget_daily: int = 100,
                          block_threshold: int = 5,
                          warn_threshold: int = 20) -> int:
    """
    Wersja af_budget_use z pelnym logowaniem stanow budzetu.
    Rzuca BladBudzetu zamiast RuntimeError (latwiej lapac).
    """
    import json
    from pathlib import Path

    cache_dir  = Path(".cache")
    budget_file = cache_dir / "af_budget.json"

    # Zaladuj budzet z dysku
    budzet = BezpiecznyCache.wczytaj_json(budget_file) or {
        "dzien": datetime.now().strftime("%Y-%m-%d"),
        "uzyto": 0,
        "historia": []
    }

    # Reset o polnocy
    dzis = datetime.now().strftime("%Y-%m-%d")
    if budzet.get("dzien") != dzis:
        logger.info("Budzet AF zresetowany (nowy dzien: %s)", dzis)
        budzet = {"dzien": dzis, "uzyto": 0, "historia": []}

    budzet["uzyto"] = budzet.get("uzyto", 0) + 1
    historia = budzet.get("historia", [])
    historia.append({"ts": datetime.now().strftime("%H:%M:%S"), "endpoint": endpoint[:60]})
    budzet["historia"] = historia[-50:]
    BezpiecznyCache.zapisz_json(budget_file, budzet)

    pozostalo = budget_daily - budzet["uzyto"]
    logger.info("Budzet AF: %d/%d uzyto | %d pozostalo | endpoint=%s",
                budzet["uzyto"], budget_daily, pozostalo, endpoint[:40])

    if pozostalo < block_threshold:
        logger.critical("KRYTYCZNY brak budzetu AF: %d pozostalo! Blokuje zapytania.",
                        pozostalo)
        raise BladBudzetu(
            f"Dzienny limit API-Football wyczerpany ({pozostalo}/{budget_daily} req). "
            f"Poczekaj do polnocy lub zmniejsz czestotliwosc skanowania."
        )

    if pozostalo < warn_threshold:
        logger.warning("Niski budzet AF: %d/%d pozostalo na dzis", pozostalo, budget_daily)

    return pozostalo


# ── Pobieranie danych ligi – z obsługa błędów ─────────────────────

class BezpiecznePobieranie:
    """
    Context manager dla wielokrokowego pobierania danych ligi.
    Zapewnia ze nawet przy bledzie jednego zrodla program nie crashuje.

    Uzycie:
        with BezpiecznePobieranie("Serie A") as bp:
            tabela = bp.wykonaj(api.tabela, "SA", fallback=None)
            wyniki = bp.wykonaj(api.wyniki, "SA", 100, fallback=pd.DataFrame())
        if bp.ma_bledy:
            print(f"Ostrzezenia: {bp.bledy}")
    """

    def __init__(self, nazwa_ligi: str):
        self.nazwa  = nazwa_ligi
        self.bledy  = []
        self._start = time.perf_counter()

    def __enter__(self):
        logger.info("Rozpoczynam pobieranie danych: %s", self.nazwa)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        dt = time.perf_counter() - self._start
        if exc_type is not None:
            logger.error("Krytyczny blad pobierania [%s] po %.1fs: %s",
                         self.nazwa, dt, exc_val, exc_info=True)
            return False  # nie tlumimy wyjatku
        if self.bledy:
            logger.warning("Pobieranie [%s] zakonczone z %d ostrzezeniami (%.1fs): %s",
                           self.nazwa, len(self.bledy), dt, "; ".join(self.bledy[:3]))
        else:
            logger.info("Pobieranie [%s] zakonczone pomyslnie (%.1fs)", self.nazwa, dt)
        return False

    def wykonaj(self, func: Callable, *args, fallback=None, opis: str = "") -> Any:
        """
        Wykonuje func(*args) bezpiecznie.
        Przy bledzie zapisuje go do self.bledy i zwraca fallback.
        """
        nazwa_f = opis or getattr(func, "__name__", str(func))
        try:
            wynik = func(*args)
            if wynik is None:
                self.bledy.append(f"{nazwa_f}: zwrocilo None")
                logger.warning("[%s] %s zwrocilo None", self.nazwa, nazwa_f)
                return fallback
            return wynik
        except BladPolaczenia as e:
            self.bledy.append(f"{nazwa_f}: brak polaczenia")
            logger.error("[%s] Brak polaczenia przy %s: %s", self.nazwa, nazwa_f, e)
            return fallback
        except BladBudzetu as e:
            self.bledy.append(f"{nazwa_f}: wyczerpany budzet AF")
            logger.critical("[%s] Wyczerpany budzet: %s", self.nazwa, e)
            raise  # budzet = krytyczny, nie tlumimy
        except Exception as e:
            self.bledy.append(f"{nazwa_f}: {type(e).__name__}")
            logger.error("[%s] Blad %s: %s", self.nazwa, nazwa_f, e, exc_info=True)
            return fallback

    @property
    def ma_bledy(self) -> bool:
        return bool(self.bledy)


# ── Walidacja formatu DataFrame ─────────────────────────────────────

def waliduj_df_wyniki(df, nazwa: str = "df_wyniki") -> bool:
    """
    Sprawdza czy DataFrame z wynikami ma wymagane kolumny i typy.
    Loguje wszystkie problemy.

    Returns:
        True jesli DataFrame jest poprawny i uzyteczny.
    """
    import pandas as pd

    wymagane = {"gospodarz", "goscie", "gole_g", "gole_a", "data"}

    if df is None:
        logger.error("waliduj_df: %s jest None", nazwa)
        return False

    if not isinstance(df, pd.DataFrame):
        logger.error("waliduj_df: %s ma typ %s zamiast DataFrame",
                     nazwa, type(df).__name__)
        return False

    if df.empty:
        logger.warning("waliduj_df: %s jest pusty (0 wierszy)", nazwa)
        return False

    brakujace = wymagane - set(df.columns)
    if brakujace:
        logger.error("waliduj_df: %s brakuje kolumn: %s | dostepne: %s",
                     nazwa, brakujace, list(df.columns))
        return False

    # Sprawdz typy numeryczne
    for kol in ("gole_g", "gole_a"):
        if kol in df.columns:
            try:
                niezero = df[kol].dropna()
                if niezero.lt(0).any():
                    logger.warning("waliduj_df: %s.%s zawiera wartosci ujemne", nazwa, kol)
                if niezero.gt(30).any():
                    logger.warning("waliduj_df: %s.%s zawiera wartosci > 30 (podejrzane?)",
                                   nazwa, kol)
            except Exception as e:
                logger.warning("waliduj_df: nie mozna sprawdzic %s.%s: %s", nazwa, kol, e)

    # Sprawdz puste nazwy druzyn
    for kol in ("gospodarz", "goscie"):
        if kol in df.columns:
            puste = df[kol].isna().sum() + (df[kol] == "").sum()
            if puste > 0:
                logger.warning("waliduj_df: %s.%s ma %d pustych wartosci", nazwa, kol, puste)

    logger.debug("waliduj_df: %s OK | %d wierszy, kolumny=%s",
                 nazwa, len(df), list(df.columns))
    return True


# ════════════════════════════════════════════════════════════════════
#  RAPORT DIAGNOSTYCZNY
# ════════════════════════════════════════════════════════════════════

def raport_diagnostyczny() -> dict:
    """
    Zwraca slownik z diagnostyką systemu:
    - stan plikow konfiguracyjnych
    - dostepnosc bibliotek
    - stan cache
    - ostatnie bledy z logu

    Uzycie:
        from footstats.utils.logging import raport_diagnostyczny
        info = raport_diagnostyczny()
        print(info)
    """
    raport = {
        "timestamp": datetime.now().isoformat(),
        "pliki":     {},
        "biblioteki": {},
        "cache":     {},
        "log":       {},
    }

    # ── Pliki ──────────────────────────────────────────────────────
    for p in [Path(".env"), Path("footstats.py"), Path("footstats.log")]:
        raport["pliki"][str(p)] = {
            "istnieje":  p.exists(),
            "rozmiar_kb": round(p.stat().st_size / 1024, 1) if p.exists() else 0,
        }

    # ── Cache ──────────────────────────────────────────────────────
    cache_dir = Path(".cache")
    raport["cache"]["katalog_istnieje"] = cache_dir.exists()
    if cache_dir.exists():
        pliki = list(cache_dir.glob("*.json"))
        raport["cache"]["pliki_json"] = len(pliki)
        raport["cache"]["rozmiar_kb"] = round(
            sum(p.stat().st_size for p in pliki) / 1024, 1
        )
        budget = BezpiecznyCache.wczytaj_json(cache_dir / "af_budget.json")
        if budget:
            raport["cache"]["budzet_af"] = {
                "dzien":     budget.get("dzien"),
                "uzyto":     budget.get("uzyto", 0),
                "pozostalo": 100 - budget.get("uzyto", 0),
            }

    # ── Biblioteki ─────────────────────────────────────────────────
    for lib in ["requests", "pandas", "numpy", "scipy", "rich",
                "reportlab", "dotenv"]:
        try:
            mod = __import__(lib)
            ver = getattr(mod, "__version__", "?")
            raport["biblioteki"][lib] = {"ok": True, "wersja": ver}
        except ImportError:
            raport["biblioteki"][lib] = {"ok": False, "wersja": None}
            logger.warning("Brakuje biblioteki: %s", lib)

    # ── Ostatnie linie logu ────────────────────────────────────────
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, encoding="utf-8") as f:
                linie = f.readlines()
            raport["log"]["linie_total"] = len(linie)
            raport["log"]["ostatnie_5"] = [l.rstrip() for l in linie[-5:]]
            bledy = [l for l in linie if " ERROR " in l or " CRITICAL " in l]
            raport["log"]["bledy_total"] = len(bledy)
            raport["log"]["ostatnie_bledy"] = [l.rstrip() for l in bledy[-3:]]
        except Exception as e:
            raport["log"]["blad_odczytu"] = str(e)

    return raport


# ════════════════════════════════════════════════════════════════════
#  SAMODZIELNY TEST
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import json

    log = inicjalizuj()
    print("=" * 60)
    print("footstats_logging.py – test modulu")
    print("=" * 60)

    # Test parsowania
    print("\n[TEST] bezpieczny_parse_prob:")
    testy = [
        ({"percent": {"home": "60%", "draw": "25%", "away": "15%"}},
         "Format A – glowny Bzzoiro"),
        ({"home_win_prob": 0.60, "draw_prob": 0.25, "away_win_prob": 0.15,
          "btts": 0.70, "over_2_5": 0.68},
         "Format B – floaty 0-1"),
        ({"home": 60, "draw": 25, "away": 15},
         "Format C – ints"),
        ({"predictions": {"percent": {"home": "55%", "draw": "25%", "away": "20%"}}},
         "Format D – zagniezdzone"),
        ({}, "Pusty slownik"),
        (None, "None"),
        ({"home": "abc", "draw": None, "away": -5}, "Bledne wartosci"),
        ({"percent": {"home": "1%", "draw": "1%", "away": "1%"}},
         "Suma < 5 (niespojne dane)"),
    ]
    for dane, opis in testy:
        wynik = bezpieczny_parse_prob(dane)
        status = "OK" if (wynik is not None) == (dane not in [None, {}]) else "--"
        print(f"  {status} {opis:40}: {wynik}")

    # Test diagnostyki
    print("\n[TEST] raport_diagnostyczny:")
    raport = raport_diagnostyczny()
    print(json.dumps(raport, ensure_ascii=False, indent=2, default=str))

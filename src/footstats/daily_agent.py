"""
FootStats Daily Agent
=====================
Codzienne uruchamianie o 8:00: Bzzoiro → forma → Groq → gotowy kupon.

Użycie:
    python -m footstats.daily_agent
    python -m footstats.daily_agent --stawka 10 --dni 2
    python -m footstats.daily_agent --tylko-kupon   # bez formy (szybciej)
    python -m footstats.daily_agent --waliduj       # + Groq walidacja kuponu A
"""

import argparse
import logging
import os
from datetime import datetime

from rich.panel import Panel

from footstats.utils.normalize import (
    PROG_DOPASOWANIA_MECZU,
    normalize_team_name,
    team_similarity,
)
from footstats.config import BTTS_TWO_WAY
from footstats.core.checkpoint import save_predictions_batch, cleanup_old_checkpoints
from footstats.core.rynki import TYP_DO_ODDS_KEY, TYPY_BTTS_NIE
from footstats.daily_agent_output import (  # noqa: F401  re-export (ścieżki + patch-targety)
    LOGS_DIR,
    _blad,
    _powiadomienie_windows,
    _sep,
    _wyswietl,
    _zapisz_txt,
    console,
    zamknij_krok,
)

log = logging.getLogger(__name__)


def _wyslij_alarm(nazwa: str, opis_skutku: str, *args, **kwargs) -> None:
    """Wysyla alarm przez `utils.telegram_notify`; NIEUDANA wysylka jest GLOSNA.

    Cztery miejsca w `main()` mialy ten sam ksztalt:

        try:
            from footstats.utils.telegram_notify import send_stop_loss_alert
            send_stop_loss_alert(dd, bankroll)
        except (ImportError, OSError, RuntimeError):
            pass

    To jest dokladnie przypadek, ktory `tests/test_ciche_except_audit.py` wymienia
    jako powod swojego istnienia: czujnik dymu meldujacy "wszystko gra", gdy sam
    sie pali. Stop-loss mogl zadzialac, a nikt sie nie dowiedzial — jedynym sladem
    bylby `console.print` w logu przebiegu, ktorego nikt nie czyta na biezaco.

    Sama awaria wysylki NIE przerywa przebiegu: alarm jest powiadomieniem, nie
    warunkiem poprawnosci.
    """
    try:
        from footstats.utils import telegram_notify
    except ImportError as e:
        log.warning("ALARM NIEWYSLANY (%s): brak telegram_notify (%s) — %s",
                    nazwa, e, opis_skutku)
        return

    wyslij = getattr(telegram_notify, nazwa, None)
    if wyslij is None:
        # Blad w KODZIE (literowka w nazwie), nie awaria srodowiska.
        log.error("ALARM NIEWYSLANY: `telegram_notify.%s` nie istnieje — %s",
                  nazwa, opis_skutku)
        return

    try:
        wyslij(*args, **kwargs)
    except (OSError, RuntimeError, ValueError) as e:
        log.warning("ALARM NIEWYSLANY (%s): %s: %s — %s",
                    nazwa, type(e).__name__, e, opis_skutku)

_norm = normalize_team_name


# ── Krok 1: Bzzoiro ───────────────────────────────────────────────────────────

def _pobierz_kandydatow(dni: int = 2) -> tuple[list, dict]:
    """
    Bzzoiro ML → (wyniki, indeks_kursow).
    indeks_kursow: klucz=(norm_gosp, norm_gosc) → {odds, gospodarz, goscie, liga}
    """
    from dotenv import load_dotenv
    load_dotenv()

    from footstats.scrapers.bzzoiro import BzzoiroClient, ENV_BZZOIRO
    from footstats.core.quick_picks import szybkie_pewniaczki_2dni
    from footstats.config import AGENT_KANDYDAT_PROG

    klucz = os.getenv(ENV_BZZOIRO, "")
    if not klucz:
        _blad("Brak BZZOIRO_API_KEY w .env")

    c = BzzoiroClient(klucz)
    ok, msg = c.waliduj()
    if not ok:
        console.print(f"[bold red]Bzzoiro: {msg}[/bold red]")

    wyniki = szybkie_pewniaczki_2dni(c, prog=AGENT_KANDYDAT_PROG, godziny=dni * 24) if ok else []
    console.print(f"[dim]Bzzoiro: {len(wyniki)} kandydatów w oknie {dni*24}h[/dim]")

    # Health-check zrodla (dlug techniczny #2): alert gdy 0 wydarzen / niedostepne.
    try:
        from footstats.utils.telegram_notify import check_and_alert_source_down
        check_and_alert_source_down("Bzzoiro", ok=ok, n_wyniki=len(wyniki))
    except (ImportError, OSError, RuntimeError) as e:
        log.warning("Health-check Bzzoiro nie powiodl sie: %s", e)

    # Buduj indeks: (norm_gosp, norm_gosc) → dane meczu
    indeks: dict = {}
    for w in wyniki:
        g = w.get("gospodarz", "")
        a = w.get("goscie", "")
        indeks[(_norm(g), _norm(a))] = {
            "odds":      w.get("odds", {}),
            "gospodarz": g,
            "goscie":    a,
            "liga":      w.get("liga", ""),
            "pred":      w.get("pred") or {},
            # Data jest potrzebna dopiero w KROKU 4b (uzgodnienie `predictions`),
            # ale musi pochodzic z tego samego meczu, co podmieniony kurs.
            "data":      w.get("data", ""),
        }

    return wyniki, indeks


# ── Krok 3b: Live odds refresh (faza final) ──────────────────────────────────

def _odswiez_kursy_live(indeks: dict, dni: int = 3) -> dict:
    """Re-fetch Bzzoiro odds and update indeks with fresh data."""
    from footstats.scrapers.bzzoiro import BzzoiroClient, ENV_BZZOIRO
    from footstats.core.quick_picks import szybkie_pewniaczki_2dni
    from footstats.config import AGENT_KANDYDAT_PROG

    klucz = os.getenv(ENV_BZZOIRO, "")
    if not klucz:
        console.print("[yellow]Brak BZZOIRO_API_KEY — pomijam odświeżenie kursów[/yellow]")
        return indeks

    try:
        c = BzzoiroClient(klucz)
        ok, msg = c.waliduj()
        if not ok:
            console.print(f"[yellow]Bzzoiro niedostępny: {msg} — używam starych kursów[/yellow]")
            return indeks

        # Bez tego krok czytal WLASNY cache i nie mogl zobaczyc zadnej zmiany:
        # `CACHE_TTL_MIN` to 30 minut, a KROK 1 i KROK 3b chodza w tym samym
        # procesie kilka-kilkanascie minut po sobie. `0/46` bylo gwarantowane
        # konstrukcja, nie obserwacja rynku. Prefiks tylko Bzzoiro — cache jest
        # wspolny, a wpisy API-Football kosztuja 1% dziennego budzetu kazdy.
        from footstats.utils.cache import uniewaznij_cache
        uniewaznij_cache("bz:")

        fresh = szybkie_pewniaczki_2dni(c, prog=AGENT_KANDYDAT_PROG, godziny=dni * 24)
        updated = dopasowanych = 0
        for w in fresh:
            g = w.get("gospodarz", "")
            a = w.get("goscie", "")
            key = (_norm(g), _norm(a))
            if key in indeks:
                dopasowanych += 1
                old_odds = indeks[key].get("odds", {})
                new_odds = w.get("odds", {})
                if new_odds and new_odds != old_odds:
                    indeks[key]["odds"] = new_odds
                    updated += 1

        console.print(f"[green]Odświeżono kursy LIVE: {updated}/{len(indeks)} meczów zaktualizowanych[/green]")

        # `0` znaczylo dotad trzy rzeczy naraz: zrodlo padlo, nazwy sie rozjechaly
        # albo kursy po prostu stoja. Ten sam ksztalt co `Final enrichment: 0/N`
        # — wartosc znaczy dwie rzeczy, a cisza czyni je nierozroznialnymi.
        if indeks and not fresh:
            log.warning(
                "Odswiezenie kursow: zrodlo oddalo ZERO meczow przy %d w indeksie "
                "— to awaria Bzzoiro, nie brak ruchu na kursach.", len(indeks))
        elif indeks and fresh and dopasowanych == 0:
            log.warning(
                "Odswiezenie kursow: zrodlo oddalo %d meczow, ale ZADEN nie trafil "
                "w indeks (%d kandydatow) — rozjazd nazw druzyn, kursy zostaja stare.",
                len(fresh), len(indeks))
        else:
            log.info("Odswiezenie kursow: %d zmienionych z %d dopasowanych "
                     "(%d w indeksie)", updated, dopasowanych, len(indeks))
    except (OSError, ValueError, KeyError) as e:
        console.print(f"[yellow]Błąd odświeżenia kursów: {e} — używam starych kursów[/yellow]")

    return indeks


# ── Krok 1b/2: enrichment (kontuzje, forma, BetBuilder, inspiracje) ─────────
# Wydzielone do core/daily_phases.py (dług techniczny #3) — re-eksport poniżej.
from footstats.core.daily_phases import (
    _apply_injury_corrections,
    _wzbogac_forme_top,
    _wzbogac_o_betbuilder,
    _wzbogac_o_inspiracje,
    _wzbogac_o_kursy_fallback,
)


# ── Krok 3: Groq AI ───────────────────────────────────────────────────────────

def _analizuj_groq(
    wyniki: list,
    cel_wygrana_a: float | None = None,
    cel_wygrana_b: float | None = None,
    stawka: float = 10.0,
) -> dict:
    from footstats.ai.analyzer import (
        ai_analiza_pewniaczki, ai_groq_dostepny, typy_awaryjne_z_modelu,
    )
    if not ai_groq_dostepny():
        # A1: brak klucza konczyl przebieg przez sys.exit(1) — razem z typami,
        # ktore model policzyl juz przed tym krokiem i ktore nie potrzebuja
        # Groqa do niczego. Degradujemy glosno zamiast przerywac.
        log.error("[Agent] Brak GROQ_API_KEY — warstwa opisowa pominieta,"
                  " typy powstaja z samego modelu.")
        console.print("[red]Brak GROQ_API_KEY — typy z samego modelu.[/red]")
        return typy_awaryjne_z_modelu(wyniki, zapisz=False)
    console.print("[dim]Groq: analizuję i buduję kupony...[/dim]")
    try:
        # A2/A3: `zapisz_predykcje=False` — zapis idzie dopiero po KROKU 4.
        return ai_analiza_pewniaczki(
            wyniki,
            pobierz_forme=False,
            cel_wygrana_a=cel_wygrana_a,
            cel_wygrana_b=cel_wygrana_b,
            stawka=stawka,
            zapisz_predykcje=False,
        )
    except (RuntimeError, OSError, ValueError) as e:
        # Brak warstwy AI degraduje przebieg, ale go NIE zabija. Kroki przed tym
        # miejscem już się wykonały i zapisały: rozliczenie wyników, analiza
        # porażek (lekcje) i kupony System paper-trading. Przerwanie wyrzucałoby
        # to do kosza i oznaczało cały dzień jako nieudany — a paliwo do nauki
        # właśnie przybyło. Zmierzone 09.08.2026: dwa przebiegi stracone przez
        # jedną odmowę Groqa (413), zero predykcji obu dni.
        #
        # GŁOŚNO, bo cicha degradacja jest gorsza od awarii: `logger.error`
        # trafia do Cloud Logging, więc monitoring to zobaczy.
        log.error("[Agent] Warstwa AI niedostepna (%s) — pomijam kupony Groq. "
                  "Rozliczenie, lekcje i kupony System sa juz zapisane.", e)
        console.print(f"[red]Groq niedostępny: {e}[/red]")
        console.print("[yellow]Przebieg degraduje do części modelowej "
                      "— kupony AI pominięte.[/yellow]")
        # A1: "degraduje do czesci modelowej" bylo dotad tylko opisem — zwracany
        # pusty slownik oznaczal ZERO zapisanych typow. Teraz czesc modelowa
        # faktycznie zostaje.
        return typy_awaryjne_z_modelu(wyniki, zapisz=False)


# ── Krok 4: Weryfikacja halucynacji ──────────────────────────────────────────

# Mapa i lista rynkow zyja w `core.rynki` — czyta je TAKZE `ai.prompts`, zeby
# enum typow w promptcie nie mogl sie rozjechac z bramka weryfikacji. Do 01.09
# schemat wyliczal 22 rynki (m.in. "Handicap +1", "Kartki Over 3.5"), z ktorych
# wyceniamy 6 — noga na pozostalych byla kasowana jako halucynacja Groqa.
_TYP_DO_ODDS_KEY = TYP_DO_ODDS_KEY
_TYPY_BTTS_NIE = TYPY_BTTS_NIE


def wykryj_anomalie_runu(n_kandydatow: int, n_po_filtrach: int, n_kuponow_system: int,
                         ma_typy: bool, system_paper: bool = False,
                         typy_po_weryfikacji: bool | None = None) -> str | None:
    """Opis cichej awarii albo None, gdy przebieg wyglada zdrowo.

    Detektor pilnowal dotad WEJSCIA (czy zrodlo cos dalo) i bocznej sciezki kuponow
    System — nie pilnowal GLOWNEGO produktu, czyli typow. 15.08 przebieg mial
    42 kandydatow i 7 po filtrach, ale JSON od Groqa nie sparsowal sie i nie powstal
    ANI JEDEN typ. Alert milczal, bo zaden z warunkow tego nie obejmowal, a job
    skonczyl sie exit=0 i wyslal Telegram — wygladalo jak dzien bez okazji.

    `n_po_filtrach == 0` to NIE awaria: filtry maja prawo wyciac komplet.
    Awaria to material po filtrach, z ktorego mimo wszystko nie powstal zaden typ.
    """
    if n_kandydatow == 0:
        return "0 kandydatów z Bzzoiro (źródło puste/niedostępne?)"
    if n_po_filtrach > 0 and not ma_typy:
        # `ma_typy` pyta o wiersze, ktore NAPRAWDE wyladowaly w `predictions`
        # (`dane["_zapisanych"]`), a nie o zawartosc `top3` po weryfikacji.
        # Stara wersja czytala `top3` PO KROKU 4, wiec dzien z zapisanymi
        # predykcjami, ktorym weryfikacja wyciela komplet typow, byl zglaszany
        # jako "ZERO predykcji zapisanych" — falszywy alarm zmierzony 23.08
        # (`footstats-final-pptp4`: 5 wierszy w bazie, alarm mowil zero).
        #
        # Od A1 awaria warstwy LLM juz tego nie wywola — typy powstaja wtedy
        # z modelu. Ten warunek zostaje jako ostatnia siatka i oznacza, ze ani
        # LLM, ani selekcja modelu, ani zapis do bazy nic nie zostawily.
        return (f"0 typów mimo {n_po_filtrach} meczów po filtrach"
                f" (LLM nic nie zwrocil I selekcja modelu nic nie wybrala:"
                f" kursy? progi? zapis do bazy?) — ZERO predykcji zapisanych")
    if ma_typy and typy_po_weryfikacji is False:
        # Predykcje SA — to nie cisza. Ale skoro weryfikacja kursow wyciela
        # wszystkie typy, dzien nie zostawil ani jednego typu do postawienia.
        # Zmierzone 23.08: Groq wytypowal trzy rynki, ktorych zrodlo nie wycenia
        # (`Over 1.5`, `Handicap +1 Gość`, `2 (wygrana gościa)`).
        return (f"{n_po_filtrach} meczów po filtrach, predykcje zapisane, ale"
                f" weryfikacja kursow wyciela KOMPLET typow"
                f" — dzien bez ani jednego użytecznego typu")
    if system_paper and n_kuponow_system == 0:
        return "0 kuponów System mimo --system-paper (kursy? filtry? pauza?)"
    return None


# FAZA 17.2: twardy filtr longshotów
_MAX_KURS_LONGSHOT = 4.0      # kurs > 4.0 ⇒ implied prob < 25% = longshot
_MIN_PROB_MODELU = 40.0       # p_modelu < 40% ⇒ odrzuć (model nie wspiera typu)


def _prob_modelu_dla_typu(typ: str, pred: dict) -> float | None:
    """Prawdopodobieństwo modelu (%) dla danego typu tipa. None jeśli brak danych."""
    if not pred:
        return None
    t = typ.strip().lower()
    if t in ("1", "1x"):
        return pred.get("p_wygrana")
    if t == "x":
        return pred.get("p_remis")
    if t in ("2", "x2"):
        return pred.get("p_przegrana")
    if t.startswith("over"):
        return pred.get("over25")
    if t.startswith("under"):
        return pred.get("under25")
    if t == "btts":
        return pred.get("btts")
    return None


def _powod_odrzucenia_longshot(typ: str, kurs: float | None, pred: dict) -> str | None:
    """Zwraca powód odrzucenia nogi (longshot) lub None jeśli noga OK."""
    if kurs is not None and kurs > _MAX_KURS_LONGSHOT:
        return f"kurs {kurs:.2f} > {_MAX_KURS_LONGSHOT} (longshot)"
    p_mod = _prob_modelu_dla_typu(typ, pred)
    if p_mod is not None and p_mod < _MIN_PROB_MODELU:
        return f"p_modelu {p_mod:.0f}% < {_MIN_PROB_MODELU:.0f}%"
    return None


def _znajdz_mecz(mecz_str: str, indeks: dict) -> dict | None:
    """
    Próbuje dopasować string 'Drużyna A vs Drużyna B' do indeksu Bzzoiro.
    Zwraca wpis indeksu lub None jeśli brak dopasowania.
    """
    parts = mecz_str.lower().replace(" - ", " vs ").split(" vs ")
    if len(parts) != 2:
        return None
    ng, na = _norm(parts[0].strip()), _norm(parts[1].strip())

    # 1. Dokładne dopasowanie
    if (ng, na) in indeks:
        return indeks[(ng, na)]

    # 2. Dopasowanie luźne przez `team_similarity`, NIE po podciągu.
    #
    # Podciąg uznawał rezerwy za pierwszy zespół ("Legia" łapała "Legia II"),
    # a stąd `_weryfikuj_noge` bierze RZECZYWISTY KURS podmieniany w nodze
    # (anty-halucynacja Groq). Noga dostawała wtedy kurs z cudzego meczu
    # i przechodziła weryfikację jako poprawna.
    #
    # Bierzemy NAJLEPSZE dopasowanie, nie pierwsze napotkane — kolejność
    # indeksu to kolejność odpowiedzi Bzzoiro, nie ranking trafności.
    najlepszy, najlepszy_wynik = None, 0.0
    for (ig, ia), dane in indeks.items():
        wynik = min(team_similarity(ng, ig), team_similarity(na, ia))
        if wynik >= PROG_DOPASOWANIA_MECZU and wynik > najlepszy_wynik:
            najlepszy, najlepszy_wynik = dane, wynik

    return najlepszy


def _weryfikuj_noge(z: dict, indeks: dict, usuniete: list[str]) -> dict | None:
    """
    Weryfikuje pojedynczą nogę (top3 row lub zdarzenie kuponu):
    - mecz musi istnieć w Bzzoiro i mieć realny kurs dla typu (inaczej usuń)
    - podmienia kurs na rzeczywisty Bzzoiro/BetExplorer (anty-halucynacja Groq)
    - twardy filtr longshotów (17.2)
    Zwraca zmodyfikowaną nogę lub None jeśli odrzucona (dopisuje powód do `usuniete`).
    """
    mecz_str = z.get("mecz", "")
    typ_raw  = z.get("typ", "").strip()
    wpis     = _znajdz_mecz(mecz_str, indeks)

    if wpis is None:
        usuniete.append(f"{mecz_str} [{typ_raw}] — brak w Bzzoiro")
        return None

    typ_norm    = typ_raw.lower()
    odds_key    = _TYP_DO_ODDS_KEY.get(typ_norm)

    # Strona NIE zostaje policzona i zalogowana, ale nie gra — dowody z 15.08 mowia,
    # ze do zera potrzebuje kursu 2.10, a rynek daje ~1.6. Flip flagi po walidacji.
    if typ_norm in _TYPY_BTTS_NIE and not BTTS_TWO_WAY:
        usuniete.append(f"{mecz_str} [{typ_raw}] — BTTS dwustronne wylaczone (BTTS_TWO_WAY=0)")
        return None

    rzeczywisty = (wpis["odds"] or {}).get(odds_key) if odds_key else None
    if not rzeczywisty:
        if odds_key:
            # Rynek znamy, tylko zrodlo go nie wycenia. To brak danych, nie zmyslony
            # typ — mieszanie tych przypadkow ukrywalo, ze czegos po prostu nie mamy.
            usuniete.append(f"{mecz_str} [{typ_raw}] — zrodlo nie podaje kursu"
                            f" dla rynku '{odds_key}'")
        else:
            usuniete.append(f"{mecz_str} [{typ_raw}] — brak realnego kursu w Bzzoiro"
                            f" (kurs Groq niezweryfikowany)")
        return None

    z["kurs"]      = float(rzeczywisty)
    z["mecz"]      = f"{wpis['gospodarz']} vs {wpis['goscie']}"
    z["_verified"] = True
    z["_data"]     = wpis.get("data", "")

    # 11.6: Arbitraż — porównaj z BetExplorer cache (bez Playwright)
    try:
        from footstats.scrapers.kursy import najlepszy_kurs_z_cache
        be = najlepszy_kurs_z_cache(wpis["gospodarz"], wpis["goscie"])
        if be:
            _be_map = {"odds_1": be.get("k1"), "odds_x": be.get("kX"), "odds_2": be.get("k2")}
            be_kurs = _be_map.get(odds_key)
            if be_kurs and be_kurs > z["kurs"]:
                z["kurs"]   = float(be_kurs)
                z["_zrodlo"] = "betexplorer"
    except (ImportError, AttributeError, TypeError) as e:
        log.warning("Arbitraz BetExplorer niedostepny dla %s-%s (%s: %s) —"
                    " noga zostaje przy kursie z pierwszego zrodla, nie z najlepszego",
                    wpis.get("gospodarz"), wpis.get("goscie"), type(e).__name__, e)

    # FAZA 17.2: twardy filtr longshotów (na finalnym kursie + pred Poissona)
    powod = _powod_odrzucenia_longshot(typ_raw, z.get("kurs"), wpis.get("pred") or {})
    if powod:
        usuniete.append(f"{mecz_str} [{typ_raw}] — {powod}")
        return None

    return z


def _weryfikuj_kupony(dane: dict, indeks: dict) -> dict:
    """
    Weryfikuje top3 + każdą nogę w kupon_a..d przez Bzzoiro (anty-halucynacja Groq):
    - podmienia kurs na rzeczywisty lub usuwa nogę bez realnego kursu
    - twardy filtr longshotów (17.2)
    Zwraca zmodyfikowany słownik dane.
    """
    usuniete: list[str] = []

    # FAZA 17.3: top3 też weryfikowane (wcześniej halucynacje wchodziły do predictions)
    top3 = dane.get("top3") or []
    if top3:
        zweryfikowane_top3 = [
            z for z in (_weryfikuj_noge(row, indeks, usuniete) for row in top3) if z is not None
        ]
        dane["top3"] = zweryfikowane_top3

    for kupon_key in ("kupon_a", "kupon_b", "kupon_c", "kupon_d"):
        # `or {}` — klucz bywa obecny z wartością None (dzień bez kuponu),
        # co obchodzi default .get() (crash final-9hkn2 na prod, 09.07).
        kupon = dane.get(kupon_key) or {}
        zdarzenia = kupon.get("zdarzenia", [])
        if not zdarzenia:
            continue

        zweryfikowane = [
            z for z in (_weryfikuj_noge(z, indeks, usuniete) for z in zdarzenia) if z is not None
        ]

        # Przenumeruj
        for i, z in enumerate(zweryfikowane, 1):
            z["nr"] = i

        # Przelicz kurs łączny i wygraną
        if zweryfikowane:
            kurs_l = 1.0
            for z in zweryfikowane:
                kurs_l *= z.get("kurs", 1.0)
            kupon["zdarzenia"]   = zweryfikowane
            kupon["kurs_laczny"] = round(kurs_l, 2)
        else:
            dane[kupon_key] = {}

    # Strukturalny slad, nie tylko tekst w `ostrzezenia`: `_zgloś_brak_kuponu_do_zapisu`
    # musi odroznic "LLM nie oddal kuponu" od "kupon byl, weryfikacja go oproznila".
    # 01.09 oba stany dostawaly ten sam komunikat i wskazywaly na zla warstwe.
    dane["_usuniete_nogi"] = list(usuniete)

    if usuniete:
        ostrzegawcze = dane.get("ostrzezenia", "") or ""
        dane["ostrzezenia"] = ostrzegawcze + "\n⚠️  USUNIĘTE HALUCYNACJE: " + " | ".join(usuniete)
        console.print(f"[red]Usunięto {len(usuniete)} halucynowanych nóg:[/red]")
        for u in usuniete:
            console.print(f"  [dim]- {u}[/dim]")

    return dane


# tip → postac zapisana w `predictions` (musi zgadzac sie z `_TYP_NORM`
# w `analyzer_helpers._auto_zapisz_backtest`, inaczej uzgodnienie nic nie trafi).
_TYP_NORM_ZAPIS = {"Over": "Over 2.5", "Under": "Under 2.5",
                   "OVER": "Over 2.5", "UNDER": "Under 2.5"}


def _zbierz_ocalale_nogi(dane: dict) -> list[dict]:
    """Nogi, ktore przezyly weryfikacje — w postaci gotowej do uzgodnienia z baza.

    Ta sama noga bywa i w `top3`, i w kuponie, wiec deduplikujemy po kluczu
    zapisu; bez tego licznik uzgodnionych wierszy bylby zawyzony i przestalby
    wykrywac rozjazd nazw.
    """
    zrodla = list(dane.get("top3") or [])
    for kupon_key in ("kupon_a", "kupon_b", "kupon_c", "kupon_d"):
        zrodla.extend((dane.get(kupon_key) or {}).get("zdarzenia") or [])

    zebrane: dict[tuple, dict] = {}
    for z in zrodla:
        mecz = z.get("mecz") or ""
        if " vs " not in mecz:
            continue
        home, away = (czesc.strip() for czesc in mecz.split(" vs ", 1))
        typ_raw = (z.get("typ") or "").strip()
        typ = _TYP_NORM_ZAPIS.get(typ_raw, typ_raw)
        klucz = (home, away, z.get("_data") or "", typ)
        zebrane[klucz] = {
            "team_home": home, "team_away": away,
            "match_date": z.get("_data") or "", "ai_tip": typ,
            "odds": z.get("kurs"),
        }
    return list(zebrane.values())


def _zapisz_predykcje_po_weryfikacji(dane: dict, wyniki: list, indeks: dict) -> int:
    """KROK 4a — dopiero TERAZ typy trafiaja do `predictions`. Zwraca liczbe wierszy.

    Zapis szedl wczesniej w KROKU 3, czyli PRZED podmiana kursu na rzeczywisty
    i przed odsiewem nog bez pokrycia. Kosztowalo to dwie rzeczy naraz (zmierzone
    na produkcji 23.08, `footstats-final-pptp4`):

      * noga wycieta na weryfikacji zostawala w bazie z kursem od modelu
        jezykowego (`odds_verified=0`) — uzgodnienie poprawia tylko ocalale;
      * slownictwo LLM-a ladowalo nietkniete: `2 (wygrana gościa)` to zwykla "2"
        z dopiskiem, ale `oblicz_tip_correct` zwraca dla niej None, wiec taki
        wiersz jest martwy od chwili zapisu.

    Weryfikacja jest przy okazji bramka slownikowa — przepuszcza wylacznie rynki
    z `_TYP_DO_ODDS_KEY`, czyli te, ktore zrodlo wycenia i ktore rozliczenie umie
    policzyc. Zapis po niej dostaje wiec tylko typy realne i rozliczalne.

    DRUGA SZANSA DLA MODELU (A1): skoro typy LLM-a moga wyparowac dopiero tutaj,
    model musi miec okazje wejsc PO weryfikacji. Bez tego dzien, w ktorym LLM
    wytypowal same rynki bez kursu, konczylby sie zerem predykcji mimo gotowych
    liczb modelu. Typy z modelu przechodza te sama bramke — nie sa z niej zwolnione.
    """
    from footstats.ai.analyzer import _dopisz_typy_z_modelu
    from footstats.ai.analyzer_helpers import _auto_zapisz_backtest

    if not dane.get("top3") and _dopisz_typy_z_modelu(dane, wyniki):
        usuniete: list[str] = []
        dane["top3"] = [
            z for z in (_weryfikuj_noge(row, indeks, usuniete) for row in dane["top3"])
            if z is not None
        ]
        if usuniete:
            log.warning("Typy z modelu tez nie przeszly weryfikacji: %s",
                        " | ".join(usuniete))

    _auto_zapisz_backtest(dane, wyniki)
    n = dane.get("_zapisanych", 0)
    nowych = dane.get("_nowych", n)
    if n:
        # Obie liczby, bo "typ ma pokrycie w bazie" i "wiersz naprawde przybyl"
        # to dwa rozne stany. `save_prediction` deduplikuje po (mecz, data, tip),
        # wiec powtorzony przebieg tego samego dnia daje n>0 i nowych=0 — i to
        # jest POPRAWNE. Do 01.09 log pokazywal samo `n` i mowil "Zapisano 4"
        # w przebiegu, po ktorym baza nie urosla (`footstats-final-66gjs`).
        log.info("Zapisano %d predykcji PO weryfikacji kursow (%d nowych, %d juz bylo)",
                 n, nowych, n - nowych)
    else:
        log.error("Zaden typ nie przezyl weryfikacji — ZERO predykcji zapisanych")
    return n


def _uzgodnij_predykcje(dane: dict) -> int:
    """KROK 4b — stawia znacznik `odds_verified` na zapisanych nogach. Zwraca liczbe wierszy.

    HISTORIA, bo rola tego kroku sie zmienila. Zapis predykcji dzial sie w KROKU 3
    (wewnatrz analizy Groqa), czyli ZANIM kurs zostal podmieniony na rzeczywisty —
    i wtedy ten krok BYL naprawa: dosylal do bazy kurs ze zrodla. Bez niego
    `predictions` opisywalo propozycje modelu jezykowego, wlacznie z kursem 52.58
    powtorzonym na trzech roznych meczach.

    Od 23.08 (A2/A3) zapis idzie dopiero PO weryfikacji, wiec kurs w bazie jest
    juz poprawny w chwili wstawienia. Ten krok zostaje jako domkniecie: oznacza
    wiersze jako zweryfikowane i nadal pilnuje rozjazdu nazw miedzy zapisem
    a weryfikacja (liczba mniejsza od dlugosci `nogi` = cos sie nie zeszlo).
    """
    nogi = _zbierz_ocalale_nogi(dane)
    if not nogi:
        return 0
    try:
        from footstats.core.backtest import oznacz_zweryfikowane
        uzgodnione = oznacz_zweryfikowane(nogi)
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        log.warning("Uzgodnienie predykcji po weryfikacji nie powiodlo sie: %s", e)
        return 0

    if uzgodnione < len(nogi):
        # Nie polykamy tego: mniej trafien niz nog = rozjazd nazw miedzy zapisem
        # a weryfikacja, czyli czesc wierszy zostaje z kursem od Groqa.
        log.warning("Uzgodniono kursy dla %d z %d zweryfikowanych nog —"
                    " reszta zostaje niezweryfikowana w `predictions`",
                    uzgodnione, len(nogi))
    else:
        log.info("Uzgodniono kursy dla %d zweryfikowanych nog", uzgodnione)
    return uzgodnione


# ── Krok 1b: API-Football Ekstraklasa ───────────────────────────────────────

def _pobierz_apifootball_ekstraklasa(dni: int = 3) -> list[dict]:
    """Dociąga kandydatów z Ekstraklasy przez API-Football (jeśli klucz dostępny)."""
    from dotenv import load_dotenv
    load_dotenv()
    from footstats.core.apisports_gate import klucz as _klucz_af

    klucz = _klucz_af()
    if not klucz:
        return []
    try:
        from footstats.scrapers.api_football import APIFootball
        af = APIFootball(klucz)
        return af.kandydaci_liga(api_id=106, godziny=dni * 24, prog_pw=0.50)
    except (OSError, ValueError, KeyError) as e:
        console.print(f"[dim]API-Football Ekstraklasa: {e}[/dim]")
        return []


# ── Krok 4b/6: Kelly Criterion + walidacja Groq (core/daily_phases.py) ─────
from footstats.core.daily_phases import _dodaj_kelly, _waliduj_kupon_groq


# ── CLI ───────────────────────────────────────────────────────────────────────

# ── Ensemble + faza final + decision score helpers (core/daily_phases.py) ──
from footstats.core.daily_phases import (
    _apply_national_lambda,
    _oblicz_roznica_modeli,
    _enrichuj_finalna_faza,
    _zapisz_next_final_txt,
)


# ── Nowe: fazy i decision score ────────────────────────────────────────────

from footstats.core.daily_filters import (
    _pre_filtruj_kursy, _pre_filtruj_tokenow,
    _pre_filtruj_value_bet, _pre_filtruj_ligi,
)
from footstats.daily_agent_decision import (  # noqa: F401  re-export (testy + ścieżki)
    _decision_score_kandydat,
    _filtruj_przez_decision_score,
    _ocen_zdarzenia_decision_score,
)

from footstats.core.daily_io import _zapisz_kupon_do_db

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="FootStats Daily Agent")
    p.add_argument("--stawka",      type=float, default=10.0, help="Stawka kupon A (PLN, domyslnie 10)")
    p.add_argument("--stawka-b",    type=float, default=5.0,  help="Stawka kupon B (PLN, domyslnie 5)")
    p.add_argument("--dni",         type=int,   default=3,    help="Horyzont w dniach (domyslnie 3)")
    p.add_argument("--tylko-kupon", action="store_true",      help="Pomiń formę SofaScore")
    p.add_argument("--waliduj",     action="store_true",      help="Uruchom walidację Groq kuponu A")
    p.add_argument("--cel-a",       type=float, default=None, help="Cel wygranej netto kupon A (PLN)")
    p.add_argument("--cel-b",       type=float, default=None, help="Cel wygranej netto kupon B (PLN)")
    p.add_argument("--faza",        choices=["draft", "final"], default=None,
                   help="Faza: draft (08:00, bez skladow) lub final (1h przed meczem, ze skladami)")
    p.add_argument("--date",        default=None,
                   help="Data YYYY-MM-DD (domyslnie: dzis) — etykieta logów i update_pending")
    p.add_argument("--dry-run",     action="store_true",
                   help="Tryb podgladu: nie zapisuje do DB, TXT, nie wysyla Telegram/Windows")
    p.add_argument("--system-paper", action="store_true",
                   help="Twórz single-leg kupony na koncie System (paper-trading, per-tip ROI)")
    p.add_argument("--bb",          action="store_true",
                   help="Pobierz realne kursy BetBuilder z Superbet API + sygnaly Strefy Inspiracji (wolno, ~3-5min)")
    return p


# ── Main ──────────────────────────────────────────────────────────────────────

def _bankroll_do_przebiegu(args, admin_uid: int) -> float:
    """
    Saldo do stawek Kelly'ego. W dry-run z configu, BEZ dotykania bazy.

    `--dry-run` obiecuje "nie zapisuje do DB", ale `get_current_bankroll` woła
    `init_bankroll_tables`, które przy braku wiersza robi INSERT do
    `bankroll_state` — i dzieje się to PRZED każdą bramką `if not args.dry_run`.
    Podgląd miał więc ścieżkę zapisu do produkcji, uruchamianą zanim
    którykolwiek warunek dry-run zdążył cokolwiek zablokować.

    Skutek praktyczny był taki, że całego potoku nie dało się sprawdzić bez
    dotykania prod DB, więc każda zmiana w fazie final była weryfikowalna
    dopiero na żywym przebiegu o 11:00 UTC.
    """
    from footstats.config import AGENT_BANKROLL
    from footstats.core.bankroll import get_current_bankroll

    if getattr(args, "dry_run", False):
        log.info("dry-run: bankroll z configu (%.2f PLN) zamiast salda z bazy "
                 "— stawki Kelly'ego sa podgladem, nie realnymi kwotami",
                 float(AGENT_BANKROLL))
        return float(AGENT_BANKROLL)

    return get_current_bankroll(user_id=admin_uid)


def _odswiez_sedziow(args) -> None:
    """
    Krok 0d: statystyki sędziów z ZawodTyper. W dry-run pomijane.

    `fetch_referees_zawodtyper` woła `upsert_referee`, czyli INSERT/UPDATE do
    bazy — i robiło to także w podglądzie, poza jakąkolwiek bramką dry-run.
    Trzeci przypadek tej samej klasy co saldo bankrolla.

    Dodatkowo chodzi przez Playwrighta, więc podgląd płacił za scraping, którego
    wynik i tak nie miał gdzie trafić.
    """
    if getattr(args, "dry_run", False):
        log.info("dry-run: pomijam odswiezenie sedziow (ZawodTyper pisze do bazy)")
        return

    try:
        from footstats.scrapers.zawodtyper_referees import fetch_referees_zawodtyper
        fetch_referees_zawodtyper()
        console.print("[green]✓ Sędziowie zaktualizowani z Zawodtyper[/green]")
    except (OSError, RuntimeError) as e:
        console.print(f"[dim]Referee update: {e}[/dim]")


def _streak_do_przebiegu(args, admin_uid: int) -> tuple[int, float]:
    """
    Seria porażek i mnożnik stawki. W dry-run neutralne, bez pytania bazy.

    To odczyty (SELECT), więc produkcji nie zagrażały — ale wymuszały
    połączenie z bazą, przez co całego potoku nie dało się sprawdzić inaczej
    niż na produkcji. Wartości są NEUTRALNE, nie wymyślone: 0 porażek jest
    poniżej progu 3, a mnożnik 1.0 nie rusza stawek, więc podgląd pokazuje
    stawki dokładnie takie, jak je podano.
    """
    from footstats.core.bankroll import get_loss_streak, get_stake_multiplier

    if getattr(args, "dry_run", False):
        return 0, 1.0

    return get_loss_streak(user_id=admin_uid), get_stake_multiplier(user_id=admin_uid)


def _zbierz_migawke_kursow(dry_run: bool = False) -> dict | None:
    """Pilot rozrzutu kursow — delegacja do `core.odds_store.zbierz_i_zapisz`.

    Cala obsluga bledow siedzi TAM, nie tutaj: audyt trzyma ten plik na zerze
    szerokich handlerow, a pilot potrzebuje wlasnie takiego (nie ma prawa
    wywrocic potoku). Ten sam zabieg co przy Superbet BB, przeniesionym
    z tego pliku do `core/daily_phases.py`.
    """
    from footstats.core.odds_store import zbierz_i_zapisz
    return zbierz_i_zapisz(dry_run=dry_run)

def _zgloś_brak_kuponu_do_zapisu(faza: str, dane: dict | None) -> None:
    """
    Mówi, DLACZEGO przebieg nie zapisał kuponu. Nigdy nie przerywa przebiegu.

    Do 30.08 zapis stał za gołym `if zdarzenia_db:` bez gałęzi else. Kupony
    `phase='final'` w bazie kończą się na 15.08 — czternaście dni ciszy, ani
    jednej linii o przyczynie. Odrzucenie przez próg i podniesienie kuponu były
    logowane; jedyny nielogowany przypadek okazał się tym, który realnie zachodzi.

    Dwa stany mają różne przyczyny i różne działania naprawcze, więc dostają
    różne komunikaty:

      typy są, kuponu nie ma  — warstwa LLM nie oddała struktury kuponu.
                                Typy i tak trafiają do `predictions` przez
                                fallback A1 (`typy_awaryjne_z_modelu`), więc
                                z zewnątrz wygląda to na zdrowy przebieg.
                                Tak jest CODZIENNIE od 16.08.
      zero typów              — nic nie przeszło filtrów wartości. Stan znany
                                i normalny przy pustym terminarzu.
    """
    typy = ((dane or {}).get("top3") or []) if isinstance(dane, dict) else []
    usuniete = ((dane or {}).get("_usuniete_nogi") or []) if isinstance(dane, dict) else []
    if typy and usuniete:
        # Trzeci stan, dodany 01.09. LLM oddal nogi, skasowala je NASZA bramka
        # slownikowa (`TYP_DO_ODDS_KEY`). Naprawa jest po stronie promptu —
        # ma nie podsuwac rynkow bez wyceny — a nie po stronie parsera.
        log.warning(
            "Faza %s: %d typow powstalo, ale kupon NIE zostal zapisany — "
            "weryfikacja kursow skasowala WSZYSTKIE nogi kuponu (%d): %s. "
            "To rynki spoza mapy wyceny, wiec wina jest po stronie promptu, "
            "nie parsera.", faza, len(typy), len(usuniete), " | ".join(usuniete[:5]))
    elif typy:
        log.warning(
            "Faza %s: %d typow powstalo i trafi do `predictions`, ale kupon NIE "
            "zostal zapisany — warstwa LLM nie oddala struktury kuponu "
            "(kupon_a.zdarzenia puste). Przebieg konczy sie sukcesem, wiec bez "
            "tego logu brak kuponow jest niewidoczny.", faza, len(typy))
    else:
        log.warning(
            "Faza %s: zaden kandydat nie przeszedl filtrow wartosci — brak typow "
            "i brak kuponu. Stan normalny przy pustym terminarzu, ale ma zostawic "
            "slad, zeby dalo sie odroznic od awarii.", faza)


def main():
    from dotenv import load_dotenv
    load_dotenv()

    # Logi JSON — job leci w Cloud Run Jobs, gdzie plaski tekst nie da sie
    # filtrowac po poziomie ani loggerze. Ten sam formatter co API.
    from footstats.core.logging_config import skonfiguruj_logi_json
    skonfiguruj_logi_json()

    args = _build_parser().parse_args()

    # Pilot rozrzutu kursow — PRZED sprawdzeniami stop-loss, bo zbieranie kwot
    # nie ma zwiazku z obstawianiem i ma sie odbyc takze wtedy, gdy agent jest
    # zapauzowany. Nie moze wywrocic potoku (patrz _zbierz_migawke_kursow).
    if args.faza == "final":
        _zbierz_migawke_kursow(dry_run=bool(args.dry_run))

    from footstats.core.bankroll import (
        check_daily_stop_loss, check_weekly_alert,
        is_agent_paused, check_and_auto_pause, get_weekly_drawdown,
    )
    from footstats.utils.admin_user import resolve_admin_user_id

    admin_uid = resolve_admin_user_id()
    current_bankroll = _bankroll_do_przebiegu(args, admin_uid)
    date_label = args.date or datetime.now().strftime("%Y-%m-%d")
    dry_tag    = "  [yellow]⚠ DRY-RUN[/yellow]" if args.dry_run else ""

    # 15.1: Pause check (weekly stop-loss)
    if not args.dry_run and is_agent_paused():
        console.print("[bold red]⛔ AGENT ZAPAUZOWANY (stop-loss 20% tygodniowy). Wznów przez dashboard.[/bold red]")
        _wyslij_alarm(
            "send_alert",
            "agent jest ZAPAUZOWANY przez stop-loss, a powiadomienie nie doszlo",
            "FootStats PAUSED",
            "Agent zapauzowany (stop-loss). Wznów przez dashboard → Bankroll.",
        )
        return

    # Daily stop-loss check
    if not args.dry_run and check_daily_stop_loss(user_id=admin_uid):
        console.print("[bold red]STOP-LOSS: dzienna strata >= 10% bankrolla — przerywam.[/bold red]")
        return

    # Streak detection
    streak, stake_mult = _streak_do_przebiegu(args, admin_uid)
    if streak >= 3:
        console.print(f"[yellow]STREAK: {streak} przegranych z rzędu → stawki x{stake_mult:.0%}[/yellow]")
        args.stawka = round(args.stawka * stake_mult, 1)
        args.stawka_b = round(args.stawka_b * stake_mult, 1)

    # 15.1: Weekly drawdown → auto-pause jeśli >= 20%
    if not args.dry_run and check_and_auto_pause(user_id=admin_uid):
        dd = get_weekly_drawdown(user_id=admin_uid)
        console.print(f"[bold red]⛔ STOP-LOSS: tygodniowy drawdown {dd:.1%} >= 20% — PAUZUJĘ agenta![/bold red]")
        _wyslij_alarm(
            "send_stop_loss_alert",
            "agent WLASNIE sie zapauzowal, a powiadomienie nie doszlo",
            dd,
            current_bankroll,
        )
        return
    elif not args.dry_run and check_weekly_alert(user_id=admin_uid):
        console.print("[bold yellow]ALERT: tygodniowy drawdown przekroczył 20% bankrolla![/bold yellow]")

    # Rolling accuracy alert (ciche — nie blokuje agenta)
    _wyslij_alarm(
        "check_and_alert_accuracy",
        "spadek skutecznosci ponizej 35% moze przejsc niezauwazony",
        threshold_pct=35.0,
        window=20,
    )

    console.print()
    console.print(Panel(
        f"[bold]FootStats Daily Agent[/bold]  |  {date_label}{dry_tag}\n"
        f"Horyzont: {args.dni} dni  |  Stawka A: {args.stawka} PLN  |  Stawka B: {args.stawka_b} PLN  |  Bankroll: {current_bankroll} PLN",
        border_style="cyan",
    ))

    # Migracje przy starcie joba — dotad robilo je WYLACZNIE `api/main.py`, wiec
    # kolejnosc wdrozenia (najpierw API, potem joby) byla niepisanym warunkiem
    # poprawnosci. Job wdrozony pierwszy padal na brakujacej kolumnie i zabieral
    # ze soba caly dzienny przebieg, nie tylko rozliczenia. Idempotentne.
    try:
        from footstats.db.migrations import run_migrations
        run_migrations()
    except (OSError, ValueError, RuntimeError, ImportError) as e:
        log.warning("Migracje pominięte przy starcie joba: %s", e)

    # Krok 0: Auto-update wynikow pending meczow (pomijamy w dry-run)
    _sep("KROK 0 — Auto-update wynikow")
    if args.dry_run:
        console.print("[yellow]DRY-RUN: pomijam update_pending[/yellow]")
    else:
        try:
            from footstats.scrapers.results_updater import update_pending
            stats_upd = update_pending(days_back=3, dry_run=False, verbose=True)
            if stats_upd["updated"] > 0:
                console.print(f"[green]Zaktualizowano {stats_upd['updated']} wynikow w backtest.db[/green]")
        except (OSError, RuntimeError) as e:
            console.print(f"[dim]Auto-update wynikow: {e}[/dim]")

        # Krok 0b: Analiza porażek AI (Pętla Feedbacku) — uruchamiana po update wyników
        try:
            from footstats.ai.post_match_analyzer import analizuj_porazki
            stats_fb = analizuj_porazki(days_back=14, dry_run=False)
            if stats_fb["analyzed"] > 0:
                console.print(
                    f"[dim]Pętla Feedbacku: przeanalizowano {stats_fb['analyzed']} porażek[/dim]"
                )
        except (OSError, RuntimeError) as e:
            console.print(f"[dim]Analiza porażek (feedback): {e}[/dim]")

        # Krok 0c: Rozliczenie ACTIVE kuponów (Settlement)
        try:
            from footstats.core.coupon_settlement import settle_active_coupons
            stats_settle = settle_active_coupons(days_back=7, dry_run=False, verbose=True)
            if stats_settle["settled"] > 0:
                console.print(
                    f"[green]Rozliczono {stats_settle['settled']} kuponów | "
                    f"Częściowych: {stats_settle['partial']} | Błędów: {stats_settle['errors']}[/green]"
                )
        except (OSError, RuntimeError) as e:
            console.print(f"[dim]Błąd settlement kuponów: {e}[/dim]")

    # Krok 0d: Aktualizacja statystyk sędziów z Zawodtyper (raz dziennie)
    _odswiez_sedziow(args)

    _sep("KROK 1 — Bzzoiro ML")
    wyniki, indeks = _pobierz_kandydatow(dni=args.dni)
    n_raw_kandydatow = len(wyniki)

    # Checkpoint: save predictions batch for recovery
    batch_id = f"daily_{datetime.now():%Y%m%d_%H%M}"
    save_predictions_batch(wyniki, batch_id=batch_id)
    log.info(f"Checkpoint saved: {batch_id} ({len(wyniki)} predictions)")

    # Krok 1a: Propozycje dnia konta 'System' (low/medium/high, shared) — raz dziennie (faza draft)
    if args.faza == "draft" and not args.dry_run:
        try:
            from footstats.scrapers.bzzoiro import BzzoiroClient, ENV_BZZOIRO
            from footstats.core.system_coupons import generate_system_coupons

            klucz_sys = os.getenv(ENV_BZZOIRO, "")
            if klucz_sys:
                c_sys = BzzoiroClient(klucz_sys)
                ok_sys, _ = c_sys.waliduj()
                if ok_sys:
                    nowe = generate_system_coupons(c_sys.predykcje_tygodnia())
                    if nowe:
                        console.print(f"[green]✓ Konto 'System': {len(nowe)} nowych propozycji dnia (shared)[/green]")
        except (OSError, RuntimeError, ValueError) as e:
            console.print(f"[dim]Propozycje dnia 'System': {e}[/dim]")

    # Krok 1b: Dociagnij Ekstraklase z API-Football jesli dostepny
    wyniki_ekstra = _pobierz_apifootball_ekstraklasa(args.dni)
    if wyniki_ekstra:
        console.print(f"[dim]API-Football Ekstraklasa: +{len(wyniki_ekstra)} kandydatow[/dim]")
        wyniki = wyniki + wyniki_ekstra
        for w in wyniki_ekstra:
            g = w.get("gospodarz", "")
            a = w.get("goscie", "")
            indeks[(_norm(g), _norm(a))] = {
                "odds": w.get("odds", {}), "gospodarz": g, "goscie": a,
                "liga": w.get("liga", ""), "data": w.get("data", ""),
            }

    if not wyniki:
        _blad("Bzzoiro nie zwrocilo zadnych kandydatow.")

    # Kadry: Poisson λ z team_stats (mundial — model nie ma historii reprezentacji).
    # Gated: kluby bez team_stats bez zmian. Przed roznica_modeli (używa pw/pp/o25).
    _apply_national_lambda(wyniki)

    # Ensemble: oblicz roznica_modeli (Poisson vs Bzzoiro) dla każdego kandydata
    _oblicz_roznica_modeli(wyniki)

    # xG prefetch z Understat (wypełnia cache przed pętlą Poissona)
    try:
        from footstats.scrapers.understat_xg import (
            UNDERSTAT_LIGI, fetch_league_team_xg, _to_slug, _cache_get,
        )
        from datetime import datetime as _dt
        _season = _dt.now().year if _dt.now().month >= 7 else _dt.now().year - 1
        _teams = {w.get("gospodarz", "") for w in wyniki} | {w.get("goscie", "") for w in wyniki}
        _missing = [t for t in _teams if t and not _cache_get(_to_slug(t), _season)]
        if _missing:
            # Tabela ligi zapełnia cache ~20 drużyn jednym pobraniem. Understat nie
            # embeduje już danych w HTML, więc per drużyna = osobne chromium.
            console.print(f"[dim]xG prefetch: {len(_missing)} drużyn bez cache...[/dim]")
            for _liga_key in dict.fromkeys(UNDERSTAT_LIGI.values()):
                try:
                    fetch_league_team_xg(_liga_key, _season)
                except (OSError, ValueError, RuntimeError) as e:
                    log.warning("Prefetch xG dla ligi %s nieudany (%s: %s) —"
                                " druzyny tej ligi jada bez xG",
                                _liga_key, type(e).__name__, e)
                if not [t for t in _missing if not _cache_get(_to_slug(t), _season)]:
                    break
    except (ImportError, AttributeError) as e:
        log.warning("Podsystem xG (understat) niedostepny (%s: %s) —"
                    " CALY przebieg leci bez xG", type(e).__name__, e)

    # -- Dziennik kalibracyjny: zapisz KAŻDĄ ocenę modelu PRZED filtrami ──────
    #
    # Filtry niżej istnieją po to, żeby wybrać co OBSTAWIĆ, i słusznie są ostre:
    # 2026-08-05 z 46 kandydatów zostało 0 (blacklista lig 46→3, EV/Kelly 3→0).
    # Ale kalibracja modelu potrzebuje czegoś innego — wszystkich przewidywań
    # wraz z wynikami, niezależnie od opłacalności. Zapis dopiero po filtrach
    # oznaczał, że model widzi wyłącznie ~5% własnych ocen i nigdy nie dowie się,
    # czy jego prawdopodobieństwa są trafne.
    #
    # Osobna tabela `model_log` — patrz `core/kalibracja_log.py`. Zero wpływu na
    # kupony i na statystyki selekcji liczone z `predictions`.
    try:
        from footstats.core.kalibracja_log import zapisz_partie
        n_kal = zapisz_partie(wyniki, zrodlo=args.faza or "final")
        if n_kal:
            console.print(f"[dim]Dziennik kalibracyjny: zapisano {n_kal} ocen modelu[/dim]")
    except (ImportError, OSError, RuntimeError) as e:
        # Dziennik to obserwacja, nie warunek działania — nie może zabić runu.
        log.warning("Dziennik kalibracyjny pominięty: %s", e)

    # -- Pre-filtr tokenów: odrzuca mecze bez pełnej nazwy drużyny lub ligi ──
    n_przed_token = len(wyniki)
    wyniki = _pre_filtruj_tokenow(wyniki)
    if len(wyniki) < n_przed_token:
        console.print(
            f"[dim]Pre-filtr tokenów (brak nazw/ligi): "
            f"{n_przed_token} → {len(wyniki)} kandydatów[/dim]"
        )

    # -- Pre-filtr kursów: oszczędza tokeny Groq (odrzuca <1.15 i >15.0) ───────
    n_przed_filter = len(wyniki)
    wyniki = _pre_filtruj_kursy(wyniki)
    if len(wyniki) < n_przed_filter:
        console.print(
            f"[dim]Pre-filtr kursów (1.15–15.0): "
            f"{n_przed_filter} → {len(wyniki)} kandydatów[/dim]"
        )

    # -- Pre-filtr lig (blacklist): odrzuca ligi z udowodnionym brakiem edge ──
    from footstats.config import LIGA_FILTER_ENABLED
    if LIGA_FILTER_ENABLED:
        n_przed_liga = len(wyniki)
        wyniki = _pre_filtruj_ligi(wyniki)
        if len(wyniki) < n_przed_liga:
            console.print(
                f"[dim]Pre-filtr lig (blacklist): "
                f"{n_przed_liga} → {len(wyniki)} kandydatów[/dim]"
            )

    # -- Pre-filtr value bet: EV > 3% i Kelly > 1% (tylko kandydaci z kursami) ──
    n_przed_ev = len(wyniki)
    wyniki = _pre_filtruj_value_bet(wyniki)
    if len(wyniki) < n_przed_ev:
        console.print(
            f"[dim]Pre-filtr value bet (EV/Kelly): "
            f"{n_przed_ev} → {len(wyniki)} kandydatów[/dim]"
        )

    # -- Faza draft/final: enrichment składów/sędziego (Decision Score → po Groq) ──
    if args.faza:
        _sep(f"FAZA {args.faza.upper()} — Składy + Sędzia (API-Football)")
        from footstats.core.apisports_gate import klucz as _klucz_af

        _enrichuj_finalna_faza(wyniki, _klucz_af() or "")
        console.print(f"[cyan]{args.faza.capitalize()}: {len(wyniki)} kandydatów po wzbogaceniu o składy/sędziego[/cyan]")

        # Dziennik kalibracyjny poszedl WYZEJ, przed filtrami — celowo, bo ma
        # widziec wszystkie oceny modelu, nie te ~5%, ktore przetrwaly filtr
        # wartosci. Pola team-news powstaja dopiero teraz, wiec bez tego
        # dopisania zostawaly NULL-em na zawsze: 07.09.2026 produkcja miala
        # 1078 wierszy w `model_log` i ZERO z niepustym `p_over_abs`, mimo
        # dzialajacej flagi i dzialajacego zrodla.
        try:
            from footstats.core.kalibracja_log import uzupelnij_team_news
            n_tn = uzupelnij_team_news(wyniki)
            if n_tn:
                console.print(f"[dim]Dziennik kalibracyjny: team-news dla {n_tn} ocen[/dim]")
        except (ImportError, OSError, RuntimeError) as e:
            log.warning("Dziennik kalibracyjny: team-news pominiete: %s", e)

        # 11.5: Korekta BTTS/Over2.5 per sędzia (po enrichmencie)
        try:
            from footstats.scrapers.referee_db import referee_prob_adjustment
            for k in wyniki:
                sig = k.get("referee_signal")
                if sig:
                    d_over, d_btts = referee_prob_adjustment(sig)
                    if d_over or d_btts:
                        k["o25"] = max(0.0, min(100.0, (k.get("o25") or 0.0) + d_over))
                        k["bt"]  = max(0.0, min(100.0, (k.get("bt")  or 0.0) + d_btts))
        except ImportError as e:
            log.warning("Baza sedziow niedostepna (%s) — korekta o25/btts"
                        " po sedzim NIE zostala zastosowana w tym przebiegu", e)

        if args.faza == "draft":
            _zapisz_next_final_txt(wyniki)

    if not args.tylko_kupon:
        _sep("KROK 2 — Forma SofaScore")
        _wzbogac_forme_top(wyniki, top_n=12)
        _wzbogac_o_betbuilder(wyniki, pobierz_superbet=args.bb)
        if args.bb:
            _wzbogac_o_inspiracje(wyniki)
        _apply_injury_corrections(wyniki)

    # D6/D1b: fallback kursów SofaScore — uzupełnia mecze bez kursów Bzzoiro
    # (egzotyki, MŚ), żeby System paper-trading mógł je typować (wymaga kursu).
    if getattr(args, "system_paper", False) and not args.dry_run:
        _sep("KROK 2a — Fallback kursów SofaScore")
        try:
            _wzbogac_o_kursy_fallback(wyniki)
        except (OSError, ValueError, KeyError, RuntimeError) as e:
            console.print(f"[yellow]Fallback kursów SofaScore pominięty: {e}[/yellow]")

    # FAZA 19: paper-trading bota — single-leg kupony System (per-tip ROI/win rate)
    n_system_coupons = 0
    if getattr(args, "system_paper", False) and not args.dry_run:
        _sep("KROK 2b — System paper-trading (single-leg)")
        try:
            from footstats.core.system_paper import build_single_leg_coupons
            n_system_coupons = build_single_leg_coupons(wyniki)
            console.print(f"[cyan]System: utworzono {n_system_coupons} single-leg kuponów na koncie System[/cyan]")
        except (OSError, ValueError, KeyError, RuntimeError) as e:
            console.print(f"[yellow]System paper-trading pominięty: {e}[/yellow]")

    _sep("KROK 3 — Groq AI")
    dane = _analizuj_groq(wyniki, cel_wygrana_a=args.cel_a, cel_wygrana_b=args.cel_b, stawka=args.stawka)

    if args.faza == "final":
        _sep("KROK 3b — Odświeżenie kursów LIVE (faza final)")
        indeks = _odswiez_kursy_live(indeks, dni=args.dni)

    _sep("KROK 4 — Weryfikacja kursow (anty-halucynacja)")
    dane = _weryfikuj_kupony(dane, indeks)

    # Krok 4a: TERAZ zapis do `predictions` — po podmianie kursu i po odsiewie
    # nog bez pokrycia. `_uzgodnij_predykcje` zostaje jako domkniecie: stawia
    # znacznik `odds_verified` na wierszach, ktore przeszly bramke.
    if not args.dry_run:
        _zapisz_predykcje_po_weryfikacji(dane, wyniki, indeks)
        _uzgodnij_predykcje(dane)

    # Krok 4b: Dodaj Kelly do kazdej nogi
    _dodaj_kelly(dane, current_bankroll)

    # Krok 4c: Decision Score post-Groq — teraz pewnosc_pct i ev_netto są rzeczywiste
    if args.faza:
        _ocen_zdarzenia_decision_score(dane, phase=args.faza)

    _wyswietl(dane, args.stawka, args.stawka_b)

    if args.waliduj:
        _waliduj_kupon_groq(dane, args.stawka, "kupon_a")

    # -- Faza: zapisz kupon do SQLite DB (pomijamy w dry-run) ─────────────────
    cid = None
    draft_legs = []
    draft_odds = 1.0
    if args.faza and not args.dry_run:
        kupon_a_db = dane.get("kupon_a") or {}
        zdarzenia_db = kupon_a_db.get("zdarzenia") or []
        kurs_db = kupon_a_db.get("kurs_laczny", 1.0) or 1.0
        if not zdarzenia_db:
            _zgloś_brak_kuponu_do_zapisu(args.faza, dane)
        if zdarzenia_db:
            # Sprawdzenie decision_score PRZED zapisem
            avg_score = int(sum(z.get("decision_score", 0) for z in zdarzenia_db) / max(len(zdarzenia_db), 1))
            from footstats.core.decision_score import PROG_FINAL, PROG_DRAFT, PROG_DRAFT_FALLBACK
            if args.faza == "final":
                threshold = PROG_FINAL
            elif len(zdarzenia_db) < 3:
                threshold = PROG_DRAFT_FALLBACK  # mało kandydatów → łagodniejszy próg
            else:
                threshold = PROG_DRAFT

            if avg_score < threshold:
                console.print(
                    f"[red]❌ ODRZUCONO: decision_score {avg_score}/{threshold} poniżej progu "
                    f"({args.faza.upper()})[/red]"
                )
                console.print("[dim]Kupon nie został zapisany do bazy danych[/dim]")
            else:
                # LLM Scout filter (tylko faza final — oszczędność tokenów)
                if args.faza == "final":
                    from footstats.ai.analyzer import oceń_kupon, _SCOUT_VETO_THRESHOLD
                    scout_legs = [
                        {
                            "home": z.get("gospodarz", z.get("home", "?")),
                            "away": z.get("goscie", z.get("away", "?")),
                            "tip": z.get("typ", z.get("tip", "?")),
                            "odds": z.get("kurs", z.get("odds", 1.0)),
                            "prob": z.get("pewnosc_pct", z.get("pw_cal")),
                            "ev_netto": z.get("ev_netto"),
                        }
                        for z in zdarzenia_db
                    ]
                    scout_reasoning, scout_score = oceń_kupon(scout_legs)
                    console.print(
                        f"\n[bold]LLM Scout:[/bold] score={scout_score}/100\n"
                        f"[dim]{scout_reasoning[:400]}[/dim]\n"
                    )
                    if scout_score < _SCOUT_VETO_THRESHOLD:
                        console.print(
                            f"[red]❌ LLM SCOUT VETO: score {scout_score} < {_SCOUT_VETO_THRESHOLD} "
                            f"— kupon nie zapisany[/red]"
                        )
                        zdarzenia_db = []  # blokuj zapis poniżej

                if zdarzenia_db:
                    cid = _zapisz_kupon_do_db(
                        zdarzenia_db,
                        phase=args.faza,
                        groq_resp=dane.get("_raw", ""),
                        stake=args.stawka,
                        total_odds=kurs_db,
                    )
                    if cid:
                        console.print(f"[green]✅ Kupon zapisany do DB — ID: {cid} | faza: {args.faza}[/green]")
                        draft_legs = zdarzenia_db
                        draft_odds = kurs_db
    elif args.dry_run and args.faza:
        console.print("[yellow]DRY-RUN: pominięto zapis kuponu do DB[/yellow]")

    # Zapisz do TXT (pomijamy w dry-run)
    if not args.dry_run:
        sciezka_txt = _zapisz_txt(dane, args.stawka, args.stawka_b)
    else:
        console.print("[yellow]DRY-RUN: pominięto zapis TXT[/yellow]")
        sciezka_txt = None

    # Powiadomienie Windows (pomijamy w dry-run)
    kupony_info = []
    for lbl, kkey in [("A", "kupon_a"), ("B", "kupon_b"), ("C", "kupon_c"), ("D", "kupon_d")]:
        kp = dane.get(kkey, {})
        if kp.get("zdarzenia"):
            kupony_info.append(f"{lbl}: @{kp.get('kurs_laczny', 0):.2f} ({kp.get('szansa_wygranej_pct', '?')}%)")
    if not args.dry_run and sciezka_txt:
        notif_tekst = (
            " | ".join(kupony_info) + f"\n{sciezka_txt.name}"
        )
        _powiadomienie_windows("FootStats - gotowy kupon", notif_tekst)

    # Telegram (pomijamy w dry-run)
    if not args.dry_run:
        try:
            from footstats.utils.telegram_notify import (
                send_kupon, send_draft_kupon, telegram_dostepny,
            )
            if telegram_dostepny():
                if args.faza == "draft" and cid and draft_legs:
                    ok = send_draft_kupon(cid, draft_legs, draft_odds)
                else:
                    ok = send_kupon(dane, stawka_a=args.stawka, stawka_b=args.stawka_b)
                console.print(f"[dim]Telegram: {'wyslano' if ok else 'blad wysylki'}[/dim]")
        except (OSError, RuntimeError) as e:
            console.print(f"[dim]Telegram niedostepny: {e}[/dim]")
    else:
        console.print("[yellow]DRY-RUN: pominięto Telegram[/yellow]")

    # Cleanup old checkpoints (>7 days)
    cleanup_old_checkpoints(days=7)

    # Obserwowalność (06-21): podsumowanie runu do logu + ALERT gdy "cicha awaria"
    # (run się wykonał ale nic nie zrobił — np. pauza, 0 kandydatów, 0 kuponów).
    # Bez tego pauza stop-loss blokowała pipeline 5 dni niezauważona (exit 0, brak logów).
    zamknij_krok()          # ostatni KROK bez tego nie zameldowalby czasu trwania
    faza_label = args.faza or "(no-faza)"
    podsumowanie = (f"daily_agent {faza_label}: kandydaci={n_raw_kandydatow}, "
                    f"po filtrach={len(wyniki)}, System kupony={n_system_coupons}")
    log.info("RUN SUMMARY — %s", podsumowanie)
    console.print(f"[dim]{podsumowanie}[/dim]")
    if not args.dry_run:
        anomalia = wykryj_anomalie_runu(
            n_raw_kandydatow, len(wyniki), n_system_coupons,
            ma_typy=bool((dane or {}).get("_zapisanych")),
            system_paper=getattr(args, "system_paper", False),
            typy_po_weryfikacji=bool((dane or {}).get("top3")),
        )
        if anomalia:
            log.warning("ALERT cicha awaria: %s | %s", anomalia, podsumowanie)
            _wyslij_alarm(
                "send_alert",
                "wykryto przebieg BEZ EFEKTU, a powiadomienie nie doszlo",
                "FootStats — run bez efektu",
                f"{faza_label}: {anomalia}\n{podsumowanie}",
            )

    console.print()
    console.print("[bold green]Gotowe.[/bold green] Powodzenia!\n")




if __name__ == "__main__":
    main()

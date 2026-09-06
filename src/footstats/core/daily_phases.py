"""
daily_phases.py – Spójne fazy wzbogacania/scoringu wydzielone z daily_agent.py.

Czyste-ish helpery operujące na liście kandydatów ('wyniki') lub słowniku
'dane' (kupony) — bez zależności od stanu lokalnego main(). Wydzielone w ramach
redukcji god-module daily_agent.py (dług techniczny #3), behavior-preserving.
"""

import logging
import os
from pathlib import Path

from rich.console import Console

from footstats.scrapers.api_football import fetch_odds_af
from footstats.utils.normalize import (
    PROG_DOPASOWANIA_MECZU,
    normalize_team_name,
    team_similarity,
)

log = logging.getLogger(__name__)
console = Console()

_norm = normalize_team_name


# ── Krok 1b: Injury Lambda Correction ──────────────────────────────────────

def _current_season() -> int:
    """Sezon piłkarski: rok bieżący gdy >czerwiec, inaczej poprzedni (jak API-Football)."""
    from datetime import datetime
    now = datetime.now()
    return now.year if now.month > 6 else now.year - 1


def _goal_shares_for(team: str, side: str | None = None) -> dict[str, float]:
    """
    Udziały w golach graczy drużyny z player_db (Kontuzje v2). Bezpieczny fallback:
    dowolny błąd / brak danych → {} (injury model użyje flat kary). side: tylko log.
    """
    try:
        from footstats.core.player_db import team_goal_shares_recent
        return team_goal_shares_recent(team, _current_season(), lookback=2)
    except (ImportError, AttributeError, TypeError, KeyError, ValueError) as e:
        # reference data nie może wywalić pipeline (team_goal_shares łapie sqlite3.Error sam)
        log.debug("goal_shares fallback (%s): %s", team, e)
        return {}


def _apply_injury_corrections(wyniki: list) -> None:
    """
    Koryguje λ i PRAWDOPODOBIEŃSTWA kandydata za kontuzje (dwustronnie):
      brak napastnika/pomocnika → mniej strzela DANA drużyna (OWN λ ↓)
      brak obrońcy/bramkarza    → więcej strzela RYWAL (λ rywala ↑)
    Przelicza pw/pr/pp/bt/o25 z macierzy Poissona dla skorygowanych λ — żeby
    kontuzje realnie wpływały na typy (1X2/O-U/BTTS), nie tylko bet_builder.
    """
    from footstats.core.lambda_optimizer import injury_lambda_factors
    from footstats.core.bet_builder import estimate_lambdas_from_probs, probability_matrix

    for w in wyniki:
        try:
            inj_h = w.get("injuries_home") or []
            inj_a = w.get("injuries_away") or []
            if not inj_h and not inj_a:
                continue

            gs_h = _goal_shares_for(w.get("gospodarz") or "", "home") or None
            gs_a = _goal_shares_for(w.get("goscie") or "", "away") or None
            h_atak, h_leak = injury_lambda_factors(inj_h, goal_shares=gs_h)
            a_atak, a_leak = injury_lambda_factors(inj_a, goal_shares=gs_a)
            if (h_atak, h_leak, a_atak, a_leak) == (1.0, 1.0, 1.0, 1.0):
                continue

            # λ wyjściowe: z lambda_h/a (bet_builder) lub estymowane z pw/pp/o25
            lh = w.get("lambda_h")
            la = w.get("lambda_a")
            if not lh or not la:
                lh, la = estimate_lambdas_from_probs(
                    (w.get("pw") or 0) / 100.0, (w.get("pp") or 0) / 100.0, (w.get("o25") or 0) / 100.0
                )
            # gospodarz strzela: własny atak ↓ + dziura w obronie gościa ↑
            lh_adj = round(lh * h_atak * a_leak, 4)
            la_adj = round(la * a_atak * h_leak, 4)
            w["lambda_h"], w["lambda_a"] = lh_adj, la_adj

            # Przelicz prawdopodobieństwa z macierzy (procenty, jak w kandydacie)
            mat = probability_matrix(lh_adj, la_adj)
            n = len(mat)
            pw = sum(mat[h][a] for h in range(n) for a in range(len(mat[h])) if h > a)
            pr = sum(mat[h][a] for h in range(n) for a in range(len(mat[h])) if h == a)
            pp = sum(mat[h][a] for h in range(n) for a in range(len(mat[h])) if a > h)
            o25 = sum(mat[h][a] for h in range(n) for a in range(len(mat[h])) if h + a > 2.5)
            bt = sum(mat[h][a] for h in range(1, n) for a in range(1, len(mat[h])))
            w["pw"], w["pr"], w["pp"] = round(pw * 100, 1), round(pr * 100, 1), round(pp * 100, 1)
            w["o25"], w["bt"] = round(o25 * 100, 1), round(bt * 100, 1)
            log.debug(
                "%s vs %s: kontuzje λ %.2f→%.2f / %.2f→%.2f",
                w.get("gospodarz"), w.get("goscie"), lh, lh_adj, la, la_adj,
            )
        except (AttributeError, TypeError, KeyError, ValueError) as e:
            log.debug(f"Injury correction error: {e}")


# ── Krok 1c: Poisson λ dla reprezentacji (kadry) ──────────────────────────────

_NATIONAL_BLEND = 0.6   # waga Poissona kadr vs Bzzoiro-ML (Bzzoiro-ML słaby na kadrach)
_HOST_BOOST = 1.0       # NEUTRAL: host-boost 2× przeszacował gospodarzy (Mexico 2× LOST),
                        # boiska WC efektywnie neutralne. Reaktywacja gdy dane pokażą edge.
_WC_HOSTS = {normalize_team_name(t) for t in ("USA", "Mexico", "Canada",
                                              "United States", "Meksyk", "Kanada")}


def _apply_national_lambda(wyniki: list) -> None:
    """
    Dla meczów reprezentacji (obie drużyny w `team_stats`): liczy Poisson λ z realnych
    statów turnieju i BLENDUJE pw/pr/pp/o25/bt z Bzzoiro-ML (waga `_NATIONAL_BLEND`).
    Gospodarze WC (USA/Meksyk/Kanada) grający u siebie → boost λ (`_HOST_BOOST`).
    Model bazowy nie ma historii kadr → to wypełnia lukę (mundial). Gated: kluby bez
    team_stats → bez zmian (backtest klubowy niezmieniony).
    """
    try:
        from footstats.core.player_db import team_attack_defense
        from footstats.core.national_lambda import national_team_probs
    except ImportError as e:
        log.warning("Lambda reprezentacji niedostepna (%s) — mecze kadr jada"
                    " na modelu bazowym, ktory NIE MA ich historii", e)
        return

    season = _current_season()
    for w in wyniki:
        try:
            ad_h = team_attack_defense(w.get("gospodarz") or "", season)
            ad_a = team_attack_defense(w.get("goscie") or "", season)
            if not ad_h or not ad_a:
                continue
            boost = _HOST_BOOST if normalize_team_name(w.get("gospodarz") or "") in _WC_HOSTS else 1.0
            nat = national_team_probs(ad_h[0], ad_h[1], ad_a[0], ad_a[1], home_boost=boost)
            bz_sum = (w.get("pw") or 0) + (w.get("pr") or 0) + (w.get("pp") or 0)
            wt = _NATIONAL_BLEND if bz_sum > 1 else 1.0
            for key in ("pw", "pr", "pp", "o25", "bt"):
                w[key] = round(wt * nat[key] + (1 - wt) * (w.get(key) or 0), 1)
            w["lambda_h"], w["lambda_a"] = nat["lambda_h"], nat["lambda_a"]
            w["national_lambda"] = True
        except (KeyError, TypeError, ValueError) as e:
            log.debug("national_lambda skip (%s): %s", w.get("gospodarz"), e)


# ── Krok 2: Forma SofaScore ───────────────────────────────────────────────────

def _wzbogac_forme_top(wyniki: list, top_n: int = 6) -> None:
    """Pobiera formę + kontuzje dla TOP N meczów przez SofaScore."""
    try:
        from footstats.scrapers.form_scraper import pobierz_forme_meczu, PLAYWRIGHT_OK
        if not PLAYWRIGHT_OK:
            console.print("[yellow]SofaScore niedostępny (Playwright) — pomijam formę[/yellow]")
            return
    except ImportError:
        console.print("[yellow]form_scraper niedostępny — pomijam formę[/yellow]")
        return

    def _max_ev(w):
        return max((v for _, v in w.get("typy", [(None, 0)])), default=0)

    top = sorted(wyniki, key=_max_ev, reverse=True)[:top_n]
    console.print(f"[dim]SofaScore: pobieram formę dla {len(top)} meczów...[/dim]")

    for w in top:
        g = w.get("gospodarz", "")
        a = w.get("goscie", "")
        if not g or not a:
            continue
        try:
            forma = pobierz_forme_meczu(g, a)
            fh = forma.get("home", {})
            fa = forma.get("away", {})
            if fh.get("form"):
                w["sofa_forma_g"] = f"{''.join(fh['form'])}({fh.get('goals_scored',0)}:{fh.get('goals_conceded',0)})"
            if fa.get("form"):
                w["sofa_forma_a"] = f"{''.join(fa['form'])}({fa.get('goals_scored',0)}:{fa.get('goals_conceded',0)})"
            # Pełne dane kontuzji (z pozycją) do korekty λ — nie tylko nazwy do wyświetlenia.
            #
            # WARUNKOWO, i to jest cała naprawa z 31.08: przypisanie było bezwarunkowe,
            # więc pusta lista z zablokowanego SofaScore'a (403 → `_empty_form`)
            # kasowała komplet absencji, które FotMob zapisał 20 linii wcześniej
            # w `_enrichuj_finalna_faza`. `_apply_injury_corrections` czytało już nic.
            # Objawem byłaby zerowa korekta λ przy poprawnie pobranych składach.
            if fh.get("injuries"):
                w["injuries_home"] = fh["injuries"]
            if fa.get("injuries"):
                w["injuries_away"] = fa["injuries"]
            inj_g = [i.get("name", "?") for i in fh.get("injuries", [])[:3]]
            inj_a = [i.get("name", "?") for i in fa.get("injuries", [])[:3]]
            if inj_g:
                w["sofa_kontuzje_g"] = ", ".join(inj_g)
            if inj_a:
                w["sofa_kontuzje_a"] = ", ".join(inj_a)
        except (AttributeError, TypeError, KeyError) as e:
            log.warning("Dane SofaScore dla %s-%s w nieoczekiwanym ksztalcie"
                        " (%s: %s) — mecz idzie bez formy i kontuzji",
                        w.get("gosp"), w.get("gosc"), type(e).__name__, e)


def _wzbogac_o_betbuilder(wyniki: list, pobierz_superbet: bool = False) -> None:
    """
    Wzbogaca mecze o sugestie BetBuilder.

    Krok 1 (zawsze): Poisson — szybka estymacja prawdopodobieństw.
    Krok 2 (--bb):   Real kursy z Superbet API via browser (~2-4min dla 5 meczów).
                     Generuje kombinacje z generuj_kombinacje() i zapisuje do
                     w["bet_builder_kombinacje_superbet"] dla kontekstu AI Groq.
    """
    # -- Krok 1: Poisson (zawsze) --
    try:
        from footstats.core.bet_builder import estimate_lambdas_from_probs, get_all_market_suggestions
        from footstats.betbuilder import fmt_bb_sugestie
    except ImportError as e:
        log.warning("BetBuilder niedostepny (%s) — brak sugestii rynkowych"
                    " w kontekscie dla Groqa w CALYM przebiegu", e)
    else:
        console.print("[dim]BetBuilder: Estymacja macierzy Poissona...[/dim]")
        for w in wyniki:
            pw  = w.get("pw", 0) / 100.0
            pp  = w.get("pp", 0) / 100.0
            o25 = w.get("o25", 0) / 100.0
            if pw > 0 or pp > 0:
                lh, la  = estimate_lambdas_from_probs(pw, pp, o25)
                ref_avg = w.get("referee_avg_y")
                markets = get_all_market_suggestions(lh, la, ref_avg_yellow=ref_avg)
                all_sugestie = [
                    f"[{cat}] {item}"
                    for cat, items in markets.items()
                    for item in items
                ]
                if all_sugestie:
                    w["bet_builder"]         = all_sugestie
                    w["bet_builder_markets"] = markets
                    bb_raw = markets.get("BetBuilder", [])
                    if bb_raw:
                        w["bet_builder_kombinacje"] = fmt_bb_sugestie(bb_raw)

    # -- Krok 2: Real Superbet BB odds (opcjonalnie, --bb) --
    if not pobierz_superbet:
        return

    try:
        from footstats.scrapers.superbet_bb import pobierz_bb_dla_meczow
        from footstats.betbuilder import generuj_kombinacje
    except ImportError:
        console.print("[yellow]BetBuilder Superbet: brak modulu superbet_bb[/yellow]")
        return

    top_n = wyniki[:5]
    mecze_input = [
        {"dom": w.get("gospodarz", ""), "gost": w.get("goscie", "")}
        for w in top_n
        if w.get("gospodarz") and w.get("goscie")
    ]
    if not mecze_input:
        return

    console.print(f"[dim]BetBuilder Superbet: pobieranie kursow dla {len(mecze_input)} meczow (moze ~3min)...[/dim]")
    try:
        bb_data = pobierz_bb_dla_meczow(mecze_input, headless=True)
    except Exception as e:  # noqa: BLE001 — Playwright raises varied types
        console.print(f"[yellow]BetBuilder Superbet error: {e}[/yellow]")
        return

    for w in top_n:
        dom   = w.get("gospodarz", "")
        gost  = w.get("goscie", "")
        klucz = f"{dom} vs {gost}"
        typy  = bb_data.get(klucz, [])
        if not typy:
            continue

        typy_filtr = [t for t in typy if 1.15 <= t.kurs <= 10.0][:60]
        if not typy_filtr:
            continue

        combos = generuj_kombinacje(
            typy_filtr,
            min_typy=2,
            max_typy=4,
            min_kurs=3.0,
            min_ev=0.0,
        )
        if not combos:
            continue

        # Fokus na realnym zakresie 5x-25x (atrakcyjne, nie absurdalne)
        zakres = [c for c in combos if 5.0 <= c.kurs_laczny <= 25.0]
        top_combos = sorted(zakres or combos, key=lambda c: c.kurs_laczny)[:12]
        w["bet_builder_kombinacje_superbet"] = [
            {"kurs": c.kurs_laczny, "typy": [{"nazwa": t.nazwa, "kurs": t.kurs} for t in c.typy]}
            for c in top_combos
        ]
        console.print(f"[dim]  BB Superbet {klucz}: {len(combos)} kombinacji ({len(zakres)} w 5-25x)[/dim]")


def _wzbogac_o_inspiracje(wyniki: list, debug: bool = False) -> None:
    """
    Krok opcjonalny (FAZA 15.7): pobiera "Popularne kupony" ze Strefy Inspiracji
    STS + karuzelę BetBuilder ze strony głównej, dopasowuje do kandydatów po
    nazwach drużyn i ocenia sygnał (VALUE/NO_VALUE) wzgledem modelu Poisson.
    Zapisuje wynik w w["inspiracje_signal"] dla kontekstu Groq.

    Niepowodzenie (brak playwright, timeout, błąd sieci) nie przerywa pipeline'u.
    """
    try:
        from footstats.scrapers.sts_inspiracje import (
            PLAYWRIGHT_OK,
            dopasuj_do_predykcji,
            parse_betbuilder_carousel,
            parse_popular_tickets,
            pobierz_betbuilder_carousel,
            pobierz_popularne_kupony,
        )
        from footstats.core.bet_builder import estimate_lambdas_from_probs
    except ImportError as e:
        console.print(f"[dim]Strefa Inspiracji: {e}[/dim]")
        return

    if not PLAYWRIGHT_OK:
        console.print("[dim]Strefa Inspiracji: playwright niedostepny, pomijam[/dim]")
        return

    console.print("[dim]Strefa Inspiracji: pobieranie sygnalow top typerow...[/dim]")
    try:
        tickets = parse_popular_tickets(pobierz_popularne_kupony(debug=debug))
        tickets += parse_betbuilder_carousel(pobierz_betbuilder_carousel(debug=debug))
    except (OSError, RuntimeError) as e:
        console.print(f"[dim]Strefa Inspiracji: blad scrapingu - {e}[/dim]")
        return

    if not tickets:
        console.print("[dim]Strefa Inspiracji: brak kuponow do dopasowania[/dim]")
        return

    predykcje = []
    for w in wyniki:
        pw, pp, o25 = w.get("pw", 0) / 100.0, w.get("pp", 0) / 100.0, w.get("o25", 0) / 100.0
        if pw <= 0 and pp <= 0:
            continue
        lh, la = estimate_lambdas_from_probs(pw, pp, o25)
        predykcje.append({
            "gosp": w.get("gospodarz", ""), "gosc": w.get("goscie", ""),
            "expected_home_goals": lh, "expected_away_goals": la,
        })

    sygnaly = dopasuj_do_predykcji(tickets, predykcje)
    if not sygnaly:
        console.print(f"[dim]Strefa Inspiracji: {len(tickets)} kuponow typerow, 0 dopasowan[/dim]")
        return

    by_team = {(_norm(s["gosp"]), _norm(s["gosc"])): s for s in sygnaly}
    for w in wyniki:
        s = by_team.get((_norm(w.get("gospodarz", "")), _norm(w.get("goscie", ""))))
        if s:
            w["inspiracje_signal"] = s

    n_value = sum(1 for s in sygnaly if s["signal"] == "VALUE")
    console.print(f"[green]Strefa Inspiracji: {len(sygnaly)} dopasowan, {n_value} VALUE[/green]")
    for s in sygnaly:
        ticket = s["ticket"]
        console.print(
            f"[dim]  {s['gosp']} vs {s['gosc']}: typy={ticket['typy']} "
            f"kurs={ticket['total_odds']} -> {s['signal']}[/dim]"
        )


# ── Krok 2b: Fallback kursów API-Football -> SofaScore (gdy Bzzoiro brak) ────

def _uzupelnij_kursy(w: dict, fallback_odds: dict | None) -> bool:
    """Dopisuje brakujące klucze kursów do kandydata `w` (nie nadpisuje istniejących)."""
    if not fallback_odds:
        return False
    existing = dict(w.get("odds") or {})
    for key, val in fallback_odds.items():
        existing.setdefault(key, val)
    w["odds"] = existing
    return True


def _wzbogac_o_kursy_fallback(wyniki: list, top_n: int | None = None) -> None:
    """
    Dla meczów bez kompletnych kursów (home/draw/away) Bzzoiro próbuje uzupełnić
    je dwustopniowo:
      1. API-Football /odds (reuse APISPORTS_KEY + budżet, brak anti-bot) — priorytet.
      2. SofaScore (scraper Playwright) jako drugi fallback, gdy AF nie znalazł kursów
         lub nie uzupełnił wszystkich rynków.

    NIE nadpisuje istniejących kursów Bzzoiro (i nie nadpisuje kursów AF kursami
    SofaScore) — wzbogaca tylko brakujące/puste klucze.
    """
    braki = [
        w for w in wyniki
        if not all((w.get("odds") or {}).get(k) for k in ("home", "draw", "away"))
    ]
    if not braki:
        return
    if top_n is not None:
        braki = braki[:top_n]

    console.print(f"[dim]Fallback kursów: API-Football dla {len(braki)} meczów bez kursów Bzzoiro...[/dim]")

    uzupelniono_af = 0
    nadal_braki = []
    for w in braki:
        g = w.get("gospodarz", "")
        a = w.get("goscie", "")
        data_meczu = w.get("data") or w.get("date") or ""
        if not g or not a:
            continue
        try:
            af_odds = fetch_odds_af(g, a, data_meczu)
        except (OSError, RuntimeError, ValueError) as e:
            log.debug("API-Football odds fallback error %s vs %s: %s", g, a, e)
            af_odds = None

        if _uzupelnij_kursy(w, af_odds):
            uzupelniono_af += 1

        if not all((w.get("odds") or {}).get(k) for k in ("home", "draw", "away")):
            nadal_braki.append(w)

    console.print(f"[cyan]API-Football fallback kursów: uzupełniono {uzupelniono_af}/{len(braki)} meczów[/cyan]")

    if not nadal_braki:
        return

    # 2. The Odds API — requests-only, bez anti-bota, cała liga w jednym zapytaniu.
    # Idzie PRZED SofaScore, bo SofaScore oddaje 403 i wymaga Playwrighta (w cloud
    # draft nie istnieje). Brak ODDS_API_KEY → cicho pomijane, łańcuch leci dalej.
    try:
        from footstats.scrapers.odds_api import dolacz_kursy_odds_api
        uzupelniono_oa = dolacz_kursy_odds_api(nadal_braki)
        if uzupelniono_oa:
            console.print(f"[cyan]The Odds API: uzupełniono {uzupelniono_oa} meczów[/cyan]")
        nadal_braki = [w for w in nadal_braki if not all(
            (w.get("odds") or {}).get(k) for k in ("home", "draw", "away")
        )]
    except (ImportError, OSError, ValueError, KeyError) as e:
        log.debug("The Odds API fallback pominiety: %s", e)

    if not nadal_braki:
        return

    try:
        from footstats.scrapers.sofascore_odds import fetch_odds, PLAYWRIGHT_OK
        from footstats.scrapers.form_scraper import _sofa_session
    except ImportError:
        console.print("[dim]sofascore_odds niedostępny — pomijam 2. fallback kursów[/dim]")
        return

    if not PLAYWRIGHT_OK:
        console.print("[yellow]SofaScore niedostępny (Playwright) — pomijam 2. fallback kursów[/yellow]")
        return

    console.print(f"[dim]SofaScore (2. fallback): uzupełniam kursy dla {len(nadal_braki)} meczów...[/dim]")

    sess = _sofa_session()
    if sess is None:
        console.print("[yellow]SofaScore: błąd sesji — pomijam 2. fallback kursów[/yellow]")
        return
    p, browser, page = sess

    uzupelniono_sofa = 0
    try:
        for w in nadal_braki:
            g = w.get("gospodarz", "")
            a = w.get("goscie", "")
            data_meczu = w.get("data") or w.get("date") or ""
            if not g or not a:
                continue
            try:
                fallback_odds = fetch_odds(g, a, data_meczu, page=page)
            except (OSError, RuntimeError, ValueError) as e:
                log.debug("SofaScore odds fallback error %s vs %s: %s", g, a, e)
                continue
            if _uzupelnij_kursy(w, fallback_odds):
                uzupelniono_sofa += 1
    finally:
        browser.close()
        p.stop()

    console.print(f"[cyan]SofaScore fallback kursów: uzupełniono {uzupelniono_sofa}/{len(nadal_braki)} meczów[/cyan]")


# ── Krok 4b: Kelly Criterion ──────────────────────────────────────────────────

def _kalibrator_pewnosci():
    """Funkcja kalibrujaca pewnosc, a przy jej braku — tozsamosc, ale GLOSNO.

    Fallback `lambda pct: pct / 100.0` jest poprawny (kupon bez stawki bylby
    gorszy niz kupon ze stawka surowa), ale do 25.08 podmienial kalibracje
    CALKOWICIE po cichu. Pewnosci przestawaly byc kalibrowane, stawki Kelly'ego
    sie zmienialy, a w logu nie bylo ani slowa — nie do odroznienia od stanu
    zdrowego.
    """
    try:
        from footstats.core.probability_calibrator import calibrate_confidence
        return calibrate_confidence
    except ImportError as e:
        log.warning("Kalibracja pewnosci niedostepna (%s) — stawki licza sie z"
                    " pewnosci SUROWEJ (pct/100)", e)
        return lambda pct: pct / 100.0


def _bezpieczny_kelly(kelly_fn, p: float, odds: float, bankroll: float) -> float:
    """Stawka Kelly'ego, a przy bledzie wejscia — 1.0 PLN, ale ze sladem.

    Stawka 1.0 wyglada na produkcji jak swiadoma decyzja modelu. Bez logu nie da
    sie jej odroznic od kursu 0, pewnosci None albo innego smiecia z Groqa.
    """
    try:
        return kelly_fn(p, odds, bankroll=bankroll)
    except (TypeError, ZeroDivisionError) as e:
        log.warning("Kelly nie policzyl stawki (p=%s, kurs=%s): %s — awaryjnie 1.0 PLN",
                    p, odds, e)
        return 1.0


def _dodaj_kelly(dane: dict, bankroll: float) -> None:
    """Dodaje kelly_stake do każdego zdarzenia w kuponach i top3."""
    try:
        from footstats.core.kelly import kelly_stake
        from footstats.config import AGENT_BANKROLL
        from footstats.core.calibration import get_stake_multiplier, calibration_summary
    except ImportError as e:
        # Wyjscie BEZ wyliczenia stawek dla calego kuponu. Kupon powstaje
        # normalnie, wiec z zewnatrz wyglada poprawnie — az ktos zapyta, czemu
        # nie ma `kelly_stake`.
        log.warning("Kelly/kalibracja nie wstaly (%s) — zdarzenia zostaja BEZ"
                    " wyliczonej stawki", e)
        return

    # Guard: bankroll musi być dodatnią liczbą — DB może zwrócić None
    if not isinstance(bankroll, (int, float)) or bankroll <= 0:
        bankroll = AGENT_BANKROLL

    # Etap 6: kalibracja stawki (Forma Bota 3 kupony + hit-rate 10 kuponów)
    multiplier = get_stake_multiplier()  # łączy oba sygnały
    cal = calibration_summary()
    if cal.get("n", 0) > 0:
        forma_info = f" | Forma3: {cal.get('forma_multiplier', 1.0)}x ({cal.get('forma_note', '')})"
        console.print(
            f"[dim]Kalibracja: hit={cal['hit_rate']:.0%} ({cal['won']}/{cal['n']}) "
            f"→ multiplier={multiplier}x — {cal['note']}{forma_info}[/dim]"
        )
    # Zabezpieczenie: multiplier nigdy None
    if not isinstance(multiplier, (int, float)) or multiplier <= 0:
        multiplier = 1.0
    effective_bankroll = bankroll * multiplier

    calibrate_confidence = _kalibrator_pewnosci()

    # (x or {}) — Groq potrafi zwrócić kupon=None / zdarzenia=None (crash prod 20.07)
    for kupon_key in ("kupon_a", "kupon_b", "kupon_c", "kupon_d"):
        for z in (dane.get(kupon_key) or {}).get("zdarzenia") or []:
            p    = calibrate_confidence(z.get("pewnosc_pct") or 50)
            odds = z.get("kurs") or 1.0
            z["kelly_stake"] = _bezpieczny_kelly(kelly_stake, p, odds, effective_bankroll)

    for row in dane.get("top3") or []:
        p    = calibrate_confidence(row.get("pewnosc_pct") or 50)
        odds = row.get("kurs") or 1.0
        row["kelly_stake"] = _bezpieczny_kelly(kelly_stake, p, odds, effective_bankroll)


# ── Krok 6: Walidacja Groq ────────────────────────────────────────────────────

def _waliduj_kupon_groq(dane: dict, stawka: float, kupon_key: str = "kupon_a") -> None:
    from footstats.ai.analyzer import ai_sprawdz_kupon

    kupon     = dane.get(kupon_key) or {}
    zdarzenia = kupon.get("zdarzenia") or []
    if not zdarzenia:
        return

    picks_text = "\n".join(
        f"{z.get('nr')}. {z.get('mecz')} | {z.get('typ')} @{z.get('kurs')}"
        for z in zdarzenia
    )
    console.rule(f"[bold cyan]WALIDACJA GROQ — {kupon_key.upper()}[/bold cyan]")
    console.print(ai_sprawdz_kupon(picks_text, stawka=stawka))


# ── Ensemble: roznica_modeli ─────────────────────────────────────────────────

def _oblicz_roznica_modeli(wyniki: list) -> None:
    """
    Oblicza roznica_modeli = max(|P_poisson − P_bzzoiro|) dla win/draw/loss.

    Używa wynik_g/wynik_a z Bzzoiro ML jako przybliżonych lambd Poissona
    (brak potrzeby ładowania bazy historycznej).
    Ustawia pole 'roznica_modeli' in-place na każdym kandydacie.
    """
    try:
        from scipy.stats import poisson as _sps
        from footstats.core.ensemble import ensemble_probs, get_roznica
    except ImportError as e:
        log.warning("Ensemble niedostepny (%s) — `roznica_modeli` zostaje PUSTE"
                    " na wszystkich kandydatach, selekcja traci ten sygnal", e)
        return

    for k in wyniki:
        pw = k.get("pw", 0) / 100.0
        pr = k.get("pr", 0) / 100.0
        pp = k.get("pp", 0) / 100.0
        if pw + pr + pp < 0.01:
            continue  # brak danych ML Bzzoiro

        p_bzzoiro = {"win": pw, "draw": pr, "loss": pp}

        lh = max(float(k.get("wynik_g", 1) or 1), 0.3)
        la = max(float(k.get("wynik_a", 1) or 1), 0.3)

        p_win = p_draw = p_loss = 0.0
        for i in range(8):
            for j in range(8):
                p = _sps.pmf(i, lh) * _sps.pmf(j, la)
                if i > j:
                    p_win  += p
                elif i == j:
                    p_draw += p
                else:
                    p_loss += p

        p_poisson = {"win": p_win, "draw": p_draw, "loss": p_loss}
        liga = k.get("liga") or None
        p_ens = ensemble_probs(p_poisson, p_bzzoiro, liga=liga)
        k["roznica_modeli"] = round(get_roznica(p_ens, p_poisson, p_bzzoiro), 3)


# ── Faza final: enrichment składów/sędziego ──────────────────────────────────

def _dopasuj_luzno(idx: dict, gospodarz: str, goscie: str) -> dict | None:
    """Najlepszy fixture dla pary drużyn, gdy dopasowanie dokładne zawiodło.

    Wcześniej sprawdzany był podciąg (`gh in fh or fh in gh`), przez co "Legia"
    łapała fixture "Legia II" — a rezerwy grają zwykle w ten sam weekend, więc
    oba mecze bywają w jednej puli. Kandydat dostawał wtedy skład i sędziego
    z cudzego spotkania i wchodziło to do selekcji jako dane pewne.

    `team_similarity` zna znaczniki rezerw i zwraca dla nich 0.0. Bierzemy
    NAJLEPSZE dopasowanie, nie pierwsze napotkane — kolejność `idx` to kolejność
    odpowiedzi API, więc "pierwsze" bywało loterią.
    """
    najlepszy, najlepszy_wynik = None, 0.0
    for (fh, fa), f in idx.items():
        wynik = min(team_similarity(gospodarz, fh), team_similarity(goscie, fa))
        if wynik >= PROG_DOPASOWANIA_MECZU and wynik > najlepszy_wynik:
            najlepszy, najlepszy_wynik = f, wynik
    return najlepszy


FLAGA_TEAM_NEWS = "FOOTSTATS_TEAM_NEWS"

# FlashScore chodzi przez Playwrighta — jedna przegladarka na mecz. Limit istnieje
# od 30.08, razem z odblokowaniem tej sciezki: wczesniej byla zabezpieczona za
# martwym API-Football i realnie nie odpalala sie wcale, wiec koszt nie istnial.
_MAX_FLASHSCORE_NA_PRZEBIEG = 6


def _flashscore_szczegoly(gospodarz: str, goscie: str) -> dict:
    """Wydzielone wywolanie FlashScore — zeby test podmienil je bez Playwrighta."""
    from footstats.scrapers.flashscore_match import scrape_match_with_search
    return scrape_match_with_search(gospodarz, goscie)


def _pobierz_team_news(data: str, pary: list[tuple[str, str]]) -> list:
    """
    Wydzielone, żeby test mógł podmienić źródło bez dotykania sieci.

    `pary` filtruje JUŻ NA LIŚCIE DNIA. Bez tego przebieg kosztowałby 483
    requesty (30.08: 147 lig, 482 mecze), żeby użyć kilkudziesięciu.
    """
    from footstats.scrapers.teamnews.fotmob import FotMobTeamNews
    return FotMobTeamNews().fetch_dla(data, pary)


def _dopasuj_team_news(idx: dict, gospodarz: str, goscie: str):
    """
    Najlepsze dopasowanie meczu po podobieństwie nazw, gdy klucz dokładny zawiódł.

    Bliźniak `_dopasuj_luzno` z toru API-Football, celowo z tym samym progiem
    `PROG_DOPASOWANIA_MECZU`: dwa różne progi rozjechałyby się po cichu, a taki
    rozjazd objawia się dopiero utratą meczów.

    NAJLEPSZE dopasowanie, nie pierwsze napotkane — kolejność `idx` to kolejność
    odpowiedzi źródła, więc "pierwsze" byłoby loterią.
    """
    najlepszy, najlepszy_wynik = None, 0.0
    for (fh, fa), tn in idx.items():
        wynik = min(team_similarity(gospodarz, fh), team_similarity(goscie, fa))
        if wynik >= PROG_DOPASOWANIA_MECZU and wynik > najlepszy_wynik:
            najlepszy, najlepszy_wynik = tn, wynik
    return najlepszy


def _sedzia_z_bazy(nazwa: str, stan: dict) -> dict | None:
    """
    Wiersz sędziego z naszej bazy. `None` gdy sędziego tam nie ma ALBO gdy baza
    jest nieosiągalna — dwa różne stany, więc drugi zostawia ostrzeżenie.

    Sędzia to wzbogacenie, nie rdzeń. Do 31.08 nieosiągalna baza przewracała
    CAŁĄ fazę final w `init_referee_table()`, z tracebackiem prowadzącym w głąb
    warstwy bazy przy płytkiej przyczynie. Skutek praktyczny: potoku nie dało
    się sprawdzić inaczej niż na produkcji.

    Gdy baza padnie naprawdę, przebieg i tak stanie — na zapisie `predictions`
    i kuponu, czyli tam, gdzie brak bazy faktycznie ma znaczenie.

    `stan` niesie flagę „już ostrzegałem": 46 kandydatów to byłoby 46 identycznych
    ostrzeżeń, a szum zabija alarmy tak samo skutecznie jak cisza.
    """
    from footstats.scrapers.referee_db import get_referee

    if stan.get("padla"):
        return None
    try:
        return get_referee(nazwa)
    except (RuntimeError, OSError) as e:
        stan["padla"] = True
        log.warning(
            "Baza sedziow nieosiagalna (%s: %s) — kandydaci ida bez statystyk "
            "sedziego, reszta wzbogacenia bez zmian", type(e).__name__, e)
        return None


def _kurs(surowa: object) -> float | None:
    """Kurs jako float. Źródła oddają raz float, raz string, raz '-'."""
    try:
        return float(str(surowa).strip())
    except (TypeError, ValueError) as e:
        # Debug, nie warning: pojedynczy śmieciowy kurs to normalny stan źródła.
        # Ale cisza tutaj znaczyłaby to samo co brak rynku, a to dwie różne rzeczy.
        log.debug("Kurs nie do sparsowania (%r): %s", surowa, e)
        return None


def _rynek_p_over(odds: object) -> float | None:
    """
    P(Over 2.5) rynku z kursów kandydata, po zdjęciu marży. None gdy brak pary.

    Do 31.08 `market_p_over` nie było ustawiane NIGDZIE w src/ — tylko czytane
    niżej i podstawiane ręcznie w testach. Zmierzone na 12 żywych kandydatach
    FotMoba: `edge_absencje` wyszło None na KAŻDYM, mimo poprawnie policzonego
    `p_over_abs`. Pole istniało wyłącznie w testach.

    Samego kursu Over NIE wystarczy: 1/kurs zawiera vig, więc rynek wyszedłby
    zawyżony, a edge systematycznie zaniżony. Bez pary zostaje None — brak
    pomiaru, nie zero.
    """
    if not isinstance(odds, dict):
        return None
    from footstats.core.calibration_metrics import devig_two_way

    para = devig_two_way(_kurs(odds.get("over_2_5")), _kurs(odds.get("under_2_5")))
    return None if para is None else round(para[0], 4)


def _policz_edge_absencji(kandydaci: list) -> None:
    """
    Zamienia potwierdzone absencje na skorygowaną λ i P(Over 2.5). In-place.

    ZAPISUJEMY OBOK, NIE NADPISUJEMY `pw/pr/pp/o25/bt` — i to jest decyzja,
    nie przeoczenie. Historii kontuzji nie ma ani u nas, ani u FotMoba, więc tej
    korekty NIE DA SIĘ zwalidować walk-forwardem. Wpuszczenie niezwalidowanej
    poprawki do typów produkcyjnych byłoby powtórzeniem błędu, który ten projekt
    już raz zmierzył: 14.08 na n=15 460 żaden z 52 podzbiorów nie przeżył
    holdoutu. Pola `*_abs` dają liczbę, którą za kilkadziesiąt meczów będzie
    można porównać z rzeczywistością — i dopiero wtedy jest o czym decydować.

    Udziały w golach biorą się z `player_db` (poprzedni pełny sezon), NIE
    z `performance.seasonGoals` FotMoba: w końcu sierpnia Premier League miała
    5 goli na dwie kadry, więc udział jednego strzelca wyszedłby 0,4.
    """
    from footstats.core.absencje import udzialy_absencji
    from footstats.core.availability_edge import over_edge_from_absences
    from footstats.core.bet_builder import estimate_lambdas_from_probs

    trafione = bez_udzialu = 0
    for k in kandydaci:
        # pop, nie get: to pole robocze jednego przebiegu. Zostawione w kandydacie
        # pojechaloby dalej potokiem i mogloby wyladowac w serializacji.
        pewne_h = k.pop("_absencje_pewne_nazwiska_home", None) or []
        pewne_a = k.pop("_absencje_pewne_nazwiska_away", None) or []
        if not pewne_h and not pewne_a:
            continue

        gs_h = _goal_shares_for(k.get("gospodarz") or "", "home")
        gs_a = _goal_shares_for(k.get("goscie") or "", "away")
        ud_h, brak_h = udzialy_absencji(pewne_h, gs_h)
        ud_a, brak_a = udzialy_absencji(pewne_a, gs_a)

        trafione += len(ud_h) + len(ud_a)
        bez_udzialu += len(brak_h) + len(brak_a)
        if brak_h or brak_a:
            k["absencje_bez_udzialu"] = len(brak_h) + len(brak_a)

        # Jawny `market_p_over` wygrywa — kursy są uzupełnieniem, nie nadpisaniem.
        rynek = k.get("market_p_over")
        if rynek is None:
            rynek = _rynek_p_over(k.get("odds"))
        # Cena Z TAMTEJ CHWILI zostaje osobno, nie tylko w `edge`. Edge jest
        # roznica, wiec po zaokragleniach nie odtworzy sie z niej skladnika —
        # a bez ceny, wobec ktorej liczylismy przewage, nie da sie pozniej
        # orzec, kto mial racje. To jest cala wartosc tego wpisu.
        #
        # ZAPIS IDZIE PRZED bramka na udzialy (07.09.2026). Cena nie zalezy od
        # tego, czy znamy udzial nieobecnych w golach — zalezy od kursow, ktore
        # juz trzymamy w reku. Do 07.09 stala pod `continue` nizej i przez to
        # nie zapisala sie ANI RAZU: w kontenerze `player_db` jest puste zawsze
        # (`no such table: player_stats`), wiec kazdy kandydat wychodzil bramka.
        k["rynek_p_over"] = rynek

        if not ud_h and not ud_a:
            # Wiemy, kto nie zagra, ale nie wiemy, ile znaczy. Zgadywanie kary
            # byłoby gorsze niż jej brak — ale cena wyzej zostaje zapisana.
            continue

        lh, la = k.get("lambda_h"), k.get("lambda_a")
        if not lh or not la:
            lh, la = estimate_lambdas_from_probs(
                (k.get("pw") or 0) / 100.0, (k.get("pp") or 0) / 100.0,
                (k.get("o25") or 0) / 100.0)
        wynik = over_edge_from_absences(lh, la, ud_h, ud_a, rynek)
        k["lambda_h_abs"] = wynik["lh"]
        k["lambda_a_abs"] = wynik["la"]
        k["p_over_abs"] = wynik["p_over_adj"]
        k["edge_absencje"] = wynik["edge"]
        k["absencje_udzial_home"] = round(sum(ud_h), 4)
        k["absencje_udzial_away"] = round(sum(ud_a), 4)

    if trafione or bez_udzialu:
        log.info("team-news: udzialy absencji %d/%d dopasowane w player_db "
                 "(reszta bez udzialu — znamy nazwisko, nie znamy wagi)",
                 trafione, trafione + bez_udzialu)


def _wzbogac_team_news(kandydaci: list) -> None:
    """
    Dokłada kandydatom przewidywany skład, absencje i sędziego z FotMoba.
    Modyfikuje `kandydaci` in-place, spójnie z resztą tej fazy.

    Za flagą `FOOTSTATS_TEAM_NEWS=1` — domyślnie OFF do czasu smoke'a na żywym
    potoku. Włączając: ustawić w TRZECH miejscach (API + `footstats-final`
    + `footstats-evening`). `ENSEMBLE_MARKET_WEIGHT` rozjechało się dokładnie
    tak: API miało 0.70, joby nie miały nic.

    Do korekty λ trafiają WYŁĄCZNIE absencje potwierdzone. "Doubtful" i brak
    danych zostają w liczniku informacyjnym — model nie ma liczyć straty
    zawodnika, który zagra.
    """
    if os.getenv(FLAGA_TEAM_NEWS) != "1":
        return
    if not kandydaci:
        return

    from datetime import date as _date

    from footstats.utils.normalize import normalize_team_name

    pary = [(k.get("gospodarz") or "", k.get("goscie") or "") for k in kandydaci]
    dane = _pobierz_team_news(_date.today().isoformat(), pary)
    if not dane:
        # PODNIESIONE Z DEBUG NA WARNING 07.09.2026. Poprzedni komentarz mówił
        # „powód zgłosił już adapter, na ERROR" — ale adapter krzyczy WYŁĄCZNIE
        # gdy padnie zapytanie o listę dnia. Gdy lista przyjdzie poprawnie i po
        # prostu zero meczów pasuje do naszych kandydatów, jedynym śladem był
        # `log.debug` w `fotmob.fetch_dla`, czyli na produkcji ślad żaden.
        # Zmierzone: przebieg `footstats-final` z 06.09 nie zostawił w 258
        # liniach stdout ANI JEDNEJ wzmianki o team-news, a kanał był martwy.
        log.warning("team-news: zrodlo oddalo pusta liste — %d kandydatow bez "
                    "skladow, absencji i sedziego w tym przebiegu", len(kandydaci))
        return

    idx = {(normalize_team_name(t.home), normalize_team_name(t.away)): t
           for t in dane if t.home and t.away}

    wzbogaconych = prognoz = 0
    for k in kandydaci:
        klucz = (normalize_team_name(k.get("gospodarz") or ""),
                 normalize_team_name(k.get("goscie") or ""))
        tn = idx.get(klucz)
        if tn is None:
            # Nazwy źródeł się rozjeżdżają: FotMob pisze "Brighton & Hove Albion",
            # Bzzoiro "Brighton". Ten sam próg i ta sama funkcja co w torze
            # API-Football — drugi mechanizm dopasowania rozjechałby się z pierwszym.
            tn = _dopasuj_team_news(idx, k.get("gospodarz") or "", k.get("goscie") or "")
        if tn is None:
            continue

        k["team_news_source"] = tn.source
        k["team_news_prognoza"] = tn.sklad_jest_prognoza
        if tn.xi_home and tn.xi_away:
            k["lineup_ok"] = True
            k["startXI_home"] = list(tn.xi_home)
            k["startXI_away"] = list(tn.xi_away)
        pewne_h = [a.nazwisko for a in tn.absencje_home if a.pewna]
        pewne_a = [a.nazwisko for a in tn.absencje_away if a.pewna]
        k["absencje_pewne_home"] = len(pewne_h)
        k["absencje_pewne_away"] = len(pewne_a)
        # Nazwiska pod kluczem z podkreśleniem: to wejście do `_policz_edge_absencji`
        # w tym samym przebiegu, nie pole kandydata do zapisu ani wyświetlenia.
        k["_absencje_pewne_nazwiska_home"] = pewne_h
        k["_absencje_pewne_nazwiska_away"] = pewne_a

        # DWUSTRONNA korekta λ (`_apply_injury_corrections`, wołane niżej w tym
        # samym przebiegu) czyta `injuries_*` i klasyfikuje PO POZYCJI. Jedynym
        # źródłem pozycji był SofaScore — zmierzony 30.08 jako HTTP 403 na każde
        # zapytanie, i z Cloud Runa, i lokalnie. Bez tego wpięcia pozycje z FotMoba
        # leżałyby w DTO, którego nikt nie czyta.
        #
        # Absencja bez pozycji NIE wchodzi: `injury_lambda_factors` i tak zwróci
        # dla niej (1.0, 1.0), a wpis udawałby, że coś policzyliśmy.
        for strona, absencje in (("home", tn.absencje_home), ("away", tn.absencje_away)):
            klucz = f"injuries_{strona}"
            if k.get(klucz):
                continue   # dane innego źródła są pełniejsze — nie nadpisujemy
            z_pozycja = [{"name": a.nazwisko, "position": a.pozycja}
                         for a in absencje if a.pewna and a.pozycja]
            if z_pozycja:
                k[klucz] = z_pozycja
        if tn.sedzia:
            k["referee_name"] = tn.sedzia
            k["referee_stats"] = dict(tn.sedzia_stats)

        wzbogaconych += 1
        prognoz += int(tn.sklad_jest_prognoza)

    _policz_edge_absencji(kandydaci)

    komunikat = (f"team-news: {wzbogaconych}/{len(kandydaci)} kandydatow wzbogaconych "
                 f"({prognoz} predicted, {wzbogaconych - prognoz} lastStarting11)")
    if wzbogaconych == 0:
        log.warning(
            "%s — zrodlo oddalo %d meczow, ale ZADEN sie nie dopasowal. To albo "
            "rozjazd nazw druzyn, albo zmiana schematu FotMoba: bez wyjatku, bez "
            "danych, a przebieg konczy sie sukcesem.", komunikat, len(dane))
    else:
        log.info("%s", komunikat)


def _enrichuj_finalna_faza(wyniki: list, api_key: str) -> None:
    """
    Faza final: dla każdego kandydata pobiera składy i sędziego.

    Kolejność ma znaczenie. FotMob (`_wzbogac_team_news`) idzie PIERWSZY i ma
    pierwszeństwo — pole wypełnione przez niego nie jest nadpisywane przez tor
    API-Football niżej. Musi też być PRZED guardem `if not api_key`, bo konto
    API-Football jest zawieszone od 01.08, a brak jego klucza nie może odcinać
    źródła, które działa.

    To nie jest agregacja w sensie `sources/aggregator.py`: nie ma głosowania
    ani uzgadniania rozjazdów, jest zwykłe pierwszeństwo.

    Aktualizuje pola lineup_ok, referee_neutral, referee_signal in-place.
    """
    _wzbogac_team_news(wyniki)

    from footstats.core.apisports_gate import wlaczone as _af_wlaczone

    if not api_key or not _af_wlaczone():
        console.print("[dim]API-Football niedostępny (bramka zamknięta lub brak klucza) —"
                      " pomijam enrichment składów/sędziego[/dim]")
        return

    # Faza 1: opcjonalny auto-refresh bazy graczy (goal_share). Domyślnie OFF —
    # in-season włącz FOOTSTATS_REFRESH_PLAYERS=1 (16 req, cache 24h). W cloud job
    # populuje in-container SQLite dla tego samego procesu (enrichment czyta niżej).
    if os.getenv("FOOTSTATS_REFRESH_PLAYERS") == "1":
        try:
            from footstats.scrapers.player_stats import refresh_tracked_leagues
            n_pl = refresh_tracked_leagues(api_key)
            log.info("player_db auto-refresh: %d graczy", n_pl)
        except (ImportError, OSError, ValueError, KeyError) as e:
            log.debug("player auto-refresh skip: %s", e)

    import requests as _req
    from datetime import date
    from footstats.scrapers.lineup_scraper import get_lineup
    from footstats.scrapers.referee_db import signal_from_stats
    from footstats.core.lineup_strength import (
        lineup_confidence_penalty_v2, lineup_offensive_strength,
    )

    dzis = date.today().isoformat()
    try:
        resp = _req.get(
            "https://v3.football.api-sports.io/fixtures",
            params={"date": dzis, "status": "NS"},
            headers={"x-apisports-key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        fixtures = resp.json().get("response", [])
    except (OSError, ValueError, KeyError) as e:
        console.print(f"[yellow]API-Football fixtures: {e} — pomijam enrichment[/yellow]")
        return

    # Indeks (norm_home, norm_away) → fixture_data
    idx: dict = {}
    for f in fixtures:
        teams = f.get("teams", {})
        fh = _norm(teams.get("home", {}).get("name", ""))
        fa = _norm(teams.get("away", {}).get("name", ""))
        if fh and fa:
            idx[(fh, fa)] = f

    enriched = 0
    fs_zostalo = _MAX_FLASHSCORE_NA_PRZEBIEG
    # Wspólny na cały przebieg — patrz `_sedzia_z_bazy`: jedno ostrzeżenie,
    # nie jedno na kandydata.
    stan_bazy: dict = {}
    for k in wyniki:
        gh = _norm(k.get("gospodarz", ""))
        ga = _norm(k.get("goscie", ""))

        fixture = idx.get((gh, ga))
        if fixture is None:
            fixture = _dopasuj_luzno(idx, k.get("gospodarz", ""), k.get("goscie", ""))

        # Do 30.08 bylo tu `if fixture is None: continue` — i to jest powod, dla
        # ktorego produkcja od miesiaca raportowala "Final enrichment: 0/N".
        # Wywolanie FlashScore stoi NIZEJ w tej samej petli, wiec `continue`
        # zabezpieczal dzialajace, niezalezne zrodlo za martwym zrodlem glownym
        # (konto API-Football zawieszone od 01.08). Brak meczu w AF ma pomijac
        # WYLACZNIE czesci zalezne od AF, nie caly wiersz.
        fixture_id = (fixture or {}).get("fixture", {}).get("id")

        # Składy
        if fixture_id:
            lineup = get_lineup(fixture_id, api_key)
            k["lineup_ok"] = (
                lineup is not None
                and not lineup.get("home", {}).get("missing_key_players", True)
                and not lineup.get("away", {}).get("missing_key_players", True)
            )
            # Faza 2: siła składu wg goal_share (brak topowego strzelca w XI → kara)
            if lineup is not None:
                gs_h = _goal_shares_for(k.get("gospodarz") or "", "home")
                gs_a = _goal_shares_for(k.get("goscie") or "", "away")
                k["lineup_star_penalty"] = lineup_confidence_penalty_v2(lineup, gs_h, gs_a)
                k["lineup_strength_home"] = round(
                    lineup_offensive_strength((lineup.get("home", {}) or {}).get("startXI", []), gs_h), 3)
                k["lineup_strength_away"] = round(
                    lineup_offensive_strength((lineup.get("away", {}) or {}).get("startXI", []), gs_a), 3)
        else:
            k["lineup_ok"] = None

        # Sędzia. `fixture` bywa None (kandydat spoza pokrycia API-Football) —
        # wtedy nazwisko przyjdzie niżej z FlashScore albo zostało już wpisane
        # przez FotMoba w `_wzbogac_team_news`.
        ref_name = ((fixture or {}).get("fixture", {}).get("referee") or "").split(",")[0].strip()
        if ref_name:
            ref_data = _sedzia_z_bazy(ref_name, stan_bazy)
            sig = signal_from_stats(ref_data)
            k["referee_neutral"] = sig in ("NEUTRALNY", "NIEZNANY")
            k["referee_name"] = ref_name
            k["referee_signal"] = sig
            if ref_data:
                k["referee_avg_y"] = ref_data.get("avg_yellow")
                k["referee_matches"] = ref_data.get("n_matches")

        # Fallback Flashscore (jeśli brak sędziego lub dla topowych kuponów)
        # Pobieramy absencje tylko jeśli mecz jest 'ciekawy' lub jesteśmy w fazie FINAL
        szukaj_fs = not k.get("referee_name") and fs_zostalo > 0
        if not k.get("referee_name") and fs_zostalo == 0:
            log.info("FlashScore: limit %d wywolan na przebieg wyczerpany — %s vs %s "
                     "zostaje bez sedziego (Playwright kosztuje przegladarke na mecz)",
                     _MAX_FLASHSCORE_NA_PRZEBIEG, k.get("gospodarz"), k.get("goscie"))
        if szukaj_fs:
            fs_zostalo -= 1
            fs_data = _flashscore_szczegoly(k.get("gospodarz"), k.get("goscie"))
            if fs_data.get("success"):
                if not k.get("referee_name") and fs_data.get("referee"):
                    k["referee_name"] = fs_data["referee"]
                    # Jeden odczyt, dwa uzycia — sygnal liczy sie z tego samego
                    # wiersza, ktory zaraz daje `avg_yellow`.
                    ref_data = _sedzia_z_bazy(fs_data["referee"], stan_bazy)
                    k["referee_signal"] = signal_from_stats(ref_data)
                    if ref_data:
                        k["referee_avg_y"] = ref_data.get("avg_yellow")

                # Absencje Flashscore
                abs_h = [f"{a['name']} ({a['reason']})" for a in fs_data["absences"]["home"]]
                abs_a = [f"{a['name']} ({a['reason']})" for a in fs_data["absences"]["away"]]
                if abs_h: k["fs_absencje_g"] = ", ".join(abs_h)
                if abs_a: k["fs_absencje_a"] = ", ".join(abs_a)

                if fs_data.get("stadium"):
                    k["stadium"] = fs_data["stadium"]

        enriched += 1
        console.print(
            f"[dim]  {k.get('gospodarz')} vs {k.get('goscie')}: "
            f"lineup_ok={k.get('lineup_ok')} | sędzia={k.get('referee_signal', 'N/A')}[/dim]"
        )

    console.print(f"[cyan]Final enrichment: {enriched}/{len(wyniki)} kandydatów wzbogacono[/cyan]")


def _zapisz_next_final_txt(wyniki: list, katalog: Path | None = None) -> None:
    """
    Zapisuje czas uruchomienia fazy final (pierwszy mecz − 70 min) do data/next_final.txt.
    Fallback: 13:30 gdy brak danych o godzinie meczu.

    `katalog` istnieje wyłącznie dla testów. Bez niego funkcja pisała do PRAWDZIWEGO
    `data/next_final.txt` w repo, a `tests/test_next_final_parse.py` robił backup
    i przywracał plik w `finally`. Przy dwóch równoległych przebiegach pytest jeden
    proces przywracał backup, gdy drugi już czytał — asercja padała bez żadnego
    błędu w logice. Zmierzone 28.08: dwa przebiegi naraz, 2 z 3 testów tego pliku
    na czerwono; te same testy w izolacji przechodzą zawsze.
    """
    from datetime import datetime as _dt, timedelta

    DATA_DIR = Path(katalog) if katalog is not None else Path(__file__).parents[3] / "data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    czasy = []
    # (format, ile znaków wartości). Wcześniej fmt[:len(val[:16])] ucinał format
    # (np. ISO "%Y-%m-%dT%H:%M:%S"→"...%H:%M:%" z gołym %) → kickoff ISO 'T'
    # NIGDY się nie parsował → faza final spadała na fallback 13:30 (zły -70min).
    _FORMATY = (
        ("%Y-%m-%dT%H:%M:%S", 19),
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d %H:%M", 16),
        ("%H:%M", 5),
    )
    for k in wyniki:
        for pole in ("kickoff", "godzina", "datetime", "data", "time", "date"):
            val = k.get(pole)
            if val and isinstance(val, str):
                for fmt, n in _FORMATY:
                    try:
                        t = _dt.strptime(val[:n], fmt)
                        if t.hour > 0:  # ignoruj daty bez godziny
                            czasy.append(t)
                        break
                    except ValueError:
                        # CISZA CELOWA: to petla PROBUJACA formaty po kolei.
                        # Nietrafiony format to stan normalny, nie awaria — log
                        # lecialby przy kazdym meczu i zabil sygnal w reszcie pliku.
                        # Brak DOWOLNEGO dopasowania konczy sie fallbackiem 13:30 nizej.
                        continue

    if czasy:
        pierwszy = min(czasy)
        final_time = pierwszy - timedelta(minutes=70)
        txt = final_time.strftime("%H:%M")
    else:
        txt = "13:30"  # fallback: mecze popołudniowe

    out = DATA_DIR / "next_final.txt"
    out.write_text(txt, encoding="utf-8")
    console.print(f"[dim]next_final.txt → {txt} (czas startu fazy final)[/dim]")

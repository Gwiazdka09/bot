"""kalibracja_log.py — dziennik KAŻDEJ oceny modelu, nie tylko obstawialnej.

PO CO ISTNIEJE: pipeline zapisuje do `predictions` wyłącznie to, co wyprodukował
Groq — czyli dopiero PO filtrze wartości. Log produkcyjny z 2026-08-05:

    kandydaci=46 → blacklista lig → 3 → filtr EV/Kelly → 0 → zero predykcji

To nie awaria, tylko konsekwencja architektury: predykcja zapisuje się dopiero
wtedy, gdy nadaje się do OBSTAWIENIA. Kalibracja potrzebuje czegoś innego —
wszystkich przewidywań modelu wraz z wynikami, niezależnie od opłacalności.
Bez tego model nigdy się nie dowie, czy jego prawdopodobieństwa są trafne, bo
widzi wyłącznie rzadkie przypadki, które przeszły filtr.

DLACZEGO OSOBNA TABELA, a nie kolejny `kupon_type` w `predictions`:
20 zapytań w 10 modułach liczy z `predictions` skuteczność selekcji i ŻADNE nie
filtruje po `kupon_type`. Dopisanie tam wierszy kalibracyjnych zafałszowałoby
każdą z tych metryk — w tym te, na których opierają się decyzje o progach.

Rozdzielone są więc dwie rzeczy, dotąd sklejone:
  * SELEKCJA DO OBSTAWIANIA — zostaje ostra (tylko dodatnie EV);
  * TEN DZIENNIK — zapisuje wszystko, zero wpływu na kupony.
"""
from __future__ import annotations

import logging

import psycopg2

from footstats.utils.betting import oblicz_tip_correct, powod_nierozliczalny
from footstats.utils.db import connect as _connect

# Awarie, ktore dziennik ma PRZEZYC: baza (psycopg2 + RuntimeError z puli),
# dysk/siec (OSError) oraz smiec w kandydacie (ValueError/TypeError/KeyError).
_AWARIE_BAZY = (psycopg2.Error, RuntimeError, OSError)
_AWARIE_DANYCH = (ValueError, TypeError, KeyError)
# Zapis POJEDYNCZEJ oceny moze paść z obu powodow naraz: smiec w kandydacie
# albo padnieta baza w trakcie partii. Test `awaria_bazy_nie_zatrzymuje_pipeline`
# wylapal, ze sam `_AWARIE_DANYCH` przepuszcza RuntimeError z puli polaczen.
_AWARIE_ZAPISU = _AWARIE_DANYCH + _AWARIE_BAZY

log = logging.getLogger(__name__)


def init_kalibracja_log() -> None:
    """Tworzy tabelę jeśli nie istnieje. Bezpieczne przy wielokrotnym wywołaniu."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS model_log (
                id             SERIAL PRIMARY KEY,
                created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                match_date     TEXT NOT NULL,
                league         TEXT,
                team_home      TEXT NOT NULL,
                team_away      TEXT NOT NULL,
                prob_home      REAL,
                prob_draw      REAL,
                prob_away      REAL,
                prob_over25    REAL,
                prob_btts      REAL,
                lambda_h       REAL,
                lambda_a       REAL,
                model_tip      TEXT,
                actual_result  TEXT,
                tip_correct    INTEGER,
                -- Trafnosc rynkow GOLOWYCH, liczona z tego samego `actual_result`.
                -- `tip_correct` mierzy wylacznie argmax 1X2, a to wlasnie rynki
                -- golowe sa dzis glownym wyjsciem selekcji (18 z 20 kuponow z 15.08).
                -- Bez tych dwoch kolumn `prob_over25` i `prob_btts` byly zapisywane
                -- i nigdy z niczym nie porownywane.
                over25_correct INTEGER,
                btts_correct   INTEGER,
                -- Trafnosc REMISU, liczona z tego samego `actual_result`, ale
                -- NIGDY z `model_tip`. Pomiar 26.08 (n=427): "X" nie wygral
                -- argmaxu ani razu (304x "1", 123x "2"), bo `prob_draw` ma
                -- maksimum 34% i nie moze pokonac dwoch pozostalych opcji.
                -- Remis to 23.6% realnych wynikow i byl niemierzalny
                -- STRUKTURALNIE, nie przez przypadek.
                draw_correct   INTEGER,
                zrodlo         TEXT,
                -- `zrodlo` to FAZA pipeline'u (final/evening), a to jest MODEL:
                -- 'poisson-dc' albo 'bzzoiro-ml'. Bez tego dziennik miesza oceny
                -- dwoch roznych modeli w jednej krzywej kalibracyjnej, a przez
                -- brak pyarrow w obrazach prod (do 2026-08-07) dokladnie to
                -- groziloby przy pierwszym cofnieciu sie do fallbacku.
                model_source   TEXT NOT NULL DEFAULT '',
                -- Obserwacja team-news (`daily_phases._policz_edge_absencji`).
                -- CELOWO NULL, gdy korekty nie liczono: zero znaczyloby
                -- "policzone i wyszlo zero", a to dwa rozne stany. Zlanie ich
                -- wpuscilo by mecze BEZ team-news do analizy jako "korekta nic
                -- nie zmienila" i rozwodnilo caly sygnal.
                -- `prob_over25` zostaje wartoscia SPRZED korekty — dopiero para
                -- (przed, po) plus `rynek_p_over` i `over25_correct` pozwala
                -- zapytac, KTO MIAL RACJE, gdy korekta rozjechala sie z cena.
                p_over_abs            REAL,
                edge_absencje         REAL,
                rynek_p_over          REAL,
                absencje_udzial_home  REAL,
                absencje_udzial_away  REAL,
                absencje_pewne_home   INTEGER,
                absencje_pewne_away   INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_model_log_mecz
                ON model_log (team_home, team_away, match_date);
            CREATE INDEX IF NOT EXISTS idx_model_log_pending
                ON model_log (tip_correct, match_date);
        """)
        # Tabela mogla powstac przed wprowadzeniem kolumny — CREATE IF NOT EXISTS
        # jej wtedy nie doda. Osobny, idempotentny ALTER (PostgreSQL 9.6+).
        conn.execute(
            "ALTER TABLE model_log ADD COLUMN IF NOT EXISTS model_source"
            " TEXT NOT NULL DEFAULT ''"
        )
        # Ten sam powod co wyzej, tylko swiezszy: tabela zyje na produkcji od
        # tygodni (595 wierszy 24.08), wiec `CREATE IF NOT EXISTS` jej nie ruszy
        # i bez tych ALTER-ow kolumny istnialyby wylacznie w testach.
        conn.execute("ALTER TABLE model_log ADD COLUMN IF NOT EXISTS over25_correct INTEGER")
        conn.execute("ALTER TABLE model_log ADD COLUMN IF NOT EXISTS btts_correct INTEGER")
        conn.execute("ALTER TABLE model_log ADD COLUMN IF NOT EXISTS draw_correct INTEGER")
        # Obserwacja team-news. Ten sam powod co wyzej — tabela zyje na produkcji.
        for _kol, _typ in (
            ("p_over_abs", "REAL"), ("edge_absencje", "REAL"),
            ("rynek_p_over", "REAL"),
            ("absencje_udzial_home", "REAL"), ("absencje_udzial_away", "REAL"),
            ("absencje_pewne_home", "INTEGER"), ("absencje_pewne_away", "INTEGER"),
        ):
            conn.execute(
                f"ALTER TABLE model_log ADD COLUMN IF NOT EXISTS {_kol} {_typ}"
            )


def _argmax_1x2(pw: float, pr: float, pp: float) -> str:
    """Typ modelu = argmax JEGO WŁASNYCH prawdopodobieństw, nie wybór Groq.

    Dzięki temu dziennik mierzy model, a nie warstwę selekcji nad nim.
    """
    if pw >= pr and pw >= pp:
        return "1"
    return "X" if pr >= pp else "2"


def zapisz_ocene(kandydat: dict, zrodlo: str = "final") -> int | None:
    """Zapisuje jedną ocenę modelu. Zwraca id albo None gdy wiersz bezużyteczny.

    Odrzuca kandydatów bez prawdopodobieństw (nie ma czego kalibrować), bez nazw
    drużyn i bez daty (nie da się później dopasować wyniku).
    """
    home = str(kandydat.get("gospodarz") or "").strip()
    away = str(kandydat.get("goscie") or "").strip()
    data = str(kandydat.get("data") or "").strip()[:10]
    pw, pr, pp = kandydat.get("pw"), kandydat.get("pr"), kandydat.get("pp")

    if not home or not away or not data:
        return None
    if pw is None or pr is None or pp is None:
        return None

    tip = _argmax_1x2(float(pw), float(pr), float(pp))

    with _connect() as conn:
        istnieje = conn.execute(
            "SELECT id FROM model_log"
            " WHERE team_home = ? AND team_away = ? AND match_date = ? LIMIT 1",
            (home, away, data),
        ).fetchone()
        if istnieje:
            # Job final i evening oceniają ten sam mecz — bez dedupu kalibracja
            # liczyłaby go dwukrotnie i zawyżała pewność.
            return istnieje["id"]

        row = conn.execute(
            """
            INSERT INTO model_log
                (match_date, league, team_home, team_away,
                 prob_home, prob_draw, prob_away, prob_over25, prob_btts,
                 lambda_h, lambda_a, model_tip, zrodlo, model_source,
                 p_over_abs, edge_absencje, rynek_p_over,
                 absencje_udzial_home, absencje_udzial_away,
                 absencje_pewne_home, absencje_pewne_away)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?) RETURNING id
            """,
            (data, str(kandydat.get("liga") or ""), home, away,
             float(pw), float(pr), float(pp),
             kandydat.get("o25"), kandydat.get("bt"),
             kandydat.get("lambda_h"), kandydat.get("lambda_a"),
             tip, zrodlo, str(kandydat.get("model_source") or ""),
             # `.get` bez domyslki: brak klucza ma zostac NULL-em, nie zerem.
             # Zero znaczy "policzone i wyszlo zero" — inny stan niz "nie
             # liczylismy", a zlanie ich zatrulo by kazda pozniejsza analize.
             kandydat.get("p_over_abs"), kandydat.get("edge_absencje"),
             kandydat.get("rynek_p_over"),
             kandydat.get("absencje_udzial_home"),
             kandydat.get("absencje_udzial_away"),
             kandydat.get("absencje_pewne_home"),
             kandydat.get("absencje_pewne_away")),
        ).fetchone()
        return row["id"] if row else None


def zapisz_partie(kandydaci: list[dict], zrodlo: str = "final") -> int:
    """Zapisuje całą listę. Zwraca liczbę faktycznie zapisanych.

    Dziennik to OBSERWACJA, nie warunek działania — jego awaria nie może zabić
    generowania kuponów, więc wyjątek jest logowany i połykany.
    """
    if not kandydaci:
        return 0
    try:
        init_kalibracja_log()
    except _AWARIE_BAZY as e:
        log.warning("kalibracja_log: init nieudany: %s", e)
        return 0

    zapisane = 0
    for k in kandydaci:
        try:
            wiersz = zapisz_ocene(k, zrodlo)
            if wiersz is not None:
                # Znacznik do drugiej fazy (`uzupelnij_team_news`). Bez niego nie
                # da sie potem trafic w ten sam wiersz, a dopasowywanie po
                # nazwach byloby trzecim mechanizmem dopasowania w tym repo.
                k["_model_log_id"] = wiersz
                zapisane += 1
        except _AWARIE_ZAPISU as e:
            # Jeden zepsuty kandydat nie moze zablokowac zapisu pozostalych.
            log.warning("kalibracja_log: pomijam kandydata (%s): %s", k.get("gospodarz"), e)
    return zapisane


# Pola liczone przez `daily_phases._policz_edge_absencji`, czyli PO tym, jak
# `zapisz_partie` zdazyl juz wstawic wiersz. Patrz `uzupelnij_team_news`.
_POLA_TEAM_NEWS = (
    "p_over_abs", "edge_absencje", "rynek_p_over",
    "absencje_udzial_home", "absencje_udzial_away",
    "absencje_pewne_home", "absencje_pewne_away",
)


def _pola_team_news(kandydat: dict) -> dict:
    """Te z pol team-news, ktore kandydat REALNIE ma.

    Brak klucza to nie to samo co wartosc zero: zero znaczy „policzone i wyszlo
    zero", brak znaczy „nie liczylismy". Zlanie ich zatrulo by kazda pozniejsza
    analize, wiec do UPDATE-u ida wylacznie klucze obecne w slowniku.
    """
    return {p: kandydat[p] for p in _POLA_TEAM_NEWS if p in kandydat}


def uzupelnij_team_news(kandydaci: list[dict]) -> int:
    """Dopisuje do `model_log` pola policzone PO wstawieniu wiersza.

    DLACZEGO OSOBNA FAZA. `daily_agent.main()` zapisuje dziennik zanim odsieje
    kandydatow filtrami, bo `model_log` ma widziec WSZYSTKIE oceny modelu, nie
    te ~5%, ktore przetrwaja filtr wartosci. Team news liczy sie dopiero po tych
    filtrach, w `_enrichuj_finalna_faza`. Skutek zmierzony 07.09.2026 na
    produkcji: 1078 wierszy w `model_log` i ZERO z niepustym `p_over_abs`,
    mimo ze flaga `FOOTSTATS_TEAM_NEWS=1` chodzila od 05.09, a FotMob oddawal
    dane. Kolumny byly w INSERT-cie od 04.09 i nadal nie mialy szans.

    Przeniesienie INSERT-a za wzbogacenie kosztowaloby 80% dziennika, wiec
    zostaje UPDATE po id zapisanym w `zapisz_partie`.

    Zwraca liczbe zaktualizowanych wierszy. Jak caly dziennik — awaria jest
    logowana i polykana, bo to obserwacja, nie warunek dzialania.
    """
    doi = [(k["_model_log_id"], _pola_team_news(k)) for k in kandydaci
           if k.get("_model_log_id") is not None and _pola_team_news(k)]
    if not doi:
        return 0

    zmienione = 0
    try:
        with _connect() as conn:
            for wiersz_id, pola in doi:
                przypisania = ", ".join(f"{p} = ?" for p in pola)
                try:
                    conn.execute(
                        f"UPDATE model_log SET {przypisania} WHERE id = ?",  # nosec B608
                        (*pola.values(), wiersz_id),
                    )
                    zmienione += 1
                except _AWARIE_ZAPISU as e:
                    log.warning("kalibracja_log: team-news dla wiersza %s pominiete: %s",
                                wiersz_id, e)
            conn.commit()
    except _AWARIE_BAZY as e:
        log.warning("kalibracja_log: uzupelnienie team-news nieudane: %s", e)
        return 0
    return zmienione


def pobierz_nierozliczone(dni_wstecz: int = 14) -> list[dict]:
    """Oceny bez wyniku z ostatnich `dni_wstecz` dni.

    Okno szersze niż w `update_pending` (2 dni), bo dziennik nie ściga się
    z rozliczaniem kuponów — może nadrabiać zaległości spokojnie.

    Warunek na `actual_result` jest RÓWNIE WAŻNY co ten na `tip_correct`.
    Mecz rozstrzygnięty po dogrywce ma wynik, którego nie da się rozliczyć
    NIGDY (rynki 90-minutowe), więc `tip_correct` zostaje NULL na zawsze.
    Bez tego warunku taki wiersz wracał tu każdego dnia — zmierzone 28.08:
    218 wierszy (34% dziennika) w nieskończonej pętli, z zapytaniem do
    scrapera i ostrzeżeniem w logach przy każdym przebiegu.
    """
    from datetime import datetime, timedelta

    # Tabela moze jeszcze nie istniec: `init` odpala sie w `zapisz_partie`, czyli
    # w dziennym jobie, a rozliczanie bywa pierwszym, ktory tu zaglada. Bez tego
    # endpoint /cron/kalibracja-rozlicz dostawal `relation "model_log" does not
    # exist` i konczyl HTTP 500 (2026-08-06).
    init_kalibracja_log()

    granica = (datetime.now() - timedelta(days=dni_wstecz)).strftime("%Y-%m-%d")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, team_home, team_away, match_date, model_tip FROM model_log"
            " WHERE tip_correct IS NULL"
            "   AND (actual_result IS NULL OR actual_result = '')"
            "   AND match_date >= ?"
            " ORDER BY match_date",
            (granica,),
        ).fetchall()
    return [dict(r) for r in rows]


def oceny_rynkow(model_tip: str, wynik: str | None) -> dict[str, int] | None:
    """Trafność modelu na CZTERECH rynkach naraz, policzona z jednego wyniku.

    `actual_result` trzyma pełny wynik (`"3-1"`), a nie sam znak 1/X/2 — więc
    Over/Under, BTTS i remis da się z niego rozliczyć dokładnie tak samo jak
    argmax. Dziennik zapisywał `prob_over25`, `prob_btts` i `prob_draw` od
    początku i nigdy ich z niczym nie porównywał; to jest brakująca druga strona.

    REMIS LICZONY OSOBNO OD `tip_correct` — argmax 1X2 wybiera "X" tylko wtedy,
    gdy `prob_draw` jest NAJWYŻSZE z trzech, a pomiar 26.08 (n=427) pokazuje
    `prob_draw` maks. 34%: "X" nie wygrywa argmaxu praktycznie nigdy (0/427),
    mimo że remis to 23.6% realnych wyników. Bez osobnej kolumny zdanie modelu
    o co czwartym meczu nigdy nie zostałoby zweryfikowane.

    Zwraca None, gdy wyniku nie ma albo nie da się z niego uczciwie rozliczyć
    (dogrywka/karne). Wtedy wiersz zostaje w kolejce zamiast dostać zera —
    „nie wiemy" to nie to samo co „model się pomylił", i dotyczy to wszystkich
    czterech rynków naraz, nie tylko 1X2.
    """
    if not wynik:
        return None
    trafny = oblicz_tip_correct(model_tip, wynik)
    if trafny is None:
        return None
    over25 = oblicz_tip_correct("Over 2.5", wynik)
    btts = oblicz_tip_correct("BTTS", wynik)
    draw = oblicz_tip_correct("X", wynik)
    if over25 is None or btts is None or draw is None:
        # Nie powinno wystapic: skoro 1X2 dalo sie rozliczyc, wynik jest poprawny.
        # Jesli jednak — wiersz zostaje w kolejce, a my sie o tym dowiadujemy,
        # zamiast zapisac polowe prawdy i uznac mecz za zmierzony.
        log.warning("Wynik '%s' rozliczyl 1X2, ale nie rynki golowe/remis"
                    " (over25=%s, btts=%s, draw=%s)", wynik, over25, btts, draw)
        return None
    return {
        "tip_correct": trafny,
        "over25_correct": over25,
        "btts_correct": btts,
        "draw_correct": draw,
    }


def zapisz_wynik(wpis_id: int, wynik: str | None, model_tip: str) -> bool:
    """Dopisuje wynik i trafność na czterech rynkach. Zwraca True gdy zapisano.

    `model_tip` jest WYMAGANY — bez niego nie da się policzyć trafności, a cichy
    zapis samego wyniku zostawiłby wiersz, który wygląda na rozliczony i nigdy
    już nie wróci do kolejki.

    Wynik nierozliczalny NIE zapisuje trafności: „nie wiemy" to nie to samo co
    „model się pomylił", a zapis zera zafałszowałby kalibrację.
    """
    oceny = oceny_rynkow(model_tip, wynik)
    if oceny is None:
        # Rozróżniamy DWA powody, bo znaczą co innego dla kolejki:
        #   * wynik jest nierozliczalny z natury (dogrywka/karne) — to fakt
        #     o meczu, który się nie zmieni. Zapisujemy sam `actual_result`,
        #     żeby wpis przestał wracać do kolejki, ale trafności NIE liczymy;
        #   * cokolwiek innego (brak wyniku, pusty `model_tip`) — to nasz stan
        #     przejściowy albo nasz błąd. Wpis zostaje w kolejce nietknięty.
        if powod_nierozliczalny(wynik) is None:
            return False
        with _connect() as conn:
            conn.execute(
                "UPDATE model_log SET actual_result = ? WHERE id = ?",
                (wynik, wpis_id),
            )
        log.info("Wpis #%s ma wynik '%s' (%s) — nie do rozliczenia nigdy,"
                 " zdejmuje z kolejki bez oceny trafnosci",
                 wpis_id, wynik, powod_nierozliczalny(wynik))
        return False

    with _connect() as conn:
        conn.execute(
            "UPDATE model_log SET actual_result = ?, tip_correct = ?,"
            " over25_correct = ?, btts_correct = ?, draw_correct = ? WHERE id = ?",
            (wynik, oceny["tip_correct"], oceny["over25_correct"],
             oceny["btts_correct"], oceny["draw_correct"], wpis_id),
        )
    return True


def uzupelnij_rynki_golowe(dry_run: bool = True) -> dict:
    """Liczy trafność rynków golowych I remisu dla wierszy, które JUŻ mają wynik.

    Zmierzone 24.08: 388 z 595 wierszy ma `actual_result`, wszystkie mają
    `prob_over25` i `prob_btts`. Ocena rynków golowych nie wymaga ani jednego
    nowego meczu — wystarczy policzyć to, co leży w tabeli od tygodni. To jest
    powód, dla którego `BTTS_TWO_WAY` może wyjść z „brakuje danych" od razu,
    a nie za miesiąc. Ten sam argument dotyczy remisu (kolumna `draw_correct`
    dopisana 26.08) — warunek niżej musi go widzieć, inaczej 427 wierszy, które
    mają już komplet kolumn golowych, nigdy by go nie dostały.

    Domyślnie `dry_run=True`: raportuje, ilu wierszy dotknie, i nie zapisuje nic.
    """
    init_kalibracja_log()

    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, model_tip, actual_result FROM model_log"
            " WHERE actual_result IS NOT NULL"
            " AND (over25_correct IS NULL OR btts_correct IS NULL OR draw_correct IS NULL)"
        ).fetchall()

    stat = {"kandydaci": len(rows), "uzupelnione": 0, "pominiete": 0}

    for r in rows:
        oceny = oceny_rynkow(r["model_tip"] or "", r["actual_result"])
        if oceny is None:
            # Dogrywka/karne albo smieciowy zapis — zostawiamy nietkniete.
            stat["pominiete"] += 1
            continue
        stat["uzupelnione"] += 1
        if dry_run:
            continue
        with _connect() as conn:
            conn.execute(
                "UPDATE model_log SET over25_correct = ?, btts_correct = ?,"
                " draw_correct = ? WHERE id = ?",
                (oceny["over25_correct"], oceny["btts_correct"],
                 oceny["draw_correct"], r["id"]),
            )

    log.info("uzupelnij_rynki_golowe(dry_run=%s): %s", dry_run, stat)
    return stat

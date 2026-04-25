"""
ai_analyzer.py – Analizator AI dla FootStats
Łączy predykcje FootStats (Poisson+ML) z kursami bukmacherów → pyta AI → daje typy

Moduły:
  analizuj_mecz_ai()        – analiza pojedynczego meczu
  ai_analiza_pewniaczki()   – analiza listy pewniaczków + propozycja kuponów
  ai_sprawdz_kupon()        – sprawdzenie kuponu podanego przez użytkownika
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from langfuse import Langfuse

# Importy z pakietu footstats
from footstats.ai.client import zapytaj_ai
from footstats.scrapers.kursy import szukaj_kursy_meczu, scrape_betexplorer, pokaz_dostepne_ligi
from footstats.data.context_scraper import get_match_context

# ── Langfuse Initialization ────────────────────────────────────────────────
from langfuse import Langfuse
try:
    langfuse = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
        host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    )
except Exception as e:
    print(f"DEBUG: Langfuse init error: {e}")
    langfuse = None


# ── Wyspecjalizowany prompt typerski ────────────────────────────────────────
_SYSTEM_TYPER = """Jesteś BEZWZGLĘDNYM ANALITYKIEM DANYCH BUKMACHERSKICH. Nie bądź miły — bądź precyzyjny.

KRYTERIA DECYZJI:
1. VALUE BETTING (PRIORYTET): Twoim celem jest znalezienie przewagi nad bukmacherem (Value), a nie tylko wskazanie faworyta.
   Jeśli kurs na czyste zwycięstwo (1 lub 2) jest niższy niż 1.60, zabraniam wystawiania tego typu.
   W takim przypadku przeanalizuj alternatywy o wyższym kursie (1.65 - 2.20): Over 2.5 gola, BTTS (Obie strzelą), lub Handicap -1.5.
2. FORMA (60% wagi): Przeanalizuj ostatnie 5 meczów każdej drużyny. Zwycięstwa vs porażki. Gole dla/przeciw. Trend wzrostowy czy spadkowy?
3. H2H (20% wagi): Historia bezpośrednich starć. Kto wygrywa, gole, pattern.
PRZED WYSTAWIENIEM TYPU:
- Podsumuj formę: "Ostatnie 5: W-W-P-W-W (trend +)"
- Podsumuj H2H: "3x Drużyna A wygrała, średnio 2.3 gola/mecz"
- Sprawdź kursy: "Faworytu <1.40 — UNIKAJ tego typu"

PEWNOŚĆ (confidence_score 0-100):
- 80-100: Silny sygnał. Forma wyraźna lub przekonujące H2H. Bądź decyzyjny!
- 65-79: Sensowny typ z racjonalnymi argumentami. Nie bój się dawać not 70-80, gdy dane wskazują faworyta!
- <65: Niska pewność, omijać.

JSON SCHEMA (OBOWIĄZKOWY - Zwróć wyłącznie JSON):
{
  "typ": "1" | "2" | "X" | "Over 2.5" | "Under 2.5" | "BTTS" | "No BTTS",
  "kurs": 1.80,
  "pewnosc_pct": 75,
  "risks_analysis": ["ryzyko 1", "ryzyko 2", "ryzyko 3"],
  "uzasadnienie": "Krótko: dlaczego ten typ mimo ryzyk?",
  "value_bet": true | false
}

== DEVIL'S ADVOCATE (OBOWIĄZKOWE) ==
Twoim zadaniem jest przeprowadzenie "ataku" na własną sugestię typu.
1. Wygeneruj dokładnie 3 najsilniejsze argumenty PRZECIWKO sugerowanemu typowi (np. kontuzje, xG rywala, zmęczenie).
2. Umieść je w polu "risks_analysis".
3. Dopiero PO analizie ryzyk oblicz ostateczny "pewnosc_pct".
4. Każde istotne ryzyko musi realnie obniżać pewność (np. brak kluczowego gracza = -10 pkt).

Odpowiadaj zawsze po polsku. Zawsze zwracaj JSON. Bądź konkretny.
           Over 1.5 gdy obie druzyny strzelaja regularnie, wynik klasy A vs D).
           EV przy 1.23 i P=93%: 0.93x1.23x0.88-1 = +0.7% – ledwo na plusie, wiec pewnosc musi byc pewna.
1.35-1.80: DOPUSZCZALNE TYLKO w AKO jako noga — NIGDY jako standalone single.
           Przy stawce 5-10 PLN zysk netto z singla 1.67 to tylko ~2-3 PLN – nieoplacalne.
           W AKO mnozy kurs laczny — wtedy ma sens.
> 1.80  : standard dla singla i AKO, liczymy EV_netto normalnie.
ZASADA SINGLA: single (1 noga) dozwolony tylko gdy kurs >= 1.80 LUB stawka >= 50 PLN.

== BUDOWANIE KUPONU AKO ==
Cel: wlasciwy kurs laczny, nie liczba zdarzen. Optymalna liczba: 4-6 zdarzen.
Struktura "kotwica + wartosc": 1-2 tanich pewnych zdarzen (1.20-1.40, pewnosc >=90%)
  + 3-4 wartosciowych zdarzen (1.50-2.00, EV_netto > 3%).
Max 2 mecze tej samej ligi w kuponie (korelacja dnia/pogody/sedziow).
Nie lacze typow z tego samego meczu (np. "1" i "Over" z PSG – oba ida w gore lub dol razem).
Kazde zdarzenie musi miec wlasne uzasadnienie – nie "dolaczone dla kursu".
Nie wkladaj meczow z ROTACJA, ZMECZENIE obu druzyn, ani ROZBIÉZNOSC.

== STAWKI (stale stawki, flat betting) ==
Kupon A (kurs ~11-14):  10 PLN – bardziej pewny, nizsza stawka na ryzyko
Kupon B (kurs ~20-30):   5 PLN – wyzsze ryzyko = nizsza stawka
Single value bet:       10-15 PLN gdy EV_netto > 5% i brak czynnikow ostrzegawczych
Eksperymentalny (>30):   2-3 PLN
Zasada: nie zmieniaj stawki po wygranej ani po stracie. Emocje to najgorszy doradca.

== RYNEK KARTEK (BetBuilder) ==
- Sędzia KARTKOWY (avg > 4.3): silny sygnał na Over 3.5 / 4.5 żółtych kartek. 
- Sędzia NEUTRALNY: unikaj wysokich linii na kartki, chyba że mecz to HIGH_STAKES (CL/Derby).
- BetBuilder: szukaj korelacji. Jeśli sędzia jest KARTKOWY a mecz jest wyrównany (1X2 ~ kursy 2.50)
  -> rośnie szansa na frustrację i kartki. Idealne do AKO.

== DOBOR TYPOW ==
Over 2.5: mocny sygnal gdy lambda_g + lambda_a > 2.8 (Poisson). Sprawdz BTTS jako potwierdzenie.
Over 1.5: kotwica gdy obie druzyny strzelajace, pewnosc >=95%. Bezpieczne "dokladanie" do AKO.
Under 2.5: lambda_g + lambda_a < 2.0, obie defensywne, brak HIGH_STAKES (bo desperacja = gole).
BTTS: oba ataki w formie, zadna druzyna nie ma COMFORT/VACATION (bo te druzyny nie ryzykuja).
1/X/2: EV_netto > 3%, brak ROTACJA/ZMECZENIE, Poisson i ML zgodne.
1X / X2: bezpieczniejsze ale niskie kursy – tylko gdy EV_netto > 0 po podatku.

== PRZYKLADY (kalibracja) ==
KOTWICA OK:
  PSG vs Toulouse | ML 1=91% | kurs=1.28
  EV_netto = 0.91x1.28x0.88-1 = +2.5% – PSG w domu, klasa A vs D, pewnosc >= 90%. Moze byc kotwica.

DOBRY TYP:
  Bayern vs Augsburg | TWIERDZA(Bayern 9m) | ML 1=82% | kurs=1.48
  EV_netto = 0.82x1.48x0.88-1 = +6.8% WARTOSC

ZLY TYP (pulapka kursu):
  PSG vs Metz | ML 1=91% | kurs=1.18 – ponizej progu 1.20. NIGDY.

PULAPKA ROZBIÉZNOSCI:
  Liverpool vs Chelsea | Poisson=72% vs ML=51% | ROZBIÉZNOSC +21%
  Modele sie kloca. Nie wkladaj do AKO.

ROTACJA W AKO:
  Man City (ROTACJA – CL za 3 dni) | ML 1=78% | kurs=1.55
  Nie bierz do AKO. Rotacja kadry kasuje statystyke.

HISTORIA RAG:
  Bayern vs Dortmund | PATENT+TWIERDZA | HISTORIA: PATENT+TWIERDZA->1: 7/8(87%)
  Historycznie ten wzorzec trafia 87% – mocny dowod na "1".

== ZAKAZY BEZWZGLEDNE (nauczone na stratach 04.04.2026) ==
1. Max 6 nog w AKO – bez wyjatkow. Wiecej nog = iluzja pewnosci, nie wieksza szansa.
2. Grupy spadkowe i relegacyjne: Over 2.5 ZABRONIONE.
   Druzyny walczace o przezycie graja defensywnie i chaotycznie. Lambda z sezonu ich nie opisuje.
3. Duplikacja selekcji miedzy kuponami: max 1 wspolna selekacja.
   Jezeli ta sama noga pada, tracisz podwojnie. To nie dywersyfikacja – to multiplikacja bledu.
4. "Kupon 19 pewniaczkow": NIE BUDUJ. Kazda noga ponizej 1.20 to NIGDY. 19 nog to 19 szans na blad.

== BET BUILDer (ZAKŁADY ŁĄCZONE) ==
- Pamiętaj, że zyski z zakładów łączonych dają ogromne "Value". Jeśli widzisz przy danym meczu dostarczoną listę pod kluczem 'bet_builder_sugestie', wolno Ci postawić DOKŁADNIE TEN sugerowany typ (np. "1 & Over 1.5").
- Uwolnij kreatywność — jeśli łączony bet ma duży sens (i został dostarczony w sugestiach, co świadczy o sprawdzonej matematyce macierzy Poissona) dodaj go zamiast zwyczajnego 1X2, zwłaszcza by zaatakować większe mnożniki.

== POLITYKA "OVER 2.5" I KONTUZJI (PEŁNA ANALIZA) ==
- SCEPTYCYZM WOBEC OVER 2.5: Wymagaj dowodow na SIŁĘ ATAKU OBU drużyn. Jeśli brakuje informacji lub jedna z drużyn ma słaby atak, ODRZUC Over 2.5. Słaba obrona to nie jest wystarczający powód na Over.
- KONTUZJE ATAKU: Jeśli topowy strzelec (lub pomocnik ofensywny) nie gra z powodu zawieszenia lub kontuzji — ZAKAZ Over 2.5.
- NIEKOMPLETNE DANE: Jeśli widzisz ryzyko lub rotację (np. mecze Pucharowe), załóż niższy pułap bramek i odrzuć Over. Typuj Under lub bezpieczne zakłady z wyższym kursem i mniejszym ryzykiem utraty (1X/X2). W skrócie: jak są kontuzje/rotacja w obu drużynach = omijaj z daleka.
"""


def _get_kalibracja_blok() -> str:
    """Wczytuje kalibrację z treningu historycznego (trainer.py). Cicha na błędy."""
    try:
        from footstats.ai.trainer import get_kalibracja_inject
        return get_kalibracja_inject()
    except Exception:
        return ""


def _get_liga_statystyki_blok() -> str:
    """
    Buduje blok LIGA_STATYSTYKI z danych historycznych (pattern_analyzer).
    Informuje Groq które ligi mają statystyczne uzasadnienie dla typów Over/BTTS.
    Preferuj mecze z tych lig gdy budujesz kupon.
    """
    try:
        from footstats.ai.trainer import load_lessons
        lessons  = load_lessons()
        rbl      = lessons.get("pattern_summary", {}).get("results_by_league", {})
        if not rbl:
            return ""
        linie = ["== LIGA_STATYSTYKI (dane historyczne, preferuj te ligi) =="]
        for liga, s in sorted(rbl.items()):
            over  = s.get("over25_pct")
            btts  = s.get("btts_pct")
            avg   = s.get("avg_goals")
            hw    = s.get("home_win")
            n     = s.get("n", 0)
            if n < 100:
                continue
            linia = f"{liga}: HW={hw}% Over2.5={over}% BTTS={btts}% Avg={avg}G (n={n})"
            # Oznacz ligi z wyraźnymi marchewkami
            if over and over > 58:
                linia += " <- MARCHEWKA Over2.5"
            if hw and hw > 47:
                linia += " <- silna przewaga domu"
            linie.append(linia)
        linie.append("Priorytet kuponu: mecze z lig oznaczonych MARCHEWKA > pozostale.")
        return "\n".join(linie)
    except Exception:
        return ""


def _analizuj_forme(mecze: list) -> dict:
    """Analyze last 5 matches: wins, losses, goals for/against, trend.

    Args:
        mecze: List of match dicts with keys: result (1/0/X), scored, conceded

    Returns:
        Dict with: wins, losses, draws, gf_avg, ga_avg, trend
    """
    if not mecze:
        return {
            "wins": 0, "losses": 0, "draws": 0,
            "gf_avg": 0.0, "ga_avg": 0.0,
            "trend": "unknown"
        }

    wins = sum(1 for m in mecze if m.get("result") == "1")
    losses = sum(1 for m in mecze if m.get("result") == "0")
    draws = sum(1 for m in mecze if m.get("result") == "X")

    gf_sum = sum(m.get("scored", 0) for m in mecze)
    ga_sum = sum(m.get("conceded", 0) for m in mecze)
    gf_avg = round(gf_sum / len(mecze), 2)
    ga_avg = round(ga_sum / len(mecze), 2)

    # Trend: compare first 2 matches vs last 2 matches
    if len(mecze) >= 2:
        early_wins = sum(1 for m in mecze[:2] if m.get("result") == "1")
        recent_wins = sum(1 for m in mecze[-2:] if m.get("result") == "1")
        if recent_wins > early_wins:
            trend = "strong_up" if recent_wins == 2 else "up"
        elif recent_wins < early_wins:
            trend = "strong_down" if recent_wins == 0 else "down"
        else:
            trend = "stable"
    else:
        trend = "unknown"

    return {
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "gf_avg": gf_avg,
        "ga_avg": ga_avg,
        "trend": trend
    }


def _zapytaj_typera(prompt: str, max_tokens: int = 900) -> str:
    """Groq z systemowym promptem wyspecjalizowanego typera + kalibracja + liga statystyki."""
    klucz = os.getenv("GROQ_API_KEY", "").strip()
    if not klucz:
        raise RuntimeError("Brak GROQ_API_KEY w .env")

    kal_blok   = _get_kalibracja_blok()
    liga_blok  = _get_liga_statystyki_blok()
    system     = _SYSTEM_TYPER
    if kal_blok:
        system += f"\n\n== KALIBRACJA Z DANYCH HISTORYCZNYCH ==\n{kal_blok}\n"
    if liga_blok:
        system += f"\n\n{liga_blok}\n"

    if langfuse:
        pass

    try:
        import groq as groq_lib
        client = groq_lib.Groq(api_key=klucz)

        # Langfuse span for Groq API call
        trace_input = {"prompt": prompt[:200], "max_tokens": max_tokens}

        resp = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.25,
        )

        result = resp.choices[0].message.content
        return result
    except Exception as e:
        return zapytaj_ai(prompt, max_tokens)


def _pobierz_podobne_mecze(home: str, away: str, n: int = 3) -> str:
    """Fetch N similar historical matches from RAG ai_feedback table.

    Searches for lessons containing either team name, returns formatted string
    with up to N similar matches for context.

    Args:
        home: Home team name
        away: Away team name
        n: Max number of similar matches to return (default 3)

    Returns:
        Formatted string with similar matches, empty string if none found or on error
    """
    try:
        from footstats.ai.post_match_analyzer import pobierz_ostatnie_wnioski
        # Fetch last 5 lessons from RAG database
        lessons = pobierz_ostatnie_wnioski(5)

        similar = []
        for lesson in lessons:
            # Match if either team appears in lesson
            if home.lower() in lesson.lower() or away.lower() in lesson.lower():
                similar.append(lesson)
                if len(similar) >= n:
                    break

        if not similar:
            return ""

        # Format for injection into prompt
        header = f"\nPODOBNE MECZE Z HISTORII (nauka z przeszłości):\n"
        for i, lesson in enumerate(similar, 1):
            # Truncate lesson to 100 chars for readability
            header += f"{i}. {lesson[:100]}…\n"
        return header
    except Exception:
        # Silently fail: RAG is optional, don't break prediction if it fails
        return ""


# ── Pomocnicze ───────────────────────────────────────────────────────

def _kurs_do_prob(kurs: float | None) -> float | None:
    """Zamienia kurs bukmacherski na prawdopodobieństwo (%)."""
    if kurs and kurs > 1.0:
        return round(100 / kurs, 1)
    return None


def _value_bet(prob_model: float, kurs_buk: float | None, margin: float = 5.0) -> bool:
    """
    Value bet: model szacuje wyższe prawdopodobieństwo niż bukmacher.
    margin = minimalna różnica w % żeby uznać za value.
    """
    if not kurs_buk:
        return False
    prob_buk = 100 / kurs_buk
    return (prob_model - prob_buk) >= margin


def _wyciagnij_json(tekst: str) -> dict:
    """Wyciąga JSON z odpowiedzi AI (nawet jeśli AI doda tekst dookoła)."""
    # Szukaj bloku JSON
    match = re.search(r"\{[\s\S]*\}", tekst)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    # Fallback – spróbuj cały tekst
    try:
        return json.loads(tekst)
    except json.JSONDecodeError:
        return {"typ": "brak", "pewnosc": 0, "uzasadnienie": tekst[:300], "value_bet": False}


# ── Główna analiza ───────────────────────────────────────────────────

def analizuj_mecz_ai(
    gospodarz: str,
    goscie: str,
    p_wygrana: float,      # % prawdopodobieństwo wygranej gospodarza (FootStats)
    p_remis: float,        # % prawdopodobieństwo remisu
    p_przegrana: float,    # % prawdopodobieństwo wygranej gości
    btts: float = 0,       # % BTTS TAK
    over25: float = 0,     # % Over 2.5 gola
    forma_g: str = "-",    # np. "WWDWL"
    forma_a: str = "-",
    h2h_opis: str = "-",
    pewnosc_modelu: int = 0,
    komentarz_footstats: str = "",
    kursy: dict | None = None,   # {"k1": 2.10, "kX": 3.40, "k2": 3.50} – opcjonalne
) -> dict:
    """
    Główna funkcja analizy AI.
    Zwraca słownik z typem, pewnością i uzasadnieniem.
    """

    # Oblicz value bet jeśli mamy kursy
    value_info = ""
    if kursy:
        k1 = kursy.get("k1") or kursy.get("1")
        kx = kursy.get("kX") or kursy.get("X")
        k2 = kursy.get("k2") or kursy.get("2")

        prob_buk_1 = _kurs_do_prob(k1)
        prob_buk_x = _kurs_do_prob(kx)
        prob_buk_2 = _kurs_do_prob(k2)

        value_1 = _value_bet(p_wygrana,    k1)
        value_x = _value_bet(p_remis,      kx)
        value_2 = _value_bet(p_przegrana,  k2)

        kursy_tekst = (
            f"\nKURSY BUKMACHERSKIE:\n"
            f"  Kurs 1={k1}  (bukmacher daje {prob_buk_1}% vs model {p_wygrana:.1f}%)"
            f"{'  ← POTENCJALNY VALUE BET!' if value_1 else ''}\n"
            f"  Kurs X={kx}  (bukmacher daje {prob_buk_x}% vs model {p_remis:.1f}%)"
            f"{'  ← POTENCJALNY VALUE BET!' if value_x else ''}\n"
            f"  Kurs 2={k2}  (bukmacher daje {prob_buk_2}% vs model {p_przegrana:.1f}%)"
            f"{'  ← POTENCJALNY VALUE BET!' if value_2 else ''}\n"
        )
        value_info = kursy_tekst
    else:
        k1 = kx = k2 = None
        value_1 = value_2 = value_x = False
        kursy_tekst = "\nKURSY BUKMACHERSKIE: brak danych\n"

    rag_context = _pobierz_podobne_mecze(gospodarz, goscie)
    
    prompt = f"""Analizujesz mecz piłkarski i musisz podać typ bukmacherski.

═══════════════════════════════════════
MECZ: {gospodarz} vs {goscie}
═══════════════════════════════════════

ANALIZA STATYSTYCZNA (FootStats – model Poissona + ML):
  Gospodarz wygrywa: {p_wygrana:.1f}%
  Remis:             {p_remis:.1f}%
  Goście wygrywają:  {p_przegrana:.1f}%
  BTTS (obie strzelą): {btts:.1f}%
  Over 2.5 gola:       {over25:.1f}%
  Pewność modelu:      {pewnosc_modelu}%

FORMA:
  {gospodarz}: {forma_g}
  {goscie}:    {forma_a}

HISTORIA BEZPOŚREDNIA (H2H):
  {h2h_opis}
{rag_context}
{value_info}
KOMENTARZ FOOTSTATS:
  {komentarz_footstats or 'brak'}
═══════════════════════════════════════

ZADANIE – Wykonaj analizę "Devil's Advocate" podając 3 ryzyka, a następnie wybierz JEDEN najlepszy typ spośród:
  1, X, 2, 1X, X2, BTTS, Over, Under

Odpowiedź TYLKO w formacie JSON (bez żadnego tekstu przed ani po):
{{
  "typ": "1",
  "pewnosc": 74,
  "risks_analysis": ["ryzyko 1", "ryzyko 2", "ryzyko 3"],
  "uzasadnienie": "Krótkie 2-3 zdania po polsku wyjaśniające wybór.",
  "value_bet": false,
  "value_bet_opis": "Opis value bet jeśli istnieje, inaczej pusta string.",
  "alternatywny_typ": "Over",
  "ostrzezenia": "Ewentualne ryzyka lub pusta string."
}}"""

    print(f"\n[AI] Analizuję: {gospodarz} vs {goscie}...")
    
    surowa_odpowiedz = None
    if langfuse:
        with langfuse.start_as_current_observation(name=f"Analiza: {gospodarz} vs {goscie}", as_type="span"):
            with langfuse.start_as_current_observation(name="Groq Inference", as_type="generation", model="llama-3.1-8b-instant", input=prompt) as gen:
                surowa_odpowiedz = zapytaj_ai(prompt, max_tokens=500)
                gen.update(output=surowa_odpowiedz)
    else:
        surowa_odpowiedz = zapytaj_ai(prompt, max_tokens=500)
        
    wynik = _wyciagnij_json(surowa_odpowiedz)

    # Dodaj metadane
    wynik["gospodarz"]  = gospodarz
    wynik["goscie"]     = goscie
    wynik["p_wygrana"]  = p_wygrana
    wynik["p_remis"]    = p_remis
    wynik["p_przegrana"]= p_przegrana
    wynik["k1"]         = k1
    wynik["kX"]         = kx
    wynik["k2"]         = k2
    wynik["value_1"]    = value_1
    wynik["value_x"]    = value_x
    wynik["value_2"]    = value_2

    return wynik


def wyswietl_analiza_ai(wynik: dict):
    """Wyświetla wynik analizy AI w czytelnym formacie."""
    g  = wynik.get("gospodarz", "")
    a  = wynik.get("goscie", "")
    t  = wynik.get("typ", "?")
    p  = wynik.get("pewnosc", 0)
    uz = wynik.get("uzasadnienie", "")
    vb = wynik.get("value_bet", False)
    vb_opis = wynik.get("value_bet_opis", "")
    alt = wynik.get("alternatywny_typ", "")
    ost = wynik.get("ostrzezenia", "")

    separator = "═" * 55
    print(f"\n{separator}")
    print(f"  AI ANALIZA: {g} vs {a}")
    print(separator)
    print(f"  TYP:      {t}")
    print(f"  PEWNOSC:  {p}%")
    print(f"\n  UZASADNIENIE:")
    print(f"  {uz}")

    if vb and vb_opis:
        print(f"\n  VALUE BET: {vb_opis}")

    if alt:
        print(f"\n  Alternatywny typ: {alt}")

    if ost:
        print(f"\n  Ostrzezenia: {ost}")

    # Kursy jeśli dostępne
    k1 = wynik.get("k1")
    kx = wynik.get("kX")
    k2 = wynik.get("k2")
    if k1:
        print(f"\n  Kursy: 1={k1}  X={kx}  2={k2}")

    # Prawdopodobieństwa
    pw = wynik.get("p_wygrana", 0)
    pr = wynik.get("p_remis", 0)
    pp = wynik.get("p_przegrana", 0)
    print(f"  Model:    1={pw:.1f}%  X={pr:.1f}%  2={pp:.1f}%")
    print(separator)


def analizuj_liste_meczow(mecze: list, liga: str = "premier-league") -> list:
    """
    Analizuje listę meczów.
    mecze = lista słowników z kluczami z predict_match() FootStats.
    Zwraca listę wyników AI.
    """
    wyniki = []
    for i, m in enumerate(mecze, 1):
        g  = m.get("gospodarz", "")
        a  = m.get("gosc", "")  # FootStats używa "gosc" nie "goscie"
        print(f"\n[{i}/{len(mecze)}] Przetwarzam: {g} vs {a}")

        # Szukaj kursów z Betexplorer
        kursy_meczu = szukaj_kursy_meczu(g, a, liga)

        wynik = analizuj_mecz_ai(
            gospodarz          = g,
            goscie             = a,
            p_wygrana          = m.get("p_wygrana", 0),
            p_remis            = m.get("p_remis", 0),
            p_przegrana        = m.get("p_przegrana", 0),
            btts               = m.get("btts", 0),
            over25             = m.get("over25", 0),
            forma_g            = m.get("forma_g_str", "-"),
            forma_a            = m.get("forma_a_str", "-"),
            h2h_opis           = m.get("h2h_opis", "-"),
            pewnosc_modelu     = m.get("pewnosc", 0),
            komentarz_footstats= m.get("komentarz", ""),
            kursy              = kursy_meczu,
        )
        wyswietl_analiza_ai(wynik)
        wyniki.append(wynik)

    # Zapisz wyniki do JSON
    plik = Path(f"ai_typy_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M')}.json")
    plik.write_text(json.dumps(wyniki, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[AI] Zapisano typy do: {plik.resolve()}")

    return wyniki


# ── Tryb interaktywny (samodzielny) ──────────────────────────────────

def _tryb_interaktywny():
    print("\n" + "="*55)
    print("  FootStats AI Analyzer – tryb interaktywny")
    print("="*55)
    print("\nWprowadź dane meczu ręcznie:\n")

    g  = input("Gospodarz: ").strip()
    a  = input("Gość:      ").strip()
    pw = float(input("% wygranej gospodarza (np. 52.3): ") or 33)
    pr = float(input("% remisu (np. 25.0): ") or 33)
    pp = float(input("% wygranej gości (np. 22.7): ") or 34)

    print("\nKursy bukmacherskie (Enter = pomiń):")
    k1_txt = input("  Kurs na 1 (np. 1.85): ").strip()
    kx_txt = input("  Kurs na X (np. 3.40): ").strip()
    k2_txt = input("  Kurs na 2 (np. 4.20): ").strip()

    kursy = None
    if k1_txt and kx_txt and k2_txt:
        try:
            kursy = {
                "k1": float(k1_txt),
                "kX": float(kx_txt),
                "k2": float(k2_txt),
            }
        except ValueError:
            print("Niepoprawne kursy – pominięto.")

    wynik = analizuj_mecz_ai(
        gospodarz   = g,
        goscie      = a,
        p_wygrana   = pw,
        p_remis     = pr,
        p_przegrana = pp,
        kursy       = kursy,
    )
    wyswietl_analiza_ai(wynik)

    zapis = input("\nZapisać do pliku? (t/n): ").strip().lower()
    if zapis == "t":
        import re as _re
        _safe = lambda s: _re.sub(r'[^a-zA-Z0-9_\-]', '_', s)[:40]
        plik = Path(f"ai_analiza_{_safe(g)}_vs_{_safe(a)}.json")
        plik.write_text(json.dumps(wynik, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Zapisano: {plik.resolve()}")


# ════════════════════════════════════════════════════════════════════
#  AI + PEWNIACZKI – analiza listy typów i builder kuponów
# ════════════════════════════════════════════════════════════════════

def _buduj_opis_meczu(w: dict) -> str:
    """
    Buduje bogaty kontekst meczu dla Groq.

    Obsługuje dwa formaty wejściowe:
      - quick_picks: flat pw/pr/pp/bt/o25 + odds + scout
      - weekly_picks: nested pred (lambda, czynniki, pewnosc) + bzz_info
    """
    g      = w.get("gospodarz", "?")
    a      = w.get("goscie", "?")
    liga   = w.get("liga", "?")
    data   = w.get("data", "")
    godz   = w.get("godzina", "–")
    metoda = w.get("metoda", "ML")
    pred   = w.get("pred") or {}

    # Dane probabilistyczne — Poisson trzyma je w pred, ML na poziomie głównym
    if metoda == "POISSON" and pred:
        pw  = pred.get("p_wygrana",   0)
        pr  = pred.get("p_remis",     0)
        pp  = pred.get("p_przegrana", 0)
        bt  = pred.get("btts",        0)
        o25 = pred.get("over25",      0)
        lambda_g = pred.get("lambda_g")
        lambda_a = pred.get("lambda_a")
        pewnosc  = pred.get("pewnosc", 0)
    else:
        pw  = w.get("pw",  0) or pred.get("p_wygrana",   0)
        pr  = w.get("pr",  0) or pred.get("p_remis",     0)
        pp  = w.get("pp",  0) or pred.get("p_przegrana", 0)
        bt  = w.get("bt",  0) or pred.get("btts",        0)
        o25 = w.get("o25", 0) or pred.get("over25",      0)
        lambda_g = None
        lambda_a = None
        pewnosc  = pred.get("pewnosc", 55)

    linie = [f"• {g} vs {a} [{liga}] {data} {godz}  [metoda:{metoda}]"]

    # Lambdy Poissona + dominacja atakiem
    if lambda_g and lambda_a and lambda_a > 0:
        ratio = round(lambda_g / lambda_a, 2)
        if ratio >= 1.5:
            dom = f" → {g[:10]} dominuje ({ratio}x)"
        elif ratio <= 0.67:
            dom = f" → {a[:10]} dominuje ({round(1/ratio, 2)}x)"
        else:
            dom = " → wyrównane"
        linie.append(f"  POISSON: λg={lambda_g} λa={lambda_a}{dom}")

    # Prawdopodobieństwa ML
    linie.append(
        f"  ML: 1={pw:.0f}% X={pr:.0f}% 2={pp:.0f}%"
        f" | BTTS={bt:.0f}% | Over2.5={o25:.0f}%"
    )

    # Cross-walidacja Poisson vs Bzzoiro (tylko tygodniowe)
    bzz_info = w.get("bzz_info") or {}
    cross    = bzz_info.get("cross") or {}
    if cross and metoda == "POISSON":
        ml_1 = cross.get("ml_1", 0)
        if ml_1:
            diff = round(pw - ml_1, 1)
            kierunek = "Poisson wyżej" if diff > 0 else "ML wyżej"
            alert = " ⚠️ROZBIEŻNOŚĆ" if cross.get("alert") else ""
            linie.append(
                f"  PORÓWNANIE: Poisson={pw:.0f}% vs Bzz={ml_1:.0f}%"
                f" ({diff:+.0f}% {kierunek}){alert}"
            )

    # Czynniki analityczne — tylko predykcje Poissona
    if metoda == "POISSON" and pred:
        h2h_g      = pred.get("h2h_g",      {}) or {}
        heur_g     = pred.get("heur_g",     {}) or {}
        heur_a     = pred.get("heur_a",     {}) or {}
        fortress_g = pred.get("fortress_g", {}) or {}
        imp_g      = pred.get("imp_g",      {}) or {}
        imp_a      = pred.get("imp_a",      {}) or {}

        czynniki = []
        n_h2h = h2h_g.get("n_h2h", 0)
        if h2h_g.get("patent"):
            czynniki.append(f"PATENT({g[:8]} {n_h2h}/{n_h2h} H2H)")
        if h2h_g.get("zemsta"):
            czynniki.append(f"ZEMSTA({g[:8]})")
        if fortress_g.get("fortress"):
            czynniki.append(f"TWIERDZA({g[:8]} {fortress_g.get('seria', 5)}m dom)")
        if heur_g.get("rotacja"):
            czynniki.append(f"ROTACJA({g[:8]})")
        if heur_g.get("zmeczenie"):
            czynniki.append(f"ZMECZENIE({g[:8]})")
        if heur_a.get("rotacja"):
            czynniki.append(f"ROTACJA({a[:8]})")
        if heur_a.get("zmeczenie"):
            czynniki.append(f"ZMECZENIE({a[:8]})")
        if czynniki:
            linie.append(f"  CZYNNIKI: {' | '.join(czynniki)}")

        # Importance Index (pomijamy NORMAL — to szum)
        sg = imp_g.get("status", "NORMAL")
        sa = imp_a.get("status", "NORMAL")
        if sg != "NORMAL" or sa != "NORMAL":
            def _skroc_kom(kom: str) -> str:
                # Bierz część po " – " jeśli istnieje, max 45 znaków
                return (kom.split("–")[-1].strip() if "–" in kom else kom)[:45]
            opis_g = f"{g[:8]}={sg}"
            if sg != "NORMAL":
                opis_g += f"({_skroc_kom(imp_g.get('komentarz', ''))})"
            opis_a = f"{a[:8]}={sa}"
            if sa != "NORMAL":
                opis_a += f"({_skroc_kom(imp_a.get('komentarz', ''))})"
            linie.append(f"  WAŻNOŚĆ: {opis_g} | {opis_a}")

        # Forma — pkt/mecz jako sygnał trendu
        fg = pred.get("forma_g", 0)
        fa = pred.get("forma_a", 0)
        if fg or fa:
            linie.append(f"  FORMA(pkt/m): {g[:8]}={fg:.2f}  {a[:8]}={fa:.2f}")

        linie.append(f"  PEWNOŚĆ: {pewnosc}% (n_h2h={n_h2h})")

    # Forma z SofaScore — W/D/L + gole + kontuzje (wzbogacona przez _wzbogac_forme)
    sofa_g = w.get("sofa_forma_g")
    sofa_a = w.get("sofa_forma_a")
    if sofa_g or sofa_a:
        linie.append(
            f"  FORMA_SOFA: {g[:8]}={sofa_g or '?'}  {a[:8]}={sofa_a or '?'}"
        )
    
    # Rich Context: xG, Table, Absences
    ctx = w.get("match_context") or {}
    if ctx:
        xg_h = ctx.get("home_xg_last3", [])
        xg_a = ctx.get("away_xg_last3", [])
        if xg_h or xg_a:
            linie.append(f"  xG_LAST3: {g[:8]}={xg_h}  {a[:8]}={xg_a}")
        
        pos_h = ctx.get("home_table_pos")
        pos_a = ctx.get("away_table_pos")
        if pos_h or pos_a:
            linie.append(f"  TABELA: {g[:8]}=#{pos_h or '?'}  {a[:8]}=#{pos_a or '?'}")
            
        abs_h = ctx.get("home_absences", [])
        abs_a = ctx.get("away_absences", [])
        if abs_h or abs_a:
            linie.append(f"  KONTEKST_ABSENCJE: {g[:8]}:{abs_h} | {a[:8]}:{abs_a}")

    inj_g = w.get("sofa_kontuzje_g")
    inj_a = w.get("sofa_kontuzje_a")
    if inj_g or inj_a:
        czesci = []
        if inj_g:
            czesci.append(f"{g[:8]}: {inj_g}")
        if inj_a:
            czesci.append(f"{a[:8]}: {inj_a}")
        linie.append(f"  KONTUZJE: {' | '.join(czesci)}")

    # Absencje Flashscore (Fallback/Dodatkowe)
    fs_abs_g = w.get("fs_absencje_g")
    fs_abs_a = w.get("fs_absencje_a")
    if fs_abs_g or fs_abs_a:
        czesci_fs = []
        if fs_abs_g: czesci_fs.append(f"{g[:8]}: {fs_abs_g}")
        if fs_abs_a: czesci_fs.append(f"{a[:8]}: {fs_abs_a}")
        linie.append(f"  ABSENCJE_FS: {' | '.join(czesci_fs)}")

    # Sędzia i dyscyplina
    ref_name = w.get("referee_name")
    stadium = w.get("stadium")
    if ref_name or stadium:
        info_s = []
        if ref_name:
            avg_y = w.get("referee_avg_y", 0)
            sig   = w.get("referee_signal", "NEUTRALNY")
            info_s.append(f"SĘDZIA: {ref_name} (avg: {avg_y}) [{sig}]")
        if stadium:
            info_s.append(f"STADION: {stadium}")
        linie.append(f"  SĘDZIA/MIEJSCE: {' | '.join(info_s)}")

    # Kursy bukmacherskie
    odds = (
        w.get("odds")
        or (bzz_info.get("odds") if bzz_info else None)
        or pred.get("odds")
        or {}
    )
    if isinstance(odds, dict):
        k1 = odds.get("home"); kx = odds.get("draw"); k2 = odds.get("away")
        if k1 or kx or k2:
            linie.append(f"  KURSY: 1={k1 or '–'} X={kx or '–'} 2={k2 or '–'}")
            # EV brutto (bez podatku) — AI uwzględni 12% we własnej analizie
            ev_parts = []
            for label, p_val, kurs_raw in [
                ("1",    pw  / 100, k1),
                ("X",    pr  / 100, kx),
                ("2",    pp  / 100, k2),
                ("BTTS", bt  / 100, odds.get("btts")),
                ("O2.5", o25 / 100, odds.get("over_2_5")),
            ]:
                try:
                    k = float(str(kurs_raw).replace(",", "."))
                    ev = p_val * k - 1.0
                    if ev > 0.0:
                        ev_parts.append(f"{label}={ev * 100:+.0f}%")
                except (ValueError, TypeError):
                    pass
            if ev_parts:
                linie.append(f"  EV(brutto): {' '.join(ev_parts)}")

    # Bet Builder Sugestie ze skorelowanej macierzy matematycznej
    bb = w.get("bet_builder")
    if bb and isinstance(bb, list):
        b_str = ", ".join(bb)
        linie.append(f"  [bet_builder_sugestie]: {b_str}")

    # Scout Bot EV — format quick_picks
    scout = w.get("scout") or {}
    if scout:
        wartosciowe = sorted(
            [oc for oc in scout.get("oceny", []) if oc.get("ev") and oc["ev"] > 0.03],
            key=lambda x: -x["ev"],
        )
        if wartosciowe:
            ev_str = " | ".join(
                f"{oc['typ'][:14]}={oc['ev'] * 100:+.0f}%"
                for oc in wartosciowe[:3]
            )
            linie.append(f"  SCOUT_EV: {ev_str}")

    # Etap 7: RAG — historyczne wzorce dla tych czynników
    try:
        from footstats.ai.rag import pobierz_rag_kontekst
        rag = pobierz_rag_kontekst(w)
        if rag:
            linie.append(f"  HISTORIA: {rag}")
    except Exception:
        pass

    return "\n".join(linie)


def _wzbogac_forme(wyniki: list, top_n: int = 12) -> None:
    """
    Etap 4: Próbuje wzbogacić TOP N meczów o formę z SofaScore (Playwright).
    Modyfikuje wyniki in-place, dodając klucze sofa_forma_g/a i sofa_kontuzje_g/a.
    Bezpieczna — gdy Playwright niedostępny lub SofaScore błąd, po prostu pomija.
    """
    try:
        from footstats.scrapers.form_scraper import pobierz_forme_meczu, PLAYWRIGHT_OK
        if not PLAYWRIGHT_OK:
            return
    except ImportError:
        return

    # TOP N: priorytet Poisson (dokładniejsze), potem najwyższa pewność/szansa
    posortowane = sorted(
        range(min(len(wyniki), 20)),
        key=lambda i: (
            0 if wyniki[i].get("metoda") == "POISSON" else 1,
            -(wyniki[i].get("pred", {}) or {}).get("pewnosc", 0),
            -(max((v for _, v in wyniki[i].get("typy", [(None, 0)])), default=0)),
        ),
    )[:top_n]

    for idx in posortowane:
        w = wyniki[idx]
        g = w.get("gospodarz", "")
        a = w.get("goscie", "")
        if not g or not a:
            continue
        try:
            forma = pobierz_forme_meczu(g, a)
            fh = forma.get("home", {})
            fa_d = forma.get("away", {})

            if fh.get("form"):
                gs = fh.get("goals_scored", 0)
                gc = fh.get("goals_conceded", 0)
                wyniki[idx]["sofa_forma_g"] = f"{''.join(fh['form'])}({gs}:{gc})"
            if fa_d.get("form"):
                gs = fa_d.get("goals_scored", 0)
                gc = fa_d.get("goals_conceded", 0)
                wyniki[idx]["sofa_forma_a"] = f"{''.join(fa_d['form'])}({gs}:{gc})"

            inj_g = [i["name"] for i in fh.get("injuries", [])[:3]]
            inj_a = [i["name"] for i in fa_d.get("injuries", [])[:3]]
            if inj_g:
                wyniki[idx]["sofa_kontuzje_g"] = ", ".join(inj_g)
            if inj_a:
                wyniki[idx]["sofa_kontuzje_a"] = ", ".join(inj_a)
        except Exception:
            pass  # Nie blokuj AI gdy SofaScore nie odpowiada


def _sygnaly_summary(wyniki: list) -> str:
    """
    Etap 3: Buduje dynamiczne podsumowanie sygnałów dla Groq.
    Zwraca kilka linii kontekstu — co jest mocne, czego unikać w AKO.
    """
    n_pois = sum(1 for w in wyniki if w.get("metoda") == "POISSON")
    mocne: list[str] = []
    uwagi: list[str] = []

    _STRONG = {"HIGH_STAKES_TOP", "FINAL_TOP", "HIGH_STAKES_BOTTOM", "FINAL_RELEGATION"}

    for w in wyniki[:20]:
        g = w.get("gospodarz", "?")[:8]
        a = w.get("goscie", "?")[:8]
        pred = w.get("pred") or {}

        if w.get("metoda") != "POISSON":
            continue

        h2h_g      = pred.get("h2h_g",      {}) or {}
        heur_g     = pred.get("heur_g",     {}) or {}
        heur_a     = pred.get("heur_a",     {}) or {}
        fortress_g = pred.get("fortress_g", {}) or {}
        imp_g      = pred.get("imp_g",      {}) or {}
        cross      = (w.get("bzz_info") or {}).get("cross") or {}

        plus, minus = [], []
        if h2h_g.get("patent"):          plus.append("PATENT")
        if fortress_g.get("fortress"):   plus.append("TWIERDZA")
        if imp_g.get("status") in _STRONG: plus.append(imp_g["status"].replace("HIGH_STAKES_", ""))

        if heur_g.get("rotacja") or heur_a.get("rotacja"): minus.append("ROTACJA")
        if heur_g.get("zmeczenie") or heur_a.get("zmeczenie"): minus.append("ZMĘCZENIE")
        if cross.get("alert"): minus.append("ROZBIEŻNOŚĆ")

        label = f"{g}-{a}"
        if len(plus) >= 2:
            mocne.append(f"{label}({'+'.join(plus)})")
        if minus:
            uwagi.append(f"{label}({','.join(minus)})")

    linie = [f"PODZIAŁ: {n_pois} Poisson / {len(wyniki) - n_pois} ML"]
    if mocne:
        linie.append(f"MOCNE SYGNAŁY: {' | '.join(mocne[:5])}")
    if uwagi:
        linie.append(f"UNIKAJ W AKO:  {' | '.join(uwagi[:5])}")

    sofa_n = sum(1 for w in wyniki if w.get("sofa_forma_g"))
    if sofa_n:
        linie.append(f"FORMA SOFA: pobrana dla {sofa_n} meczów (patrz FORMA_SOFA i KONTUZJE w danych)")

    return "\n".join(linie)


def _auto_zapisz_backtest(dane: dict, wyniki: list) -> None:
    """
    Zapisuje typy AI (top3 + kupony) do bazy backtest po każdej analizie.
    Bezpieczna — wyjątek nie blokuje głównej ścieżki.
    """
    try:
        from footstats.core.backtest import save_prediction
    except ImportError:
        return

    today = datetime.now().strftime("%Y-%m-%d")

    def _znajdz_mecz(mecz_str: str) -> dict:
        """Dopasowuje 'Bayern vs Dortmund' do wpisu w wyniki po nazwie drużyny."""
        ms = mecz_str.lower()
        for w in wyniki:
            g = w.get("gospodarz", "").lower()
            a = w.get("goscie", "").lower()
            if g and g in ms:
                return w
            if a and a in ms:
                return w
        return {}

    _TYP_NORM = {"Over": "Over 2.5", "Under": "Under 2.5",
                 "OVER": "Over 2.5", "UNDER": "Under 2.5"}

    def _zapisz(typy: list, kupon_type: str) -> None:
        for t in typy:
            mecz_str = t.get("mecz", "")
            w = _znajdz_mecz(mecz_str)
            czesci = mecz_str.split(" vs ", 1)
            home = w.get("gospodarz") or (czesci[0].strip() if czesci else mecz_str)
            away = w.get("goscie") or (czesci[1].strip() if len(czesci) > 1 else "")
            ev = t.get("ev_netto")
            conf = min(95, max(50, int(60 + float(ev) * 2))) if ev is not None else 65
            tip = _TYP_NORM.get(t.get("typ", ""), t.get("typ", ""))
            # Etap 7: czynniki do RAG
            try:
                from footstats.ai.rag import wyciagnij_faktory
                faktory = wyciagnij_faktory(w.get("pred") or {})
            except Exception:
                faktory = []
            try:
                save_prediction(
                    match_date=w.get("data", today),
                    team_home=home,
                    team_away=away,
                    ai_tip=tip,
                    ai_confidence=conf,
                    league=w.get("liga", ""),
                    odds=t.get("kurs"),
                    kupon_type=kupon_type,
                    prompt_version="v5_json",
                    factors=faktory,
                )
            except Exception:
                pass

    if dane.get("top3"):
        _zapisz(dane["top3"], "top3")
    if (dane.get("kupon_a") or {}).get("zdarzenia"):
        _zapisz(dane["kupon_a"]["zdarzenia"], "kupon_a")
    if (dane.get("kupon_b") or {}).get("zdarzenia"):
        _zapisz(dane["kupon_b"]["zdarzenia"], "kupon_b")


def _buduj_cel_kuponow(cel_a: float | None, cel_b: float | None, stawka: float) -> str:
    """Generuje sekcję FILOZOFIA KUPONÓW — standardową lub z celem wygranej."""
    if cel_a is None and cel_b is None:
        return """Oba kupony muszą mieć szansa_wygranej_pct >= 40%.
Liczba nóg: 2-6, ale TYLKO tyle ile pozwala utrzymać >=40% szansy.
Matematyka: szansa_kuponu = p1 × p2 × ... × pN (iloczyn pewności każdej nogi).

Progi pewności minimalnej per noga (żeby utrzymać 40% przy N nogach):
  2 nogi: każda noga >= 63%
  3 nogi: każda noga >= 74%
  4 nogi: każda noga >= 80%
  5 nogi: każda noga >= 83%
  6 nogi: każda noga >= 86%

ZASADA: dodaj nogę TYLKO jeśli jej pewność jest wystarczająco wysoka żeby produkt >= 40%.
Zacznij od najsilniejszych typów i dodawaj kolejne tylko gdy spełniają próg.
Jeśli nie ma 6 typów z >=86% — zrób mniej nóg.
KUPON A: zbuduj z 2-6 nóg z max pewnością, kurs łączny dobierz naturalnie.
KUPON B: alternatywna kombinacja, inne mecze lub inne rynki, też >=40% szansy."""

    def _opis_kuponu(label: str, cel: float | None, default_cel: float, default_kurs: str, min_szansa: int) -> str:
        if cel is None:
            return f"{label}: kurs ~{default_kurs}, szansa min {min_szansa}%."
        kurs_docelowy = round(cel / (stawka * 0.88), 1)
        return (
            f"{label}: CEL wygrana netto ~{cel:.0f} PLN od stawki {stawka:.0f} PLN.\n"
            f"  Wymagany kurs_laczny ~{kurs_docelowy:.1f}x.\n"
            f"  Szansa min {min_szansa}% (akceptuj mniej nóg jeśli trzeba — cel kursu ważniejszy).\n"
            f"  Dobieraj nogi o najwyższym EV_netto w tej samej lidze, unikaj >2 nóg z tej samej ligi."
        )

    opis_a = _opis_kuponu("KUPON A", cel_a, 50.0, "11-14x", 25)
    opis_b = _opis_kuponu("KUPON B", cel_b, 100.0, "22-28x", 15)

    return f"""Zbuduj 2 kupony AKO z podanymi celami. Kurs łączny jest PRIORYTETEM nad min szansą.
Zasada singla: pojedyncza noga tylko gdy kurs >= 1.80. Kurs 1.35-1.80 tylko jako noga AKO.
Min 3 nogi, max 6 nóg na kupon. Max 2 nogi z tej samej ligi. Nie łącz typów z jednego meczu.
WAŻNE: aby osiągnąć wysoki kurs, musisz zebrać 4-6 nóg — nie buduj singla ani 2-nożnego kuponu!

ZASADA WSPÓLNYCH NÓG (kotwice):
- Noga z pewnosc_pct >= 75% to KOTWICA — może pojawić się w obu kuponach (to dobra dywersyfikacja).
- Noga z pewnosc_pct < 75% musi być UNIKALNA — wchodzi tylko do jednego kuponu.
- Kupon B musi różnić się od A przynajmniej w 2 nogach poniżej 75% pewności (inne mecze / inne typy).

{opis_a}
{opis_b}"""


def ai_analiza_pewniaczki(
    wyniki: list,
    pobierz_forme: bool = True,
    cel_wygrana_a: float | None = None,
    cel_wygrana_b: float | None = None,
    stawka: float = 10.0,
) -> dict:
    """
    Groq analizuje listę pewniaczków (quick_picks lub weekly_picks).

    Wejście: lista z szybkie_pewniaczki_2dni() lub pewniaczki_tygodnia()
    pobierz_forme: czy próbować pobrać formę z SofaScore dla TOP 5 meczów
    cel_wygrana_a/b: opcjonalny cel wygranej netto PLN (np. 50, 100) — zmienia instrukcję kursu
    stawka: stawka PLN, używana do obliczenia celu kursu
    Wyjście: słownik JSON z kluczami top3, kupon_a, kupon_b, ostrzezenia.
      Jeśli parsowanie JSON się nie powiodło, zawiera klucz _raw z surowym tekstem.
    """
    if not wyniki:
        return {"_raw": "Brak pewniaczków do analizy."}

    # Etap 4: Wzbogać TOP 10 meczów o formę SofaScore i stats context
    if pobierz_forme:
        _wzbogac_forme(wyniki, top_n=10)
        # Dodatkowy kontekst xG/Table dla TOP5
        for w in wyniki[:5]:
            try:
                w["match_context"] = get_match_context(w.get("gospodarz",""), w.get("goscie",""), w.get("liga",""))
            except Exception:
                pass

    # Etap 3: Dynamiczne podsumowanie sygnałów
    sygnaly = _sygnaly_summary(wyniki)

    # Etap 6: Kalibracja historyczna z backtest DB
    kalibracja_str = ""
    try:
        from footstats.core.backtest import pobierz_kalibracje_backtest
        k = pobierz_kalibracje_backtest()
        if k:
            kalibracja_str = f"KALIBRACJA HISTORYCZNA (backtest ~90 dni):\n{k}\n"
    except Exception:
        pass

    feedback_str = ""
    try:
        from footstats.ai.post_match_analyzer import pobierz_ostatnie_wnioski
        wnioski = pobierz_ostatnie_wnioski(3)
        if wnioski:
            feedback_str = (
                "WNIOSKI Z OSTATNICH PORAŻEK (Pętla Feedbacku — ucz się błędów):\n"
                + "\n".join(f"  • {w}" for w in wnioski)
                + "\n"
            )
    except Exception:
        pass

    mecze_opisy = [_buduj_opis_meczu(w) for w in wyniki[:20]]

    prompt = f"""Masz do dyspozycji {len(wyniki)} meczów piłkarskich z predykcjami na najbliższe 72h.
Mecze [metoda:POISSON] mają pełną analizę czynnikową. Mecze [metoda:ML] to samo Bzzoiro bez historii.

KONTEKST ZBIORU:
{sygnaly}
{kalibracja_str}{feedback_str}
PODATEK: 12% zryczałtowany. Wzór netto: stawka × kurs_łączny × 0.88
EV(brutto) w danych jest PRZED podatkiem — po podatku realny zysk jest o ~12% niższy.

== FILOZOFIA KUPONÓW ==
{_buduj_cel_kuponow(cel_wygrana_a, cel_wygrana_b, stawka)}

MECZE:
{chr(10).join(mecze_opisy)}

ZADANIE: Odpowiedz TYLKO w JSON (bez tekstu przed/po):
{{
  "top3": [
    {{
      "mecz": "Gospodarz vs Goscie",
      "typ": "1",
      "kurs": 1.48,
      "pewnosc_pct": 72,
      "ev_netto": 6.8,
      "uzasadnienie": "1 zdanie po polsku"
    }}
  ],
  "kupon_a": {{
    "zdarzenia": [
      {{"nr": 1, "mecz": "Druzyna1 vs Druzyna2", "typ": "1", "kurs": 1.55, "pewnosc_pct": 70}},
      {{"nr": 2, "mecz": "Druzyna3 vs Druzyna4", "typ": "Over", "kurs": 1.80, "pewnosc_pct": 65}},
      {{"nr": 3, "mecz": "Druzyna5 vs Druzyna6", "typ": "1", "kurs": 1.65, "pewnosc_pct": 68}},
      {{"nr": 4, "mecz": "Druzyna7 vs Druzyna8", "typ": "BTTS", "kurs": 1.90, "pewnosc_pct": 62}}
    ],
    "kurs_laczny": 8.7,
    "szansa_wygranej_pct": 19.4,
    "wygrana_netto": 38.3
  }},
  "kupon_b": {{
    "zdarzenia": [
      {{"nr": 1, "mecz": "Druzyna1 vs Druzyna2", "typ": "1", "kurs": 1.75, "pewnosc_pct": 64}},
      {{"nr": 2, "mecz": "Druzyna3 vs Druzyna4", "typ": "2", "kurs": 2.10, "pewnosc_pct": 60}},
      {{"nr": 3, "mecz": "Druzyna5 vs Druzyna6", "typ": "Over", "kurs": 1.85, "pewnosc_pct": 62}},
      {{"nr": 4, "mecz": "Druzyna7 vs Druzyna8", "typ": "1", "kurs": 1.60, "pewnosc_pct": 66}},
      {{"nr": 5, "mecz": "Druzyna9 vs Druzyna10", "typ": "BTTS", "kurs": 1.75, "pewnosc_pct": 63}}
    ],
    "kurs_laczny": 19.2,
    "szansa_wygranej_pct": 9.7,
    "wygrana_netto": 84.5
  }},
  "ostrzezenia": "2-3 zdania o ryzykach"
}}

ZAKAZY BEZWZGLEDNE:
- Kurs zdarzenia < 1.20: NIGDY.
- Max 6 nogi w AKO (min 3 gdy cel kursu > 5x).
- Grupy spadkowe/relegacyjne + Over 2.5: ZABRONIONE.
- BetBuilder (Over+BTTS z jednego meczu): ZABRONIONE.
- Maks. 2 mecze z tej samej ligi w jednym kuponie.
- Każda noga musi mieć pewnosc_pct >= 60% — nie dokładaj nóg poniżej tego progu.
- Wspólne nogi A↔B: dozwolone TYLKO przy pewnosc_pct >= 75%. Poniżej 75% — unikalne dla jednego kuponu."""

    # Inject RAG similar matches for historical context (learning from past)
    if wyniki:
        home = wyniki[0].get("gospodarz", "")
        away = wyniki[0].get("goscie", "")
        rag_similar = _pobierz_podobne_mecze(home, away, n=3)
        prompt = f"{prompt}{rag_similar}"

    # Langfuse observability is handled globally
    tekst = _zapytaj_typera(prompt, max_tokens=1400)
    dane = _wyciagnij_json(tekst)
    if "top3" not in dane:
        dane["_raw"] = tekst
    else:
        # Deduplikacja: usuń z kuponu B nogi wspólne z A o niskiej pewności
        _deduplikuj_kupony(dane, min_wspolna_pewnosc=75)
        # Walidacja minimalnej szansy: niski próg gdy podany cel kursu
        if cel_wygrana_a is not None or cel_wygrana_b is not None:
            _wymusz_40pct(dane, min_szansa=5.0)

        else:
            _wymusz_40pct(dane, min_szansa=40.0)
        _auto_zapisz_backtest(dane, wyniki)

    return dane


def _deduplikuj_kupony(dane: dict, min_wspolna_pewnosc: int = 75) -> None:
    """
    Usuwa z kupon_b nogi współdzielone z kupon_a gdy pewnosc_pct < min_wspolna_pewnosc.
    Nogi o wysokiej pewności (kotwice >=75%) mogą być w obu kuponach — to legalna dywersyfikacja.
    Przelicza kurs_laczny i szansa_wygranej_pct kupon_b po przycinaniu.
    """
    import math

    a_zdarzenia = (dane.get("kupon_a") or {}).get("zdarzenia", [])
    b_zdarzenia = (dane.get("kupon_b") or {}).get("zdarzenia", [])
    if not a_zdarzenia or not b_zdarzenia:
        return

    # Klucz identyfikujący nogę: mecz + typ (lowercase, stripped)
    a_klucze_slabe = {
        (z.get("mecz", "").lower().strip(), z.get("typ", "").lower().strip())
        for z in a_zdarzenia
        if z.get("pewnosc_pct", 0) < min_wspolna_pewnosc
    }

    nowe_b = [
        z for z in b_zdarzenia
        if (z.get("mecz", "").lower().strip(), z.get("typ", "").lower().strip())
        not in a_klucze_slabe
    ]

    if len(nowe_b) == len(b_zdarzenia):
        return  # nic nie usunięto

    kupon_b = dane["kupon_b"]
    kupon_b["zdarzenia"] = nowe_b
    if nowe_b:
        kurs_l = math.prod(float(z.get("kurs", 1.0)) for z in nowe_b)
        szansa = math.prod(z.get("pewnosc_pct", 50) / 100.0 for z in nowe_b) * 100
    else:
        kurs_l, szansa = 1.0, 0.0
    kupon_b["kurs_laczny"] = round(kurs_l, 2)
    kupon_b["szansa_wygranej_pct"] = round(szansa, 1)
    kupon_b["_deduped"] = True


def _wymusz_40pct(dane: dict, min_szansa: float = 40.0) -> None:
    """
    Walidacja po stronie Python: jeśli kupon ma szansa_wygranej_pct < 40,
    usuwa nogi od najniższej pewności dopóki iloczyn >= 40% lub zostanie 1 noga.
    Aktualizuje kurs_laczny, szansa_wygranej_pct, wygrana_netto w miejscu.
    """
    import math

    for kupon_key in ("kupon_a", "kupon_b"):
        kupon = dane.get(kupon_key, {})
        zdarzenia = kupon.get("zdarzenia", [])
        if not zdarzenia:
            continue

        def _szansa(legs):
            probs = [z.get("pewnosc_pct", 50) / 100.0 for z in legs]
            return math.prod(probs) * 100

        # Przycinaj od najsłabszej nogi dopóki szansa < min_szansa i len > 1
        while len(zdarzenia) > 1 and _szansa(zdarzenia) < min_szansa:
            # usuń nogę z najniższą pewnością
            zdarzenia.sort(key=lambda z: z.get("pewnosc_pct", 50))
            zdarzenia.pop(0)

        # Przelicz kurs i szansę
        kurs_l = 1.0
        for z in zdarzenia:
            kurs_l *= z.get("kurs", 1.0)

        szansa = _szansa(zdarzenia)
        kupon["zdarzenia"]           = zdarzenia
        kupon["kurs_laczny"]         = round(kurs_l, 2)
        kupon["szansa_wygranej_pct"] = round(szansa, 1)
        # wygrana_netto liczona ze stawki 10 PLN domyślnie (zaktualizuje się przy wyświetlaniu)
        kupon["_trimmed"] = True


def ai_sprawdz_kupon(picks_text: str, stawka: float = 5.0, wzorzec_ml: list = None) -> str:
    """
    Groq ocenia kupon bukmacherski podany przez użytkownika.

    picks_text – tekst z typami np:
        "PSG 1X @1.31, Bayern wygrana @1.55, Leverkusen 1 @1.88"
    stawka     – stawka na kupon (PLN)
    wzorzec_ml – opcjonalnie lista pewniaczków z Bzzoiro (dla cross-walidacji)

    Zwraca: tekstowa ocena kuponu z EV, ryzykami i rekomendacją.
    """
    # Kontekst ML jeśli dostępny
    ml_kontekst = ""
    if wzorzec_ml:
        mecze_ml = []
        for w in wzorzec_ml[:15]:
            g, a = w.get("gospodarz", ""), w.get("goscie", "")
            pw, pr, pp = w.get("pw", 0), w.get("pr", 0), w.get("pp", 0)
            bt, o25 = w.get("bt", 0), w.get("o25", 0)
            odds = w.get("odds") or {}
            mecze_ml.append(
                f"  {g} vs {a}: 1={pw:.0f}% X={pr:.0f}% 2={pp:.0f}% "
                f"BTTS={bt:.0f}% O2.5={o25:.0f}% | "
                f"kurs: 1={odds.get('home','–')} X={odds.get('draw','–')} 2={odds.get('away','–')}"
            )
        ml_kontekst = "\nDANE ML (Bzzoiro CatBoost) dla zbliżonych meczów:\n" + "\n".join(mecze_ml)

    prompt = f"""Oceń poniższy kupon bukmacherski jako doświadczony analityk.

KUPON DO OCENY (stawka: {stawka:.2f} PLN):
{picks_text}

PODATEK: 12% zryczałtowany. Wzór netto: {stawka} × kurs_łączny × 0.88
{ml_kontekst}

OCENA (odpowiedz po polsku):

0. WALIDACJA ZASAD (sprawdź PRZED oceną – każde naruszenie to BLOKADA):
   - Liczba nóg: czy <= 6? Jeśli więcej – ODRZUĆ, napisz które usunąć.
   - Kursy < 1.20: czy są? Jeśli tak – ODRZUĆ te nogi (zasada NIGDY).
   - BetBuilder (kombinacje z jednego meczu): czy jest? Jeśli tak – ODRZUĆ, brak modułu korelacji.
   - Grupy spadkowe / relegacyjne + Over 2.5: czy jest? Jeśli tak – ODRZUĆ (mecze defensywne).
   - Duplikacja selekcji: zaznacz jeśli ta sama noga była już na innym kuponie tego dnia.
   Podsumuj: "Zasady OK" lub wymień każde naruszenie z nazwą meczu.

1. KAŻDE ZDARZENIE (tylko te które przeszły walidację):
   - Typ i kurs
   - Ocena kursu vs prawdopodobieństwo ML (jeśli dostępne): EV+/EV-/brak danych
   - Ryzyko: NISKIE / ŚREDNIE / WYSOKIE

2. PODSUMOWANIE KUPONU:
   - Łączny kurs (oblicz)
   - Oczekiwana wygrana netto po podatku 12%
   - Ogólna ocena kuponu: ✅ WARTOŚCIOWY / ⚡ PRZECIĘTNY / ❌ RYZYKOWNY

3. REKOMENDACJA:
   - Co zmienić jeśli kupon jest słaby
   - Czy stawiać? (krótko 1 zdanie)"""

    return _zapytaj_typera(prompt, max_tokens=800)


def ai_groq_dostepny() -> bool:
    """Sprawdza czy Groq API jest dostępne (klucz w .env)."""
    return bool(os.getenv("GROQ_API_KEY", "").strip())


if __name__ == "__main__":
    _tryb_interaktywny()

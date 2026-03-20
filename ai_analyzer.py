"""
ai_analyzer.py – Analizator AI dla FootStats
Łączy predykcje FootStats (Poisson+ML) z kursami bukmacherów → pyta AI → daje typy
Umieść w F:\\bot\\ai_analyzer.py

Użycie samodzielne:
    python ai_analyzer.py

Użycie z FootStats – dodaj opcję "ai" w menu footstats.py (patrz koniec pliku)
"""

import json
import re
import sys
from pathlib import Path

# Importy z tego samego folderu
try:
    from ai_client import zapytaj_ai
    from scraper_kursy import szukaj_kursy_meczu, scrape_betexplorer, pokaz_dostepne_ligi
except ImportError as e:
    print(f"BŁĄD importu: {e}")
    print("Upewnij się że ai_client.py i scraper_kursy.py są w tym samym folderze.")
    sys.exit(1)


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
{value_info}
KOMENTARZ FOOTSTATS:
  {komentarz_footstats or 'brak'}
═══════════════════════════════════════

ZADANIE – oceń mecz i wybierz JEDEN najlepszy typ spośród:
  1     – wygrana gospodarza
  X     – remis
  2     – wygrana gości
  1X    – gospodarz lub remis
  X2    – remis lub goście
  BTTS  – obie drużyny strzelą
  Over  – ponad 2.5 gola
  Under – poniżej 2.5 gola

Odpowiedź TYLKO w formacie JSON (bez żadnego tekstu przed ani po):
{{
  "typ": "1",
  "pewnosc": 74,
  "uzasadnienie": "Krótkie 2-3 zdania po polsku wyjaśniające wybór.",
  "value_bet": false,
  "value_bet_opis": "Opis value bet jeśli istnieje, inaczej pusta string.",
  "alternatywny_typ": "Over",
  "ostrzezenia": "Ewentualne ryzyka lub pusta string."
}}"""

    print(f"\n[AI] Analizuję: {gospodarz} vs {goscie}...")
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
    print(f"  🤖 ANALIZA AI: {g} vs {a}")
    print(separator)
    print(f"  TYP:      {t}")
    print(f"  PEWNOŚĆ:  {p}%  {'🟢' if p >= 70 else '🟡' if p >= 55 else '🔴'}")
    print(f"\n  UZASADNIENIE:")
    print(f"  {uz}")

    if vb and vb_opis:
        print(f"\n  💰 VALUE BET: {vb_opis}")

    if alt:
        print(f"\n  Alternatywny typ: {alt}")

    if ost:
        print(f"\n  ⚠️  Ostrzeżenia: {ost}")

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
    print("\n" + "═"*55)
    print("  🤖 FootStats AI Analyzer – tryb interaktywny")
    print("═"*55)
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


if __name__ == "__main__":
    _tryb_interaktywny()

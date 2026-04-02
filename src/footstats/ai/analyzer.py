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
from pathlib import Path

# Importy z pakietu footstats
from footstats.ai.client import zapytaj_ai
from footstats.scrapers.kursy import szukaj_kursy_meczu, scrape_betexplorer, pokaz_dostepne_ligi


# ── Wyspecjalizowany prompt typerski ────────────────────────────────────────
_SYSTEM_TYPER = (
    "Jesteś doświadczonym analitykiem bukmacherskim z 10-letnim stażem. "
    "Specjalizujesz się w typowaniu piłkarskim na rynku polskim. "
    "Zawsze odpowiadasz po polsku. Znasz podatek 12% zryczałtowany (netto = stawka × kurs × 0.88). "
    "Analizujesz EV (Expected Value), formy drużyn i dane ML. "
    "Jesteś sceptyczny wobec kuponów z >5 zdarzeniami – ryzyko rośnie wykładniczo. "
    "Preferujesz value bety (EV>0) nad bezrefleksyjnymi faworytami z niskim kursem. "
    "Jeśli prosisz o JSON – zwracasz TYLKO JSON, bez żadnego tekstu przed ani po."
)


def _zapytaj_typera(prompt: str, max_tokens: int = 900) -> str:
    """Groq z systemowym promptem wyspecjalizowanego typerа."""
    klucz = os.getenv("GROQ_API_KEY", "").strip()
    if not klucz:
        raise RuntimeError("Brak GROQ_API_KEY w .env")
    try:
        import groq as groq_lib
        client = groq_lib.Groq(api_key=klucz)
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _SYSTEM_TYPER},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.25,
        )
        return resp.choices[0].message.content
    except Exception as e:
        # Fallback na standardowego zapytaj_ai
        return zapytaj_ai(prompt, max_tokens)


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

def ai_analiza_pewniaczki(wyniki: list) -> str:
    """
    Groq analizuje listę pewniaczków z Bzzoiro ML.

    Wejście: lista zwrócona przez szybkie_pewniaczki_2dni()
    Wyjście: sformatowany tekst z:
      - TOP 3 najlepszymi typami (EV + pewność)
      - Propozycją kuponu ~50 PLN netto (5 PLN stawka)
      - Propozycją kuponu ~100 PLN netto (5 PLN stawka)
      - Głównymi ryzykami
    """
    if not wyniki:
        return "Brak pewniaczków do analizy."

    # Zbuduj kompaktowy opis każdego meczu
    mecze_opisy = []
    for w in wyniki[:20]:
        g    = w.get("gospodarz", "?")
        a    = w.get("goscie", "?")
        liga = w.get("liga", "?")
        pw, pr, pp = w.get("pw", 0), w.get("pr", 0), w.get("pp", 0)
        bt, o25    = w.get("bt", 0), w.get("o25", 0)
        data  = w.get("data", "")
        godz  = w.get("godzina", "")

        # Typy z EV
        scout = w.get("scout", {})
        oceny = {o["typ"]: o for o in scout.get("oceny", [])}
        typy_str = []
        for typ_opis, szansa in w.get("typy", []):
            oc = oceny.get(typ_opis, {})
            ev = oc.get("ev")
            kurs = oc.get("kurs", "–")
            ev_txt = f"EV={ev*100:+.0f}%" if ev is not None else ""
            typy_str.append(f"{typ_opis} ({szansa:.0f}% kurs={kurs} {ev_txt})")

        odds = w.get("odds") or {}
        k1 = odds.get("home", "–")
        kx = odds.get("draw", "–")
        k2 = odds.get("away", "–")

        mecze_opisy.append(
            f"• [{data} {godz}] {g} vs {a} [{liga}]\n"
            f"  ML: 1={pw:.0f}% X={pr:.0f}% 2={pp:.0f}% BTTS={bt:.0f}% O2.5={o25:.0f}%\n"
            f"  Kursy: 1={k1} X={kx} 2={k2}\n"
            f"  Typy: {' | '.join(typy_str)}"
        )

    prompt = f"""Masz do dyspozycji {len(wyniki)} meczów piłkarskich z predykcjami ML (CatBoost Bzzoiro) na najbliższe 48h.

PODATEK: 12% zryczałtowany. Wzór netto: stawka × kurs_łączny × 0.88
CELE KUPONÓW: 5 PLN stawka → KUPON A: cel ~50 PLN netto (kurs_łączny ≈ 11.4) | KUPON B: cel ~100 PLN netto (kurs_łączny ≈ 22.7)

MECZE:
{chr(10).join(mecze_opisy)}

ZADANIE (odpowiedz po polsku, konkretnie):

1. TOP 3 POJEDYNCZE TYPY – wybierz 3 typy z najwyższym EV i pewnością ML. Dla każdego: mecz, typ, kurs, uzasadnienie (1 zdanie).

2. KUPON A (~50 PLN netto, stawka 5 PLN):
   - Wybierz 4-5 zdarzeń (różne mecze!) z łącznym kursem ~11-12
   - Format: NR. Mecz | typ | kurs | pewność ML
   - Kurs łączny i oczekiwana wygrana netto
   - Uzasadnienie (2-3 zdania)

3. KUPON B (~100 PLN netto, stawka 5 PLN):
   - Wybierz 5-6 zdarzeń z łącznym kursem ~22-24
   - Format: NR. Mecz | typ | kurs | pewność ML
   - Kurs łączny i oczekiwana wygrana netto
   - Uzasadnienie (2-3 zdania)

4. RYZYKA – wymień 2-3 główne ryzyka dla tych kuponów.

WAŻNE: Nie bierz kursów poniżej 1.30 do kuponów AKO (ryzyko nieadekwatne do wartości). Preferuj typy z EV>0."""

    return _zapytaj_typera(prompt, max_tokens=1000)


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

1. KAŻDE ZDARZENIE:
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

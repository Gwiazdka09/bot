"""
trainer.py – Groq "marchewka i kij": uczy się z danych historycznych.

Jak działa:
  1. Pobiera analizę wzorców z pattern_analyzer.py
  2. Formatuje statystyki jako kontekst dla Groq
  3. Groq analizuje co NAPRAWDĘ działa (marchewki) vs co to mity (kije)
  4. Generuje zaktualizowane zasady kuponów + kalibrację do promptu
  5. Zapisuje lessons do data/groq_lessons.json

Użycie:
    python -m footstats.ai.trainer               # pełny trening
    python -m footstats.ai.trainer --show        # pokaż ostatnie lekcje
    python -m footstats.ai.trainer --inject      # pokaż blok do wklejenia w prompt
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import os
from dotenv import load_dotenv
load_dotenv()
try:
    from groq import Groq as _GroqSDK
    _HAS_GROQ_SDK = True
except ImportError:
    _HAS_GROQ_SDK = False
from footstats.core.pattern_analyzer import analyze_all, format_report
from footstats.data.historical_loader import download_all, load_cached

log = logging.getLogger(__name__)

LESSONS_FILE = Path(__file__).parents[3] / "data" / "groq_lessons.json"

SYSTEM_TRAINER = """Jesteś ekspertem od analizy statystycznej zakładów sportowych.
Analizujesz dane historyczne z dziesiątek tysięcy meczów piłkarskich.
Twoim zadaniem jest wyciąganie KONKRETNYCH, MIERZALNYCH wniosków które pomogą ulepszyć system typowania.

Zasady:
- Podawaj liczby. Nie puste slogany.
- Odróżniaj korelację od przyczynowości.
- Wskazuj zarówno co DZIAŁA (marchewki) jak i co to MITY/PUŁAPKI (kije).
- Skup się na tym co zmienia EV (Expected Value) gracza.
- Bądź sceptyczny wobec małych próbek (n < 100).
- Format odpowiedzi: JSON."""

PROMPT_TRAINER = """Poniżej masz raport statystyczny z analizy {n_matches:,} historycznych meczów piłkarskich.

{report}

Na podstawie tych danych odpowiedz w formacie JSON:

{{
  "marchewki": [
    {{
      "regula": "treść reguły (co robić)",
      "uzasadnienie": "dlaczego statystyki to potwierdzają",
      "sila": "mocna/srednia/slaba",
      "rynki": ["1", "Over 2.5", ...]
    }}
  ],
  "kije": [
    {{
      "mit": "opis mitu do obalenia",
      "dowod": "statystyki które to obalają",
      "uwaga": "co zamiast tego"
    }}
  ],
  "kalibracja_per_rynek": {{
    "1":       {{"korekta_pewnosci": 0, "komentarz": "..."}},
    "X":       {{"korekta_pewnosci": 0, "komentarz": "..."}},
    "2":       {{"korekta_pewnosci": 0, "komentarz": "..."}},
    "Over 2.5": {{"korekta_pewnosci": 0, "komentarz": "..."}},
    "BTTS":    {{"korekta_pewnosci": 0, "komentarz": "..."}}
  }},
  "nowe_zasady_kuponow": [
    "Zasada 1: ...",
    "Zasada 2: ..."
  ],
  "ostrzezenia": [
    "Liga X: uważaj bo..."
  ],
  "kalibracja_summary": "jeden akapit do wklejenia w system prompt Groq"
}}

korekta_pewnosci: wartość od -15 do +15 (procent do dodania/odjęcia od confidence AI gdy typuje ten rynek)
"""


# ─────────────────────────── load/save lessons ────────────────────────────

def load_lessons() -> dict:
    if LESSONS_FILE.exists():
        try:
            return json.loads(LESSONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_lessons(lessons: dict) -> None:
    LESSONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LESSONS_FILE.write_text(
        json.dumps(lessons, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[Trainer] Zapisano lekcje -> {LESSONS_FILE}")


# ─────────────────────────── wywołanie Groq ───────────────────────────────

def ask_groq_trainer(report_text: str, n_matches: int) -> dict | None:
    import requests as _req

    prompt = PROMPT_TRAINER.format(report=report_text, n_matches=n_matches)
    klucz = os.getenv("GROQ_API_KEY", "").strip()

    if _HAS_GROQ_SDK and klucz:
        client = _GroqSDK(api_key=klucz)
        try:
            resp = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": SYSTEM_TRAINER},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.3,
                max_tokens=3000,
            )
            raw = resp.choices[0].message.content.strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log.warning("Groq SDK JSON error: %s", e)
            return None
        except Exception as e:
            log.error("Groq SDK error: %s", e)
            return None

    # Fallback: raw HTTP (jak w client.py)
    if not klucz:
        log.error("Brak GROQ_API_KEY w .env")
        return None

    try:
        r = _req.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {klucz}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {"role": "system", "content": SYSTEM_TRAINER},
                    {"role": "user",   "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 3000,
            },
            timeout=60,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("Groq HTTP JSON error: %s", e)
        return None
    except Exception as e:
        log.error("Groq HTTP error: %s", e)
        return None


# ─────────────────────────── główna funkcja treningu ─────────────────────

def train(
    league_filter: list[str] | None = None,
    force_download: bool = False,
) -> dict | None:
    """
    Pełny cykl treningu:
    1. Pobierz/wczytaj dane historyczne
    2. Analiza wzorców
    3. Groq wyciąga marchewki i kije
    4. Zapisz lessons
    """
    print("\n" + "=" * 60)
    print("  FOOTSTATS GROQ TRAINER – marchewka i kij")
    print("=" * 60)

    # 1. Dane
    if force_download:
        df = download_all()
    else:
        try:
            df = load_cached()
            print(f"[Trainer] Wczytano cache: {len(df):,} meczów")
        except FileNotFoundError:
            print("[Trainer] Brak cache — pobieram dane...")
            df = download_all()

    if df.empty:
        print("[Trainer] BŁĄD: brak danych historycznych!")
        return None

    if league_filter:
        df = df[df["league"].isin(league_filter)]
        print(f"[Trainer] Filtr lig: {league_filter} → {len(df):,} meczów")

    # 2. Analiza
    analysis = analyze_all(df, league_filter=league_filter)
    report   = format_report(analysis)
    print("\n" + report)

    # 3. Groq
    print("\n[Trainer] Wysyłam raport do Groq (marchewka/kij)...")
    lessons_raw = ask_groq_trainer(report, len(df))

    if lessons_raw is None:
        print("[Trainer] Groq nie odpowiedział poprawnie.")
        return None

    # 4. Zapisz
    lessons = {
        "updated_at":      datetime.now().isoformat(),
        "n_matches":       len(df),
        "leagues":         analysis.get("leagues", []),
        "date_range":      analysis.get("date_range", []),
        "groq_lessons":    lessons_raw,
        "pattern_summary": {
            "results_by_league": analysis.get("results_by_league", {}),
            "form_vs_result":    analysis.get("form_vs_result", {}),
            "goals_dist":        analysis.get("goals_distribution", {}),
            "marchewki_raw":     analysis.get("marchewki_i_kije", {}),
        },
    }
    save_lessons(lessons)

    # Pokaż wyniki
    _print_lessons(lessons_raw)
    return lessons


# ─────────────────────────── wyświetlanie lekcji ──────────────────────────

def _print_lessons(lessons: dict) -> None:
    print("\n" + "=" * 60)
    print("  WYNIKI TRENINGU GROQ")
    print("=" * 60)

    marchewki = lessons.get("marchewki", [])
    kije      = lessons.get("kije", [])

    if marchewki:
        print(f"\n  MARCHEWKI ({len(marchewki)}) – co wzmocnić:")
        for i, m in enumerate(marchewki, 1):
            sila = m.get("sila", "?")
            print(f"\n  {i}. [{sila.upper()}] {m.get('regula', '?')}")
            print(f"     Uzasadnienie: {m.get('uzasadnienie', '?')}")
            rynki = m.get("rynki", [])
            if rynki:
                print(f"     Rynki: {', '.join(rynki)}")

    if kije:
        print(f"\n  KIJE ({len(kije)}) – mity do obalenia:")
        for i, k in enumerate(kije, 1):
            print(f"\n  {i}. MIT: {k.get('mit', '?')}")
            print(f"     Dowód: {k.get('dowod', '?')}")
            print(f"     Zamiast: {k.get('uwaga', '?')}")

    kalibracja = lessons.get("kalibracja_per_rynek", {})
    if kalibracja:
        print("\n  KALIBRACJA RYNKÓW:")
        for rynek, kal in kalibracja.items():
            kor = kal.get("korekta_pewnosci", 0)
            sign = "+" if kor >= 0 else ""
            print(f"    {rynek:<12}: {sign}{kor:+d}%  {kal.get('komentarz', '')}")

    nowe_zasady = lessons.get("nowe_zasady_kuponow", [])
    if nowe_zasady:
        print("\n  NOWE ZASADY KUPONÓW:")
        for z in nowe_zasady:
            print(f"    • {z}")

    summary = lessons.get("kalibracja_summary", "")
    if summary:
        print(f"\n  BLOK DO PROMPTU GROQ:\n  {'─'*50}")
        print(f"  {summary}")
        print(f"  {'─'*50}")


def get_kalibracja_inject() -> str:
    """
    Zwraca blok kalibracji z ostatniego treningu do wstrzyknięcia w prompt Groq.
    Używane przez analyzer.py.
    """
    lessons = load_lessons()
    groq_l  = lessons.get("groq_lessons", {})
    summary = groq_l.get("kalibracja_summary", "")
    if not summary:
        return ""

    updated = lessons.get("updated_at", "?")[:10]
    lines   = [f"KALIBRACJA HISTORYCZNA ({updated}, n={lessons.get('n_matches', 0):,}):"]
    lines.append(summary)

    # Dodaj korektę pewności per rynek
    kal = groq_l.get("kalibracja_per_rynek", {})
    if kal:
        parts = []
        for rynek, v in kal.items():
            kor = v.get("korekta_pewnosci", 0)
            if kor != 0:
                parts.append(f"{rynek}:{kor:+d}%")
        if parts:
            lines.append(f"Korekty: {' | '.join(parts)}")

    return "\n".join(lines)


# ─────────────────────────── CLI ──────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="FootStats Groq Trainer")
    parser.add_argument("--show",    action="store_true", help="Pokaż ostatnie lekcje")
    parser.add_argument("--inject",  action="store_true", help="Pokaż blok do promptu")
    parser.add_argument("--download", action="store_true", help="Wymuś pobranie danych")
    parser.add_argument("--leagues", nargs="+", help="Filtruj ligi", default=None)
    args = parser.parse_args()

    if args.show:
        lessons = load_lessons()
        if not lessons:
            print("Brak zapisanych lekcji. Uruchom bez --show żeby wytrenować.")
        else:
            print(f"Ostatni trening: {lessons.get('updated_at', '?')}")
            print(f"Meczów: {lessons.get('n_matches', 0):,}")
            _print_lessons(lessons.get("groq_lessons", {}))
        sys.exit(0)

    if args.inject:
        blok = get_kalibracja_inject()
        if blok:
            print("\n--- WKLEJ DO PROMPTU ---")
            print(blok)
            print("--- KONIEC ---")
        else:
            print("Brak kalibracji. Uruchom trening pierwszy.")
        sys.exit(0)

    train(league_filter=args.leagues, force_download=args.download)

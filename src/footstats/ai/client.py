"""
ai_client.py – Klient AI dla FootStats
Priorytet: Groq (online, darmowy, 70B) → Ollama (lokalny, offline, 2B)
"""

import os
import requests
from dotenv import load_dotenv
from footstats.utils.console import console

load_dotenv()

GROQ_MODEL   = "llama-3.3-70b-versatile"
OLLAMA_MODEL = "gemma2:2b"
OLLAMA_URL   = "http://localhost:11434/api/generate"


def _groq(prompt: str, max_tokens: int = 600) -> str | None:
    """Odpytuje Groq API. Zwraca tekst lub None jeśli błąd."""
    klucz = os.getenv("GROQ_API_KEY", "").strip()
    if not klucz:
        return None
    try:
        import groq as groq_lib
        client = groq_lib.Groq(api_key=klucz)
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Jesteś ekspertem analitykiem piłkarskim. "
                        "Odpowiadasz zawsze po polsku. "
                        "Jeśli prosisz o JSON – zwracasz TYLKO JSON, bez żadnego tekstu przed ani po."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return resp.choices[0].message.content
    except Exception as e:
        print(f"[AI] Groq błąd: {e}")
        return None


def _ollama(prompt: str) -> str | None:
    """Odpytuje lokalną Ollamę. Zwraca tekst lub None jeśli błąd."""
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        r.raise_for_status()
        return r.json().get("response", "")
    except Exception as e:
        print(f"[AI] Ollama błąd: {e}")
        return None


def zapytaj_ai(prompt: str, max_tokens: int = 600) -> str:
    """
    Główna funkcja. Najpierw próbuje Groq, potem Ollama.
    Rzuca RuntimeError jeśli oba zawodzą.
    """
    odpowiedz = _groq(prompt, max_tokens)
    if odpowiedz:
        print("[AI] Źródło: Groq (llama-3.3-70b)")
        return odpowiedz

    odpowiedz = _ollama(prompt)
    if odpowiedz:
        print("[AI] Źródło: Ollama (gemma2:2b lokalnie)")
        return odpowiedz

    raise RuntimeError(
        "Brak dostępnego AI. Sprawdź:\n"
        "  1. Klucz GROQ_API_KEY w pliku .env\n"
        "  2. Czy Ollama działa: ollama serve\n"
        "  3. Czy model pobrany: ollama pull gemma2:2b"
    )


# ── Szybki test ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Test AI client...")
    try:
        odp = zapytaj_ai("Napisz jedno zdanie po polsku o piłce nożnej.", max_tokens=100)
        print(f"Odpowiedź: {odp}")
    except RuntimeError as e:
        print(f"BŁĄD: {e}")

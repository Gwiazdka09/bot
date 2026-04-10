"""
telegram_notify.py – wysyłanie kuponów FootStats na Telegram.

Konfiguracja w .env:
    TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
    TELEGRAM_CHAT_ID=-1001234567890   (lub Twoje user ID)

Jak uzyskać:
    1. Stwórz bota przez @BotFather → /newbot → skopiuj token
    2. Wyślij /start do swojego bota
    3. Wejdź na: https://api.telegram.org/bot<TOKEN>/getUpdates
       i skopiuj "chat":{"id": ...}

Użycie:
    from footstats.utils.telegram_notify import send_kupon, telegram_dostepny
    if telegram_dostepny():
        send_kupon(dane_kuponu, stawka_a=10, stawka_b=5)
"""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def _get_credentials() -> tuple[str, str]:
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    return token, chat_id


def telegram_dostepny() -> bool:
    """Zwraca True jeśli TELEGRAM_BOT_TOKEN i TELEGRAM_CHAT_ID są w .env."""
    token, chat_id = _get_credentials()
    return bool(token and chat_id)


def _send(text: str, parse_mode: str = "HTML") -> bool:
    """Wysyła wiadomość na Telegram. Zwraca True jeśli sukces."""
    token, chat_id = _get_credentials()
    if not token or not chat_id:
        return False
    try:
        r = requests.post(
            TELEGRAM_API.format(token=token, method="sendMessage"),
            json={
                "chat_id":    chat_id,
                "text":       text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        return r.ok
    except Exception:
        return False


def _format_zdarzenia(zdarzenia: list[dict]) -> str:
    linie = []
    for z in zdarzenia:
        verified = "✓" if z.get("_verified") else "?"
        linie.append(
            f"  {z.get('nr', '')}. {z.get('mecz', '?')} "
            f"<b>{z.get('typ', '?')}</b> @{z.get('kurs', 0):.2f} {verified}"
        )
    return "\n".join(linie)


def send_kupon(dane: dict, stawka_a: float = 10.0, stawka_b: float = 5.0) -> bool:
    """
    Formatuje i wysyła kupon na Telegram.
    dane – słownik z kluczami: kupon_a, kupon_b, top3, ostrzezenia
    """
    dzis   = datetime.now().strftime("%d.%m.%Y %H:%M")
    linie  = [f"<b>FootStats {dzis}</b>"]

    for label, kupon_key, stawka in [
        ("KUPON A", "kupon_a", stawka_a),
        ("KUPON B", "kupon_b", stawka_b),
    ]:
        kupon     = dane.get(kupon_key, {})
        zdarzenia = kupon.get("zdarzenia", [])
        if not zdarzenia:
            continue

        kurs_l  = kupon.get("kurs_laczny", 0) or 0
        wyg     = stawka * kurs_l * 0.88
        szansa  = kupon.get("szansa_wygranej_pct")
        n_nog   = len(zdarzenia)

        szansa_str = f" | szansa {szansa}%" if szansa else ""
        linie.append(
            f"\n<b>{label}</b> ({n_nog} {'noga' if n_nog==1 else 'nogi' if n_nog<=4 else 'nog'}"
            f", stawka {stawka:.0f} PLN{szansa_str})"
        )
        linie.append(_format_zdarzenia(zdarzenia))
        linie.append(
            f"  Kurs: <b>{kurs_l:.2f}</b> | Wygrana: <b>{wyg:.2f} PLN</b>"
        )

    top3 = dane.get("top3", [])
    if top3:
        linie.append("\n<b>TOP 3 typy:</b>")
        for row in top3[:3]:
            ev = row.get("ev_netto", 0) or 0
            linie.append(
                f"  • {row.get('mecz','?')} <b>{row.get('typ','?')}</b> "
                f"@{row.get('kurs',0):.2f} EV={ev:+.1f}%"
            )

    if dane.get("ostrzezenia"):
        linie.append(f"\n⚠️ {dane['ostrzezenia']}")

    msg = "\n".join(linie)
    ok  = _send(msg)
    return ok


def send_wynik_update(match_id: int, mecz: str, ai_tip: str,
                      actual_result: str, tip_correct: int | None) -> bool:
    """Powiadomienie o wpisaniu wyniku do backtestu."""
    status = {1: "TRAFIONY ✅", 0: "PUDLO ❌", None: "? (nieznany)"}[tip_correct]
    msg = (
        f"<b>FootStats – wynik meczu</b>\n"
        f"{mecz}\n"
        f"Typ AI: <b>{ai_tip}</b>\n"
        f"Wynik: {actual_result} → {status}"
    )
    return _send(msg)


def send_draft_kupon(coupon_id: int, legs: list[dict], total_odds: float) -> bool:
    """
    Powiadomienie o zapisie kuponu DRAFT — alert że kandydaci są zaplanowani.
    Wysyłany po fazie draft, przed finalem.
    """
    dzis = datetime.now().strftime("%d.%m.%Y %H:%M")
    n = len(legs)
    linie = [
        f"<b>FootStats DRAFT #{coupon_id} \u2014 {dzis}</b>",
        f"Nogi: <b>{n}</b> | \u0141\u0105czny kurs: <b>{total_odds:.2f}</b>",
        "",
        "<b>Kandydaci:</b>",
    ]
    for leg in legs[:6]:
        home  = leg.get("home") or leg.get("gospodarz", "")
        away  = leg.get("away") or leg.get("goscie", "")
        tip   = leg.get("tip") or leg.get("typ", "?")
        odds  = leg.get("odds") or leg.get("kurs", 0.0)
        score = leg.get("decision_score", 0)
        # Fallback: parsuj pole "mecz" jeśli brak home/away
        if not home and not away:
            mecz = leg.get("mecz", "")
            if " vs " in mecz:
                home, away = mecz.split(" vs ", 1)
            elif " - " in mecz:
                home, away = mecz.split(" - ", 1)
            else:
                home, away = mecz, ""
        home = home.strip() or "?"
        away = away.strip() or "?"
        linie.append(f"  \u2022 {home} \u2013 {away} <b>{tip}</b> @{float(odds):.2f} [score={score}]")
    linie.append("\n\u23f3 Status: DRAFT (fina\u0142 ~1h przed meczem)")
    return _send("\n".join(linie))


def send_message(text: str) -> bool:
    """Wysyła dowolną wiadomość tekstową na Telegram."""
    return _send(text)


def send_trening_raport(n_matches: int, marchewki: list, kije: list) -> bool:
    """Wysyła skrót wyników treningu Groq."""
    linie = [f"<b>FootStats Trening – {datetime.now().strftime('%d.%m')}</b>"]
    linie.append(f"Przeanalizowano {n_matches:,} meczow historycznych\n")

    if marchewki:
        linie.append("<b>Marchewki:</b>")
        for m in marchewki[:3]:
            linie.append(f"  + {m.get('regula', m) if isinstance(m, dict) else m}")

    if kije:
        linie.append("\n<b>Kije (mity):</b>")
        for k in kije[:3]:
            linie.append(f"  - {k.get('mit', k) if isinstance(k, dict) else k}")

    return _send("\n".join(linie))

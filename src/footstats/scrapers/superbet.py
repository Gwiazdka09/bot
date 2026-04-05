"""
superbet.py – Scraper kuponów z Superbet SuperSocial
=====================================================
Pobiera aktywne kupony top typerów z SuperSocial (w tym BetBuilder)
i analizuje je przez AI.

Wymagania w .env:
    SUPERBET_LOGIN=twoj@email.com
    SUPERBET_PASSWORD=twoje_haslo

Użycie:
    python -m footstats.scrapers.superbet              # pobierz i analizuj AI
    python -m footstats.scrapers.superbet --brak-ai    # tylko pobierz
    python -m footstats.scrapers.superbet --debug      # widoczna przeglądarka
    python -m footstats.scrapers.superbet --top 20     # max 20 typerów
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("BLAD: pip install playwright  nastepnie  python -m playwright install chromium")
    sys.exit(1)

from dotenv import load_dotenv
load_dotenv()

SUPERBET_URL = "https://www.superbet.pl"
SOCIAL_URL   = f"{SUPERBET_URL}/social"
CACHE_DIR    = Path("cache/superbet")


# ── Helpers ───────────────────────────────────────────────────────────────

def _zamknij_popup(page) -> None:
    for sel in [
        "#onetrust-accept-btn-handler",
        "button:has-text('Akceptuję')",
        "button:has-text('Zgadzam się')",
        "button:has-text('Akceptuj wszystkie')",
        "button:has-text('Akceptuj')",
        "button:has-text('Zamknij')",
        "[aria-label='close']",
        "[aria-label='Zamknij']",
        "button.close",
    ]:
        try:
            page.click(sel, timeout=2000)
            time.sleep(0.4)
            return
        except Exception:
            pass


def _akceptuj_cookies(page) -> None:
    """Akceptuje baner cookie zanim cokolwiek innego zrobimy."""
    for sel in [
        "#onetrust-accept-btn-handler",
        "button:has-text('Akceptuj wszystkie')",
        "button:has-text('Akceptuję')",
        "button:has-text('Akceptuj')",
        "button:has-text('Zgadzam się')",
        "[data-testid='cookie-accept']",
        ".cookie-accept",
    ]:
        try:
            page.wait_for_selector(sel, timeout=5000)
            page.click(sel)
            print("[Superbet] Zaakceptowano cookies")
            time.sleep(1)
            return
        except Exception:
            pass
    print("[Superbet] Baner cookie nie pojawil sie lub juz zaakceptowany")


def _zapisz_cache(dane: list, nazwa: str = "kupony") -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    sciezka = CACHE_DIR / f"{nazwa}_{ts}.json"
    sciezka.write_text(json.dumps(dane, ensure_ascii=False, indent=2), encoding="utf-8")
    return sciezka


# ── Logowanie ─────────────────────────────────────────────────────────────

def zaloguj(page) -> bool:
    login = os.getenv("SUPERBET_LOGIN", "").strip()
    haslo = os.getenv("SUPERBET_PASSWORD", "").strip()

    if not login or not haslo:
        print("[Superbet] Brak SUPERBET_LOGIN lub SUPERBET_PASSWORD w .env")
        return False

    # Selektory pola email/login — Superbet: name='username', type='text', pusty placeholder
    EMAIL_SELS = [
        "input[name='username']",      # Superbet: <input name="username" type="text">
        "input[id*='username']",       # Superbet: id="username-0"
        "input[placeholder*='użytkownika']",
        "input[placeholder*='uzytkownika']",
        "input[placeholder*='Nazwa']",
        "input[placeholder*='mail']",
        "input[placeholder*='Login']",
        "input[placeholder*='login']",
        "input[type='email']",
        "input[name='email']",
        "input[name='login']",
    ]
    FORM_WAIT_SEL = (
        "input[name='username'], input[id*='username'], "
        "input[placeholder*='użytkownika'], input[placeholder*='mail'], "
        "input[type='email'], input[type='password']"
    )

    try:
        # Krok 1: otwórz stronę główną i kliknij Zaloguj (modal)
        print("[Superbet] Klikam przycisk Zaloguj na stronie glownej...")
        page.goto(SUPERBET_URL, wait_until="domcontentloaded", timeout=20000)
        time.sleep(2)
        _akceptuj_cookies(page)
        time.sleep(1)

        # Kliknij przycisk Zaloguj żeby otworzyć modal
        for sel in [
            "button:has-text('Zaloguj')",
            "a:has-text('Zaloguj')",
            "[data-cy='login-button']",
            "button:has-text('Logowanie')",
        ]:
            try:
                page.wait_for_selector(sel, timeout=5000)
                page.click(sel)
                print(f"[Superbet] Kliknieto przycisk logowania ({sel})")
                time.sleep(3)
                break
            except Exception:
                continue

        # Krok 2: poczekaj na formularz logowania
        print("[Superbet] Czekam na formularz logowania...")
        try:
            page.wait_for_selector(FORM_WAIT_SEL, timeout=10000)
            print("[Superbet] Formularz znaleziony")
        except PWTimeout:
            print("[Superbet] Formularz nie pojawil sie — sprawdz screenshot")
            page.screenshot(path="superbet_debug_noform.png")
            return False

        # Krok 3: wpisz email/login (page.fill jest bardziej niezawodne niż el.fill)
        email_wpisany = False
        for sel in EMAIL_SELS:
            try:
                page.fill(sel, login, timeout=3000)
                print(f"[Superbet] Login wpisany ({sel})")
                email_wpisany = True
                time.sleep(0.4)
                break
            except Exception:
                continue

        if not email_wpisany:
            # Debug: wypisz wszystkie inputy na stronie
            inputs_info = page.evaluate("""
                Array.from(document.querySelectorAll('input')).map(i => ({
                    type: i.type, name: i.name, placeholder: i.placeholder,
                    id: i.id, visible: i.offsetParent !== null
                }))
            """)
            print(f"[Superbet] BLAD: nie znaleziono pola loginu. Inputy: {inputs_info}")
            page.screenshot(path="superbet_debug_noform.png")
            return False

        # Krok 4: wpisz hasło
        for sel in ["input[type='password']", "input[name='password']", "input[id*='password']"]:
            try:
                page.fill(sel, haslo, timeout=3000)
                print("[Superbet] Haslo wpisane")
                time.sleep(0.4)
                break
            except Exception:
                continue

        page.screenshot(path="superbet_debug_filled.png")
        print("[Superbet] Screenshot po wpisaniu: superbet_debug_filled.png")

        # Krok 5: zatwierdź
        for sel in [
            "button[type='submit']",
            "button:has-text('Zaloguj się')",
            "button:has-text('Zaloguj')",
            "button:has-text('Wejdź')",
            "button:has-text('ZALOGUJ')",
        ]:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    print(f"[Superbet] Submit klikniety ({sel})")
                    time.sleep(5)
                    break
            except Exception:
                continue

        # Krok 6: sprawdź czy zalogowany
        zalogowany = False
        for sel in [
            "button:has-text('Wpłata')",
            "button:has-text('Wplata')",
            "span:has-text('PLN')",
            "[data-cy='user-balance']",
            ".user-balance",
            "a:has-text('Wyloguj')",
            "button:has-text('Wypłać')",
        ]:
            try:
                page.wait_for_selector(sel, timeout=6000)
                zalogowany = True
                print(f"[Superbet] Zalogowano pomyslnie (wykryto: {sel})")
                break
            except PWTimeout:
                continue

        if not zalogowany:
            print("[Superbet] Nie potwierdzono logowania — sprawdz screenshot")
            page.screenshot(path="superbet_debug_login_fail.png")
        return True  # kontynuuj nawet jeśli nie pewne

    except Exception as e:
        print(f"[Superbet] Blad logowania: {e}")
        return False


# ── Przechwytywanie API SuperSocial ──────────────────────────────────────

def pobierz_kupony_api(page, max_kupony: int = 50) -> list:
    """
    Przechwytuje requesty JSON API SuperSocial i buduje listę kuponów.
    Zwraca listę dict kompatybilną z resztą potoku (lub [] jeśli brak danych).
    """
    # Zbieramy WSZYSTKIE JSON-owe odpowiedzi (bez filtrowania URL)
    # żeby znaleźć właściwy endpoint social feed
    api_dane: list[dict] = []

    # Słowa kluczowe WYKLUCZAJĄCE typowe śmieciowe endpointy
    _EXCLUDE = [
        'localization', 'sports-offer/sports', 'sport/android',
        'payment-providers', 'sponsorships', 'footer-config',
        'seo-manager', 'category-icon', 'hot-tournaments/offer',
        'clickstream', 'o11y', 'evaluate', 'bankRegistration',
        '/struct', 'tvguide',
    ]

    def _on_response(response):
        url = response.url
        # Odrzuć nie-JSON i znane śmieciowe endpointy
        try:
            ct = response.headers.get('content-type', '')
            if 'json' not in ct:
                return
            if any(x in url for x in _EXCLUDE):
                return
            data = response.json()
            api_dane.append({'url': url, 'data': data})
        except Exception:
            pass

    page.on('response', _on_response)

    feed_urls = [
        f"{SUPERBET_URL}/social/for-you/popular",
        f"{SUPERBET_URL}/social/popularne-analizy-uzytkownikow",
        f"{SUPERBET_URL}/social/for-you",
        f"{SUPERBET_URL}/social/aktualnosci",
        f"{SUPERBET_URL}/social",
    ]

    for url in feed_urls:
        try:
            api_dane.clear()
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            time.sleep(4)
            _zamknij_popup(page)
            print(f"[API] Zaladowano: {page.url}")

            # Scroll żeby wyzwolić lazy-loading
            for _ in range(5):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1.0)

            print(f"[API] Zebrano {len(api_dane)} odpowiedzi JSON z {url}")
            for r in api_dane:
                print(f"  [API URL] {r['url'][:120]}")

            # Zbuduj mapę ticketId → nick z DOM-u (przed parsowaniem API)
            nick_map = _wyciagnij_nicki_z_dom(page)
            print(f"[API] Nick map z DOM-u: {len(nick_map)} wpisow")

            # Parsuj ticket responses
            kupony_znalezione = []
            debug_saved = False
            for resp in api_dane:
                resp_url = resp['url']
                m_tid = re.search(r'/ticket/([A-Z0-9\-]+)$', resp_url)
                ticket_id = m_tid.group(1) if m_tid else None
                nick = nick_map.get(ticket_id, "?") if ticket_id else "?"

                wyniki_r = _parsuj_json_api(resp['data'], nick)
                if wyniki_r and not debug_saved and ticket_id:
                    debug_t = CACHE_DIR / f"ticket_sample_{ticket_id}.json"
                    debug_t.parent.mkdir(parents=True, exist_ok=True)
                    debug_t.write_text(
                        json.dumps(resp['data'], ensure_ascii=False, indent=2),
                        encoding='utf-8'
                    )
                    print(f"  [API] Probka ticketu: {debug_t.name}")
                    debug_saved = True
                kupony_znalezione.extend(wyniki_r)

            if kupony_znalezione:
                n = len(kupony_znalezione)
                print(f"[API] Sparsowano {n} kuponow z {url}")
                return kupony_znalezione[:max_kupony]

        except Exception as e:
            print(f"[API] Blad dla {url}: {e}")

    # Nic nie znaleziono — zapisz dump do diagnozy
    if api_dane:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        dump_path = CACHE_DIR / "api_debug_dump.json"
        dump_path.write_text(
            json.dumps([{'url': r['url'], 'keys': list(r['data'].keys())
                         if isinstance(r['data'], dict) else type(r['data']).__name__}
                        for r in api_dane],
                       ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        print(f"[API] Dump struktury API → {dump_path}")

    return []


def _parsuj_json_api(data, nick: str = "?") -> list:
    """Parsuje odpowiedź JSON API — obsługuje format ticket oraz inne struktury."""
    if isinstance(data, dict) and 'ticketId' in data:
        k = _parsuj_ticket(data, nick)
        return [k] if k else []

    kupony = []
    if isinstance(data, list):
        for item in data:
            k = _parsuj_item_api(item)
            if k:
                kupony.append(k)
    elif isinstance(data, dict):
        for key in ['data', 'items', 'results', 'coupons', 'tickets',
                    'bets', 'content', 'feed', 'posts', 'picks']:
            if key in data and isinstance(data[key], list):
                for item in data[key]:
                    k = _parsuj_item_api(item)
                    if k:
                        kupony.append(k)
    return kupony


def _parsuj_ticket(data: dict, nick: str = "?") -> dict | None:
    """Parsuje odpowiedź Superbet Ticket Presentation API."""
    ticket_id = data.get('ticketId', '')

    kurs_laczny = None
    for key in ['coefficient', 'initialCoefficient']:
        if key in data:
            try:
                k = float(data[key])
                if k > 1.0:
                    kurs_laczny = k
                    break
            except (ValueError, TypeError):
                pass

    # Stawka
    stawka = None
    payment = data.get('payment', {})
    if isinstance(payment, dict):
        for k in ['amount', 'value', 'stake', 'betAmount']:
            if k in payment:
                try:
                    stawka = float(payment[k])
                    break
                except (ValueError, TypeError):
                    pass
    elif isinstance(payment, (int, float)):
        stawka = float(payment)

    # Zdarzenia
    zdarzenia = []
    for ev in data.get('events', []):
        if not isinstance(ev, dict):
            continue
        # Nazwa meczu
        mecz = (ev.get('name') or ev.get('eventName') or
                f"{ev.get('homeTeamName', '')} - {ev.get('awayTeamName', '')}").strip(' -')
        # Typ zakładu
        typ = (ev.get('marketName') or ev.get('betTypeName') or
               ev.get('oddName') or ev.get('betName') or
               ev.get('selectionName') or '?')
        # Kurs per zdarzenie
        kurs_ev = None
        for kk in ['coefficient', 'odds', 'price', 'oddValue']:
            if kk in ev:
                try:
                    kurs_ev = float(ev[kk])
                    break
                except (ValueError, TypeError):
                    pass
        zdarzenia.append({
            'mecz': str(mecz)[:80] or '?',
            'typ':  str(typ)[:80],
            'kurs': kurs_ev,
            'betbuilder': _czy_betbuilder(str(typ)),
        })

    if not zdarzenia and not kurs_laczny:
        return None

    return {
        'nick':       nick,
        'ticket_id':  ticket_id,
        'kurs_laczny': kurs_laczny,
        'stawka':     stawka,
        'zdarzenia':  zdarzenia,
        'linie_raw':  [],
        'tresc':      json.dumps(data, ensure_ascii=False)[:600],
        'zrodlo':     'superbet_ticket_api',
        'pobrano':    datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def _parsuj_item_api(item) -> dict | None:
    """Parsuje element z ogólnej listy API (nie-ticket format)."""
    if not isinstance(item, dict):
        return None

    nick = "?"
    for path in [
        ['username'], ['nick'], ['login'], ['name'],
        ['user', 'username'], ['user', 'nick'], ['user', 'login'],
        ['author', 'username'], ['author', 'nick'],
        ['tipster', 'username'], ['tipster', 'nick'],
    ]:
        try:
            v = item
            for k in path:
                v = v[k]
            if isinstance(v, str) and v:
                nick = v[:40]
                break
        except (KeyError, TypeError):
            pass

    kurs_laczny = None
    for key in ['totalOdds', 'total_odds', 'odds', 'kurs', 'rate', 'totalRate']:
        if key in item:
            try:
                kurs_laczny = float(item[key])
                break
            except (ValueError, TypeError):
                pass

    zdarzenia = []
    for key in ['selections', 'events', 'bets', 'picks', 'legs', 'items']:
        if key in item and isinstance(item[key], list):
            for sel in item[key]:
                if not isinstance(sel, dict):
                    continue
                mecz = (sel.get('eventName') or sel.get('event') or
                        sel.get('match') or sel.get('name') or '?')
                typ  = (sel.get('marketName') or sel.get('market') or
                        sel.get('pick') or sel.get('selection') or '?')
                kurs = None
                for kk in ['odds', 'price', 'rate', 'kurs', 'coefficient']:
                    if kk in sel:
                        try:
                            kurs = float(sel[kk])
                            break
                        except (ValueError, TypeError):
                            pass
                zdarzenia.append({
                    'mecz': str(mecz)[:80],
                    'typ':  str(typ)[:80],
                    'kurs': kurs,
                    'betbuilder': _czy_betbuilder(str(typ)),
                })
            break

    if nick == "?" and not zdarzenia and not kurs_laczny:
        return None

    return {
        'nick':        nick,
        'kurs_laczny': kurs_laczny,
        'stawka':      None,
        'zdarzenia':   zdarzenia,
        'linie_raw':   [],
        'tresc':       json.dumps(item, ensure_ascii=False)[:600],
        'zrodlo':      'superbet_api',
        'pobrano':     datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ── Wyciąganie nicków z DOM-u strony social ───────────────────────────────

def _wyciagnij_nicki_z_dom(page) -> dict:
    """
    Próbuje wyciągnąć mapowanie {ticketId: nick} z DOM-u aktualnej strony social.
    Szuka linków do profili użytkowników w pobliżu kart kuponów.
    Zwraca dict lub {} jeśli nie znaleziono.
    """
    try:
        wynik = page.evaluate("""
            () => {
                const map = {};
                // Szukaj kart kuponów zawierających link do profilu i id ticketu
                const cards = document.querySelectorAll(
                    '[class*="coupon"], [class*="ticket"], [class*="social"], article, [class*="card"]'
                );
                for (const card of cards) {
                    const userLink = card.querySelector(
                        'a[href*="/social/uzytkownik"], a[href*="/social/user"], a[href*="uzytkownik"]'
                    );
                    if (!userLink) continue;
                    const nick = userLink.textContent.trim().split('\\n')[0].trim();
                    if (!nick) continue;

                    // Szukaj ticket ID w atrybutach data-* i href-ach
                    const allEls = card.querySelectorAll('[data-ticket-id], [data-code], [data-id]');
                    for (const el of allEls) {
                        const tid = el.dataset.ticketId || el.dataset.code || el.dataset.id;
                        if (tid && /^[A-Z0-9]{4}-[A-Z0-9]{6,}/.test(tid)) {
                            map[tid] = nick;
                        }
                    }
                    // Szukaj w linkach do kuponów
                    const couponLinks = card.querySelectorAll(
                        'a[href*="/ticket/"], a[href*="/kupon/"], a[href*="/coupon/"]'
                    );
                    for (const a of couponLinks) {
                        const m = a.href.match(/\\/ticket\\/([A-Z0-9]{4}-[A-Z0-9]+)/);
                        if (m) map[m[1]] = nick;
                    }
                }
                return map;
            }
        """)
        return wynik or {}
    except Exception as e:
        print(f"[DOM] Blad ekstrakcji nicków: {e}")
        return {}


# ── Pobieranie typerów z SuperSocial (DOM) ────────────────────────────────

def pobierz_typerzy(page, max_typerzy: int = 30) -> list:
    """
    Przechodzi do SuperSocial i zbiera listę typerów z aktywnymi kuponami.
    Próbuje kolejno: popularne-analizy, for-you/popular, strona główna social.
    """
    typerzy = []

    kandydaci_url = [
        f"{SUPERBET_URL}/social/for-you/popular?filter=popular",
        f"{SUPERBET_URL}/social/for-you/popular",
        f"{SUPERBET_URL}/social/popularne-analizy-uzytkownikow",
        f"{SUPERBET_URL}/social/for-you",
        SOCIAL_URL,
    ]

    for social_url in kandydaci_url:
        try:
            print(f"[Superbet] Próbuję: {social_url}")
            page.goto(social_url, wait_until="domcontentloaded", timeout=25000)
            time.sleep(3)
            _zamknij_popup(page)
            print(f"[Superbet] Faktyczny URL: {page.url}")

            # Screenshot przed scrollem
            slug = social_url.split('/')[-1] or 'social'
            page.screenshot(path=f"superbet_debug_{slug}.png")

            # Poczekaj na treść
            try:
                page.wait_for_selector(
                    "[class*='tipster'], [class*='user-card'], "
                    "[class*='social-card'], [class*='profile-card'], "
                    "a[href*='/social/uzytkownik'], a[href*='/social/user'], "
                    "[class*='coupon-card'], [class*='CouponCard']",
                    timeout=8000
                )
            except PWTimeout:
                pass

            # Scroll
            for _ in range(4):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(1.0)

            # Dump WSZYSTKICH linków (bez filtrowania) dla diagnostyki
            wszystkie_linki = page.evaluate("""
                Array.from(document.querySelectorAll('a[href]'))
                    .map(a => a.getAttribute('href'))
                    .filter(h => h && !h.startsWith('#') && !h.startsWith('javascript'))
                    .slice(0, 60)
            """)
            social_linki = [h for h in wszystkie_linki
                            if any(x in (h or '') for x in
                                   ['social', 'uzytkownik', 'user', 'profil', 'typer'])]
            print(f"[Superbet] Linki ogólem: {len(wszystkie_linki)}, "
                  f"social/user: {len(social_linki)}")
            if social_linki:
                print(f"[Superbet] Social linki: {social_linki[:15]}")

            # Wzorce URL profilu — testuj kolejno
            linki = []
            for wzorzec in [
                "a[href*='/social/uzytkownik']",
                "a[href*='/social/user']",
                "a[href*='/social/profil']",
                "a[href*='/social/typer']",
                "a[href*='uzytkownik']",
            ]:
                linki = page.query_selector_all(wzorzec)
                if linki:
                    print(f"[Superbet] Wzorzec '{wzorzec}': {len(linki)} linków")
                    break

            if not linki:
                print(f"[Superbet] Brak linków profili na {social_url}")
                continue  # spróbuj kolejny URL

        except Exception as e:
            print(f"[Superbet] Blad dla {social_url}: {e}")
            continue

        # Zbierz typerów z linków
        seen_urls: set[str] = set()
        for link in linki[:max_typerzy * 3]:
            try:
                href = link.get_attribute("href") or ""
                if not href or href in seen_urls:
                    continue
                href = href.split("/kupony")[0].split("/analizy")[0]
                if href in seen_urls:
                    continue
                seen_urls.add(href)

                tekst = link.inner_text().strip()
                if not tekst:
                    parent = link.evaluate_handle("el => el.parentElement").as_element()
                    tekst = parent.inner_text().strip() if parent else ""

                nick = "?"
                for linia in tekst.split("\n"):
                    l = linia.strip()
                    if l and l not in ("Obserwuj", "Obserwowani", "Kupony") and not l.isdigit():
                        nick = l[:40]
                        break

                typerzy.append({
                    "nick":        nick,
                    "url_profilu": href if href.startswith("http") else SUPERBET_URL + href,
                })
                if len(typerzy) >= max_typerzy:
                    break
            except Exception:
                continue

        if typerzy:
            break  # znaleziono — nie próbuj kolejnych URL

    # Deduplikacja
    seen_nicks: set[str] = set()
    typerzy_uniq = []
    for t in typerzy:
        if t["nick"] not in seen_nicks and t["nick"] != "?":
            seen_nicks.add(t["nick"])
            typerzy_uniq.append(t)

    print(f"[Superbet] Unikalni typerzy (DOM): {len(typerzy_uniq)}")
    return typerzy_uniq


# ── Pobieranie kuponów z profilu typera ───────────────────────────────────

def pobierz_kupony_typera(page, typer: dict) -> list:
    """
    Wchodzi na profil typera i scrapuje jego aktywne kupony.
    Obsługuje standardowe typy oraz BetBuilder.
    """
    kupony = []
    nick = typer.get("nick", "?")
    url  = typer.get("url_profilu", "")

    if not url:
        return []

    # Przejdź do zakładki Kupony
    url_kupony = url.rstrip("/") + "/kupony"

    try:
        page.goto(url_kupony, wait_until="domcontentloaded", timeout=20000)
        time.sleep(2.5)
        _zamknij_popup(page)

        # Poczekaj na kupony
        try:
            page.wait_for_selector(
                "[class*='coupon'], [class*='ticket'], [class*='bet-slip'], "
                "[class*='kupon'], [class*='aktywne']",
                timeout=8000
            )
        except PWTimeout:
            pass

        # Przewiń żeby załadować wszystkie
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.8)

        # Znajdź karty kuponów
        # SuperSocial pokazuje kupony jako karty z kursem łącznym i zdarzeniami
        kupon_els = page.query_selector_all(
            "[class*='coupon-card'], [class*='CouponCard'], "
            "[class*='ticket-card'], [class*='TicketCard'], "
            "[class*='bet-card'], [class*='BetCard'], "
            "article[class*='coupon'], div[class*='social-coupon']"
        )

        if not kupon_els:
            # Fallback — szukaj po strukturze treści
            kupon_els = page.query_selector_all(
                "div:has([class*='odds']):has([class*='event'])"
            )

        print(f"  [{nick}] Znaleziono {len(kupon_els)} kuponów")

        for el in kupon_els:
            try:
                kupon = _parsuj_element_kuponu(el, nick)
                if kupon:
                    kupony.append(kupon)
            except Exception:
                continue

        # Jeśli brak kuponów przez selektory — fallback na surowy tekst strony
        if not kupony:
            kupon = _parsuj_fallback(page, nick, url_kupony)
            if kupon:
                kupony.append(kupon)

    except Exception as e:
        print(f"  [{nick}] Blad: {e}")

    return kupony


def _parsuj_element_kuponu(el, nick: str) -> dict | None:
    """Parsuje pojedynczy element kuponu w SuperSocial."""
    tekst = el.inner_text().strip()
    if len(tekst) < 15:
        return None

    linie = [l.strip() for l in tekst.split("\n") if l.strip()]

    # Szukaj kursu łącznego (duża liczba, np. "116.42" lub "14.46")
    kurs_laczny = None
    for linia in linie:
        m = re.search(r'\b(\d{1,4}[.,]\d{2})\b', linia)
        if m:
            try:
                k = float(m.group(1).replace(",", "."))
                if 1.01 < k < 50000:
                    kurs_laczny = k
                    break
            except ValueError:
                pass

    # Szukaj stawki (wzorzec "X,XX PLN" lub "Stawka X PLN")
    stawka = None
    for linia in linie:
        m = re.search(r'(\d+[.,]\d{2})\s*PLN', linia, re.IGNORECASE)
        if m:
            try:
                stawka = float(m.group(1).replace(",", "."))
                break
            except ValueError:
                pass

    # Wyciągnij zdarzenia — szukaj wzorca "Mecz – typ @ kurs" lub nazwy meczu
    zdarzenia = _parsuj_zdarzenia(linie)

    # Czas "Za Xh" lub "Za Xmin"
    czas_str = ""
    for linia in linie:
        if re.search(r'Za \d+[hm]', linia):
            czas_str = linia
            break

    return {
        "nick":         nick,
        "kurs_laczny":  kurs_laczny,
        "stawka":       stawka,
        "zdarzenia":    zdarzenia,
        "czas":         czas_str,
        "linie_raw":    linie[:25],
        "tresc":        tekst[:600],
        "zrodlo":       "superbet_social",
        "pobrano":      datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


_SLOWA_MECZ_NIE = [
    "gol", "polowa", "połowa", "karta", "rzut", "strzal", "strzał",
    "faul", "corner", "liczba", "przedzial", "przedział", "powyzej",
    "powyżej", "ponizej", "poniżej", "wynik", "mecz:", "oba",
]


def _czy_linia_to_mecz(linia: str) -> bool:
    """True jeśli linia wygląda jak 'Druzyna A - Druzyna B', nie jak typ BetBuilder."""
    if " - " not in linia and " \u2013 " not in linia:
        return False
    czesci = re.split(r' [-\u2013] ', linia, maxsplit=1)
    if len(czesci) < 2:
        return False
    lewa, prawa = czesci[0].strip(), czesci[1].strip()
    # Oba człony muszą być >= 3 znaki i zaczynać się wielką literą
    if len(lewa) < 3 or len(prawa) < 3:
        return False
    if not lewa[0].isupper() or not prawa[0].isupper():
        return False
    # Nie może zawierać słów kluczowych typów
    linia_lower = linia.lower()
    if any(s in linia_lower for s in _SLOWA_MECZ_NIE):
        return False
    # Prawa strona nie może być samą liczbą (np. "1-3" to zakres, nie drużyna)
    if re.match(r'^\d+[-–]\d+$', prawa.strip()):
        return False
    return True


def _parsuj_zdarzenia(linie: list[str]) -> list[dict]:
    """
    Wyciąga listę zdarzeń z linii tekstowych kuponu.
    Obsługuje: standardowe typy (1/X/2, Over, BTTS) oraz BetBuilder.
    """
    zdarzenia = []

    # Wzorzec kursu per zdarzenie: liczba >= 1.01
    kurs_re = re.compile(r'\b(\d+[.,]\d{2})\b')

    i = 0
    while i < len(linie):
        linia = linie[i]

        # Pomijaj linie które są nagłówkami lub meta-danymi
        if any(x in linia.lower() for x in
               ["stawka", "kurs", "wygrana", "za ", "obserwu", "kupony",
                "analizy", "statystyki", "zainspirowani", "srednia"]):
            i += 1
            continue

        is_mecz = _czy_linia_to_mecz(linia)

        if is_mecz:
            mecz = linia.strip()
            typ  = ""
            kurs = None

            # Następna(e) linie mogą być typem i kursem
            if i + 1 < len(linie):
                nastepna = linie[i + 1]
                # Sprawdź czy to typ zakładu (nie mecz, nie gołe metadane)
                if not _czy_linia_to_mecz(nastepna):
                    typ = nastepna.strip()
                    i += 1

                    # Kurs może być w tej samej linii lub kolejnej
                    m_kurs = kurs_re.search(typ)
                    if m_kurs:
                        try:
                            k = float(m_kurs.group(1).replace(",", "."))
                            if 1.01 < k < 100:
                                kurs = k
                        except ValueError:
                            pass
                    elif i + 1 < len(linie):
                        m_kurs = kurs_re.search(linie[i + 1])
                        if m_kurs:
                            try:
                                k = float(m_kurs.group(1).replace(",", "."))
                                if 1.01 < k < 100:
                                    kurs = k
                                    i += 1
                            except ValueError:
                                pass

            zdarzenia.append({
                "mecz": mecz,
                "typ":  typ,
                "kurs": kurs,
                "betbuilder": _czy_betbuilder(typ),
            })

        i += 1

    return zdarzenia


def _czy_betbuilder(typ: str) -> bool:
    """Wykrywa czy typ to BetBuilder (kombinacja z jednego meczu)."""
    slowa_bb = [
        "przedział", "przedzial", "polowa", "połowa", "karta",
        "rzut rożny", "strzal", "strzał", "faul", "corner",
        "liczba goli", "gole w", "strzelec", "asyst",
    ]
    typ_lower = typ.lower()
    return any(s in typ_lower for s in slowa_bb)


def _parsuj_fallback(page, nick: str, url: str) -> dict | None:
    """Fallback — pobiera surowy tekst całej strony profilu."""
    try:
        tekst = page.inner_text("body")
        # Ogranicz do sekcji kuponów
        m = re.search(r'AKTYWNE KUPONY(.{0,3000})', tekst, re.DOTALL | re.IGNORECASE)
        fragment = m.group(0)[:2000] if m else tekst[500:2500]

        linie = [l.strip() for l in fragment.split("\n") if l.strip()]

        return {
            "nick":        nick,
            "kurs_laczny": None,
            "stawka":      None,
            "zdarzenia":   _parsuj_zdarzenia(linie),
            "linie_raw":   linie[:30],
            "tresc":       fragment[:600],
            "zrodlo":      "superbet_social_fallback",
            "pobrano":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
    except Exception:
        return None


# ── Analiza AI ────────────────────────────────────────────────────────────

def analizuj_kupony_ai(kupony: list) -> list:
    """Wysyła kupony do Groq i prosi o ocenę (szczególnie BetBuilder)."""
    try:
        from footstats.ai.analyzer import _zapytaj_typera
    except ImportError:
        try:
            from footstats.ai.client import zapytaj_ai as _zapytaj_typera
        except ImportError:
            print("[AI] Brak modulu AI — pomijam")
            return kupony

    wyniki = []

    for kupon in kupony:
        nick   = re.sub(r'[^a-zA-Z0-9_\-]', '_', kupon.get("nick", "?"))[:40]
        tresc  = kupon.get("tresc", "")
        zdarz  = kupon.get("zdarzenia", [])
        kurs_l = kupon.get("kurs_laczny")

        if not tresc and not zdarz:
            continue

        zdarz_str = "\n".join(
            f"  - {z['mecz']} | {z['typ']} @ {z['kurs'] or '?'}"
            + (" [BetBuilder]" if z.get("betbuilder") else "")
            for z in zdarz
        ) or tresc[:400]

        prompt = f"""Oceniasz kupon bukmacherski z Superbet SuperSocial od typera "{nick}".

KUPON:
Kurs laczny: {kurs_l or '?'}
Zdarzenia:
{zdarz_str}

ZADANIE: Oceń kupon i odpowiedz TYLKO w JSON:
{{
  "nick": "{nick}",
  "kurs_laczny": {kurs_l or 'null'},
  "zdarzenia": [
    {{"mecz": "...", "typ": "...", "kurs": 1.80, "betbuilder": false, "ocena_ev": "plus/minus/brak_danych"}}
  ],
  "ocena_ogolna": "DOBRY/RYZYKOWNY/BRAK_DANYCH",
  "komentarz": "1-2 zdania po polsku",
  "betbuilder_wykryty": true/false
}}"""

        try:
            odp  = _zapytaj_typera(prompt, max_tokens=400)
            m    = re.search(r'\{[\s\S]*\}', odp)
            wynik = json.loads(m.group()) if m else {
                "nick": nick, "ocena_ogolna": "BRAK", "komentarz": odp[:200]
            }
        except Exception as e:
            wynik = {"nick": nick, "ocena_ogolna": "BLAD", "komentarz": str(e)}

        wynik["_oryginal"] = kupon
        wyniki.append(wynik)
        print(f"  [AI] {nick}: {wynik.get('ocena_ogolna','?')} — {wynik.get('komentarz','')[:80]}")

    return wyniki


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    brak_ai = "--brak-ai"  in sys.argv
    debug   = "--debug"    in sys.argv
    max_top = 30
    for i, arg in enumerate(sys.argv):
        if arg == "--top" and i + 1 < len(sys.argv):
            try:
                max_top = int(sys.argv[i + 1])
            except ValueError:
                pass

    print(f"[Superbet] SuperSocial Scraper — top {max_top} typerów")
    print(f"[Superbet] AI: {'wylaczone' if brak_ai else 'wlaczone (Groq)'}")
    print()

    login = os.getenv("SUPERBET_LOGIN", "")
    if not login:
        print("BLAD: Dodaj SUPERBET_LOGIN i SUPERBET_PASSWORD do .env")
        sys.exit(1)

    wszystkie_kupony: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not debug)
        ctx = browser.new_context(
            extra_http_headers={"Accept-Language": "pl-PL,pl;q=0.9"},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = ctx.new_page()

        try:
            # ── Krok 1: zaloguj ──────────────────────────────────────────────
            if not zaloguj(page):
                print("[Superbet] Automatyczne logowanie nie powiodlo sie")
                if debug:
                    input("Zaloguj sie recznie i nacisnij Enter...")
                else:
                    browser.close()
                    sys.exit(1)

            time.sleep(2)
            _zamknij_popup(page)

            if debug:
                page.screenshot(path="superbet_debug_login.png")

            # ── Krok 2a: próba przechwycenia API ─────────────────────────────
            print("[Superbet] Próba przechwycenia API SuperSocial...")
            wszystkie_kupony = pobierz_kupony_api(page, max_kupony=max_top * 3)

            if wszystkie_kupony:
                print(f"[Superbet] API: zebrano {len(wszystkie_kupony)} kuponów — pomijam DOM scraping")
            else:
                # ── Krok 2b: fallback — DOM scraping przez profile ────────────
                print("[Superbet] API nie zwrócilo danych — próba DOM scrapingu...")
                typerzy = pobierz_typerzy(page, max_typerzy=max_top)

                if not typerzy:
                    print("[Superbet] Brak typerów — sprawdz superbet_debug_*.png")
                    browser.close()
                    sys.exit(1)

                # ── Krok 3: scrapuj kupony każdego typera ────────────────────
                for idx, typer in enumerate(typerzy, 1):
                    nick = typer["nick"]
                    print(f"\n[{idx}/{len(typerzy)}] {nick}")

                    kupony = pobierz_kupony_typera(page, typer)
                    wszystkie_kupony.extend(kupony)
                    print(f"  Zebrano {len(kupony)} kuponów")

        except Exception as e:
            print(f"[Superbet] Blad glowny: {e}")
            if debug:
                page.screenshot(path="superbet_error.png")
        finally:
            browser.close()

    # ── Krok 4: zapisz i analizuj ─────────────────────────────────────────
    print(f"\n[Superbet] Zebrano {len(wszystkie_kupony)} kuponów lacznie")

    if not wszystkie_kupony:
        print("[Superbet] Brak kuponów — uruchom z --debug zeby zobaczyc co sie dzieje")
        sys.exit(1)

    plik_raw = _zapisz_cache(wszystkie_kupony, "kupony_raw")
    print(f"[Superbet] Surowe dane: {plik_raw}")

    # Podsumowanie BetBuilderów
    n_bb = sum(
        1 for k in wszystkie_kupony
        for z in k.get("zdarzenia", [])
        if z.get("betbuilder")
    )
    if n_bb:
        print(f"[Superbet] Wykryto {n_bb} zdarzen BetBuilder")

    if not brak_ai:
        print("\n[AI] Analizuje kupony...")
        wyniki_ai = analizuj_kupony_ai(wszystkie_kupony)

        plik_ai = _zapisz_cache(wyniki_ai, "kupony_ai")
        print(f"[AI] Wyniki AI: {plik_ai}")

        print("\n" + "=" * 60)
        print("  PODSUMOWANIE — SUPERBET SUPERSOCIAL")
        print("=" * 60)

        for w in wyniki_ai:
            ocena = w.get("ocena_ogolna", "?")
            bb    = " [BB]" if w.get("betbuilder_wykryty") else ""
            kl    = w.get("kurs_laczny")
            kl_str = f" kurs={kl}" if kl else ""
            print(f"\n[{ocena}]{bb}{kl_str} — {w.get('nick','?')}")
            for z in w.get("zdarzenia", [])[:5]:
                bb_tag = " [BetBuilder]" if z.get("betbuilder") else ""
                print(f"   * {z.get('mecz','?')} | {z.get('typ','?')} @ {z.get('kurs','?')}{bb_tag}")
            print(f"   {w.get('komentarz','')}")
        print("=" * 60)

    else:
        print("[Superbet] AI pominiete (--brak-ai)")


if __name__ == "__main__":
    main()

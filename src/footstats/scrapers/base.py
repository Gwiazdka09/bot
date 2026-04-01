import time
import requests
from footstats.utils.cache import _rate_guard
from footstats.utils.console import console
from rich.panel import Panel

# ── HTTP GET (football-data.org) ─────────────────────────────────────

def _http_get(endpoint: str, params: dict = None, headers: dict = None) -> dict | None:
    url = f"https://api.football-data.org/v4{endpoint}"
    _rate_guard()
    try:
        r = requests.get(url, headers=headers, params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 429:
            console.print(Panel(
                "[bold red]Limit API wyczerpany (429 Too Many Requests)![/bold red]\n\n"
                "Plan FREE: [bold]10 zapytan na minute[/bold].\n"
                "FootStats wznowi pobieranie za [bold]62 sekundy[/bold]...",
                border_style="red", title="Rate Limit Exceeded", padding=(1, 2)
            ))
            time.sleep(62)
            return _http_get(endpoint, params, headers)
        elif r.status_code == 403:
            console.print("[red]403 Forbidden - nieprawidlowy klucz API lub plan.[/red]")
            return None
        elif r.status_code == 404:
            console.print(f"[yellow]404 Not Found: {endpoint}[/yellow]")
            return None
        else:
            console.print(f"[red]HTTP {r.status_code}: {endpoint}[/red]")
            return None
    except requests.ConnectionError:
        console.print("[red]Brak polaczenia z internetem.[/red]")
        return None
    except requests.Timeout:
        console.print("[red]Timeout - serwer nie odpowiada.[/red]")
        return None

import os
import sys
import time
import math
import json
from datetime import datetime
from pathlib import Path

import requests
import pandas as pd
import numpy as np
from scipy.stats import poisson
from dotenv import load_dotenv, set_key

# Rich – kolorowy terminal
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt
from rich.progress import Progress, SpinnerColumn, TextColumn

# ReportLab – PDF
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table as RLTable, TableStyle
from reportlab.lib import colors

console = Console()

# ================================================================
#    KONFIGURACJA I STAŁE
# ================================================================
VERSION       = "v2.3 Platinum"
MAX_GOLE      = 8
OSTATNIE_N    = 15
BONUS_DOMOWY  = 1.15
SLEEP_API     = 1.5

LIGI = {
    "1": {"nazwa": "Premier League (Anglia)",  "kod": "PL",  "emoji": "🇬🇧", "druzyny": 20},
    "2": {"nazwa": "La Liga (Hiszpania)",       "kod": "PD",  "emoji": "🇪🇸", "druzyny": 20},
    "3": {"nazwa": "Bundesliga (Niemcy)",       "kod": "BL1", "emoji": "🇩🇪", "druzyny": 18},
    "4": {"nazwa": "Serie A (Wlochy)",          "kod": "SA",  "emoji": "🇮🇹", "druzyny": 20},
    "5": {"nazwa": "Ligue 1 (Francja)",         "kod": "FL1", "emoji": "🇫🇷", "druzyny": 18},
    "6": {"nazwa": "Ekstraklasa (Polska)",      "kod": "PPL", "emoji": "🇵🇱", "druzyny": 18},
    "7": {"nazwa": "Champions League",          "kod": "CL",  "emoji": "🇪🇺", "druzyny": 36},
    "8": {"nazwa": "Eredivisie (Holandia)",     "kod": "DED", "emoji": "🇳🇱", "druzyny": 18},
}

# Cache system, aby nie przekroczyć limitów API
CACHE = {"standings": {}, "matches": {}}

# ================================================================
#    BEZPIECZEŃSTWO (.env)
# ================================================================
def setup_api():
    if not Path(".env").exists():
        console.print("[yellow]Plik .env nie istnieje. Tworzę nowy...[/yellow]")
        klucz = Prompt.ask("Wpisz swój klucz API z football-data.org")
        with open(".env", "w") as f:
            f.write(f'FOOTBALL_API_KEY="{klucz}"')
    
    load_dotenv()
    return os.getenv("FOOTBALL_API_KEY")

# ================================================================
#    LOGIKA ANALITYCZNA (Importance & Two-Leg)
# ================================================================
def calculate_motivation(team_name, df_standings, total_teams):
    """Oblicza mnożnik motywacji na podstawie pozycji w tabeli."""
    if df_standings is None or team_name not in df_standings['Druzyna'].values:
        return 1.0, "Normalna"
    
    row = df_standings[df_standings['Druzyna'] == team_name].iloc[0]
    pos = int(row['Poz.'])
    played = int(row['M'])
    
    # Walka o mistrza/puchary (Top 4) lub spadek (ostatnie 3)
    if pos <= 4 or pos > (total_teams - 3):
        return 1.20, "🔥 WYSOKA (Walka o cel)"
    # Środek tabeli (tzw. "plaża")
    if 8 <= pos <= (total_teams - 6) and played > 25:
        return 0.85, "🧊 NISKA (Środek tabeli)"
    
    return 1.0, "Neutralna"

def apply_two_leg_logic(lambda_h, lambda_a, agg_h, agg_a):
    """Scenariusz Jagiellonii: jeśli ktoś wysoko wygrał 1. mecz, w rewanżu odpuszcza."""
    if agg_h is None or agg_a is None:
        return lambda_h, lambda_a, ""
    
    diff = agg_h - agg_a
    if diff >= 3: # Gospodarz pierwszego meczu zmiażdżył rywala
        return lambda_h * 0.7, lambda_a * 1.3, "Rewanż: Faworyt oszczędza siły, underdog atakuje."
    elif diff <= -3:
        return lambda_h * 1.3, lambda_a * 0.7, "Rewanż: Faworyt oszczędza siły, underdog atakuje."
    
    return lambda_h, lambda_a, "Rewanż: Wynik stykowy, pełna mobilizacja."

# ================================================================
#    POBIERANIE DANYCH Z CACHE
# ================================================================
def get_data(endpoint, api_key):
    headers = {"X-Auth-Token": api_key}
    url = f"https://api.football-data.org/v4{endpoint}"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 403:
            console.print("[red]BŁĄD: Brak dostępu do tej ligi w Twoim planie API.[/red]")
        return None
    except Exception as e:
        console.print(f"[red]Błąd połączenia: {e}[/red]")
        return None

# ================================================================
#    SILNIK PROGNOZY (Poisson)
# ================================================================
def run_prediction(home_team, away_team, df_results, df_standings, league_info, agg_score=None):
    # Prosta średnia goli ligi
    avg_goals = (df_results['gole_g'].mean() + df_results['gole_a'].mean()) / 2
    
    # Siła ataku/obrony (uproszczona na potrzeby v2.3)
    def get_strength(team):
        team_matches = df_results[(df_results['gospodarz'] == team) | (df_results['goscie'] == team)].tail(OSTATNIE_N)
        att = team_matches[team_matches['gospodarz'] == team]['gole_g'].mean() / avg_goals
        def_ = team_matches[team_matches['goscie'] == team]['gole_g'].mean() / avg_goals
        return att, def_

    att_h, def_h = get_strength(home_team)
    att_a, def_a = get_strength(away_team)
    
    # Lambdy bazowe
    lambda_h = att_h * def_a * avg_goals * BONUS_DOMOWY
    lambda_a = att_a * def_h * avg_goals
    
    # Mnożnik motywacji
    mot_h, label_h = calculate_motivation(home_team, df_standings, league_info['druzyny'])
    mot_a, label_a = calculate_motivation(away_team, df_standings, league_info['druzyny'])
    
    lambda_h *= mot_h
    lambda_a *= mot_a
    
    # Logika dwumeczu
    context_msg = ""
    if agg_score:
        lambda_h, lambda_a, context_msg = apply_two_leg_logic(lambda_h, lambda_a, agg_score[0], agg_score[1])
        
    # Prawdopodobieństwa
    probs = []
    for h in range(MAX_GOLE):
        for a in range(MAX_GOLE):
            p = poisson.pmf(h, lambda_h) * poisson.pmf(a, lambda_a)
            probs.append((h, a, p))
            
    # Wynik 1X2
    win = sum(p for h, a, p in probs if h > a)
    draw = sum(p for h, a, p in probs if h == a)
    loss = sum(p for h, a, p in probs if h < a)
    
    return {
        "1": win*100, "X": draw*100, "2": loss*100,
        "mot_h": label_h, "mot_a": label_a,
        "context": context_msg,
        "score": max(probs, key=lambda x: x[2])
    }

# ================================================================
#    GŁÓWNE MENU I OBSŁUGA
# ================================================================
def main():
    api_key = setup_api()
    
    while True:
        console.clear()
        console.print(Panel(f"[bold cyan]FootStats {VERSION}[/bold cyan]\n[dim]Analiza motywacji i wyników historycznych[/dim]", expand=False))
        
        table = Table(box=box.ROUNDED)
        table.add_column("Klawisz", style="yellow")
        table.add_column("Liga", style="white")
        
        for k, v in LIGI.items():
            table.add_row(k, f"{v['emoji']} {v['nazwa']}")
        
        console.print(table)
        wybor = Prompt.ask("Wybierz ligę (lub 'q' aby wyjść)")
        
        if wybor.lower() == 'q': break
        if wybor not in LIGI: continue
        
        league = LIGI[wybor]
        
        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}")) as progress:
            progress.add_task(description=f"Pobieranie danych dla {league['nazwa']}...", total=None)
            
            # Pobieranie tabeli
            data_standings = get_data(f"/competitions/{league['kod']}/standings", api_key)
            if not data_standings: continue
            
            rows = []
            for t in data_standings['standings'][0]['table']:
                rows.append({"Poz.": t['position'], "Druzyna": t['team']['shortName'], "M": t['playedGames'], "Pkt": t['points']})
            df_standings = pd.DataFrame(rows)
            
            # Pobieranie wyników
            data_matches = get_data(f"/competitions/{league['kod']}/matches?status=FINISHED", api_key)
            match_rows = []
            for m in data_matches['matches']:
                match_rows.append({
                    "gospodarz": m['homeTeam']['shortName'], 
                    "goscie": m['awayTeam']['shortName'],
                    "gole_g": m['score']['fullTime']['home'],
                    "gole_a": m['score']['fullTime']['away']
                })
            df_results = pd.DataFrame(match_rows)

        # Prosta symulacja meczu
        h_team = Prompt.ask("Gospodarz", choices=list(df_standings['Druzyna']))
        a_team = Prompt.ask("Gość", choices=list(df_standings['Druzyna']))
        
        res = run_prediction(h_team, a_team, df_results, df_standings, league)
        
        res_table = Table(title=f"Analiza: {h_team} vs {a_team}")
        res_table.add_column("Typ", justify="center")
        res_table.add_column("Szansa %", justify="center")
        res_table.add_column("Motywacja", justify="center")
        
        res_table.add_row("1", f"{res['1']:.1f}%", res['mot_h'])
        res_table.add_row("X", f"{res['X']:.1f}%", "-")
        res_table.add_row("2", f"{res['2']:.1f}%", res['mot_a'])
        
        console.print(res_table)
        console.print(f"[yellow]Najbardziej prawdopodobny wynik: {res['score'][0]}:{res['score'][1]}[/yellow]")
        if res['context']: console.print(f"[cyan]Komentarz: {res['context']}[/cyan]")
        
        Prompt.ask("\nNaciśnij Enter, aby kontynuować...")

if __name__ == "__main__":
    main()
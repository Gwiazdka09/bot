# FootStats — Harmonogram zadań (Windows Task Scheduler)

Instrukcja konfiguracji automatycznego uruchamiania bota **bez wyskakującego okna konsoli**.

---

## Pliki .bat

Utwórz poniższe pliki w katalogu `F:\bot\scripts\` (utwórz folder jeśli nie istnieje).

### `scripts\run_agent.bat` — codzienna analiza i kupon
```bat
@echo off
cd /d F:\bot
call .venv\Scripts\activate.bat
python -m footstats.daily_agent --faza final >> logs\scheduler_agent.log 2>&1
```

### `scripts\run_dashboard.bat` — uruchomienie serwera API (jednorazowo przy starcie systemu)
```bat
@echo off
cd /d F:\bot
call .venv\Scripts\activate.bat
start "" /B python -m uvicorn footstats.api.main:app --port 8000 >> logs\scheduler_dashboard.log 2>&1
```

### `scripts\run_results.bat` — aktualizacja wyników (po meczach)
```bat
@echo off
cd /d F:\bot
call .venv\Scripts\activate.bat
python -m footstats.scrapers.results_updater >> logs\scheduler_results.log 2>&1
```

---

## Konfiguracja Task Scheduler (bez okna konsoli)

### Krok 1 — Otwórz harmonogram
```
Win + R → taskschd.msc → Enter
```

### Krok 2 — Utwórz nowe zadanie
Kliknij **"Utwórz zadanie..."** (nie "Utwórz zadanie podstawowe").

### Krok 3 — Zakładka "Ogólne"
| Pole | Wartość |
|------|---------|
| Nazwa | `FootStats — Daily Agent` |
| Uruchom niezależnie czy użytkownik jest zalogowany | ✅ (zaznacz) |
| Uruchom z najwyższymi uprawnieniami | ✅ (zaznacz) |

### Krok 4 — Zakładka "Wyzwalacze" → Nowy
| Pole | Wartość |
|------|---------|
| Rozpocznij zadanie | Zgodnie z harmonogramem |
| Codziennie | ✅ |
| Godzina startu | `08:00:00` |
| Powtarzaj co | (opcjonalnie) `30 minut` przez `12 godzin` |

### Krok 5 — Zakładka "Akcje" → Nowy ⚠️ KLUCZOWE (brak okna konsoli)

| Pole | Wartość |
|------|---------|
| Akcja | Uruchom program |
| Program/skrypt | `wscript.exe` |
| Dodaj argumenty | `"F:\bot\scripts\silent_run.vbs" "F:\bot\scripts\run_agent.bat"` |
| Uruchom w | `F:\bot` |

> **Dlaczego `wscript.exe`?** Uruchamia `.bat` przez VBScript bez tworzenia okna konsoli (`cmd.exe` zawsze pokazuje okno).

### Krok 6 — Utwórz `scripts\silent_run.vbs`
```vbscript
' silent_run.vbs — uruchamia .bat bez okna konsoli
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """" & WScript.Arguments(0) & """", 0, False
Set WshShell = Nothing
```

### Krok 7 — Zakładka "Warunki"
- Odznacz **"Uruchom tylko gdy komputer jest zasilany z sieci"** (jeśli laptop)
- Odznacz **"Zatrzymaj jeśli komputer przełączy się na zasilanie bateryjne"**

### Krok 8 — Zakładka "Ustawienia"
- ✅ Uruchom zadanie tak szybko jak to możliwe, jeśli zaplanowane uruchomienie zostało pominięte
- ✅ Jeśli zadanie nie zakończy się po: `30 minut` → Zatrzymaj je

---

## Harmonogram kompletny (zalecany)

| Zadanie | Wyzwalacz | Skrypt | Opis |
|---------|-----------|--------|------|
| FootStats — Dashboard | Przy uruchomieniu systemu | `run_dashboard.bat` | Serwer API na porcie 8000 |
| FootStats — Daily Agent | Codziennie 08:00 | `run_agent.bat` | Analiza + kupon dnia |
| FootStats — Daily Agent 2 | Codziennie 16:00 | `run_agent.bat` | Aktualizacja przed wieczornymi meczami |
| FootStats — Wyniki | Codziennie 23:30 | `run_results.bat` | Aktualizacja wyników zakończonych meczów |

---

## Weryfikacja działania

```powershell
# Sprawdź logi po pierwszym uruchomieniu
Get-Content F:\bot\logs\scheduler_agent.log -Tail 30

# Sprawdź status zadań
Get-ScheduledTask | Where-Object {$_.TaskName -like "FootStats*"}

# Uruchom ręcznie testowo
Start-ScheduledTask -TaskName "FootStats — Daily Agent"
```

---

## Rozwiązywanie problemów

| Problem | Rozwiązanie |
|---------|-------------|
| Zadanie nie uruchamia się | Sprawdź czy ścieżka do `.venv\Scripts\activate.bat` jest poprawna |
| Błąd "nie znaleziono modułu" | Upewnij się że `.bat` aktywuje właściwe venv (`call .venv\Scripts\activate.bat`) |
| Okno konsoli nadal się pojawia | Sprawdź czy używasz `wscript.exe` + `silent_run.vbs`, nie `cmd.exe` |
| Log jest pusty | Dodaj do `.bat`: `echo %date% %time% START >> logs\debug.log` na początku |
| Zadanie uruchamia się ale natychmiast kończy | Dodaj `pause` na końcu `.bat` i sprawdź co się wyświetla |

# Coupon Settlement — Rozliczanie Zaległych Kuponów

## Problem

Kupony z wczoraj (np. Djurgårdens, SC Oțelul) wiszą jako **ACTIVE**, ponieważ:
1. API-Football free plan zwraca wyniki tylko dla meczów w bieżącym oknie (~3 dni)
2. Starsze mecze nie mają wyników w API
3. `evening_agent.py` nie może ich rozliczyć

## Rozwiązanie

### Architektura

1. **Scraper FlashScore** (`scrapers/flashscore_results.py`)
   - BeautifulSoup na FlashScore
   - Cache per data
   - Fallback gdy API-Football zawiedzie

2. **Rozliczanie** (`core/coupon_settlement.py`)
   - API-Football → FlashScore → RAG feedback
   - WIN: aktualizuj bankroll
   - LOSE: wyślij do `post_match_analyzer.py` (RAG feedback)

3. **API Endpoint** (`api/main.py`)
   - POST `/api/coupons/settle` — ręczne rozliczenie

---

## Użycie

### Opcja 1: Skrypt Python (lokalne)

```bash
# Test — tylko pokaż co by zmienił
python scripts/settle_coupons.py --days 3 --dry

# Rzeczywiste rozliczenie
python scripts/settle_coupons.py --days 3
```

### Opcja 2: API Endpoint (z dashboardu/curl)

#### cURL

```bash
# Test — dry-run
curl -X POST http://localhost:8000/api/coupons/settle \
  -H "Content-Type: application/json" \
  -d '{
    "days_back": 3,
    "dry_run": true
  }'

# Rzeczywiste rozliczenie
curl -X POST http://localhost:8000/api/coupons/settle \
  -H "Content-Type: application/json" \
  -d '{
    "days_back": 3,
    "dry_run": false
  }'
```

#### Python

```python
import requests

# Test — dry-run
response = requests.post(
    "http://localhost:8000/api/coupons/settle",
    json={
        "days_back": 3,
        "dry_run": True,
    }
)
print(response.json())

# Rzeczywiste rozliczenie
response = requests.post(
    "http://localhost:8000/api/coupons/settle",
    json={
        "days_back": 3,
        "dry_run": False,
    }
)
print(response.json())
```

#### JavaScript (z dashboardu)

```javascript
async function settleCoupons(daysBack = 3, dryRun = true) {
  const response = await fetch("/api/coupons/settle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      days_back: daysBack,
      dry_run: dryRun,
    }),
  });
  return response.json();
}

// Test
const result = await settleCoupons(3, true);
console.log(result);
// {
//   "ok": true,
//   "settled": 2,
//   "partial": 1,
//   "errors": 0,
//   "message": "Rozliczono 2, częściowych 1, błędów 0"
// }

// Rzeczywiste rozliczenie
const result = await settleCoupons(3, false);
console.log(result);
```

---

## Odpowiedź API

```json
{
  "ok": true,
  "settled": 2,
  "partial": 1,
  "errors": 0,
  "message": "Rozliczono 2, częściowych 1, błędów 0"
}
```

- **settled**: liczba zamkniętych kuponów (WIN lub LOSE)
- **partial**: liczba kuponów czekających na brakujące wyniki
- **errors**: liczba błędów podczas rozliczania

---

## Parametry

### `settle_active_coupons()`

```python
settle_active_coupons(
    days_back: int = 3,        # ile dni wstecz sprawdzać
    dry_run: bool = False,     # tylko test bez zmian
    verbose: bool = True,      # drukuj logi
) -> dict
```

---

## Logika Rozliczania

Dla każdego ACTIVE kuponu:

1. **Pobierz wyniki**
   ```
   API-Football (prioritet)
   └─ FlashScore fallback (jeśli API nie ma wyniku)
   ```

2. **Oceń każdą nogę** (tip)
   - Over 2.5: wynik > 2.5 goli
   - 1/Home: drużyna gospodarza wygra
   - 2/Away: drużyna gościa wygra
   - Draw: remis
   - Itp.

3. **Zamknij kupon**
   ```
   WIN (wszystkie nogi trafione)
   └─ aktualizuj bankroll
      └─ INSERT INTO bankroll_history

   LOSE (przynajmniej jedna noga nietrafiiona)
   └─ wyślij do RAG feedback
      └─ INSERT INTO ai_feedback
   ```

---

## FlashScore Fallback

Gdy API-Football brakuje wyniku:

1. Scraper pobiera HTML ze FlashScore
2. BeautifulSoup parsuje wynik (regex + JSON-LD)
3. Cache: `cache/flashscore/YYYY-MM-DD.json`
4. Wynik: `"2-1"` lub `None`

---

## RAG Feedback

Dla każdego LOSE kuponu:

```python
uczy_sie_z_porażek(
    coupon_id=1,
    lesson_text="Kupon nietrafiany:\n• Team A vs Team B: Over 2.5 (wynik: 1-0)",
    ai_model="manual_settlement",
)
```

Zapisuje się w `ai_feedback` table → LLM Groq je czyta przy następnym kuponnie.

---

## Troubleshooting

### "NOT FOUND" — nie znaleziono wyniku

- Mogą być starsze mecze spoza okna API-Football
- FlashScore nie ma meczu (zupełnie małe ligi)
- **Rozwiązanie**: ręcznie poinformuj o wyniku lub pomiń kupon

### PARTIAL — czekaj na wyniki

- Mecz jeszcze się nie odbył lub wynik nie jest dostępny
- **Rozwiązanie**: uruchom ponownie za godzinę

### "Telegram" — powiadomienia o wynikach

Jeśli `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID` są w `.env`:
- Każdy LOSE kupon wyśle powiadomienie do RAG
- Każdy WIN kupon aktualizuje bankroll

---

## Harmonogram

Rekomendacje:

```cron
# Codziennie o 21:00 (po meczach)
0 21 * * * python scripts/settle_coupons.py --days 3

# Ręcznie ze dashboardu
POST /api/coupons/settle {"days_back": 3, "dry_run": false}
```

---

## Wersja

- **v3.2** — 2026-04-18
- Autorzy: Claude + Jakub

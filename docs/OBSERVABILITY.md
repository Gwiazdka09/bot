# FootStats — Observability & Monitoring

## Langfuse Integration

Langfuse jest narzędziem do monitorowania i debugowania LLM aplikacji. Śledzi:
- Prośby do Groq API
- Czas odpowiedzi
- Token usage
- Błędy i wyjątki
- RAG feedback loop

### Konfiguracja Langfuse

#### 1. Utwórz konto na Langfuse

Przejdź do https://cloud.langfuse.com i załóż bezpłatne konto.

#### 2. Pobierz klucze API

Po zalogowaniu:
1. Przejdź do **Settings** → **API Keys**
2. Skopiuj:
   - **Public Key** (zaczynający się od `pk_`)
   - **Secret Key** (zaczynający się od `sk_`)

#### 3. Dodaj klucze do `.env`

Edytuj `.env` w katalogu głównym projektu:

```bash
# Langfuse Configuration
LANGFUSE_PUBLIC_KEY=pk_your_public_key_here
LANGFUSE_SECRET_KEY=sk_your_secret_key_here
LANGFUSE_HOST=https://cloud.langfuse.com
```

**WAŻNE**: Nigdy nie commituj `.env` do git! Plik jest już w `.gitignore`.

#### 4. Zintegruj Langfuse w `ai/analyzer.py`

W funkcji `ai_analiza_pewniaczki()` dodaj obsługę Langfuse:

```python
from langfuse import Langfuse
import os

# Inicjalizuj Langfuse
langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
)

def ai_analiza_pewniaczki(...):
    # Zaloguj tracer dla tej analizy
    with langfuse.trace(
        name="ai_analiza_pewniaczki",
        input={
            "home": home_team,
            "away": away_team,
            "forma": forma_data
        }
    ):
        # Twój kod analizy...
        
        # Loguj Groq call
        with langfuse.span(name="groq_api_call"):
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[...],
                temperature=0.7
            )
            
        # Loguj output
        langfuse.event(
            name="ai_analysis_complete",
            output={
                "tip": tip,
                "decision_score": decision_score,
                "groq_reasoning": groq_reasoning
            }
        )
```

#### 5. Weryfikacja

Po kilku uruchomieniach:
1. Przejdź do https://cloud.langfuse.com
2. Kliknij **Dashboard**
3. Powinieneś widzieć trace'y z Groq callów

### Monitoring RAG Feedback Loop

Langfuse automatycznie śledzi:

- **LLM Cost**: Ile tokenów kosztuje każdy call do Groq
- **Latency**: Jak długo trwają analizy
- **Error Rate**: Ile błędów w procesie analizy
- **Feedback Records**: Ile lessons zapisaliśmy do `ai_feedback`

W dashboardzie Langfuse:
- **Traces** → Full history of all LLM calls
- **Analytics** → Cost, latency, error trends
- **Logs** → Real-time monitoring

### Troubleshooting

#### Langfuse nie rejestruje danych

1. Sprawdź czy `.env` ma prawidłowe klucze:
   ```bash
   echo $LANGFUSE_PUBLIC_KEY
   echo $LANGFUSE_SECRET_KEY
   ```

2. Sprawdź czy Langfuse jest zaimportowany:
   ```python
   python -c "from langfuse import Langfuse; print('OK')"
   ```

3. Uruchom daily agent w debug mode:
   ```bash
   LANGFUSE_DEBUG=1 python -m footstats.daily_agent --faza final
   ```

#### Błędy autoryzacji

- Sprawdź czy klucze zaczyna się od `pk_` (public) i `sk_` (secret)
- Regeneruj klucze w Langfuse Settings jeśli są stare

### Dokumentacja

- **Langfuse Docs**: https://langfuse.com/docs
- **Python SDK**: https://github.com/langfuse/langfuse-python
- **Integration Examples**: https://langfuse.com/docs/integrations

### Kolejne Kroki

1. **Metrics Dashboard**: Dodaj custom metrics (Kelly alignment, hit-rate, etc.)
2. **Alerts**: Konfiguruj alerty dla błędów > 5% lub latency > 10s
3. **Cost Analysis**: Śledź koszt Groq API monthly

---

## Inne Narzędzia Observability

### Strukturalne Logowanie

Projekt używa `logging` module w Pythonie. Logi są zapisywane do:
- `logs/daily_agent.log`
- `logs/evening_agent.log`

Każdy log zawiera:
- Timestamp
- Level (DEBUG, INFO, WARNING, ERROR)
- Module name
- Message

### Database Audit

SQLite ma wbudowany audit trail. Aby sprawdzić históię zmian:

```sql
SELECT * FROM ai_feedback ORDER BY created_at DESC LIMIT 10;
SELECT * FROM coupons WHERE created_at > datetime('now', '-7 days');
```

---

## Best Practices

1. **Don't log secrets**: Nigdy nie loguj API keys ani sensitive data
2. **Structured logging**: Używaj dict/JSON zamiast plain strings
3. **Levels**: INFO dla normalnych operacji, ERROR dla rzeczywistych błędów
4. **Sampling**: W produkcji, sample 1% callów jeśli koszt jest zbyt wysoki
5. **Retention**: Langfuse bezpłatnie przechowuje dane przez 30 dni

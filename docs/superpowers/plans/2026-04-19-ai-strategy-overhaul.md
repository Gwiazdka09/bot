# AI Analysis Strategy Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform AI betting analysis from "helpful assistant" to "ruthless data analyst" with form-based weighting (60% recent form, 20% H2H), RAG-enhanced historical context, and confidence filtering (≥75% to survive backtest).

**Architecture:** 
1. Replace system prompt with aggressive, data-driven persona
2. Add form analysis layer (last 5 matches) with explicit 60/20 weighting
3. Integrate RAG similar matches into prompt (reusing existing `pobierz_ostatnie_wnioski()` pattern)
4. Add `confidence_score` field (0-100) to JSON output and apply ≥75 filter in backtest
5. Keep existing structure; surgical edits only

**Tech Stack:** Python, Groq LLM, SQLite (predictions table), existing RAG system

---

## File Structure

**Modify:**
- `src/footstats/ai/analyzer.py` — Lines 23-60 (system prompt), lines 950-1100 (ai_analiza_pewniaczki logic, prompt construction)
- `src/footstats/core/backtest_engine.py` — Add confidence ≥75 filter in `_check_prediction_result()`

**Create:**
- `tests/test_form_analysis.py` — Test form analysis function
- `tests/test_backtest_confidence_filter.py` — Test that backtest respects confidence threshold

---

## Task Breakdown

### Task 1: Replace System Prompt with Ruthless Persona

**Files:**
- Modify: `src/footstats/ai/analyzer.py:23-60`

- [ ] **Step 1: Read current system prompt**

```bash
sed -n '23,60p' F:/bot/src/footstats/ai/analyzer.py
```

- [ ] **Step 2: Replace _SYSTEM_TYPER with aggressive version**

Replace lines 23-60 in `src/footstats/ai/analyzer.py`:

```python
_SYSTEM_TYPER = """Jesteś BEZWZGLĘDNYM ANALITYKIEM DANYCH BUKMACHERSKICH. Nie bądź miły — bądź precyzyjny.

KRYTERIA DECYZJI:
1. FORMA (60% wagi): Przeanalizuj ostatnie 5 meczów każdej drużyny. Zwycięstwa vs porażki. Gole dla/przeciw. Trend wzrostowy czy spadkowy?
2. H2H (20% wagi): Historia bezpośrednich starć. Kto wygrywa, gole, pattern.
3. KURSY (20% wagi): Jeśli kurs na faworyta <1.40, ODRZUĆ ten typ. Szukaj innego rynku (Over 2.5, BTTS, itp).

PRZED WYSTAWIENIEM TYPU:
- Podsumuj formę: "Ostatnie 5: W-W-P-W-W (trend +)"
- Podsumuj H2H: "3x Drużyna A wygrała, średnio 2.3 gola/mecz"
- Sprawdź kursy: "Faworytu <1.40 — UNIKAJ tego typu"

PEWNOŚĆ (confidence_score 0-100):
- 85-100: Forma wyraźna + H2H jasne + kurs rozumny
- 70-84: Forma ok + H2H mieszane + kurs powiedzmy
- 50-69: Brak jasnego trendu, ryzykowne
- <50: ODRZUĆ (nigdy nie stawiaj)

JSON SCHEMA (OBOWIĄZKOWY):
{
  "typ": "1" | "2" | "X" | "Over 2.5" | "Under 2.5" | "BTTS" | "No BTTS",
  "kurs": 1.80,
  "pewnosc_pct": 75,
  "uzasadnienie": "Krótko: forma, H2H, kursy.",
  "value_bet": true | false
}

Odpowiadaj zawsze po polsku. Zawsze zwracaj JSON. Bądź konkretny."""
```

- [ ] **Step 3: Verify replacement**

```bash
grep -A 5 "_SYSTEM_TYPER = " F:/bot/src/footstats/ai/analyzer.py
```

- [ ] **Step 4: Commit**

```bash
git add src/footstats/ai/analyzer.py && git commit -m "feat: replace system prompt with ruthless data analyst persona"
```

---

### Task 2: Add Form Analysis Layer

**Files:**
- Modify: `src/footstats/ai/analyzer.py` — Add `_analizuj_forme()` function around line 170

- [ ] **Step 1: Write test for form analysis**

Create `tests/test_form_analysis.py`:

```python
import pytest
from src.footstats.ai.analyzer import _analizuj_forme


def test_analizuj_forme_returns_correct_stats():
    """Form analysis should calculate wins, losses, goals avg, trend."""
    forma = _analizuj_forme([
        {"result": "1", "scored": 2, "conceded": 0},
        {"result": "1", "scored": 1, "conceded": 0},
        {"result": "0", "scored": 1, "conceded": 2},
        {"result": "1", "scored": 3, "conceded": 1},
        {"result": "1", "scored": 2, "conceded": 0},
    ])
    
    assert forma["wins"] == 4
    assert forma["losses"] == 1
    assert forma["draws"] == 0
    assert forma["gf_avg"] == 1.8
    assert forma["ga_avg"] == 0.6
    assert forma["trend"] in ["strong_up", "up", "stable", "down", "strong_down"]


def test_analizuj_forme_empty_list():
    """Should handle empty match list gracefully."""
    forma = _analizuj_forme([])
    assert forma["wins"] == 0
    assert forma["gf_avg"] == 0
```

- [ ] **Step 2: Implement _analizuj_forme function**

Add to `src/footstats/ai/analyzer.py` around line 170:

```python
def _analizuj_forme(mecze: list) -> dict:
    """Analyze last 5 matches: wins, losses, goals for/against, trend."""
    if not mecze:
        return {
            "wins": 0, "losses": 0, "draws": 0,
            "gf_avg": 0.0, "ga_avg": 0.0,
            "trend": "unknown"
        }
    
    wins = sum(1 for m in mecze if m.get("result") == "1")
    losses = sum(1 for m in mecze if m.get("result") == "0")
    draws = sum(1 for m in mecze if m.get("result") == "X")
    
    gf_sum = sum(m.get("scored", 0) for m in mecze)
    ga_sum = sum(m.get("conceded", 0) for m in mecze)
    gf_avg = round(gf_sum / len(mecze), 2)
    ga_avg = round(ga_sum / len(mecze), 2)
    
    if len(mecze) >= 2:
        early_wins = sum(1 for m in mecze[:2] if m.get("result") == "1")
        recent_wins = sum(1 for m in mecze[-2:] if m.get("result") == "1")
        if recent_wins > early_wins:
            trend = "strong_up" if recent_wins == 2 else "up"
        elif recent_wins < early_wins:
            trend = "strong_down" if recent_wins == 0 else "down"
        else:
            trend = "stable"
    else:
        trend = "unknown"
    
    return {
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "gf_avg": gf_avg,
        "ga_avg": ga_avg,
        "trend": trend
    }
```

- [ ] **Step 3: Run test**

```bash
pytest tests/test_form_analysis.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/footstats/ai/analyzer.py tests/test_form_analysis.py && git commit -m "feat: add form analysis function (last 5 matches)"
```

---

### Task 3: Integrate RAG Similar Matches into Prompt

**Files:**
- Modify: `src/footstats/ai/analyzer.py` — Add `_pobierz_podobne_mecze()` function, integrate into `ai_analiza_pewniaczki()`

- [ ] **Step 1: Add RAG helper function**

Add to `src/footstats/ai/analyzer.py` around line 240:

```python
def _pobierz_podobne_mecze(home: str, away: str, n: int = 3) -> str:
    """Fetch N similar historical matches from RAG ai_feedback table."""
    try:
        from src.footstats.ai.rag import pobierz_ostatnie_wnioski
        lessons = pobierz_ostatnie_wnioski(5)
        
        similar = []
        for lesson in lessons:
            if home.lower() in lesson.lower() or away.lower() in lesson.lower():
                similar.append(lesson)
                if len(similar) >= n:
                    break
        
        if not similar:
            return ""
        
        header = f"\nPODOBNE MECZE Z HISTORII (nauka z przeszłości):\n"
        for i, lesson in enumerate(similar, 1):
            header += f"{i}. {lesson[:100]}…\n"
        return header
    except Exception:
        return ""
```

- [ ] **Step 2: Integrate RAG into ai_analiza_pewniaczki prompt**

Find where prompt_user is built (around line 1000) and before `_zapytaj_typera()` call, add:

```python
rag_similar = _pobierz_podobne_mecze(home, away, n=3)
prompt_user = f"{prompt_user}{rag_similar}"
```

- [ ] **Step 3: Verify integration**

```bash
grep -n "_pobierz_podobne_mecze" F:/bot/src/footstats/ai/analyzer.py
```

- [ ] **Step 4: Commit**

```bash
git add src/footstats/ai/analyzer.py && git commit -m "feat: inject RAG similar matches into AI prompt"
```

---

### Task 4: Add Confidence Filter to Backtest Engine

**Files:**
- Modify: `src/footstats/core/backtest_engine.py` — `_check_prediction_result()` method
- Create: `tests/test_backtest_confidence_filter.py`

- [ ] **Step 1: Write test for confidence filter**

Create `tests/test_backtest_confidence_filter.py`:

```python
import pytest
from src.footstats.core.backtest_engine import BacktestEngine


def test_confidence_below_75_excluded():
    """Predictions with confidence < 75 should be skipped."""
    engine = BacktestEngine()
    engine._check_prediction_result(
        match_dict={"home": "Bayern", "away": "Dortmund", "date": "2025-01-15", "goals_home": 2, "goals_away": 1},
        tip="1",
        confidence=60,
        kupon_type="single"
    )
    stats = engine.get_stats()
    assert stats.get("total_predictions", 0) == 0


def test_confidence_75_or_above_included():
    """Predictions with confidence >= 75 should be counted."""
    engine = BacktestEngine()
    engine._check_prediction_result(
        match_dict={"home": "Bayern", "away": "Dortmund", "date": "2025-01-15", "goals_home": 2, "goals_away": 1},
        tip="1",
        confidence=80,
        kupon_type="single"
    )
    stats = engine.get_stats()
    assert stats.get("total_predictions", 0) == 1
```

- [ ] **Step 2: Implement confidence filter**

Find `_check_prediction_result()` in `src/footstats/core/backtest_engine.py` and add confidence parameter + check:

```python
def _check_prediction_result(self, match_dict: dict, tip: str, confidence: int, kupon_type: str) -> None:
    """Check if prediction was correct. Skip if confidence < 75."""
    if confidence < 75:
        self.stats["skipped_low_confidence"] = self.stats.get("skipped_low_confidence", 0) + 1
        return
    # ... rest of method logic ...
```

- [ ] **Step 3: Update all calls to pass confidence**

```bash
grep -n "_check_prediction_result" F:/bot/src/footstats/core/backtest_engine.py
```

Ensure confidence from `ai_confidence` column is passed.

- [ ] **Step 4: Run test**

```bash
pytest tests/test_backtest_confidence_filter.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/footstats/core/backtest_engine.py tests/test_backtest_confidence_filter.py && git commit -m "feat: add confidence >=75 filter to backtest engine"
```

---

### Task 5: Update JSON Schema Documentation

**Files:**
- Modify: `src/footstats/ai/analyzer.py` — Ensure confidence_score is documented

- [ ] **Step 1: Verify current schema includes pewnosc_pct**

```bash
grep -n "pewnosc_pct" F:/bot/src/footstats/ai/analyzer.py | head -3
```

- [ ] **Step 2: Commit system prompt update (already done in Task 1)**

System prompt in Task 1 already includes JSON schema with `pewnosc_pct`. No additional work needed.

---

### Task 6: Integration Test

**Files:**
- Create: `tests/test_ai_pipeline_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_ai_pipeline_integration.py`:

```python
import pytest
from src.footstats.ai.analyzer import ai_analiza_pewniaczki


@pytest.mark.integration
def test_full_pipeline_returns_confidence_scores():
    """AI pipeline should return JSON with confidence scores."""
    wyniki = [{
        "data": "2025-01-15",
        "liga": "ekstraklasa",
        "mecze": [{
            "gospodarz": "Bayern",
            "goscie": "Dortmund",
            "kurs_1": 1.80,
            "kurs_2": 3.50,
            "kurs_x": 3.40,
            "kurs_over": 2.10,
            "id_api": 12345
        }]
    }]
    
    result = ai_analiza_pewniaczki(wyniki=wyniki, pobierz_forme=True, metoda="backtest")
    
    assert "top3" in result
    assert "kupon_a" in result
    assert "kupon_b" in result
```

- [ ] **Step 2: Commit**

```bash
git add tests/test_ai_pipeline_integration.py && git commit -m "test: add integration test for AI pipeline"
```

---

### Task 7: Validation Run

**Files:**
- No changes; test existing script

- [ ] **Step 1: Run backtest with new changes**

```bash
cd F:/bot && python -m src.footstats.core.backtest_engine --days 7 --stawka 10 --dry-run
```

- [ ] **Step 2: Verify confidence filtering in output**

Check output for `skipped_low_confidence` count and win rate stats.

- [ ] **Step 3: Document results**

If backtest output format changed, commit it.

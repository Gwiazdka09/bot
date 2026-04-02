import time
import requests
from datetime import datetime, timedelta
from footstats.utils.cache import _cache_get, _cache_set
from footstats.utils.console import console
from footstats.config import ENV_BZZOIRO, PEWNIACZEK_DNI, BZZOIRO_MAX_ROZN

# ================================================================
#  MODUL 4c – BZZOIRO (sports.bzzoiro.com) v2.7
#  DARMOWY bez limitu: ML predictions CatBoost + kursy bukmacherskie
# ================================================================

class BzzoiroClient:
    """
    Klient sports.bzzoiro.com.
    BEZ LIMITU zapytan. ML CatBoost predictions + odsy bukmacherskie.
    Uzywa do cross-walidacji i wzbogacenia predykcji FootStats.
    Header: Authorization: Token KEY
    """
    BASE = "https://sports.bzzoiro.com/api"

    # Mapowanie kodow lig Bzzoiro do ID
    _LIGA_IDS = {
        "PL":  1,  "PPL": 2,   "PD":  3,   "SA":  4,   "BL1": 5,
        "FL1": 6,  "CL":  7,   "ELC": 12,  "DED": 10,  "BSA": 9,
        "EKS": None,  # nie ma Ekstraklasy w Bzzoiro
    }

    def __init__(self, api_key: str):
        self.headers = {"Authorization": f"Token {api_key}"}
        self._valid: bool | None = None

    def waliduj(self) -> tuple[bool, str]:
        """Sprawdza poprawnosc klucza."""
        try:
            r = requests.get(f"{self.BASE}/leagues/",
                             headers=self.headers, timeout=10)
            if r.status_code == 200:
                self._valid = True
                n = len(r.json().get("results", []))
                return True, f"OK – {n} lig dostepnych"
            elif r.status_code == 401:
                self._valid = False
                return False, "Nieprawidlowy klucz Bzzoiro (401)"
            else:
                self._valid = False
                return False, f"HTTP {r.status_code}"
        except Exception as e:
            self._valid = False
            return False, str(e)

    def _get(self, path: str, params: dict = None) -> dict | None:
        cache_key = f"bz:{path}:{params}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        try:
            r = requests.get(f"{self.BASE}{path}",
                             headers=self.headers, params=params, timeout=15)
            if r.status_code == 200:
                data = r.json()
                _cache_set(cache_key, data)
                return data
        except Exception:
            pass
        return None

    def nadchodzace_tygodnia(self, liga_kod: str = None) -> list:
        """
        Pobiera nadchodzace mecze z nastepnych 7 dni.
        Opcjonalnie filtruje po lidze (kod wewnetrzny).
        Zwraca liste eventow z predykcjami ML.
        """
        data_od  = datetime.now().strftime("%Y-%m-%d")
        data_do  = (datetime.now() + timedelta(days=PEWNIACZEK_DNI)).strftime("%Y-%m-%d")
        params   = {"date_from": data_od, "date_to": data_do, "upcoming": "true"}

        liga_id = None
        if liga_kod:
            liga_id = self._LIGA_IDS.get(liga_kod)
        if liga_id:
            params["league"] = liga_id

        dane = self._get("/events/", params=params)
        return dane.get("results", []) if dane else []

    def predykcja_meczu(self, event_id: int) -> dict | None:
        """Pobiera predykcje ML dla konkretnego meczu."""
        dane = self._get(f"/predictions/", params={"event": event_id})
        if not dane:
            return None
        wyniki = dane.get("results", [])
        return wyniki[0] if wyniki else None

    def predykcje_tygodnia(self, liga_kod: str = None) -> list:
        """
        Pobiera predykcje ML na caly tydzien z /predictions/.
        Zwraca liste slownikow z kompletna analiza ML i kursami.
        """
        data_od = datetime.now().strftime("%Y-%m-%d")
        data_do = (datetime.now() + timedelta(days=PEWNIACZEK_DNI)).strftime("%Y-%m-%d")
        params  = {"date_from": data_od, "date_to": data_do}

        liga_id = None
        if liga_kod:
            liga_id = self._LIGA_IDS.get(liga_kod)
        if liga_id:
            params["league"] = liga_id

        dane = self._get("/predictions/", params=params)
        preds = dane.get("results", []) if dane else []

        wynik = []
        for pred in preds:
            ev = pred.get("event") or {}

            # Liga
            liga_obj = ev.get("league", {})
            liga_str = liga_obj.get("name", "?") if isinstance(liga_obj, dict) else str(liga_obj)

            # Data/godzina z event_date ISO
            ev_date = str(ev.get("event_date", ""))
            data    = ev_date[:10]
            godzina = ev_date[11:16]

            # pred_ml w formacie zgodnym z _bzz_parse_prob (Format E: prob_*)
            pred_ml = None
            if pred.get("prob_home_win") is not None:
                # Most likely score: "0-1" → {"home": 0, "away": 1}
                mls_raw = str(pred.get("most_likely_score") or "1-1")
                try:
                    mg, ma = mls_raw.split("-", 1)
                    mls = {"home": int(mg), "away": int(ma)}
                except Exception:
                    mls = {"home": 1, "away": 0}

                pred_ml = {
                    "prob_home_win": pred["prob_home_win"],
                    "prob_draw":     pred.get("prob_draw", 0),
                    "prob_away_win": pred.get("prob_away_win", 0),
                    "prob_over_25":  pred.get("prob_over_25", 0),
                    "prob_btts_yes": pred.get("prob_btts_yes", 0),
                    "most_likely_score": mls,
                    "expected_home_goals": pred.get("expected_home_goals"),
                    "expected_away_goals": pred.get("expected_away_goals"),
                }

            # Kursy z event
            odds = None
            if ev.get("odds_home") is not None:
                odds = {
                    "home":      ev.get("odds_home"),
                    "draw":      ev.get("odds_draw"),
                    "away":      ev.get("odds_away"),
                    "over_2_5":  ev.get("odds_over_25"),
                    "under_2_5": ev.get("odds_under_25"),
                    "btts":      ev.get("odds_btts_yes"),
                }

            wynik.append({
                "id":      ev.get("id"),
                "gosp":    ev.get("home_team"),
                "gosc":    ev.get("away_team"),
                "liga":    liga_str,
                "data":    data,
                "godzina": godzina,
                "status":  ev.get("status", "notstarted"),
                "pred_ml": pred_ml,
                "odds":    odds,
            })
        return wynik

    @staticmethod
    def porownaj_z_poisson(pw_pois: float, px_pois: float, pp_pois: float,
                            pred_ml: dict | None) -> dict:
        """
        Porownuje predykcje Poissona z ML Bzzoiro.
        Zwraca slownik z informacja o zgodnosci.
        """
        if not pred_ml:
            return {"zgodnosc": None, "opis": "Bzzoiro: brak danych ML"}

        try:
            wyp_ml = _bzz_parse_prob(pred_ml)
            if wyp_ml is None:
                return {"zgodnosc": None, "opis": "Bzzoiro: nieznany format danych ML"}
            ml_1, ml_x, ml_2 = wyp_ml[0], wyp_ml[1], wyp_ml[2]

            # Faworyt wg obu modeli
            faw_pois = "1" if pw_pois > max(px_pois, pp_pois) else (
                        "X" if px_pois > pp_pois else "2")
            faw_ml   = "1" if ml_1 > max(ml_x, ml_2) else (
                        "X" if ml_x > ml_2 else "2")

            zgodnosc = (faw_pois == faw_ml)

            # Roznica procentowa na faworycie
            if faw_pois == "1": r = abs(pw_pois - ml_1)
            elif faw_pois == "X": r = abs(px_pois - ml_x)
            else: r = abs(pp_pois - ml_2)

            alert = r > BZZOIRO_MAX_ROZN

            return {
                "zgodnosc":    zgodnosc,
                "alert":       alert,
                "ml_1":        round(ml_1,1),
                "ml_x":        round(ml_x,1),
                "ml_2":        round(ml_2,1),
                "roznica_max": round(r, 1),
                "faw_pois":    faw_pois,
                "faw_ml":      faw_ml,
                "opis": (
                    f"Poisson: 1={pw_pois:.0f}% X={px_pois:.0f}% 2={pp_pois:.0f}% | "
                    f"ML Bzzoiro: 1={ml_1:.0f}% X={ml_x:.0f}% 2={ml_2:.0f}%"
                    + (f" [ALERT: roznica {r:.0f}%!]" if alert else "")
                ),
            }
        except Exception:
            return {"zgodnosc": None, "opis": "Bzzoiro: blad parsowania ML"}


def _bzz_parse_prob(pred_ml: dict) -> tuple:
    """
    Uniwersalny parser Bzzoiro – WSZYSTKIE znane formaty API sports.bzzoiro.com.

    Zbadane formaty:
      Format A: {percent: {home:"55%", draw:"25%", away:"20%"}}  <- GLOWNY
      Format B: {home_win_prob:0.55, draw_prob:0.25, away_win_prob:0.20}
      Format C: {home:55, draw:25, away:20}
      Format D: zagniezdzone {predictions:{...}} lub {prediction:{...}}

    Zwraca (pw, pr, pp, bt, o25) jako procenty 0-100 lub None.
    """
    if not pred_ml or not isinstance(pred_ml, dict):
        return None

    def p(v):
        if v is None:
            return 0.0
        try:
            f = float(str(v).strip().rstrip('%'))
            # UWAGA: granica 1.0 jest niejednoznaczna.
            # Uzywamy SCISLEGO < 1.0 zamiast <= 1.0:
            #   0.55 → ulamek → *100 = 55.0  ✓
            #   1.0  → procent → 1.0          ✓ (1% to rzadkie ale poprawne)
            #   55.0 → procent → 55.0         ✓
            return f * 100 if 0 < f < 1.0 else f
        except (ValueError, TypeError):
            return 0.0

    def norm(pw, pr, pp, bt=0.0, o25=0.0):
        s = pw + pr + pp or 100.0
        return (round(pw/s*100, 1), round(pr/s*100, 1),
                round(100 - pw/s*100 - pr/s*100, 1),
                round(min(max(bt, 0), 100), 1),
                round(min(max(o25, 0), 100), 1))

    # Format A: percent.home/draw/away (glowny format Bzzoiro)
    pct = pred_ml.get("percent") or pred_ml.get("percentages")
    if isinstance(pct, dict):
        pw, pr, pp = p(pct.get("home")), p(pct.get("draw")), p(pct.get("away"))
        if pw + pr + pp > 5:
            bt  = p(pct.get("btts") or pred_ml.get("btts", 0))
            o25 = p(pct.get("over_2_5") or pred_ml.get("over_2_5", 0))
            return norm(pw, pr, pp, bt, o25)

    # Format B: home_win_prob / draw_prob / away_win_prob
    if "home_win_prob" in pred_ml:
        pw = p(pred_ml.get("home_win_prob"))
        pr = p(pred_ml.get("draw_prob"))
        pp = p(pred_ml.get("away_win_prob"))
        if pw + pr + pp > 5:
            return norm(pw, pr, pp,
                        p(pred_ml.get("btts", 0)),
                        p(pred_ml.get("over_2_5", 0)))

    # Format E: prob_home_win / prob_draw / prob_away_win (aktualny /predictions/ API)
    if "prob_home_win" in pred_ml:
        pw = p(pred_ml.get("prob_home_win"))
        pr = p(pred_ml.get("prob_draw"))
        pp = p(pred_ml.get("prob_away_win"))
        if pw + pr + pp > 5:
            return norm(pw, pr, pp,
                        p(pred_ml.get("prob_btts_yes", 0)),
                        p(pred_ml.get("prob_over_25", 0)))

    # Format C: home/draw/away bezposrednio
    if all(k in pred_ml for k in ("home", "draw", "away")):
        pw, pr, pp = p(pred_ml["home"]), p(pred_ml["draw"]), p(pred_ml["away"])
        if pw + pr + pp > 5:
            return norm(pw, pr, pp)

    # Format D: zagniezdzone predictions/prediction
    nested = pred_ml.get("predictions") or pred_ml.get("prediction")
    if isinstance(nested, dict):
        return _bzz_parse_prob(nested)

    return None

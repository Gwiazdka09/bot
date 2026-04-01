import pandas as pd
from datetime import datetime, timedelta
from footstats.config import ROTACJA_DNI, ROTACJA_KARA, ZMECZ_GODZ, ZMECZ_KARA_OBR
from footstats.utils.helpers import _parse_date

# ================================================================
#  MODUL 6 - HEURYSTYKA ZMECZENIA I ROTACJI (NOWE v2.4)
# ================================================================

class HeurystaZmeczeniaRotacji:
    """
    Wykrywa dwa czynniki obnizajace jakosc gry:

    🔄 ROTACJA: mecz CL w ciagu ROTACJA_DNI dni -> trener rotuje sklad
       Efekt: lambda ataku * ROTACJA_KARA = -20%

    😫 ZMECZENIE: poprzedni mecz < ZMECZ_GODZ godzin temu
       Efekt: lambda obrony * ZMECZ_KARA_OBR = -15%
       (co matematycznie zwieksza expected goals przeciwnika)
    """

    def __init__(self, df_mecze: pd.DataFrame):
        self.df = df_mecze.copy() if df_mecze is not None else pd.DataFrame()
        if not self.df.empty and "data_full" in self.df.columns:
            self.df["_dt"] = self.df["data_full"].apply(_parse_date)

    def _mecze_druzyny(self, druzyna: str) -> pd.DataFrame:
        if self.df.empty:
            return pd.DataFrame()
        maska = (self.df["gospodarz"] == druzyna) | (self.df["goscie"] == druzyna)
        return self.df[maska].copy()

    def analiza(self, druzyna: str, data_meczu_str: str) -> dict:
        """
        Zwraca slownik z mnoznikami i opisem.
        Klucze: rotacja, zmeczenie, mnoznik_atak, mnoznik_obr, ikony, opis
        """
        wynik = {
            "rotacja":      False,
            "zmeczenie":    False,
            "mnoznik_atak": 1.0,
            "mnoznik_obr":  1.0,
            "ikony":        "",
            "opis":         "",
        }
        data_meczu = _parse_date(data_meczu_str)
        if data_meczu is None or self.df.empty:
            return wynik

        mecze_d = self._mecze_druzyny(druzyna)
        if mecze_d.empty or "_dt" not in mecze_d.columns:
            return wynik
        mecze_d = mecze_d.dropna(subset=["_dt"])

        # 🔄 ROTACJA: mecz CL w oknie +/- ROTACJA_DNI
        okno_s = data_meczu - timedelta(days=ROTACJA_DNI)
        okno_e = data_meczu + timedelta(days=ROTACJA_DNI)
        mecze_cl = mecze_d[
            (mecze_d["_dt"] >= okno_s) &
            (mecze_d["_dt"] <= okno_e) &
            (mecze_d.get("competition", pd.Series(["?"]*len(mecze_d))) == "CL")
        ]
        if not mecze_cl.empty:
            wynik["rotacja"]      = True
            wynik["mnoznik_atak"] *= ROTACJA_KARA
            wynik["ikony"]        += "🔄"
            wynik["opis"]         += (
                f"🔄 Rotacja: {druzyna} gra CL w ciagu {ROTACJA_DNI} dni "
                f"(atak -{int((1-ROTACJA_KARA)*100)}%). "
            )

        # 😫 ZMECZENIE: ostatni mecz < ZMECZ_GODZ h
        prev = mecze_d[mecze_d["_dt"] < data_meczu].sort_values("_dt")
        if not prev.empty:
            diff_h = (data_meczu - prev.iloc[-1]["_dt"]).total_seconds() / 3600
            if diff_h < ZMECZ_GODZ:
                wynik["zmeczenie"]   = True
                wynik["mnoznik_obr"] *= ZMECZ_KARA_OBR
                wynik["ikony"]       += "😫"
                wynik["opis"]        += (
                    f"😫 Zmeczenie: {druzyna} grala {int(diff_h)}h temu "
                    f"(obrona -{int((1-ZMECZ_KARA_OBR)*100)}%). "
                )

        return wynik

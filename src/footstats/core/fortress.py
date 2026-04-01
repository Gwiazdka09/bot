import pandas as pd
from footstats.config import FORTRESS_MECZE, FORTRESS_BONUS_OBR

# ================================================================
#  MODUL 7b - HOME FORTRESS (v2.5)
# ================================================================

class HomeFortress:
    """
    🏰 HOME FORTRESS: Twierdza domowa

    Jesli gospodarz nie przegral u siebie od FORTRESS_MECZE=5 meczow,
    model zaklada psychologiczna przewage na wlasnym stadionie.
    Efekt: lambda obrony gospodarza * FORTRESS_BONUS_OBR = +10%
    (czyli przyjmie mniej goli niz wskazywaloby to na statystyki).

    Wazne: bonus DODAJE sie do standardowego BONUS_DOMOWY,
    wiec lacznie gospodarz moze miec znaczaca przewage obronno-atakajna.
    """

    def __init__(self, df_mecze: pd.DataFrame):
        self.df = df_mecze.copy() if df_mecze is not None else pd.DataFrame()

    def analiza(self, gospodarz: str) -> dict:
        """
        Sprawdza serie bez porazki u siebie.
        Zwraca: {fortress, bonus_obrona, seria, ikona, opis}
        """
        wynik = {
            "fortress":     False,
            "bonus_obrona": 1.0,
            "seria":        0,
            "ikona":        "",
            "opis":         "",
        }

        if self.df is None or self.df.empty:
            return wynik

        dom = self.df[self.df["gospodarz"] == gospodarz].sort_values("data")
        if dom.empty:
            return wynik

        # Policz nieprzerwana serie bez porazki u siebie (od najnowszego)
        seria = 0
        for _, r in dom.iloc[::-1].iterrows():
            gg, ga = int(r["gole_g"]), int(r["gole_a"])
            if gg > ga or gg == ga:   # wygrana lub remis
                seria += 1
            else:                      # przegrana – stop
                break

        wynik["seria"] = seria

        if seria >= FORTRESS_MECZE:
            wynik["fortress"]     = True
            wynik["bonus_obrona"] = FORTRESS_BONUS_OBR
            wynik["ikona"]        = "🏰"
            wynik["opis"]         = (
                f"🏰 Twierdza domowa: {gospodarz} nie przegral u siebie od {seria} meczow "
                f"→ obrona +{int((FORTRESS_BONUS_OBR-1)*100)}% na wlasnym stadionie."
            )

        return wynik

import pandas as pd
from datetime import datetime, timedelta
from footstats.config import (
    H2H_OKNO_DNI, H2H_MIN_MECZE, PATENT_BONUS,
    ZEMSTA_MIN_GOLE, ZEMSTA_BONUS, CONFIDENCE_H2H_MAX, OSTATNIE_N,
)
from footstats.utils.helpers import _parse_date

# ================================================================
#  MODUL 7 - ANALIZA H2H (v2.5) + SYSTEM ZEMSTY + PATENT
# ================================================================

class AnalizaH2H:
    """
    Inteligentna analiza bezposrednich meczu (Head-to-Head) z filtrem 24 miesiecy.

    FILTR CZASOWY: brane sa wylacznie mecze z ostatnich H2H_OKNO_DNI = 730 dni.
    Starsze wyniki sa automatycznie odrzucane jako historycznie nieistotne.

    Wykrywane wzorce:

    🏅 PATENT (dominacja):
       Jesli jedna druzyna wygrywa WSZYSTKIE mecze H2H w ciagu 2 lat (min. H2H_MIN_MECZE=2),
       jej szanse przesunieto o PATENT_BONUS=+10%. Psychologicznie: "patent na rywala".

    ⚔️ ZEMSTA:
       Jesli ostatni mecz H2H zakonczyl sie roznica ZEMSTA_MIN_GOLE=3+ goli,
       druzyna przegrana dostaje ZEMSTA_BONUS=+15% do lambda_atak.

    📊 CONFIDENCE METER:
       Pewnosc typu (0-100%) na podstawie liczby swiezych meczow H2H:
         0 meczow = 20%  (minimalna pewnosc bazowa)
         1 mecz   = 40%
         2 mecze  = 60%
         3 mecze  = 75%
         4 mecze  = 87%
         5+ mecze = 100%
    """

    def __init__(self, df_mecze: pd.DataFrame):
        self.df = df_mecze.copy() if df_mecze is not None else pd.DataFrame()
        # Parsuj daty raz przy inicjalizacji
        if not self.df.empty and "data" in self.df.columns:
            self.df["_dt"] = pd.to_datetime(self.df["data"], errors="coerce")

    def _filtruj_h2h(self, druzyna1: str, druzyna2: str) -> pd.DataFrame:
        """
        Pobiera mecze H2H z ostatnich 24 miesiecy miedzy dwoma druzyna.
        Odrzuca wszystkie mecze starsze niz H2H_OKNO_DNI dni.
        """
        if self.df.empty:
            return pd.DataFrame()

        prog_cut = datetime.now() - timedelta(days=H2H_OKNO_DNI)

        maska = (
            (
                (self.df["gospodarz"] == druzyna1) & (self.df["goscie"] == druzyna2)
            ) | (
                (self.df["gospodarz"] == druzyna2) & (self.df["goscie"] == druzyna1)
            )
        )
        h2h = self.df[maska].copy()

        # Filtr czasowy: tylko 24 miesiace wstecz
        if "_dt" in h2h.columns:
            h2h = h2h[h2h["_dt"] >= pd.Timestamp(prog_cut)]

        return h2h.sort_values("data")

    def analiza(self, druzyna: str, przeciwnik: str) -> dict:
        """
        Zwraca kompletny wynik analizy H2H dla pary druzyn.

        Klucze slownika:
          patent        : bool  – dominacja w H2H (wszystkie wygrane)
          zemsta        : bool  – motywacja po wysokiej porazce
          mnoznik_atak  : float – laczny mnoznik lambda ataku
          mnoznik_szans : float – korekta szans (Patent +10%)
          ikona         : str   – ikony aktywnych czynnikow
          opis          : str   – opis do komentarza analityka
          pewnosc       : int   – Confidence Meter 0-100%
          n_h2h         : int   – liczba swiezych meczow H2H (<=24 mies.)
          h2h_df        : DataFrame – surowe dane H2H do wyswietlenia
        """
        wynik = {
            "patent":        False,
            "zemsta":        False,
            "mnoznik_atak":  1.0,
            "mnoznik_szans": 1.0,
            "ikona":         "",
            "opis":          "",
            "pewnosc":       20,   # minimalna pewnosc bazowa
            "n_h2h":         0,
            "h2h_df":        pd.DataFrame(),
        }

        h2h = self._filtruj_h2h(druzyna, przeciwnik)
        wynik["h2h_df"] = h2h
        wynik["n_h2h"]  = len(h2h)

        # ── Confidence Meter ──────────────────────────────────────────
        # Skala: 0→20%, 1→40%, 2→60%, 3→75%, 4→87%, 5+→100%
        skala = {0: 20, 1: 40, 2: 60, 3: 75, 4: 87}
        n = len(h2h)
        wynik["pewnosc"] = skala.get(n, 100) if n < CONFIDENCE_H2H_MAX else 100

        if h2h.empty:
            wynik["opis"] = f"Brak danych H2H z ostatnich 24 mies. (pewnosc: {wynik['pewnosc']}%)"
            return wynik

        # ── ZEMSTA: ostatni mecz H2H, roznica 3+ goli ────────────────
        ostatni  = h2h.iloc[-1]
        gg, ga   = int(ostatni["gole_g"]), int(ostatni["gole_a"])
        roznica  = abs(gg - ga)

        if roznica >= ZEMSTA_MIN_GOLE:
            # Ustal czy druzyna przegrala ten mecz
            if druzyna == ostatni["gospodarz"]:
                przegral = gg < ga
            else:
                przegral = ga < gg

            if przegral:
                wynik["zemsta"]       = True
                wynik["mnoznik_atak"] *= ZEMSTA_BONUS
                wynik["ikona"]        += "⚔️"
                wynik["opis"]         += (
                    f"⚔️ Zemsta: {druzyna} przegrala ostatni H2H z {przeciwnik} "
                    f"az {roznica} golami ({gg}:{ga}) "
                    f"→ motywacja rewanzowa, atak +{int((ZEMSTA_BONUS-1)*100)}%. "
                )

        # ── PATENT: wszystkie mecze H2H wygrane (min. 2) ─────────────
        if n >= H2H_MIN_MECZE:
            wygrane = 0
            for _, r in h2h.iterrows():
                gg_r, ga_r = int(r["gole_g"]), int(r["gole_a"])
                if druzyna == r["gospodarz"]:
                    if gg_r > ga_r: wygrane += 1
                else:
                    if ga_r > gg_r: wygrane += 1

            if wygrane == n:
                wynik["patent"]        = True
                wynik["mnoznik_szans"] = PATENT_BONUS
                wynik["ikona"]        += "🏅"
                wynik["opis"]         += (
                    f"🏅 Patent: {druzyna} wygrywa WSZYSTKIE {n} mecze H2H "
                    f"z ostatnich 24 mies. z {przeciwnik} "
                    f"→ przesuniecie szans +{int((PATENT_BONUS-1)*100)}%. "
                )

        if not wynik["opis"]:
            wynik["opis"] = (
                f"H2H {n} mecze (24 mies.): brak dominacji ani zemsta. "
                f"Pewnosc modelu: {wynik['pewnosc']}%."
            )

        return wynik

    @staticmethod
    def oblicz_pewnosc_laczna(n_h2h: int, n_meczow_ogolnie: int) -> int:
        """
        Oblicza laczna pewnosc typu lacząc dane H2H i ogolna liczbe meczow.
        Uzywana w Confidence Meter w tabeli kolejki.
        """
        # Baza z H2H (waga 60%)
        skala_h2h = {0: 20, 1: 40, 2: 60, 3: 75, 4: 87}
        baza_h2h  = skala_h2h.get(min(n_h2h, 4), 100) if n_h2h < CONFIDENCE_H2H_MAX else 100

        # Korekta z liczby ogolnych meczow (waga 40%)
        baza_og = min(100, int(n_meczow_ogolnie / OSTATNIE_N * 100))

        pewnosc = int(baza_h2h * 0.6 + baza_og * 0.4)
        return max(20, min(100, pewnosc))

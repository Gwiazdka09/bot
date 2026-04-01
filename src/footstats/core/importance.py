import pandas as pd
from footstats.config import IMP2_PROG_FINAL, IMP2_BONUS_FINAL, IMP2_WAKACJE

# ================================================================
#  ImportanceIndex – wydzielony z MODUL 4d
# ================================================================

class ImportanceIndex:
    """
    Importance Index 2.0 – dwustopniowa motywacja konca sezonu:

    TRYB NORMALNY (pozostalo > IMP2_PROG_FINAL kolejek):
      * High Stakes Top (poz. 1-4, < 10 kolejek): atak +20%
      * Baraze/Spadek (ostanie 5, < 10 kolejek):  atak +10-20%
      * Comfort (srodek tabeli, duzo kolejek):     atak -10%

    TRYB FINALNY (pozostalo <= IMP2_PROG_FINAL = 5 kolejek):
      * Miejsca 1-3:             atak +20% (walka o tytul / CL)
      * Ostatnie 3 miejsca:      atak +20% (desperacja, utrzymanie)
      * Reszta ('bezpieczni'):   atak -10% (efekt wakacji)
    """

    def __init__(self, df_tabela: pd.DataFrame, n_druzyn: int = 20):
        self.df = df_tabela
        self.n  = n_druzyn if n_druzyn else (len(df_tabela) if df_tabela is not None else 20)

    def _pozostale(self, rozegrane: int) -> int:
        sezon_dl = 34 if self.n <= 18 else 38
        return max(0, sezon_dl - rozegrane)

    def analiza(self, druzyna: str) -> dict:
        if self.df is None or self.df.empty:
            return self._normal()
        wiersz = self.df[self.df["Druzyna"] == druzyna]
        if wiersz.empty:
            return self._normal()
        poz       = int(wiersz["Poz."].iloc[0])
        rozegr    = int(wiersz["M"].iloc[0])
        pozostalo = self._pozostale(rozegr)

        # ── TRYB FINALNY: <= 5 kolejek do konca ─────────────────────
        if pozostalo <= IMP2_PROG_FINAL:
            # Miejsca 1-3: walka o tytul / UEFA
            if poz <= 3:
                ikona = "👑" if poz == 1 else "🏆"
                return {
                    "status":      "FINAL_TOP",
                    "label":       f"[bold gold1]{ikona} FINAL-TOP{poz}[/bold gold1]",
                    "label_plain": f"FINAL-TOP{poz}",
                    "bonus_atak":  IMP2_BONUS_FINAL,
                    "komentarz":   (
                        f"TRYB FINALNY: {druzyna} na {poz}. miejscu, "
                        f"zostalo {pozostalo} kolejek – atak +20% (walka o tytul/CL)."
                    ),
                }
            # Ostatnie 3 miejsca: bezposredni spadek
            if poz >= self.n - 2:
                return {
                    "status":      "FINAL_RELEGATION",
                    "label":       "[bold red]🆘 FINAL-SPADEK[/bold red]",
                    "label_plain": "FINAL-SPADEK",
                    "bonus_atak":  IMP2_BONUS_FINAL,
                    "komentarz":   (
                        f"TRYB FINALNY: {druzyna} zagrozony spadkiem (poz. {poz}/{self.n}), "
                        f"{pozostalo} kolejek – desperacja, atak +20%."
                    ),
                }
            # Reszta: efekt wakacji
            return {
                "status":      "VACATION",
                "label":       "[dim]🏖️  Wakacje-MID[/dim]",
                "label_plain": "Wakacje-MID",
                "bonus_atak":  IMP2_WAKACJE,
                "komentarz":   (
                    f"TRYB FINALNY: {druzyna} bezpieczna pozycja (poz. {poz}), "
                    f"{pozostalo} kolejek – efekt wakacji, wydajnosc -10%."
                ),
            }

        # ── TRYB NORMALNY: wiecej niz 5 kolejek ─────────────────────
        # Wysokie stawki: Top 4 (< 10 kolejek)
        if poz <= 4 and pozostalo < 10:
            ikona = "👑" if poz == 1 else "🏆"
            return {
                "status":      "HIGH_STAKES_TOP",
                "label":       f"[bold green]{ikona} Wysoka-TOP{poz}[/bold green]",
                "label_plain": f"Wysoka-TOP{poz}",
                "bonus_atak":  1.20,
                "komentarz":   f"{druzyna} walczy o Top {poz} (poz. {poz}/{self.n}), ~{pozostalo} kolejek – atak +20%.",
            }
        # Strefa spadkowa (< 10 kolejek)
        if poz >= self.n - 2 and pozostalo < 10:
            return {
                "status":      "HIGH_STAKES_BOTTOM",
                "label":       "[bold red]🆘 Wysoka-SPADEK[/bold red]",
                "label_plain": "Wysoka-SPADEK",
                "bonus_atak":  1.20,
                "komentarz":   f"{druzyna} zagrozony spadkiem (poz. {poz}/{self.n}), {pozostalo} kolejek – atak +20%.",
            }
        # Baraze (< 10 kolejek)
        if poz >= self.n - 5 and pozostalo < 10:
            return {
                "status":      "HIGH_STAKES_BOTTOM",
                "label":       "[bold orange_red1]⚠️  Wysoka-BARAZE[/bold orange_red1]",
                "label_plain": "Wysoka-BARAZE",
                "bonus_atak":  1.10,
                "komentarz":   f"{druzyna} strefa barazy (poz. {poz}), ~{pozostalo} kolejek – ofensywa +10%.",
            }
        # Komfort (duzo kolejek, srodek tabeli)
        mid_lo, mid_hi = 5, max(6, self.n - 6)
        if mid_lo <= poz <= mid_hi and pozostalo >= 10:
            return {
                "status":      "COMFORT",
                "label":       "[dim]😐 Neutralna-MID[/dim]",
                "label_plain": "Neutralna-MID",
                "bonus_atak":  0.90,
                "komentarz":   f"{druzyna} srodek tabeli (poz. {poz}), {pozostalo} kolejek – motywacja -10%.",
            }
        return self._normal(poz)

    def _normal(self, poz: int = 0) -> dict:
        return {
            "status":      "NORMAL",
            "label":       "[cyan]🔵 Normalna[/cyan]",
            "label_plain": "Normalna",
            "bonus_atak":  1.0,
            "komentarz":   f"Druzyna (poz. {poz}) – brak specjalnych czynnikow.",
        }

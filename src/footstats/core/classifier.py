import pandas as pd
from datetime import datetime, timedelta
from footstats.utils.helpers import _parse_date
from footstats.config import (
    REWANZ_OKNO_DNI, REWANZ_VABANK, REWANZ_PARKING_BUS,
    REWANZ_FORT_OBR, FINAL_REMIS_BOOST, _FINAL_STAGES,
    _SINGLE_MATCH_COMPS, IMP2_PROG_FINAL, IMP2_BONUS_FINAL,
    IMP2_WAKACJE,
)

# ================================================================
#  MODUL 9 - LOGIKA DWUMECZOW
# ================================================================

def _czy_knockout(stage: str) -> bool:
    return str(stage).upper() in {
        "FINAL", "THIRD_PLACE", "SEMI_FINALS", "QUARTER_FINALS",
        "LAST_16", "LAST_32", "LAST_64",
        "ROUND_4", "ROUND_3", "ROUND_2", "ROUND_1",
        "KNOCKOUT_PHASE_PLAYOFF",
        "PLAYOFF_ROUND_1", "PLAYOFF_ROUND_2", "PLAYOFFS",
        "ROUND_OF_16",
    }


# ================================================================
#  MODUL 9b – KLASYFIKATOR MECZU v2.6
# ================================================================

class KlasyfikatorMeczu:
    """
    Rozpoznaje typ meczu i generuje etykiete UI:
      [LIGA]          – REGULAR_SEASON
      [PUCHAR 1/2]    – faza pucharowa, pierwsza noga (lub brak historii)
      [REWANZ (X:Y)]  – wykryta druga noga (1. mecz w ostatnich 14 dniach)
      [FINAL]         – mecze finalne / turnieje bez rewanzu (EC, WC)

    Wykrywanie rewanzu: sprawdza czy w df_wyk istnieje mecz tych samych druzyn
    w tej samej fazie z ostatnich REWANZ_OKNO_DNI=14 dni.
    """

    def __init__(self, df_wyk: pd.DataFrame, kod_ligi: str = ""):
        self.df      = df_wyk.copy() if df_wyk is not None else pd.DataFrame()
        self.kod     = kod_ligi.upper()

    def klasyfikuj(self, g: str, a: str, stage: str, data_meczu_str: str,
                   first_leg_g=None, first_leg_a=None) -> dict:
        """
        Zwraca slownik:
          typ         : "LIGA" | "PUCHAR_1" | "REWANZ" | "FINAL"
          etykieta    : str  (do wyswietlenia w tabeli)
          etykieta_pdf: str  (bez Rich markup)
          rewanz      : bool
          single      : bool – mecz bez rewanzu (Final/EC/WC)
          agg_g       : int | None  – gole gosp. z 1. nogi
          agg_a       : int | None  – gole gosci z 1. nogi
          opis        : str
        """
        stage_up = str(stage).upper()

        # ── LIGA ────────────────────────────────────────────────────
        if stage_up == "REGULAR_SEASON":
            return {
                "typ":          "LIGA",
                "etykieta":     "[dim][LIGA][/dim]",
                "etykieta_pdf": "[LIGA]",
                "rewanz":       False,
                "single":       False,
                "agg_g":        None,
                "agg_a":        None,
                "opis":         "",
            }

        # ── FINAL / TURNIEJE BEZ REWANZU ────────────────────────────
        is_final_stage = stage_up in _FINAL_STAGES
        is_single_comp = self.kod in _SINGLE_MATCH_COMPS
        if is_final_stage or is_single_comp:
            label = "FINAL" if is_final_stage else "TURNIEJ"
            return {
                "typ":          "FINAL",
                "etykieta":     f"[bold magenta][{label}][/bold magenta]",
                "etykieta_pdf": f"[{label}]",
                "rewanz":       False,
                "single":       True,
                "agg_g":        None,
                "agg_a":        None,
                "opis":         f"Mecz {label} – bez rewanzu. Mozliwa dogrywka/karne.",
            }

        # ── FAZA PUCHAROWA – sprawdz czy to rewanz ──────────────────
        # Jesli API zwrocilo aggregateScore, uzyj go bezposrednio
        if first_leg_g is not None and first_leg_a is not None:
            try:
                ag, aa = int(first_leg_g), int(first_leg_a)
                roznica_agg = ag - aa
                return {
                    "typ":          "REWANZ",
                    "etykieta":     f"[bold cyan][REWANZ ({ag}:{aa})][/bold cyan]",
                    "etykieta_pdf": f"[REWANZ ({ag}:{aa})]",
                    "rewanz":       True,
                    "single":       False,
                    "agg_g":        ag,
                    "agg_a":        aa,
                    "opis":         f"Rewanz: wynik 1. meczu {ag}:{aa} (roznica {abs(roznica_agg)}).",
                }
            except (TypeError, ValueError):
                pass

        # Szukaj 1. nogi w historii (ostatnie REWANZ_OKNO_DNI dni)
        data_meczu = _parse_date(data_meczu_str)
        if data_meczu is not None and not self.df.empty:
            prog_cut = data_meczu - timedelta(days=REWANZ_OKNO_DNI)
            hist = self.df[
                (
                    ((self.df["gospodarz"] == g) & (self.df["goscie"] == a)) |
                    ((self.df["gospodarz"] == a) & (self.df["goscie"] == g))
                ) &
                (self.df["stage"] == stage)
            ].copy()
            if "data_full" in hist.columns:
                hist["_dt"] = hist["data_full"].apply(_parse_date)
            elif "data" in hist.columns:
                hist["_dt"] = hist["data"].apply(_parse_date)
            hist = hist.dropna(subset=["_dt"])
            hist = hist[hist["_dt"] >= prog_cut]

            if not hist.empty:
                pierwsza = hist.sort_values("_dt").iloc[-1]
                fg = int(pierwsza["gole_g"])
                fa = int(pierwsza["gole_a"])
                # Jesli w 1. meczu gospodarz byl goscia (teraz graja rewanz u siebie)
                # agg_g = gole aktualnego gospodarza
                if pierwsza["gospodarz"] == g:
                    agg_g, agg_a = fg, fa
                else:
                    agg_g, agg_a = fa, fg
                roznica = agg_g - agg_a
                return {
                    "typ":          "REWANZ",
                    "etykieta":     f"[bold cyan][REWANZ ({agg_g}:{agg_a})][/bold cyan]",
                    "etykieta_pdf": f"[REWANZ ({agg_g}:{agg_a})]",
                    "rewanz":       True,
                    "single":       False,
                    "agg_g":        agg_g,
                    "agg_a":        agg_a,
                    "opis":         f"Rewanz (wykryty z historii): wynik 1. meczu {fg}:{fa}.",
                }

        # Pierwsza noga (brak historii rewanzu)
        return {
            "typ":          "PUCHAR_1",
            "etykieta":     "[bold yellow][PUCHAR 1/2][/bold yellow]",
            "etykieta_pdf": "[PUCHAR 1/2]",
            "rewanz":       False,
            "single":       False,
            "agg_g":        None,
            "agg_a":        None,
            "opis":         f"Pierwsza noga: {stage_up}. Rewanz bedzie za ~7 dni.",
        }


def _korekta_rewanz_v26(lg: float, la: float,
                        agg_g: int, agg_a: int) -> tuple:
    """
    Korekta lambd dla rewanzu v2.6 (rozszerzona logika):

    Gospodarz (aktualny) = druzyna, ktora w 1. meczu byla goscia.
    agg_g = gole aktualnego gospodarza z 1. meczu (jako gosc)
    agg_a = gole aktualnych gosci z 1. meczu (jako gospodarz)

    Roznica = agg_g - agg_a (>0 = gospodarz prowadzi w dwumeczu)

    Progi:
      roznica >= +2: gospodarz prowadzi komfortowo → gra na czas
        atak  *REWANZ_PARKING_BUS (-25%)
        obrona *REWANZ_FORT_OBR (+20%)
      roznica <= -2: gospodarz przegrywa → vabank
        atak  *REWANZ_VABANK (+30%)
      roznica == -1 lub +1: minimalna roznica → oba atakuja
        atak  *1.10 dla obu
      remis (0:0 lub wyrownosc): neutralnie + lekki wzrost
    """
    roznica = agg_g - agg_a
    opis = f"[REWANZ] Wynik 1. meczu: {agg_g}:{agg_a} (roznica {'+' if roznica>=0 else ''}{roznica}). "

    if roznica >= 2:
        # Gospodarz prowadzi 2+ – gra na czas, goscie vabank
        opis += (f"Gospodarz PROWADZI (+{roznica}) → defensywa/gra na czas "
                 f"(atak -{int((1-REWANZ_PARKING_BUS)*100)}%, obrona +{int((REWANZ_FORT_OBR-1)*100)}%). "
                 f"Goscie gra VA-BANK (atak +{int((REWANZ_VABANK-1)*100)}%).")
        return (
            round(lg * REWANZ_PARKING_BUS, 3),
            round(la * REWANZ_VABANK / REWANZ_FORT_OBR, 3),
            opis,
        )
    elif roznica <= -2:
        # Gospodarz przegrywa 2+ – vabank, goscie defensywa
        opis += (f"Gospodarz PRZEGRYWA ({roznica}) → VA-BANK "
                 f"(atak +{int((REWANZ_VABANK-1)*100)}%). "
                 f"Goscie gra na czas (atak -{int((1-REWANZ_PARKING_BUS)*100)}%, "
                 f"obrona +{int((REWANZ_FORT_OBR-1)*100)}%).")
        return (
            round(lg * REWANZ_VABANK, 3),
            round(la * REWANZ_PARKING_BUS / REWANZ_FORT_OBR, 3),
            opis,
        )
    elif roznica == 0 and agg_g == agg_a:
        # Remis 0:0 lub rowny wynik → oba musza atakowac
        opis += "Remis – oba zespoly musza atakowac (+10% lambda obu)."
        return round(lg * 1.10, 3), round(la * 1.10, 3), opis
    else:
        # Roznica 1 lub -1 → wyrownana rywalizacja
        opis += f"Minimalna roznica (1 gol) → wyrownana walka, lekkie wzmocnienie ataku obu (+5%)."
        return round(lg * 1.05, 3), round(la * 1.05, 3), opis


def _korekta_dwumecz(lg, la, first_leg_g, first_leg_a, jest_gospodarzem_1: bool):
    """Kompatybilnosc wsteczna – uzywana gdy brak agg z API."""
    try:
        fg, fa = int(first_leg_g), int(first_leg_a)
    except (TypeError, ValueError):
        return lg, la, "Brak wyniku 1. meczu - standardowa analiza."
    roznica = fg - fa
    if not jest_gospodarzem_1:
        roznica = -roznica
    if abs(roznica) >= 3:
        if roznica > 0:
            return round(lg*0.60,3), round(la*1.50,3), (
                f"REWANZ: Gospodarz prowadzi {fg}:{fa} (+{roznica}). "
                "Parking Bus (atak -40%) vs All-In gosci (atak +50%).")
        else:
            return round(lg*1.50,3), round(la*0.60,3), (
                f"REWANZ: Goscie prowadza {fa}:{fg}. "
                "Gospodarz All-In (+50%), goscie Parking Bus (-40%).")
    elif roznica == 0 and fg == fa:
        return round(lg*1.10,3), round(la*1.10,3), (
            f"REWANZ: Remis 1. meczu ({fg}:{fa}) - oba zespoly musza atakowac.")
    return lg, la, f"REWANZ: Wynik 1. meczu {fg}:{fa} - standardowe lambdy."

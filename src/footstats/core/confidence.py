from footstats.utils.helpers import _s
from footstats.config import FINAL_REMIS_BOOST

# ================================================================
#  MODUL 12 - KOMENTARZ ANALITYKA
# ================================================================

def komentarz_analityka(w: dict) -> str:
    g, a       = w["gospodarz"], w["gosc"]
    pw, pr, pp = w["p_wygrana"], w["p_remis"], w["p_przegrana"]
    linie      = []

    # ── v2.6 Kontekst meczu ──────────────────────────────────────────
    klas = w.get("klasyfikacja", {})
    typ  = klas.get("typ", "LIGA")
    if typ == "REWANZ":
        agg_g = klas.get("agg_g", "?")
        agg_a = klas.get("agg_a", "?")
        linie.append(f"[REWANZ] Wynik 1. meczu: {agg_g}:{agg_a}. {klas.get('opis','')}")
    elif typ == "FINAL":
        linie.append(
            f"[FINAL/TURNIEJ] Mecz bez rewanzu. "
            f"Uwaga: mozliwa dogrywka/karne (remis po 90 min = {pr:.0f}%, "
            f"prawdopodobienstwo wzroslo o +{int((FINAL_REMIS_BOOST-1)*100)}% vs standard)."
        )
    elif typ == "PUCHAR_1":
        linie.append(f"[PUCHAR 1/2] Pierwsza noga – wynik bedzie ksztaltowal rewanz.")

    if pw >= 65:       linie.append(f"Model faworyzuje {g} ({pw:.0f}% szans na wygrana).")
    elif pp >= 65:     linie.append(f"Model faworyzuje {a} ({pp:.0f}% szans na wygrana).")
    elif pr >= 28:     linie.append(f"Mecz wyrownany – wysoka szansa na remis ({pr:.0f}%).")
    else:              linie.append("Mecz wyrownany – roznice minimalne.")

    # Importance Index 2.0 – nowe statusy v2.5
    for d, imp in [(g, w.get("imp_g",{})), (a, w.get("imp_a",{}))]:
        st = imp.get("status", "NORMAL")
        if st == "FINAL_TOP":
            linie.append(f"{d}: TRYB FINALNY – walka o podium, atak +20% (zostalo maks. 5 kolejek).")
        elif st == "FINAL_RELEGATION":
            linie.append(f"{d}: TRYB FINALNY – desperacja o utrzymanie, atak +20%.")
        elif st == "VACATION":
            linie.append(f"{d}: Efekt wakacji – bezpieczna pozycja, motywacja -10%.")
        elif st == "HIGH_STAKES_TOP":
            linie.append(f"{d} walczy o TOP/tytul – agresja ofensywna +20%.")
        elif st == "HIGH_STAKES_BOTTOM":
            linie.append(f"{d} zagrozony spadkiem – gra pod presja.")
        elif st == "COMFORT":
            linie.append(f"{d} w strefie komfortu – motywacja obnizona -10%.")

    # Heurystyka v2.4
    for d, heur in [(g, w.get("heur_g",{})), (a, w.get("heur_a",{}))]:
        if heur.get("opis"): linie.append(heur["opis"].strip())

    # H2H v2.5 – Patent i Zemsta
    for d, h2h in [(g, w.get("h2h_g",{})), (a, w.get("h2h_a",{}))]:
        opis = h2h.get("opis", "")
        if opis and (h2h.get("patent") or h2h.get("zemsta")):
            linie.append(opis.strip())

    # Home Fortress v2.5
    fort = w.get("fortress_g", {})
    if fort.get("fortress") and fort.get("opis"):
        linie.append(fort["opis"].strip())

    # Forma
    fg, fa = w.get("forma_g", 0), w.get("forma_a", 0)
    if fg > fa + 0.5:   linie.append(f"Forma {g} ({fg:.1f} pkt/mecz) lepsza niz {a} ({fa:.1f}).")
    elif fa > fg + 0.5: linie.append(f"Forma {a} ({fa:.1f} pkt/mecz) lepsza niz {g} ({fg:.1f}).")

    if w["btts"] >= 65:  linie.append(f"Obie druzyny prawdopodobnie strzela ({w['btts']:.0f}% BTTS).")
    if w["over25"] >= 70: linie.append(f"Mecz bramkostrzelny – Over 2.5 ({w['over25']:.0f}%).")
    elif w["under25"] >= 65: linie.append(f"Mecz defensywny – Under 2.5 ({w['under25']:.0f}%).")
    if w.get("knockout") and w.get("korekta_opis"):
        linie.append(w["korekta_opis"])

    # Confidence Meter
    pewnosc = w.get("pewnosc", 20)
    linie.append(f"Pewnosc modelu: {pewnosc}% (baza danych H2H 24 mies. + historia ogolna).")

    return " ".join(linie)

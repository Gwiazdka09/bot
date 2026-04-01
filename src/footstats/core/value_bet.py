# ================================================================
#  MODUL 11 - TYPY BUKMACHERSKIE
# ================================================================

def typy_zaklady(w: dict) -> list:
    pw, pr, pp  = w["p_wygrana"], w["p_remis"], w["p_przegrana"]
    bt, o25, u25 = w["btts"], w["over25"], w["under25"]
    wyniki = []
    def dodaj(typ, val, pewny=70, dobry=55):
        if val >= pewny:   wyniki.append((typ, f"{val:.1f}%", "PEWNY"))
        elif val >= dobry: wyniki.append((typ, f"{val:.1f}%", "DOBRY"))
    dodaj("1  (Gospodarz wygrywa)", pw)
    if pr >= 32: wyniki.append(("X  (Remis)", f"{pr:.1f}%", "DOBRY"))
    dodaj("2  (Gosc wygrywa)", pp)
    dodaj("1X (Gosp. lub remis)",  pw + pr, 80, 72)
    dodaj("X2 (Remis lub gosc)",   pr + pp, 80, 72)
    dodaj("12 (Ktos wygrywa)",     pw + pp, 85, 75)
    dodaj("BTTS TAK", bt, 65, 55)
    if bt < 45: wyniki.append(("BTTS NIE", f"{100-bt:.1f}%", "DOBRY" if 100-bt>=60 else "SLABY"))
    dodaj("Over 2.5", o25, 70, 58)
    dodaj("Under 2.5", u25, 68, 58)
    return wyniki

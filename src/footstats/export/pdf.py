from pathlib import Path
from datetime import datetime
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
    Table as RLTable, TableStyle, HRFlowable, PageBreak, KeepTogether)
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from footstats.export.pdf_font import _pdf, PDF_FONT, PDF_FONT_BOLD, FONT_OK
_s = _pdf  # alias używany wewnętrznie
from footstats.utils.console import console
from footstats.config import VERSION, FINAL_REMIS_BOOST
from footstats.core.value_bet import typy_zaklady
from footstats.core.confidence import komentarz_analityka

#  MODUL 15 - EKSPORT PDF
# ================================================================

def eksportuj_pdf(wyniki_kolejki: list, nazwa_ligi: str,
                  df_tabela: pd.DataFrame = None, sciezka: str = None) -> str:
    if not sciezka:
        sciezka = f"FootStats_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"

    doc = SimpleDocTemplate(sciezka, pagesize=A4,
                             rightMargin=1.5*cm, leftMargin=1.5*cm,
                             topMargin=2*cm, bottomMargin=2*cm)
    F, FB = PDF_FONT, PDF_FONT_BOLD

    def st(name, **kw):
        return ParagraphStyle(name, fontName=F, **kw)

    s_tit = st("t",  fontSize=18, textColor=colors.HexColor("#1a5276"), alignment=TA_CENTER, spaceAfter=4)
    s_sub = st("s",  fontSize=8,  textColor=colors.grey, alignment=TA_CENTER, spaceAfter=8)
    s_h1  = st("h1", fontSize=13, textColor=colors.HexColor("#1a5276"), spaceBefore=10, spaceAfter=5)
    s_h2  = st("h2", fontSize=10, textColor=colors.HexColor("#2980b9"), spaceBefore=6,  spaceAfter=3)
    s_bod = st("b",  fontSize=8,  spaceAfter=2)
    s_kom = st("k",  fontSize=8,  textColor=colors.HexColor("#2c3e50"),
               backColor=colors.HexColor("#eaf4fb"), alignment=TA_JUSTIFY,
               leftIndent=6, rightIndent=6, spaceBefore=3, spaceAfter=4)
    s_ok  = st("ok", fontSize=8,  textColor=colors.HexColor("#27ae60"), spaceAfter=2)
    s_dob = st("d",  fontSize=8,  textColor=colors.HexColor("#e67e22"), spaceAfter=2)

    note = "" if FONT_OK else " [UWAGA: Brak DejaVuSans.ttf - ogonki zastapione ASCII.]"
    story = []

    story.append(Paragraph(_pdf(f"FootStats {VERSION}  |  Raport Predykcji"), s_tit))
    story.append(Paragraph(_pdf(
        f"Liga: {nazwa_ligi}  |  {datetime.now().strftime('%d.%m.%Y %H:%M')}  |  "
        f"Model: Poisson + Importance + Stage Recognition + Rewanz Vabank + H2H + Fortress{note}"
    ), s_sub))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a5276"), spaceAfter=8))

    # Tabela zbiorcza
    story.append(Paragraph(_pdf("Przeglad Kolejki"), s_h1))
    nagl  = [_pdf(x) for x in ["Data","Gospodarz","Goscie","Typ","1%","X%","2%","BTTS","Ov2.5","Czynniki","Inf."]]
    dane_t = [nagl]
    for wpis in wyniki_kolejki:
        m, w = wpis["mecz"], wpis["predykcja"]
        klas = wpis.get("klasyfikacja", {})
        ikony = (w.get("heur_g",{}).get("ikony","") + w.get("heur_a",{}).get("ikony","") +
                 w.get("zemsta_g",{}).get("ikona","") + w.get("zemsta_a",{}).get("ikona",""))
        cz  = _pdf((ikony + " " + w.get("imp_g",{}).get("label_plain",""))[:14].strip())
        inf = _pdf(klas.get("etykieta_pdf", "[LIGA]")[:12])
        dane_t.append([
            _pdf(m.get("data","-")),
            _pdf(str(m.get("gospodarz","-"))[:13]),
            _pdf(str(m.get("goscie","-"))[:13]),
            _pdf(f"{w['wynik_g']}:{w['wynik_a']}"),
            _pdf(f"{w['p_wygrana']:.0f}"),
            _pdf(f"{w['p_remis']:.0f}"),
            _pdf(f"{w['p_przegrana']:.0f}"),
            _pdf(f"{'T' if w['btts']>=50 else 'N'} {w['btts']:.0f}%"),
            _pdf(f"{'OV' if w['over25']>=50 else 'UN'} {w['over25']:.0f}%"),
            cz, inf,
        ])
    ts_styl = TableStyle([
        ("BACKGROUND",     (0,0),(-1,0),  colors.HexColor("#1a5276")),
        ("TEXTCOLOR",      (0,0),(-1,0),  colors.white),
        ("FONTNAME",       (0,0),(-1,-1), F), ("FONTNAME",(0,0),(-1,0), FB),
        ("FONTSIZE",       (0,0),(-1,-1), 7),
        ("ALIGN",          (0,0),(-1,-1), "CENTER"),
        ("ROWBACKGROUNDS", (0,1),(-1,-1), [colors.white, colors.HexColor("#eaf4fb")]),
        ("GRID",           (0,0),(-1,-1), 0.4, colors.grey),
        ("TOPPADDING",     (0,0),(-1,-1), 2), ("BOTTOMPADDING",(0,0),(-1,-1), 2),
    ])
    widths = [1.8*cm,2.2*cm,2.2*cm,1.2*cm,0.9*cm,0.9*cm,0.9*cm,1.6*cm,1.6*cm,1.8*cm,1.6*cm]
    story.append(RLTable(dane_t, colWidths=widths, repeatRows=1, style=ts_styl))
    story.append(Spacer(1, 0.4*cm))

    # Szczegoly
    story.append(PageBreak())
    story.append(Paragraph(_pdf("Szczegolowa Analiza Meczow"), s_h1))
    for i, wpis in enumerate(wyniki_kolejki):
        m, w = wpis["mecz"], wpis["predykcja"]
        g, a = w["gospodarz"], w["gosc"]
        blok = []
        blok.append(HRFlowable(width="100%", thickness=0.8,
                                color=colors.HexColor("#aed6f1"), spaceAfter=4))
        klas_pdf = wpis.get("klasyfikacja", {})
        etykieta_pdf = klas_pdf.get("etykieta_pdf", "")
        blok.append(Paragraph(_pdf(
            f"{_s(m.get('data','-'))}  |  {g}  vs  {a}"
            + (f"  {etykieta_pdf}" if etykieta_pdf else "")
        ), s_h2))
        # Uwaga o dogrywce dla meczow final/single
        if w.get("single"):
            blok.append(Paragraph(_pdf(
                "UWAGA: Mecz bez rewanzu – mozliwa dogrywka/karne "
                f"(szansa remisu po 90 min: {w['p_remis']:.0f}%, "
                f"wzmocniona +{int((FINAL_REMIS_BOOST-1)*100)}% vs standard)."
            ), ParagraphStyle("warn", fontName=PDF_FONT_BOLD, fontSize=8,
                              textColor=colors.HexColor("#8e44ad"), spaceAfter=3)))
        dm = [
            [_pdf("Typ"), _pdf("Szansa"), _pdf("Typ"), _pdf("Szansa")],
            [_pdf("1 Gosp."),  _pdf(f"{w['p_wygrana']}%"), _pdf("BTTS TAK"),  _pdf(f"{w['btts']}%")],
            [_pdf("X Remis"),  _pdf(f"{w['p_remis']}%"),   _pdf("BTTS NIE"),  _pdf(f"{100-w['btts']:.1f}%")],
            [_pdf("2 Gosc"),   _pdf(f"{w['p_przegrana']}%"),_pdf("Over 2.5"), _pdf(f"{w['over25']}%")],
            [_pdf("1X"),       _pdf(f"{w['p_wygrana']+w['p_remis']:.1f}%"),
             _pdf("Under 2.5"),_pdf(f"{w['under25']}%")],
        ]
        dm_st = TableStyle([
            ("BACKGROUND",(0,0),(-1,0), colors.HexColor("#2980b9")),
            ("TEXTCOLOR", (0,0),(-1,0), colors.white),
            ("FONTNAME",  (0,0),(-1,-1), F), ("FONTNAME",(0,0),(-1,0), FB),
            ("FONTSIZE",  (0,0),(-1,-1), 7.5),
            ("ALIGN",     (0,0),(-1,-1), "CENTER"),
            ("GRID",      (0,0),(-1,-1), 0.4, colors.lightgrey),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#eaf4fb")]),
        ])
        blok.append(RLTable(dm, colWidths=[2.8*cm,2*cm,2.8*cm,2*cm], style=dm_st))
        blok.append(Spacer(1,0.1*cm))
        blok.append(Paragraph(_pdf("  |  ".join(f"{r}({p}%)" for r,p in w["top5"])), s_bod))
        blok.append(Paragraph(_pdf(
            f"Lambda G={w['lambda_g']}  A={w['lambda_a']}  "
            f"Forma G={w['forma_g']:.1f}  A={w['forma_a']:.1f}"), s_bod))
        for naz,sz,pew in typy_zaklady(w):
            blok.append(Paragraph(_pdf(f"{'*' if pew=='PEWNY' else '-'} {naz}: {sz} [{pew}]"),
                                   s_ok if pew=="PEWNY" else(s_dob if pew=="DOBRY" else s_bod)))
        blok.append(Paragraph(_pdf("Komentarz Analityka:"), s_bod))
        blok.append(Paragraph(_pdf(komentarz_analityka(w)), s_kom))
        for d,heur in [(g,w.get("heur_g",{})), (a,w.get("heur_a",{}))]:
            if heur.get("opis"): blok.append(Paragraph(_pdf(heur["opis"]), s_bod))
        for d,zem  in [(g,w.get("zemsta_g",{})), (a,w.get("zemsta_a",{}))]:
            if zem.get("opis"):  blok.append(Paragraph(_pdf(zem["opis"]),  s_bod))
        blok.append(Spacer(1,0.3*cm))
        story.append(KeepTogether(blok))
        if (i+1) % 4 == 0 and i+1 < len(wyniki_kolejki):
            story.append(PageBreak())

    # Tabela ligowa
    if df_tabela is not None and not df_tabela.empty:
        story.append(PageBreak())
        story.append(Paragraph(_pdf(f"Tabela: {nazwa_ligi}"), s_h1))
        nagl_t = [_pdf(x) for x in ["Poz.","Druzyna","M","W","R","P","Bramki","+/-","Pkt"]]
        dane_tb = [nagl_t]
        for _,r in df_tabela.iterrows():
            dane_tb.append([_pdf(str(r[k])) for k in ["Poz.","Druzyna","M","W","R","P","Bramki","+/-","Pkt"]])
        tb_st = TableStyle([
            ("BACKGROUND",(0,0),(-1,0), colors.HexColor("#1a5276")),
            ("TEXTCOLOR", (0,0),(-1,0), colors.white),
            ("FONTNAME",  (0,0),(-1,-1), F), ("FONTNAME",(0,0),(-1,0), FB),
            ("FONTSIZE",  (0,0),(-1,-1), 7.5),
            ("ALIGN",     (0,0),(-1,-1),"CENTER"), ("ALIGN",(1,0),(1,-1),"LEFT"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#eaf4fb")]),
            ("GRID",      (0,0),(-1,-1), 0.4, colors.grey),
        ])
        n_dr = len(df_tabela)
        for ri in range(1, n_dr+1):
            if ri <= 4:       tb_st.add("BACKGROUND",(0,ri),(0,ri),colors.HexColor("#27ae60"))
            elif ri >= n_dr-1:tb_st.add("BACKGROUND",(0,ri),(0,ri),colors.HexColor("#c0392b"))
        story.append(RLTable(dane_tb,
            colWidths=[1.2*cm,4*cm,1*cm,1*cm,1*cm,1*cm,1.8*cm,1.2*cm,1.2*cm],
            repeatRows=1, style=tb_st))

    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=0.8, color=colors.grey))
    story.append(Paragraph(_pdf(
        f"FootStats {VERSION}  |  Poisson + Stage Recognition + Rewanz Vabank + Importance +  "
        "Fatigue/Rotation + H2H + Fortress + Two-Leg  |  "
        "Dane: football-data.org  |  TYLKO DO UZYTKU ANALITYCZNEGO"
    ), ParagraphStyle("ft", fontName=F, fontSize=6, textColor=colors.grey, alignment=TA_CENTER)))

    doc.build(story)
    return sciezka


# ================================================================
#  MODUL 16 - INTERFEJS

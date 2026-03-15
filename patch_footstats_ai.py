"""
patch_footstats_ai.py – Automatycznie dodaje opcję AI do menu FootStats
Uruchom JEDEN RAZ: python patch_footstats_ai.py
Tworzy kopię zapasową footstats_BACKUP.py przed zmianami.
"""

import shutil
from pathlib import Path
import sys

PLIK = Path("footstats.py")
BACKUP = Path("footstats_BACKUP.py")

# ── Sprawdzenia ──────────────────────────────────────────────────────
if not PLIK.exists():
    print("BŁĄD: Nie znaleziono footstats.py w bieżącym folderze.")
    print("Uruchom ten skrypt z folderu F:\\bot\\")
    sys.exit(1)

if BACKUP.exists():
    print(f"[Patch] Kopia zapasowa już istnieje: {BACKUP}")
    odp = input("Nadpisać backup i zastosować patch ponownie? (t/n): ").strip().lower()
    if odp != "t":
        print("Anulowano.")
        sys.exit(0)

# Kopia zapasowa
shutil.copy2(PLIK, BACKUP)
print(f"[Patch] Kopia zapasowa: {BACKUP}")

kod = PLIK.read_text(encoding="utf-8")

# ── Sprawdź czy patch już był zastosowany ────────────────────────────
if "OPCJA_AI_FOOTSTATS_PATCH" in kod:
    print("[Patch] Opcja AI już była dodana wcześniej. Nic do zrobienia.")
    sys.exit(0)

# ════════════════════════════════════════════════════════════════════
#  PATCH 1 – Importy AI na początku main()
#  Dodaj po linii: cache_kolejki: list = []
# ════════════════════════════════════════════════════════════════════

STARY_IMPORT = "    cache_kolejki: list = []\n    cache_pewniaczki: list = []"
NOWY_IMPORT  = """    cache_kolejki: list = []
    cache_pewniaczki: list = []

    # ── AI moduły (opcja AI) – ładuj jeśli dostępne ──────────────────
    # OPCJA_AI_FOOTSTATS_PATCH
    _ai_dostepne = False
    try:
        from ai_client   import zapytaj_ai        as _zapytaj_ai    # noqa: F401
        from ai_analyzer import analizuj_mecz_ai  as _analizuj_ai   # noqa: F401
        from ai_analyzer import wyswietl_analiza_ai as _pokaz_ai    # noqa: F401
        from scraper_kursy import szukaj_kursy_meczu as _kursy_ai   # noqa: F401
        _ai_dostepne = True
    except ImportError:
        pass"""

if STARY_IMPORT not in kod:
    print("BŁĄD: Nie znaleziono punktu wstrzyknięcia importów.")
    print("Być może footstats.py ma inną wersję niż oczekiwana.")
    sys.exit(1)

kod = kod.replace(STARY_IMPORT, NOWY_IMPORT, 1)
print("[Patch 1/3] Dodano importy AI ✓")

# ════════════════════════════════════════════════════════════════════
#  PATCH 2 – Wpis w menu (wyświetlanie)
#  Dodaj przed: console.print("[bold]0[/bold]  Wyjscie\n")
# ════════════════════════════════════════════════════════════════════

STARY_MENU = '        console.print("[bold]0[/bold]  Wyjscie\\n")'
NOWY_MENU  = '''        if _ai_dostepne:
            console.print(
                "[bold yellow]I[/bold yellow]  "
                "[bold yellow]🤖 AI Analiza meczu[/bold yellow]  "
                "[dim yellow](Groq 70B / Ollama + kursy bukmacherów)[/dim yellow]"
            )
            console.print(
                "[bold yellow]J[/bold yellow]  "
                "[bold yellow]🤖 AI Analiza kolejki[/bold yellow]  "
                "[dim yellow](wszystkie nadchodzące mecze)[/dim yellow]"
            )
        console.print("[bold]0[/bold]  Wyjscie\\n")'''

if STARY_MENU not in kod:
    print("BŁĄD: Nie znaleziono miejsca na wpis w menu.")
    sys.exit(1)

kod = kod.replace(STARY_MENU, NOWY_MENU, 1)
print("[Patch 2/3] Dodano pozycje w menu ✓")

# ════════════════════════════════════════════════════════════════════
#  PATCH 3 – choices lista + handler opcji AI
#  Dodaj "i","j" do choices i handler w bloku elif
# ════════════════════════════════════════════════════════════════════

STARY_CHOICES = '        choices = ["0","1","2","3","4","5","6","7","9","a","A","k","K","c","C","p","P"]'
NOWY_CHOICES  = '        choices = ["0","1","2","3","4","5","6","7","9","a","A","k","K","c","C","p","P","i","I","j","J"]'

if STARY_CHOICES not in kod:
    print("BŁĄD: Nie znaleziono listy choices.")
    sys.exit(1)

kod = kod.replace(STARY_CHOICES, NOWY_CHOICES, 1)
print("[Patch 3/3] Zaktualizowano choices ✓")

# ════════════════════════════════════════════════════════════════════
#  PATCH 4 – Handler opcji I i J (wstaw przed elif wybor == "0")
# ════════════════════════════════════════════════════════════════════

STARY_HANDLER = '        elif wybor == "0":\n            console.print(f"\\n[bold blue]Do zobaczenia! FootStats {VERSION}[/bold blue]\\n")\n            break'
NOWY_HANDLER  = '''        elif wybor in ("i",):
            # ── AI ANALIZA POJEDYNCZEGO MECZU ───────────────────────
            console.print()
            if not _ai_dostepne:
                console.print("[red]Brak modułów AI. Sprawdź ai_client.py i ai_analyzer.py.[/red]")
            else:
                g, a = wybierz_druzyny(df_wyniki)
                console.print()

                # Oblicz predykcję FootStats
                from rich.progress import Progress, SpinnerColumn, TextColumn
                imp_g  = imp.analiza(g, df_tabela, n_druzyn, kod_ligi, datetime.now())
                imp_a  = imp.analiza(a, df_tabela, n_druzyn, kod_ligi, datetime.now())
                heur_g = heur.analiza(g, df_wyniki)
                heur_a = heur.analiza(a, df_wyniki)
                h2h_g  = h2h.analiza(g, a)
                h2h_a  = h2h.analiza(a, g)
                fort_g = fort.analiza(g)
                klas_m = klas.klasyfikuj(g, a, "REGULAR_SEASON", datetime.now(), None, None)

                with Progress(SpinnerColumn(style="yellow"),
                              TextColumn("[yellow]Obliczam Poissona...[/yellow]"),
                              console=console, transient=True) as _pg:
                    _pg.add_task("", total=None)
                    wynik_fs = predict_match(
                        g, a, df_wyniki, imp_g, imp_a, heur_g, heur_a,
                        h2h_g, h2h_a, fort_g, klasyfikacja=klas_m)

                if not wynik_fs:
                    console.print("[red]Za mało danych dla tej pary.[/red]")
                else:
                    wyswietl_predykcje(wynik_fs)

                    # Pobierz kursy z Betexplorer
                    console.print()
                    _liga_slug = Prompt.ask(
                        "[dim]Liga dla kursów bukmacherskich (Enter=pomiń)[/dim]",
                        default=""
                    ).strip()
                    _kursy = None
                    if _liga_slug:
                        with Progress(SpinnerColumn(style="cyan"),
                                      TextColumn("[cyan]Pobieram kursy...[/cyan]"),
                                      console=console, transient=True) as _pg2:
                            _pg2.add_task("", total=None)
                            try:
                                _kursy = _kursy_ai(g, a, _liga_slug)
                            except Exception as _e:
                                console.print(f"[yellow]Kursy niedostępne: {_e}[/yellow]")

                    # Pobierz formę jako string
                    def _forma_str(druz, n=5):
                        try:
                            df_f = df_wyniki[
                                (df_wyniki["gospodarz"]==druz) | (df_wyniki["goscie"]==druz)
                            ].tail(n)
                            wyniki = []
                            for _, r in df_f.iterrows():
                                if r["gospodarz"] == druz:
                                    wyniki.append("W" if r["gole_g"]>r["gole_a"] else ("R" if r["gole_g"]==r["gole_a"] else "P"))
                                else:
                                    wyniki.append("W" if r["gole_a"]>r["gole_g"] else ("R" if r["gole_g"]==r["gole_a"] else "P"))
                            return "".join(wyniki)
                        except Exception:
                            return "-"

                    _h2h_opis = wynik_fs["h2h_g"].get("opis", "-") or "-"

                    with Progress(SpinnerColumn(style="yellow"),
                                  TextColumn("[yellow]🤖 AI analizuje mecz...[/yellow]"),
                                  console=console, transient=True) as _pg3:
                        _pg3.add_task("", total=None)
                        _wynik_ai = _analizuj_ai(
                            gospodarz          = g,
                            goscie             = a,
                            p_wygrana          = wynik_fs["p_wygrana"],
                            p_remis            = wynik_fs["p_remis"],
                            p_przegrana        = wynik_fs["p_przegrana"],
                            btts               = wynik_fs["btts"],
                            over25             = wynik_fs["over25"],
                            forma_g            = _forma_str(g),
                            forma_a            = _forma_str(a),
                            h2h_opis           = _h2h_opis,
                            pewnosc_modelu     = wynik_fs.get("pewnosc", 0),
                            komentarz_footstats= komentarz_analityka(wynik_fs),
                            kursy              = _kursy,
                        )
                    _pokaz_ai(_wynik_ai)

        elif wybor in ("j",):
            # ── AI ANALIZA CAŁEJ KOLEJKI ─────────────────────────────
            console.print()
            if not _ai_dostepne:
                console.print("[red]Brak modułów AI.[/red]")
            elif df_nadchodzace is None or df_nadchodzace.empty:
                console.print("[yellow]Brak nadchodzących meczów. Najpierw wybierz ligę (opcja 7).[/yellow]")
            else:
                if not cache_kolejki:
                    console.print("[yellow]Najpierw uruchom analizę kolejki (opcja 5) dla pełnych danych.[/yellow]")
                    if not Confirm.ask("Kontynuować z uproszczoną analizą?", default=True):
                        pass
                    else:
                        cache_kolejki = analiza_kolejki(
                            df_nadchodzace, df_wyniki, imp, heur, h2h, fort, klas)

                if cache_kolejki:
                    _liga_slug_j = Prompt.ask(
                        "[dim]Liga dla kursów bukmacherskich (Enter=pomiń)[/dim]",
                        default=""
                    ).strip()

                    console.print(f"[cyan]Analizuję {len(cache_kolejki)} meczów z AI...[/cyan]")
                    _wyniki_ai_j = []
                    for _i, _m in enumerate(cache_kolejki, 1):
                        _g = _m.get("gospodarz", "")
                        _a = _m.get("gosc", "")
                        console.print(f"  [{_i}/{len(cache_kolejki)}] {_g} vs {_a}")
                        _k = None
                        if _liga_slug_j:
                            try:
                                _k = _kursy_ai(_g, _a, _liga_slug_j)
                            except Exception:
                                pass
                        try:
                            _wyn = _analizuj_ai(
                                gospodarz      = _g,
                                goscie         = _a,
                                p_wygrana      = _m.get("p_wygrana", 33),
                                p_remis        = _m.get("p_remis", 33),
                                p_przegrana    = _m.get("p_przegrana", 34),
                                btts           = _m.get("btts", 0),
                                over25         = _m.get("over25", 0),
                                pewnosc_modelu = _m.get("pewnosc", 0),
                                komentarz_footstats = _m.get("komentarz", ""),
                                kursy          = _k,
                            )
                            _pokaz_ai(_wyn)
                            _wyniki_ai_j.append(_wyn)
                        except Exception as _e:
                            console.print(f"  [red]Błąd AI dla {_g} vs {_a}: {_e}[/red]")

                    if _wyniki_ai_j:
                        import json as _json
                        _plik_ai = f"ai_kolejka_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
                        Path(_plik_ai).write_text(
                            _json.dumps(_wyniki_ai_j, ensure_ascii=False, indent=2),
                            encoding="utf-8"
                        )
                        console.print(f"[green]Zapisano: {_plik_ai}[/green]")

        elif wybor == "0":
            console.print(f"\\n[bold blue]Do zobaczenia! FootStats {VERSION}[/bold blue]\\n")
            break'''

if STARY_HANDLER not in kod:
    print("BŁĄD: Nie znaleziono bloku wyjścia (wybor == 0).")
    print("Zapisuję częściowe zmiany i kończę...")
    PLIK.write_text(kod, encoding="utf-8")
    sys.exit(1)

kod = kod.replace(STARY_HANDLER, NOWY_HANDLER, 1)
print("[Patch 4/4] Dodano handlery opcji I i J ✓")

# ── Zapisz ──────────────────────────────────────────────────────────
PLIK.write_text(kod, encoding="utf-8")

print()
print("═" * 55)
print("  Patch zastosowany pomyślnie!")
print("═" * 55)
print()
print("W menu FootStats pojawiły się nowe opcje:")
print("  I  – 🤖 AI Analiza meczu (wybrany mecz)")
print("  J  – 🤖 AI Analiza kolejki (wszystkie mecze)")
print()
print("Uruchom: python footstats.py")
print()
print(f"Kopia zapasowa: {BACKUP.resolve()}")

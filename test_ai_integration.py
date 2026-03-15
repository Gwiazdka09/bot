"""
test_ai_integration.py – Testy integracyjne FootStats AI
=========================================================
Sprawdza WSZYSTKIE nowe moduły AI bez zużywania tokenów API.

Co testuje:
  ✔ ai_client.py        – Groq, Ollama, fallback, brak kluczy
  ✔ ai_analyzer.py      – analiza meczu, wyciąganie JSON, value bet
  ✔ scraper_kursy.py    – parsowanie kursów, cache, szukanie meczu
  ✔ patch footstats.py  – czy opcje I/J są w menu, czy importy działają
  ✔ .env                – czy klucze są obecne (NIE wysyła zapytań)
  ✔ .gitignore          – czy .env jest chroniony

Uruchomienie:
    python test_ai_integration.py
    python test_ai_integration.py -v        (verbose)
    python -m pytest test_ai_integration.py -v

Legenda wyników:
    ✓  PASS  – działa poprawnie
    ✗  FAIL  – błąd do naprawienia
    ⚠  SKIP  – pominięto (np. brak klucza API)
"""

import sys
import os
import json
import time
import unittest
import tempfile
import importlib
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime

# ── Kolory terminala ─────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def zielony(t):  return f"{GREEN}✓ {t}{RESET}"
def czerwony(t): return f"{RED}✗ {t}{RESET}"
def zolty(t):    return f"{YELLOW}⚠ {t}{RESET}"

# ── Upewnij się że jesteśmy w F:\bot ─────────────────────────────────
BOT_DIR = Path(__file__).parent
sys.path.insert(0, str(BOT_DIR))


# ════════════════════════════════════════════════════════════════════
#  BLOK 1 – ŚRODOWISKO I PLIKI
# ════════════════════════════════════════════════════════════════════

class TestSrodowisko(unittest.TestCase):
    """Sprawdza czy wszystkie pliki są na miejscu i .env jest bezpieczny."""

    def test_01_pliki_ai_istnieja(self):
        """Wszystkie pliki AI muszą być w F:\\bot\\"""
        wymagane = ["ai_client.py", "ai_analyzer.py", "scraper_kursy.py", "footstats.py"]
        brakujace = [f for f in wymagane if not (BOT_DIR / f).exists()]
        self.assertEqual(brakujace, [], f"Brakuje plików: {brakujace}")

    def test_02_env_istnieje(self):
        """.env musi istnieć z kluczami API"""
        env = BOT_DIR / ".env"
        self.assertTrue(env.exists(), ".env nie istnieje – uruchom footstats.py żeby go stworzyć")

    def test_03_env_ma_klucze(self):
        """Klucze API muszą być w .env (nie sprawdzamy ich poprawności)"""
        env_tekst = (BOT_DIR / ".env").read_text(encoding="utf-8")
        self.assertIn("FOOTBALL_API_KEY", env_tekst, "Brak FOOTBALL_API_KEY w .env")

    def test_04_env_ma_groq(self):
        """Klucz Groq powinien być w .env"""
        env_tekst = (BOT_DIR / ".env").read_text(encoding="utf-8")
        ma_groq = "GROQ_API_KEY" in env_tekst
        if not ma_groq:
            self.skipTest("GROQ_API_KEY nie ma w .env – dodaj klucz z console.groq.com")
        # Sprawdź czy nie jest placeholder
        for linia in env_tekst.splitlines():
            if linia.startswith("GROQ_API_KEY"):
                wartosc = linia.split("=", 1)[-1].strip().strip('"').strip("'")
                self.assertTrue(
                    wartosc.startswith("gsk_") and len(wartosc) > 20,
                    f"GROQ_API_KEY wygląda jak placeholder: '{wartosc[:20]}...'"
                )

    def test_05_gitignore_chroni_env(self):
        """.gitignore musi zawierać .env"""
        gitignore = BOT_DIR / ".gitignore"
        self.assertTrue(gitignore.exists(), ".gitignore nie istnieje!")
        tekst = gitignore.read_text(encoding="utf-8")
        self.assertIn(".env", tekst, ".gitignore nie chroni .env – NIEBEZPIECZNE!")

    def test_06_backup_istnieje(self):
        """Kopia zapasowa footstats powinna istnieć po patchu"""
        backup = BOT_DIR / "footstats_BACKUP.py"
        self.assertTrue(backup.exists(),
            "Brak footstats_BACKUP.py – czy patch_footstats_ai.py był uruchomiony?")

    def test_07_patch_zastosowany(self):
        """footstats.py musi zawierać marker patcha AI"""
        kod = (BOT_DIR / "footstats.py").read_text(encoding="utf-8")
        self.assertIn("OPCJA_AI_FOOTSTATS_PATCH", kod,
            "Patch AI nie został zastosowany – uruchom: python patch_footstats_ai.py")

    def test_08_opcje_ij_w_menu(self):
        """Opcje I i J muszą być widoczne w menu footstats.py"""
        kod = (BOT_DIR / "footstats.py").read_text(encoding="utf-8")
        self.assertIn('"i"', kod, "Opcja I nie ma w choices menu")
        self.assertIn('"j"', kod, "Opcja J nie ma w choices menu")
        self.assertIn("AI Analiza meczu", kod, "Tekst 'AI Analiza meczu' nie ma w menu")
        self.assertIn("AI Analiza kolejki", kod, "Tekst 'AI Analiza kolejki' nie ma w menu")


# ════════════════════════════════════════════════════════════════════
#  BLOK 2 – AI CLIENT
# ════════════════════════════════════════════════════════════════════

class TestAiClient(unittest.TestCase):
    """Testuje ai_client.py z mockowaniem sieci."""

    def _import(self):
        """Importuje ai_client ze świeżym stanem."""
        if "ai_client" in sys.modules:
            del sys.modules["ai_client"]
        import ai_client
        return ai_client

    def test_01_import_dziala(self):
        """ai_client.py musi się importować bez błędów"""
        try:
            ai_client = self._import()
            self.assertTrue(hasattr(ai_client, "zapytaj_ai"))
        except ImportError as e:
            self.fail(f"Import ai_client.py nie działa: {e}")

    def test_02_groq_mock_odpowiada(self):
        """Groq z mockiem powinien zwrócić odpowiedź"""
        ai_client = self._import()

        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "Testowa odpowiedź po polsku."

        mock_groq_client = MagicMock()
        mock_groq_client.chat.completions.create.return_value = mock_resp

        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk_testowy_klucz_12345678"}):
            with patch("groq.Groq", return_value=mock_groq_client):
                wynik = ai_client._groq("Test prompt")

        self.assertEqual(wynik, "Testowa odpowiedź po polsku.")
        mock_groq_client.chat.completions.create.assert_called_once()

    def test_03_groq_brak_klucza_zwraca_none(self):
        """Groq bez klucza musi zwrócić None (nie rzucać wyjątku)"""
        ai_client = self._import()
        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            wynik = ai_client._groq("Test")
        self.assertIsNone(wynik)

    def test_04_ollama_mock_odpowiada(self):
        """Ollama z mockiem powinna zwrócić odpowiedź"""
        ai_client = self._import()
        import requests

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "Odpowiedź z Ollamy."}
        mock_resp.raise_for_status = MagicMock()

        with patch("requests.post", return_value=mock_resp):
            wynik = ai_client._ollama("Test prompt")

        self.assertEqual(wynik, "Odpowiedź z Ollamy.")

    def test_05_ollama_offline_zwraca_none(self):
        """Jeśli Ollama nie działa, _ollama() zwraca None (nie crash)"""
        ai_client = self._import()
        import requests

        with patch("requests.post", side_effect=requests.exceptions.ConnectionError("offline")):
            wynik = ai_client._ollama("Test")
        self.assertIsNone(wynik)

    def test_06_zapytaj_ai_fallback_do_ollamy(self):
        """Jeśli Groq zawodzi, zapytaj_ai() przełącza się na Ollama"""
        ai_client = self._import()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "Ollama backup działa."}
        mock_resp.raise_for_status = MagicMock()

        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            with patch("requests.post", return_value=mock_resp):
                wynik = ai_client.zapytaj_ai("Test fallback")

        self.assertEqual(wynik, "Ollama backup działa.")

    def test_07_zapytaj_ai_blad_gdy_oba_padaja(self):
        """Gdy Groq i Ollama niedostępne, musi rzucić RuntimeError"""
        ai_client = self._import()
        import requests

        with patch.dict(os.environ, {"GROQ_API_KEY": ""}):
            with patch("requests.post", side_effect=requests.exceptions.ConnectionError):
                with self.assertRaises(RuntimeError) as ctx:
                    ai_client.zapytaj_ai("Test błędu")
        self.assertIn("Brak dostępnego AI", str(ctx.exception))


# ════════════════════════════════════════════════════════════════════
#  BLOK 3 – AI ANALYZER
# ════════════════════════════════════════════════════════════════════

class TestAiAnalyzer(unittest.TestCase):
    """Testuje ai_analyzer.py z mockowaniem AI."""

    def setUp(self):
        """Mockuj ai_client przed każdym testem."""
        if "ai_analyzer" in sys.modules:
            del sys.modules["ai_analyzer"]
        if "ai_client" in sys.modules:
            del sys.modules["ai_client"]
        # Mock ai_client
        self.mock_ai = MagicMock()
        self.mock_ai.zapytaj_ai = MagicMock()
        sys.modules["ai_client"] = self.mock_ai
        # Mock scraper_kursy
        self.mock_scraper = MagicMock()
        self.mock_scraper.szukaj_kursy_meczu = MagicMock(return_value=None)
        self.mock_scraper.scrape_betexplorer = MagicMock(return_value=[])
        self.mock_scraper.pokaz_dostepne_ligi = MagicMock()
        sys.modules["scraper_kursy"] = self.mock_scraper

    def tearDown(self):
        for m in ["ai_analyzer", "ai_client", "scraper_kursy"]:
            if m in sys.modules:
                del sys.modules[m]

    def _import(self):
        import ai_analyzer
        return ai_analyzer

    def test_01_import_dziala(self):
        """ai_analyzer.py musi się importować"""
        try:
            az = self._import()
            self.assertTrue(hasattr(az, "analizuj_mecz_ai"))
            self.assertTrue(hasattr(az, "wyswietl_analiza_ai"))
        except ImportError as e:
            self.fail(f"Import ai_analyzer.py nie działa: {e}")

    def test_02_wyciagnij_json_czysty(self):
        """_wyciagnij_json() musi parsować poprawny JSON"""
        az = self._import()
        wynik = az._wyciagnij_json('{"typ": "1", "pewnosc": 74, "uzasadnienie": "Test."}')
        self.assertEqual(wynik["typ"], "1")
        self.assertEqual(wynik["pewnosc"], 74)

    def test_03_wyciagnij_json_z_tekstem_wokol(self):
        """_wyciagnij_json() musi znaleźć JSON gdy AI doda tekst dookoła"""
        az = self._import()
        tekst = 'Oto moja odpowiedź: {"typ": "X", "pewnosc": 61, "uzasadnienie": "Remis."} Dziękuję.'
        wynik = az._wyciagnij_json(tekst)
        self.assertEqual(wynik["typ"], "X")

    def test_04_wyciagnij_json_uszkodzony(self):
        """_wyciagnij_json() przy złym JSON zwraca dict z 'brak'"""
        az = self._import()
        wynik = az._wyciagnij_json("To nie jest JSON w ogóle")
        self.assertEqual(wynik["typ"], "brak")
        self.assertEqual(wynik["pewnosc"], 0)

    def test_05_kurs_do_prob(self):
        """_kurs_do_prob() poprawnie liczy prawdopodobieństwo"""
        az = self._import()
        self.assertAlmostEqual(az._kurs_do_prob(2.0),  50.0, places=1)
        self.assertAlmostEqual(az._kurs_do_prob(4.0),  25.0, places=1)
        self.assertAlmostEqual(az._kurs_do_prob(1.5), 66.7, places=1)
        self.assertIsNone(az._kurs_do_prob(None))
        self.assertIsNone(az._kurs_do_prob(0))

    def test_06_value_bet_wykrywa(self):
        """_value_bet() wykrywa gdy model szacuje wyżej niż bukmacher"""
        az = self._import()
        # Model: 52%, bukmacher: 1.85 → ~54% → brak value
        self.assertFalse(az._value_bet(52.0, 1.85))
        # Model: 65%, bukmacher: 3.0 → ~33% → value!
        self.assertTrue(az._value_bet(65.0, 3.0))
        # Brak kursu
        self.assertFalse(az._value_bet(70.0, None))

    def test_07_analizuj_mecz_ai_zwraca_dict(self):
        """analizuj_mecz_ai() musi zwrócić słownik z wymaganymi kluczami"""
        az = self._import()

        self.mock_ai.zapytaj_ai.return_value = json.dumps({
            "typ": "1",
            "pewnosc": 72,
            "uzasadnienie": "Model faworyzuje Manchester City.",
            "value_bet": False,
            "value_bet_opis": "",
            "alternatywny_typ": "Over",
            "ostrzezenia": ""
        })

        wynik = az.analizuj_mecz_ai(
            gospodarz="Manchester City",
            goscie="Arsenal",
            p_wygrana=52.0,
            p_remis=26.0,
            p_przegrana=22.0,
            btts=55.0,
            over25=48.0,
            kursy={"k1": 1.85, "kX": 3.60, "k2": 4.20}
        )

        self.assertEqual(wynik["typ"], "1")
        self.assertEqual(wynik["pewnosc"], 72)
        self.assertEqual(wynik["gospodarz"], "Manchester City")
        self.assertEqual(wynik["goscie"], "Arsenal")
        self.assertIn("k1", wynik)
        self.assertAlmostEqual(wynik["k1"], 1.85)

    def test_08_analizuj_mecz_bez_kursow(self):
        """Analiza działa też bez kursów bukmacherskich"""
        az = self._import()
        self.mock_ai.zapytaj_ai.return_value = '{"typ": "X", "pewnosc": 55, "uzasadnienie": "Wyrównany mecz."}'

        wynik = az.analizuj_mecz_ai(
            gospodarz="Legia",
            goscie="Lech",
            p_wygrana=35.0,
            p_remis=32.0,
            p_przegrana=33.0,
        )
        self.assertEqual(wynik["typ"], "X")
        self.assertIsNone(wynik["k1"])

    def test_09_analizuj_mecz_value_bet_flaga(self):
        """Flaga value_bet ustawia się poprawnie przy kursach"""
        az = self._import()
        # AI zwraca value_bet: true
        self.mock_ai.zapytaj_ai.return_value = json.dumps({
            "typ": "2", "pewnosc": 68,
            "uzasadnienie": "Goście niedocenieni.",
            "value_bet": True, "value_bet_opis": "Kurs 4.5 przy 30% szansie modelu",
            "alternatywny_typ": "", "ostrzezenia": ""
        })
        wynik = az.analizuj_mecz_ai(
            gospodarz="Slavia Praha",
            goscie="Sparta Praha",
            p_wygrana=25.0, p_remis=30.0, p_przegrana=45.0,
            kursy={"k1": 1.60, "kX": 3.80, "k2": 4.50}
        )
        # Własny value bet: model 45%, bukmacher 1/4.5=22.2% → różnica >5% → True
        self.assertTrue(wynik.get("value_2", False))

    def test_10_wyswietl_analiza_ai_nie_crashuje(self):
        """wyswietl_analiza_ai() musi działać bez błędów"""
        az = self._import()
        wynik = {
            "gospodarz": "Test FC", "goscie": "Mock United",
            "typ": "1X", "pewnosc": 78,
            "uzasadnienie": "Gospodarz w dobrej formie.",
            "value_bet": True, "value_bet_opis": "Kurs 1X zawyżony.",
            "alternatywny_typ": "BTTS",
            "ostrzezenia": "Kontuzja bramkarza.",
            "k1": 1.90, "kX": 3.20, "k2": 4.10,
            "p_wygrana": 55.0, "p_remis": 25.0, "p_przegrana": 20.0,
        }
        # Musi działać bez wyjątku
        try:
            az.wyswietl_analiza_ai(wynik)
        except Exception as e:
            self.fail(f"wyswietl_analiza_ai() rzuciło wyjątek: {e}")


# ════════════════════════════════════════════════════════════════════
#  BLOK 4 – SCRAPER KURSÓW
# ════════════════════════════════════════════════════════════════════

class TestScraperKursy(unittest.TestCase):
    """Testuje scraper_kursy.py bez prawdziwego scrapowania."""

    def setUp(self):
        if "scraper_kursy" in sys.modules:
            del sys.modules["scraper_kursy"]

    def test_01_import_dziala(self):
        """scraper_kursy.py musi się importować"""
        try:
            import scraper_kursy
            self.assertTrue(hasattr(scraper_kursy, "scrape_betexplorer"))
            self.assertTrue(hasattr(scraper_kursy, "szukaj_kursy_meczu"))
        except ImportError as e:
            self.fail(f"Import scraper_kursy.py nie działa: {e}")

    def test_02_parsuj_kurs_poprawny(self):
        """_parsuj_kurs() musi poprawnie zamieniać string na float"""
        import scraper_kursy as sc
        self.assertEqual(sc._parsuj_kurs("2.10"), 2.10)
        self.assertEqual(sc._parsuj_kurs("1.85"), 1.85)
        self.assertEqual(sc._parsuj_kurs("10.50"), 10.50)

    def test_03_parsuj_kurs_zly_format(self):
        """_parsuj_kurs() na złym formacie zwraca None"""
        import scraper_kursy as sc
        self.assertIsNone(sc._parsuj_kurs("abc"))
        self.assertIsNone(sc._parsuj_kurs(""))
        self.assertIsNone(sc._parsuj_kurs(None))
        self.assertIsNone(sc._parsuj_kurs("1.00"))   # kurs 1.00 = niemożliwy
        self.assertIsNone(sc._parsuj_kurs("200.0"))  # kurs 200 = niemożliwy

    def test_04_szukaj_kursy_czesciowe_dopasowanie(self):
        """szukaj_kursy_meczu() dopasowuje po częściowej nazwie drużyny"""
        import scraper_kursy as sc

        # Wstrzyknij fałszywe dane do cache
        dane_testowe = [
            {"gospodarz": "Manchester City", "goscie": "Arsenal FC",
             "k1": 1.85, "kX": 3.60, "k2": 4.20, "wynik": "2:1",
             "liga": "premier-league", "data": "15.03", "zrodlo": "test"},
            {"gospodarz": "Liverpool FC", "goscie": "Chelsea",
             "k1": 2.10, "kX": 3.40, "k2": 3.50, "wynik": "1:1",
             "liga": "premier-league", "data": "14.03", "zrodlo": "test"},
        ]
        with patch.object(sc, "scrape_betexplorer", return_value=dane_testowe):
            # Szukaj po skróconej nazwie
            wynik = sc.szukaj_kursy_meczu("Manchester", "Arsenal", "premier-league")
            self.assertIsNotNone(wynik)
            self.assertEqual(wynik["k1"], 1.85)

            # Szukaj drugiego meczu
            wynik2 = sc.szukaj_kursy_meczu("Liverpool", "Chelsea", "premier-league")
            self.assertIsNotNone(wynik2)
            self.assertAlmostEqual(wynik2["kX"], 3.40)

            # Mecz którego nie ma
            brak = sc.szukaj_kursy_meczu("Legia", "Lech", "premier-league")
            self.assertIsNone(brak)

    def test_05_cache_zapis_i_odczyt(self):
        """Cache powinien zapisywać i odczytywać dane z pliku JSON"""
        import scraper_kursy as sc

        with tempfile.TemporaryDirectory() as tmpdir:
            stary_cache = sc.CACHE_DIR
            sc.CACHE_DIR = Path(tmpdir)

            dane = [{"gospodarz": "A", "goscie": "B", "k1": 2.0, "kX": 3.0, "k2": 4.0}]
            sc._zapisz_cache("test-liga", dane)
            odczytane = sc._wczytaj_cache("test-liga")

            sc.CACHE_DIR = stary_cache  # przywróć

        self.assertIsNotNone(odczytane)
        self.assertEqual(len(odczytane), 1)
        self.assertEqual(odczytane[0]["gospodarz"], "A")

    def test_06_ligi_betexplorer_zdefiniowane(self):
        """Wszystkie kluczowe ligi muszą być w słowniku LIGI_BETEXPLORER"""
        import scraper_kursy as sc
        wymagane = ["premier-league", "ekstraklasa", "la-liga", "bundesliga"]
        for liga in wymagane:
            self.assertIn(liga, sc.LIGI_BETEXPLORER, f"Brak ligi '{liga}' w LIGI_BETEXPLORER")


# ════════════════════════════════════════════════════════════════════
#  BLOK 5 – INTEGRACJA: AI ANALYZER + FOOTSTATS DATA
# ════════════════════════════════════════════════════════════════════

class TestIntegracjaAiFootstats(unittest.TestCase):
    """
    Testuje pipeline: dane FootStats → ai_analyzer → wynik AI.
    Wszystko zmockowane — zero tokenów API.
    """

    def setUp(self):
        for m in ["ai_analyzer", "ai_client", "scraper_kursy"]:
            if m in sys.modules:
                del sys.modules[m]

        self.mock_ai = MagicMock()
        self.mock_scraper = MagicMock()
        self.mock_scraper.szukaj_kursy_meczu = MagicMock(return_value=None)
        self.mock_scraper.pokaz_dostepne_ligi = MagicMock()
        sys.modules["ai_client"] = self.mock_ai
        sys.modules["scraper_kursy"] = self.mock_scraper

    def tearDown(self):
        for m in ["ai_analyzer", "ai_client", "scraper_kursy"]:
            if m in sys.modules:
                del sys.modules[m]

    def test_01_pelny_pipeline_mecz(self):
        """Pełny pipeline dla jednego meczu działa end-to-end"""
        import ai_analyzer as az

        # Symuluj dane z predict_match() FootStats
        dane_footstats = {
            "gospodarz": "Legia Warszawa",
            "gosc":      "Lech Poznań",
            "p_wygrana":    48.5,
            "p_remis":      27.3,
            "p_przegrana":  24.2,
            "btts":         58.0,
            "over25":       52.0,
            "pewnosc":      35,
            "h2h_g":        {"opis": "Legia wygrała 3 z ostatnich 5 H2H"},
            "komentarz":    "Model faworyzuje Legię (48.5%), mecz bramkostrzelny.",
        }

        # Symuluj odpowiedź Groq
        self.mock_ai.zapytaj_ai.return_value = json.dumps({
            "typ": "1",
            "pewnosc": 68,
            "uzasadnienie": "Legia ma przewagę H2H i gra u siebie.",
            "value_bet": False,
            "value_bet_opis": "",
            "alternatywny_typ": "Over",
            "ostrzezenia": "Mecz derbowy – wynik trudny do przewidzenia."
        })

        wynik = az.analizuj_mecz_ai(
            gospodarz          = dane_footstats["gospodarz"],
            goscie             = dane_footstats["gosc"],
            p_wygrana          = dane_footstats["p_wygrana"],
            p_remis            = dane_footstats["p_remis"],
            p_przegrana        = dane_footstats["p_przegrana"],
            btts               = dane_footstats["btts"],
            over25             = dane_footstats["over25"],
            h2h_opis           = dane_footstats["h2h_g"]["opis"],
            pewnosc_modelu     = dane_footstats["pewnosc"],
            komentarz_footstats= dane_footstats["komentarz"],
        )

        self.assertEqual(wynik["typ"], "1")
        self.assertGreater(wynik["pewnosc"], 0)
        self.assertEqual(wynik["gospodarz"], "Legia Warszawa")
        self.assertEqual(wynik["goscie"], "Lech Poznań")

        # Sprawdź że prompt zawierał dane FootStats (AI było dobrze poinformowane)
        call_args = self.mock_ai.zapytaj_ai.call_args[0][0]
        self.assertIn("Legia Warszawa", call_args)
        self.assertIn("48.5", call_args)
        self.assertIn("Poissona", call_args)

    def test_02_pipeline_z_kursami(self):
        """Pipeline z kursami bukmacherów liczy value bet"""
        import ai_analyzer as az

        self.mock_ai.zapytaj_ai.return_value = json.dumps({
            "typ": "2", "pewnosc": 71,
            "uzasadnienie": "Goście niedocenieni przez bukmachera.",
            "value_bet": True,
            "value_bet_opis": "Kurs 4.50 przy 35% modelu = value",
            "alternatywny_typ": "", "ostrzezenia": ""
        })

        wynik = az.analizuj_mecz_ai(
            gospodarz="Wisła Kraków",
            goscie="Cracovia",
            p_wygrana=30.0, p_remis=35.0, p_przegrana=35.0,
            kursy={"k1": 2.20, "kX": 3.10, "k2": 4.50}
        )

        # Model 35% vs bukmacher 1/4.5=22% → różnica 13% → value!
        self.assertTrue(wynik["value_2"])
        self.assertAlmostEqual(wynik["k2"], 4.50)

    def test_03_lista_meczow_zapisuje_json(self):
        """analizuj_liste_meczow() zapisuje wyniki do pliku JSON"""
        import ai_analyzer as az

        self.mock_ai.zapytaj_ai.return_value = json.dumps({
            "typ": "1X", "pewnosc": 74, "uzasadnienie": "Solidna drużyna domowa.",
            "value_bet": False, "value_bet_opis": "",
            "alternatywny_typ": "Over", "ostrzezenia": ""
        })

        mecze = [
            {"gospodarz": "Team A", "gosc": "Team B",
             "p_wygrana": 55.0, "p_remis": 25.0, "p_przegrana": 20.0,
             "btts": 50.0, "over25": 45.0, "pewnosc": 40, "komentarz": ""},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            stary_dir = os.getcwd()
            os.chdir(tmpdir)
            wyniki = az.analizuj_liste_meczow(mecze, liga="premier-league")
            # Znajdź zapisany plik
            pliki = list(Path(tmpdir).glob("ai_typy_*.json"))
            os.chdir(stary_dir)

        self.assertEqual(len(wyniki), 1)
        self.assertEqual(wyniki[0]["typ"], "1X")
        self.assertEqual(len(pliki), 1, "Brak zapisanego pliku JSON z wynikami")


# ════════════════════════════════════════════════════════════════════
#  BLOK 6 – SZYBKI TEST GROQ (prawdziwy, zużywa 1 token)
# ════════════════════════════════════════════════════════════════════

class TestGroqPrawdziwy(unittest.TestCase):
    """
    Jeden prawdziwy test Groq — zużywa ~10 tokenów.
    Pomijany jeśli brak klucza.
    """

    def test_01_groq_odpowiada_po_polsku(self):
        """Groq musi odpowiedzieć na proste pytanie po polsku"""
        # Sprawdź klucz
        from dotenv import load_dotenv
        load_dotenv(".env")
        klucz = os.getenv("GROQ_API_KEY", "").strip()
        if not klucz or not klucz.startswith("gsk_"):
            self.skipTest("Brak ważnego GROQ_API_KEY – pomijam test sieciowy")

        if "ai_client" in sys.modules:
            del sys.modules["ai_client"]
        import ai_client

        try:
            odp = ai_client.zapytaj_ai(
                "Odpowiedz jednym słowem po polsku: jaki sport jest grany na boisku z bramkami?",
                max_tokens=10
            )
            self.assertIsInstance(odp, str)
            self.assertGreater(len(odp), 0)
            # Odpowiedź powinna zawierać "piłka" lub "futbol" lub "nożna"
            odp_lower = odp.lower()
            znane = any(s in odp_lower for s in ["piłka", "futbol", "nożna", "soccer", "football"])
            if not znane:
                print(f"\n  [INFO] Groq odpowiedział: '{odp}' (akceptowalne)")
        except RuntimeError as e:
            self.fail(f"Groq niedostępny: {e}")


# ════════════════════════════════════════════════════════════════════
#  RUNNER Z CZYTELNYM RAPORTEM
# ════════════════════════════════════════════════════════════════════

class _KolorowyRunner(unittest.TextTestResult):
    def addSuccess(self, test):
        super().addSuccess(test)
        if self.showAll:
            self.stream.write(f"  {zielony('PASS')}  {test.shortDescription() or str(test)}\n")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        if self.showAll:
            self.stream.write(f"  {czerwony('FAIL')}  {test.shortDescription() or str(test)}\n")
            self.stream.write(f"         {str(err[1])}\n")

    def addError(self, test, err):
        super().addError(test, err)
        if self.showAll:
            self.stream.write(f"  {czerwony('ERROR')} {test.shortDescription() or str(test)}\n")
            self.stream.write(f"         {str(err[1])}\n")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        if self.showAll:
            self.stream.write(f"  {zolty('SKIP')}  {test.shortDescription() or str(test)}: {reason}\n")


if __name__ == "__main__":
    verbose = "-v" in sys.argv

    print(f"\n{BOLD}{CYAN}{'═'*60}{RESET}")
    print(f"{BOLD}{CYAN}  FootStats AI – Testy integracyjne{RESET}")
    print(f"{BOLD}{CYAN}  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}{RESET}")
    print(f"{BOLD}{CYAN}{'═'*60}{RESET}\n")

    bloki = [
        ("Środowisko i pliki",              TestSrodowisko),
        ("AI Client (Groq + Ollama)",       TestAiClient),
        ("AI Analyzer",                     TestAiAnalyzer),
        ("Scraper kursów",                  TestScraperKursy),
        ("Integracja AI ↔ FootStats",       TestIntegracjaAiFootstats),
        ("Groq – test sieciowy (1 token)",  TestGroqPrawdziwy),
    ]

    loader = unittest.TestLoader()
    wszystkie_ok = True

    for nazwa, klasa in bloki:
        print(f"{BOLD}▶ {nazwa}{RESET}")
        suite = loader.loadTestsFromTestCase(klasa)
        stream = sys.stdout
        runner = unittest.TextTestRunner(
            stream=stream,
            resultclass=_KolowyRunner if False else unittest.TextTestResult,
            verbosity=2 if verbose else 1,
        )
        wynik = runner.run(suite)
        if not wynik.wasSuccessful():
            wszystkie_ok = False
        n_ok   = wynik.testsRun - len(wynik.failures) - len(wynik.errors) - len(wynik.skipped)
        n_skip = len(wynik.skipped)
        print(f"  → {zielony(str(n_ok))} ok  |  "
              f"{czerwony(str(len(wynik.failures)+len(wynik.errors)))} błędów  |  "
              f"{zolty(str(n_skip))} pominięto\n")

    print(f"{BOLD}{'═'*60}{RESET}")
    if wszystkie_ok:
        print(f"{GREEN}{BOLD}  WSZYSTKIE TESTY PRZESZŁY ✓{RESET}")
        print(f"  System AI gotowy do użycia w FootStats!")
    else:
        print(f"{RED}{BOLD}  Niektóre testy nie przeszły ✗{RESET}")
        print(f"  Sprawdź błędy powyżej i popraw przed użyciem.")
    print(f"{'═'*60}\n")

    sys.exit(0 if wszystkie_ok else 1)

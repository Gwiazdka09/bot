"""Shared Playwright helpers for betting site scrapers."""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SiteConfig:
    name: str
    url: str
    cache_dir: Path
    login_env: str
    password_env: str
    popup_selectors: tuple[str, ...] = (
        "#onetrust-accept-btn-handler",
        "button:has-text('Akceptuję')",
        "[aria-label='Zamknij']",
        "button.close",
    )
    email_selectors: tuple[str, ...] = (
        "input[type='email']",
        "input[placeholder*='e-mail']",
        "input[placeholder*='E-mail']",
    )
    password_selectors: tuple[str, ...] = (
        "input[type='password']",
        "input[placeholder*='Hasło']",
    )
    login_button_selector: str = "button:has-text('Zaloguj się')"
    login_trigger_selector: str = "button:has-text('Zaloguj się'), a:has-text('Zaloguj się')"
    login_success_hidden: str = "button:has-text('Zaloguj się')"
    avatar_selectors: tuple[str, ...] = (
        "[data-cy='user-avatar']",
        ".user-avatar",
        ".profile-icon",
    )


STS_CONFIG = SiteConfig(
    name="STS",
    url="https://www.sts.pl",
    cache_dir=Path("cache/sts"),
    login_env="STS_LOGIN",
    password_env="STS_HASLO",
)

SUPERBET_CONFIG = SiteConfig(
    name="Superbet",
    url="https://www.superbet.pl",
    cache_dir=Path("cache/superbet"),
    login_env="SUPERBET_LOGIN",
    password_env="SUPERBET_PASSWORD",
    popup_selectors=(
        "#onetrust-accept-btn-handler",
        "button:has-text('Akceptuję')",
        "button:has-text('Zgadzam się')",
        "button:has-text('Akceptuj wszystkie')",
        "button:has-text('Akceptuj')",
        "button:has-text('Zamknij')",
        "[aria-label='close']",
        "[aria-label='Zamknij']",
        "button.close",
    ),
    email_selectors=(
        "input[name='username']",
        "input[id*='username']",
        "input[placeholder*='użytkownika']",
        "input[placeholder*='uzytkownika']",
        "input[placeholder*='Nazwa']",
        "input[placeholder*='mail']",
        "input[placeholder*='Login']",
        "input[placeholder*='login']",
        "input[type='email']",
        "input[name='email']",
        "input[name='login']",
    ),
    login_trigger_selector="button:has-text('Zaloguj'), a:has-text('Zaloguj')",
    login_success_hidden="button:has-text('Zaloguj')",
)

SUPEROFERTA_CONFIG = SiteConfig(
    name="STS",
    url="https://www.sts.pl",
    cache_dir=Path("cache/superoferta"),
    login_env="STS_LOGIN",
    password_env="STS_HASLO",
    popup_selectors=(
        "button#onetrust-accept-btn-handler",
        "[aria-label='Zamknij']",
        "button:has-text('Akceptuję')",
    ),
)


def zamknij_popup(page: Page, cfg: SiteConfig) -> None:
    for sel in cfg.popup_selectors:
        try:
            page.click(sel, timeout=2000)
            time.sleep(0.3)
            logger.debug("[%s] Popup zamknięty: %s", cfg.name, sel)
            return
        except Exception:
            pass


def akceptuj_cookies(page: Page, cfg: SiteConfig) -> None:
    for sel in cfg.popup_selectors:
        try:
            page.wait_for_selector(sel, timeout=5000)
            page.click(sel)
            logger.info("[%s] Zaakceptowano cookies", cfg.name)
            time.sleep(1)
            return
        except Exception:
            pass
    logger.info("[%s] Baner cookie nie pojawił się lub już zaakceptowany", cfg.name)


def zaloguj(page: Page, cfg: SiteConfig) -> bool:
    login = os.getenv(cfg.login_env, "").strip()
    haslo = os.getenv(cfg.password_env, "").strip()

    if not login or not haslo:
        logger.info("[%s] Brak %s lub %s w .env", cfg.name, cfg.login_env, cfg.password_env)
        return False

    try:
        try:
            page.click(cfg.login_trigger_selector, timeout=3000)
            time.sleep(1.5)
        except Exception:
            pass

        email_combined = ", ".join(cfg.email_selectors)
        try:
            page.wait_for_selector(email_combined, timeout=5000)
        except PWTimeout:
            logger.info("[%s] Formularz logowania nie pojawił się", cfg.name)
            return False

        for sel in cfg.email_selectors:
            try:
                page.fill(sel, login, timeout=2000)
                break
            except Exception:
                continue

        time.sleep(0.3)

        for sel in cfg.password_selectors:
            try:
                page.fill(sel, haslo, timeout=2000)
                break
            except Exception:
                continue

        time.sleep(0.3)
        page.click(cfg.login_button_selector, timeout=5000)
        time.sleep(3)

        try:
            page.wait_for_selector(cfg.login_success_hidden, state="hidden", timeout=5000)
            logger.info("[%s] Zalogowano", cfg.name)
            return True
        except PWTimeout:
            for sel in cfg.avatar_selectors:
                if page.query_selector(sel):
                    logger.info("[%s] Zalogowano", cfg.name)
                    return True
            logger.info("[%s] Logowanie mogło się nie udać — kontynuuję", cfg.name)
            return False

    except Exception as e:
        logger.info("[%s] Logowanie nieudane: %s", cfg.name, e)
        return False


def zapisz_cache(dane: list, cfg: SiteConfig, nazwa: str = "kupony") -> Path:
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    sciezka = cfg.cache_dir / f"{nazwa}_{ts}.json"
    sciezka.write_text(json.dumps(dane, ensure_ascii=False, indent=2), encoding="utf-8")
    return sciezka

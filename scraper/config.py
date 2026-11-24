"""Crawl settings, read from the environment (or .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from db.env import load_dotenv


@dataclass(frozen=True)
class CrawlSettings:
    contact: str
    min_delay: float = 4.0
    captcha_timeout: float = 300.0
    max_task_attempts: int = 3
    max_captcha_attempts: int = 5

    @property
    def bot_token(self) -> str:
        """Appended to the browser's own User-Agent so NHPR can tell who we are."""
        return f"HealthFacilityFinderBot/0.1 (coding-challenge crawler; contact: {self.contact})"


def load_crawl_settings() -> CrawlSettings:
    load_dotenv()
    contact = os.environ.get("SCRAPER_CONTACT", "").strip()
    if not contact or contact == "your-email@example.com":
        raise SystemExit(
            "Set SCRAPER_CONTACT (in .env) to an email address. It goes into the "
            "User-Agent so the NHPR team can reach whoever is crawling."
        )
    return CrawlSettings(
        contact=contact,
        min_delay=float(os.environ.get("SCRAPER_MIN_DELAY_SECONDS", 4)),
        captcha_timeout=float(os.environ.get("SCRAPER_CAPTCHA_TIMEOUT_SECONDS", 300)),
    )

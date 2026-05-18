"""Abstract base class for all scrapers."""

import sqlite3
import logging
from abc import ABC, abstractmethod

from repository.db import upsert, log_health


class BaseScraper(ABC):
    def __init__(self, conn: sqlite3.Connection = None, headless: bool = True, max_pages: int = 20):
        self.conn = conn
        self.headless = headless
        self.max_pages = max_pages
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def scrape(self) -> list:
        """Run the scraper and return list of tender dicts."""
        ...

    def save(self, records: list) -> int:
        if self.conn and records:
            return upsert(self.conn, records)
        return 0

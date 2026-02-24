import asyncio
import csv
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from config import Config


logger = logging.getLogger(__name__)


class QuoteScraper:
    """
    Class-based async scraper that encapsulates:
    - Session management (single aiohttp.ClientSession)
    - Pagination over quote pages
    - Author profile navigation
    - Async-safe author caching
    - Error handling with retries and backoff
    - Rate limiting + concurrency bounds
    """

    def __init__(self):
        self._logger = logging.getLogger(self.__class__.__name__)
        self._timeout = aiohttp.ClientTimeout(
            sock_connect=Config.REQUEST_TIMEOUT_SECONDS,
            sock_read=Config.REQUEST_TIMEOUT_SECONDS,
        )
        self._headers = {
            "User-Agent": Config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        self._semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT_REQUESTS)
        self._author_cache: Dict[str, Dict[str, Optional[str]]] = {}
        self._author_cache_lock = asyncio.Lock()
        self._author_inflight: Dict[str, asyncio.Task[Dict[str, Optional[str]]]] = {}

        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "QuoteScraper":
        self._session = aiohttp.ClientSession(headers=self._headers, timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise RuntimeError("Session not initialized. Use 'async with QuoteScraper(...) as s:'")
        return self._session

    async def fetch_html(self, url: str, *, max_retries: int = 3) -> Optional[str]:
        for attempt in range(1, max_retries + 1):
            try:
                await asyncio.sleep(Config.RATE_LIMIT_DELAY_SECONDS)
                async with self._semaphore:
                    async with self.session.get(url) as response:
                        if response.status != 200:
                            self._logger.warning("Non-200 status (%s) for %s", response.status, url)
                            return None
                        return await response.text()
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                self._logger.error(
                    "Error fetching %s (attempt %d/%d): %s",
                    url,
                    attempt,
                    max_retries,
                    exc,
                )
                if attempt == max_retries:
                    return None
                await asyncio.sleep(attempt)
        return None

    async def get_soup(self, url: str) -> Optional[BeautifulSoup]:
        html = await self.fetch_html(url)
        if html is None:
            return None
        return BeautifulSoup(html, "html.parser")

    async def _fetch_author_info(self, author_url: str) -> Dict[str, Optional[str]]:
        default_info: Dict[str, Optional[str]] = {
            "author_full_name": None,
            "author_born_date": None,
            "author_born_location": None,
        }

        soup = await self.get_soup(author_url)
        if soup is None:
            return default_info

        full_name_el = soup.select_one("h3.author-title")
        born_date_el = soup.select_one("span.author-born-date")
        born_location_el = soup.select_one("span.author-born-location")

        return {
            "author_full_name": full_name_el.get_text(strip=True) if full_name_el else None,
            "author_born_date": born_date_el.get_text(strip=True) if born_date_el else None,
            "author_born_location": born_location_el.get_text(strip=True) if born_location_el else None,
        }

    async def get_author_info(self, author_url: Optional[str]) -> Dict[str, Optional[str]]:
        if not author_url:
            return {
                "author_full_name": None,
                "author_born_date": None,
                "author_born_location": None,
            }

        async with self._author_cache_lock:
            cached = self._author_cache.get(author_url)
            if cached is not None:
                return cached

            inflight = self._author_inflight.get(author_url)
            if inflight is None:
                inflight = asyncio.create_task(self._fetch_author_info(author_url))
                self._author_inflight[author_url] = inflight

        try:
            info = await inflight
        finally:
            async with self._author_cache_lock:
                self._author_inflight.pop(author_url, None)

        async with self._author_cache_lock:
            self._author_cache.setdefault(author_url, info)

        return info

    async def scrape_quotes_page(self, page_url: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        soup = await self.get_soup(page_url)
        if soup is None:
            return [], None

        quotes: List[Dict[str, Any]] = []
        author_urls: List[Optional[str]] = []

        for quote_block in soup.select("div.quote"):
            quote_text_el = quote_block.select_one("span.text")
            author_name_el = quote_block.select_one("small.author")

            if not quote_text_el or not author_name_el:
                continue

            quote_text = quote_text_el.get_text(strip=True)
            author_name = author_name_el.get_text(strip=True)
            tags = [t.get_text(strip=True) for t in quote_block.select("div.tags a.tag")]

            author_link_el = quote_block.select_one("span a[href^='/author/']")
            author_url: Optional[str] = None
            if author_link_el and author_link_el.get("href"):
                author_url = urljoin(Config.BASE_URL, author_link_el["href"])

            quotes.append(
                {
                    "quote_text": quote_text,
                    "author_name": author_name,
                    "tags": tags,
                    "author_full_name": None,
                    "author_born_date": None,
                    "author_born_location": None,
                }
            )
            author_urls.append(author_url)

        author_infos = await asyncio.gather(*(self.get_author_info(u) for u in author_urls))
        for quote, info in zip(quotes, author_infos):
            quote.update(info)

        next_link = soup.select_one("li.next a")
        if next_link and next_link.get("href"):
            next_page_url = urljoin(page_url, next_link["href"])
        else:
            next_page_url = None

        return quotes, next_page_url

    async def scrape_all_quotes(self) -> List[Dict[str, Any]]:
        quotes: List[Dict[str, Any]] = []
        next_page_url: Optional[str] = Config.BASE_URL

        while next_page_url:
            self._logger.info("Scraping page: %s", next_page_url)
            page_quotes, next_page_url = await self.scrape_quotes_page(next_page_url)
            quotes.extend(page_quotes)
            self._logger.info("Scraped %d quotes so far", len(quotes))

        return quotes

    def save_as_csv(self, quotes: List[Dict[str, Any]], path: Optional[str] = None) -> None:
        output_path = path or Config.OUTPUT_CSV

        fieldnames = [
            "quote_text",
            "author_name",
            "tags",
            "author_full_name",
            "author_born_date",
            "author_born_location",
        ]

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for quote in quotes:
                row = dict(quote)
                tags_value = quote.get("tags", [])
                if isinstance(tags_value, list):
                    row["tags"] = ", ".join(tags_value)
                else:
                    row["tags"] = str(tags_value)
                writer.writerow(row)

    def save_as_json(self, quotes: List[Dict[str, Any]], path: Optional[str] = None) -> None:
        output_path = path or Config.OUTPUT_JSON
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(quotes, f, ensure_ascii=False, indent=2)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    Config.validate()

    start_time = time.perf_counter()

    async def _run_and_save() -> int:
        async with QuoteScraper() as scraper:
            quotes = await scraper.scrape_all_quotes()
            scraper.save_as_csv(quotes)
            scraper.save_as_json(quotes)
            return len(quotes)

    count = asyncio.run(_run_and_save())
    duration = time.perf_counter() - start_time

    logger.info("Scraped %d quotes in %.2f seconds", count, duration)
    print(f"Scraped {count} quotes in {duration:.2f} seconds.")


if __name__ == "__main__":
    main()


import asyncio

from bs4 import BeautifulSoup

from config import Config
from scrape_quotes import QuoteScraper


def test_config_defaults_are_valid():
    # Should not raise for default .env/example values
    Config.validate()


class DummyScraper(QuoteScraper):
    """
    QuoteScraper subclass that bypasses network calls for testing by
    returning fixed HTML for page and author URLs.
    """

    PAGE_HTML = """
    <div class="quote">
      <span class="text">“Test quote.”</span>
      <span>
        <small class="author">Test Author</small>
        <a href="/author/test-author">about</a>
      </span>
      <div class="tags">
        <a class="tag">tag1</a>
        <a class="tag">tag2</a>
      </div>
    </div>
    """

    AUTHOR_HTML = """
    <h3 class="author-title">Test Author</h3>
    <span class="author-born-date">January 1, 1900</span>
    <span class="author-born-location">in Test City, Test Country</span>
    """

    async def get_soup(self, url: str):
        if "author" in url:
            return BeautifulSoup(self.AUTHOR_HTML, "html.parser")
        return BeautifulSoup(self.PAGE_HTML, "html.parser")


def test_scrape_quotes_page_parses_quote_and_author():
    async def run():
        scraper = DummyScraper()
        quotes, next_url = await scraper.scrape_quotes_page("https://example.com/page/1")

        assert next_url is None
        assert len(quotes) == 1

        quote = quotes[0]
        assert quote["quote_text"] == "“Test quote.”"
        assert quote["author_name"] == "Test Author"
        assert quote["tags"] == ["tag1", "tag2"]
        assert quote["author_full_name"] == "Test Author"
        assert quote["author_born_date"] == "January 1, 1900"
        assert quote["author_born_location"] == "in Test City, Test Country"

    asyncio.run(run())


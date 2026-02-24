## Python Web Scraping Task – Quotes to Scrape

### Overall approach

- **Libraries**: `asyncio` + `aiohttp` for asynchronous HTTP requests, `BeautifulSoup` for HTML parsing, and `python-dotenv` for configuration from a `.env` file.
- **Configuration**: `config.py` defines a `Config` class that reads environment variables (with defaults) and exposes `Config.validate()` to check that critical values are valid before running.
- **Architecture**: Core logic lives in `QuoteScraper` in `scrape_quotes.py`:
  - Clean separation of concerns (HTTP fetching, parsing, pagination, author scraping, persistence).
  - Reusable methods for different scraping tasks (page vs author scraping).
  - State managed via instance variables (session, semaphore, caches).
- **Session management**: A single `aiohttp.ClientSession` is created per run and reused for all requests (persistent connections + consistent headers).
- **Outputs**: Data is saved to CSV (`quotes.csv`) and JSON (`quotes.json`) as configured in `Config`.

### Pagination and navigation

- **Pagination**: Starting from the base URL (`https://quotes.toscrape.com/`), the script:
  - Parses each page for quote blocks.
  - Looks for the `"Next"` link using the `li.next a` selector.
  - Uses `urljoin` to build the absolute URL for the next page and continues until there is no `"Next"` link.
- **Author pages**:
  - For each quote, the script reads the author profile link using `span a[href^='/author/']`.
  - It then visits the author page and extracts:
    - Full name (`h3.author-title`)
    - Date of birth (`span.author-born-date`)
    - Place of birth (`span.author-born-location`)
  - These details are stored in an async-safe cache keyed by the author URL so subsequent quotes by the same author reuse the already-fetched data.

### Error handling, session management, and rate limiting

- **Session management**: `QuoteScraper` manages a single `aiohttp.ClientSession` instance for all requests, with consistent headers (including a custom `User-Agent`) and request timeouts to keep connections efficient.
- **Author caching**: `QuoteScraper` keeps an in-memory `author_cache` dictionary plus async-safe coordination:
  - An `asyncio.Lock` guards access to the cache and in-flight tasks map.
  - An in-flight task map prevents duplicate simultaneous fetches of the same author profile page when many quotes reference the same author.
- **Error handling**: All HTTP requests go through `QuoteScraper.fetch_html()` which wraps calls in `try`/`except` blocks, catches network and timeout errors, and retries a few times with a short backoff before giving up.
- **Rate limiting and concurrency**:
  - A global `asyncio.Semaphore` limits the number of in-flight HTTP requests (e.g. 10 at once).
  - An `asyncio.sleep(0.5)` before each outbound request provides a simple delay to avoid overwhelming the server and to be polite with traffic.

### Logging and timing

- **Logging**: The scraper uses Python’s `logging` module. On run, `main()` calls `logging.basicConfig()` with a timestamped format at `INFO` level. `QuoteScraper` logs page URLs being scraped, quote counts per page, non-200 responses, and fetch errors (with retry attempt).
- **Timing**: Total run duration is measured with `time.perf_counter()` from start to finish. The final message logs and prints the number of quotes scraped and the elapsed time in seconds.

### Testing

- **Framework**: Tests use **pytest** (see `requirements.txt`).
- **Location**: `test_scrape_quotes.py` in the project root.
- **Coverage**:
  - **Config**: `test_config_defaults_are_valid` ensures `Config.validate()` passes with default/`.env` values.
  - **Parsing**: `test_scrape_quotes_page_parses_quote_and_author` uses a `DummyScraper` (subclass of `QuoteScraper` that overrides `get_soup` with fixed HTML) to assert quote text, author name, tags, and author profile fields are parsed correctly—no live HTTP requests.
- **Run tests** (from project root):
  - `pytest`

### One challenge and how it was addressed

- **Challenge**: Combining asynchronous scraping with caching and concurrency limits in a way that avoids duplicate work and keeps the code reasonably simple.
- **Solution**: I introduced a small async-safe caching layer:
  - A global `author_cache` dictionary keyed by author URL.
  - An `asyncio.Lock` to guard updates to the cache, so only one task writes for a given author while others reuse the stored data.
  - All author fetches run concurrently via `asyncio.gather`, but the semaphore and lock keep concurrency bounded and cache updates safe.

### One improvement with more time

- **Improvement idea**: Add a CLI (e.g. `argparse`) for output paths, max concurrency, and rate-limit delay; optional resume/checkpoint support and more granular metrics when selectors or pages fail.

### How to run

1. **Install dependencies** (ideally in a virtual environment):
   - `pip install -r requirements.txt`
2. **(Optional) Configure with `.env`**:
   - Copy `.env.example` to `.env` and adjust as needed.
   - Keys: `BASE_URL`, `REQUEST_TIMEOUT_SECONDS`, `MAX_CONCURRENT_REQUESTS`, `RATE_LIMIT_DELAY_SECONDS`, `USER_AGENT`, `OUTPUT_CSV`, `OUTPUT_JSON` (defaults documented in `.env.example`).
3. **Run the scraper**:
   - `python scrape_quotes.py`
   - Console and logs will show per-page progress and final count plus total time.
4. **Run tests**:
   - `pytest`
5. **Outputs** (paths from `Config`):
   - `quotes.csv`: All quotes with author and birth details; tags as a comma-separated string.
   - `quotes.json`: Same data as a list of JSON objects; `tags` as a list of strings.

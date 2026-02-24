import os
from dotenv import load_dotenv
from pathlib import Path
from typing import Optional

load_dotenv()

class Config:    
    BASE_URL: str = os.getenv('BASE_URL', 'https://quotes.toscrape.com/')

    # Request Settings
    REQUEST_TIMEOUT_SECONDS: int = int(os.getenv('REQUEST_TIMEOUT_SECONDS', '15'))
    MAX_CONCURRENT_REQUESTS: int = int(os.getenv('MAX_CONCURRENT_REQUESTS', '10'))
    RATE_LIMIT_DELAY_SECONDS: float = float(os.getenv('RATE_LIMIT_DELAY_SECONDS', '0.5'))
    USER_AGENT: str = os.getenv(
        'USER_AGENT',
        'BetternshipQuotesScraper/1.0 (+https://quotes.toscrape.com)'
    )

    # Output Settings
    OUTPUT_CSV: str = os.getenv('OUTPUT_CSV', 'quotes.csv')
    OUTPUT_JSON: str = os.getenv('OUTPUT_JSON', 'quotes.json')

    @classmethod
    def validate(cls):
        """Validate critical configuration values"""
        if not cls.BASE_URL:
            raise ValueError("BASE_URL must be set")

        if cls.REQUEST_TIMEOUT_SECONDS <= 0:
            raise ValueError("REQUEST_TIMEOUT_SECONDS must be positive")

        if cls.RATE_LIMIT_DELAY_SECONDS < 0:
            raise ValueError("RATE_LIMIT_DELAY_SECONDS cannot be negative")
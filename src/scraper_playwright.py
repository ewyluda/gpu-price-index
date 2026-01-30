"""GPU rental rate scraper using Playwright."""

import asyncio
import random
import time
from datetime import datetime
from typing import Dict, List, Optional

from playwright.async_api import async_playwright, Page, Browser
from bs4 import BeautifulSoup

from src.config import TARGET_URL, GPU_MODELS, USER_AGENTS, PAGE_LOAD_TIMEOUT, SCROLL_PAUSE_TIME


class PlaywrightScraper:
    """Scraper implementation using Playwright."""

    def __init__(self, headless: bool = True, slow_mo: int = 100):
        """
        Initialize Playwright scraper.

        Args:
            headless: Run browser in headless mode
            slow_mo: Slow down operations by specified milliseconds
        """
        self.headless = headless
        self.slow_mo = slow_mo
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    async def __aenter__(self):
        """Context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.close()

    async def start(self):
        """Start the browser."""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
            ]
        )

        # Create context with realistic settings
        self.context = await self.browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport={'width': 1920, 'height': 1080},
            locale='en-US',
            timezone_id='America/New_York',
        )

        # Add extra headers
        await self.context.set_extra_http_headers({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })

        self.page = await self.context.new_page()

        # Inject script to remove webdriver property
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

    async def close(self):
        """Close the browser."""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def human_like_scroll(self):
        """Simulate human-like scrolling behavior."""
        # Scroll down slowly
        for _ in range(3):
            await self.page.evaluate('window.scrollBy(0, window.innerHeight / 3)')
            await asyncio.sleep(random.uniform(0.5, 1.5))

        # Scroll back up
        await self.page.evaluate('window.scrollTo(0, 0)')
        await asyncio.sleep(random.uniform(0.5, 1.0))

    async def fetch_page(self, url: str) -> str:
        """
        Fetch page content with anti-detection measures.

        Args:
            url: URL to fetch

        Returns:
            HTML content of the page
        """
        try:
            # Navigate to page
            response = await self.page.goto(
                url,
                wait_until='networkidle',
                timeout=PAGE_LOAD_TIMEOUT * 1000
            )

            print(f"[Playwright] Response status: {response.status}")

            # Wait for page to be fully loaded
            await self.page.wait_for_load_state('domcontentloaded')
            await asyncio.sleep(random.uniform(1, 2))

            # Simulate human behavior
            await self.human_like_scroll()

            # Wait for any dynamic content
            await asyncio.sleep(SCROLL_PAUSE_TIME)

            # Get page content
            content = await self.page.content()

            return content

        except Exception as e:
            print(f"[Playwright] Error fetching page: {e}")
            raise

    def parse_gpu_rates(self, html_content: str) -> List[Dict]:
        """
        Parse GPU rental rates from HTML content.

        Args:
            html_content: HTML content to parse

        Returns:
            List of dictionaries containing GPU rate information
        """
        soup = BeautifulSoup(html_content, 'lxml')
        rates = []

        # Save HTML for debugging
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_file = f"logs/playwright_page_{timestamp}.html"
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"[Playwright] Page content saved to {debug_file}")

        # Look for common patterns in pricing tables
        # These selectors are placeholders and need to be adjusted based on actual site structure

        # Strategy 1: Look for table rows
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                text = row.get_text()
                for gpu_model in GPU_MODELS:
                    if gpu_model in text:
                        print(f"[Playwright] Found {gpu_model} in table row: {text.strip()}")
                        # Extract rate (this is a placeholder - needs actual parsing logic)
                        rates.append({
                            'gpu_model': gpu_model,
                            'raw_text': text.strip(),
                            'timestamp': datetime.now().isoformat(),
                        })

        # Strategy 2: Look for divs/cards with pricing info
        pricing_elements = soup.find_all(['div', 'section', 'article'],
                                         class_=lambda x: x and any(term in str(x).lower()
                                                                   for term in ['price', 'rate', 'cost', 'index', 'gpu']))
        for element in pricing_elements:
            text = element.get_text()
            for gpu_model in GPU_MODELS:
                if gpu_model in text:
                    print(f"[Playwright] Found {gpu_model} in element: {text[:100]}")

        # Strategy 3: Search all text for GPU models
        all_text = soup.get_text()
        for gpu_model in GPU_MODELS:
            if gpu_model in all_text:
                print(f"[Playwright] {gpu_model} found in page content")

        return rates

    async def scrape(self) -> Dict:
        """
        Scrape GPU rental rates from Silicon Data.

        Returns:
            Dictionary containing scraping results and metadata
        """
        start_time = time.time()

        try:
            html_content = await self.fetch_page(TARGET_URL)
            rates = self.parse_gpu_rates(html_content)

            result = {
                'success': True,
                'scraper': 'playwright',
                'timestamp': datetime.now().isoformat(),
                'duration_seconds': time.time() - start_time,
                'rates': rates,
                'page_size_bytes': len(html_content),
            }

            return result

        except Exception as e:
            return {
                'success': False,
                'scraper': 'playwright',
                'timestamp': datetime.now().isoformat(),
                'duration_seconds': time.time() - start_time,
                'error': str(e),
                'rates': [],
            }


async def main():
    """Test the Playwright scraper."""
    print("=" * 60)
    print("Testing Playwright Scraper")
    print("=" * 60)

    async with PlaywrightScraper(headless=True) as scraper:
        result = await scraper.scrape()

        print(f"\nSuccess: {result['success']}")
        print(f"Duration: {result['duration_seconds']:.2f} seconds")

        if result['success']:
            print(f"Page size: {result['page_size_bytes']} bytes")
            print(f"Rates found: {len(result['rates'])}")
            for rate in result['rates']:
                print(f"  - {rate}")
        else:
            print(f"Error: {result.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())

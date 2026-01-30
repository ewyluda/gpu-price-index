"""GPU rental rate scraper using Selenium."""

import random
import time
from datetime import datetime
from typing import Dict, List, Optional

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from bs4 import BeautifulSoup

from src.config import TARGET_URL, GPU_MODELS, USER_AGENTS, PAGE_LOAD_TIMEOUT, SCROLL_PAUSE_TIME


class SeleniumScraper:
    """Scraper implementation using Selenium."""

    def __init__(self, headless: bool = True):
        """
        Initialize Selenium scraper.

        Args:
            headless: Run browser in headless mode
        """
        self.headless = headless
        self.driver: Optional[webdriver.Chrome] = None

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def start(self):
        """Start the browser."""
        chrome_options = Options()

        if self.headless:
            chrome_options.add_argument('--headless=new')

        # Anti-detection options
        chrome_options.add_argument(f'user-agent={random.choice(USER_AGENTS)}')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-setuid-sandbox')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-popup-blocking')
        chrome_options.add_argument('--start-maximized')
        chrome_options.add_argument('--disable-infobars')

        # Additional preferences
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        # Add preferences for better stealth
        prefs = {
            "credentials_enable_service": False,
            "profile.password_manager_enabled": False,
            "profile.default_content_setting_values.notifications": 2,
        }
        chrome_options.add_experimental_option("prefs", prefs)

        try:
            self.driver = webdriver.Chrome(options=chrome_options)

            # Remove webdriver property
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                '''
            })

            self.driver.implicitly_wait(PAGE_LOAD_TIMEOUT)

        except Exception as e:
            print(f"[Selenium] Error starting browser: {e}")
            raise

    def close(self):
        """Close the browser."""
        if self.driver:
            self.driver.quit()

    def human_like_scroll(self):
        """Simulate human-like scrolling behavior."""
        try:
            # Get page height
            page_height = self.driver.execute_script("return document.body.scrollHeight")

            # Scroll down in chunks
            scroll_position = 0
            scroll_increment = page_height // 4

            for _ in range(3):
                scroll_position += scroll_increment
                self.driver.execute_script(f"window.scrollTo(0, {scroll_position})")
                time.sleep(random.uniform(0.5, 1.5))

            # Scroll back to top
            self.driver.execute_script("window.scrollTo(0, 0)")
            time.sleep(random.uniform(0.5, 1.0))

        except Exception as e:
            print(f"[Selenium] Error during scrolling: {e}")

    def fetch_page(self, url: str) -> str:
        """
        Fetch page content with anti-detection measures.

        Args:
            url: URL to fetch

        Returns:
            HTML content of the page
        """
        try:
            # Navigate to page
            self.driver.get(url)

            # Wait for page load
            WebDriverWait(self.driver, PAGE_LOAD_TIMEOUT).until(
                lambda driver: driver.execute_script("return document.readyState") == "complete"
            )

            print(f"[Selenium] Page title: {self.driver.title}")
            print(f"[Selenium] Current URL: {self.driver.current_url}")

            # Random delay to appear more human
            time.sleep(random.uniform(1, 2))

            # Simulate human behavior
            self.human_like_scroll()

            # Wait for dynamic content
            time.sleep(SCROLL_PAUSE_TIME)

            # Get page source
            html_content = self.driver.page_source

            return html_content

        except TimeoutException:
            print(f"[Selenium] Timeout waiting for page to load")
            raise
        except WebDriverException as e:
            print(f"[Selenium] WebDriver error: {e}")
            raise
        except Exception as e:
            print(f"[Selenium] Error fetching page: {e}")
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
        debug_file = f"logs/selenium_page_{timestamp}.html"
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"[Selenium] Page content saved to {debug_file}")

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
                        print(f"[Selenium] Found {gpu_model} in table row: {text.strip()}")
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
                    print(f"[Selenium] Found {gpu_model} in element: {text[:100]}")

        # Strategy 3: Search all text for GPU models
        all_text = soup.get_text()
        for gpu_model in GPU_MODELS:
            if gpu_model in all_text:
                print(f"[Selenium] {gpu_model} found in page content")

        return rates

    def scrape(self) -> Dict:
        """
        Scrape GPU rental rates from Silicon Data.

        Returns:
            Dictionary containing scraping results and metadata
        """
        start_time = time.time()

        try:
            html_content = self.fetch_page(TARGET_URL)
            rates = self.parse_gpu_rates(html_content)

            result = {
                'success': True,
                'scraper': 'selenium',
                'timestamp': datetime.now().isoformat(),
                'duration_seconds': time.time() - start_time,
                'rates': rates,
                'page_size_bytes': len(html_content),
            }

            return result

        except Exception as e:
            return {
                'success': False,
                'scraper': 'selenium',
                'timestamp': datetime.now().isoformat(),
                'duration_seconds': time.time() - start_time,
                'error': str(e),
                'rates': [],
            }


def main():
    """Test the Selenium scraper."""
    print("=" * 60)
    print("Testing Selenium Scraper")
    print("=" * 60)

    with SeleniumScraper(headless=True) as scraper:
        result = scraper.scrape()

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
    main()

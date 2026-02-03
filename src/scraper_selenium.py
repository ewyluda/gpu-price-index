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
        
        This scraper handles the tabbed interface by clicking each GPU tab
        and extracting the price from the active content area.

        Args:
            html_content: HTML content to parse

        Returns:
            List of dictionaries containing GPU rate information
        """
        rates = []
        
        # Save HTML for debugging
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        debug_file = f"logs/selenium_page_{timestamp}.html"
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"[Selenium] Page content saved to {debug_file}")

        # Target GPU models to scrape
        gpu_tabs = ['h100', 'a100', 'b200']
        
        for gpu in gpu_tabs:
            try:
                print(f"[Selenium] Clicking {gpu.upper()} tab...")
                
                # Click the GPU tab button
                tab_button = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, f"radix-_r_0_-trigger-{gpu}"))
                )
                tab_button.click()
                
                # Wait for content to load
                time.sleep(1)
                
                # Wait for the content area to be visible
                content_id = f"radix-_r_0_-content-{gpu}"
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, content_id))
                )
                
                # Extract price from the text-5xl paragraph
                price_element = self.driver.find_element(
                    By.XPATH, 
                    f"//*[@id='{content_id}']//p[contains(@class, 'text-5xl')]"
                )
                price_text = price_element.text.strip()
                
                # Parse the numeric price
                try:
                    rate_usd_per_hour = float(price_text)
                except ValueError:
                    print(f"[Selenium] Warning: Could not parse price '{price_text}' for {gpu.upper()}")
                    continue
                
                rate_data = {
                    'gpu_model': gpu.upper(),
                    'rate_usd_per_hour': rate_usd_per_hour,
                    'timestamp': datetime.now().isoformat(),
                    'source': 'silicon_data',
                }
                
                rates.append(rate_data)
                print(f"[Selenium] ✓ {gpu.upper()}: ${rate_usd_per_hour}/hr")
                
            except TimeoutException:
                print(f"[Selenium] Timeout waiting for {gpu.upper()} content to load")
            except Exception as e:
                print(f"[Selenium] Error extracting {gpu.upper()} rate: {e}")
        
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
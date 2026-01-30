# Setup Instructions

## Prerequisites

- Python 3.8 or higher
- pip (Python package manager)
- Chrome browser (for Selenium)

## Installation

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Playwright Browsers

After installing the Python packages, you need to install the Playwright browser binaries:

```bash
playwright install chromium
```

Or install all browsers:

```bash
playwright install
```

### 3. Install ChromeDriver for Selenium

Selenium requires ChromeDriver to control Chrome. You have several options:

#### Option A: Automatic (Recommended)

Selenium 4.6+ includes Selenium Manager which automatically downloads the correct ChromeDriver:

```bash
# No additional steps needed - it will download automatically
```

#### Option B: Manual Installation

Download ChromeDriver manually:

1. Check your Chrome version: `google-chrome --version` or `chromium --version`
2. Download matching ChromeDriver from: https://chromedriver.chromium.org/downloads
3. Extract and add to PATH

#### Option C: Using WebDriver Manager (Alternative)

```bash
pip install webdriver-manager
```

Then modify `src/scraper_selenium.py` to use it:

```python
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

service = Service(ChromeDriverManager().install())
self.driver = webdriver.Chrome(service=service, options=chrome_options)
```

## Testing the Scrapers

### Run Comparison Test

This will test both Playwright and Selenium scrapers:

```bash
python test_scrapers.py
```

The script will:
- Test both scrapers against the Silicon Data website
- Save HTML content to `logs/` directory for debugging
- Compare performance and success rates
- Provide a recommendation on which scraper to use

### Run Individual Scrapers

Test Playwright only:

```bash
python -m src.scraper_playwright
```

Test Selenium only:

```bash
python -m src.scraper_selenium
```

## Debugging

### View Scraped Content

After running the test, check the `logs/` directory for saved HTML files:

```bash
ls -lh logs/
```

Open the HTML files in a browser to see what content was actually scraped:

```bash
# Linux
xdg-open logs/playwright_page_*.html

# macOS
open logs/playwright_page_*.html

# Windows
start logs/playwright_page_*.html
```

### Run in Non-Headless Mode

To see the browser in action, modify the test script or run with headless=False:

```python
# In test_scrapers.py, change:
async with PlaywrightScraper(headless=False) as scraper:
    # or
with SeleniumScraper(headless=False) as scraper:
```

### Common Issues

#### Issue: 403 Forbidden Error

The website is blocking the scraper. Try:
- Running in non-headless mode
- Adding delays between requests
- Using residential proxies
- Checking if the site requires authentication

#### Issue: ChromeDriver version mismatch

```
SessionNotCreatedException: Message: session not created: This version of ChromeDriver only supports Chrome version X
```

Solution: Update ChromeDriver to match your Chrome version.

#### Issue: Playwright browser not found

```
playwright._impl._api_types.Error: Executable doesn't exist
```

Solution: Run `playwright install chromium`

## Next Steps

1. Review the HTML files saved in `logs/` to understand the page structure
2. Update the parsing logic in `parse_gpu_rates()` methods to extract actual prices
3. Implement database storage
4. Add scheduling for automated collection

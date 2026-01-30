# GPU Rental Rate Tracker

Automated web scraping system to collect and track rental rates for high-end GPUs (H100, A100, B200) from [Silicon Data](https://www.silicondata.com/products/silicon-index).

## Overview

This project provides web scrapers to collect GPU rental pricing data for analytics and trend analysis. It includes implementations using both Playwright and Selenium to handle bot protection and dynamic content.

## Features

- **Dual Scraper Implementation**: Playwright and Selenium versions for maximum compatibility
- **Anti-Bot Detection**: Mimics human browsing behavior to bypass common protections
- **Rate Extraction**: Targets H100, A100, and B200 GPU models
- **Debug Logging**: Saves HTML snapshots for troubleshooting parsing logic
- **Performance Comparison**: Built-in testing to compare both scrapers

## Quick Start

See [SETUP.md](SETUP.md) for detailed installation and setup instructions.

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Run comparison test
python test_scrapers.py
```

## Project Structure

```
gpu-rental-rate/
├── src/
│   ├── config.py              # Configuration settings
│   ├── scraper_playwright.py  # Playwright implementation
│   └── scraper_selenium.py    # Selenium implementation
├── logs/                      # Debug HTML files and results
├── test_scrapers.py          # Comparison test script
├── requirements.txt          # Python dependencies
├── SETUP.md                 # Setup instructions
└── README.md                # This file
```

## Current Status

- [x] Playwright scraper implementation
- [x] Selenium scraper implementation
- [x] Comparison testing framework
- [x] Anti-detection measures
- [ ] Rate parsing logic (requires site structure analysis)
- [ ] Database integration
- [ ] Automated scheduling
- [ ] Analytics dashboard

## Next Steps

1. Test both scrapers to determine which works best
2. Analyze HTML output to refine parsing logic
3. Implement database storage
4. Add scheduling for automated collection
5. Build analytics queries and visualizations

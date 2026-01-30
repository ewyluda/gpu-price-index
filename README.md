# GPU Rental Rate Tracker

Automated web scraping system to collect and track rental rates for high-end GPUs (H100, A100, B200) from [Silicon Data](https://www.silicondata.com/products/silicon-index).

## Overview

This project provides web scrapers to collect GPU rental pricing data for analytics and trend analysis. It includes implementations using both Playwright and Selenium to handle bot protection and dynamic content.

## Features

- **Dual Scraper Implementation**: Playwright and Selenium versions for maximum compatibility
- **Anti-Bot Detection**: Mimics human browsing behavior to bypass common protections
- **Rate Extraction**: Targets H100, A100, and B200 GPU models
- **SQLite Database**: Automatic storage with deduplication and indexing
- **Analytics Engine**: Trend analysis, statistics, and comparison reports
- **Debug Logging**: Saves HTML snapshots for troubleshooting parsing logic
- **Performance Comparison**: Built-in testing to compare both scrapers
- **CSV Export**: Export historical data for external analysis

## Quick Start

See [SETUP.md](SETUP.md) for detailed installation and setup instructions.

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Test database operations
python test_database.py

# Run scraper comparison test (with database storage)
python test_scrapers.py

# Run production collection
python collect_rates.py --scraper playwright --report
```

## Project Structure

```
gpu-rental-rate/
├── src/
│   ├── config.py              # Configuration settings
│   ├── scraper_playwright.py  # Playwright implementation
│   ├── scraper_selenium.py    # Selenium implementation
│   ├── database.py            # Database manager and schema
│   └── analytics.py           # Analytics and reporting
├── logs/                      # Debug HTML files and results
├── data/                      # SQLite database storage
├── test_scrapers.py          # Scraper comparison test
├── test_database.py          # Database operation tests
├── collect_rates.py          # Main collection workflow
├── requirements.txt          # Python dependencies
├── SETUP.md                 # Setup instructions
└── README.md                # This file
```

## Current Status

- [x] Playwright scraper implementation
- [x] Selenium scraper implementation
- [x] Comparison testing framework
- [x] Anti-detection measures
- [x] SQLite database with full schema
- [x] Database connection and insertion logic
- [x] Analytics engine with trend analysis
- [x] CSV export functionality
- [x] Main collection workflow script
- [ ] Rate parsing logic (requires site structure analysis)
- [ ] Automated scheduling (GitHub Actions/cron)
- [ ] Webhook notifications for failures

## Usage

### Collect Rates

```bash
# Use Playwright scraper (recommended)
python collect_rates.py --scraper playwright

# Use Selenium scraper
python collect_rates.py --scraper selenium

# Show analytics report after collection
python collect_rates.py --scraper playwright --report

# Run in visible mode (see browser)
python collect_rates.py --scraper playwright --visible

# Export to CSV
python collect_rates.py --scraper playwright --export-csv data/export.csv
```

### Database Operations

```python
from src.database import DatabaseManager
from src.analytics import GPURateAnalytics

# Initialize database
db = DatabaseManager()

# Get latest rates
latest = db.get_latest_rates(gpu_model='H100', limit=10)

# Get statistics
stats = db.get_rate_statistics('H100', days=7)

# Get analytics
analytics = GPURateAnalytics()
report = analytics.generate_summary_report(days=7)
print(report)

# Compare GPU models
comparison = analytics.compare_gpu_models(days=7)

# Export to CSV
analytics.export_to_csv('data/export.csv', days=30)
```

## Database Schema

The SQLite database includes two main tables:

**gpu_rental_rates**: Stores GPU rental rate observations
- Unique constraint on (timestamp, gpu_model, provider, region) prevents duplicates
- Indexed on gpu_model and timestamp for fast queries
- Stores rate_per_hour, currency, provider, region, availability, and raw data

**scraping_logs**: Tracks scraping attempts and performance
- Records success/failure, duration, rates found, errors
- Helps monitor scraper health and performance

## Next Steps

1. Test both scrapers to determine which works best
2. Analyze HTML output to refine parsing logic
3. Add scheduling for automated collection (GitHub Actions)
4. Set up notifications for scraping failures
5. Create data visualization dashboard

"""Main workflow script to collect GPU rental rates."""

import asyncio
import argparse
import logging
import sys
from datetime import datetime
from typing import Optional

from src.database import DatabaseManager
from src.analytics import GPURateAnalytics
from src.config import TARGET_URL, GPU_MODELS


async def collect_with_playwright(db: DatabaseManager, headless: bool = True) -> dict:
    """
    Collect rates using Playwright scraper.

    Args:
        db: Database manager instance
        headless: Run browser in headless mode

    Returns:
        Scraping result dictionary
    """
    from src.scraper_playwright import PlaywrightScraper

    logging.info("Starting Playwright scraper...")

    try:
        async with PlaywrightScraper(headless=headless) as scraper:
            result = await scraper.scrape()

            # Save to database
            db.log_scraping_attempt(
                timestamp=datetime.fromisoformat(result['timestamp']),
                scraper_type=result['scraper'],
                success=result['success'],
                duration_seconds=result['duration_seconds'],
                rates_found=len(result['rates']),
                error_message=result.get('error'),
                page_size_bytes=result.get('page_size_bytes'),
            )

            if result['success'] and result['rates']:
                for rate in result['rates']:
                    rate['scraper_type'] = result['scraper']
                    rate['source_url'] = TARGET_URL

                inserted = db.insert_rates_batch(result['rates'])
                logging.info(f"Inserted {inserted} rates into database")

            return result

    except Exception as e:
        logging.error(f"Playwright scraper failed: {e}")
        return {
            'success': False,
            'scraper': 'playwright',
            'timestamp': datetime.now().isoformat(),
            'duration_seconds': 0,
            'error': str(e),
            'rates': [],
        }


def collect_with_selenium(db: DatabaseManager, headless: bool = True) -> dict:
    """
    Collect rates using Selenium scraper.

    Args:
        db: Database manager instance
        headless: Run browser in headless mode

    Returns:
        Scraping result dictionary
    """
    from src.scraper_selenium import SeleniumScraper

    logging.info("Starting Selenium scraper...")

    try:
        with SeleniumScraper(headless=headless) as scraper:
            result = scraper.scrape()

            # Save to database
            db.log_scraping_attempt(
                timestamp=datetime.fromisoformat(result['timestamp']),
                scraper_type=result['scraper'],
                success=result['success'],
                duration_seconds=result['duration_seconds'],
                rates_found=len(result['rates']),
                error_message=result.get('error'),
                page_size_bytes=result.get('page_size_bytes'),
            )

            if result['success'] and result['rates']:
                for rate in result['rates']:
                    rate['scraper_type'] = result['scraper']
                    rate['source_url'] = TARGET_URL

                inserted = db.insert_rates_batch(result['rates'])
                logging.info(f"Inserted {inserted} rates into database")

            return result

    except Exception as e:
        logging.error(f"Selenium scraper failed: {e}")
        return {
            'success': False,
            'scraper': 'selenium',
            'timestamp': datetime.now().isoformat(),
            'duration_seconds': 0,
            'error': str(e),
            'rates': [],
        }


async def main(
    scraper_type: str = 'playwright',
    headless: bool = True,
    show_report: bool = False,
    export_csv: Optional[str] = None,
):
    """
    Main workflow to collect GPU rental rates.

    Args:
        scraper_type: Which scraper to use ('playwright' or 'selenium')
        headless: Run browser in headless mode
        show_report: Show analytics report after collection
        export_csv: Export data to CSV file (optional)
    """
    print("=" * 70)
    print("GPU RENTAL RATE COLLECTION WORKFLOW")
    print("=" * 70)
    print(f"Target URL:  {TARGET_URL}")
    print(f"GPU Models:  {', '.join(GPU_MODELS)}")
    print(f"Scraper:     {scraper_type}")
    print(f"Headless:    {headless}")
    print(f"Timestamp:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # Initialize database
    db = DatabaseManager()
    logging.info(f"Database initialized: {db.db_path}")

    # Run scraper
    if scraper_type == 'playwright':
        result = await collect_with_playwright(db, headless=headless)
    elif scraper_type == 'selenium':
        result = collect_with_selenium(db, headless=headless)
    else:
        print(f"Error: Unknown scraper type '{scraper_type}'")
        print("Valid options: 'playwright', 'selenium'")
        sys.exit(1)

    # Print results
    print("\n" + "-" * 70)
    print("COLLECTION RESULTS")
    print("-" * 70)
    print(f"Success:        {result['success']}")
    print(f"Duration:       {result['duration_seconds']:.2f} seconds")
    print(f"Rates Found:    {len(result['rates'])}")

    if not result['success']:
        print(f"Error:          {result.get('error', 'Unknown error')}")
        logging.error(f"Collection failed: {result.get('error')}")
    else:
        print(f"Page Size:      {result.get('page_size_bytes', 0):,} bytes")
        logging.info("Collection completed successfully")

        if result['rates']:
            print("\nGPU Rates Collected:")
            for rate in result['rates']:
                gpu = rate.get('gpu_model', 'Unknown')
                rate_value = rate.get('rate_per_hour')
                if rate_value:
                    print(f"  - {gpu}: ${rate_value:.2f}/hour")
                else:
                    print(f"  - {gpu}: (parsing needed)")

    # Show analytics report if requested
    if show_report:
        print("\n" + "=" * 70)
        print("ANALYTICS REPORT")
        print("=" * 70)
        analytics = GPURateAnalytics(db)
        print(analytics.generate_summary_report(days=7))

    # Export to CSV if requested
    if export_csv:
        print(f"\nExporting data to {export_csv}...")
        analytics = GPURateAnalytics(db)
        analytics.export_to_csv(export_csv, days=30)

    print("\n" + "=" * 70)
    print(f"Database: {db.db_path}")
    print(f"Total Records: {db.get_record_count()}")
    print("=" * 70)


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/collection.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )

    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description='Collect GPU rental rates from Silicon Data'
    )
    parser.add_argument(
        '--scraper',
        type=str,
        choices=['playwright', 'selenium'],
        default='playwright',
        help='Which scraper to use (default: playwright)'
    )
    parser.add_argument(
        '--visible',
        action='store_true',
        help='Run browser in visible mode (not headless)'
    )
    parser.add_argument(
        '--report',
        action='store_true',
        help='Show analytics report after collection'
    )
    parser.add_argument(
        '--export-csv',
        type=str,
        help='Export data to CSV file (e.g., data/export.csv)'
    )

    args = parser.parse_args()

    try:
        asyncio.run(main(
            scraper_type=args.scraper,
            headless=not args.visible,
            show_report=args.report,
            export_csv=args.export_csv,
        ))
    except KeyboardInterrupt:
        print("\n\nCollection interrupted by user.")
        sys.exit(0)
    except Exception as e:
        logging.exception("Fatal error during collection")
        print(f"\n\n❌ Fatal error: {e}")
        sys.exit(1)

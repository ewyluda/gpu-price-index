"""Test Selenium scraper."""

import sys
from datetime import datetime

from src.scraper_selenium import SeleniumScraper
from src.database import DatabaseManager
from src.config import TARGET_URL, GPU_MODELS


def print_results(results: dict):
    """Print scraper results in a formatted way."""
    print(f"\n{'='*60}")
    print(f"Scraper: {results['scraper'].upper()}")
    print(f"{'='*60}")
    print(f"Success: {results['success']}")
    print(f"Timestamp: {results['timestamp']}")
    print(f"Duration: {results['duration_seconds']:.2f} seconds")

    if results['success']:
        print(f"Page Size: {results['page_size_bytes']:,} bytes")
        print(f"Rates Found: {len(results['rates'])}")

        if results['rates']:
            print("\nGPU Rates:")
            for rate in results['rates']:
                gpu = rate.get('gpu_model', 'N/A')
                rate_value = rate.get('rate_usd_per_hour')
                if rate_value:
                    print(f"  - {gpu}: ${rate_value:.2f}/hr")
                else:
                    print(f"  - {gpu}: (no rate)")
        else:
            print("\nNo rates found in the page content.")
    else:
        print(f"\nError: {results.get('error', 'Unknown error')}")


def test_selenium():
    """Test Selenium scraper."""
    print("\n" + "="*60)
    print("TESTING SELENIUM SCRAPER")
    print("="*60)

    try:
        with SeleniumScraper(headless=True) as scraper:
            result = scraper.scrape()
            return result
    except Exception as e:
        return {
            'success': False,
            'scraper': 'selenium',
            'timestamp': datetime.now().isoformat(),
            'duration_seconds': 0,
            'error': str(e),
            'rates': [],
        }


def save_to_database(result: dict, db: DatabaseManager):
    """
    Save scraping results to database.

    Args:
        result: Scraping result dictionary
        db: Database manager instance
    """
    # Log the scraping attempt
    db.log_scraping_attempt(
        timestamp=datetime.fromisoformat(result['timestamp']),
        scraper_type=result['scraper'],
        success=result['success'],
        duration_seconds=result['duration_seconds'],
        rates_found=len(result['rates']),
        error_message=result.get('error'),
        page_size_bytes=result.get('page_size_bytes'),
    )

    # Insert rates if found
    if result['success'] and result['rates']:
        for rate in result['rates']:
            # Add scraper type and source URL to rate data
            rate['scraper_type'] = result['scraper']
            rate['source_url'] = TARGET_URL

        inserted = db.insert_rates_batch(result['rates'])
        print(f"[Database] Inserted {inserted} rates from {result['scraper']} scraper")


def main():
    """Run scraper test."""
    print("\n" + "="*60)
    print("GPU RENTAL RATE SCRAPER TEST")
    print("="*60)
    print(f"Target: {TARGET_URL}")
    print(f"GPU Models: {', '.join(GPU_MODELS)}")

    # Initialize database
    db = DatabaseManager()
    print("\n[Database] Initialized and ready")

    # Test Selenium scraper
    selenium_result = test_selenium()
    print_results(selenium_result)
    save_to_database(selenium_result, db)

    # Print summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    if selenium_result['success']:
        print("Selenium scraper: SUCCESS")
        print(f"  - Found {len(selenium_result['rates'])} GPU rates")
        print(f"  - Duration: {selenium_result['duration_seconds']:.2f}s")
    else:
        print("Selenium scraper: FAILED")
        print(f"  - Error: {selenium_result.get('error', 'Unknown')}")

    # Save results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"logs/scraper_test_{timestamp}.txt"

    with open(results_file, 'w') as f:
        f.write("SCRAPER TEST RESULTS\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Selenium:\n{selenium_result}\n\n")

    print(f"\nResults saved to: {results_file}")
    print(f"Database location: {db.db_path}")
    print(f"Total records in database: {db.get_record_count()}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        sys.exit(1)

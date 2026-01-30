"""Test and compare Playwright and Selenium scrapers."""

import asyncio
import sys
from datetime import datetime

from src.scraper_playwright import PlaywrightScraper
from src.scraper_selenium import SeleniumScraper
from src.database import DatabaseManager


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
                print(f"  - GPU: {rate.get('gpu_model', 'N/A')}")
                print(f"    Text: {rate.get('raw_text', 'N/A')[:100]}...")
        else:
            print("\nNo rates found in the page content.")
    else:
        print(f"\nError: {results.get('error', 'Unknown error')}")


async def test_playwright():
    """Test Playwright scraper."""
    print("\n" + "="*60)
    print("TESTING PLAYWRIGHT SCRAPER")
    print("="*60)

    try:
        async with PlaywrightScraper(headless=True) as scraper:
            result = await scraper.scrape()
            return result
    except Exception as e:
        return {
            'success': False,
            'scraper': 'playwright',
            'timestamp': datetime.now().isoformat(),
            'duration_seconds': 0,
            'error': str(e),
            'rates': [],
        }


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


def compare_results(playwright_result: dict, selenium_result: dict):
    """Compare results from both scrapers."""
    print("\n" + "="*60)
    print("COMPARISON SUMMARY")
    print("="*60)

    comparison = {
        'playwright': {
            'success': playwright_result['success'],
            'duration': playwright_result['duration_seconds'],
            'rates_found': len(playwright_result['rates']),
            'page_size': playwright_result.get('page_size_bytes', 0),
        },
        'selenium': {
            'success': selenium_result['success'],
            'duration': selenium_result['duration_seconds'],
            'rates_found': len(selenium_result['rates']),
            'page_size': selenium_result.get('page_size_bytes', 0),
        }
    }

    print("\n┌─────────────────┬──────────────┬──────────────┐")
    print("│ Metric          │ Playwright   │ Selenium     │")
    print("├─────────────────┼──────────────┼──────────────┤")
    print(f"│ Success         │ {str(comparison['playwright']['success']):12s} │ {str(comparison['selenium']['success']):12s} │")
    print(f"│ Duration (sec)  │ {comparison['playwright']['duration']:12.2f} │ {comparison['selenium']['duration']:12.2f} │")
    print(f"│ Rates Found     │ {comparison['playwright']['rates_found']:12d} │ {comparison['selenium']['rates_found']:12d} │")
    print(f"│ Page Size (KB)  │ {comparison['playwright']['page_size']/1024:12.2f} │ {comparison['selenium']['page_size']/1024:12.2f} │")
    print("└─────────────────┴──────────────┴──────────────┘")

    # Determine winner
    print("\n" + "="*60)
    print("RECOMMENDATION")
    print("="*60)

    if not playwright_result['success'] and not selenium_result['success']:
        print("❌ Both scrapers failed. The website may have strong bot protection.")
        print("   Next steps:")
        print("   - Check the saved HTML files in logs/ directory")
        print("   - Consider using residential proxies")
        print("   - Try running with headless=False to see what's happening")
        print("   - Investigate if the site requires authentication")

    elif playwright_result['success'] and not selenium_result['success']:
        print("✅ Playwright succeeded, Selenium failed.")
        print("   Recommendation: Use Playwright for production.")

    elif selenium_result['success'] and not playwright_result['success']:
        print("✅ Selenium succeeded, Playwright failed.")
        print("   Recommendation: Use Selenium for production.")

    elif playwright_result['success'] and selenium_result['success']:
        # Both succeeded, compare performance
        if comparison['playwright']['rates_found'] > comparison['selenium']['rates_found']:
            print("✅ Playwright found more rates.")
            print("   Recommendation: Use Playwright for production.")
        elif comparison['selenium']['rates_found'] > comparison['playwright']['rates_found']:
            print("✅ Selenium found more rates.")
            print("   Recommendation: Use Selenium for production.")
        elif comparison['playwright']['duration'] < comparison['selenium']['duration']:
            print("✅ Both scrapers succeeded. Playwright is faster.")
            print("   Recommendation: Use Playwright for production.")
        else:
            print("✅ Both scrapers succeeded. Selenium is faster.")
            print("   Recommendation: Use Selenium for production.")

        print("\n   Next steps:")
        print("   - Review the saved HTML files to refine parsing logic")
        print("   - Implement proper rate extraction from raw text")
        print("   - Add retry logic and error handling")


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


async def main():
    """Run both scrapers and compare results."""
    print("\n" + "="*60)
    print("GPU RENTAL RATE SCRAPER COMPARISON TEST")
    print("="*60)
    print(f"Target: {TARGET_URL}")
    print(f"GPU Models: {', '.join(GPU_MODELS)}")

    # Initialize database
    db = DatabaseManager()
    print("\n[Database] Initialized and ready")

    # Test both scrapers
    playwright_result = await test_playwright()
    print_results(playwright_result)
    save_to_database(playwright_result, db)

    selenium_result = test_selenium()
    print_results(selenium_result)
    save_to_database(selenium_result, db)

    # Compare results
    compare_results(playwright_result, selenium_result)

    # Save results to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"logs/comparison_results_{timestamp}.txt"

    with open(results_file, 'w') as f:
        f.write("SCRAPER COMPARISON RESULTS\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Playwright:\n{playwright_result}\n\n")
        f.write(f"Selenium:\n{selenium_result}\n\n")

    print(f"\n📝 Results saved to: {results_file}")
    print(f"📊 Database location: {db.db_path}")
    print(f"📊 Total records in database: {db.get_record_count()}")


if __name__ == "__main__":
    # Import config after we know src is in path
    from src.config import TARGET_URL, GPU_MODELS

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        sys.exit(1)

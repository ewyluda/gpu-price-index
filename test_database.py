"""Test database operations and analytics."""

from datetime import datetime, timedelta
from src.database import DatabaseManager
from src.analytics import GPURateAnalytics


def test_database_operations():
    """Test database insertion and query operations."""
    print("=" * 70)
    print("TESTING DATABASE OPERATIONS")
    print("=" * 70)

    # Initialize database
    db = DatabaseManager("data/test_gpu_rates.db")
    print(f"\n✓ Database initialized: {db.db_path}")

    # Test 1: Insert sample rates
    print("\n1. Testing rate insertion...")
    sample_rates = [
        {
            'timestamp': datetime.now() - timedelta(days=5),
            'gpu_model': 'H100',
            'rate_per_hour': 3.50,
            'currency': 'USD',
            'provider': 'Cloud Provider A',
            'region': 'US-East',
            'scraper_type': 'test',
        },
        {
            'timestamp': datetime.now() - timedelta(days=4),
            'gpu_model': 'H100',
            'rate_per_hour': 3.45,
            'currency': 'USD',
            'provider': 'Cloud Provider B',
            'region': 'US-West',
            'scraper_type': 'test',
        },
        {
            'timestamp': datetime.now() - timedelta(days=3),
            'gpu_model': 'A100',
            'rate_per_hour': 2.20,
            'currency': 'USD',
            'provider': 'Cloud Provider A',
            'region': 'US-East',
            'scraper_type': 'test',
        },
        {
            'timestamp': datetime.now() - timedelta(days=2),
            'gpu_model': 'A100',
            'rate_per_hour': 2.25,
            'currency': 'USD',
            'provider': 'Cloud Provider C',
            'region': 'EU-West',
            'scraper_type': 'test',
        },
        {
            'timestamp': datetime.now() - timedelta(days=1),
            'gpu_model': 'B200',
            'rate_per_hour': 4.50,
            'currency': 'USD',
            'provider': 'Cloud Provider B',
            'region': 'US-West',
            'scraper_type': 'test',
        },
        {
            'timestamp': datetime.now(),
            'gpu_model': 'H100',
            'rate_per_hour': 3.40,
            'currency': 'USD',
            'provider': 'Cloud Provider A',
            'region': 'US-East',
            'scraper_type': 'test',
        },
    ]

    inserted = db.insert_rates_batch(sample_rates)
    print(f"   ✓ Inserted {inserted} sample rates")

    # Test 2: Log scraping attempts
    print("\n2. Testing scraping log...")
    db.log_scraping_attempt(
        timestamp=datetime.now(),
        scraper_type='test',
        success=True,
        duration_seconds=5.2,
        rates_found=6,
        page_size_bytes=15000,
    )
    print("   ✓ Logged scraping attempt")

    # Test 3: Query latest rates
    print("\n3. Testing latest rates query...")
    latest = db.get_latest_rates(limit=3)
    for rate in latest:
        print(f"   - {rate['gpu_model']}: ${rate['rate_per_hour']}/hr ({rate['provider']})")

    # Test 4: Get average rates
    print("\n4. Testing average rate calculation...")
    models = db.get_all_gpu_models()
    for model in models:
        avg = db.get_average_rate(model)
        if avg:
            print(f"   - {model}: ${avg:.2f}/hr average")

    # Test 5: Get statistics
    print("\n5. Testing statistics...")
    for model in models:
        stats = db.get_rate_statistics(model, days=7)
        if stats.get('count', 0) > 0:
            print(f"\n   {model}:")
            print(f"     Count:   {stats['count']}")
            print(f"     Average: ${stats['avg_rate']:.2f}/hr")
            print(f"     Min:     ${stats['min_rate']:.2f}/hr")
            print(f"     Max:     ${stats['max_rate']:.2f}/hr")

    # Test 6: Get rate trends
    print("\n6. Testing rate trends...")
    if models:
        trends = db.get_rate_trend(models[0], days=7)
        print(f"   {models[0]} trend (last 7 days): {len(trends)} data points")

    # Test 7: Get scraping stats
    print("\n7. Testing scraping statistics...")
    scraping_stats = db.get_scraping_stats(days=7)
    for scraper, stats in scraping_stats.items():
        print(f"   {scraper}: {stats['success_rate']:.1f}% success rate")

    print("\n" + "=" * 70)
    print("✅ All database tests passed!")
    print("=" * 70)


def test_analytics():
    """Test analytics functionality."""
    print("\n" + "=" * 70)
    print("TESTING ANALYTICS")
    print("=" * 70)

    # Initialize analytics with test database
    analytics = GPURateAnalytics(DatabaseManager("data/test_gpu_rates.db"))

    # Test 1: Generate summary report
    print("\n1. Summary Report:")
    print(analytics.generate_summary_report(days=7))

    # Test 2: Compare GPU models
    print("\n2. GPU Model Comparison:")
    comparison = analytics.compare_gpu_models(days=7)
    for model, stats in comparison.items():
        print(f"   {model}: ${stats['avg_rate']:.2f}/hr (avg)")

    # Test 3: Best value GPU
    print("\n3. Best Value GPU:")
    best = analytics.get_best_value_gpu(days=7)
    if best:
        print(f"   {best['gpu_model']}: ${best['avg_rate']:.2f}/hr")

    # Test 4: Price trend report
    models = analytics.db.get_all_gpu_models()
    if models:
        print("\n4. Price Trend Report:")
        print(analytics.get_price_trend_report(models[0], days=7))

    # Test 5: Export to CSV
    print("\n5. CSV Export:")
    analytics.export_to_csv("data/test_export.csv", days=30)

    print("\n" + "=" * 70)
    print("✅ All analytics tests passed!")
    print("=" * 70)


if __name__ == "__main__":
    try:
        # Test database operations
        test_database_operations()

        # Test analytics
        test_analytics()

        print("\n" + "=" * 70)
        print("🎉 ALL TESTS COMPLETED SUCCESSFULLY!")
        print("=" * 70)
        print("\nTest database created at: data/test_gpu_rates.db")
        print("Test CSV exported to: data/test_export.csv")
        print("\nYou can now run the scrapers with confidence!")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

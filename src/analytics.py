"""Analytics and reporting for GPU rental rates."""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from src.database import DatabaseManager


class GPURateAnalytics:
    """Analytics and reporting for GPU rental rates."""

    def __init__(self, db_manager: Optional[DatabaseManager] = None):
        """
        Initialize analytics.

        Args:
            db_manager: Database manager instance (creates new if not provided)
        """
        self.db = db_manager or DatabaseManager()

    def generate_summary_report(self, days: int = 7) -> str:
        """
        Generate a comprehensive summary report.

        Args:
            days: Number of days to analyze

        Returns:
            Formatted summary report
        """
        report_lines = []
        report_lines.append("=" * 70)
        report_lines.append(f"GPU RENTAL RATE SUMMARY REPORT")
        report_lines.append(f"Last {days} days")
        report_lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report_lines.append("=" * 70)

        # Get all GPU models
        models = self.db.get_all_gpu_models()

        if not models:
            report_lines.append("\nNo data available in database.")
            return "\n".join(report_lines)

        # Statistics for each GPU model
        report_lines.append("\n" + "-" * 70)
        report_lines.append("GPU MODELS OVERVIEW")
        report_lines.append("-" * 70)

        for model in models:
            stats = self.db.get_rate_statistics(model, days=days)

            if stats.get('count', 0) > 0:
                report_lines.append(f"\n{model}:")
                report_lines.append(f"  Observations: {stats['count']}")
                report_lines.append(f"  Average Rate: ${stats['avg_rate']:.2f}/hour")
                report_lines.append(f"  Min Rate:     ${stats['min_rate']:.2f}/hour")
                report_lines.append(f"  Max Rate:     ${stats['max_rate']:.2f}/hour")
                report_lines.append(f"  Range:        ${stats['max_rate'] - stats['min_rate']:.2f}")
                report_lines.append(f"  First Seen:   {stats['first_observation']}")
                report_lines.append(f"  Last Seen:    {stats['last_observation']}")
            else:
                report_lines.append(f"\n{model}:")
                report_lines.append(f"  No data available for this period")

        # Scraping statistics
        report_lines.append("\n" + "-" * 70)
        report_lines.append("SCRAPING PERFORMANCE")
        report_lines.append("-" * 70)

        scraping_stats = self.db.get_scraping_stats(days=days)

        if scraping_stats:
            for scraper, stats in scraping_stats.items():
                report_lines.append(f"\n{scraper.upper()}:")
                report_lines.append(f"  Total Attempts:   {stats['total_attempts']}")
                report_lines.append(f"  Successful:       {stats['successful']}")
                report_lines.append(f"  Success Rate:     {stats['success_rate']:.1f}%")
                report_lines.append(f"  Avg Duration:     {stats['avg_duration']:.2f}s")
                report_lines.append(f"  Avg Rates Found:  {stats['avg_rates_found']:.1f}")
        else:
            report_lines.append("\nNo scraping logs available.")

        # Database overview
        report_lines.append("\n" + "-" * 70)
        report_lines.append("DATABASE OVERVIEW")
        report_lines.append("-" * 70)
        total_records = self.db.get_record_count()
        report_lines.append(f"Total Records: {total_records}")

        report_lines.append("\n" + "=" * 70)

        return "\n".join(report_lines)

    def compare_gpu_models(self, days: int = 7) -> Dict:
        """
        Compare pricing across different GPU models.

        Args:
            days: Number of days to analyze

        Returns:
            Dictionary with comparison data
        """
        models = self.db.get_all_gpu_models()
        comparison = {}

        for model in models:
            stats = self.db.get_rate_statistics(model, days=days)
            if stats.get('count', 0) > 0:
                comparison[model] = {
                    'avg_rate': stats['avg_rate'],
                    'min_rate': stats['min_rate'],
                    'max_rate': stats['max_rate'],
                    'observations': stats['count'],
                }

        # Sort by average rate
        comparison = dict(sorted(comparison.items(), key=lambda x: x[1]['avg_rate']))

        return comparison

    def get_price_trend_report(self, gpu_model: str, days: int = 30) -> str:
        """
        Generate a price trend report for a specific GPU.

        Args:
            gpu_model: GPU model to analyze
            days: Number of days to analyze

        Returns:
            Formatted trend report
        """
        report_lines = []
        report_lines.append("=" * 70)
        report_lines.append(f"PRICE TREND REPORT: {gpu_model}")
        report_lines.append(f"Last {days} days")
        report_lines.append("=" * 70)

        trend_data = self.db.get_rate_trend(gpu_model, days=days)

        if not trend_data:
            report_lines.append("\nNo data available for this period.")
            return "\n".join(report_lines)

        report_lines.append("\nDate           Avg Rate    Min Rate    Max Rate    Observations")
        report_lines.append("-" * 70)

        for datapoint in trend_data:
            report_lines.append(
                f"{datapoint['date']}    "
                f"${datapoint['avg_rate']:7.2f}    "
                f"${datapoint['min_rate']:7.2f}    "
                f"${datapoint['max_rate']:7.2f}    "
                f"{datapoint['count']:3d}"
            )

        # Calculate trend direction
        if len(trend_data) >= 2:
            first_avg = trend_data[0]['avg_rate']
            last_avg = trend_data[-1]['avg_rate']
            change = last_avg - first_avg
            change_pct = (change / first_avg * 100) if first_avg > 0 else 0

            report_lines.append("\n" + "-" * 70)
            report_lines.append("TREND ANALYSIS")
            report_lines.append("-" * 70)
            report_lines.append(f"Starting Average: ${first_avg:.2f}/hour")
            report_lines.append(f"Ending Average:   ${last_avg:.2f}/hour")
            report_lines.append(f"Change:           ${change:+.2f} ({change_pct:+.1f}%)")

            if change > 0:
                report_lines.append(f"Direction:        INCREASING ↑")
            elif change < 0:
                report_lines.append(f"Direction:        DECREASING ↓")
            else:
                report_lines.append(f"Direction:        STABLE →")

        report_lines.append("\n" + "=" * 70)

        return "\n".join(report_lines)

    def get_best_value_gpu(self, days: int = 7) -> Optional[Dict]:
        """
        Determine which GPU offers the best value.

        Args:
            days: Number of days to analyze

        Returns:
            Dictionary with best value GPU info
        """
        comparison = self.compare_gpu_models(days=days)

        if not comparison:
            return None

        # Sort by average rate (lowest first)
        best_value = min(comparison.items(), key=lambda x: x[1]['avg_rate'])

        return {
            'gpu_model': best_value[0],
            'avg_rate': best_value[1]['avg_rate'],
            'min_rate': best_value[1]['min_rate'],
            'max_rate': best_value[1]['max_rate'],
            'observations': best_value[1]['observations'],
        }

    def export_to_csv(self, output_file: str, days: int = 30):
        """
        Export rate data to CSV file.

        Args:
            output_file: Output CSV file path
            days: Number of days of data to export
        """
        import csv

        start_date = datetime.now() - timedelta(days=days)

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    timestamp,
                    gpu_model,
                    rate_usd_per_hour,
                    currency,
                    provider,
                    region,
                    availability,
                    source_url,
                    scraper_type
                FROM gpu_rental_rates
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
            """, (start_date.isoformat(),))

            rows = cursor.fetchall()

        if not rows:
            print("No data to export.")
            return

        # Write CSV
        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                'Timestamp',
                'GPU Model',
                'Rate USD Per Hour',
                'Currency',
                'Provider',
                'Region',
                'Availability',
                'Source URL',
                'Scraper Type'
            ])

            # Data
            for row in rows:
                writer.writerow([
                    row['timestamp'],
                    row['gpu_model'],
                    row['rate_usd_per_hour'],
                    row['currency'],
                    row['provider'],
                    row['region'],
                    row['availability'],
                    row['source_url'],
                    row['scraper_type'],
                ])

        print(f"Exported {len(rows)} records to {output_file}")


def main():
    """Test analytics functions."""
    print("\n" + "=" * 70)
    print("TESTING GPU RATE ANALYTICS")
    print("=" * 70)

    # Initialize analytics
    analytics = GPURateAnalytics()

    # Generate summary report
    print("\n1. Summary Report:")
    print(analytics.generate_summary_report(days=7))

    # Compare GPU models
    print("\n2. GPU Model Comparison:")
    comparison = analytics.compare_gpu_models(days=7)
    for model, stats in comparison.items():
        print(f"  {model}: ${stats['avg_rate']:.2f}/hr (avg) - {stats['observations']} obs")

    # Best value GPU
    print("\n3. Best Value GPU:")
    best = analytics.get_best_value_gpu(days=7)
    if best:
        print(f"  {best['gpu_model']}: ${best['avg_rate']:.2f}/hr")
    else:
        print("  No data available")

    # Price trend for a specific GPU
    print("\n4. Price Trend Report:")
    models = analytics.db.get_all_gpu_models()
    if models:
        print(analytics.get_price_trend_report(models[0], days=30))

    # Export to CSV
    print("\n5. Exporting to CSV:")
    analytics.export_to_csv("data/gpu_rates_export.csv", days=30)

    print("\n" + "=" * 70)
    print("Analytics tests completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()

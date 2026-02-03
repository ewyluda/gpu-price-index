"""Database manager for GPU rental rate storage and analytics."""

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from contextlib import contextmanager
from pathlib import Path


class DatabaseManager:
    """Manages SQLite database for GPU rental rates."""

    def __init__(self, db_path: str = "data/gpu_rates.db"):
        """
        Initialize database manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)

        # Ensure data directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_database()

    @contextmanager
    def get_connection(self):
        """
        Context manager for database connections.

        Yields:
            sqlite3.Connection: Database connection
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            self.logger.error(f"Database error: {e}")
            raise
        finally:
            conn.close()

    def _init_database(self):
        """Initialize database schema."""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Create gpu_rental_rates table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gpu_rental_rates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    gpu_model VARCHAR(50) NOT NULL,
                    rate_usd_per_hour DECIMAL(10, 4),
                    currency VARCHAR(10) DEFAULT 'USD',
                    provider VARCHAR(100),
                    region VARCHAR(100),
                    availability VARCHAR(50),
                    source_url TEXT,
                    scraper_type VARCHAR(20),
                    raw_data TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(timestamp, gpu_model, provider, region)
                )
            """)

            # Create indices for common queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_gpu_timestamp
                ON gpu_rental_rates(gpu_model, timestamp)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON gpu_rental_rates(timestamp)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_gpu_model
                ON gpu_rental_rates(gpu_model)
            """)

            # Create scraping_logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scraping_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    scraper_type VARCHAR(20) NOT NULL,
                    success BOOLEAN NOT NULL,
                    duration_seconds DECIMAL(10, 2),
                    rates_found INTEGER,
                    error_message TEXT,
                    page_size_bytes INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_scraping_logs_timestamp
                ON scraping_logs(timestamp)
            """)

            self.logger.info(f"Database initialized at {self.db_path}")

    def insert_rate(
        self,
        timestamp: datetime,
        gpu_model: str,
        rate_usd_per_hour: Optional[float] = None,
        currency: str = "USD",
        provider: Optional[str] = None,
        region: Optional[str] = None,
        availability: Optional[str] = None,
        source_url: Optional[str] = None,
        scraper_type: Optional[str] = None,
        raw_data: Optional[str] = None,
    ) -> Optional[int]:
        """
        Insert a GPU rental rate record.

        Args:
            timestamp: When the rate was observed
            gpu_model: GPU model (e.g., 'H100', 'A100', 'B200')
            rate_usd_per_hour: Rental rate per hour in USD
            currency: Currency code (default: 'USD')
            provider: Provider name
            region: Geographic region
            availability: Availability status
            source_url: Source URL
            scraper_type: Which scraper was used
            raw_data: Raw data for debugging

        Returns:
            Inserted row ID, or None if duplicate
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR IGNORE INTO gpu_rental_rates (
                        timestamp, gpu_model, rate_usd_per_hour, currency,
                        provider, region, availability, source_url,
                        scraper_type, raw_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    timestamp.isoformat(),
                    gpu_model,
                    rate_usd_per_hour,
                    currency,
                    provider,
                    region,
                    availability,
                    source_url,
                    scraper_type,
                    raw_data,
                ))

                if cursor.rowcount > 0:
                    self.logger.info(f"Inserted rate for {gpu_model}: ${rate_usd_per_hour}/hr")
                    return cursor.lastrowid
                else:
                    self.logger.debug(f"Duplicate rate skipped for {gpu_model}")
                    return None

        except Exception as e:
            self.logger.error(f"Error inserting rate: {e}")
            raise

    def insert_rates_batch(self, rates: List[Dict]) -> int:
        """
        Insert multiple rate records in a batch.

        Args:
            rates: List of rate dictionaries

        Returns:
            Number of records inserted
        """
        inserted_count = 0

        for rate_data in rates:
            row_id = self.insert_rate(
                timestamp=rate_data.get('timestamp', datetime.now()),
                gpu_model=rate_data['gpu_model'],
                rate_usd_per_hour=rate_data.get('rate_usd_per_hour'),
                currency=rate_data.get('currency', 'USD'),
                provider=rate_data.get('provider'),
                region=rate_data.get('region'),
                availability=rate_data.get('availability'),
                source_url=rate_data.get('source_url'),
                scraper_type=rate_data.get('scraper_type'),
                raw_data=rate_data.get('raw_data'),
            )

            if row_id is not None:
                inserted_count += 1

        self.logger.info(f"Batch insert: {inserted_count}/{len(rates)} records inserted")
        return inserted_count

    def log_scraping_attempt(
        self,
        timestamp: datetime,
        scraper_type: str,
        success: bool,
        duration_seconds: float,
        rates_found: int = 0,
        error_message: Optional[str] = None,
        page_size_bytes: Optional[int] = None,
    ) -> int:
        """
        Log a scraping attempt.

        Args:
            timestamp: When the scraping occurred
            scraper_type: Type of scraper used
            success: Whether scraping succeeded
            duration_seconds: How long it took
            rates_found: Number of rates found
            error_message: Error message if failed
            page_size_bytes: Size of scraped page

        Returns:
            Inserted row ID
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO scraping_logs (
                        timestamp, scraper_type, success, duration_seconds,
                        rates_found, error_message, page_size_bytes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    timestamp.isoformat(),
                    scraper_type,
                    success,
                    duration_seconds,
                    rates_found,
                    error_message,
                    page_size_bytes,
                ))

                self.logger.info(f"Logged scraping attempt: {scraper_type} - {'success' if success else 'failed'}")
                return cursor.lastrowid

        except Exception as e:
            self.logger.error(f"Error logging scraping attempt: {e}")
            raise

    def get_latest_rates(self, gpu_model: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """
        Get the most recent rates.

        Args:
            gpu_model: Filter by GPU model (optional)
            limit: Maximum number of records to return

        Returns:
            List of rate dictionaries
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if gpu_model:
                cursor.execute("""
                    SELECT * FROM gpu_rental_rates
                    WHERE gpu_model = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (gpu_model, limit))
            else:
                cursor.execute("""
                    SELECT * FROM gpu_rental_rates
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            return [dict(row) for row in cursor.fetchall()]

    def get_average_rate(
        self,
        gpu_model: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Optional[float]:
        """
        Calculate average rate for a GPU model.

        Args:
            gpu_model: GPU model to query
            start_date: Start of date range (optional)
            end_date: End of date range (optional)

        Returns:
            Average rate, or None if no data
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if start_date and end_date:
                cursor.execute("""
                    SELECT AVG(rate_usd_per_hour) as avg_rate
                    FROM gpu_rental_rates
                    WHERE gpu_model = ?
                      AND timestamp BETWEEN ? AND ?
                      AND rate_usd_per_hour IS NOT NULL
                """, (gpu_model, start_date.isoformat(), end_date.isoformat()))
            else:
                cursor.execute("""
                    SELECT AVG(rate_usd_per_hour) as avg_rate
                    FROM gpu_rental_rates
                    WHERE gpu_model = ?
                      AND rate_usd_per_hour IS NOT NULL
                """, (gpu_model,))

            result = cursor.fetchone()
            return result['avg_rate'] if result else None

    def get_rate_statistics(
        self,
        gpu_model: str,
        days: int = 7,
    ) -> Dict:
        """
        Get comprehensive statistics for a GPU model.

        Args:
            gpu_model: GPU model to query
            days: Number of days to look back

        Returns:
            Dictionary with min, max, avg, count statistics
        """
        start_date = datetime.now() - timedelta(days=days)

        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as count,
                    MIN(rate_usd_per_hour) as min_rate,
                    MAX(rate_usd_per_hour) as max_rate,
                    AVG(rate_usd_per_hour) as avg_rate,
                    MIN(timestamp) as first_observation,
                    MAX(timestamp) as last_observation
                FROM gpu_rental_rates
                WHERE gpu_model = ?
                  AND timestamp >= ?
                  AND rate_usd_per_hour IS NOT NULL
            """, (gpu_model, start_date.isoformat()))

            result = cursor.fetchone()

            if result and result['count'] > 0:
                return {
                    'gpu_model': gpu_model,
                    'count': result['count'],
                    'min_rate': result['min_rate'],
                    'max_rate': result['max_rate'],
                    'avg_rate': result['avg_rate'],
                    'first_observation': result['first_observation'],
                    'last_observation': result['last_observation'],
                    'days': days,
                }
            else:
                return {
                    'gpu_model': gpu_model,
                    'count': 0,
                    'message': 'No data available for this time period'
                }

    def get_rate_trend(
        self,
        gpu_model: str,
        days: int = 30,
        interval_hours: int = 24,
    ) -> List[Dict]:
        """
        Get rate trends over time.

        Args:
            gpu_model: GPU model to query
            days: Number of days to look back
            interval_hours: Grouping interval in hours

        Returns:
            List of time-series data points
        """
        start_date = datetime.now() - timedelta(days=days)

        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    DATE(timestamp) as date,
                    AVG(rate_usd_per_hour) as avg_rate,
                    MIN(rate_usd_per_hour) as min_rate,
                    MAX(rate_usd_per_hour) as max_rate,
                    COUNT(*) as count
                FROM gpu_rental_rates
                WHERE gpu_model = ?
                  AND timestamp >= ?
                  AND rate_usd_per_hour IS NOT NULL
                GROUP BY DATE(timestamp)
                ORDER BY date
            """, (gpu_model, start_date.isoformat()))

            return [dict(row) for row in cursor.fetchall()]

    def get_scraping_stats(self, days: int = 7) -> Dict:
        """
        Get scraping performance statistics.

        Args:
            days: Number of days to look back

        Returns:
            Dictionary with scraping statistics
        """
        start_date = datetime.now() - timedelta(days=days)

        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    scraper_type,
                    COUNT(*) as total_attempts,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful,
                    AVG(duration_seconds) as avg_duration,
                    AVG(rates_found) as avg_rates_found
                FROM scraping_logs
                WHERE timestamp >= ?
                GROUP BY scraper_type
            """, (start_date.isoformat(),))

            results = cursor.fetchall()

            stats = {}
            for row in results:
                scraper = row['scraper_type']
                stats[scraper] = {
                    'total_attempts': row['total_attempts'],
                    'successful': row['successful'],
                    'success_rate': (row['successful'] / row['total_attempts'] * 100) if row['total_attempts'] > 0 else 0,
                    'avg_duration': row['avg_duration'],
                    'avg_rates_found': row['avg_rates_found'],
                }

            return stats

    def get_all_gpu_models(self) -> List[str]:
        """
        Get list of all GPU models in the database.

        Returns:
            List of GPU model names
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT gpu_model
                FROM gpu_rental_rates
                ORDER BY gpu_model
            """)
            return [row['gpu_model'] for row in cursor.fetchall()]

    def get_record_count(self) -> int:
        """
        Get total number of rate records.

        Returns:
            Total record count
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM gpu_rental_rates")
            result = cursor.fetchone()
            return result['count'] if result else 0


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def main():
    """Test database operations."""
    print("=" * 60)
    print("Testing Database Manager")
    print("=" * 60)

    # Initialize database
    db = DatabaseManager()

    # Test inserting a single rate
    print("\n1. Testing single rate insertion...")
    row_id = db.insert_rate(
        timestamp=datetime.now(),
        gpu_model="H100",
        rate_usd_per_hour=3.50,
        currency="USD",
        provider="Test Provider",
        region="US-East",
        scraper_type="test",
    )
    print(f"   Inserted row ID: {row_id}")

    # Test batch insertion
    print("\n2. Testing batch insertion...")
    test_rates = [
        {
            'timestamp': datetime.now(),
            'gpu_model': 'A100',
            'rate_usd_per_hour': 2.25,
            'provider': 'Provider A',
            'scraper_type': 'test',
        },
        {
            'timestamp': datetime.now(),
            'gpu_model': 'B200',
            'rate_usd_per_hour': 4.00,
            'provider': 'Provider B',
            'scraper_type': 'test',
        },
    ]
    inserted = db.insert_rates_batch(test_rates)
    print(f"   Inserted {inserted} records")

    # Test logging a scraping attempt
    print("\n3. Testing scraping log...")
    log_id = db.log_scraping_attempt(
        timestamp=datetime.now(),
        scraper_type="test",
        success=True,
        duration_seconds=5.2,
        rates_found=3,
        page_size_bytes=15000,
    )
    print(f"   Logged scraping attempt ID: {log_id}")

    # Test queries
    print("\n4. Testing queries...")

    print("\n   Latest rates:")
    latest = db.get_latest_rates(limit=5)
    for rate in latest:
        print(f"   - {rate['gpu_model']}: ${rate['rate_usd_per_hour']}/hr ({rate['timestamp']})")

    print("\n   H100 statistics:")
    stats = db.get_rate_statistics('H100', days=7)
    for key, value in stats.items():
        print(f"   - {key}: {value}")

    print("\n   All GPU models in database:")
    models = db.get_all_gpu_models()
    print(f"   - {', '.join(models)}")

    print("\n   Total records:")
    count = db.get_record_count()
    print(f"   - {count} records")

    print("\n   Scraping statistics:")
    scraping_stats = db.get_scraping_stats(days=7)
    for scraper, stats in scraping_stats.items():
        print(f"   - {scraper}:")
        print(f"     Success rate: {stats['success_rate']:.1f}%")
        print(f"     Avg duration: {stats['avg_duration']:.2f}s")

    print("\n" + "=" * 60)
    print("Database tests completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()

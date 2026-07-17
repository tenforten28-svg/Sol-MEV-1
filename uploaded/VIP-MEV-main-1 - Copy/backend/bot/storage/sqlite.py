"""
SQLITE STORAGE - Persistent Event Storage
==========================================
Append-only storage for all bot events.
Enables replay, analysis, and learning.
"""

import sqlite3
import json
import os
import time
import threading
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from contextlib import contextmanager

from ..events.schema import Event, redact_secrets

logger = logging.getLogger('storage')

# ============================================================================
# CONFIG
# ============================================================================

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'bot_events.sqlite')
MAX_DB_SIZE_MB = 500
RETENTION_DAYS = 30
VACUUM_THRESHOLD_MB = 100

# ============================================================================
# SQLITE STORAGE
# ============================================================================

class SQLiteStorage:
    """
    SQLite storage for bot events.
    Thread-safe, with automatic rotation and vacuum.
    """
    
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._stats = {
            'writes': 0,
            'write_errors': 0,
            'reads': 0,
        }
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # Initialize database
        self._init_db()
        
        logger.info(f"SQLite storage initialized: {db_path}")
    
    @property
    def _conn(self) -> sqlite3.Connection:
        """Get thread-local connection"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn
    
    @contextmanager
    def _get_cursor(self):
        """Get a cursor with automatic commit/rollback"""
        cursor = self._conn.cursor()
        try:
            yield cursor
            self._conn.commit()
        except Exception as e:
            self._conn.rollback()
            raise e
        finally:
            cursor.close()
    
    def _init_db(self):
        """Initialize database schema"""
        with self._get_cursor() as cursor:
            # Events table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    ts_ms INTEGER NOT NULL,
                    slot INTEGER,
                    event_type TEXT NOT NULL,
                    fingerprint TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Indexes for common queries
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts_ms)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_fingerprint ON events(fingerprint)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(event_type, ts_ms)')
            
            # Runs table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    started_ts_ms INTEGER NOT NULL,
                    ended_ts_ms INTEGER,
                    bot_version TEXT,
                    config_json TEXT,
                    stats_json TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Trades table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    opportunity_event_id TEXT,
                    fingerprint TEXT,
                    status TEXT NOT NULL,
                    buy_pool TEXT,
                    sell_pool TEXT,
                    spread_bps REAL,
                    expected_profit_usd REAL,
                    actual_profit_usd REAL,
                    pnl_lamports INTEGER,
                    fees_lamports INTEGER,
                    failure_tag TEXT,
                    signature TEXT,
                    created_ts_ms INTEGER NOT NULL,
                    FOREIGN KEY (opportunity_event_id) REFERENCES events(event_id)
                )
            ''')
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_fingerprint ON trades(fingerprint)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(created_ts_ms)')
            
            # Fingerprint stats table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS fingerprint_stats (
                    fingerprint TEXT PRIMARY KEY,
                    attempts INTEGER DEFAULT 0,
                    successes INTEGER DEFAULT 0,
                    failures INTEGER DEFAULT 0,
                    total_profit_usd REAL DEFAULT 0,
                    avg_spread_bps REAL,
                    avg_latency_ms REAL,
                    half_life_ms REAL,
                    last_attempt_ts_ms INTEGER,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        
        logger.info("Database schema initialized")
    
    def write_event(self, event: Event) -> bool:
        """Write an event to the database"""
        with self._write_lock:
            try:
                event_dict = event.to_dict()
                
                # Redact secrets
                event_dict = redact_secrets(event_dict)
                
                header = event_dict.get('header', {})
                payload = event_dict.get('payload', {})
                
                with self._get_cursor() as cursor:
                    cursor.execute('''
                        INSERT OR REPLACE INTO events 
                        (event_id, ts_ms, slot, event_type, fingerprint, payload_json)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        header.get('event_id'),
                        header.get('ts_ms'),
                        header.get('slot'),
                        event_dict.get('event_type'),
                        header.get('fingerprint'),
                        json.dumps(event_dict, default=str)
                    ))
                
                self._stats['writes'] += 1
                return True
                
            except Exception as e:
                self._stats['write_errors'] += 1
                logger.error(f"DB write error: {e}")
                return False
    
    def write_trade(self, trade: Dict) -> bool:
        """Write a trade record"""
        with self._write_lock:
            try:
                with self._get_cursor() as cursor:
                    cursor.execute('''
                        INSERT OR REPLACE INTO trades
                        (trade_id, opportunity_event_id, fingerprint, status,
                         buy_pool, sell_pool, spread_bps, expected_profit_usd,
                         actual_profit_usd, pnl_lamports, fees_lamports,
                         failure_tag, signature, created_ts_ms)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        trade.get('trade_id'),
                        trade.get('opportunity_event_id'),
                        trade.get('fingerprint'),
                        trade.get('status'),
                        trade.get('buy_pool'),
                        trade.get('sell_pool'),
                        trade.get('spread_bps'),
                        trade.get('expected_profit_usd'),
                        trade.get('actual_profit_usd'),
                        trade.get('pnl_lamports'),
                        trade.get('fees_lamports'),
                        trade.get('failure_tag'),
                        trade.get('signature'),
                        trade.get('created_ts_ms', int(time.time() * 1000))
                    ))
                return True
            except Exception as e:
                logger.error(f"Trade write error: {e}")
                return False
    
    def start_run(self, run_id: str, bot_version: str, config: Dict):
        """Record a new bot run"""
        with self._get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO runs (run_id, started_ts_ms, bot_version, config_json)
                VALUES (?, ?, ?, ?)
            ''', (run_id, int(time.time() * 1000), bot_version, json.dumps(config)))
    
    def end_run(self, run_id: str, stats: Dict):
        """Record end of bot run"""
        with self._get_cursor() as cursor:
            cursor.execute('''
                UPDATE runs SET ended_ts_ms = ?, stats_json = ? WHERE run_id = ?
            ''', (int(time.time() * 1000), json.dumps(stats), run_id))
    
    # =========================================================================
    # QUERIES
    # =========================================================================
    
    def get_events(
        self,
        event_type: Optional[str] = None,
        fingerprint: Optional[str] = None,
        from_ts: Optional[int] = None,
        to_ts: Optional[int] = None,
        limit: int = 1000
    ) -> List[Dict]:
        """Query events with filters"""
        self._stats['reads'] += 1
        
        query = "SELECT * FROM events WHERE 1=1"
        params = []
        
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        
        if fingerprint:
            query += " AND fingerprint = ?"
            params.append(fingerprint)
        
        if from_ts:
            query += " AND ts_ms >= ?"
            params.append(from_ts)
        
        if to_ts:
            query += " AND ts_ms <= ?"
            params.append(to_ts)
        
        query += " ORDER BY ts_ms DESC LIMIT ?"
        params.append(limit)
        
        with self._get_cursor() as cursor:
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            return [
                json.loads(row['payload_json'])
                for row in rows
            ]
    
    def get_event_counts(self, from_ts: Optional[int] = None) -> Dict[str, int]:
        """Get event counts by type"""
        query = "SELECT event_type, COUNT(*) as count FROM events"
        params = []
        
        if from_ts:
            query += " WHERE ts_ms >= ?"
            params.append(from_ts)
        
        query += " GROUP BY event_type"
        
        with self._get_cursor() as cursor:
            cursor.execute(query, params)
            return {row['event_type']: row['count'] for row in cursor.fetchall()}
    
    def get_fingerprint_stats(self, fingerprint: str) -> Optional[Dict]:
        """Get stats for a fingerprint"""
        with self._get_cursor() as cursor:
            cursor.execute(
                "SELECT * FROM fingerprint_stats WHERE fingerprint = ?",
                (fingerprint,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def update_fingerprint_stats(self, fingerprint: str, success: bool, profit_usd: float, spread_bps: float, latency_ms: float):
        """Update fingerprint statistics"""
        with self._get_cursor() as cursor:
            cursor.execute('''
                INSERT INTO fingerprint_stats 
                (fingerprint, attempts, successes, failures, total_profit_usd, avg_spread_bps, avg_latency_ms, last_attempt_ts_ms)
                VALUES (?, 1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    attempts = attempts + 1,
                    successes = successes + ?,
                    failures = failures + ?,
                    total_profit_usd = total_profit_usd + ?,
                    avg_spread_bps = (avg_spread_bps * attempts + ?) / (attempts + 1),
                    avg_latency_ms = (avg_latency_ms * attempts + ?) / (attempts + 1),
                    last_attempt_ts_ms = ?,
                    updated_at = CURRENT_TIMESTAMP
            ''', (
                fingerprint,
                1 if success else 0,
                0 if success else 1,
                profit_usd,
                spread_bps,
                latency_ms,
                int(time.time() * 1000),
                1 if success else 0,
                0 if success else 1,
                profit_usd,
                spread_bps,
                latency_ms,
                int(time.time() * 1000)
            ))
    
    def get_top_fingerprints(self, limit: int = 10) -> List[Dict]:
        """Get top fingerprints by frequency"""
        with self._get_cursor() as cursor:
            cursor.execute('''
                SELECT fingerprint, COUNT(*) as count 
                FROM events 
                WHERE fingerprint IS NOT NULL 
                GROUP BY fingerprint 
                ORDER BY count DESC 
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_trades(
        self,
        fingerprint: Optional[str] = None,
        status: Optional[str] = None,
        from_ts: Optional[int] = None,
        limit: int = 100
    ) -> List[Dict]:
        """Query trades"""
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        
        if fingerprint:
            query += " AND fingerprint = ?"
            params.append(fingerprint)
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        if from_ts:
            query += " AND created_ts_ms >= ?"
            params.append(from_ts)
        
        query += " ORDER BY created_ts_ms DESC LIMIT ?"
        params.append(limit)
        
        with self._get_cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
    
    # =========================================================================
    # MAINTENANCE
    # =========================================================================
    
    def rotate_old_data(self, retention_days: int = RETENTION_DAYS):
        """Delete data older than retention period"""
        cutoff_ts = int((datetime.now() - timedelta(days=retention_days)).timestamp() * 1000)
        
        with self._get_cursor() as cursor:
            cursor.execute("DELETE FROM events WHERE ts_ms < ?", (cutoff_ts,))
            deleted = cursor.rowcount
        
        logger.info(f"Rotated {deleted} old events")
        return deleted
    
    def vacuum(self):
        """Vacuum database to reclaim space"""
        self._conn.execute("VACUUM")
        logger.info("Database vacuumed")
    
    def get_db_size_mb(self) -> float:
        """Get database file size in MB"""
        if os.path.exists(self.db_path):
            return os.path.getsize(self.db_path) / (1024 * 1024)
        return 0
    
    def maintenance(self):
        """Run maintenance tasks"""
        # Rotate old data
        self.rotate_old_data()
        
        # Vacuum if needed
        size_mb = self.get_db_size_mb()
        if size_mb > VACUUM_THRESHOLD_MB:
            self.vacuum()
        
        logger.info(f"Maintenance complete. DB size: {size_mb:.1f} MB")
    
    def get_stats(self) -> Dict:
        """Get storage statistics"""
        return {
            **self._stats,
            'db_size_mb': self.get_db_size_mb(),
            'event_counts': self.get_event_counts()
        }
    
    def close(self):
        """Close database connection"""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

_storage: Optional[SQLiteStorage] = None


def get_storage() -> SQLiteStorage:
    """Get the global storage instance"""
    global _storage
    if _storage is None:
        _storage = SQLiteStorage()
    return _storage


def write_event(event: Event) -> bool:
    """Convenience function to write an event"""
    return get_storage().write_event(event)

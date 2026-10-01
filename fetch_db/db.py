# db.py
import sqlite3
from typing import List, Optional, Tuple
import pandas as pd
from config import DB_PATH

class Database:
    def __init__(self, db_path=DB_PATH):
        self.db_path = str(db_path)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        # 启用 WAL 模式，大幅提升多进程并发读写性能，避免 database locked
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def init_db(self):
        """初始化表结构与索引"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 1. 股票代码基础表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS stock_basic (
                    symbol TEXT PRIMARY KEY,
                    code TEXT NOT NULL,
                    name TEXT NOT NULL,
                    float_shares REAL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # 2. 日 K 线数据表（联合主键 symbol + date 保证天然去重）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_kline (
                    symbol TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL,
                    close REAL,
                    high REAL,
                    low REAL,
                    volume REAL,
                    turnover_pct REAL,
                    PRIMARY KEY (symbol, date)
                );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kline_date ON daily_kline(date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kline_symbol ON daily_kline(symbol);")
            conn.commit()

    def save_stock_basics(self, stock_list: List[dict]):
        """批量保存或更新股票基础信息"""
        if not stock_list:
            return
        records = [
            (s["symbol"], s["code"], s["name"], s.get("float_shares", 0.0))
            for s in stock_list
        ]
        with self.get_connection() as conn:
            conn.executemany("""
                INSERT INTO stock_basic (symbol, code, name, float_shares, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(symbol) DO UPDATE SET
                    name=excluded.name,
                    float_shares=excluded.float_shares,
                    updated_at=CURRENT_TIMESTAMP;
            """, records)
            conn.commit()

    def get_latest_dates(self) -> dict:
        """获取本地数据库中每只股票已存的最新日期 {symbol: 'YYYY-MM-DD'}"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT symbol, MAX(date) FROM daily_kline GROUP BY symbol;")
            rows = cursor.fetchall()
            return {row[0]: row[1] for row in rows}

    def save_klines_batch(self, df_list: List[pd.DataFrame]):
        """批量写入多个 DataFrame 的 K 线数据（原子事务，高效写入）"""
        if not df_list:
            return
        all_df = pd.concat(df_list, ignore_index=True)
        records = all_df[[
            "symbol", "date", "open", "close", "high", "low", "volume", "turnover_pct"
        ]].to_records(index=False).tolist()

        with self.get_connection() as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO daily_kline 
                (symbol, date, open, close, high, low, volume, turnover_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """, records)
            conn.commit()

    def load_kline(self, symbol: str, limit: int = 320) -> pd.DataFrame:
        """从本地数据库极速读取单只股票 K 线"""
        query = """
            SELECT date, open, close, high, low, volume, turnover_pct
            FROM daily_kline
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT ?;
        """
        with self.get_connection() as conn:
            df = pd.read_sql_query(query, conn, params=(symbol.lower(), limit))
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                return df.sort_values("date").reset_index(drop=True)
            return pd.DataFrame()

    def load_all_latest_kline(self, min_date: str) -> pd.DataFrame:
        """筛选程序专用：一次性加载全市场指定日期之后的全部数据进行向量化计算"""
        query = """
            SELECT symbol, date, open, close, high, low, volume, turnover_pct
            FROM daily_kline
            WHERE date >= ?
            ORDER BY symbol, date ASC;
        """
        with self.get_connection() as conn:
            return pd.read_sql_query(query, conn, params=(min_date,))

# 单例实例化
db = Database()
import aiosqlite
import datetime
import logging
import pandas as pd

DB_PATH = "data/trades.db"

async def init_db():
    """Ініціалізація бази даних (Гіпокамп системи)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                direction TEXT,
                entry_price REAL,
                take_profit REAL,
                stop_loss REAL,
                timestamp DATETIME,
                status TEXT
            )
        ''')
        await db.commit()

async def save_signal(symbol: str, direction: str, entry: float, tp: float, sl: float):
    """Збереження нового наміру ШІ в пам'ять."""
    now = datetime.datetime.now(datetime.timezone.utc)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO signals (symbol, direction, entry_price, take_profit, stop_loss, timestamp, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (symbol, direction, entry, tp, sl, now, "OPEN")
        )
        await db.commit()

async def resolve_open_signals(market_dataframes: dict):
    """
    Арбітр Реальності 2.0 (High/Low Trajectory Analysis).
    Перевіряє історію свічок (High/Low) замість точкових зрізів ціни.
    Використовує Песимістичне Виконання для усунення помилки виживання.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, symbol, direction, take_profit, stop_loss, timestamp FROM signals WHERE status = 'OPEN'") as cursor:
            async for row in cursor:
                sig_id, symbol, direction, tp, sl, ts_str = row
                
                if symbol not in market_dataframes:
                    continue
                    
                df = market_dataframes[symbol]
                if df is None or df.empty:
                    continue
                
                # Парсимо час сигналу. Формат SQLite зберігає +00:00 для UTC
                try:
                    sig_time = datetime.datetime.fromisoformat(ts_str)
                    if sig_time.tzinfo is None:
                        sig_time = sig_time.replace(tzinfo=datetime.timezone.utc)
                except Exception as e:
                    logging.error(f"Помилка парсингу часу для сигналу {sig_id}: {e}")
                    continue

                now = datetime.datetime.now(datetime.timezone.utc)
                status = "OPEN"
                
                # Чому: Ітеруємося по свічках, що сформувалися ПІСЛЯ видачі сигналу.
                # Свічка 15m маркується часом початку. Тому кінець свічки = індекс + 15хв.
                for idx, candle in df.iterrows():
                    candle_end_time = idx + pd.Timedelta(minutes=15)
                    
                    if candle_end_time > sig_time:
                        high = float(candle['high'])
                        low = float(candle['low'])
                        
                        hit_tp = False
                        hit_sl = False
                        
                        # Математична перевірка екстремумів
                        if direction == "ЛОНГ":
                            if low <= sl: hit_sl = True
                            if high >= tp: hit_tp = True
                        elif direction == "ШОРТ":
                            if high >= sl: hit_sl = True
                            if low <= tp: hit_tp = True
                            
                        # Чому: Pessimistic Execution. Якщо в одній свічці зачепило і SL, і TP — 
                        # ми записуємо LOSS, щоб не створювати ілюзію грааля без тікових даних.
                        if hit_sl:
                            status = "LOSS"
                            break
                        elif hit_tp and not hit_sl:
                            status = "WIN"
                            break

                # Перевірка TTL (3 години) якщо статус досі OPEN
                if status == "OPEN" and (now - sig_time).total_seconds() > 3 * 3600:
                    status = "EXPIRED"

                if status != "OPEN":
                    await db.execute("UPDATE signals SET status = ? WHERE id = ?", (status, sig_id))
                    logging.info(f"Сигнал {sig_id} по {symbol} закрито зі статусом {status} (Арбітр Реальності 2.0)")
        
        await db.commit()

async def get_recent_stats() -> tuple:
    """Повертає (total_signals, win_rate_pct) за останні 24 години."""
    yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT status FROM signals WHERE timestamp >= ? AND status IN ('WIN', 'LOSS')", 
            (yesterday,)
        ) as cursor:
            results = await cursor.fetchall()
            
    total = len(results)
    if total == 0:
        return 0, 50.0 
        
    wins = sum(1 for r in results if r[0] == "WIN")
    win_rate = (wins / total) * 100
    return total, win_rate
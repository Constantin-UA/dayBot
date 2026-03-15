import aiosqlite
import datetime
import logging

DB_PATH = "trades.db"

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

async def resolve_open_signals(current_prices: dict):
    """
    Арбітр Реальності: перевіряє відкриті сигнали за поточними цінами.
    Якщо ціна торкнулася стопа — LOSS, якщо тейк-профіту — WIN.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, symbol, direction, take_profit, stop_loss, timestamp FROM signals WHERE status = 'OPEN'") as cursor:
            async for row in cursor:
                sig_id, symbol, direction, tp, sl, ts_str = row
                
                if symbol not in current_prices:
                    continue
                    
                current_price = current_prices[symbol]
                sig_time = datetime.datetime.fromisoformat(ts_str)
                now = datetime.datetime.now(datetime.timezone.utc)
                
                status = "OPEN"
                # Математична перевірка спрацьовування рівнів
                if direction == "ЛОНГ":
                    if current_price >= tp: status = "WIN"
                    elif current_price <= sl: status = "LOSS"
                elif direction == "ШОРТ":
                    if current_price <= tp: status = "WIN"
                    elif current_price >= sl: status = "LOSS"
                
                # Перевірка TTL (3 години)
                if status == "OPEN" and (now - sig_time).total_seconds() > 3 * 3600:
                    status = "EXPIRED"

                if status != "OPEN":
                    await db.execute("UPDATE signals SET status = ? WHERE id = ?", (status, sig_id))
                    logging.info(f"Сигнал {sig_id} по {symbol} закритий зі статусом {status}")
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
        return 0, 50.0 # Нейтральний старт, якщо історії ще немає
        
    wins = sum(1 for r in results if r[0] == "WIN")
    win_rate = (wins / total) * 100
    return total, win_rate
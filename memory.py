import aiosqlite
import datetime
import logging
import pandas as pd

DB_PATH = "data/trades.db"

# Чому: Фіксація транзакційних витрат (Maker/Taker) для усунення ілюзії прибутковості мікро-рухів.
FEE_RATE = 0.0012 

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
    Арбітр Реальності 3.0 (Dynamic Trailing & Commission Tax).
    Переводить позиції в безубиток при досягненні 50% цілі.
    Відфільтровує математично збиткові "WIN" сигнали.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # Чому: Додано entry_price до вибірки, оскільки тепер він потрібен для розрахунку комісій та трейлінгу.
        async with db.execute("SELECT id, symbol, direction, entry_price, take_profit, stop_loss, timestamp FROM signals WHERE status = 'OPEN'") as cursor:
            async for row in cursor:
                sig_id, symbol, direction, entry_price, tp, sl, ts_str = row
                
                if symbol not in market_dataframes:
                    continue
                    
                df = market_dataframes[symbol]
                if df is None or df.empty:
                    continue
                
                try:
                    sig_time = datetime.datetime.fromisoformat(ts_str)
                    if sig_time.tzinfo is None:
                        sig_time = sig_time.replace(tzinfo=datetime.timezone.utc)
                except Exception as e:
                    logging.error(f"Помилка парсингу часу для {sig_id}: {e}")
                    continue

                now = datetime.datetime.now(datetime.timezone.utc)
                status = "OPEN"
                breakeven_triggered = False
                current_sl = sl

                # Чому: Розрахунок точки 50% шляху (half_target) та точки безпечного виходу (be_price) з урахуванням біржових зборів.
                if direction == "ЛОНГ":
                    half_target = entry_price + (tp - entry_price) * 0.5
                    be_price = entry_price * (1 + FEE_RATE)
                else: # ШОРТ
                    half_target = entry_price - (entry_price - tp) * 0.5
                    be_price = entry_price * (1 - FEE_RATE)

                for idx, candle in df.iterrows():
                    candle_end_time = idx + pd.Timedelta(minutes=15)
                    
                    if candle_end_time > sig_time:
                        high = float(candle['high'])
                        low = float(candle['low'])
                        
                        # Чому: Динамічний захист капіталу (Trailing Stop). Якщо ціна пройшла половину шляху, ми не маємо права отримати збиток.
                        if direction == "ЛОНГ" and not breakeven_triggered:
                            if high >= half_target:
                                current_sl = be_price
                                breakeven_triggered = True
                        elif direction == "ШОРТ" and not breakeven_triggered:
                            if low <= half_target:
                                current_sl = be_price
                                breakeven_triggered = True

                        hit_tp = False
                        hit_sl = False
                        
                        # Перевірка екстремумів відносно динамічного стопа
                        if direction == "ЛОНГ":
                            if low <= current_sl: hit_sl = True
                            if high >= tp: hit_tp = True
                        elif direction == "ШОРТ":
                            if high >= current_sl: hit_sl = True
                            if low <= tp: hit_tp = True
                            
                        # Чому: Pessimistic Execution з урахуванням нових станів.
                        if hit_sl:
                            if breakeven_triggered:
                                status = "BREAKEVEN"
                            else:
                                status = "LOSS"
                            break
                        elif hit_tp and not hit_sl:
                            # Чому: Податок на виконання. Якщо тейк-профіт візуально досягнуто, але він менший за комісію, це математичний збиток.
                            gross_profit_pct = abs(tp - entry_price) / entry_price
                            if gross_profit_pct > FEE_RATE:
                                status = "WIN"
                            else:
                                status = "LOSS" 
                            break

                if status == "OPEN" and (now - sig_time).total_seconds() > 3 * 3600:
                    status = "EXPIRED"

                if status != "OPEN":
                    await db.execute("UPDATE signals SET status = ? WHERE id = ?", (status, sig_id))
                    logging.info(f"Сигнал {sig_id} по {symbol} закрито зі статусом {status}")
        
        await db.commit()

async def get_recent_stats() -> tuple:
    """
    Повертає статистику. BREAKEVEN ігнорується при розрахунку WinRate, 
    оскільки не несе ні прибутку, ні збитку.
    """
    yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    async with aiosqlite.connect(DB_PATH) as db:
        # Чому: Додаємо BREAKEVEN до вибірки для загального підрахунку активності.
        async with db.execute(
            "SELECT status FROM signals WHERE timestamp >= ? AND status IN ('WIN', 'LOSS', 'BREAKEVEN')", 
            (yesterday,)
        ) as cursor:
            results = await cursor.fetchall()
            
    total_resolved = len(results)
    wins = sum(1 for r in results if r[0] == "WIN")
    losses = sum(1 for r in results if r[0] == "LOSS")
    
    # Чому: Win Rate рахується виключно по ризикових угодах (ті, що дали чистий плюс або чистий мінус).
    strict_total = wins + losses
    if strict_total == 0:
        return total_resolved, 50.0 
        
    win_rate = (wins / strict_total) * 100
    return total_resolved, win_rate
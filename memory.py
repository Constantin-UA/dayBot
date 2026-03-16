import aiosqlite
import datetime
import logging
import pandas as pd

DB_PATH = "data/trades.db"
FEE_RATE = 0.0012 

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        # Чому: Розширення схеми даних для підтримки кількісного фінансового аналізу (position_size, pnl).
        await db.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT,
                direction TEXT,
                entry_price REAL,
                take_profit REAL,
                stop_loss REAL,
                position_size REAL,
                pnl REAL,
                timestamp DATETIME,
                status TEXT
            )
        ''')
        await db.commit()

async def save_signal(symbol: str, direction: str, entry: float, tp: float, sl: float, pos_size: float):
    now = datetime.datetime.now(datetime.timezone.utc)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO signals (symbol, direction, entry_price, take_profit, stop_loss, position_size, timestamp, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (symbol, direction, entry, tp, sl, pos_size, now, "OPEN")
        )
        await db.commit()

async def resolve_open_signals(market_dataframes: dict):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, symbol, direction, entry_price, take_profit, stop_loss, position_size, timestamp FROM signals WHERE status = 'OPEN'") as cursor:
            async for row in cursor:
                sig_id, symbol, direction, entry_price, tp, sl, pos_size, ts_str = row
                
                if symbol not in market_dataframes: continue
                df = market_dataframes[symbol]
                if df is None or df.empty: continue
                
                try:
                    sig_time = datetime.datetime.fromisoformat(ts_str)
                    if sig_time.tzinfo is None: sig_time = sig_time.replace(tzinfo=datetime.timezone.utc)
                except: continue

                now = datetime.datetime.now(datetime.timezone.utc)
                status = "OPEN"
                breakeven_triggered = False
                current_sl = sl

                if direction == "ЛОНГ":
                    half_target = entry_price + (tp - entry_price) * 0.5
                    be_price = entry_price * (1 + FEE_RATE)
                else:
                    half_target = entry_price - (entry_price - tp) * 0.5
                    be_price = entry_price * (1 - FEE_RATE)

                for idx, candle in df.iterrows():
                    candle_end_time = idx + pd.Timedelta(minutes=15)
                    if candle_end_time > sig_time:
                        high, low = float(candle['high']), float(candle['low'])
                        
                        if direction == "ЛОНГ" and not breakeven_triggered and high >= half_target:
                            current_sl = be_price
                            breakeven_triggered = True
                        elif direction == "ШОРТ" and not breakeven_triggered and low <= half_target:
                            current_sl = be_price
                            breakeven_triggered = True

                        hit_tp, hit_sl = False, False
                        if direction == "ЛОНГ":
                            if low <= current_sl: hit_sl = True
                            if high >= tp: hit_tp = True
                        elif direction == "ШОРТ":
                            if high >= current_sl: hit_sl = True
                            if low <= tp: hit_tp = True
                            
                        if hit_sl:
                            status = "BREAKEVEN" if breakeven_triggered else "LOSS"
                            break
                        elif hit_tp and not hit_sl:
                            gross_profit_pct = abs(tp - entry_price) / entry_price
                            status = "WIN" if gross_profit_pct > FEE_RATE else "LOSS"
                            break

                if status == "OPEN" and (now - sig_time).total_seconds() > 3 * 3600:
                    status = "EXPIRED"

                if status != "OPEN":
                    # Чому: Розрахунок реального грошового потоку з урахуванням напрямку, спреду та об'єму для формування Equity Curve.
                    exit_price = entry_price 
                    if status == "WIN": exit_price = tp
                    elif status == "LOSS": exit_price = current_sl

                    if status in ["WIN", "LOSS", "BREAKEVEN"]:
                        direction_mult = 1.0 if direction == "ЛОНГ" else -1.0
                        gross_pnl = (exit_price - entry_price) * pos_size * direction_mult
                        fees = (entry_price + exit_price) * pos_size * FEE_RATE
                        net_pnl = gross_pnl - fees
                    else:
                        net_pnl = 0.0

                    await db.execute("UPDATE signals SET status = ?, pnl = ? WHERE id = ?", (status, net_pnl, sig_id))
                    logging.info(f"Сигнал {sig_id} закрито: {status} | PnL: ${net_pnl:.2f}")
        
        await db.commit()

async def get_recent_stats() -> tuple:
    yesterday = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT status FROM signals WHERE timestamp >= ? AND status IN ('WIN', 'LOSS', 'BREAKEVEN')", 
            (yesterday,)
        ) as cursor:
            results = await cursor.fetchall()
            
    total_resolved = len(results)
    wins = sum(1 for r in results if r[0] == "WIN")
    losses = sum(1 for r in results if r[0] == "LOSS")
    
    strict_total = wins + losses
    if strict_total == 0: return total_resolved, 50.0 
    return total_resolved, (wins / strict_total) * 100
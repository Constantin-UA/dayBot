import io
import datetime
import asyncio
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf
import logging
from config import exchange # Ін'єкція залежності: імпортуємо готовий сокет

async def get_market_data(symbol: str = "ETH", period: int = 14) -> tuple:
    """
    Асинхронний конектор для отримання внутрішньоденних (15m) даних.
    Оптимізовано через використання пулу постійних з'єднань.
    """
    symbol_spot = f"{symbol}/USDT"
    
    try:
        ticker = await exchange.fetch_ticker(symbol_spot)
        current_price = ticker['last']
        
        symbol_perp = f"{symbol}/USDT:USDT"
        funding_data = await exchange.fetch_funding_rate(symbol_perp)
        funding_rate = funding_data['fundingRate']

        order_book = await exchange.fetch_order_book(symbol_spot, limit=50)
        bids_volume = sum([bid[1] for bid in order_book['bids']])
        asks_volume = sum([ask[1] for ask in order_book['asks']])
        total_volume = bids_volume + asks_volume
        buy_pressure = (bids_volume / total_volume) * 100 if total_volume > 0 else 50
        sell_pressure = (asks_volume / total_volume) * 100 if total_volume > 0 else 50

        ohlcv_15m = await exchange.fetch_ohlcv(symbol_spot, timeframe='15m', limit=150)
        df_15m = pd.DataFrame(ohlcv_15m, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_15m['timestamp'] = pd.to_datetime(df_15m['timestamp'], unit='ms', utc=True)
        df_15m.set_index('timestamp', inplace=True)
        df_15m['volume'] = pd.to_numeric(df_15m['volume'])

        df_15m['date_utc'] = df_15m.index.date
        df_15m['typical_price'] = (df_15m['high'] + df_15m['low'] + df_15m['close']) / 3
        df_15m['vol_tp'] = df_15m['volume'] * df_15m['typical_price']
        
        grouped = df_15m.groupby('date_utc')
        df_15m['cum_vol'] = grouped['volume'].cumsum()
        df_15m['cum_vol_tp'] = grouped['vol_tp'].cumsum()
        df_15m['vwap'] = df_15m['cum_vol_tp'] / df_15m['cum_vol']
        
        current_vwap = float(df_15m['vwap'].iloc[-1])
        vwap_distance_pct = ((current_price - current_vwap) / current_vwap) * 100

        df_15m.ta.rsi(length=period, append=True)
        current_rsi_15m = float(df_15m[f'RSI_{period}'].iloc[-1])
        
        macd_indicator = df_15m.ta.macd(append=True)
        macd_hist_15m = float(macd_indicator.iloc[-1, 1])

        if symbol == "BTC":
            guide_name = "Локальний імпульс"
            guide_macd_hist = macd_hist_15m
        else:
            guide_name = "Биткоїн (BTC 15m)"
            ohlcv_guide = await exchange.fetch_ohlcv("BTC/USDT", timeframe='15m', limit=50)
            df_guide = pd.DataFrame(ohlcv_guide, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            macd_guide = df_guide.ta.macd(append=True)
            guide_macd_hist = float(macd_guide.iloc[-1, 1])

        current_volume = float(df_15m['volume'].iloc[-1])
        avg_volume_10_candles = float(df_15m['volume'].rolling(10).mean().iloc[-1])

        # Чому: Видалено await exchange.close(). З'єднання залишається відкритим для наступних ітерацій.
        return (current_price, current_vwap, vwap_distance_pct, current_rsi_15m, funding_rate, df_15m, 
                buy_pressure, sell_pressure, macd_hist_15m, guide_macd_hist, guide_name, 
                current_volume, avg_volume_10_candles)
                
    except Exception as e:
        # Чому: Видалено закриття сокета при помилці. Глобальний об'єкт має відновитися самостійно.
        logging.error(f"Помилка API (market.py): {e}")
        return (None,) * 13

def create_chart(df: pd.DataFrame, current_price: float, vwap: float, symbol: str = "ETH", filename: str = "chart.png") -> io.BytesIO:
    """Генерує 15-хвилинний графік з накладеною лінією VWAP."""
    df_plot = df.tail(60)
    buf = io.BytesIO()
    
    vwap_line = mpf.make_addplot(df_plot['vwap'], color='fuchsia', width=2.5, label='VWAP')
    
    mpf.plot(
        df_plot, type='candle', style='charles', 
        addplot=[vwap_line],
        hlines=dict(hlines=[current_price], colors=['b'], linestyle='--', alpha=0.5),
        title=f'\n{symbol}/USDT 15m Intraday (VWAP)', ylabel='Price', volume=True, ylabel_lower='Volume',
        savefig=dict(fname=buf, dpi=120, bbox_inches='tight', format='png')
    )
    buf.seek(0)
    return buf
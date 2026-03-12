import xml.etree.ElementTree as ET
import aiohttp
import logging
from config import ai_model

async def fetch_news(symbol: str = "ETH") -> str:
    # Добавляем теги для новых активов
    tags = {
        "BTC": "bitcoin", 
        "ETH": "ethereum", 
        "SOL": "solana",
        "BNB": "binance-coin",
        "XRP": "ripple",
        "ADA": "cardano"
    } 
    tag = tags.get(symbol, "cryptocurrency")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://cointelegraph.com/rss/tag/{tag}', timeout=5) as response:
                xml_data = await response.text()
                root = ET.fromstring(xml_data)
                news = [f"- {item.find('title').text}" for item in root.findall('./channel/item')[:5]]
                return "\n".join(news)
    except Exception as e:
        logging.error(f"Ошибка парсинга новостей: {e}")
        return "Не вдалося отримати свіжі новини."

async def fetch_fear_and_greed() -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get('https://api.alternative.me/fng/?limit=1', timeout=5) as response:
                data = await response.json()
                return f"{data['data'][0]['value']}/100 ({data['data'][0]['value_classification']})"
    except Exception as e:
        logging.error(f"Ошибка получения Fear & Greed: {e}")
        return "Невідомо"

async def get_ai_forecast(symbol, price, daily_low, daily_high, position_pct, rsi_1d, macd_hist, guide_macd_hist, guide_name, fng_index, news, funding_rate, ema50, cur_vol, avg_vol, poc_price, fibo_618, risk_usd, long_sl, long_amount, long_tp, short_sl, short_amount, short_tp):
    trend_50 = "ВИЩЕ (Глобальний бичачий тренд)" if price > ema50 else "НИЖЧЕ (Глобальний ведмежий тренд)"
    vol_status = "АНОМАЛЬНИЙ РІСТ" if cur_vol > avg_vol * 1.5 else ("ПАДАЮТЬ" if cur_vol < avg_vol * 0.8 else "В межах норми")

    prompt = f"""
    Ти — алгоритмічний ризик-менеджер та Chief AI Architect. Твоя спеціалізація — СВІНГ-ТРЕЙДИНГ (утримання 1-3 дні).
    Твоє завдання — провести детермінований аналіз ринкової ситуації та видати чіткий Торговий План.

    ДАНІ РИНКУ (АКТИВ: {symbol}/USDT):
    - Поточна ціна: {price:.2f}
    - Глобальний тренд (vs EMA 50): Ціна {trend_50}
    - Денний коридор ATR: Підтримка {daily_low:.2f} | Опір {daily_high:.2f}
    - Позиція ціни в коридорі: {position_pct:.1f}% (0% = на підтримці, 100% = на опорі, 50% = рівно посередині)
    - Об'ємний кластер POC (Point of Control 30d): {poc_price:.2f}
    - Рівень Фібоначчі 0.618: {fibo_618:.2f}
    - Локальний імпульс (MACD 4H): {'Бичачий (Вгору)' if macd_hist > 0 else 'Ведмежий (Вниз)'}
    - Макро-поводир ({guide_name}): {'Зростає (Підтримка лонгів)' if guide_macd_hist > 0 else 'Падає (Тиск вниз)'}
    
    ФІНАНСОВА МАТЕМАТИКА (Твій фіксований ризик на угоду складає: ${risk_usd:.2f}):
    - Якщо ти обираєш ЛОНГ: Безпечний Stop-Loss знаходиться на рівні {long_sl:.2f}. Об'єм позиції для суворого дотримання ризику: {long_amount:.4f} {symbol}. Ціль: {long_tp:.2f}.
    - Якщо ти обираєш ШОРТ: Безпечний Stop-Loss знаходиться на рівні {short_sl:.2f}. Об'єм позиції для суворого дотримання ризику: {short_amount:.4f} {symbol}. Ціль: {short_tp:.2f}.
    
    СУВОРИЙ АЛГОРИТМ МІРКУВАНЬ:
    1. Оціни Позицію ціни в коридорі ({position_pct:.1f}%). Якщо значення між 30% та 70%, ризик відкриття позиції максимальний — торговий план скасовується (ПОЗА РИНКОМ).
    2. Зістав межі ATR, POC та Фібоначчі для підтвердження безпеки входу.
    
    ФОРМАТ ВІДПОВІДІ:
    **🔍 [Аналіз Ліквідності та Трендів]**: (2-3 речення)
    **💡 Свінг-вердикт**: (ЛОНГ / ШОРТ / ПОЗА РИНКОМ)
    
    **🎯 Торговий План**:
    (Якщо вердикт ПОЗА РИНКОМ, напиши тут: "Немає безпечного математичного плану для входу. Очікування кращого Risk/Reward.")
    (Якщо ЛОНГ або ШОРТ, скопіюй дані з блоку Фінансова Математика у такому вигляді):
    - 🛡 Вхід: [Поточна ціна]
    - ⚖️ Об'єм позиції: [Об'єм з математики] {symbol} (Ризик суворо ${risk_usd:.2f})
    - 🛑 Stop-Loss: [SL з математики]
    - 🏁 Take-Profit: [Ціль з математики]
    """
    try:
        response = await ai_model.generate_content_async(prompt, generation_config={"temperature": 0.1})
        return response.text
    except Exception as e:
        logging.error(f"Ошибка Gemini API: {e}")
        return "Нейромережа зараз недоступна."
import xml.etree.ElementTree as ET
import aiohttp
import logging
from config import ai_model

async def fetch_news(symbol: str = "ETH") -> str:
    """
    Ізолюємо мережевий запит. Новини дають макро-контекст, 
    який може зламати будь-який інтрадей-патерн.
    """
    tags = {"ETH": "ethereum", "BTC": "bitcoin"}
    tag = tags.get(symbol, "cryptocurrency")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'https://cointelegraph.com/rss/tag/{tag}', timeout=5) as response:
                xml_data = await response.text()
                root = ET.fromstring(xml_data)
                news = [f"- {item.find('title').text}" for item in root.findall('./channel/item')[:5]]
                return "\n".join(news)
    except Exception as e:
        logging.error(f"Помилка парсингу новин: {e}")
        return "Немає свіжих новин."

async def get_ai_forecast(symbol: str, price: float, current_vwap: float, vwap_distance_pct: float, 
                          rsi_15m: float, macd_hist: float, guide_macd_hist: float, guide_name: str, 
                          news: str, funding_rate: float, cur_vol: float, avg_vol: float,
                          vwap_threshold: float, local_high: float, local_low: float) -> str:
    
    vol_status = "АНОМАЛЬНИЙ РІСТ" if cur_vol > avg_vol * 1.5 else ("ПАДАЮТЬ" if cur_vol < avg_vol * 0.8 else "В межах норми")

    prompt = f"""
    Ти — алгоритмічний HFT-аналітик та ризик-менеджер. Твоя спеціалізація — ДЕЙТРЕЙДИНГ.
    Твоя задача — провести жорсткий математичний аналіз мікроструктури та видати готовий торговий план.

    ДАНІ РИНКУ (АКТИВ: {symbol}/USDT, ТАЙМФРЕЙМ: 15m):
    - Поточна ціна: {price:.2f}
    - Інституційний якір (VWAP): {current_vwap:.2f}
    - Відхилення ціни від VWAP: {vwap_distance_pct:.2f}% 
    - Локальний максимум (за останню годину): {local_high:.2f}
    - Локальний мінімум (за останню годину): {local_low:.2f}
    - RSI (15m): {rsi_15m:.1f}
    - Локальний імпульс (MACD 15m): {'Бичачий' if macd_hist > 0 else 'Ведмежий'}
    - Об'єми торгів: {vol_status}
    - Ставка фінансування (Funding): {funding_rate * 100:.4f}%
    - Поводир ({guide_name}): {'Росте' if guide_macd_hist > 0 else 'Падає'}
    
    СВІЖІ НОВИНИ:
    {news}

    СТРОГИЙ АЛГОРИТМ МІРКУВАНЬ (Chain of Thought):
    1. [Аналіз Відхилення]: Оціни Відхилення ({vwap_distance_pct:.2f}%). Твій поріг: {vwap_threshold}%.
    2. [Аналіз Ліквідності]: Оціни Funding та RSI.
    3. [Математика Ризику (Risk/Reward)]: Це НАЙВАЖЛИВІШИЙ КРОК. 
       - Потенційний прибуток (Reward) — це завжди повернення до VWAP ({current_vwap:.2f}).
       - Потенційний збиток (Risk) — це відступ за локальний екстремум (для Лонга СТОП = {local_low:.2f}, для Шорта СТОП = {local_high:.2f}). 
       - Подумки порівняй ці дистанції. Якщо відстань до Стопа більша, ніж відстань до VWAP (Risk > Reward), ти ЗОБОВ'ЯЗАНИЙ заборонити вхід у ринок.
    
    ФОРМАТ ВІДПОВІДІ:
    **🔍 [Аналіз Мікроструктури]**: (2-3 речення)
    **⚖️ [Синтез факторів]**: (2-3 речення)
    
    **💡 Intraday-вердикт**: (ЛОНГ / ШОРТ / ПОЗА РИНКОМ)

    (Якщо вердикт ЛОНГ або ШОРТ, ОБОВ'ЯЗКОВО додай наступний блок):
    🎯 **Тейк-профіт**: {current_vwap:.2f} (Динамічний магніт VWAP)
    🛑 **Стоп-лос**: (Вкажи {local_low:.2f} для Лонга або {local_high:.2f} для Шорта)
    ⏱ **Час життя ідеї (TTL)**: Максимум 3 години. Якщо ціна не торкнулася VWAP і не вибила Стоп-лос, закрити позицію за поточними цінами (нульовий овернайт-ризик).
    """
    try:
        response = await ai_model.generate_content_async(prompt, generation_config={"temperature": 0.1})
        return response.text
    except Exception as e:
        logging.error(f"Помилка Gemini API: {e}")
        return "Нейромережа наразі недоступна."
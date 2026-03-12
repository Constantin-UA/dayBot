import xml.etree.ElementTree as ET
import aiohttp
import logging
from config import ai_model

async def fetch_news(symbol: str = "ETH") -> str:
    """
    Изолируем сетевой запрос. Новости дают макро-контекст, 
    который может сломать любой интрадей-паттерн.
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
        logging.error(f"Ошибка парсинга новостей: {e}")
        return "Нет свежих новостей."

async def get_ai_forecast(symbol: str, price: float, current_vwap: float, vwap_distance_pct: float, 
                          rsi_15m: float, macd_hist: float, guide_macd_hist: float, guide_name: str, 
                          news: str, funding_rate: float, cur_vol: float, avg_vol: float) -> str:
    """
    Формирует промпт для интрадей-анализа.
    Почему VWAP: это институциональный якорь. ШИ должен понимать, насколько цена отклонилась от справедливой.
    """
    vol_status = "АНОМАЛЬНЫЙ РОСТ" if cur_vol > avg_vol * 1.5 else ("ПАДАЮТ" if cur_vol < avg_vol * 0.8 else "В пределах нормы")

    prompt = f"""
    Ты — алгоритмический HFT-аналитик и Intraday-трейдер. Твоя специализация — ДЕЙТРЕЙДИНГ (сделки от 15 минут до 3 часов).
    Твоя задача — провести детерминированный анализ рыночной микроструктуры и выдать четкий вердикт.

    ДАННЫЕ РЫНКА (АКТИВ: {symbol}/USDT, ТАЙМФРЕЙМ: 15m):
    - Текущая цена: {price:.2f}
    - Институциональный якорь (VWAP): {current_vwap:.2f}
    - Отклонение цены от VWAP: {vwap_distance_pct:.2f}% (Положительное = перегрев вверх, Отрицательное = падение ниже средневзвешенной цены)
    - RSI (15m): {rsi_15m:.1f}
    - Локальный импульс (MACD 15m): {'Бычий (Вверх)' if macd_hist > 0 else 'Медвежий (Вниз)'}
    - Объемы торгов (относительно 10 свечей): {vol_status}
    - Ставка финансирования (Funding): {funding_rate * 100:.4f}%
    - Поводырь ({guide_name}): {'Растет' if guide_macd_hist > 0 else 'Падает'}
    
    СВЕЖИЕ НОВОСТИ:
    {news}
    
    СТРОГИЙ АЛГОРИТМ РАССУЖДЕНИЙ (Chain of Thought):
    1. [Анализ Отклонения]: Оцени Отклонение от VWAP ({vwap_distance_pct:.2f}%). Если оно около 0%, цена в равновесии (опасность флэта). Если > 1.5% или < -1.5%, вероятен институциональный возврат к средней (Mean Reversion).
    2. [Аналіз Ліквідності]: Оцени Funding и RSI 15m. Есть ли локальный перегрев толпы на 15-минутном таймфрейме?
    3. [Синтез]: Сопоставь Отклонение VWAP, Поводыря и Объемы для поиска безопасной точки входа.
    
    ФОРМАТ ОТВЕТА:
    **🔍 [Анализ Микроструктуры]**: (2-3 предложения)
    **⚖️ [Синтез факторов]**: (2-3 предложения)
    **💡 Intraday-вердикт (15m - 3h)**: (ЛОНГ / ШОРТ / ВНЕ РЫНКА (Ждать отката к VWAP)).
    """
    try:
        # Низкая температура для устранения креативных галлюцинаций в строгой математике
        response = await ai_model.generate_content_async(prompt, generation_config={"temperature": 0.1})
        return response.text
    except Exception as e:
        logging.error(f"Ошибка Gemini API: {e}")
        return "Нейросеть сейчас недоступна."
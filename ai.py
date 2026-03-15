import xml.etree.ElementTree as ET
import aiohttp
import logging
import datetime
import json
from config import ai_model
from schemas import TradingVerdict

async def fetch_news(symbol: str = "ETH") -> str:
    # Чому: Ізолюємо макро-контекст від мікроструктури для зменшення шуму в прийнятті рішень.
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
                          vwap_threshold: float, local_high: float, local_low: float,
                          total_signals: int, win_rate: float) -> TradingVerdict | None:
    
    current_time_utc = datetime.datetime.now(datetime.timezone.utc).strftime('%H:%M')
    vol_status = "АНОМАЛЬНИЙ РІСТ" if cur_vol > avg_vol * 1.5 else ("ПАДАЮТЬ" if cur_vol < avg_vol * 0.8 else "В межах норми")

    # Чому: Балансуючий зворотний зв'язок для контролю просадки капіталу (Drawdown).
    if total_signals >= 3 and win_rate < 40.0:
        reflection_block = f"КРИТИЧНА УВАГА: Твій Win Rate за 24 години впав до {win_rate:.1f}%. Ринок у стадії жорсткого 'запилу' (зняття ліквідності). ТИ ЗОБОВ'ЯЗАНИЙ ПОДВОЇТИ ЖОРСТКІСТЬ ФІЛЬТРІВ. Якщо Risk/Reward не ідеальний — видавай вердикт ПОЗА РИНКОМ."
    elif total_signals >= 3 and win_rate >= 60.0:
        reflection_block = f"ВІДМІННО: Твій Win Rate {win_rate:.1f}%. Ти знаходишся в ідеальній синергії з ринком. Продовжуй шукати інтрадей-аномалії за поточними критеріями."
    else:
        reflection_block = f"Статистика: {total_signals} угод, Win Rate {win_rate:.1f}%. Зберігай стандартний нейтральний підхід до ризик-менеджменту."

    prompt = f"""
    Ти — алгоритмічний HFT-аналітик та ризик-менеджер. Твоя спеціалізація — ДЕЙТРЕЙДИНГ.
    Твоя задача — провести жорсткий математичний аналіз мікроструктури та видати готовий торговий план у форматі JSON.

    [САМОРЕФЛЕКСІЯ ТА MLOps]:
    {reflection_block}

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
    
    ЧАСОВИЙ КОНТЕКСТ (СИНХРОНІЗАЦІЯ СЕСІЙ):
    - ПОТОЧНИЙ ЧАС (UTC): {current_time_utc}
    - КАРТА ЛІКВІДНОСТІ (UTC):
      * 00:00 - 08:00 (Азія): Низька волатильність, формування меж, хибні пробої.
      * 08:00 - 13:30 (Лондон): Пробудження об'ємів, маніпуляції (зняття стопів), старт трендів.
      * 13:30 - 21:00 (Нью-Йорк): Висока ліквідність, справжні рухи.
    
    СВІЖІ НОВИНИ:
    {news}

    СТРОГИЙ АЛГОРИТМ МІРКУВАНЬ:
    1. Оціни ПОТОЧНИЙ ЧАС (UTC).
    2. Оціни Відхилення ({vwap_distance_pct:.2f}%). Поріг: {vwap_threshold}%.
    3. Оціни Ліквідність (Funding, RSI).
    4. Математика Ризику: 
       - Reward = повернення до VWAP ({current_vwap:.2f}).
       - Risk = відступ за екстремум (Лонг СТОП = {local_low:.2f}, Шорт СТОП = {local_high:.2f}). 
       - Якщо Risk > Reward, ти ЗОБОВ'ЯЗАНИЙ заборонити вхід у ринок (ПОЗА РИНКОМ).
    """
    try:
        # Чому: Перенесення відповідальності за структуру даних на API гарантує системну стабільність виводу.
        response = await ai_model.generate_content_async(
            prompt, 
            generation_config={
                "temperature": 0.0,
                "response_mime_type": "application/json",
                "response_schema": TradingVerdict
            }
        )
        verdict_data = json.loads(response.text)
        return TradingVerdict(**verdict_data)
    except Exception as e:
        # Чому: Перехоплення помилок валідації Pydantic або мережевих збоїв, захист від крашу основного циклу.
        logging.error(f"Помилка генерації або валідації JSON ШІ: {e}")
        return None
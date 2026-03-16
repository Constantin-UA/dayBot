import os
import logging
from dotenv import load_dotenv
from google import genai
import ccxt.async_support as ccxt

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

VWAP_ALERT_THRESHOLD = float(os.getenv("VWAP_ALERT_THRESHOLD", 1.0))
WATCHLIST_RAW = os.getenv("WATCHLIST", "ETH,BTC")
WATCHLIST = [coin.strip() for coin in WATCHLIST_RAW.split(",")]

# Чому: Фіксація максимально допустимих втрат на одну ітерацію для стабілізації кривої капіталу (Equity Curve).
FIXED_RISK_USD = float(os.getenv("FIXED_RISK_USD", 10.0))

if not all([BOT_TOKEN, ADMIN_ID, LOG_CHANNEL_ID, GEMINI_API_KEY]):
    raise ValueError("Відсутні токени в .env!")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

client = genai.Client(api_key=GEMINI_API_KEY)

# Чому: Патерн Singleton для управління I/O. 
# Створюємо єдиний постійний екземпляр з'єднання з біржею для всього життєвого циклу додатку.
exchange = ccxt.bybit({'enableRateLimit': True})
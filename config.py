import os
import logging
from dotenv import load_dotenv
from google import genai

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

VWAP_ALERT_THRESHOLD = float(os.getenv("VWAP_ALERT_THRESHOLD", 1.0))
WATCHLIST_RAW = os.getenv("WATCHLIST", "ETH,BTC")
WATCHLIST = [coin.strip() for coin in WATCHLIST_RAW.split(",")]

if not all([BOT_TOKEN, ADMIN_ID, LOG_CHANNEL_ID, GEMINI_API_KEY]):
    raise ValueError("Відсутні токени в .env!")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Чому: Перехід на сучасний синхронно-асинхронний клієнт згідно зі специфікаціями Google 2026 року.
client = genai.Client(api_key=GEMINI_API_KEY)
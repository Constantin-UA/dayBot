import os
import logging
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

VWAP_ALERT_THRESHOLD = float(os.getenv("VWAP_ALERT_THRESHOLD", 1.0))

# --- НОВЫЙ БЛОК: Изоляция списка активов ---
# Почему: принцип Open/Closed. Читаем строку из .env и превращаем в List[str]
WATCHLIST_RAW = os.getenv("WATCHLIST", "ETH,BTC")
WATCHLIST = [coin.strip() for coin in WATCHLIST_RAW.split(",")]
# -------------------------------------------

if not all([BOT_TOKEN, ADMIN_ID, LOG_CHANNEL_ID, GEMINI_API_KEY]):
    raise ValueError("Відсутні токени в .env!")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

genai.configure(api_key=GEMINI_API_KEY)
ai_model = genai.GenerativeModel('gemini-2.5-flash')
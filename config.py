import os
import logging
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# --- НАЛАШТУВАННЯ РИЗИК-МЕНЕДЖМЕНТУ ---
TRADE_DEPOSIT = float(os.getenv("TRADE_DEPOSIT", 1000)) # Ваш депозит у доларах
TRADE_RISK_PCT = float(os.getenv("TRADE_RISK_PCT", 10))  # Ризик на угоду у відсотках (1%)
# ---------------------------------------

if not all([BOT_TOKEN, ADMIN_ID, LOG_CHANNEL_ID, GEMINI_API_KEY]):
    raise ValueError("Відсутні токени в .env!")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

genai.configure(api_key=GEMINI_API_KEY)
ai_model = genai.GenerativeModel('gemini-2.5-flash')
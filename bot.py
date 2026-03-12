import asyncio
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_ID, LOG_CHANNEL_ID, logging, TRADE_DEPOSIT, TRADE_RISK_PCT
from market import get_market_data, create_chart
from ai import fetch_news, fetch_fear_and_greed, get_ai_forecast

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()
alert_state = {} 

class LogState(StatesGroup):
    waiting_for_note = State()

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📈 Analize"), KeyboardButton(text="🧠 AI Прогноз")],
        [KeyboardButton(text="📝 Log")]
    ], resize_keyboard=True
)

def get_asset_keyboard(action_prefix):
    # Разбиваем кнопки на два элегантных ряда для удобства в Telegram
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="BTC", callback_data=f"{action_prefix}_BTC"),
            InlineKeyboardButton(text="ETH", callback_data=f"{action_prefix}_ETH"),
            InlineKeyboardButton(text="SOL", callback_data=f"{action_prefix}_SOL")
        ],
        [
            InlineKeyboardButton(text="BNB", callback_data=f"{action_prefix}_BNB"),
            InlineKeyboardButton(text="XRP", callback_data=f"{action_prefix}_XRP"),
            InlineKeyboardButton(text="ADA", callback_data=f"{action_prefix}_ADA")
        ]
    ])

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer("👋 Привіт! Оберіть дію в меню.", reply_markup=main_keyboard)

@dp.message(F.text == "📈 Analize")
async def ask_analyze(message: types.Message):
    await message.answer("Оберіть актив для технічного аналізу:", reply_markup=get_asset_keyboard("market"))

@dp.message(F.text == "🧠 AI Прогноз")
async def ask_ai(message: types.Message):
    await message.answer("Оберіть актив для ШІ-прогнозу:", reply_markup=get_asset_keyboard("ai"))

@dp.message(F.text == "📝 Log")
async def ask_log(message: types.Message):
    await message.answer("Для якого активу пишемо лог?", reply_markup=get_asset_keyboard("log"))

@dp.callback_query(F.data.startswith("market_"))
async def market_handler(call: CallbackQuery):
    await call.answer()
    symbol = call.data.split("_")[1]
    await call.message.edit_text(f"⏳ Збираю дані по {symbol}...")
    
    data = await get_market_data(symbol)
    if data[0] is None:
        return await call.message.edit_text("❌ Помилка отримання даних.")

    price, atr_1d, rsi_1d, funding, df_1d, buy_pct, sell_pct, macd_hist, guide_macd_hist, guide_name, ema50, cur_vol, avg_vol, poc_price, fibo_618 = data
    
    daily_open = df_1d['open'].iloc[-1]
    daily_high = daily_open + atr_1d
    daily_low = daily_open - atr_1d

    chart_buffer = create_chart(df_1d, price, daily_high, daily_low, symbol)
    photo = BufferedInputFile(chart_buffer.getvalue(), filename="chart.png")

    trend_status = "🟢 Вище EMA50" if price > ema50 else "🔴 Нижче EMA50"
    
    text = (
        f"📊 **Торговий радар {symbol}/USDT**\n\n"
        f"💰 **Ціна:** `${price:,.2f}` ({trend_status})\n"
        f"🎯 **Коридор дня:** `🔽 {daily_low:,.0f} --- 🔼 {daily_high:,.0f}`\n\n"
        f"🧲 **POC (Об'єм 30d):** `{poc_price:,.0f}`\n"
        f"📐 **Fibo 0.618:** `{fibo_618:,.0f}`\n"
        f"📈 **RSI (1D):** `{rsi_1d:.1f}`\n"
        f"⛽️ **Funding:** `{funding * 100:.4f}%`\n"
        f"🧭 **Тренд 4H:** {symbol} `{'Вгору' if macd_hist > 0 else 'Вниз'}` | {guide_name} `{'Вгору' if guide_macd_hist > 0 else 'Вниз'}`"
    )
    await call.message.delete()
    await call.message.answer_photo(photo=photo, caption=text, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("ai_"))
async def ai_forecast_handler(call: CallbackQuery):
    await call.answer()
    symbol = call.data.split("_")[1]
    await call.message.edit_text(f"🧠 Запускаю ШІ для {symbol}...")
    
    data = await get_market_data(symbol)
    news = await fetch_news(symbol)
    fng_index = await fetch_fear_and_greed()
    
    if data[0] is None:
        return await call.message.edit_text("❌ Помилка даних.")

    price, atr_1d, rsi_1d, funding, df_1d, _, _, macd_hist, guide_macd_hist, guide_name, ema50, cur_vol, avg_vol, poc_price, fibo_618 = data
    
    daily_open = df_1d['open'].iloc[-1]
    daily_high = daily_open + atr_1d
    daily_low = daily_open - atr_1d
    
    channel_range = daily_high - daily_low
    position_pct = ((price - daily_low) / channel_range * 100) if channel_range > 0 else 50
    
    # --- МАТЕМАТИКА РИЗИК-МЕНЕДЖМЕНТУ (Position Sizing) ---
    risk_usd = TRADE_DEPOSIT * (TRADE_RISK_PCT / 100)
    
    # Сценарій для ЛОНГу (Stop-Loss на 0.2% нижче підтримки ATR)
    long_sl = daily_low * 0.998
    long_risk_per_coin = price - long_sl
    long_amount = risk_usd / long_risk_per_coin if long_risk_per_coin > 0 else 0
    long_tp = daily_high # Ціль - верхня межа коридору
    
    # Сценарій для ШОРТу (Stop-Loss на 0.2% вище опору ATR)
    short_sl = daily_high * 1.002
    short_risk_per_coin = short_sl - price
    short_amount = risk_usd / short_risk_per_coin if short_risk_per_coin > 0 else 0
    short_tp = daily_low # Ціль - нижня межа коридору
    # --------------------------------------------------------
    
    ai_text = await get_ai_forecast(
        symbol=symbol, price=price, daily_low=daily_low, daily_high=daily_high, position_pct=position_pct,
        rsi_1d=rsi_1d, macd_hist=macd_hist, guide_macd_hist=guide_macd_hist, 
        guide_name=guide_name, fng_index=fng_index, news=news, 
        funding_rate=funding, ema50=ema50, cur_vol=cur_vol, avg_vol=avg_vol,
        poc_price=poc_price, fibo_618=fibo_618,
        risk_usd=risk_usd, long_sl=long_sl, long_amount=long_amount, long_tp=long_tp,
        short_sl=short_sl, short_amount=short_amount, short_tp=short_tp
    )
    
    await call.message.delete()
    await call.message.answer(f"🤖 **Аналіз AI ({symbol}):**\n\n{ai_text}", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("log_"))
async def start_log_process(call: CallbackQuery, state: FSMContext):
    await call.answer()
    symbol = call.data.split("_")[1]
    await state.update_data(symbol=symbol) 
    await state.set_state(LogState.waiting_for_note)
    await call.message.delete()
    await call.message.answer(f"✍️ Опишіть думку по **{symbol}**:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Скасувати")]], resize_keyboard=True))

@dp.message(F.text == "❌ Скасувати", LogState.waiting_for_note)
async def cancel_log(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Скасовано.", reply_markup=main_keyboard)

@dp.message(LogState.waiting_for_note)
async def save_log(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    symbol = user_data.get("symbol", "ETH")
    user_note = message.text
    
    wait_msg = await message.answer(f"⏳ Зберігаю лог по {symbol}...")
    await state.clear()
    
    data = await get_market_data(symbol)
    price, atr_1d, rsi_1d, _, df_1d, _, _, _, _, _, _, _, _, _, _ = data
    
    daily_open = df_1d['open'].iloc[-1]
    daily_high = daily_open + atr_1d
    daily_low = daily_open - atr_1d
    
    chart_buffer = create_chart(df_1d, price, daily_high, daily_low, symbol, "log_chart.png")
    photo = BufferedInputFile(chart_buffer.getvalue(), filename="log_chart.png")

    log_text = (
        f"📖 **ЩОДЕННИК УГОДИ ({symbol})** | `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}`\n\n"
        f"📝 **Запис:**\n_{user_note}_\n\n"
        f"💰 Ціна: `${price:,.2f}` | RSI: `{rsi_1d:.1f}`"
    )

    await bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=photo, caption=log_text, parse_mode="Markdown")
    await message.answer("✅ У щоденнику!", reply_markup=main_keyboard)
    await wait_msg.delete()

async def check_alerts():
    # Расширяем список сканирования до 6 фундаментальных активов
    for symbol in ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA"]: 
        data = await get_market_data(symbol)
        if data[0] is None: continue
        
        # ... остальная логика радара остается без изменений ...
        price, atr_1d, rsi_1d, df_1d = data[0], data[1], data[2], data[4]
        
        daily_open = df_1d['open'].iloc[-1]
        daily_high = daily_open + atr_1d
        daily_low = daily_open - atr_1d
        
        alert_message, current_alert_type = None, None

        if price >= daily_high: current_alert_type, alert_message = "RESISTANCE", f"🚨 ПРОБІЙ ВГОРУ ({symbol}): {price:.2f}"
        elif price <= daily_low: current_alert_type, alert_message = "SUPPORT", f"🚨 ПРОБІЙ ВНИЗ ({symbol}): {price:.2f}"
        elif rsi_1d >= 75: current_alert_type, alert_message = "RSI_HIGH", f"⚠️ ПЕРЕКУПЛЕНІСТЬ ({symbol}): {rsi_1d:.1f}"
        elif rsi_1d <= 25: current_alert_type, alert_message = "RSI_LOW", f"⚠️ ПЕРЕПРОДАНІСТЬ ({symbol}): {rsi_1d:.1f}"
        else: alert_state[f"last_{symbol}"] = None

        if alert_message and current_alert_type != alert_state.get(f"last_{symbol}"):
            await bot.send_message(chat_id=ADMIN_ID, text=alert_message)
            alert_state[f"last_{symbol}"] = current_alert_type
            
async def main():
    scheduler.add_job(check_alerts, 'interval', minutes=15)
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
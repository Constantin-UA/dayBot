import asyncio
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_ID, LOG_CHANNEL_ID, logging, VWAP_ALERT_THRESHOLD
from market import get_market_data, create_chart
from ai import fetch_news, get_ai_forecast

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()
alert_state = {} 

class LogState(StatesGroup):
    waiting_for_note = State()

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⚡ Intraday Radar"), KeyboardButton(text="🧠 AI Скальп")],
        [KeyboardButton(text="📝 Log")]
    ], resize_keyboard=True
)

def get_asset_keyboard(action_prefix: str) -> InlineKeyboardMarkup:
    """DRY: Універсальна генерація клавіатур для активів."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="ETH", callback_data=f"{action_prefix}_ETH"),
            InlineKeyboardButton(text="BTC", callback_data=f"{action_prefix}_BTC")
        ]
    ])

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer("🏎 Привіт! Це VWAP Intraday-радар. Оберіть дію.", reply_markup=main_keyboard)

@dp.message(F.text == "⚡ Intraday Radar")
async def ask_analyze(message: types.Message):
    await message.answer("Оберіть актив для сканування мікроструктури:", reply_markup=get_asset_keyboard("market"))

@dp.message(F.text == "🧠 AI Скальп")
async def ask_ai(message: types.Message):
    await message.answer("Оберіть актив для Intraday ШІ-прогнозу:", reply_markup=get_asset_keyboard("ai"))

@dp.message(F.text == "📝 Log")
async def ask_log(message: types.Message):
    await message.answer("Для якого активу пишемо лог?", reply_markup=get_asset_keyboard("log"))

@dp.callback_query(F.data.startswith("market_"))
async def market_handler(call: CallbackQuery):
    await call.answer()
    symbol = call.data.split("_")[1]
    await call.message.edit_text(f"⏳ Сканую VWAP по {symbol}...")
    
    data = await get_market_data(symbol)
    if data[0] is None:
        return await call.message.edit_text("❌ Помилка отримання даних.")

    price, vwap, vwap_dist_pct, rsi_15m, funding, df_15m, buy_pct, sell_pct, macd_15m, guide_macd, guide_name, cur_vol, avg_vol = data

    chart_buffer = create_chart(df_15m, price, vwap, symbol)
    photo = BufferedInputFile(chart_buffer.getvalue(), filename="chart.png")

    vwap_status = "🔴 ПЕРЕГРІВ ВГОРУ" if vwap_dist_pct > VWAP_ALERT_THRESHOLD else ("🟢 ПЕРЕПРОДАНІСТЬ" if vwap_dist_pct < -VWAP_ALERT_THRESHOLD else "⚪ В зоні балансу")
    
    text = (
        f"⚡ **VWAP Радар {symbol}/USDT (15m)**\n\n"
        f"💰 **Ціна:** `${price:,.2f}`\n"
        f"🧲 **VWAP:** `${vwap:,.2f}`\n"
        f"📏 **Відхилення:** `{vwap_dist_pct:+.2f}%` ({vwap_status})\n\n"
        f"📈 **RSI (15m):** `{rsi_15m:.1f}`\n"
        f"🧱 **Стакан:** `{buy_pct:.0f}% / {sell_pct:.0f}%`\n"
        f"🧭 **Імпульс 15m:** {symbol} `{'Вгору' if macd_15m > 0 else 'Вниз'}` | {guide_name} `{'Вгору' if guide_macd > 0 else 'Вниз'}`"
    )
    await call.message.delete()
    await call.message.answer_photo(photo=photo, caption=text, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("ai_"))
async def ai_forecast_handler(call: CallbackQuery):
    await call.answer()
    symbol = call.data.split("_")[1]
    await call.message.edit_text(f"🧠 Запускаю HFT-аналіз для {symbol}...")
    
    data = await get_market_data(symbol)
    news = await fetch_news(symbol)
    
    if data[0] is None:
        return await call.message.edit_text("❌ Помилка даних.")

    price, vwap, vwap_dist_pct, rsi_15m, funding, df_15m, _, _, macd_15m, guide_macd, guide_name, cur_vol, avg_vol = data
    
    # --- БЛОК ІЗОЛЯЦІЇ РИЗИКУ: Розрахунок локальних екстремумів (остання 1 година = 4 свічки по 15m) ---
    local_high = float(df_15m['high'].tail(4).max())
    local_low = float(df_15m['low'].tail(4).min())
    # ----------------------------------------------------------------------------------------------------
    
    ai_text = await get_ai_forecast(
            symbol=symbol, price=price, current_vwap=vwap, vwap_distance_pct=vwap_dist_pct,
            rsi_15m=rsi_15m, macd_hist=macd_15m, guide_macd_hist=guide_macd, 
            guide_name=guide_name, news=news, funding_rate=funding, cur_vol=cur_vol, avg_vol=avg_vol,
            vwap_threshold=VWAP_ALERT_THRESHOLD,
            local_high=local_high, local_low=local_low
        )
    
    await call.message.delete()
    await call.message.answer(f"🤖 **Intraday AI ({symbol}):**\n\n{ai_text}", parse_mode="Markdown")

@dp.callback_query(F.data.startswith("log_"))
async def start_log_process(call: CallbackQuery, state: FSMContext):
    await call.answer()
    symbol = call.data.split("_")[1]
    await state.update_data(symbol=symbol) 
    await state.set_state(LogState.waiting_for_note)
    await call.message.delete()
    await call.message.answer(f"✍️ Опишіть інтрадей-угоду по **{symbol}**:", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="❌ Скасувати")]], resize_keyboard=True))

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
    price, vwap, vwap_dist_pct, rsi_15m, _, df_15m, _, _, _, _, _, _, _ = data
    
    chart_buffer = create_chart(df_15m, price, vwap, symbol, "log_chart.png")
    photo = BufferedInputFile(chart_buffer.getvalue(), filename="log_chart.png")

    log_text = (
        f"📖 **INTRADAY ЖУРНАЛ ({symbol})** | `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}`\n\n"
        f"📝 **Запис:**\n_{user_note}_\n\n"
        f"💰 Ціна: `${price:,.2f}` | VWAP Відхилення: `{vwap_dist_pct:+.2f}%` | RSI 15m: `{rsi_15m:.1f}`"
    )

    await bot.send_photo(chat_id=LOG_CHANNEL_ID, photo=photo, caption=log_text, parse_mode="Markdown")
    await message.answer("✅ Збережено в журнал!", reply_markup=main_keyboard)
    await wait_msg.delete()

async def check_alerts():
    """Системний фоновий чекер відхилень VWAP."""
    for symbol in ["ETH", "BTC"]:
        data = await get_market_data(symbol)
        if data[0] is None: continue
        
        price, vwap, vwap_dist_pct, rsi_15m = data[0], data[1], data[2], data[3]
        alert_message, current_alert_type = None, None

        if vwap_dist_pct >= VWAP_ALERT_THRESHOLD: 
            current_alert_type, alert_message = "VWAP_OVERBOUGHT", f"🚨 ПЕРЕГРІВ ({symbol}): Ціна відірвалася на {vwap_dist_pct:.2f}% вище VWAP. Готуємо ШОРТ."
        elif vwap_dist_pct <= -VWAP_ALERT_THRESHOLD: 
            current_alert_type, alert_message = "VWAP_OVERSOLD", f"🚨 ОБВАЛ ({symbol}): Ціна впала на {vwap_dist_pct:.2f}% нижче VWAP. Шукаємо ЛОНГ."
        elif rsi_15m >= 80: 
            current_alert_type, alert_message = "RSI_HIGH_15M", f"⚠️ RSI ЕКСТРЕМУМ ({symbol}): {rsi_15m:.1f} на 15m таймфреймі."
        elif rsi_15m <= 20: 
            current_alert_type, alert_message = "RSI_LOW_15M", f"⚠️ RSI ДНО ({symbol}): {rsi_15m:.1f} на 15m таймфреймі."
        else: 
            alert_state[f"last_{symbol}"] = None

        if alert_message and current_alert_type != alert_state.get(f"last_{symbol}"):
            await bot.send_message(chat_id=ADMIN_ID, text=alert_message)
            alert_state[f"last_{symbol}"] = current_alert_type

async def main():
    scheduler.add_job(check_alerts, 'interval', minutes=5)
    scheduler.start()
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
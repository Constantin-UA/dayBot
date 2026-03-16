import asyncio
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import BOT_TOKEN, ADMIN_ID, LOG_CHANNEL_ID, logging, ATR_MULTIPLIER, WATCHLIST, FIXED_RISK_USD
from market import get_market_data, create_chart
from ai import fetch_news, get_ai_forecast
from memory import init_db, save_signal, resolve_open_signals, get_recent_stats, get_full_statistics

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
alert_state = {} 
global_dataframes = {}

main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="⚡ Intraday Radar"), KeyboardButton(text="🧠 AI Скальп")],
        [KeyboardButton(text="📊 Статистика")]
    ], resize_keyboard=True
)

def get_asset_keyboard(action_prefix: str) -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(text=coin, callback_data=f"{action_prefix}_{coin}") for coin in WATCHLIST]
    keyboard = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer("🏎 Привіт! Це VWAP Intraday-радар.", reply_markup=main_keyboard)

@dp.message(F.text == "⚡ Intraday Radar")
async def ask_analyze(message: types.Message):
    await message.answer("Оберіть актив для сканування:", reply_markup=get_asset_keyboard("market"))

@dp.message(F.text == "🧠 AI Скальп")
async def ask_ai(message: types.Message):
    await message.answer("Оберіть актив для ШІ-прогнозу:", reply_markup=get_asset_keyboard("ai"))

@dp.message(F.text == "📊 Статистика")
async def show_statistics(message: types.Message):
    stats = await get_full_statistics()
    if stats["total"] == 0:
        return await message.answer("📭 База даних порожня.")
    pnl_sign = "+" if stats['net_pnl'] > 0 else ""
    text = (
        f"📊 **Кількісний Фінансовий Звіт**\n\n"
        f"💼 **Чистий PnL:** `{pnl_sign}${stats['net_pnl']:.2f}`\n"
        f"🎯 **Win Rate:** `{stats['win_rate']:.1f}%`\n\n"
        f"📈 Всього угод: `{stats['total']}`\n"
        f"✅ WIN: `{stats['wins']}` | ❌ LOSS: `{stats['losses']}` | 🛡 BE: `{stats['breakevens']}`"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("market_"))
async def market_handler(call: CallbackQuery):
    await call.answer()
    symbol = call.data.split("_")[1]
    await call.message.edit_text(f"⏳ Сканую VWAP по {symbol}...")
    
    data = await get_market_data(symbol, use_ws=False)
    if data[0] is None:
        return await call.message.edit_text("❌ Помилка даних.")

    price, vwap, vwap_dist_pct, rsi_15m, funding, df_15m, buy_pct, sell_pct, macd_15m, guide_macd, guide_name, cur_vol, avg_vol, atr_pct = data
    dynamic_threshold = atr_pct * ATR_MULTIPLIER

    chart_buffer = create_chart(df_15m, price, vwap, symbol)
    photo = BufferedInputFile(chart_buffer.getvalue(), filename="chart.png")

    vwap_status = "🔴 ПЕРЕГРІВ" if vwap_dist_pct > dynamic_threshold else ("🟢 ПЕРЕПРОДАНІСТЬ" if vwap_dist_pct < -dynamic_threshold else "⚪ Баланс")
    vol_tag = "⚠️ АНОМАЛІЯ ОБ'ЄМУ" if cur_vol > (avg_vol * 2.0) else "Норма"

    text = (
        f"⚡ **VWAP Радар {symbol} (15m)**\n\n"
        f"💰 **Ціна:** `${price:,.4f}`\n"
        f"📏 **Відхилення:** `{vwap_dist_pct:+.2f}%` ({vwap_status})\n"
        f"🎯 **Поріг ATR:** `±{dynamic_threshold:.2f}%`\n"
        f"📊 **Об'єм:** {vol_tag}\n\n"
        f"📈 **RSI:** `{rsi_15m:.1f}` | 🧱 **Стакан:** `{buy_pct:.0f}% / {sell_pct:.0f}%`\n"
    )
    await call.message.delete()
    await call.message.answer_photo(photo=photo, caption=text, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("ai_"))
async def ai_forecast_handler(call: CallbackQuery):
    await call.answer()
    symbol = call.data.split("_")[1]
    await call.message.edit_text(f"🧠 Запускаю HFT-аналіз для {symbol}...")
    
    data = await get_market_data(symbol, use_ws=False)
    news = await fetch_news(symbol)
    if data[0] is None: return await call.message.edit_text("❌ Помилка даних.")

    price, vwap, vwap_dist_pct, rsi_15m, funding, df_15m, _, _, macd_15m, guide_macd, guide_name, cur_vol, avg_vol, atr_pct = data
    local_high = float(df_15m['high'].tail(4).max())
    local_low = float(df_15m['low'].tail(4).min())
    dynamic_threshold = atr_pct * ATR_MULTIPLIER
    total_sig, win_rate = await get_recent_stats()
    
    verdict_obj = await get_ai_forecast(
        symbol=symbol, price=price, current_vwap=vwap, vwap_distance_pct=vwap_dist_pct,
        rsi_15m=rsi_15m, macd_hist=macd_15m, guide_macd_hist=guide_macd, guide_name=guide_name, 
        news=news, funding_rate=funding, cur_vol=cur_vol, avg_vol=avg_vol,
        vwap_threshold=dynamic_threshold, local_high=local_high, local_low=local_low,
        total_signals=total_sig, win_rate=win_rate
    )
    
    if verdict_obj is None: return await call.message.edit_text("❌ Збій валідації ШІ.")

    ui_text = (
        f"🤖 **Intraday AI ({symbol}):**\n\n"
        f"**🔍 Мікроструктура:**\n{verdict_obj.analysis}\n\n"
        f"**⚖️ Синтез:**\n{verdict_obj.synthesis}\n\n"
        f"**💡 Вердикт:** {verdict_obj.direction}\n"
    )

    if verdict_obj.direction in ["ЛОНГ", "ШОРТ"] and verdict_obj.take_profit and verdict_obj.stop_loss:
        # Чому: Інтеграція впливу комісії (Fee Impact) у визначення справжнього ризику на монету
        FEE_RATE = 0.0012
        price_delta = abs(price - verdict_obj.stop_loss)
        fee_impact = (price + verdict_obj.stop_loss) * FEE_RATE
        true_risk_per_coin = price_delta + fee_impact
        
        position_size = FIXED_RISK_USD / true_risk_per_coin if true_risk_per_coin > 0 else 0
        
        await save_signal(symbol, verdict_obj.direction, price, verdict_obj.take_profit, verdict_obj.stop_loss, position_size)
        ui_text += f"🎯 **TP**: {verdict_obj.take_profit} | 🛑 **SL**: {verdict_obj.stop_loss}\n"
        ui_text += f"⚖️ **Об'єм:** `{position_size:.4f} {symbol}` | 💸 **Ризик:** `${FIXED_RISK_USD:.2f}`\n"

    await call.message.delete()
    await call.message.answer(ui_text, parse_mode="Markdown")

async def symbol_worker(symbol: str):
    await asyncio.sleep(WATCHLIST.index(symbol))
    while True:
        try:
            data = await get_market_data(symbol, use_ws=True)
            if data[0] is None: 
                await asyncio.sleep(5)
                continue
                
            price, vwap, vwap_dist_pct, rsi_15m, funding, df_15m, buy_pct, sell_pct, macd_15m, guide_macd, guide_name, cur_vol, avg_vol, atr_pct = data
            global_dataframes[symbol] = df_15m
            
            dynamic_threshold = atr_pct * ATR_MULTIPLIER
            alert_message, current_alert_type = None, None
            vol_tag = "⚠️ [АНОМАЛЬНИЙ ОБ'ЄМ]" if cur_vol > (avg_vol * 2.0) else ""

            if vwap_dist_pct >= dynamic_threshold: 
                current_alert_type = "VWAP_OVERBOUGHT"
                alert_message = f"🚨 ПЕРЕГРІВ ({symbol}): Відхилення {vwap_dist_pct:.2f}% (Поріг ATR: {dynamic_threshold:.2f}%). {vol_tag} Готуємо ШОРТ."
            elif vwap_dist_pct <= -dynamic_threshold: 
                current_alert_type = "VWAP_OVERSOLD"
                alert_message = f"🚨 ОБВАЛ ({symbol}): Відхилення {vwap_dist_pct:.2f}% (Поріг ATR: {dynamic_threshold:.2f}%). {vol_tag} Шукаємо ЛОНГ."

            if alert_message and current_alert_type != alert_state.get(f"last_{symbol}"):
                await bot.send_message(chat_id=ADMIN_ID, text=alert_message.strip())
                alert_state[f"last_{symbol}"] = current_alert_type

                if current_alert_type in ["VWAP_OVERBOUGHT", "VWAP_OVERSOLD"]:
                    await bot.send_message(chat_id=ADMIN_ID, text=f"🧠 Запускаю авто-аналіз мікроструктури для {symbol}...")
                    local_high = float(df_15m['high'].tail(4).max())
                    local_low = float(df_15m['low'].tail(4).min())
                    news = await fetch_news(symbol)
                    total_sig, win_rate = await get_recent_stats()

                    verdict_obj = await get_ai_forecast(
                        symbol=symbol, price=price, current_vwap=vwap, vwap_distance_pct=vwap_dist_pct,
                        rsi_15m=rsi_15m, macd_hist=macd_15m, guide_macd_hist=guide_macd, 
                        guide_name=guide_name, news=news, funding_rate=funding, cur_vol=cur_vol, avg_vol=avg_vol,
                        vwap_threshold=dynamic_threshold, local_high=local_high, local_low=local_low,
                        total_signals=total_sig, win_rate=win_rate
                    )
                    
                    if verdict_obj:
                        ui_text = f"🤖 **Auto AI ({symbol}):**\n\n**🔍 Мікроструктура:**\n{verdict_obj.analysis}\n\n**⚖️ Синтез:**\n{verdict_obj.synthesis}\n\n**💡 Вердикт:** {verdict_obj.direction}\n"
                        if verdict_obj.direction in ["ЛОНГ", "ШОРТ"] and verdict_obj.take_profit and verdict_obj.stop_loss:
                            # Чому: Ідентичний розрахунок істинного ризику для фонового контуру
                            FEE_RATE = 0.0012
                            price_delta = abs(price - verdict_obj.stop_loss)
                            fee_impact = (price + verdict_obj.stop_loss) * FEE_RATE
                            true_risk_per_coin = price_delta + fee_impact
                            
                            position_size = FIXED_RISK_USD / true_risk_per_coin if true_risk_per_coin > 0 else 0
                            
                            await save_signal(symbol, verdict_obj.direction, price, verdict_obj.take_profit, verdict_obj.stop_loss, position_size)
                            ui_text += f"🎯 **TP**: {verdict_obj.take_profit} | 🛑 **SL**: {verdict_obj.stop_loss}\n⚖️ **Об'єм:** `{position_size:.4f} {symbol}` | 💸 **Ризик:** `${FIXED_RISK_USD:.2f}`\n"
                        await bot.send_message(chat_id=ADMIN_ID, text=ui_text, parse_mode="Markdown")
                    await asyncio.sleep(3)
            await asyncio.sleep(2)
        except Exception as e:
            logging.error(f"Worker Error {symbol}: {e}")
            await asyncio.sleep(10)

async def reality_arbitrator():
    while True:
        await asyncio.sleep(60) 
        if global_dataframes:
            await resolve_open_signals(global_dataframes)

async def main():
    await init_db()
    asyncio.create_task(reality_arbitrator())
    for symbol in WATCHLIST:
        asyncio.create_task(symbol_worker(symbol))
        
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
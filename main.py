import asyncio
import datetime
import os
import json
import logging
import pandas as pd
import pandas_ta as ta
import pytz
import mplfinance as mpf

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from deriv_ws import DerivWebSocket, find_gold_symbol

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')

STOCH_K = 8
STOCH_D = 3
STOCH_SMOOTH = 3
ATR_PERIOD = 14
ATR_MULTIPLIER = 1.8
RR_TP1 = 1.0
RR_TP2 = 1.5
ADX_FILTER_PERIOD = 14
ADX_FILTER_THRESHOLD = 15
MA_SHORT_PERIOD = 21
LOT_SIZE = 0.01
RISK_PER_TRADE_USD = 2.00

active_trade = {}
win_count = 0
loss_count = 0
be_count = 0
deriv_ws = None
gold_symbol = None
subscribers = set()
dashboard_messages = {}
tracking_message_ids = {}

CHART_FILENAME = 'chart_v31.png'
STATE_FILENAME = 'bot_state_v31.json'
SUBSCRIBERS_FILENAME = 'subscribers.json'
LOG_FILENAME = 'bot_v31.log'
wib_tz = pytz.timezone('Asia/Jakarta')

class NoHttpxFilter(logging.Filter):
    def filter(self, record):
        return 'httpx' not in record.name and 'HTTP Request' not in record.getMessage()

bot_logger = logging.getLogger("BotV31")
bot_logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
bot_logger.addHandler(stream_handler)

file_handler = logging.FileHandler(LOG_FILENAME)
file_handler.setFormatter(formatter)
bot_logger.addHandler(file_handler)

logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("pandas_ta").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

def save_state():
    state = {'win_count': win_count, 'loss_count': loss_count, 'be_count': be_count}
    with open(STATE_FILENAME, 'w') as f:
        json.dump(state, f, indent=4)

def load_state():
    global win_count, loss_count, be_count
    try:
        if os.path.exists(STATE_FILENAME):
            with open(STATE_FILENAME, 'r') as f:
                state = json.load(f)
            win_count = state.get('win_count', 0)
            loss_count = state.get('loss_count', 0)
            be_count = state.get('be_count', 0)
            bot_logger.info(f"State dimuat: W:{win_count} L:{loss_count} BE:{be_count}")
    except Exception as e:
        bot_logger.error(f"Gagal memuat state: {e}")

def save_subscribers():
    with open(SUBSCRIBERS_FILENAME, 'w') as f:
        json.dump(list(subscribers), f)

def load_subscribers():
    global subscribers
    try:
        if os.path.exists(SUBSCRIBERS_FILENAME):
            with open(SUBSCRIBERS_FILENAME, 'r') as f:
                subscribers = set(json.load(f))
            bot_logger.info(f"Loaded {len(subscribers)} subscribers")
    except Exception as e:
        bot_logger.error(f"Failed to load subscribers: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    
    keyboard = [
        [InlineKeyboardButton("📥 Subscribe", callback_data="subscribe"),
         InlineKeyboardButton("📤 Unsubscribe", callback_data="unsubscribe")],
        [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard"),
         InlineKeyboardButton("📈 Stats", callback_data="stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    subscribed = chat_id in subscribers
    status = "✅ AKTIF" if subscribed else "❌ TIDAK AKTIF"
    
    await update.message.reply_text(
        f"🏆 *Bot Sinyal XAU/USD V31*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌐 Data real-time dari Deriv WebSocket\n\n"
        f"📋 Status Langganan: *{status}*\n\n"
        f"📌 *Menu Perintah:*\n"
        f"├ /subscribe - Mulai berlangganan\n"
        f"├ /unsubscribe - Berhenti langganan\n"
        f"├ /dashboard - Lihat posisi aktif\n"
        f"├ /stats - Statistik trading\n"
        f"└ /info - Info sistem\n\n"
        f"💡 Bot ini aktif 24 jam mencari sinyal terbaik untuk Anda!",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    
    if chat_id in subscribers:
        await update.message.reply_text(
            "✅ Anda sudah berlangganan!\n\n"
            "📊 Gunakan /dashboard untuk pantau posisi aktif.",
            parse_mode='Markdown'
        )
    else:
        subscribers.add(chat_id)
        save_subscribers()
        await update.message.reply_text(
            "🎉 *Selamat! Berhasil berlangganan!*\n\n"
            "📬 Anda akan menerima sinyal trading XAU/USD secara real-time.\n\n"
            "💡 *Tips:*\n"
            "├ Gunakan /dashboard untuk pantau posisi\n"
            "└ Bot akan mengirim update setiap 5 detik saat ada trade aktif\n\n"
            "🚀 Selamat trading!",
            parse_mode='Markdown'
        )
        bot_logger.info(f"New subscriber: {chat_id}")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.message.chat_id)
    
    if chat_id in subscribers:
        subscribers.discard(chat_id)
        save_subscribers()
        await update.message.reply_text(
            "👋 *Sampai jumpa lagi!*\n\n"
            "Anda telah berhenti berlangganan.\n\n"
            "💡 Gunakan /subscribe kapan saja untuk kembali bergabung!",
            parse_mode='Markdown'
        )
        bot_logger.info(f"Unsubscribed: {chat_id}")
    else:
        await update.message.reply_text(
            "ℹ️ Anda belum berlangganan.\n\n"
            "💡 Gunakan /subscribe untuk mulai menerima sinyal.",
            parse_mode='Markdown'
        )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total = win_count + loss_count + be_count
    win_rate = (win_count / (win_count + loss_count)) * 100 if (win_count + loss_count) > 0 else 0.0
    
    if win_rate >= 60:
        rate_emoji = "🔥"
    elif win_rate >= 50:
        rate_emoji = "👍"
    else:
        rate_emoji = "📊"
    
    await update.message.reply_text(
        f"📈 *Statistik Trading XAU/USD*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Total Trade: *{total}*\n\n"
        f"✅ Menang: *{win_count}*\n"
        f"❌ Kalah: *{loss_count}*\n"
        f"⚖️ Break Even: *{be_count}*\n\n"
        f"{rate_emoji} Win Rate: *{win_rate:.1f}%*\n\n"
        f"💡 Bot terus bekerja 24 jam untuk Anda!",
        parse_mode='Markdown'
    )

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = "🟢 Terhubung" if (deriv_ws and deriv_ws.connected) else "🔴 Terputus"
    current_price = deriv_ws.get_current_price() if deriv_ws else None
    price_str = f"${current_price:.3f}" if current_price else "N/A"
    subscriber_count = len(subscribers)
    
    await update.message.reply_text(
        f"⚙️ *Info Sistem Bot*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📡 WebSocket: {status}\n"
        f"🏷️ Symbol: {gold_symbol or 'frxXAUUSD'}\n"
        f"💰 Harga Terakhir: {price_str}\n"
        f"👥 Total Subscriber: {subscriber_count}\n\n"
        f"📊 Data Source: Deriv\n"
        f"⏱️ Interval: 1 menit\n"
        f"🔄 Update Tracking: 5 detik\n\n"
        f"🤖 Bot berjalan 24 jam non-stop!",
        parse_mode='Markdown'
    )

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_dashboard(update.message.chat_id, context.bot)

async def send_dashboard(chat_id, bot):
    status = "🟢 Terhubung" if (deriv_ws and deriv_ws.connected) else "🔴 Terputus"
    current_price = deriv_ws.get_current_price() if deriv_ws else None
    price_str = f"${current_price:.3f}" if current_price else "N/A"
    
    now = datetime.datetime.now(wib_tz)
    
    dashboard_text = (
        f"📊 *DASHBOARD XAU/USD*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 _{now.strftime('%H:%M:%S WIB')}_\n\n"
        f"📡 Status: {status}\n"
        f"💰 Harga: *{price_str}*\n"
        f"🏷️ Symbol: {gold_symbol or 'frxXAUUSD'}\n\n"
    )
    
    if active_trade:
        direction = active_trade['direction']
        entry = active_trade['entry_price']
        tp1 = active_trade['tp1_level']
        tp2 = active_trade['tp2_level']
        sl = active_trade['sl_level']
        trade_status = active_trade['status']
        
        dir_emoji = "📈" if direction == 'BUY' else "📉"
        
        if current_price:
            if direction == 'BUY':
                pnl_pips = (current_price - entry) * 10
            else:
                pnl_pips = (entry - current_price) * 10
            pnl_emoji = "🟢" if pnl_pips >= 0 else "🔴"
            pnl_str = f"{pnl_emoji} {pnl_pips:+.1f} pips"
        else:
            pnl_str = "N/A"
        
        status_display = "🛡️ BE Mode" if trade_status == 'tp1_hit' else "🔥 Aktif"
        
        dashboard_text += (
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{dir_emoji} *POSISI AKTIF*\n\n"
            f"📍 Arah: *{direction}*\n"
            f"💵 Entry: *${entry:.3f}*\n\n"
            f"🎯 TP1: ${tp1:.3f}\n"
            f"🏆 TP2: ${tp2:.3f}\n"
            f"🛑 SL: ${sl:.3f}\n\n"
            f"📊 Status: *{status_display}*\n"
            f"💹 P&L: *{pnl_str}*\n\n"
        )
    else:
        dashboard_text += (
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 *Tidak Ada Posisi Aktif*\n\n"
            f"💡 Bot sedang mencari sinyal terbaik...\n\n"
        )
    
    total = win_count + loss_count + be_count
    win_rate = (win_count / (win_count + loss_count)) * 100 if (win_count + loss_count) > 0 else 0.0
    
    dashboard_text += (
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 *STATISTIK*\n"
        f"Total: {total} | ✅ {win_count} | ❌ {loss_count} | ⚖️ {be_count}\n"
        f"Win Rate: {win_rate:.1f}%"
    )
    
    keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="dashboard")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=dashboard_text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    except Exception as e:
        bot_logger.error(f"Failed to send dashboard: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = str(query.message.chat_id)
    
    if query.data == "subscribe":
        if chat_id in subscribers:
            await query.edit_message_text(
                "✅ Anda sudah berlangganan!\n\n"
                "📊 Gunakan /dashboard untuk pantau posisi aktif.",
                parse_mode='Markdown'
            )
        else:
            subscribers.add(chat_id)
            save_subscribers()
            await query.edit_message_text(
                "🎉 *Selamat! Berhasil berlangganan!*\n\n"
                "📬 Anda akan menerima sinyal trading XAU/USD secara real-time.\n\n"
                "💡 Gunakan /dashboard untuk pantau posisi aktif.",
                parse_mode='Markdown'
            )
    
    elif query.data == "unsubscribe":
        if chat_id in subscribers:
            subscribers.discard(chat_id)
            save_subscribers()
            await query.edit_message_text(
                "👋 *Sampai jumpa lagi!*\n\n"
                "Anda telah berhenti berlangganan.\n"
                "💡 Gunakan /subscribe untuk bergabung kembali.",
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                "ℹ️ Anda belum berlangganan.\n\n"
                "💡 Gunakan /subscribe untuk mulai menerima sinyal.",
                parse_mode='Markdown'
            )
    
    elif query.data == "dashboard":
        await send_dashboard(chat_id, context.bot)
    
    elif query.data == "stats":
        total = win_count + loss_count + be_count
        win_rate = (win_count / (win_count + loss_count)) * 100 if (win_count + loss_count) > 0 else 0.0
        
        if win_rate >= 60:
            rate_emoji = "🔥"
        elif win_rate >= 50:
            rate_emoji = "👍"
        else:
            rate_emoji = "📊"
        
        await query.edit_message_text(
            f"📈 *Statistik Trading XAU/USD*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 Total Trade: *{total}*\n\n"
            f"✅ Menang: *{win_count}*\n"
            f"❌ Kalah: *{loss_count}*\n"
            f"⚖️ Break Even: *{be_count}*\n\n"
            f"{rate_emoji} Win Rate: *{win_rate:.1f}%*",
            parse_mode='Markdown'
        )

async def get_historical_data():
    global deriv_ws, gold_symbol
    
    if not deriv_ws or not deriv_ws.connected:
        bot_logger.warning("WebSocket not connected, attempting reconnect...")
        deriv_ws = DerivWebSocket()
        if not await deriv_ws.connect():
            return None
    
    try:
        symbol = gold_symbol or "frxXAUUSD"
        candles = await deriv_ws.get_candles(symbol=symbol, count=200, granularity=60)
        
        if not candles:
            bot_logger.warning("No candle data received")
            return None
        
        df_data = []
        for c in candles:
            df_data.append({
                'date': datetime.datetime.fromtimestamp(c['epoch'], tz=datetime.timezone.utc),
                'Open': float(c['open']),
                'High': float(c['high']),
                'Low': float(c['low']),
                'Close': float(c['close'])
            })
        
        df = pd.DataFrame(df_data)
        df.set_index('date', inplace=True)
        return df
        
    except Exception as e:
        bot_logger.error(f"DATA-ERROR: {e}")
        return None

async def get_realtime_price():
    global deriv_ws
    
    if deriv_ws and deriv_ws.connected:
        return deriv_ws.get_current_price()
    return None

def calculate_indicators(df):
    df.ta.stoch(k=STOCH_K, d=STOCH_D, smooth_k=STOCH_SMOOTH, append=True)
    df.ta.atr(length=ATR_PERIOD, append=True)
    df.ta.adx(length=ADX_FILTER_PERIOD, append=True)
    df.ta.ema(length=MA_SHORT_PERIOD, append=True)
    return df

async def send_to_all_subscribers(bot, text, photo_path=None):
    for chat_id in subscribers.copy():
        try:
            if photo_path and os.path.exists(photo_path):
                with open(photo_path, 'rb') as photo_file:
                    await bot.send_photo(chat_id=chat_id, photo=photo_file, caption=text, parse_mode='Markdown')
            else:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')
        except TelegramError as e:
            bot_logger.error(f"Failed to send to {chat_id}: {e}")
            if "blocked" in str(e).lower() or "not found" in str(e).lower():
                subscribers.discard(chat_id)
                save_subscribers()

async def send_tracking_update(bot, current_price):
    global tracking_message_ids
    
    if not active_trade:
        return
    
    direction = active_trade['direction']
    entry = active_trade['entry_price']
    tp1 = active_trade['tp1_level']
    tp2 = active_trade['tp2_level']
    sl = active_trade['sl_level']
    trade_status = active_trade['status']
    
    dir_emoji = "📈" if direction == 'BUY' else "📉"
    
    if direction == 'BUY':
        pnl_pips = (current_price - entry) * 10
        distance_tp1 = tp1 - current_price
        distance_tp2 = tp2 - current_price
        distance_sl = current_price - sl
    else:
        pnl_pips = (entry - current_price) * 10
        distance_tp1 = current_price - tp1
        distance_tp2 = current_price - tp2
        distance_sl = sl - current_price
    
    pnl_emoji = "🟢" if pnl_pips >= 0 else "🔴"
    status_display = "🛡️ BE Mode" if trade_status == 'tp1_hit' else "🔥 Tracking"
    
    now = datetime.datetime.now(wib_tz)
    
    update_text = (
        f"🎯 *LIVE TRACKING XAU/USD*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 _{now.strftime('%H:%M:%S WIB')}_\n\n"
        f"{dir_emoji} *{direction}* @ ${entry:.3f}\n"
        f"💰 Harga: *${current_price:.3f}*\n\n"
        f"{pnl_emoji} P&L: *{pnl_pips:+.1f} pips*\n"
        f"📊 Status: *{status_display}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 Jarak TP1: {distance_tp1:.3f}\n"
        f"🏆 Jarak TP2: {distance_tp2:.3f}\n"
        f"🛑 Jarak SL: {distance_sl:.3f}\n\n"
        f"🔄 Update setiap 5 detik"
    )
    
    for chat_id in subscribers.copy():
        try:
            if chat_id in tracking_message_ids:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=tracking_message_ids[chat_id],
                        text=update_text,
                        parse_mode='Markdown'
                    )
                except TelegramError as edit_error:
                    if "message is not modified" not in str(edit_error).lower():
                        msg = await bot.send_message(chat_id=chat_id, text=update_text, parse_mode='Markdown')
                        tracking_message_ids[chat_id] = msg.message_id
            else:
                msg = await bot.send_message(chat_id=chat_id, text=update_text, parse_mode='Markdown')
                tracking_message_ids[chat_id] = msg.message_id
        except TelegramError as e:
            bot_logger.error(f"Tracking update failed for {chat_id}: {e}")

def clear_tracking_messages():
    global tracking_message_ids
    tracking_message_ids = {}

async def send_photo(bot, caption_text):
    if os.path.exists(CHART_FILENAME):
        await send_to_all_subscribers(bot, caption_text, CHART_FILENAME)
        os.remove(CHART_FILENAME)
        return True
    return False

async def generate_chart(df, trade_info, title):
    try:
        hlines = [trade_info.get('sl_level'), trade_info.get('tp1_level'), trade_info.get('tp2_level')]
        hlines = [h for h in hlines if h is not None]
        
        mpf.plot(
            df.tail(60),
            type='candle',
            style='yahoo',
            title=title,
            ylabel='Harga ($)',
            volume=False,
            hlines=dict(hlines=hlines, colors=['r', 'orange', 'g'][:len(hlines)], linestyle='--'),
            savefig=CHART_FILENAME
        )
        return True
    except Exception as e:
        bot_logger.error(f"CHART-ERROR: {e}")
        return False

async def signal_engine_loop(bot):
    global active_trade, win_count, loss_count, be_count, deriv_ws, gold_symbol
    
    bot_logger.info("=" * 50)
    bot_logger.info("🚀 Bot Sinyal V31 (Public Edition) dimulai!")
    bot_logger.info("🌐 Sumber Data: Deriv WebSocket")
    bot_logger.info("🔄 Mode: 24 Jam Non-Stop")
    bot_logger.info("=" * 50)
    
    gold_symbol = "frxXAUUSD"
    bot_logger.info(f"🏷️ Menggunakan symbol XAU/USD: {gold_symbol}")
    
    deriv_ws = DerivWebSocket()
    if not await deriv_ws.connect():
        bot_logger.critical("❌ Gagal connect ke Deriv WebSocket!")
        return
    
    await deriv_ws.subscribe_ticks(gold_symbol)
    
    listen_task = asyncio.create_task(deriv_ws.listen())
    
    async def keep_alive():
        while True:
            await asyncio.sleep(30)
            if deriv_ws and deriv_ws.connected:
                await deriv_ws.send_ping()
    
    keepalive_task = asyncio.create_task(keep_alive())
    
    bot_logger.info("🔍 Mesin sinyal dimulai - Mencari sinyal 24 jam...")
    
    while True:
        try:
            status_str = '🎯 Melacak' if active_trade else '🔍 Mencari'
            bot_logger.info(f"--- Siklus Baru | Status: {status_str} | 👥 Subscribers: {len(subscribers)} ---")
            
            if not deriv_ws.connected:
                bot_logger.warning("⚠️ WebSocket terputus, mencoba reconnect...")
                if listen_task and not listen_task.done():
                    listen_task.cancel()
                    try:
                        await listen_task
                    except asyncio.CancelledError:
                        pass
                if await deriv_ws.connect():
                    await deriv_ws.subscribe_ticks(gold_symbol)
                    listen_task = asyncio.create_task(deriv_ws.listen())
                    bot_logger.info("✅ Reconnect berhasil!")
                else:
                    await asyncio.sleep(30)
                    continue
            
            df = await get_historical_data()
            
            if df is None:
                bot_logger.warning("⚠️ Data tidak tersedia dari Deriv")
                await asyncio.sleep(60)
                continue
            
            if active_trade:
                bot_logger.info(f"🎯 Mode Pelacakan (Trade {active_trade['direction']})")
                trade_closed = False
                
                for i in range(12):
                    await asyncio.sleep(5)
                    current_price = await get_realtime_price()
                    
                    if current_price is None:
                        continue
                    
                    bot_logger.info(
                        f"📊 Melacak... Harga: {current_price:.3f} | "
                        f"TP2: {active_trade['tp2_level']:.3f} | "
                        f"SL: {active_trade['sl_level']:.3f}"
                    )
                    
                    await send_tracking_update(bot, current_price)
                    
                    result_info = {}
                    trade_status = active_trade['status']
                    
                    if trade_status == 'active':
                        if active_trade['direction'] == 'BUY' and current_price <= active_trade['sl_level']:
                            result_info = {'type': 'LOSS'}
                        elif active_trade['direction'] == 'SELL' and current_price >= active_trade['sl_level']:
                            result_info = {'type': 'LOSS'}
                        elif active_trade['direction'] == 'BUY' and current_price >= active_trade['tp1_level']:
                            result_info = {'type': 'TP1_HIT'}
                        elif active_trade['direction'] == 'SELL' and current_price <= active_trade['tp1_level']:
                            result_info = {'type': 'TP1_HIT'}
                    
                    elif trade_status == 'tp1_hit':
                        if active_trade['direction'] == 'BUY' and current_price <= active_trade['entry_price']:
                            result_info = {'type': 'BREAK_EVEN'}
                        elif active_trade['direction'] == 'BUY' and current_price >= active_trade['tp2_level']:
                            result_info = {'type': 'WIN'}
                        elif active_trade['direction'] == 'SELL' and current_price >= active_trade['entry_price']:
                            result_info = {'type': 'BREAK_EVEN'}
                        elif active_trade['direction'] == 'SELL' and current_price <= active_trade['tp2_level']:
                            result_info = {'type': 'WIN'}
                    
                    if result_info.get('type') == 'TP1_HIT':
                        active_trade['status'] = 'tp1_hit'
                        active_trade['sl_level'] = active_trade['entry_price']
                        
                        tp1_text = (
                            f"🎯 *TP1 TERCAPAI!*\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"📍 Posisi: *{active_trade['direction']}* @ ${active_trade['entry_price']:.3f}\n\n"
                            f"🛡️ *AKSI: SL dipindah ke Entry!*\n\n"
                            f"💡 Trade sekarang dalam mode Break Even\n"
                            f"🎯 Target selanjutnya: TP2"
                        )
                        await send_to_all_subscribers(bot, tp1_text)
                    
                    elif result_info.get('type') in ['WIN', 'LOSS', 'BREAK_EVEN']:
                        if result_info['type'] == 'WIN':
                            win_count += 1
                            result_emoji = "🏆"
                            result_text = "MENANG - TP2 TERCAPAI!"
                        elif result_info['type'] == 'LOSS':
                            loss_count += 1
                            result_emoji = "❌"
                            result_text = "KALAH - SL TERKENA"
                        elif result_info['type'] == 'BREAK_EVEN':
                            be_count += 1
                            result_emoji = "⚖️"
                            result_text = "BREAK EVEN"
                        
                        save_state()
                        
                        closing_df = await get_historical_data()
                        if closing_df is not None:
                            duration = round(
                                (datetime.datetime.now(datetime.timezone.utc) - active_trade['start_time_utc']).total_seconds() / 60,
                                1
                            )
                            final_title = f"{result_emoji} {result_text}"
                            
                            win_rate = (win_count / (win_count + loss_count)) * 100 if (win_count + loss_count) > 0 else 0.0
                            
                            result_caption = (
                                f"{result_emoji} *{result_text}*\n"
                                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                                f"⏱️ Durasi: *{duration} menit*\n\n"
                                f"📊 *Statistik Update:*\n"
                                f"✅ Win: {win_count} | ❌ Loss: {loss_count} | ⚖️ BE: {be_count}\n"
                                f"📈 Win Rate: {win_rate:.1f}%\n\n"
                                f"🔍 Bot kembali mencari sinyal..."
                            )
                            if await generate_chart(closing_df, active_trade, final_title):
                                await send_photo(bot, result_caption)
                        
                        active_trade = {}
                        trade_closed = True
                        clear_tracking_messages()
                        break
                
                if trade_closed:
                    continue
            
            else:
                bot_logger.info("🔍 Menganalisis data dari Deriv...")
                df = calculate_indicators(df)
                latest = df.iloc[-2]
                previous = df.iloc[-3]
                latest_close = latest['Close']
                
                bot_logger.info(f"💰 Data Terakhir XAU/USD: Close = {latest_close:.3f}")
                
                stoch_k_col = f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'
                stoch_d_col = f'STOCHd_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'
                
                is_buy = (previous[stoch_k_col] < previous[stoch_d_col] and latest[stoch_k_col] > latest[stoch_d_col])
                is_sell = (previous[stoch_k_col] > previous[stoch_d_col] and latest[stoch_k_col] < latest[stoch_d_col])
                
                adx_value = latest[f'ADX_{ADX_FILTER_PERIOD}']
                ma_value = latest[f'EMA_{MA_SHORT_PERIOD}']
                
                bot_logger.info(f"📊 Data Sinyal: StochBuy={is_buy}, StochSell={is_sell}, ADX={adx_value:.2f}, EMA={ma_value:.2f}")
                
                final_signal = None
                if adx_value >= ADX_FILTER_THRESHOLD:
                    if is_buy and latest_close > ma_value:
                        final_signal = 'BUY'
                    elif is_sell and latest_close < ma_value:
                        final_signal = 'SELL'
                
                if final_signal:
                    bot_logger.info(f"🎯 Sinyal {final_signal} valid ditemukan!")
                    
                    latest_atr = latest[f'ATRr_{ATR_PERIOD}']
                    
                    if final_signal == "BUY":
                        sl = latest_close - (latest_atr * ATR_MULTIPLIER)
                        risk = abs(latest_close - sl)
                        tp1 = latest_close + (risk * RR_TP1)
                        tp2 = latest_close + (risk * RR_TP2)
                        signal_emoji = "📈"
                    else:
                        sl = latest_close + (latest_atr * ATR_MULTIPLIER)
                        risk = abs(latest_close - sl)
                        tp1 = latest_close - (risk * RR_TP1)
                        tp2 = latest_close - (risk * RR_TP2)
                        signal_emoji = "📉"
                    
                    title = f"{signal_emoji} SINYAL {final_signal}"
                    start_time_utc = datetime.datetime.now(datetime.timezone.utc)
                    
                    temp_trade_info = {
                        "direction": final_signal,
                        "entry_price": latest_close,
                        "tp1_level": tp1,
                        "tp2_level": tp2,
                        "sl_level": sl,
                        "start_time_utc": start_time_utc,
                        "status": "active"
                    }
                    
                    caption = (
                        f"{signal_emoji} *SINYAL {final_signal} XAU/USD*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🌐 _Data: Deriv WebSocket_\n\n"
                        f"🕐 Waktu: *{start_time_utc.astimezone(wib_tz).strftime('%H:%M:%S WIB')}*\n"
                        f"💵 Entry: *${latest_close:.3f}*\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"📋 *RENCANA EKSEKUSI*\n"
                        f"📦 Lot: {LOT_SIZE}\n"
                        f"💰 Risiko: ~${RISK_PER_TRADE_USD:.2f}\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🎯 *TARGET & PROTEKSI*\n"
                        f"🎯 TP1: *${tp1:.3f}*\n"
                        f"🏆 TP2: *${tp2:.3f}*\n"
                        f"🛑 SL: *${sl:.3f}*\n\n"
                        f"🔄 Update posisi setiap 5 detik"
                    )
                    
                    if await generate_chart(df, temp_trade_info, title):
                        if await send_photo(bot, caption):
                            active_trade = temp_trade_info
                            clear_tracking_messages()
                            current_price = await get_realtime_price()
                            if current_price:
                                await send_tracking_update(bot, current_price)
                            bot_logger.info("✅ Sinyal berhasil dikirim! Mode pelacakan aktif.")
                else:
                    bot_logger.info("🔍 Tidak ada sinyal valid saat ini. Terus mencari...")
            
            if not active_trade:
                bot_logger.info("⏳ Menunggu 60 detik sebelum analisis berikutnya...")
                await asyncio.sleep(60)
        
        except asyncio.TimeoutError:
            bot_logger.error("⚠️ TIMEOUT: Proses terlalu lama")
            await asyncio.sleep(60)
        except Exception as e:
            bot_logger.critical(f"❌ Error kritis: {e}")
            await asyncio.sleep(60)

async def main():
    if 'YOUR_BOT_TOKEN' in TELEGRAM_BOT_TOKEN:
        bot_logger.critical("❌ Harap set TELEGRAM_BOT_TOKEN di environment variables!")
        bot_logger.info("💡 Export variable: TELEGRAM_BOT_TOKEN")
        return
    
    load_state()
    load_subscribers()
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("dashboard", dashboard))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    async with application:
        await application.initialize()
        await application.start()
        if application.updater:
            await application.updater.start_polling()
        
        bot_logger.info("🚀 Bot dimulai! Otomatis mencari sinyal 24 jam...")
        await signal_engine_loop(application.bot)
        
        if application.updater:
            await application.updater.stop()
        await application.stop()

if __name__ == '__main__':
    print("""
🏆 XAU/USD Signal Bot V31 - Public Edition
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 Menggunakan Deriv WebSocket
🔄 Mode: 24 Jam Non-Stop
📊 Update Tracking: Setiap 5 Detik
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        bot_logger.info("👋 Bot dihentikan oleh user.")
    except Exception as e:
        bot_logger.critical(f"❌ Error tak terduga: {e}")

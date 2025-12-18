import asyncio
import datetime
import os
import json
import logging
import random
import pandas as pd
import pandas_ta as ta
import pytz
import mplfinance as mpf
from aiohttp import web, ClientSession

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from deriv_ws import DerivWebSocket, find_gold_symbol

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')
PORT = int(os.environ.get('PORT', 8000))

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
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
LOT_SIZE = 0.01
RISK_PER_TRADE_USD = 2.00

ANALYSIS_INTERVAL = 10
ANALYSIS_JITTER = 3

cached_candles_df = None
last_candle_fetch = None

deriv_ws = None
gold_symbol = None
subscribers = set()
current_signal = {}
last_signal_info = {}

user_states = {}

CHART_FILENAME = 'chart_v1.2.png'
USER_STATES_FILENAME = 'user_states.json'
SUBSCRIBERS_FILENAME = 'subscribers.json'
LOG_FILENAME = 'bot_v1.2.log'
wib_tz = pytz.timezone('Asia/Jakarta')

def get_default_user_state():
    """Return default state for a new user"""
    return {
        'win_count': 0,
        'loss_count': 0,
        'be_count': 0,
        'active_trade': {},
        'tracking_message_id': None,
        'last_signal_time': None
    }

def get_user_state(chat_id):
    """Get user state, create if not exists"""
    chat_id = str(chat_id)
    if chat_id not in user_states:
        user_states[chat_id] = get_default_user_state()
    return user_states[chat_id]

def save_user_states():
    """Save all user states to file"""
    try:
        states_to_save = {}
        for chat_id, state in user_states.items():
            state_copy = state.copy()
            if state_copy.get('active_trade') and 'start_time_utc' in state_copy['active_trade']:
                trade = state_copy['active_trade'].copy()
                if isinstance(trade.get('start_time_utc'), datetime.datetime):
                    trade['start_time_utc'] = trade['start_time_utc'].isoformat()
                state_copy['active_trade'] = trade
            states_to_save[chat_id] = state_copy
        with open(USER_STATES_FILENAME, 'w') as f:
            json.dump(states_to_save, f, indent=2)
    except Exception as e:
        bot_logger.error(f"Failed to save user states: {e}")

def load_user_states():
    """Load all user states from file"""
    global user_states
    try:
        if os.path.exists(USER_STATES_FILENAME):
            with open(USER_STATES_FILENAME, 'r') as f:
                loaded = json.load(f)
            for chat_id, state in loaded.items():
                if state.get('active_trade') and 'start_time_utc' in state['active_trade']:
                    try:
                        state['active_trade']['start_time_utc'] = datetime.datetime.fromisoformat(
                            state['active_trade']['start_time_utc']
                        )
                    except:
                        pass
                user_states[chat_id] = state
            bot_logger.info(f"Loaded states for {len(user_states)} users")
    except Exception as e:
        bot_logger.error(f"Failed to load user states: {e}")

class NoHttpxFilter(logging.Filter):
    def filter(self, record):
        return 'httpx' not in record.name and 'HTTP Request' not in record.getMessage()

bot_logger = logging.getLogger("BotV1.2")
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
logging.getLogger("aiohttp").setLevel(logging.WARNING)

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    chat_id = str(update.message.chat_id)
    
    get_user_state(chat_id)
    
    keyboard = [
        [InlineKeyboardButton("📥 Subscribe", callback_data="subscribe"),
         InlineKeyboardButton("📤 Unsubscribe", callback_data="unsubscribe")],
        [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard"),
         InlineKeyboardButton("📈 Stats", callback_data="stats")],
        [InlineKeyboardButton("🔄 Reset Data", callback_data="riset")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    subscribed = chat_id in subscribers
    status = "✅ AKTIF" if subscribed else "❌ TIDAK AKTIF"
    
    await update.message.reply_text(
        f"🏆 *Bot Sinyal XAU/USD V1.2*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌐 Data real-time dari Deriv WebSocket\n\n"
        f"📋 Status Langganan: *{status}*\n\n"
        f"📌 *Menu Perintah:*\n"
        f"├ /subscribe - Mulai berlangganan\n"
        f"├ /unsubscribe - Berhenti langganan\n"
        f"├ /dashboard - Lihat posisi aktif\n"
        f"├ /signal - Lihat sinyal terakhir\n"
        f"├ /stats - Statistik trading Anda\n"
        f"├ /riset - Reset data trading Anda\n"
        f"└ /info - Info sistem\n\n"
        f"💡 Bot ini aktif 24 jam mencari sinyal terbaik untuk Anda!",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
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
        
        user_state = get_user_state(chat_id)
        if current_signal:
            user_state['active_trade'] = current_signal.copy()
            user_state['tracking_message_id'] = None
            save_user_states()
        
        await update.message.reply_text(
            "🎉 *Selamat! Berhasil berlangganan!*\n\n"
            "📬 Anda akan menerima sinyal trading XAU/USD secara real-time.\n\n"
            "💡 *Tips:*\n"
            "├ Gunakan /dashboard untuk pantau posisi\n"
            "└ Bot akan melacak posisi hingga TP/SL tercapai\n\n"
            "🚀 Selamat trading!",
            parse_mode='Markdown'
        )
        bot_logger.info(f"New subscriber: {chat_id}")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
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

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    chat_id = str(update.message.chat_id)
    user_state = get_user_state(chat_id)
    
    win_count = user_state['win_count']
    loss_count = user_state['loss_count']
    be_count = user_state['be_count']
    
    total = win_count + loss_count + be_count
    win_rate = (win_count / (win_count + loss_count)) * 100 if (win_count + loss_count) > 0 else 0.0
    
    if win_rate >= 60:
        rate_emoji = "🔥"
    elif win_rate >= 50:
        rate_emoji = "👍"
    else:
        rate_emoji = "📊"
    
    await update.message.reply_text(
        f"📈 *Statistik Trading Anda*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Total Trade: *{total}*\n\n"
        f"✅ Menang: *{win_count}*\n"
        f"❌ Kalah: *{loss_count}*\n"
        f"⚖️ Break Even: *{be_count}*\n\n"
        f"{rate_emoji} Win Rate: *{win_rate:.1f}%*\n\n"
        f"💡 Gunakan /riset untuk reset statistik.\n"
        f"🤖 Bot bekerja 24 jam untuk Anda!",
        parse_mode='Markdown'
    )

async def riset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset user's trading data"""
    if not update.message:
        return
    chat_id = str(update.message.chat_id)
    
    user_state = get_user_state(chat_id)
    old_stats = f"W:{user_state['win_count']} L:{user_state['loss_count']} BE:{user_state['be_count']}"
    
    user_state['win_count'] = 0
    user_state['loss_count'] = 0
    user_state['be_count'] = 0
    user_state['active_trade'] = {}
    user_state['tracking_message_id'] = None
    
    save_user_states()
    
    await update.message.reply_text(
        f"🔄 *DATA BERHASIL DIRESET!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Data sebelumnya: {old_stats}\n"
        f"📊 Data sekarang: W:0 L:0 BE:0\n\n"
        f"✅ Trade aktif: Dihapus\n"
        f"✅ Win rate: 0%\n\n"
        f"💡 Langganan Anda tetap aktif!\n"
        f"📬 Sinyal baru akan dikirim otomatis.",
        parse_mode='Markdown'
    )
    bot_logger.info(f"User {chat_id} reset data: {old_stats} -> 0")

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
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
        f"⏱️ Interval Analisis: ~10 detik\n"
        f"🔄 Tracking: Aktif saat ada posisi\n\n"
        f"🤖 Bot berjalan 24 jam non-stop!",
        parse_mode='Markdown'
    )

async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await send_dashboard(update.message.chat_id, context.bot)

async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    
    if not last_signal_info:
        await update.message.reply_text(
            "🔍 *Belum Ada Sinyal*\n\n"
            "Bot sedang mencari sinyal terbaik untuk Anda.\n"
            "💡 Gunakan /subscribe untuk menerima notifikasi otomatis.",
            parse_mode='Markdown'
        )
        return
    
    direction = last_signal_info.get('direction', 'N/A')
    entry = last_signal_info.get('entry_price', 0)
    tp1 = last_signal_info.get('tp1_level', 0)
    tp2 = last_signal_info.get('tp2_level', 0)
    sl = last_signal_info.get('sl_level', 0)
    signal_time = last_signal_info.get('time', 'N/A')
    status = last_signal_info.get('status', 'N/A')
    
    dir_emoji = "📈" if direction == 'BUY' else "📉"
    
    await update.message.reply_text(
        f"📋 *SINYAL TERAKHIR*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{dir_emoji} Arah: *{direction}*\n"
        f"🕐 Waktu: {signal_time}\n"
        f"📊 Status: *{status}*\n\n"
        f"💵 Entry: *${entry:.3f}*\n"
        f"🎯 TP1: ${tp1:.3f}\n"
        f"🏆 TP2: ${tp2:.3f}\n"
        f"🛑 SL: ${sl:.3f}\n\n"
        f"💡 Gunakan /dashboard untuk tracking real-time",
        parse_mode='Markdown'
    )

async def send_dashboard(chat_id, bot):
    chat_id = str(chat_id)
    user_state = get_user_state(chat_id)
    
    ws_status = "🟢 Terhubung" if (deriv_ws and deriv_ws.connected) else "🔴 Terputus"
    current_price = deriv_ws.get_current_price() if deriv_ws else None
    price_str = f"${current_price:.3f}" if current_price else "N/A"
    
    now = datetime.datetime.now(wib_tz)
    
    dashboard_text = (
        f"📊 *DASHBOARD XAU/USD*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 _{now.strftime('%H:%M:%S WIB')}_\n\n"
        f"📡 Status: {ws_status}\n"
        f"💰 Harga: *{price_str}*\n"
        f"🏷️ Symbol: {gold_symbol or 'frxXAUUSD'}\n\n"
    )
    
    active_trade = user_state.get('active_trade', {})
    
    if active_trade:
        direction = active_trade['direction']
        entry = active_trade['entry_price']
        tp1 = active_trade['tp1_level']
        tp2 = active_trade['tp2_level']
        sl = active_trade['sl_level']
        trade_status = active_trade.get('status', 'active')
        
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
            f"{dir_emoji} *POSISI AKTIF ANDA*\n\n"
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
    
    win_count = user_state['win_count']
    loss_count = user_state['loss_count']
    be_count = user_state['be_count']
    total = win_count + loss_count + be_count
    win_rate = (win_count / (win_count + loss_count)) * 100 if (win_count + loss_count) > 0 else 0.0
    
    dashboard_text += (
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 *STATISTIK ANDA*\n"
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

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.message:
        return
    await query.answer()
    
    chat_id = str(query.message.chat_id)  # type: ignore
    
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
            
            user_state = get_user_state(chat_id)
            if current_signal:
                user_state['active_trade'] = current_signal.copy()
                user_state['tracking_message_id'] = None
                save_user_states()
            
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
    
    elif query.data == "riset":
        user_state = get_user_state(chat_id)
        old_stats = f"W:{user_state['win_count']} L:{user_state['loss_count']} BE:{user_state['be_count']}"
        
        user_state['win_count'] = 0
        user_state['loss_count'] = 0
        user_state['be_count'] = 0
        user_state['active_trade'] = {}
        user_state['tracking_message_id'] = None
        save_user_states()
        
        await query.edit_message_text(
            f"🔄 *DATA BERHASIL DIRESET!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 Data sebelumnya: {old_stats}\n"
            f"📊 Data sekarang: W:0 L:0 BE:0\n\n"
            f"✅ Langganan Anda tetap aktif!",
            parse_mode='Markdown'
        )
        bot_logger.info(f"User {chat_id} reset via button: {old_stats} -> 0")
    
    elif query.data == "stats":
        user_state = get_user_state(chat_id)
        win_count = user_state['win_count']
        loss_count = user_state['loss_count']
        be_count = user_state['be_count']
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
        bot_logger.warning("WebSocket not connected, skipping data fetch...")
        return None
    
    try:
        symbol = gold_symbol or "frxXAUUSD"
        candles = await deriv_ws.get_candles(symbol=symbol, count=200, granularity=60)
        
        if not candles or not isinstance(candles, list):
            bot_logger.warning("No candle data received")
            return None
        
        df_data = []
        for c in candles:  # type: ignore
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
    df.ta.rsi(length=RSI_PERIOD, append=True)
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

async def send_tracking_update(bot, current_price, signal_info):
    """Send tracking update to all subscribers with active trade"""
    if not signal_info:
        return
    
    direction = signal_info['direction']
    entry = signal_info['entry_price']
    tp1 = signal_info['tp1_level']
    tp2 = signal_info['tp2_level']
    sl = signal_info['sl_level']
    trade_status = signal_info.get('status', 'active')
    
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
        f"📡 Tracking aktif"
    )
    
    for chat_id in subscribers.copy():
        user_state = get_user_state(chat_id)
        if not user_state.get('active_trade'):
            continue
        
        try:
            tracking_msg_id = user_state.get('tracking_message_id')
            if tracking_msg_id:
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=tracking_msg_id,
                        text=update_text,
                        parse_mode='Markdown'
                    )
                except TelegramError as edit_error:
                    if "message is not modified" not in str(edit_error).lower():
                        msg = await bot.send_message(chat_id=chat_id, text=update_text, parse_mode='Markdown')
                        user_state['tracking_message_id'] = msg.message_id
            else:
                msg = await bot.send_message(chat_id=chat_id, text=update_text, parse_mode='Markdown')
                user_state['tracking_message_id'] = msg.message_id
        except TelegramError as e:
            bot_logger.error(f"Tracking update failed for {chat_id}: {e}")
    
    save_user_states()

def clear_user_tracking_messages():
    """Clear tracking message IDs for all users"""
    for chat_id in user_states:
        user_states[chat_id]['tracking_message_id'] = None
    save_user_states()

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

async def send_startup_notification(bot):
    """Kirim notifikasi ke semua subscriber saat bot restart"""
    if not subscribers:
        bot_logger.info("📭 Tidak ada subscriber untuk dinotifikasi saat startup")
        return
    
    now = datetime.datetime.now(wib_tz)
    
    for chat_id in subscribers.copy():
        user_state = get_user_state(chat_id)
        active_trade = user_state.get('active_trade', {})
        
        startup_text = (
            f"🚀 *BOT AKTIF KEMBALI!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 _{now.strftime('%d/%m/%Y %H:%M:%S WIB')}_\n\n"
            f"🔄 Bot telah restart dan siap beroperasi!\n\n"
            f"🔍 *Status:* Otomatis mencari sinyal...\n"
            f"📡 *Data:* Deriv WebSocket\n"
            f"⏱️ *Mode:* 24 Jam Non-Stop\n\n"
        )
        
        if active_trade:
            direction = active_trade.get('direction', 'N/A')
            entry = active_trade.get('entry_price', 0)
            startup_text += (
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"⚠️ *Trade Aktif Anda:*\n"
                f"{'📈' if direction == 'BUY' else '📉'} {direction} @ ${entry:.3f}\n"
                f"📊 Tracking dilanjutkan otomatis\n\n"
            )
        else:
            startup_text += (
                f"💡 Anda tidak perlu klik apa-apa.\n"
                f"📬 Sinyal akan dikirim otomatis!\n\n"
            )
        
        startup_text += f"👥 Total Subscriber Aktif: *{len(subscribers)}*"
        
        try:
            await bot.send_message(chat_id=chat_id, text=startup_text, parse_mode='Markdown')
            bot_logger.info(f"✅ Notifikasi startup terkirim ke {chat_id}")
        except TelegramError as e:
            bot_logger.error(f"❌ Gagal kirim notifikasi startup ke {chat_id}: {e}")
            if "blocked" in str(e).lower() or "not found" in str(e).lower():
                subscribers.discard(chat_id)
                save_subscribers()

async def health_handler(request):
    """HTTP health check endpoint for Koyeb keep-alive"""
    return web.Response(text="OK", status=200)

async def start_health_server():
    """Start HTTP health check server for Koyeb"""
    app = web.Application()
    app.router.add_get('/', health_handler)
    app.router.add_get('/health', health_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    bot_logger.info(f"🌐 Health server started on port {PORT}")
    return runner

async def self_ping_loop():
    """Periodically ping self to prevent idle timeout on Koyeb"""
    await asyncio.sleep(60)
    
    while True:
        try:
            async with ClientSession() as session:
                async with session.get(f"http://localhost:{PORT}/health", timeout=10) as resp:
                    if resp.status == 200:
                        bot_logger.debug("🔄 Self-ping OK")
        except Exception as e:
            bot_logger.debug(f"Self-ping error (normal if local): {e}")
        
        await asyncio.sleep(300)

async def signal_engine_loop(bot):
    global current_signal, deriv_ws, gold_symbol
    
    bot_logger.info("=" * 50)
    bot_logger.info("🚀 Bot Sinyal V1.2 (Public Edition) dimulai!")
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
    
    await send_startup_notification(bot)
    
    bot_logger.info("🔍 Mesin sinyal dimulai - Mencari sinyal 24 jam...")
    
    while True:
        try:
            has_active_trades = any(get_user_state(cid).get('active_trade') for cid in subscribers)
            status_str = '🎯 Melacak' if (current_signal or has_active_trades) else '🔍 Mencari'
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
            
            if current_signal:
                bot_logger.info(f"🎯 Mode Pelacakan (Trade {current_signal['direction']})")
                trade_closed = False
                
                for i in range(6):
                    current_price = await get_realtime_price()
                    
                    if current_price is None:
                        await asyncio.sleep(8)
                        continue
                    
                    bot_logger.info(
                        f"📊 Melacak... Harga: {current_price:.3f} | "
                        f"TP2: {current_signal['tp2_level']:.3f} | "
                        f"SL: {current_signal['sl_level']:.3f}"
                    )
                    
                    if i == 0 or i == 3:
                        await send_tracking_update(bot, current_price, current_signal)
                        await asyncio.sleep(8)
                    else:
                        await asyncio.sleep(8)
                    
                    result_info = {}
                    trade_status = current_signal.get('status', 'active')
                    
                    if trade_status == 'active':
                        if current_signal['direction'] == 'BUY' and current_price <= current_signal['sl_level']:
                            result_info = {'type': 'LOSS'}
                        elif current_signal['direction'] == 'SELL' and current_price >= current_signal['sl_level']:
                            result_info = {'type': 'LOSS'}
                        elif current_signal['direction'] == 'BUY' and current_price >= current_signal['tp1_level']:
                            result_info = {'type': 'TP1_HIT'}
                        elif current_signal['direction'] == 'SELL' and current_price <= current_signal['tp1_level']:
                            result_info = {'type': 'TP1_HIT'}
                    
                    elif trade_status == 'tp1_hit':
                        entry = current_signal['entry_price']
                        tp2 = current_signal['tp2_level']
                        current_sl = current_signal['sl_level']
                        
                        if current_signal['direction'] == 'BUY':
                            profit_pips = (current_price - entry) * 10
                            if profit_pips >= 5:
                                new_sl = entry + (current_price - entry) * 0.5
                                if new_sl > current_sl:
                                    current_signal['sl_level'] = new_sl
                                    for cid in subscribers:
                                        us = get_user_state(cid)
                                        if us.get('active_trade'):
                                            us['active_trade']['sl_level'] = new_sl
                                    save_user_states()
                                    bot_logger.info(f"🔄 Trailing Stop: SL dipindah ke ${new_sl:.3f}")
                            
                            if current_price <= current_signal['sl_level']:
                                if current_signal['sl_level'] > entry:
                                    result_info = {'type': 'WIN'}
                                else:
                                    result_info = {'type': 'BREAK_EVEN'}
                            elif current_price >= tp2:
                                result_info = {'type': 'WIN'}
                        else:
                            profit_pips = (entry - current_price) * 10
                            if profit_pips >= 5:
                                new_sl = entry - (entry - current_price) * 0.5
                                if new_sl < current_sl:
                                    current_signal['sl_level'] = new_sl
                                    for cid in subscribers:
                                        us = get_user_state(cid)
                                        if us.get('active_trade'):
                                            us['active_trade']['sl_level'] = new_sl
                                    save_user_states()
                                    bot_logger.info(f"🔄 Trailing Stop: SL dipindah ke ${new_sl:.3f}")
                            
                            if current_price >= current_signal['sl_level']:
                                if current_signal['sl_level'] < entry:
                                    result_info = {'type': 'WIN'}
                                else:
                                    result_info = {'type': 'BREAK_EVEN'}
                            elif current_price <= tp2:
                                result_info = {'type': 'WIN'}
                    
                    if result_info.get('type') == 'TP1_HIT':
                        current_signal['status'] = 'tp1_hit'
                        current_signal['sl_level'] = current_signal['entry_price']
                        
                        for cid in subscribers:
                            us = get_user_state(cid)
                            if us.get('active_trade'):
                                us['active_trade']['status'] = 'tp1_hit'
                                us['active_trade']['sl_level'] = current_signal['entry_price']
                        save_user_states()
                        
                        tp1_text = (
                            f"🎯 *TP1 TERCAPAI!*\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"📍 Posisi: *{current_signal['direction']}* @ ${current_signal['entry_price']:.3f}\n\n"
                            f"🛡️ *AKSI: SL dipindah ke Entry!*\n\n"
                            f"💡 Trade sekarang dalam mode Break Even\n"
                            f"🎯 Target selanjutnya: TP2"
                        )
                        await send_to_all_subscribers(bot, tp1_text)
                    
                    elif result_info.get('type') in ['WIN', 'LOSS', 'BREAK_EVEN']:
                        result_emoji = "❓"
                        result_text = "UNKNOWN"
                        if result_info['type'] == 'WIN':
                            result_emoji = "🏆"
                            result_text = "MENANG - TP2 TERCAPAI!"
                        elif result_info['type'] == 'LOSS':
                            result_emoji = "❌"
                            result_text = "KALAH - SL TERKENA"
                        elif result_info['type'] == 'BREAK_EVEN':
                            result_emoji = "⚖️"
                            result_text = "BREAK EVEN"
                        
                        for cid in subscribers:
                            us = get_user_state(cid)
                            if us.get('active_trade'):
                                if result_info['type'] == 'WIN':
                                    us['win_count'] += 1
                                elif result_info['type'] == 'LOSS':
                                    us['loss_count'] += 1
                                elif result_info['type'] == 'BREAK_EVEN':
                                    us['be_count'] += 1
                                us['active_trade'] = {}
                                us['tracking_message_id'] = None
                        save_user_states()
                        
                        closing_df = await get_historical_data()
                        if closing_df is not None:
                            duration = round(
                                (datetime.datetime.now(datetime.timezone.utc) - current_signal['start_time_utc']).total_seconds() / 60,
                                1
                            )
                            final_title = f"{result_emoji} {result_text}"
                            
                            result_caption = (
                                f"{result_emoji} *{result_text}*\n"
                                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                                f"⏱️ Durasi: *{duration} menit*\n\n"
                                f"📊 Gunakan /stats untuk melihat statistik Anda\n\n"
                                f"🔍 Bot kembali mencari sinyal..."
                            )
                            if await generate_chart(closing_df, current_signal, final_title):
                                await send_photo(bot, result_caption)
                        
                        if last_signal_info:
                            last_signal_info['status'] = result_text
                        current_signal = {}
                        trade_closed = True
                        clear_user_tracking_messages()
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
                adx_col = f'ADX_{ADX_FILTER_PERIOD}'
                ema_col = f'EMA_{MA_SHORT_PERIOD}'
                rsi_col = f'RSI_{RSI_PERIOD}'
                atr_col = f'ATRr_{ATR_PERIOD}'
                
                required_cols = [stoch_k_col, stoch_d_col, adx_col, ema_col, rsi_col, atr_col]
                if any(pd.isna(latest.get(col)) or pd.isna(previous.get(col)) for col in required_cols[:2]):
                    bot_logger.warning("⚠️ Indicator NaN detected, waiting for more data...")
                    await asyncio.sleep(ANALYSIS_INTERVAL)
                    continue
                
                is_buy = (previous[stoch_k_col] < previous[stoch_d_col] and latest[stoch_k_col] > latest[stoch_d_col])
                is_sell = (previous[stoch_k_col] > previous[stoch_d_col] and latest[stoch_k_col] < latest[stoch_d_col])
                
                adx_value = latest[adx_col]
                ma_value = latest[ema_col]
                rsi_value = latest[rsi_col]
                
                if pd.isna(adx_value) or pd.isna(ma_value) or pd.isna(rsi_value):
                    bot_logger.warning("⚠️ ADX/EMA/RSI NaN detected, skipping...")
                    await asyncio.sleep(ANALYSIS_INTERVAL)
                    continue
                
                bot_logger.info(f"📊 Data Sinyal: StochBuy={is_buy}, StochSell={is_sell}, ADX={adx_value:.2f}, EMA={ma_value:.2f}, RSI={rsi_value:.2f}")
                
                final_signal = None
                if adx_value >= ADX_FILTER_THRESHOLD:
                    if is_buy and latest_close > ma_value and rsi_value < RSI_OVERBOUGHT:
                        final_signal = 'BUY'
                    elif is_sell and latest_close < ma_value and rsi_value > RSI_OVERSOLD:
                        final_signal = 'SELL'
                
                if final_signal:
                    bot_logger.info(f"🎯 Sinyal {final_signal} valid ditemukan!")
                    
                    latest_atr = latest[atr_col]
                    if pd.isna(latest_atr) or latest_atr <= 0:
                        bot_logger.warning("⚠️ ATR invalid, skipping signal...")
                        await asyncio.sleep(ANALYSIS_INTERVAL)
                        continue
                    
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
                        f"📡 Tracking aktif hingga TP/SL tercapai"
                    )
                    
                    if await generate_chart(df, temp_trade_info, title):
                        if await send_photo(bot, caption):
                            current_signal = temp_trade_info
                            
                            for cid in subscribers:
                                us = get_user_state(cid)
                                us['active_trade'] = temp_trade_info.copy()
                                us['tracking_message_id'] = None
                            save_user_states()
                            
                            last_signal_info.clear()
                            last_signal_info.update({
                                'direction': final_signal,
                                'entry_price': latest_close,
                                'tp1_level': tp1,
                                'tp2_level': tp2,
                                'sl_level': sl,
                                'time': start_time_utc.astimezone(wib_tz).strftime('%H:%M:%S WIB'),
                                'status': 'AKTIF'
                            })
                            clear_user_tracking_messages()
                            rt_price = await get_realtime_price()
                            if rt_price:
                                await send_tracking_update(bot, rt_price, current_signal)
                            bot_logger.info("✅ Sinyal berhasil dikirim! Mode pelacakan aktif.")
                else:
                    bot_logger.info("🔍 Tidak ada sinyal valid saat ini. Terus mencari...")
            
            if not current_signal:
                wait_time = ANALYSIS_INTERVAL + random.randint(-ANALYSIS_JITTER, ANALYSIS_JITTER)
                bot_logger.info(f"⏳ Menunggu {wait_time} detik sebelum analisis berikutnya...")
                await asyncio.sleep(wait_time)
        
        except asyncio.TimeoutError:
            bot_logger.error("⚠️ TIMEOUT: Proses terlalu lama")
            await asyncio.sleep(ANALYSIS_INTERVAL)
        except Exception as e:
            bot_logger.critical(f"❌ Error kritis: {e}")
            await asyncio.sleep(ANALYSIS_INTERVAL)

async def main():
    if 'YOUR_BOT_TOKEN' in TELEGRAM_BOT_TOKEN:
        bot_logger.critical("❌ Harap set TELEGRAM_BOT_TOKEN di environment variables!")
        bot_logger.info("💡 Export variable: TELEGRAM_BOT_TOKEN")
        return
    
    load_subscribers()
    load_user_states()
    
    health_runner = await start_health_server()
    
    asyncio.create_task(self_ping_loop())
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("subscribe", subscribe))
    application.add_handler(CommandHandler("unsubscribe", unsubscribe))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("riset", riset))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("dashboard", dashboard))
    application.add_handler(CommandHandler("signal", signal))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    async with application:
        await application.initialize()
        await application.start()
        if application.updater:
            await application.updater.start_polling()
        
        bot_logger.info("🚀 Bot dimulai! Otomatis mencari sinyal 24 jam...")
        bot_logger.info(f"🌐 Health server aktif di port {PORT}")
        await signal_engine_loop(application.bot)
        
        if application.updater:
            await application.updater.stop()
        await application.stop()
        await health_runner.cleanup()

if __name__ == '__main__':
    print("""
🏆 XAU/USD Signal Bot V1.2 - Public Edition
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 Menggunakan Deriv WebSocket
🔄 Mode: 24 Jam Non-Stop
📡 Tracking: Aktif saat ada posisi
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        bot_logger.info("👋 Bot dihentikan oleh user.")
    except Exception as e:
        bot_logger.critical(f"❌ Error tak terduga: {e}")

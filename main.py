import asyncio
import datetime
import os
import json
import logging
import pandas as pd
import pandas_ta as ta
import pytz
import mplfinance as mpf

from telegram import Bot
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler
from deriv_ws import DerivWebSocket, find_gold_symbol

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')
TARGET_CHAT_ID = os.environ.get('TARGET_CHAT_ID', 'YOUR_CHAT_ID')

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

CHART_FILENAME = 'chart_v31.png'
STATE_FILENAME = 'bot_state_v31.json'
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

async def start(update, context):
    if str(update.message.chat_id) == TARGET_CHAT_ID:
        await update.message.reply_text(
            "Bot Sinyal V31 (Deriv Edition) aktif!\n\n"
            "Data dari Deriv WebSocket (tanpa API key)\n"
            "/stats untuk melihat performa\n"
            "/info untuk info sistem",
            parse_mode='Markdown'
        )

async def stats(update, context):
    if str(update.message.chat_id) == TARGET_CHAT_ID:
        total = win_count + loss_count + be_count
        win_rate = (win_count / (win_count + loss_count)) * 100 if (win_count + loss_count) > 0 else 0.0
        await update.message.reply_text(
            f"*Statistik Keseluruhan*\n\n"
            f"Total Trade: *{total}*\n"
            f"Menang: *{win_count}*\n"
            f"Kalah: *{loss_count}*\n"
            f"BE: *{be_count}*\n\n"
            f"Win Rate (W vs L): *{win_rate:.2f}%*",
            parse_mode='Markdown'
        )

async def info(update, context):
    if str(update.message.chat_id) == TARGET_CHAT_ID:
        status = "Terhubung" if (deriv_ws and deriv_ws.connected) else "Terputus"
        current_price = deriv_ws.get_current_price() if deriv_ws else None
        price_str = f"${current_price:.3f}" if current_price else "N/A"
        
        await update.message.reply_text(
            f"*Info Sistem*\n\n"
            f"WebSocket: {status}\n"
            f"Symbol: {gold_symbol or 'N/A'}\n"
            f"Harga Terakhir: {price_str}\n"
            f"Data Source: Deriv (No API Key)\n"
            f"Interval: 1 menit",
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

async def send_photo(bot, caption_text):
    try:
        with open(CHART_FILENAME, 'rb') as photo_file:
            await bot.send_photo(chat_id=TARGET_CHAT_ID, photo=photo_file, caption=caption_text, parse_mode='Markdown')
        if os.path.exists(CHART_FILENAME):
            os.remove(CHART_FILENAME)
        return True
    except Exception as e:
        bot_logger.error(f"TELEGRAM-ERROR: Gagal mengirim foto: {e}")
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
    bot_logger.info("Bot Sinyal V31 (Deriv Edition) dimulai!")
    bot_logger.info("Sumber Data: Deriv WebSocket (Tanpa API Key)")
    bot_logger.info("=" * 50)
    
    bot_logger.info("Mencari symbol XAU/USD di Deriv...")
    gold_symbols = await find_gold_symbol()
    
    if gold_symbols:
        gold_symbol = gold_symbols[0].get('symbol')
        display_name = gold_symbols[0].get('display_name', gold_symbol)
        bot_logger.info(f"Symbol ditemukan: {gold_symbol} ({display_name})")
    else:
        bot_logger.warning("Symbol XAU/USD tidak ditemukan, menggunakan frxXAUUSD sebagai default")
        gold_symbol = "frxXAUUSD"
    
    deriv_ws = DerivWebSocket()
    if not await deriv_ws.connect():
        bot_logger.critical("Gagal connect ke Deriv WebSocket!")
        return
    
    await deriv_ws.subscribe_ticks(gold_symbol)
    
    listen_task = asyncio.create_task(deriv_ws.listen())
    
    async def keep_alive():
        while True:
            await asyncio.sleep(30)
            if deriv_ws and deriv_ws.connected:
                await deriv_ws.send_ping()
    
    keepalive_task = asyncio.create_task(keep_alive())
    
    bot_logger.info("Mesin sinyal dimulai...")
    
    while True:
        try:
            status_str = 'Melacak' if active_trade else 'Mencari'
            bot_logger.info(f"--- Siklus Baru | Status: {status_str} ---")
            
            if not deriv_ws.connected:
                bot_logger.warning("WebSocket terputus, mencoba reconnect...")
                if await deriv_ws.connect():
                    await deriv_ws.subscribe_ticks(gold_symbol)
                    listen_task = asyncio.create_task(deriv_ws.listen())
                else:
                    await asyncio.sleep(30)
                    continue
            
            df = await get_historical_data()
            
            if df is None:
                bot_logger.warning("Data tidak tersedia dari Deriv")
                await asyncio.sleep(60)
                continue
            
            if active_trade:
                bot_logger.info(f"Mode Pelacakan (Trade {active_trade['direction']})")
                trade_closed = False
                
                for i in range(4):
                    await asyncio.sleep(15)
                    current_price = await get_realtime_price()
                    
                    if current_price is None:
                        continue
                    
                    bot_logger.info(
                        f"Melacak... Harga: {current_price:.3f} | "
                        f"TP2: {active_trade['tp2_level']:.3f} | "
                        f"SL: {active_trade['sl_level']:.3f}"
                    )
                    
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
                        await bot.send_message(
                            chat_id=TARGET_CHAT_ID,
                            text=(
                                f"*TP1 TERCAPAI!*\n\n"
                                f"*Posisi:* {active_trade['direction']} @ ${active_trade['entry_price']:.3f}\n"
                                f"*AKSI: Pindahkan SL ke harga entry!*"
                            ),
                            parse_mode='Markdown'
                        )
                    
                    elif result_info.get('type') in ['WIN', 'LOSS', 'BREAK_EVEN']:
                        if result_info['type'] == 'WIN':
                            win_count += 1
                        elif result_info['type'] == 'LOSS':
                            loss_count += 1
                        elif result_info['type'] == 'BREAK_EVEN':
                            be_count += 1
                        
                        save_state()
                        
                        closing_df = await get_historical_data()
                        if closing_df is not None:
                            duration = round(
                                (datetime.datetime.now(datetime.timezone.utc) - active_trade['start_time_utc']).total_seconds() / 60,
                                1
                            )
                            final_title = f"[{result_info['type']}] - Trade Ditutup!"
                            result_caption = (
                                f"*{final_title}*\n\n"
                                f"Durasi: *{duration} menit*\n"
                                f"Statistik: W:{win_count} L:{loss_count} BE:{be_count}"
                            )
                            if await generate_chart(closing_df, active_trade, final_title):
                                await send_photo(bot, result_caption)
                        
                        active_trade = {}
                        trade_closed = True
                        break
                
                if trade_closed:
                    continue
            
            else:
                bot_logger.info("Menganalisis data dari Deriv...")
                df = calculate_indicators(df)
                latest = df.iloc[-2]
                previous = df.iloc[-3]
                latest_close = latest['Close']
                
                bot_logger.info(f"Data Terakhir XAU/USD: Close = {latest_close:.3f}")
                
                stoch_k_col = f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'
                stoch_d_col = f'STOCHd_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'
                
                is_buy = (previous[stoch_k_col] < previous[stoch_d_col] and latest[stoch_k_col] > latest[stoch_d_col])
                is_sell = (previous[stoch_k_col] > previous[stoch_d_col] and latest[stoch_k_col] < latest[stoch_d_col])
                
                adx_value = latest[f'ADX_{ADX_FILTER_PERIOD}']
                ma_value = latest[f'EMA_{MA_SHORT_PERIOD}']
                
                bot_logger.info(f"Data Sinyal: StochBuy={is_buy}, StochSell={is_sell}, ADX={adx_value:.2f}, EMA={ma_value:.2f}")
                
                final_signal = None
                if adx_value >= ADX_FILTER_THRESHOLD:
                    if is_buy and latest_close > ma_value:
                        final_signal = 'BUY'
                    elif is_sell and latest_close < ma_value:
                        final_signal = 'SELL'
                
                if final_signal:
                    bot_logger.info(f"Sinyal {final_signal} valid ditemukan!")
                    
                    latest_atr = latest[f'ATRr_{ATR_PERIOD}']
                    
                    if final_signal == "BUY":
                        sl = latest_close - (latest_atr * ATR_MULTIPLIER)
                        risk = abs(latest_close - sl)
                        tp1 = latest_close + (risk * RR_TP1)
                        tp2 = latest_close + (risk * RR_TP2)
                    else:
                        sl = latest_close + (latest_atr * ATR_MULTIPLIER)
                        risk = abs(latest_close - sl)
                        tp1 = latest_close - (risk * RR_TP1)
                        tp2 = latest_close - (risk * RR_TP2)
                    
                    title = f"SINYAL {final_signal} V31"
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
                        f"*{title}*\n"
                        f"_Data: Deriv WebSocket_\n\n"
                        f"Waktu: *{start_time_utc.astimezone(wib_tz).strftime('%H:%M:%S WIB')}*\n"
                        f"Harga Entry: *${latest_close:.3f}*\n\n"
                        f"--- RENCANA EKSEKUSI ---\n"
                        f"Lot: {LOT_SIZE} | Estimasi Risiko: ~${RISK_PER_TRADE_USD:.2f}\n\n"
                        f"--- TARGET & PROTEKSI ---\n"
                        f"TP 1: *${tp1:.3f}*\n"
                        f"TP 2: *${tp2:.3f}*\n"
                        f"SL: *${sl:.3f}*"
                    )
                    
                    if await generate_chart(df, temp_trade_info, title):
                        if await send_photo(bot, caption):
                            active_trade = temp_trade_info
                            bot_logger.info("Sinyal berhasil dikirim! Mengaktifkan mode pelacakan.")
                else:
                    bot_logger.info("Tidak ada sinyal yang valid saat ini.")
            
            if not active_trade:
                bot_logger.info("Menunggu 60 detik...")
                await asyncio.sleep(60)
        
        except asyncio.TimeoutError:
            bot_logger.error("TIMEOUT: Proses terlalu lama")
            await asyncio.sleep(60)
        except Exception as e:
            bot_logger.critical(f"Error kritis: {e}")
            await asyncio.sleep(60)

async def main():
    if 'YOUR_BOT_TOKEN' in TELEGRAM_BOT_TOKEN or 'YOUR_CHAT_ID' in TARGET_CHAT_ID:
        bot_logger.critical("Harap set TELEGRAM_BOT_TOKEN dan TARGET_CHAT_ID di environment variables!")
        bot_logger.info("Export variables: TELEGRAM_BOT_TOKEN, TARGET_CHAT_ID")
        return
    
    load_state()
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("info", info))
    
    async with application:
        await application.initialize()
        await application.start()
        if application.updater:
            await application.updater.start_polling()
        await signal_engine_loop(application.bot)
        if application.updater:
            await application.updater.stop()
        await application.stop()

if __name__ == '__main__':
    print("""
XAU/USD Signal Bot V31 - Deriv Edition
Tanpa API Key - Menggunakan Deriv WebSocket
    """)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        bot_logger.info("Bot dihentikan oleh user.")
    except Exception as e:
        bot_logger.critical(f"Error tak terduga: {e}")

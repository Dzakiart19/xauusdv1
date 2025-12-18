import requests
import pandas as pd
import pandas_ta as ta
import time
import asyncio
import datetime
import os
import json
import logging

from telegram import Bot
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler
import pytz
import mplfinance as mpf

# --- PENGATURAN V30 (THE FINAL VERSION) ---
TELEGRAM_BOT_TOKEN = '8083284621:AAGANGmpHZ2op0zbXt-uUb-t9dyUBYi4Ooc'
TWELVE_DATA_API_KEY = 'e2cacd5d5f6142869584835dae4312f3'
TARGET_CHAT_ID = '7390867903' 

# --- PENGATURAN STRATEGI AGRESIF ---
STOCH_K = 8; STOCH_D = 3; STOCH_SMOOTH = 3
ATR_PERIOD = 14; ATR_MULTIPLIER = 1.8; RR_TP1 = 1.0; RR_TP2 = 1.5
ADX_FILTER_PERIOD = 14; ADX_FILTER_THRESHOLD = 15
MA_SHORT_PERIOD = 21
LOT_SIZE = 0.01; RISK_PER_TRADE_USD = 2.00

# --- Database & Variabel Global ---
active_trade = {}
win_count = 0; loss_count = 0; be_count = 0
CHART_FILENAME = 'chart_v30.png'
STATE_FILENAME = 'bot_state_v30.json'
LOG_FILENAME = 'bot_v30.log'
wib_tz = pytz.timezone('Asia/Jakarta')

# --- Konfigurasi Logging (Log Bersih) ---
class NoHttpxFilter(logging.Filter):
    def filter(self, record):
        return 'httpx' not in record.name and 'HTTP Request' not in record.getMessage()

bot_logger = logging.getLogger("BotV30")
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

# --- Fungsi State & Perintah Pengguna ---
def save_state():
    state = {'win_count': win_count, 'loss_count': loss_count, 'be_count': be_count}
    with open(STATE_FILENAME, 'w') as f: json.dump(state, f, indent=4)
def load_state():
    global win_count, loss_count, be_count
    try:
        if os.path.exists(STATE_FILENAME):
            with open(STATE_FILENAME, 'r') as f: state = json.load(f)
            win_count = state.get('win_count', 0); loss_count = state.get('loss_count', 0); be_count = state.get('be_count', 0)
            bot_logger.info(f"State dimuat: W:{win_count} L:{loss_count} BE:{be_count}")
    except Exception as e: bot_logger.error(f"Gagal memuat state: {e}")
async def start(update, context):
    if str(update.message.chat_id) == TARGET_CHAT_ID: await update.message.reply_text("✅ Bot Sinyal Pribadi V30 aktif! /stats untuk performa.")
async def stats(update, context):
    if str(update.message.chat_id) == TARGET_CHAT_ID:
        total = win_count + loss_count + be_count
        win_rate = (win_count / (win_count + loss_count)) * 100 if (win_count + loss_count) > 0 else 0.0
        await update.message.reply_text(f"📊 *Statistik Keseluruhan* 📊\n\nTotal Trade: *{total}*\n✅ Menang: *{win_count}*\n❌ Kalah: *{loss_count}*\n➖ BE: *{be_count}*\n\nWin Rate (W vs L): *{win_rate:.2f}%*", parse_mode='Markdown')

# --- FUNGSI GET DATA (Anti-Stuck) ---
def sync_get_historical_data():
    try:
        response = requests.get(f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=1min&apikey={TWELVE_DATA_API_KEY}&outputsize=200", timeout=15)
        response.raise_for_status(); data = response.json()
        if data.get('status') == 'error' or 'values' not in data or not data['values']: return None
        df = pd.DataFrame(data['values']); df.rename(columns={'datetime': 'date', 'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close'}, inplace=True)
        df['date'] = pd.to_datetime(df['date']); df.set_index('date', inplace=True)
        df[['Open', 'High', 'Low', 'Close']] = df[['Open', 'High', 'Low', 'Close']].apply(pd.to_numeric)
        return df.iloc[::-1]
    except Exception as e: bot_logger.error(f"DATA-ERROR: {e}"); return None
async def get_realtime_price():
    try:
        response = requests.get(f"https://api.twelvedata.com/price?symbol=XAU/USD&apikey={TWELVE_DATA_API_KEY}&dp=3", timeout=10)
        response.raise_for_status(); data = response.json()
        return float(data['price'])
    except: return None

# --- Fungsi Inti & Charting ---
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
        if os.path.exists(CHART_FILENAME): os.remove(CHART_FILENAME)
        return True
    except Exception as e: bot_logger.error(f"TELEGRAM-ERROR: Gagal mengirim foto: {e}"); return False
async def generate_chart(df, trade_info, title):
    try:
        mpf.plot(df.tail(60), type='candle', style='yahoo', title=title, ylabel='Harga ($)', volume=False, hlines=dict(hlines=[trade_info.get('sl_level'), trade_info.get('tp1_level'), trade_info.get('tp2_level')], colors=['r', 'orange', 'g'], linestyle='--'), savefig=CHART_FILENAME)
        return True
    except Exception as e: bot_logger.error(f"CHART-ERROR: {e}"); return False

# --- Mesin Sinyal Utama V30 ---
async def signal_engine_loop(bot):
    global active_trade, win_count, loss_count, be_count
    bot_logger.info("Mesin sinyal (The Final Version) dimulai...")
    while True:
        try:
            bot_logger.info(f"--- Siklus Baru | Status: {'Melacak' if active_trade else 'Mencari'} ---")
            df = None
            try:
                df = await asyncio.wait_for(asyncio.to_thread(sync_get_historical_data), timeout=20.0)
            except asyncio.TimeoutError:
                bot_logger.error("GAGAL TOTAL: Proses ambil data lebih dari 20 detik.")
            
            if df is None:
                bot_logger.warning("Data tidak tersedia.")
            elif active_trade:
                bot_logger.info(f"Mode Pelacakan Cepat (Trade {active_trade['direction']})")
                trade_closed = False
                for i in range(4):
                    await asyncio.sleep(15)
                    current_price = await get_realtime_price()
                    if current_price is None: continue
                    bot_logger.info(f"Melacak... Harga: {current_price:.3f} | TP2: {active_trade['tp2_level']:.3f} | SL: {active_trade['sl_level']:.3f}")
                    result_info = {}
                    trade_status = active_trade['status']
                    if trade_status == 'active':
                        if active_trade['direction'] == 'BUY' and current_price <= active_trade['sl_level']: result_info = {'type': 'LOSS'}
                        elif active_trade['direction'] == 'SELL' and current_price >= active_trade['sl_level']: result_info = {'type': 'LOSS'}
                        elif active_trade['direction'] == 'BUY' and current_price >= active_trade['tp1_level']: result_info = {'type': 'TP1_HIT'}
                        elif active_trade['direction'] == 'SELL' and current_price <= active_trade['tp1_level']: result_info = {'type': 'TP1_HIT'}
                    elif trade_status == 'tp1_hit':
                        if active_trade['direction'] == 'BUY' and current_price <= active_trade['entry_price']: result_info = {'type': 'BREAK_EVEN'}
                        elif active_trade['direction'] == 'SELL' and current_price >= active_trade['tp2_level']: result_info = {'type': 'WIN'}
                    
                    if result_info.get('type') == 'TP1_HIT':
                        active_trade['status'] = 'tp1_hit'; active_trade['sl_level'] = active_trade['entry_price']
                        await bot.send_message(chat_id=TARGET_CHAT_ID, text=f"🔔 *TP1 TERCAPAI!* 🔔\n\n*Posisi:* {active_trade['direction']} @ ${active_trade['entry_price']:.3f}\n*AKSI: Pindahkan SL ke harga entry!*", parse_mode='Markdown')
                    elif result_info.get('type') in ['WIN', 'LOSS', 'BREAK_EVEN']:
                        if result_info['type'] == 'WIN': win_count += 1
                        elif result_info['type'] == 'LOSS': loss_count += 1
                        # --- INI BARIS YANG DIPERBAIKI ---
                        elif result_info['type'] == 'BREAK_EVEN': be_count += 1
                        # -----------------------------------
                        save_state()
                        
                        closing_df = await asyncio.wait_for(asyncio.to_thread(sync_get_historical_data), timeout=20.0)
                        if closing_df is not None:
                            duration = round((datetime.datetime.now(datetime.UTC) - active_trade['start_time_utc']).total_seconds() / 60, 1)
                            final_title = f"[{result_info['type']}] - Trade Ditutup!"
                            result_caption = (f"*{final_title}*\n\nDurasi: *{duration} menit*\nStatistik: W:{win_count} L:{loss_count} BE:{be_count}")
                            if await generate_chart(closing_df, active_trade, final_title):
                                await send_photo(bot, result_caption)
                        
                        active_trade = {}; trade_closed = True; break
                if trade_closed: continue
            else:
                bot_logger.info("Menganalisis data...")
                df = calculate_indicators(df)
                latest = df.iloc[-2]; previous = df.iloc[-3]
                latest_close = latest['Close']
                bot_logger.info(f"Data Terakhir XAU/USD: Close = {latest_close:.3f}")
                
                is_buy = (previous[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] < previous[f'STOCHd_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] and latest[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] > latest[f'STOCHd_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'])
                is_sell = (previous[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] > previous[f'STOCHd_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] and latest[f'STOCHk_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'] < latest[f'STOCHd_{STOCH_K}_{STOCH_D}_{STOCH_SMOOTH}'])
                adx_value = latest[f'ADX_{ADX_FILTER_PERIOD}']; ma_value = latest[f'EMA_{MA_SHORT_PERIOD}']
                bot_logger.info(f"Data Sinyal: StochBuy={is_buy}, StochSell={is_sell}, ADX={adx_value:.2f}, EMA={ma_value:.2f}")
                
                final_signal = None
                if adx_value >= ADX_FILTER_THRESHOLD:
                    if is_buy and latest_close > ma_value: final_signal = 'BUY'
                    elif is_sell and latest_close < ma_value: final_signal = 'SELL'
                
                if final_signal:
                    bot_logger.info(f"Sinyal {final_signal} valid ditemukan.")
                    latest_atr = latest[f'ATRr_{ATR_PERIOD}']
                    sl = latest_close - (latest_atr * ATR_MULTIPLIER) if final_signal == "BUY" else latest_close + (latest_atr * ATR_MULTIPLIER)
                    risk = abs(latest_close - sl)
                    tp1 = latest_close + (risk * RR_TP1) if final_signal == "BUY" else latest_close - (risk * RR_TP1)
                    tp2 = latest_close + (risk * RR_TP2) if final_signal == "BUY" else latest_close - (risk * RR_TP2)
                    title = f"SINYAL {final_signal} V30"; start_time_utc = datetime.datetime.now(datetime.UTC)
                    temp_trade_info = {"direction": final_signal, "entry_price": latest_close, "tp1_level": tp1, "tp2_level": tp2, "sl_level": sl, "start_time_utc": start_time_utc, "status": "active"}
                    caption = (f"🚀 *{title}* 🚀\n\nWaktu: *{start_time_utc.astimezone(wib_tz).strftime('%H:%M:%S WIB')}*\nHarga Entry: *${latest_close:.3f}*\n\n"
                               f"--- RENCANA EKSEKUSI ---\n📈 Lot: 0.01 | 💰 Estimasi Risiko: ~$2.00\n\n"
                               f"--- TARGET & PROTEKSI ---\n🎯 TP 1: *${tp1:.3f}*\n🎯 TP 2: *${tp2:.3f}*\n⛔ SL: *${sl:.3f}*")
                    if await generate_chart(df, temp_trade_info, title):
                        if await send_photo(bot, caption):
                            active_trade = temp_trade_info
                            bot_logger.info("Sinyal berhasil dikirim! Mengaktifkan mode pelacakan cepat.")
                else:
                    bot_logger.info("Tidak ada sinyal yang valid saat ini.")
            
            if not active_trade:
                bot_logger.info("Menunggu 60 detik...")
                await asyncio.sleep(60)

        except asyncio.TimeoutError:
            bot_logger.error("GAGAL TOTAL: Proses ambil data lebih dari 20 detik.")
            await asyncio.sleep(60)
        except Exception as e:
            bot_logger.critical(f"Terjadi error kritis: {e}")
            await asyncio.sleep(60)

async def main():
    if 'GANTI_DENGAN' in TARGET_CHAT_ID: bot_logger.critical("Harap isi TARGET_CHAT_ID."); return
    load_state()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    async with application:
        await application.initialize(); await application.start()
        await application.updater.start_polling()
        await signal_engine_loop(application.bot)
        await application.updater.stop(); await application.stop()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        bot_logger.info("Bot Final dihentikan.")
    except Exception as e:
        bot_logger.critical(f"Terjadi error tak terduga di luar loop utama: {e}")

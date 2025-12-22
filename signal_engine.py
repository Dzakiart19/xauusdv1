import asyncio
import datetime
import random
import os
import pandas as pd
import logging
from typing import Optional, TYPE_CHECKING

from config import BotConfig
from utils import calculate_indicators, generate_chart, bot_logger
from deriv_ws import DerivWebSocket, find_gold_symbol

if TYPE_CHECKING:
    from telegram_service import TelegramService
    from state_manager import StateManager


class SignalEngine:
    def __init__(self, state_manager: 'StateManager', telegram_service: Optional['TelegramService'] = None):
        self.state_manager = state_manager
        self.telegram_service: Optional['TelegramService'] = telegram_service
        self.deriv_ws: Optional[DerivWebSocket] = None
        self.gold_symbol: str = "frxXAUUSD"
        self.cached_candles_df: Optional[pd.DataFrame] = None
        self.last_candle_fetch: Optional[datetime.datetime] = None
        self.signal_history: list = []
        self.last_signal_time: Optional[datetime.datetime] = None
        self.signal_cooldown_seconds: int = BotConfig.SIGNAL_COOLDOWN_SECONDS
        self.total_signals_generated: int = 0
        self._running: bool = False
        self._shutdown_event: asyncio.Event = asyncio.Event()
    
    def _has_telegram_service(self) -> bool:
        return self.telegram_service is not None
    
    def _can_generate_signal(self) -> bool:
        if self.last_signal_time is None:
            return True
        
        now = datetime.datetime.now(datetime.timezone.utc)
        elapsed = (now - self.last_signal_time).total_seconds()
        return elapsed >= self.signal_cooldown_seconds
    
    def _record_signal(self, signal_info: dict) -> None:
        self.last_signal_time = datetime.datetime.now(datetime.timezone.utc)
        self.total_signals_generated += 1
        
        history_entry = {
            'id': self.total_signals_generated,
            'direction': signal_info.get('direction'),
            'entry_price': signal_info.get('entry_price'),
            'tp1': signal_info.get('tp1_level'),
            'tp2': signal_info.get('tp2_level'),
            'sl': signal_info.get('sl_level'),
            'timestamp': self.last_signal_time.isoformat(),
            'result': 'PENDING'
        }
        
        self.signal_history.append(history_entry)
        if len(self.signal_history) > 100:
            self.signal_history = self.signal_history[-100:]
        
        self.state_manager.add_signal_to_history(signal_info)
        bot_logger.info(f"📝 Signal #{self.total_signals_generated} recorded")
    
    def get_deriv_ws(self) -> Optional[DerivWebSocket]:
        return self.deriv_ws
    
    def get_gold_symbol(self) -> str:
        return self.gold_symbol
    
    async def get_historical_data(self) -> Optional[pd.DataFrame]:
        if not self.deriv_ws or not self.deriv_ws.connected:
            bot_logger.warning("WebSocket not connected, skipping data fetch...")
            return None
        
        try:
            symbol = self.gold_symbol or "frxXAUUSD"
            candles = await self.deriv_ws.get_candles(symbol=symbol, count=200, granularity=60)
            
            if not candles or not isinstance(candles, list):
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
    
    async def get_realtime_price(self) -> Optional[float]:
        if self.deriv_ws and self.deriv_ws.connected:
            return self.deriv_ws.get_current_price()
        return None
    
    async def send_photo(self, bot, caption: str) -> bool:
        if os.path.exists(BotConfig.CHART_FILENAME) and self._has_telegram_service() and self.telegram_service:
            await self.telegram_service.send_to_all_subscribers(bot, caption, BotConfig.CHART_FILENAME)
            try:
                os.remove(BotConfig.CHART_FILENAME)
                bot_logger.info(f"🗑️ Chart deleted: {BotConfig.CHART_FILENAME}")
            except Exception as e:
                bot_logger.warning(f"Failed to delete chart: {e}")
            return True
        return False
    
    async def notify_restart(self, bot) -> None:
        if not self._has_telegram_service() or not self.telegram_service:
            return
        restart_msg = (
            "🔄 *BOT RESTART NOTIFICATION*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Bot telah direstart dan mencari sinyal baru.\n\n"
            "💡 Gunakan /dashboard untuk melihat status terkini."
        )
        await self.telegram_service.send_to_all_subscribers(bot, restart_msg)
        bot_logger.info("Sent restart notification to all subscribers")
    
    def request_shutdown(self) -> None:
        self._running = False
        self._shutdown_event.set()
        bot_logger.info("Shutdown requested for signal engine")
    
    async def run(self, bot) -> None:
        bot_logger.info("🚀 Starting Signal Engine...")
        self._running = True
        self._shutdown_event.clear()
        
        gold_symbols = await find_gold_symbol()
        if gold_symbols:
            for s in gold_symbols:
                if s.get('symbol') == 'frxXAUUSD':
                    self.gold_symbol = 'frxXAUUSD'
                    break
            else:
                self.gold_symbol = gold_symbols[0].get('symbol', 'frxXAUUSD')
        bot_logger.info(f"Using gold symbol: {self.gold_symbol}")
        
        self.deriv_ws = DerivWebSocket()
        
        connected = await self.deriv_ws.connect()
        if not connected:
            bot_logger.critical("Failed to connect to Deriv WebSocket!")
            return
        
        await self.deriv_ws.subscribe_ticks(self.gold_symbol)
        
        listen_task = asyncio.create_task(self.deriv_ws.listen())
        
        await asyncio.sleep(5)
        
        self.state_manager.current_signal = {}
        for chat_id in self.state_manager.subscribers:
            user_state = self.state_manager.get_user_state(chat_id)
            user_state['active_trade'] = {}
            user_state['tracking_message_id'] = None
        self.state_manager.save_user_states()
        bot_logger.info("🔄 Cleared all active trades - searching for fresh signals")
        
        await self.notify_restart(bot)
        
        tracking_counter = 0
        last_market_closed_notify: Optional[datetime.datetime] = None
        last_daily_summary: Optional[datetime.date] = None
        
        while self._running:
            try:
                now = datetime.datetime.now(BotConfig.WIB_TZ)
                if (now.hour == BotConfig.DAILY_SUMMARY_HOUR and 
                    now.minute >= BotConfig.DAILY_SUMMARY_MINUTE and
                    (last_daily_summary is None or last_daily_summary != now.date())):
                    if self._has_telegram_service() and self.telegram_service:
                        await self.telegram_service.send_daily_summary(bot)
                        last_daily_summary = now.date()
                
                market_status = BotConfig.get_market_status()
                if not market_status['is_open']:
                    now_dt = datetime.datetime.now()
                    should_notify = (
                        last_market_closed_notify is None or 
                        (now_dt - last_market_closed_notify).total_seconds() > 3600
                    )
                    
                    if should_notify:
                        bot_logger.info(f"📅 Market tutup: {market_status['message']}")
                        market_msg = (
                            "📅 *MARKET TUTUP (WEEKEND)*\n"
                            "━━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"🕐 {market_status['message']}\n\n"
                            "💡 Bot akan otomatis aktif kembali saat market buka.\n"
                            "📊 Gunakan /dashboard untuk cek status."
                        )
                        if self._has_telegram_service() and self.telegram_service:
                            await self.telegram_service.send_to_all_subscribers(bot, market_msg)
                        last_market_closed_notify = now_dt
                    
                    await asyncio.sleep(BotConfig.MARKET_CHECK_INTERVAL)
                    continue
                
                if not self.deriv_ws.connected:
                    bot_logger.warning("⚠️ WebSocket disconnected, reconnecting...")
                    listen_task.cancel()
                    try:
                        await listen_task
                    except asyncio.CancelledError:
                        pass
                    
                    connected = await self.deriv_ws.connect()
                    if connected:
                        await self.deriv_ws.subscribe_ticks(self.gold_symbol)
                        listen_task = asyncio.create_task(self.deriv_ws.listen())
                        bot_logger.info("✅ Reconnected to WebSocket")
                    else:
                        await asyncio.sleep(10)
                        continue
                
                current_signal = self.state_manager.current_signal
                
                if current_signal:
                    await asyncio.sleep(2)
                    tracking_counter += 1
                    trade_closed = False
                    
                    rt_price = await self.get_realtime_price()
                    if rt_price:
                        direction = current_signal['direction']
                        entry = current_signal['entry_price']
                        tp1 = current_signal['tp1_level']
                        tp2 = current_signal['tp2_level']
                        sl = current_signal['sl_level']
                        trade_status = current_signal.get('status', 'active')
                        
                        if tracking_counter % 15 == 0:
                            bot_logger.info(f"📍 Tracking {direction}: Price=${rt_price:.3f} Entry=${entry:.3f} SL=${sl:.3f}")
                            if self._has_telegram_service() and self.telegram_service:
                                await self.telegram_service.send_tracking_update(bot, rt_price, current_signal)
                        
                        result_info = None
                        
                        if direction == 'BUY':
                            if rt_price >= tp2:
                                result_info = {'type': 'WIN', 'emoji': '🏆', 'text': 'TP2 HIT - FULL WIN!'}
                            elif rt_price >= tp1 and trade_status == 'active':
                                current_signal['status'] = 'tp1_hit'
                                current_signal['sl_level'] = entry
                                for cid in self.state_manager.subscribers:
                                    us = self.state_manager.get_user_state(cid)
                                    if us.get('active_trade'):
                                        us['active_trade']['status'] = 'tp1_hit'
                                        us['active_trade']['sl_level'] = entry
                                self.state_manager.save_user_states()
                                
                                tp1_msg = (
                                    "🎯 *TP1 TERCAPAI!*\n"
                                    "━━━━━━━━━━━━━━━━━━━━━\n\n"
                                    f"💰 Harga: *${rt_price:.3f}*\n"
                                    f"🎯 TP1: ${tp1:.3f}\n\n"
                                    "🛡️ *SL dipindahkan ke Entry (Break Even)*\n"
                                    "🏆 Target selanjutnya: TP2\n\n"
                                    "💡 Profit sebagian sudah aman!"
                                )
                                if self._has_telegram_service() and self.telegram_service:
                                    await self.telegram_service.send_to_all_subscribers(bot, tp1_msg)
                                bot_logger.info(f"✅ TP1 HIT! SL moved to BE. Price: {rt_price:.3f}")
                            
                            elif rt_price <= sl:
                                if trade_status == 'tp1_hit':
                                    result_info = {'type': 'BREAK_EVEN', 'emoji': '⚖️', 'text': 'BREAK EVEN - TP1 Hit, SL at Entry'}
                                else:
                                    result_info = {'type': 'LOSS', 'emoji': '❌', 'text': 'STOP LOSS HIT'}
                        
                        else:
                            if rt_price <= tp2:
                                result_info = {'type': 'WIN', 'emoji': '🏆', 'text': 'TP2 HIT - FULL WIN!'}
                            elif rt_price <= tp1 and trade_status == 'active':
                                current_signal['status'] = 'tp1_hit'
                                current_signal['sl_level'] = entry
                                for cid in self.state_manager.subscribers:
                                    us = self.state_manager.get_user_state(cid)
                                    if us.get('active_trade'):
                                        us['active_trade']['status'] = 'tp1_hit'
                                        us['active_trade']['sl_level'] = entry
                                self.state_manager.save_user_states()
                                
                                tp1_msg = (
                                    "🎯 *TP1 TERCAPAI!*\n"
                                    "━━━━━━━━━━━━━━━━━━━━━\n\n"
                                    f"💰 Harga: *${rt_price:.3f}*\n"
                                    f"🎯 TP1: ${tp1:.3f}\n\n"
                                    "🛡️ *SL dipindahkan ke Entry (Break Even)*\n"
                                    "🏆 Target selanjutnya: TP2\n\n"
                                    "💡 Profit sebagian sudah aman!"
                                )
                                if self._has_telegram_service() and self.telegram_service:
                                    await self.telegram_service.send_to_all_subscribers(bot, tp1_msg)
                                bot_logger.info(f"✅ TP1 HIT! SL moved to BE. Price: {rt_price:.3f}")
                            
                            elif rt_price >= sl:
                                if trade_status == 'tp1_hit':
                                    result_info = {'type': 'BREAK_EVEN', 'emoji': '⚖️', 'text': 'BREAK EVEN - TP1 Hit, SL at Entry'}
                                else:
                                    result_info = {'type': 'LOSS', 'emoji': '❌', 'text': 'STOP LOSS HIT'}
                        
                        trade_closed = False
                        if result_info:
                            result_emoji = result_info['emoji']
                            result_text = result_info['text']
                            
                            self.state_manager.update_trade_result(result_info['type'])
                            self.state_manager.update_last_signal_result(result_info['type'])
                            
                            start_time_utc = current_signal.get('start_time_utc')
                            if start_time_utc:
                                duration = round(
                                    (datetime.datetime.now(datetime.timezone.utc) - start_time_utc).total_seconds() / 60,
                                    1
                                )
                            else:
                                duration = 0
                            
                            result_caption = (
                                f"{result_emoji} *{result_text}*\n"
                                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                                f"💵 Entry: *${entry:.3f}*\n"
                                f"💰 Exit: *${rt_price:.3f}*\n"
                                f"⏱️ Durasi: *{duration} menit*\n\n"
                                f"📊 Gunakan /stats untuk melihat statistik\n"
                                f"🔍 Bot kembali mencari sinyal..."
                            )
                            if self._has_telegram_service() and self.telegram_service:
                                await self.telegram_service.send_to_all_subscribers(bot, result_caption)
                            
                            if self.state_manager.last_signal_info:
                                self.state_manager.last_signal_info['status'] = result_text
                            self.state_manager.clear_current_signal()
                            trade_closed = True
                            self.state_manager.clear_user_tracking_messages()
                    
                    if trade_closed:
                        continue
                
                else:
                    df = await self.get_historical_data()
                    
                    if df is None:
                        await asyncio.sleep(BotConfig.ANALYSIS_INTERVAL)
                        continue
                    
                    bot_logger.info("🔍 Menganalisis data dari Deriv (Scalping Strategy)...")
                    df = calculate_indicators(df)
                    latest = df.iloc[-2]
                    previous = df.iloc[-3]
                    latest_close = latest['Close']
                    
                    bot_logger.info(f"💰 Data Terakhir XAU/USD: Close = {latest_close:.3f}")
                    
                    ema_med_col = BotConfig.get_ema_medium_col()
                    rsi_col = BotConfig.get_rsi_col()
                    adx_col = BotConfig.get_adx_col()
                    
                    required_cols = [ema_med_col, rsi_col, adx_col]
                    if any(pd.isna(latest.get(col)) for col in required_cols):
                        bot_logger.warning("⚠️ Core indicators NaN detected, waiting for more data...")
                        await asyncio.sleep(BotConfig.ANALYSIS_INTERVAL)
                        continue
                    
                    ema50_value = latest[ema_med_col]
                    rsi_value = latest[rsi_col]
                    adx_value = latest[adx_col]
                    
                    prev_rsi_value = previous[rsi_col] if rsi_col in previous.index else None
                    
                    if pd.isna(ema50_value) or pd.isna(rsi_value) or pd.isna(adx_value):
                        bot_logger.warning("⚠️ Invalid indicator values, waiting...")
                        await asyncio.sleep(BotConfig.ANALYSIS_INTERVAL)
                        continue
                    
                    if prev_rsi_value is None or pd.isna(prev_rsi_value):
                        bot_logger.warning("⚠️ Previous RSI not available, waiting...")
                        await asyncio.sleep(BotConfig.ANALYSIS_INTERVAL)
                        continue
                    
                    bot_logger.info(f"📊 Analysis: Price=${latest_close:.3f}, EMA50=${ema50_value:.3f}, RSI={rsi_value:.1f} (prev={prev_rsi_value:.1f}), ADX={adx_value:.1f}")
                    
                    final_signal = None
                    
                    if adx_value < BotConfig.ADX_FILTER_THRESHOLD:
                        bot_logger.info(f"❌ ADX too low ({adx_value:.1f} < {BotConfig.ADX_FILTER_THRESHOLD}), skip")
                    elif latest_close > ema50_value:
                        rsi_was_oversold = prev_rsi_value < BotConfig.RSI_OVERSOLD
                        rsi_exiting_oversold = rsi_value >= BotConfig.RSI_EXIT_OVERSOLD and rsi_value > prev_rsi_value
                        
                        if rsi_was_oversold and rsi_exiting_oversold:
                            bot_logger.info(f"🟢 BUY Signal: Price > EMA50, RSI exiting oversold ({prev_rsi_value:.1f} → {rsi_value:.1f}), ADX={adx_value:.1f}")
                            final_signal = 'BUY'
                        elif rsi_was_oversold:
                            bot_logger.info(f"⏳ BUY Setup: RSI oversold ({prev_rsi_value:.1f}), waiting for exit above {BotConfig.RSI_EXIT_OVERSOLD}")
                    elif latest_close < ema50_value:
                        rsi_was_overbought = prev_rsi_value > BotConfig.RSI_OVERBOUGHT
                        rsi_exiting_overbought = rsi_value <= BotConfig.RSI_EXIT_OVERBOUGHT and rsi_value < prev_rsi_value
                        
                        if rsi_was_overbought and rsi_exiting_overbought:
                            bot_logger.info(f"🔴 SELL Signal: Price < EMA50, RSI exiting overbought ({prev_rsi_value:.1f} → {rsi_value:.1f}), ADX={adx_value:.1f}")
                            final_signal = 'SELL'
                        elif rsi_was_overbought:
                            bot_logger.info(f"⏳ SELL Setup: RSI overbought ({prev_rsi_value:.1f}), waiting for exit below {BotConfig.RSI_EXIT_OVERBOUGHT}")
                    else:
                        bot_logger.info(f"⚖️ Price = EMA50, no clear trend direction, skip")
                    
                    if final_signal and not self._can_generate_signal():
                        if self.last_signal_time is not None:
                            cooldown_left = self.signal_cooldown_seconds - (datetime.datetime.now(datetime.timezone.utc) - self.last_signal_time).total_seconds()
                            bot_logger.info(f"⏳ Signal {final_signal} detected but in cooldown ({cooldown_left:.0f}s left)")
                        final_signal = None
                    
                    if final_signal:
                        bot_logger.info(f"✅ Sinyal {final_signal} valid ditemukan!")
                        
                        if final_signal == "BUY":
                            sl = latest_close - BotConfig.FIXED_SL_USD
                            tp1 = latest_close + BotConfig.FIXED_TP_USD
                            tp2 = latest_close + (BotConfig.FIXED_TP_USD * 1.5)
                            signal_emoji = "📈"
                        else:
                            sl = latest_close + BotConfig.FIXED_SL_USD
                            tp1 = latest_close - BotConfig.FIXED_TP_USD
                            tp2 = latest_close - (BotConfig.FIXED_TP_USD * 1.5)
                            signal_emoji = "📉"
                        
                        title = f"{signal_emoji} SCALPING {final_signal}"
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
                            f"{signal_emoji} *SCALPING {final_signal} XAU/USD*\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🌐 _Strategi: EMA50 + RSI3 + ADX55_\n\n"
                            f"🕐 Waktu: *{start_time_utc.astimezone(BotConfig.WIB_TZ).strftime('%H:%M:%S WIB')}*\n"
                            f"💵 Entry: *${latest_close:.3f}*\n\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n"
                            f"📋 *KONDISI ENTRY*\n"
                            f"📊 EMA50: ${ema50_value:.3f}\n"
                            f"📈 RSI(3): {rsi_value:.1f}\n"
                            f"💪 ADX(55): {adx_value:.1f}\n\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 *TARGET & PROTEKSI*\n"
                            f"🎯 TP1: *${tp1:.3f}* (+${abs(tp1-latest_close):.2f})\n"
                            f"🏆 TP2: *${tp2:.3f}* (+${abs(tp2-latest_close):.2f})\n"
                            f"🛑 SL: *${sl:.3f}* (-${abs(sl-latest_close):.2f})\n\n"
                            f"📡 Tracking aktif hingga TP/SL tercapai"
                        )
                        
                        if BotConfig.GENERATE_CHARTS:
                            chart_generated = await generate_chart(df, temp_trade_info, title)
                        else:
                            chart_generated = True
                            bot_logger.info("📊 Chart generation disabled (GENERATE_CHARTS=false)")
                        
                        if chart_generated:
                            if BotConfig.GENERATE_CHARTS:
                                photo_sent = await self.send_photo(bot, caption)
                            else:
                                if self._has_telegram_service() and self.telegram_service:
                                    await self.telegram_service.send_to_all_subscribers(bot, caption)
                                photo_sent = True
                            
                            if photo_sent:
                                self._record_signal(temp_trade_info)
                                self.state_manager.update_current_signal(temp_trade_info)
                                self.state_manager.set_active_trade_for_subscribers(temp_trade_info)
                                
                                self.state_manager.update_last_signal_info({
                                    'direction': final_signal,
                                    'entry_price': latest_close,
                                    'tp1_level': tp1,
                                    'tp2_level': tp2,
                                    'sl_level': sl,
                                    'time': start_time_utc.astimezone(BotConfig.WIB_TZ).strftime('%H:%M:%S WIB'),
                                    'status': 'AKTIF'
                                })
                                self.state_manager.clear_user_tracking_messages()
                                rt_price = await self.get_realtime_price()
                                if rt_price and self._has_telegram_service() and self.telegram_service:
                                    await self.telegram_service.send_tracking_update(bot, rt_price, self.state_manager.current_signal)
                                bot_logger.info("✅ Sinyal Scalping berhasil dikirim! Mode pelacakan aktif.")
                    else:
                        bot_logger.info("🔍 Belum ada kondisi entry scalping. Terus mencari...")
                
                if not self.state_manager.current_signal:
                    wait_time = BotConfig.ANALYSIS_INTERVAL + random.randint(-BotConfig.ANALYSIS_JITTER, BotConfig.ANALYSIS_JITTER)
                    bot_logger.info(f"⏳ Menunggu {wait_time} detik sebelum analisis berikutnya...")
                    await asyncio.sleep(wait_time)
            
            except asyncio.CancelledError:
                bot_logger.info("Signal engine cancelled")
                break
            except asyncio.TimeoutError:
                bot_logger.error("⚠️ TIMEOUT: Proses terlalu lama")
                await asyncio.sleep(BotConfig.ANALYSIS_INTERVAL)
            except Exception as e:
                bot_logger.critical(f"❌ Error kritis: {e}", exc_info=True)
                await asyncio.sleep(BotConfig.ANALYSIS_INTERVAL)
        
        bot_logger.info("Signal engine shutting down...")
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass
        
        if self.deriv_ws:
            await self.deriv_ws.close()
        
        bot_logger.info("Signal engine stopped")

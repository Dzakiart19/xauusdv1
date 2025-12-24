import asyncio
import datetime
import random
import os
import pandas as pd
import logging
from typing import Optional, TYPE_CHECKING

from config import BotConfig
from utils import calculate_indicators, bot_logger
from deriv_ws import DerivWebSocket

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
    
    def get_strategy_status(self, latest_close: float, ema50_value: float, rsi_value: float, 
                           prev_rsi_value: float, adx_value: float) -> dict:
        """Determine current strategy status based on market conditions"""
        status = "UNKNOWN"
        emoji = "❓"
        description = ""
        
        current_signal = self.state_manager.current_signal
        has_active_trades = bool(current_signal) or any(
            self.state_manager.get_user_state(cid).get('active_trade') 
            for cid in self.state_manager.subscribers
        )
        
        # POSITION ACTIVE
        if has_active_trades:
            status = "POSITION ACTIVE"
            emoji = "🟣"
            description = "Sinyal aktif sedang dipantau TP/SL"
        # TREND WEAK
        elif adx_value <= BotConfig.ADX_FILTER_THRESHOLD:
            status = "TREND WEAK (NO TRADE)"
            emoji = "⚠️"
            description = "ADX lemah / sideways — tidak ada entry"
        # BUY SETUP
        elif latest_close > ema50_value and adx_value > BotConfig.ADX_FILTER_THRESHOLD:
            rsi_was_oversold = prev_rsi_value < BotConfig.RSI_OVERSOLD
            rsi_exiting_oversold = rsi_value >= BotConfig.RSI_EXIT_OVERSOLD and rsi_value > prev_rsi_value
            
            if rsi_was_oversold and rsi_exiting_oversold:
                status = "BUY SETUP"
                emoji = "🟢"
                description = "Bullish trend valid — menunggu trigger BUY"
            elif rsi_was_oversold:
                status = "WAITING PULLBACK"
                emoji = "⏳"
                description = "Trend bullish valid — RSI pullback belum selesai"
            else:
                status = "WAITING PULLBACK"
                emoji = "⏳"
                description = "Harga > EMA50 — menunggu RSI masuk oversold"
        # SELL SETUP
        elif latest_close < ema50_value and adx_value > BotConfig.ADX_FILTER_THRESHOLD:
            rsi_was_overbought = prev_rsi_value > BotConfig.RSI_OVERBOUGHT
            rsi_exiting_overbought = rsi_value <= BotConfig.RSI_EXIT_OVERBOUGHT and rsi_value < prev_rsi_value
            
            if rsi_was_overbought and rsi_exiting_overbought:
                status = "SELL SETUP"
                emoji = "🔴"
                description = "Bearish trend valid — menunggu trigger SELL"
            elif rsi_was_overbought:
                status = "WAITING PULLBACK"
                emoji = "⏳"
                description = "Trend bearish valid — RSI pullback belum selesai"
            else:
                status = "WAITING PULLBACK"
                emoji = "⏳"
                description = "Harga < EMA50 — menunggu RSI masuk overbought"
        else:
            status = "WAITING PULLBACK"
            emoji = "⏳"
            description = "Harga ≈ EMA50 — trend tidak jelas"
        
        return {
            'status': status,
            'emoji': emoji,
            'description': description,
            'rsi': round(rsi_value, 1),
            'ema': round(ema50_value, 3),
            'adx': round(adx_value, 1),
            'price': round(latest_close, 3)
        }
    
    async def get_historical_data(self) -> Optional[pd.DataFrame]:
        if not self.deriv_ws or not self.deriv_ws.connected:
            bot_logger.warning("WebSocket not connected, skipping data fetch...")
            return None
        
        # Skip if market is closed - Deriv API won't have data
        market_status = BotConfig.get_market_status()
        if not market_status['is_open']:
            bot_logger.info(f"📅 Market closed ({market_status['message']}), skipping candle fetch")
            return None
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                symbol = self.gold_symbol or "frxXAUUSD"
                candles = await self.deriv_ws.get_candles(symbol=symbol, count=100, granularity=60)
                
                if not candles or not isinstance(candles, list):
                    if attempt < max_retries - 1:
                        delay = 10 + (10 * attempt)
                        bot_logger.warning(f"No candle data (attempt {attempt+1}/{max_retries}), waiting {delay}s...")
                        await asyncio.sleep(delay)
                        continue
                    bot_logger.warning("No candle data received after retries")
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
                if attempt < max_retries - 1:
                    delay = 10 + (10 * attempt)
                    bot_logger.warning(f"DATA-ERROR (attempt {attempt+1}/{max_retries}): {e}, waiting {delay}s...")
                    await asyncio.sleep(delay)
                    continue
                bot_logger.error(f"DATA-ERROR: Failed after {max_retries} attempts: {e}")
                return None
    
    async def get_realtime_price(self) -> Optional[float]:
        if self.deriv_ws and self.deriv_ws.connected:
            return self.deriv_ws.get_current_price()
        return None
    
    async def generate_manual_signal(self, bot, target_chat_id: Optional[str] = None) -> bool:
        """Generate signal manually regardless of market conditions
        
        Args:
            bot: Telegram bot instance
            target_chat_id: If provided, send only to this user. If None, broadcast to all.
        """
        try:
            df = await self.get_historical_data()
            if df is None:
                bot_logger.warning("❌ Tidak bisa ambil data pasar")
                return False
            
            df = calculate_indicators(df)
            latest = df.iloc[-2]
            latest_close = latest['Close']
            
            ema_med_col = BotConfig.get_ema_medium_col()
            rsi_col = BotConfig.get_rsi_col()
            
            ema50_value = latest[ema_med_col]
            rsi_value = latest[rsi_col]
            
            # Determine signal direction based on price vs EMA50 and RSI
            if latest_close > ema50_value:
                final_signal = 'BUY'
                signal_emoji = "📈"
            elif latest_close < ema50_value:
                final_signal = 'SELL'
                signal_emoji = "📉"
            else:
                bot_logger.warning("⚠️ Price = EMA50, tidak bisa tentukan arah")
                return False
            
            # Generate levels
            sl = latest_close - BotConfig.FIXED_SL_USD if final_signal == "BUY" else latest_close + BotConfig.FIXED_SL_USD
            tp1 = latest_close + BotConfig.FIXED_TP_USD if final_signal == "BUY" else latest_close - BotConfig.FIXED_TP_USD
            tp2 = latest_close + (BotConfig.FIXED_TP_USD * 1.5) if final_signal == "BUY" else latest_close - (BotConfig.FIXED_TP_USD * 1.5)
            
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
                f"🌐 _Strategi: EMA50 + RSI(3) + ADX(55)_\n\n"
                f"🕐 Waktu: *{start_time_utc.astimezone(BotConfig.WIB_TZ).strftime('%H:%M:%S WIB')}*\n"
                f"💵 Entry: *${latest_close:.3f}*\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📋 *KONDISI PASAR*\n"
                f"📊 EMA50: ${ema50_value:.3f}\n"
                f"📈 RSI(3): {rsi_value:.1f}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🎯 *TARGET & PROTEKSI*\n"
                f"🎯 TP1: *${tp1:.3f}* (+${abs(tp1-latest_close):.2f})\n"
                f"🏆 TP2: *${tp2:.3f}* (+${abs(tp2-latest_close):.2f})\n"
                f"🛑 SL: *${sl:.3f}* (-${abs(sl-latest_close):.2f})\n\n"
                f"📡 Tracking aktif hingga TP/SL tercapai"
            )
            
            if self._has_telegram_service() and self.telegram_service:
                if target_chat_id:
                    # Send only to specific user (manual signal)
                    await self.telegram_service._safe_send(bot.send_message(
                        chat_id=target_chat_id,
                        text=caption,
                        parse_mode='Markdown'
                    ))
                    # Update only this user's state
                    user_state = self.state_manager.get_user_state(target_chat_id)
                    user_state['active_trade'] = temp_trade_info.copy()
                    user_state['tracking_message_id'] = None
                    if 'signal_history' not in user_state:
                        user_state['signal_history'] = []
                    user_state['signal_history'].append({
                        'id': len(user_state['signal_history']) + 1,
                        'direction': final_signal,
                        'entry_price': latest_close,
                        'tp1': tp1,
                        'tp2': tp2,
                        'sl': sl,
                        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        'result': 'PENDING'
                    })
                    self.state_manager.save_user_states()
                    # ❌ DO NOT set global signal for manual signals!
                    # Only user 1's state is updated, NOT broadcast to others
                    bot_logger.info(f"✅ Manual signal {final_signal} sent to user {target_chat_id} ONLY! Personal tracking enabled.")
                else:
                    # Broadcast to all subscribers
                    await self.telegram_service.send_to_all_subscribers(bot, caption)
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
                    bot_logger.info(f"✅ Manual signal {final_signal} broadcast to all subscribers!")
                
                return True
            
            return False
        except Exception as e:
            bot_logger.error(f"❌ Manual signal error: {e}", exc_info=True)
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
        
        self.gold_symbol = 'frxXAUUSD'
        bot_logger.info(f"Using gold symbol: {self.gold_symbol}")
        
        self.deriv_ws = DerivWebSocket()
        
        max_connect_attempts = 3
        for attempt in range(max_connect_attempts):
            try:
                connected = await self.deriv_ws.connect()
                if connected:
                    break
                else:
                    if attempt < max_connect_attempts - 1:
                        bot_logger.warning(f"Connection attempt {attempt + 1} failed, retrying...")
                        await asyncio.sleep(3)
            except Exception as e:
                bot_logger.error(f"Connection attempt {attempt + 1} error: {e}")
                if attempt < max_connect_attempts - 1:
                    await asyncio.sleep(3)
        
        if not self.deriv_ws.connected:
            bot_logger.critical("Failed to connect to Deriv WebSocket after max attempts!")
            return
        
        await self.deriv_ws.subscribe_ticks(self.gold_symbol)
        
        listen_task = asyncio.create_task(self.deriv_ws.listen())
        
        await asyncio.sleep(3)
        
        self.state_manager.current_signal = {}
        self.last_signal_time = None  # Reset to allow immediate signal search
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
                
                # Check if there's ANY active trade (global or manual per-user)
                has_active_trades = bool(current_signal) or any(
                    self.state_manager.get_user_state(cid).get('active_trade') 
                    for cid in self.state_manager.subscribers
                )
                
                if has_active_trades:
                    await asyncio.sleep(BotConfig.TRACKING_UPDATE_INTERVAL)
                    tracking_counter += 1
                    trade_closed = False
                    
                    rt_price = await self.get_realtime_price()
                    if rt_price:
                        # Use current_signal if available (broadcast signal), otherwise None (per-user signals)
                        direction = current_signal.get('direction') if current_signal else None
                        entry = current_signal.get('entry_price') if current_signal else None
                        tp1 = current_signal.get('tp1_level') if current_signal else None
                        tp2 = current_signal.get('tp2_level') if current_signal else None
                        sl = current_signal.get('sl_level') if current_signal else None
                        trade_status = current_signal.get('status', 'active') if current_signal else 'active'
                        
                        if direction and entry and tp1 and tp2 and sl:
                            bot_logger.info(f"📍 Tracking #{tracking_counter} {direction}: Price=${rt_price:.3f} Entry=${entry:.3f} SL=${sl:.3f}")
                        else:
                            # Manual per-user signals - track individual active trades
                            bot_logger.info(f"📍 Tracking #{tracking_counter} - Per-user tracking (manual signals)")
                        
                        if self._has_telegram_service() and self.telegram_service:
                            try:
                                # ALWAYS send tracking update - works for both global AND per-user signals
                                # send_tracking_update() loops all subscribers and tracks from their active_trade
                                await self.telegram_service.send_tracking_update(bot, rt_price, current_signal if current_signal else {})
                                bot_logger.debug(f"✅ Tracking update sent to all active traders")
                            except Exception as e:
                                bot_logger.error(f"❌ Failed to send tracking update: {e}")
                        else:
                            bot_logger.warning("⚠️ Telegram service not available for tracking")
                        
                        result_info = None
                        users_with_closed_trades = []
                        
                        # GLOBAL SIGNAL result tracking
                        if current_signal and direction == 'BUY' and tp2 and tp1:
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
                            
                            elif sl and rt_price <= sl:
                                if trade_status == 'tp1_hit':
                                    result_info = {'type': 'BREAK_EVEN', 'emoji': '⚖️', 'text': 'BREAK EVEN - TP1 Hit, SL at Entry'}
                                else:
                                    result_info = {'type': 'LOSS', 'emoji': '❌', 'text': 'STOP LOSS HIT'}
                        
                        elif current_signal and direction == 'SELL' and tp2 and tp1:
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
                            
                            elif sl and rt_price >= sl:
                                if trade_status == 'tp1_hit':
                                    result_info = {'type': 'BREAK_EVEN', 'emoji': '⚖️', 'text': 'BREAK EVEN - TP1 Hit, SL at Entry'}
                                else:
                                    result_info = {'type': 'LOSS', 'emoji': '❌', 'text': 'STOP LOSS HIT'}
                        
                        # PER-USER MANUAL SIGNAL SL/TP detection (if NO global signal)
                        if not current_signal:
                            for cid in self.state_manager.subscribers:
                                user_state = self.state_manager.get_user_state(cid)
                                active_trade = user_state.get('active_trade')
                                if not active_trade:
                                    continue
                                
                                u_dir = active_trade.get('direction')
                                u_entry = active_trade.get('entry_price')
                                u_sl = active_trade.get('sl_level')
                                u_tp1 = active_trade.get('tp1_level')
                                u_tp2 = active_trade.get('tp2_level')
                                u_status = active_trade.get('status', 'active')
                                
                                u_result = None
                                
                                # BUY signal SL/TP detection
                                if u_dir == 'BUY':
                                    if rt_price >= u_tp2:
                                        u_result = {'type': 'WIN', 'emoji': '🏆', 'text': 'TP2 HIT - FULL WIN!'}
                                    elif rt_price >= u_tp1 and u_status == 'active':
                                        active_trade['status'] = 'tp1_hit'
                                        active_trade['sl_level'] = u_entry
                                        self.state_manager.save_user_states()
                                        if self._has_telegram_service() and self.telegram_service:
                                            await self.telegram_service.send_to_one_subscriber(bot, cid, "🎯 *TP1 TERCAPAI!*\n━━━━━━━━━━━━━━━━━━━━━\n\n💰 Harga: *${rt_price:.3f}*\n🎯 TP1: ${u_tp1:.3f}\n\n🛡️ *SL dipindahkan ke Entry (Break Even)*\n🏆 Target selanjutnya: TP2\n\n💡 Profit sebagian sudah aman!")
                                        bot_logger.info(f"✅ User {cid} TP1 HIT! SL moved to BE. Price: {rt_price:.3f}")
                                    elif u_sl and rt_price <= u_sl:
                                        if u_status == 'tp1_hit':
                                            u_result = {'type': 'BREAK_EVEN', 'emoji': '⚖️', 'text': 'BREAK EVEN - TP1 Hit, SL at Entry'}
                                        else:
                                            u_result = {'type': 'LOSS', 'emoji': '❌', 'text': 'STOP LOSS HIT'}
                                
                                # SELL signal SL/TP detection
                                elif u_dir == 'SELL':
                                    if rt_price <= u_tp2:
                                        u_result = {'type': 'WIN', 'emoji': '🏆', 'text': 'TP2 HIT - FULL WIN!'}
                                    elif rt_price <= u_tp1 and u_status == 'active':
                                        active_trade['status'] = 'tp1_hit'
                                        active_trade['sl_level'] = u_entry
                                        self.state_manager.save_user_states()
                                        if self._has_telegram_service() and self.telegram_service:
                                            await self.telegram_service.send_to_one_subscriber(bot, cid, "🎯 *TP1 TERCAPAI!*\n━━━━━━━━━━━━━━━━━━━━━\n\n💰 Harga: *${rt_price:.3f}*\n🎯 TP1: ${u_tp1:.3f}\n\n🛡️ *SL dipindahkan ke Entry (Break Even)*\n🏆 Target selanjutnya: TP2\n\n💡 Profit sebagian sudah aman!")
                                        bot_logger.info(f"✅ User {cid} TP1 HIT! SL moved to BE. Price: {rt_price:.3f}")
                                    elif u_sl and rt_price >= u_sl:
                                        if u_status == 'tp1_hit':
                                            u_result = {'type': 'BREAK_EVEN', 'emoji': '⚖️', 'text': 'BREAK EVEN - TP1 Hit, SL at Entry'}
                                        else:
                                            u_result = {'type': 'LOSS', 'emoji': '❌', 'text': 'STOP LOSS HIT'}
                                
                                # Send result to user if trade closed
                                if u_result:
                                    self.state_manager.update_trade_result(u_result['type'], cid)
                                    duration = 0
                                    if u_entry and 'start_time_utc' in active_trade:
                                        try:
                                            start = active_trade['start_time_utc']
                                            if isinstance(start, str):
                                                start = datetime.datetime.fromisoformat(start)
                                            duration = round((datetime.datetime.now(datetime.timezone.utc) - start).total_seconds() / 60, 1)
                                        except:
                                            duration = 0
                                    
                                    result_text = f"{u_result['emoji']} *{u_result['text']}*\n━━━━━━━━━━━━━━━━━━━━━\n\n💵 Entry: *${u_entry:.3f}*\n💰 Exit: *${rt_price:.3f}*\n⏱️ Durasi: *{duration} menit*\n\n📊 Gunakan /stats untuk melihat statistik\n🔍 Bot kembali mencari sinyal..."
                                    if self._has_telegram_service() and self.telegram_service:
                                        await self.telegram_service.send_to_one_subscriber(bot, cid, result_text)
                                    
                                    active_trade.clear()
                                    self.state_manager.save_user_states()
                                    users_with_closed_trades.append(cid)
                                    bot_logger.info(f"✅ User {cid} trade closed: {u_result['text']} @ ${rt_price:.3f}")
                        
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
                        cooldown_jitter = random.randint(30, 60)
                        bot_logger.info(f"⏳ Trade closed, waiting {cooldown_jitter}s before searching new signal...")
                        await asyncio.sleep(cooldown_jitter)
                        continue
                
                else:
                    df = await self.get_historical_data()
                    
                    if df is None:
                        wait_time = 60 + random.randint(30, 60)
                        bot_logger.warning(f"⏳ Failed to fetch data, long cooldown {wait_time}s before retry...")
                        await asyncio.sleep(wait_time)
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
                    # Update real-time indicators for /info command
                    self.state_manager.update_current_indicators(rsi_value, ema50_value, adx_value)
                    
                    # Update strategy status
                    strategy_status = self.get_strategy_status(latest_close, ema50_value, rsi_value, prev_rsi_value, adx_value)
                    self.state_manager.update_strategy_status(strategy_status)
                    
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
                            bot_logger.info(f"⏳ Signal {final_signal} detected but COOLDOWN active ({cooldown_left:.0f}s remaining until next signal allowed)")
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
                            f"🌐 _Strategi: EMA50 + RSI(3) + ADX(55)_\n\n"
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
                        
                        photo_sent = False
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
                            
                            # Log signal distribution
                            subscriber_count = len(self.state_manager.subscribers)
                            bot_logger.info(f"✅ Sinyal {final_signal} dikirim ke {subscriber_count} subscribers! Mode pelacakan aktif.")
                            for sub_id in self.state_manager.subscribers:
                                bot_logger.debug(f"  → Sinyal dikirim ke user: {sub_id}")
                            
                            rt_price = await self.get_realtime_price()
                            if rt_price and self._has_telegram_service() and self.telegram_service:
                                await self.telegram_service.send_tracking_update(bot, rt_price, self.state_manager.current_signal)
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

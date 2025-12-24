import asyncio
import datetime
import io
import os
import logging
from typing import Optional, TYPE_CHECKING

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, RetryAfter, TimedOut
from telegram.ext import ContextTypes

from config import BotConfig
from utils import format_pnl, get_win_rate_emoji, calculate_win_rate

if TYPE_CHECKING:
    from state_manager import StateManager


logger = logging.getLogger("TelegramService")


class TelegramService:
    def __init__(self, state_manager: 'StateManager', deriv_ws_getter, gold_symbol_getter):
        self.state_manager = state_manager
        self.deriv_ws_getter = deriv_ws_getter
        self.gold_symbol_getter = gold_symbol_getter
        self._rate_limit_lock = asyncio.Lock()
        self._last_send_time = 0.0
        self._last_tracking_price = {}  # Track last price per user
        self._tracking_update_counter = 0  # Force update every N calls
    
    async def _safe_send(self, coro):
        try:
            async with self._rate_limit_lock:
                now = asyncio.get_event_loop().time()
                time_since_last = now - self._last_send_time
                if time_since_last < BotConfig.TELEGRAM_RATE_LIMIT_DELAY:
                    await asyncio.sleep(BotConfig.TELEGRAM_RATE_LIMIT_DELAY - time_since_last)
                self._last_send_time = asyncio.get_event_loop().time()
                return await coro
        except (RetryAfter, TimedOut, TelegramError) as e:
            error_msg = str(e).lower()
            if "chat not found" in error_msg or "not found" in error_msg:
                logger.debug(f"Chat not found, will be removed: {e}")
            elif "message is not modified" in error_msg:
                logger.debug(f"Message unchanged, skipping: {e}")
            else:
                logger.error(f"Failed to send message: {e}")
            return None
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        chat_id = str(update.message.chat_id)
        
        self.state_manager.get_user_state(chat_id)
        
        # Auto-subscribe user on /start
        was_subscriber = self.state_manager.is_subscriber(chat_id)
        if not was_subscriber:
            self.state_manager.add_subscriber(chat_id)
            user_state = self.state_manager.get_user_state(chat_id)
            if self.state_manager.current_signal:
                user_state['active_trade'] = self.state_manager.current_signal.copy()
                user_state['tracking_message_id'] = None
            self.state_manager.save_user_states()
        
        keyboard = [
            [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard"),
             InlineKeyboardButton("📈 Stats", callback_data="stats")],
            [InlineKeyboardButton("🔄 Reset Data", callback_data="riset"),
             InlineKeyboardButton("🚀 Send Signal", callback_data="send_signal")],
            [InlineKeyboardButton("❌ Unsubscribe", callback_data="unsubscribe"),
             InlineKeyboardButton("ℹ️ Info", callback_data="info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Show welcome message if new subscriber
        if not was_subscriber:
            await update.message.reply_text(
                f"🎉 *Selamat Datang!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🏆 Bot Sinyal XAU/USD V2.0 Pro\n"
                f"✅ Anda sudah otomatis berlangganan!\n\n"
                f"🌐 Data real-time dari Deriv WebSocket\n"
                f"📡 Strategi: EMA50 + RSI(3) + ADX(55)\n\n"
                f"📬 Bot akan mengirim sinyal otomatis 24 jam\n"
                f"📊 Gunakan /dashboard untuk pantau posisi\n\n"
                f"💡 *Menu Cepat:*\n"
                f"├ /dashboard - Lihat posisi aktif\n"
                f"├ /stats - Statistik trading Anda\n"
                f"├ /today - Statistik hari ini\n"
                f"├ /send - Signal manual\n"
                f"└ /info - Info sistem\n\n"
                f"🚀 Selamat trading!",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            # Returning user
            await update.message.reply_text(
                f"🏆 *Bot Sinyal XAU/USD V2.0 Pro*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"✅ Status: AKTIF & BERLANGGANAN\n\n"
                f"📡 Strategi: EMA50 + RSI(3) + ADX(55)\n"
                f"💰 Real-time tracking & sinyal otomatis\n\n"
                f"💡 *Menu Cepat:*\n"
                f"├ /dashboard - Lihat posisi aktif\n"
                f"├ /stats - Statistik trading\n"
                f"├ /send - Signal manual\n"
                f"└ /info - Info sistem",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
    
    async def subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        chat_id = str(update.message.chat_id)
        
        # Validate that chat_id is numeric
        if not chat_id.isdigit():
            await update.message.reply_text(
                "❌ *Error*\n\n"
                "Invalid chat ID format. This shouldn't happen normally.",
                parse_mode='Markdown'
            )
            return
        
        if self.state_manager.is_subscriber(chat_id):
            await update.message.reply_text(
                "✅ Anda sudah berlangganan!\n\n"
                "📊 Gunakan /dashboard untuk pantau posisi aktif.",
                parse_mode='Markdown'
            )
        else:
            self.state_manager.add_subscriber(chat_id)
            
            user_state = self.state_manager.get_user_state(chat_id)
            if self.state_manager.current_signal:
                user_state['active_trade'] = self.state_manager.current_signal.copy()
                user_state['tracking_message_id'] = None
                self.state_manager.save_user_states()
            
            await update.message.reply_text(
                "🎉 *Selamat! Berhasil berlangganan!*\n\n"
                "📬 Anda akan menerima sinyal trading XAU/USD secara real-time.\n\n"
                "💡 *Tips:*\n"
                "├ Gunakan /dashboard untuk pantau posisi\n"
                "├ Gunakan /today untuk statistik hari ini\n"
                "└ Bot akan melacak posisi hingga TP/SL tercapai\n\n"
                "🚀 Selamat trading!",
                parse_mode='Markdown'
            )
            logger.info(f"New subscriber: {chat_id}")
    
    async def unsubscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        chat_id = str(update.message.chat_id)
        
        if self.state_manager.is_subscriber(chat_id):
            self.state_manager.remove_subscriber(chat_id)
            await update.message.reply_text(
                "👋 *Sampai jumpa lagi!*\n\n"
                "Anda telah berhenti berlangganan.\n\n"
                "💡 Gunakan /subscribe kapan saja untuk kembali bergabung!",
                parse_mode='Markdown'
            )
            logger.info(f"Unsubscribed: {chat_id}")
        else:
            await update.message.reply_text(
                "ℹ️ Anda belum berlangganan.\n\n"
                "💡 Gunakan /subscribe untuk mulai menerima sinyal.",
                parse_mode='Markdown'
            )
    
    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        chat_id = str(update.message.chat_id)
        user_state = self.state_manager.get_user_state(chat_id)
        
        win_count = user_state['win_count']
        loss_count = user_state['loss_count']
        be_count = user_state['be_count']
        
        total = win_count + loss_count + be_count
        win_rate = calculate_win_rate(win_count, loss_count)
        rate_emoji = get_win_rate_emoji(win_rate)
        
        await update.message.reply_text(
            f"📈 *Statistik Trading Anda*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 Total Trade: *{total}*\n\n"
            f"✅ Menang: *{win_count}*\n"
            f"❌ Kalah: *{loss_count}*\n"
            f"⚖️ Break Even: *{be_count}*\n\n"
            f"{rate_emoji} Win Rate: *{win_rate:.1f}%*\n\n"
            f"💡 Gunakan /today untuk statistik hari ini.\n"
            f"🤖 Bot bekerja 24 jam untuk Anda!",
            parse_mode='Markdown'
        )
    
    async def today(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        chat_id = str(update.message.chat_id)
        
        today_stats = self.state_manager.get_today_stats(chat_id)
        
        await update.message.reply_text(
            f"📅 *Statistik Hari Ini*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 Total Sinyal: *{today_stats['total']}*\n\n"
            f"✅ Menang: *{today_stats['wins']}*\n"
            f"❌ Kalah: *{today_stats['losses']}*\n"
            f"⚖️ Break Even: *{today_stats['break_evens']}*\n"
            f"⏳ Pending: *{today_stats['pending']}*\n\n"
            f"🎯 Win Rate: *{today_stats['win_rate']:.1f}%*",
            parse_mode='Markdown'
        )
    
    async def riset(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        chat_id = str(update.message.chat_id)
        
        old_stats = self.state_manager.reset_user_data(chat_id)
        
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
        logger.info(f"User {chat_id} reset data: {old_stats} -> 0")
    
    async def info(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        chat_id = str(update.message.chat_id)
        deriv_ws = self.deriv_ws_getter()
        gold_symbol = self.gold_symbol_getter()
        
        status = "🟢 Terhubung" if (deriv_ws and deriv_ws.connected) else "🔴 Terputus"
        current_price = deriv_ws.get_current_price() if deriv_ws else None
        price_str = f"${current_price:.3f}" if current_price else "N/A"
        subscriber_count = len(self.state_manager.subscribers)
        
        market_status = BotConfig.get_market_status()
        market_info = f"📅 Market: *{market_status['status']}*"
        if not market_status['is_open']:
            market_info += f"\n   _{market_status['message']}_"
        
        today_stats = self.state_manager.get_today_stats(chat_id)
        
        # Real-time indicators
        indicators = self.state_manager.current_indicators
        rsi_str = f"{indicators.get('rsi', 0):.1f}" if indicators else "N/A"
        ema_str = f"${indicators.get('ema', 0):.3f}" if indicators else "N/A"
        adx_str = f"{indicators.get('adx', 0):.1f}" if indicators else "N/A"
        
        # Strategy status
        strat_status = self.state_manager.strategy_status
        status_emoji = strat_status.get('emoji', '❓')
        status_name = strat_status.get('status', 'UNKNOWN')
        status_desc = strat_status.get('description', '')
        status_section = f"📊 Status Strategi:\n└ {status_emoji} *{status_name}*\n   _{status_desc}_\n\n" if strat_status else ""
        
        await update.message.reply_text(
            f"⚙️ *Info Sistem Bot V2.0 Pro*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📡 WebSocket: {status}\n"
            f"🏷️ Symbol: {gold_symbol or 'frxXAUUSD'}\n"
            f"💰 Harga Terakhir: {price_str}\n"
            f"👥 Total Subscriber: {subscriber_count}\n\n"
            f"{status_section}"
            f"📊 *Indikator Real-Time (EMA50 + RSI(3) + ADX(55)):*\n"
            f"├ 📈 RSI: *{rsi_str}*\n"
            f"├ 💹 EMA50: *{ema_str}*\n"
            f"└ 💪 ADX: *{adx_str}*\n\n"
            f"{market_info}\n\n"
            f"📊 *Statistik Hari Ini (Anda):*\n"
            f"├ Sinyal: {today_stats['total']}\n"
            f"├ Win: {today_stats['wins']} | Loss: {today_stats['losses']}\n"
            f"└ Win Rate: {today_stats['win_rate']:.1f}%\n\n"
            f"🤖 Bot berjalan 24 jam non-stop!",
            parse_mode='Markdown'
        )
    
    async def dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message:
            await self.send_dashboard(update.message.chat_id, context.bot)
    
    async def signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        
        if not self.state_manager.last_signal_info:
            await update.message.reply_text(
                "🔍 *Belum Ada Sinyal*\n\n"
                "Bot sedang mencari sinyal terbaik untuk Anda.\n"
                "💡 Gunakan /subscribe untuk menerima notifikasi otomatis.",
                parse_mode='Markdown'
            )
            return
        
        info = self.state_manager.last_signal_info
        direction = info.get('direction', 'N/A')
        entry = info.get('entry_price', 0)
        tp1 = info.get('tp1_level', 0)
        tp2 = info.get('tp2_level', 0)
        sl = info.get('sl_level', 0)
        signal_time = info.get('time', 'N/A')
        status = info.get('status', 'N/A')
        
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
    
    async def send(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        
        chat_id = str(update.message.chat_id)
        
        await update.message.reply_text(
            "🔄 *Generating manual signal...*\n\n"
            "Tunggu sebentar, bot sedang menganalisis pasar dan membuat signal.",
            parse_mode='Markdown'
        )
        
        from signal_engine import SignalEngine
        signal_engine = context.bot_data.get('signal_engine')
        
        if not signal_engine:
            await update.message.reply_text(
                "❌ *Error*\n\n"
                "Signal engine tidak tersedia.",
                parse_mode='Markdown'
            )
            return
        
        # Pass chat_id so signal only goes to this user
        success = await signal_engine.generate_manual_signal(context.bot, target_chat_id=chat_id)
        
        if success:
            await update.message.reply_text(
                "✅ *Signal Manual Berhasil Dibuat!*\n\n"
                "Signal dikirim ke Anda saja.\n"
                "📍 Gunakan /dashboard untuk tracking.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ *Gagal Membuat Signal*\n\n"
                "Ada masalah saat menganalisis data pasar.\n"
                "Cek logs untuk detail error.",
                parse_mode='Markdown'
            )
    
    async def send_dashboard(self, chat_id, bot) -> None:
        chat_id = str(chat_id)
        user_state = self.state_manager.get_user_state(chat_id)
        deriv_ws = self.deriv_ws_getter()
        gold_symbol = self.gold_symbol_getter()
        
        ws_status = "🟢 Terhubung" if (deriv_ws and deriv_ws.connected) else "🔴 Terputus"
        current_price = deriv_ws.get_current_price() if deriv_ws else None
        price_str = f"${current_price:.3f}" if current_price else "N/A"
        
        market_status = BotConfig.get_market_status()
        
        now = datetime.datetime.now(BotConfig.WIB_TZ)
        
        dashboard_text = (
            f"📊 *DASHBOARD XAU/USD*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 _{now.strftime('%H:%M:%S WIB')}_\n\n"
            f"📡 Status: {ws_status}\n"
            f"📅 Market: *{market_status['status']}*\n"
            f"💰 Harga: *{price_str}*\n"
            f"🏷️ Symbol: {gold_symbol or 'frxXAUUSD'}\n\n"
        )
        
        if not market_status['is_open']:
            dashboard_text += f"⏰ _{market_status['message']}_\n\n"
        
        # Strategy status
        strat_status = self.state_manager.strategy_status
        if strat_status:
            dashboard_text += (
                f"📊 Status Strategi:\n"
                f"└ {strat_status.get('emoji', '❓')} *{strat_status.get('status', 'UNKNOWN')}*\n"
                f"   RSI: {strat_status.get('rsi', 0):.1f} | EMA50: ${strat_status.get('ema', 0):.3f} | ADX: {strat_status.get('adx', 0):.1f}\n"
                f"   _{strat_status.get('description', '')}_\n\n"
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
            pnl_str = format_pnl(direction, entry, current_price)
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
        win_rate = calculate_win_rate(win_count, loss_count)
        
        dashboard_text += (
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 *STATISTIK ANDA*\n"
            f"Total: {total} | ✅ {win_count} | ❌ {loss_count} | ⚖️ {be_count}\n"
            f"Win Rate: {win_rate:.1f}%"
        )
        
        keyboard = [[InlineKeyboardButton("🔄 Refresh", callback_data="dashboard")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        try:
            await self._safe_send(bot.send_message(
                chat_id=chat_id,
                text=dashboard_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            ))
        except Exception as e:
            logger.error(f"Failed to send dashboard: {e}")
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not query.message:
            return
        await query.answer()
        
        try:
            chat_id = str(query.message.chat.id)
        except (AttributeError, TypeError):
            return
        
        if query.data == "subscribe":
            if self.state_manager.is_subscriber(chat_id):
                await query.edit_message_text(
                    "✅ Anda sudah berlangganan!\n\n"
                    "📊 Gunakan /dashboard untuk pantau posisi aktif.",
                    parse_mode='Markdown'
                )
            else:
                self.state_manager.add_subscriber(chat_id)
                
                user_state = self.state_manager.get_user_state(chat_id)
                if self.state_manager.current_signal:
                    user_state['active_trade'] = self.state_manager.current_signal.copy()
                    user_state['tracking_message_id'] = None
                    self.state_manager.save_user_states()
                
                await query.edit_message_text(
                    "🎉 *Selamat! Berhasil berlangganan!*\n\n"
                    "📬 Anda akan menerima sinyal trading XAU/USD secara real-time.\n\n"
                    "💡 Gunakan /dashboard untuk pantau posisi aktif.",
                    parse_mode='Markdown'
                )
        
        elif query.data == "unsubscribe":
            if self.state_manager.is_subscriber(chat_id):
                self.state_manager.remove_subscriber(chat_id)
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
            await self.send_dashboard(chat_id, context.bot)
        
        elif query.data == "riset":
            old_stats = self.state_manager.reset_user_data(chat_id)
            
            await query.edit_message_text(
                f"🔄 *DATA BERHASIL DIRESET!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 Data sebelumnya: {old_stats}\n"
                f"📊 Data sekarang: W:0 L:0 BE:0\n\n"
                f"✅ Langganan Anda tetap aktif!",
                parse_mode='Markdown'
            )
            logger.info(f"User {chat_id} reset via button: {old_stats} -> 0")
        
        elif query.data == "stats":
            user_state = self.state_manager.get_user_state(chat_id)
            win_count = user_state['win_count']
            loss_count = user_state['loss_count']
            be_count = user_state['be_count']
            total = win_count + loss_count + be_count
            win_rate = calculate_win_rate(win_count, loss_count)
            rate_emoji = get_win_rate_emoji(win_rate)
            
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
        
        elif query.data == "send_signal":
            await query.answer("⏳ Generating manual signal...", show_alert=False)
            signal_engine = context.bot_data.get('signal_engine')
            
            if not signal_engine:
                await query.edit_message_text(
                    "❌ *Error*\n\n"
                    "Signal engine tidak tersedia.",
                    parse_mode='Markdown'
                )
                return
            
            # Generate manual signal for this user only
            success = await signal_engine.generate_manual_signal(context.bot, target_chat_id=chat_id)
            
            if success:
                await query.edit_message_text(
                    "✅ *Signal Manual Berhasil Dibuat!*\n\n"
                    "📊 Signal dikirim ke Anda saja.\n"
                    "📍 Gunakan /dashboard untuk tracking real-time.",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    "❌ *Gagal Membuat Signal*\n\n"
                    "Ada masalah saat menganalisis data pasar.\n"
                    "Coba lagi dalam beberapa detik.",
                    parse_mode='Markdown'
                )
        
        elif query.data == "info":
            deriv_ws = self.deriv_ws_getter()
            gold_symbol = self.gold_symbol_getter()
            
            status = "🟢 Terhubung" if (deriv_ws and deriv_ws.connected) else "🔴 Terputus"
            current_price = deriv_ws.get_current_price() if deriv_ws else None
            price_str = f"${current_price:.3f}" if current_price else "N/A"
            subscriber_count = len(self.state_manager.subscribers)
            
            market_status = BotConfig.get_market_status()
            market_info = f"📅 Market: *{market_status['status']}*"
            
            today_stats = self.state_manager.get_today_stats(chat_id)
            
            # Real-time indicators
            indicators = self.state_manager.current_indicators
            rsi_str = f"{indicators.get('rsi', 0):.1f}" if indicators else "N/A"
            ema_str = f"${indicators.get('ema', 0):.3f}" if indicators else "N/A"
            adx_str = f"{indicators.get('adx', 0):.1f}" if indicators else "N/A"
            
            # Strategy status
            strat_status = self.state_manager.strategy_status
            status_emoji = strat_status.get('emoji', '❓')
            status_name = strat_status.get('status', 'UNKNOWN')
            status_desc = strat_status.get('description', '')
            
            # Determine BUY/SELL/NO TRADE indicator
            trade_signal = "⚠️ NO TRADE"
            if "BUY SETUP" in status_name:
                trade_signal = "🟢 BUY READY"
            elif "SELL SETUP" in status_name:
                trade_signal = "🔴 SELL READY"
            elif "POSITION ACTIVE" in status_name:
                trade_signal = "🟣 POSITION ACTIVE"
            
            status_section = f"📊 Status: {status_emoji} *{status_name}*\n└ {trade_signal}\n" if strat_status else ""
            
            await query.edit_message_text(
                f"⚙️ *Info Sistem Bot V2.0 Pro*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📡 WebSocket: {status}\n"
                f"🏷️ Symbol: {gold_symbol or 'frxXAUUSD'}\n"
                f"💰 Harga: {price_str}\n"
                f"👥 Subscribers: {subscriber_count}\n\n"
                f"{status_section}"
                f"📊 *Indikator Real-Time:*\n"
                f"├ 📈 RSI: *{rsi_str}*\n"
                f"├ 💹 EMA50: *{ema_str}*\n"
                f"└ 💪 ADX: *{adx_str}*\n\n"
                f"{market_info}\n\n"
                f"📊 *Hari Ini:*\n"
                f"├ Sinyal: {today_stats['total']}\n"
                f"├ Win: {today_stats['wins']} | Loss: {today_stats['losses']}\n"
                f"└ Win Rate: {today_stats['win_rate']:.1f}%",
                parse_mode='Markdown'
            )
    
    async def send_to_one_subscriber(self, bot, chat_id: str | int, text: str) -> bool:
        """Send message to ONE specific subscriber (per-user tracking/results)"""
        chat_id = str(chat_id)
        if not chat_id.isdigit():
            logger.warning(f"⚠️ Skipping invalid subscriber ID: {chat_id}")
            return False
        
        try:
            await self._safe_send(bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown'
            ))
            return True
        except TelegramError as e:
            error_str = str(e).lower()
            logger.error(f"Failed to send to user {chat_id}: {e}")
            if "blocked" in error_str or "not found" in error_str or "deactivated" in error_str:
                self.state_manager.remove_subscriber(chat_id)
                logger.info(f"Removed inactive subscriber: {chat_id}")
            return False
    
    async def send_to_all_subscribers(self, bot, text: str, photo_path: Optional[str] = None) -> None:
        photo_bytes = None
        if photo_path and os.path.exists(photo_path):
            try:
                with open(photo_path, 'rb') as f:
                    photo_bytes = f.read()
            except Exception as e:
                logger.error(f"Failed to read photo {photo_path}: {e}")
        
        async def send_to_one(chat_id: str, photo_data: Optional[bytes]):
            # Validate chat_id is numeric (not placeholder)
            if not str(chat_id).isdigit():
                logger.warning(f"⚠️ Skipping invalid subscriber ID: {chat_id}")
                self.state_manager.remove_subscriber(chat_id)
                return (chat_id, False, "invalid_id")
            
            try:
                if photo_data:
                    await self._safe_send(bot.send_photo(
                        chat_id=chat_id, 
                        photo=io.BytesIO(photo_data), 
                        caption=text, 
                        parse_mode='Markdown'
                    ))
                else:
                    await self._safe_send(bot.send_message(
                        chat_id=chat_id, 
                        text=text, 
                        parse_mode='Markdown'
                    ))
                return (chat_id, True, None)
            except TelegramError as e:
                error_str = str(e).lower()
                logger.error(f"Failed to send to {chat_id}: {e}")
                return (chat_id, False, error_str)
        
        subscribers_list = list(self.state_manager.subscribers.copy())
        
        if not subscribers_list:
            return
        
        batch_size = BotConfig.TELEGRAM_BATCH_SIZE
        for i in range(0, len(subscribers_list), batch_size):
            batch = subscribers_list[i:i+batch_size]
            results = await asyncio.gather(
                *[send_to_one(cid, photo_bytes) for cid in batch], 
                return_exceptions=True
            )
            
            for result in results:
                if isinstance(result, tuple):
                    chat_id, success, error = result
                    if not success and error:
                        if "blocked" in error or "not found" in error or "deactivated" in error:
                            self.state_manager.remove_subscriber(chat_id)
                            logger.info(f"Removed inactive subscriber: {chat_id}")
            
            if i + batch_size < len(subscribers_list):
                await asyncio.sleep(0.5)
    
    async def send_tracking_update(self, bot, current_price: float, signal_info: dict) -> None:
        """Send tracking updates for ALL active trades (manual OR global signals)
        
        This method ALWAYS loops through subscribers and tracks their active_trade.
        It works for both:
        - Manual signals (per-user active_trade, no global signal_info)
        - Global signals (all users get same signal_info)
        
        Deduplication: Only updates when price changes by TRACKING_PRICE_DELTA or every 10 calls
        """
        # Increment counter for forced updates
        self._tracking_update_counter += 1
        force_update = (self._tracking_update_counter % 10 == 0)
        
        subscribers = list(self.state_manager.subscribers)
        sent_count = 0
        failed_users = []
        
        for chat_id in subscribers:
            # Validate chat_id is numeric (not placeholder like "user1", "user2")
            if not str(chat_id).isdigit():
                logger.warning(f"⚠️ Skipping invalid subscriber ID: {chat_id}")
                failed_users.append(chat_id)
                self.state_manager.remove_subscriber(chat_id)
                continue
            
            user_state = self.state_manager.get_user_state(chat_id)
            active_trade = user_state.get('active_trade')
            if not active_trade:
                continue
            
            # Debounce: Skip if price hasn't changed much and not time for forced update
            last_price = self._last_tracking_price.get(chat_id)
            price_delta = abs(current_price - last_price) if last_price else float('inf')
            should_update = force_update or price_delta >= BotConfig.TRACKING_PRICE_DELTA
            
            if last_price is not None and not should_update:
                continue  # Skip this user, price hasn't changed enough
            
            self._last_tracking_price[chat_id] = current_price  # Update last price
            
            direction = active_trade['direction']
            entry = active_trade['entry_price']
            tp1 = active_trade['tp1_level']
            tp2 = active_trade['tp2_level']
            sl = active_trade['sl_level']
            trade_status = active_trade.get('status', 'active')
            
            pnl_str = format_pnl(direction, entry, current_price)
            
            if direction == 'BUY':
                pnl_percent = ((current_price - entry) / entry) * 100
                max_win_percent = ((tp2 - entry) / entry) * 100
                max_loss_percent = ((sl - entry) / entry) * 100
                tp2_distance = tp2 - current_price
                tp2_progress = ((current_price - entry) / (tp2 - entry)) * 100 if tp2 != entry else 0
            else:
                pnl_percent = ((entry - current_price) / entry) * 100
                max_win_percent = ((entry - tp2) / entry) * 100
                max_loss_percent = ((entry - sl) / entry) * 100
                tp2_distance = current_price - tp2
                tp2_progress = ((entry - current_price) / (entry - tp2)) * 100 if entry != tp2 else 0
            
            dir_emoji = "📈" if direction == 'BUY' else "📉"
            
            if trade_status == 'tp1_hit':
                filled = int(tp2_progress / 10)
                empty = 10 - filled
                progress_bar = "█" * filled + "░" * empty
                tracking_text = (
                    f"📍 *TRACKING - AWAITING TP2*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{dir_emoji} Arah: *{direction}*\n"
                    f"💰 Harga Sekarang: *${current_price:.3f}*\n"
                    f"💵 Entry Anda: *${entry:.3f}*\n\n"
                    f"✅ *TP1 SUDAH TERCAPAI!*\n"
                    f"🎯 TP1: ${tp1:.3f} ✓\n"
                    f"🏆 Target TP2: ${tp2:.3f}\n"
                    f"📏 Jarak ke TP2: ${abs(tp2_distance):.3f}\n"
                    f"📊 Progress: {tp2_progress:.1f}%\n"
                    f"{progress_bar}\n\n"
                    f"🛡️ SL (Break Even): ${entry:.3f}\n"
                    f"💹 P&L Saat Ini: *{pnl_str}*\n"
                    f"🔒 Min. Profit Terjamin: +$3.00"
                )
            else:
                tracking_text = (
                    f"📍 *TRACKING UPDATE*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"{dir_emoji} Arah: *{direction}*\n"
                    f"💰 Harga Sekarang: *${current_price:.3f}*\n"
                    f"💵 Entry Anda: *${entry:.3f}*\n\n"
                    f"🎯 TP1: ${tp1:.3f}\n"
                    f"🏆 TP2: ${tp2:.3f}\n"
                    f"🛑 SL: ${sl:.3f}\n\n"
                    f"📊 Status: *🔥 Aktif*\n"
                    f"💹 P&L Anda: *{pnl_str}*\n"
                    f"📈 Max Win: {max_win_percent:+.2f}% | 📉 Max Loss: {max_loss_percent:.2f}%"
                )
            
            try:
                tracking_msg_id = user_state.get('tracking_message_id')
                sent = False
                
                if tracking_msg_id:
                    # Try to edit existing message
                    try:
                        result = await self._safe_send(bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=tracking_msg_id,
                            text=tracking_text,
                            parse_mode='Markdown'
                        ))
                        if result:
                            sent = True
                            sent_count += 1
                    except Exception as e:
                        logger.debug(f"Edit message failed for {chat_id}, will send new: {e}")
                        # Fall through to send new message
                
                if not sent:
                    # Send new message
                    try:
                        msg = await self._safe_send(bot.send_message(
                            chat_id=chat_id,
                            text=tracking_text,
                            parse_mode='Markdown'
                        ))
                        if msg:
                            user_state['tracking_message_id'] = msg.message_id
                            self.state_manager.save_user_states()
                            sent = True
                            sent_count += 1
                        else:
                            logger.warning(f"⚠️ Failed to send tracking message to {chat_id}")
                            failed_users.append(chat_id)
                    except Exception as e:
                        logger.warning(f"⚠️ Tracking send error for {chat_id}: {e}")
                        failed_users.append(chat_id)
            except Exception as e:
                logger.error(f"Tracking update error for {chat_id}: {e}", exc_info=True)
    
    async def send_daily_summary(self, bot) -> None:
        today_stats = self.state_manager.get_today_stats()
        trade_stats = self.state_manager.get_trade_stats()
        
        summary_text = (
            f"📊 *RINGKASAN HARIAN*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 {datetime.datetime.now(BotConfig.WIB_TZ).strftime('%d %B %Y')}\n\n"
            f"*Statistik Hari Ini:*\n"
            f"├ Total Sinyal: {today_stats['total']}\n"
            f"├ ✅ Win: {today_stats['wins']}\n"
            f"├ ❌ Loss: {today_stats['losses']}\n"
            f"├ ⚖️ Break Even: {today_stats['break_evens']}\n"
            f"└ 🎯 Win Rate: {today_stats['win_rate']:.1f}%\n\n"
            f"*Statistik Keseluruhan:*\n"
            f"├ Total Trade: {trade_stats['total_trades']}\n"
            f"└ Win Rate: {trade_stats['win_rate']:.1f}%\n\n"
            f"💡 Tetap disiplin dan ikuti money management!"
        )
        
        await self.send_to_all_subscribers(bot, summary_text)
        logger.info("Daily summary sent to all subscribers")

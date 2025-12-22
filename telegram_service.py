import asyncio
import datetime
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
    
    async def _rate_limited_send(self, coro):
        async with self._rate_limit_lock:
            now = asyncio.get_event_loop().time()
            time_since_last = now - self._last_send_time
            if time_since_last < BotConfig.TELEGRAM_RATE_LIMIT_DELAY:
                await asyncio.sleep(BotConfig.TELEGRAM_RATE_LIMIT_DELAY - time_since_last)
            self._last_send_time = asyncio.get_event_loop().time()
            return await coro
    
    async def _safe_send(self, coro, retries: int = 3):
        for attempt in range(retries):
            try:
                return await self._rate_limited_send(coro)
            except RetryAfter as e:
                retry_after = e.retry_after if isinstance(e.retry_after, (int, float)) else 5
                wait_time = retry_after + 1
                logger.warning(f"Rate limited, waiting {wait_time}s")
                await asyncio.sleep(wait_time)
            except TimedOut:
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                    continue
                raise
            except TelegramError as e:
                if "blocked" in str(e).lower() or "not found" in str(e).lower():
                    raise
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                    continue
                raise
        return None
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        chat_id = str(update.message.chat_id)
        
        self.state_manager.get_user_state(chat_id)
        
        keyboard = [
            [InlineKeyboardButton("📥 Subscribe", callback_data="subscribe"),
             InlineKeyboardButton("📤 Unsubscribe", callback_data="unsubscribe")],
            [InlineKeyboardButton("📊 Dashboard", callback_data="dashboard"),
             InlineKeyboardButton("📈 Stats", callback_data="stats")],
            [InlineKeyboardButton("🔄 Reset Data", callback_data="riset")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        subscribed = self.state_manager.is_subscriber(chat_id)
        status = "✅ AKTIF" if subscribed else "❌ TIDAK AKTIF"
        
        await update.message.reply_text(
            f"🏆 *Bot Sinyal XAU/USD V2.0 Pro*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌐 Data real-time dari Deriv WebSocket\n"
            f"📡 Strategi: EMA50 + RSI3 + ADX55\n\n"
            f"📋 Status Langganan: *{status}*\n\n"
            f"📌 *Menu Perintah:*\n"
            f"├ /subscribe - Mulai berlangganan\n"
            f"├ /unsubscribe - Berhenti langganan\n"
            f"├ /dashboard - Lihat posisi aktif\n"
            f"├ /signal - Lihat sinyal terakhir\n"
            f"├ /stats - Statistik trading Anda\n"
            f"├ /today - Statistik hari ini\n"
            f"├ /riset - Reset data trading Anda\n"
            f"└ /info - Info sistem\n\n"
            f"💡 Bot ini aktif 24 jam mencari sinyal terbaik!",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    
    async def subscribe(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        chat_id = str(update.message.chat_id)
        
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
        
        today_stats = self.state_manager.get_today_stats()
        
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
        
        today_stats = self.state_manager.get_today_stats()
        
        await update.message.reply_text(
            f"⚙️ *Info Sistem Bot V2.0 Pro*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📡 WebSocket: {status}\n"
            f"🏷️ Symbol: {gold_symbol or 'frxXAUUSD'}\n"
            f"💰 Harga Terakhir: {price_str}\n"
            f"👥 Total Subscriber: {subscriber_count}\n\n"
            f"{market_info}\n\n"
            f"📊 *Statistik Hari Ini:*\n"
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
        admin_chat_id = BotConfig.ADMIN_CHAT_ID
        
        if chat_id != admin_chat_id:
            await update.message.reply_text(
                "❌ *Akses Ditolak*\n\n"
                "Hanya admin yang bisa menggunakan /send command.",
                parse_mode='Markdown'
            )
            return
        
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
        
        success = await signal_engine.generate_manual_signal(context.bot)
        
        if success:
            await update.message.reply_text(
                "✅ *Signal Manual Berhasil Dibuat!*\n\n"
                "Signal sudah dikirim ke semua subscriber.\n"
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
    
    async def send_to_all_subscribers(self, bot, text: str, photo_path: Optional[str] = None) -> None:
        photo_bytes = None
        if photo_path and os.path.exists(photo_path):
            try:
                with open(photo_path, 'rb') as f:
                    photo_bytes = f.read()
            except Exception as e:
                logger.error(f"Failed to read photo {photo_path}: {e}")
        
        async def send_to_one(chat_id: str, photo_data: Optional[bytes]):
            try:
                if photo_data:
                    import io
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
        if not signal_info:
            return
        
        direction = signal_info['direction']
        entry = signal_info['entry_price']
        tp1 = signal_info['tp1_level']
        tp2 = signal_info['tp2_level']
        sl = signal_info['sl_level']
        trade_status = signal_info.get('status', 'active')
        
        pnl_str = format_pnl(direction, entry, current_price)
        dir_emoji = "📈" if direction == 'BUY' else "📉"
        status_display = "🛡️ BE Mode" if trade_status == 'tp1_hit' else "🔥 Aktif"
        
        tracking_text = (
            f"📍 *TRACKING UPDATE*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{dir_emoji} Arah: *{direction}*\n"
            f"💰 Harga Sekarang: *${current_price:.3f}*\n"
            f"💵 Entry: ${entry:.3f}\n\n"
            f"🎯 TP1: ${tp1:.3f}\n"
            f"🏆 TP2: ${tp2:.3f}\n"
            f"🛑 SL: ${sl:.3f}\n\n"
            f"📊 Status: *{status_display}*\n"
            f"💹 P&L: *{pnl_str}*"
        )
        
        for chat_id in list(self.state_manager.subscribers):
            user_state = self.state_manager.get_user_state(chat_id)
            if not user_state.get('active_trade'):
                continue
            
            try:
                tracking_msg_id = user_state.get('tracking_message_id')
                
                if tracking_msg_id:
                    try:
                        await self._safe_send(bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=tracking_msg_id,
                            text=tracking_text,
                            parse_mode='Markdown'
                        ))
                    except TelegramError:
                        msg = await self._safe_send(bot.send_message(
                            chat_id=chat_id,
                            text=tracking_text,
                            parse_mode='Markdown'
                        ))
                        if msg:
                            user_state['tracking_message_id'] = msg.message_id
                            self.state_manager.save_user_states()
                else:
                    msg = await self._safe_send(bot.send_message(
                        chat_id=chat_id,
                        text=tracking_text,
                        parse_mode='Markdown'
                    ))
                    if msg:
                        user_state['tracking_message_id'] = msg.message_id
                        self.state_manager.save_user_states()
            except TelegramError as e:
                logger.error(f"Failed to send tracking to {chat_id}: {e}")
    
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

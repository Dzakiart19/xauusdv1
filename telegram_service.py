import datetime
import os
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from config import BotConfig
from utils import format_pnl, get_win_rate_emoji, calculate_win_rate


logger = logging.getLogger("TelegramService")


class TelegramService:
    def __init__(self, state_manager, deriv_ws_getter, gold_symbol_getter):
        self.state_manager = state_manager
        self.deriv_ws_getter = deriv_ws_getter
        self.gold_symbol_getter = gold_symbol_getter
    
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
            f"💡 Gunakan /riset untuk reset statistik.\n"
            f"🤖 Bot bekerja 24 jam untuk Anda!",
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
        
        await update.message.reply_text(
            f"⚙️ *Info Sistem Bot*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📡 WebSocket: {status}\n"
            f"🏷️ Symbol: {gold_symbol or 'frxXAUUSD'}\n"
            f"💰 Harga Terakhir: {price_str}\n"
            f"👥 Total Subscriber: {subscriber_count}\n\n"
            f"{market_info}\n\n"
            f"📊 Data Source: Deriv\n"
            f"⏱️ Interval Analisis: ~10 detik\n"
            f"🔄 Tracking: Aktif saat ada posisi\n\n"
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
    
    async def send_dashboard(self, chat_id, bot):
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
            await bot.send_message(
                chat_id=chat_id,
                text=dashboard_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
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
    
    async def send_to_all_subscribers(self, bot, text, photo_path=None):
        async def send_to_one(chat_id):
            try:
                if photo_path and os.path.exists(photo_path):
                    with open(photo_path, 'rb') as photo_file:
                        await bot.send_photo(chat_id=chat_id, photo=photo_file, caption=text, parse_mode='Markdown')
                else:
                    await bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown')
                return (chat_id, True, None)
            except TelegramError as e:
                logger.error(f"Failed to send to {chat_id}: {e}")
                return (chat_id, False, str(e))
        
        import asyncio
        subscribers_list = list(self.state_manager.subscribers.copy())
        
        if not subscribers_list:
            return
        
        batch_size = 20
        for i in range(0, len(subscribers_list), batch_size):
            batch = subscribers_list[i:i+batch_size]
            results = await asyncio.gather(*[send_to_one(cid) for cid in batch], return_exceptions=True)
            
            for result in results:
                if isinstance(result, tuple):
                    chat_id, success, error = result
                    if not success and error:
                        if "blocked" in error.lower() or "not found" in error.lower():
                            self.state_manager.remove_subscriber(chat_id)
            
            if i + batch_size < len(subscribers_list):
                await asyncio.sleep(0.5)
    
    async def send_tracking_update(self, bot, current_price, signal_info):
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
        
        for chat_id in self.state_manager.subscribers.copy():
            user_state = self.state_manager.get_user_state(chat_id)
            if not user_state.get('active_trade'):
                continue
            
            try:
                tracking_msg_id = user_state.get('tracking_message_id')
                
                if tracking_msg_id:
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=tracking_msg_id,
                            text=tracking_text,
                            parse_mode='Markdown'
                        )
                    except:
                        msg = await bot.send_message(
                            chat_id=chat_id,
                            text=tracking_text,
                            parse_mode='Markdown'
                        )
                        user_state['tracking_message_id'] = msg.message_id
                        self.state_manager.save_user_states()
                else:
                    msg = await bot.send_message(
                        chat_id=chat_id,
                        text=tracking_text,
                        parse_mode='Markdown'
                    )
                    user_state['tracking_message_id'] = msg.message_id
                    self.state_manager.save_user_states()
            except TelegramError as e:
                logger.error(f"Failed to send tracking to {chat_id}: {e}")

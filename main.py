import asyncio
import signal
import sys

from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from config import BotConfig
from state_manager import StateManager
from telegram_service import TelegramService
from signal_engine import SignalEngine
from health_server import HealthServer, self_ping_loop
from utils import bot_logger


class GracefulShutdown:
    def __init__(self):
        self.shutdown_event = asyncio.Event()
        self.signal_engine = None
        self.application = None
        self.health_server = None
    
    def register_signal_engine(self, engine):
        self.signal_engine = engine
    
    def register_application(self, app):
        self.application = app
    
    def register_health_server(self, server):
        self.health_server = server
    
    async def shutdown(self):
        bot_logger.info("🛑 Initiating graceful shutdown...")
        
        if self.signal_engine:
            self.signal_engine.request_shutdown()
        
        self.shutdown_event.set()
        
        bot_logger.info("✅ Graceful shutdown complete")


shutdown_handler = GracefulShutdown()


def handle_signal(sig, frame):
    bot_logger.info(f"Received signal {sig}")
    asyncio.create_task(shutdown_handler.shutdown())


async def main():
    is_valid, errors = BotConfig.validate_config()
    if not is_valid:
        for error in errors:
            bot_logger.critical(f"❌ Config Error: {error}")
        return
    
    if 'YOUR_BOT_TOKEN' in BotConfig.TELEGRAM_BOT_TOKEN:
        bot_logger.critical("❌ Harap set TELEGRAM_BOT_TOKEN di environment variables!")
        bot_logger.info("💡 Export variable: TELEGRAM_BOT_TOKEN")
        return
    
    state_manager = StateManager()
    state_manager.load_subscribers()
    state_manager.load_user_states()
    
    signal_engine = SignalEngine(state_manager, None)
    shutdown_handler.register_signal_engine(signal_engine)
    
    telegram_service = TelegramService(
        state_manager,
        lambda: signal_engine.get_deriv_ws(),
        lambda: signal_engine.get_gold_symbol()
    )
    
    signal_engine.telegram_service = telegram_service
    
    health_server = HealthServer(
        state_manager,
        lambda: signal_engine.get_deriv_ws(),
        lambda: signal_engine
    )
    shutdown_handler.register_health_server(health_server)
    await health_server.start()
    
    ping_task = asyncio.create_task(self_ping_loop())
    
    application = Application.builder().token(BotConfig.TELEGRAM_BOT_TOKEN).build()
    shutdown_handler.register_application(application)
    
    # Force disconnect any old polling instances
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        bot_logger.info("🔄 Cleaned up old webhook/polling connections")
    except Exception as e:
        bot_logger.warning(f"⚠️ Webhook cleanup warning: {e}")
    
    application.add_handler(CommandHandler("start", telegram_service.start))
    application.add_handler(CommandHandler("subscribe", telegram_service.subscribe))
    application.add_handler(CommandHandler("unsubscribe", telegram_service.unsubscribe))
    application.add_handler(CommandHandler("stats", telegram_service.stats))
    application.add_handler(CommandHandler("today", telegram_service.today))
    application.add_handler(CommandHandler("riset", telegram_service.riset))
    application.add_handler(CommandHandler("info", telegram_service.info))
    application.add_handler(CommandHandler("dashboard", telegram_service.dashboard))
    application.add_handler(CommandHandler("signal", telegram_service.signal))
    application.add_handler(CommandHandler("send", telegram_service.send))
    application.add_handler(CallbackQueryHandler(telegram_service.button_callback))
    
    # Store signal_engine in bot_data for /send command
    application.bot_data['signal_engine'] = signal_engine
    
    signal_task = None
    
    async with application:
        await application.initialize()
        await application.start()
        if application.updater:
            await application.updater.start_polling()
        
        bot_logger.info("🚀 Bot dimulai! Otomatis mencari sinyal 24 jam...")
        bot_logger.info(f"🌐 Health server aktif di port {BotConfig.PORT}")
        bot_logger.info(f"📊 Unlimited Signals: {BotConfig.UNLIMITED_SIGNALS}")
        bot_logger.info(f"📈 Chart Generation: {BotConfig.GENERATE_CHARTS}")
        
        signal_task = asyncio.create_task(signal_engine.run(application.bot))
        
        try:
            done, pending = await asyncio.wait(
                [signal_task, asyncio.create_task(shutdown_handler.shutdown_event.wait())],
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        except asyncio.CancelledError:
            bot_logger.info("Main task cancelled")
        finally:
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
            
            if signal_task and not signal_task.done():
                signal_engine.request_shutdown()
                try:
                    await asyncio.wait_for(signal_task, timeout=10)
                except asyncio.TimeoutError:
                    signal_task.cancel()
                    try:
                        await signal_task
                    except asyncio.CancelledError:
                        pass
            
            if application.updater:
                await application.updater.stop()
            await application.stop()
            await health_server.cleanup()
            
            state_manager.save_user_states()
            state_manager.save_subscribers()
            state_manager.save_signal_history()
            
            bot_logger.info("👋 Bot stopped successfully")


if __name__ == '__main__':
    print("""
🏆 XAU/USD Scalping Signal Bot V2.0 Pro
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 Menggunakan Deriv WebSocket
🔄 Mode: 24 Jam Non-Stop + Unlimited Signals
📡 Strategi: EMA50 + RSI(3) + ADX(55)
💰 Money Management: SL $3 | TP $3 (1:1 Ratio)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    """)
    
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        
        for sig_name in ('SIGINT', 'SIGTERM'):
            try:
                loop.add_signal_handler(
                    getattr(signal, sig_name),
                    lambda: asyncio.create_task(shutdown_handler.shutdown())
                )
            except (NotImplementedError, AttributeError):
                pass
        
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        bot_logger.info("👋 Bot dihentikan oleh user.")
    except Exception as e:
        bot_logger.critical(f"❌ Error tak terduga: {e}", exc_info=True)
    finally:
        loop.close()

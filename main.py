import asyncio

from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from config import BotConfig
from state_manager import StateManager
from telegram_service import TelegramService
from signal_engine import SignalEngine
from health_server import HealthServer, self_ping_loop
from utils import bot_logger


async def main():
    if 'YOUR_BOT_TOKEN' in BotConfig.TELEGRAM_BOT_TOKEN:
        bot_logger.critical("❌ Harap set TELEGRAM_BOT_TOKEN di environment variables!")
        bot_logger.info("💡 Export variable: TELEGRAM_BOT_TOKEN")
        return
    
    state_manager = StateManager()
    state_manager.load_subscribers()
    state_manager.load_user_states()
    
    signal_engine = SignalEngine(state_manager, None)
    
    telegram_service = TelegramService(
        state_manager,
        lambda: signal_engine.get_deriv_ws(),
        lambda: signal_engine.get_gold_symbol()
    )
    
    signal_engine.telegram_service = telegram_service
    
    health_server = HealthServer(
        state_manager,
        lambda: signal_engine.get_deriv_ws()
    )
    await health_server.start()
    
    asyncio.create_task(self_ping_loop())
    
    application = Application.builder().token(BotConfig.TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", telegram_service.start))
    application.add_handler(CommandHandler("subscribe", telegram_service.subscribe))
    application.add_handler(CommandHandler("unsubscribe", telegram_service.unsubscribe))
    application.add_handler(CommandHandler("stats", telegram_service.stats))
    application.add_handler(CommandHandler("riset", telegram_service.riset))
    application.add_handler(CommandHandler("info", telegram_service.info))
    application.add_handler(CommandHandler("dashboard", telegram_service.dashboard))
    application.add_handler(CommandHandler("signal", telegram_service.signal))
    application.add_handler(CallbackQueryHandler(telegram_service.button_callback))
    
    signal_task = None
    
    async with application:
        await application.initialize()
        await application.start()
        if application.updater:
            await application.updater.start_polling()
        
        bot_logger.info("🚀 Bot dimulai! Otomatis mencari sinyal 24 jam...")
        bot_logger.info(f"🌐 Health server aktif di port {BotConfig.PORT}")
        
        signal_task = asyncio.create_task(signal_engine.run(application.bot))
        
        try:
            await signal_task
        except asyncio.CancelledError:
            bot_logger.info("Signal engine task cancelled")
        finally:
            if application.updater:
                await application.updater.stop()
            await application.stop()
            await health_server.cleanup()


if __name__ == '__main__':
    print("""
🏆 XAU/USD Signal Bot V1.2 - Modular Edition
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

import asyncio
import logging
from aiohttp import web, ClientSession

from config import BotConfig


logger = logging.getLogger("HealthServer")


class HealthServer:
    def __init__(self, state_manager, deriv_ws_getter):
        self.state_manager = state_manager
        self.deriv_ws_getter = deriv_ws_getter
        self.runner = None
    
    async def health_handler(self, request):
        deriv_ws = self.deriv_ws_getter()
        return web.json_response({
            "status": "ok",
            "subscribers": len(self.state_manager.subscribers),
            "websocket_connected": deriv_ws.connected if deriv_ws else False,
            "current_price": deriv_ws.get_current_price() if deriv_ws else None
        })
    
    async def start(self):
        app = web.Application()
        app.router.add_get('/health', self.health_handler)
        app.router.add_get('/', self.health_handler)
        
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '0.0.0.0', BotConfig.PORT)
        await site.start()
        logger.info(f"Health server started on port {BotConfig.PORT}")
        return self.runner
    
    async def cleanup(self):
        if self.runner:
            await self.runner.cleanup()


async def self_ping_loop():
    from aiohttp import ClientTimeout
    await asyncio.sleep(30)
    while True:
        try:
            async with ClientSession() as session:
                async with session.get(f"http://localhost:{BotConfig.PORT}/health", timeout=ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        logger.debug("Self-ping successful")
        except Exception as e:
            logger.warning(f"Self-ping failed: {e}")
        await asyncio.sleep(300)

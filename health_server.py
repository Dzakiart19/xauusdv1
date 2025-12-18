import asyncio
import logging
import time
import sys
from aiohttp import web, ClientSession

from config import BotConfig


logger = logging.getLogger("HealthServer")


class HealthServer:
    def __init__(self, state_manager, deriv_ws_getter, signal_engine_getter=None):
        self.state_manager = state_manager
        self.deriv_ws_getter = deriv_ws_getter
        self.signal_engine_getter = signal_engine_getter
        self.runner = None
        self.start_time = time.time()
    
    async def health_handler(self, request):
        deriv_ws = self.deriv_ws_getter()
        
        ws_stats = {}
        tick_age = None
        if deriv_ws:
            if hasattr(deriv_ws, 'get_connection_stats'):
                ws_stats = deriv_ws.get_connection_stats()
            if hasattr(deriv_ws, 'last_tick_received') and deriv_ws.last_tick_received:
                tick_age = round(time.time() - deriv_ws.last_tick_received, 1)
        
        uptime = time.time() - self.start_time
        
        trade_stats = self.state_manager.get_trade_stats()
        
        signal_stats = {}
        if self.signal_engine_getter:
            signal_engine = self.signal_engine_getter()
            if signal_engine:
                signal_stats = {
                    'total_generated': signal_engine.total_signals_generated,
                    'history_count': len(signal_engine.signal_history),
                    'cooldown_seconds': signal_engine.signal_cooldown_seconds,
                }
        
        memory_mb = 0
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            memory_mb = round(usage.ru_maxrss / 1024, 1)
        except ImportError:
            try:
                import os
                with open('/proc/self/status', 'r') as f:
                    for line in f:
                        if line.startswith('VmRSS:'):
                            memory_mb = round(int(line.split()[1]) / 1024, 1)
                            break
            except:
                pass
        except:
            pass
        
        return web.json_response({
            "status": "ok",
            "version": "1.3",
            "uptime_seconds": round(uptime, 0),
            "uptime_human": self._format_uptime(uptime),
            "subscribers": len(self.state_manager.subscribers),
            "memory_mb": memory_mb,
            "websocket": {
                "connected": deriv_ws.connected if deriv_ws else False,
                "current_price": deriv_ws.get_current_price() if deriv_ws and deriv_ws.connected else None,
                "tick_age_seconds": tick_age,
                **ws_stats
            },
            "trading": {
                "active_signal": bool(self.state_manager.current_signal),
                "total_wins": trade_stats.get('wins', 0),
                "total_losses": trade_stats.get('losses', 0),
                "total_be": trade_stats.get('break_evens', 0),
                "win_rate": trade_stats.get('win_rate', 0),
            },
            "signals": signal_stats,
            "config": {
                "analysis_interval": BotConfig.ANALYSIS_INTERVAL,
                "charts_enabled": BotConfig.GENERATE_CHARTS,
                "unlimited_signals": BotConfig.UNLIMITED_SIGNALS,
                "min_consensus": BotConfig.MIN_INDICATOR_CONSENSUS,
            }
        })
    
    def _format_uptime(self, seconds: float) -> str:
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        if days > 0:
            return f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    
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
    interval = BotConfig.KEEP_ALIVE_INTERVAL
    timeout = ClientTimeout(total=10)
    
    logger.info(f"Keep-alive loop started (interval: {interval}s)")
    
    async with ClientSession(timeout=timeout) as session:
        while True:
            try:
                async with session.get(f"http://localhost:{BotConfig.PORT}/health") as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        memory = data.get('memory_mb', 0)
                        subs = data.get('subscribers', 0)
                        logger.debug(f"Keep-alive OK (mem: {memory}MB, subs: {subs})")
            except Exception as e:
                logger.warning(f"Keep-alive ping failed: {e}")
            await asyncio.sleep(interval)

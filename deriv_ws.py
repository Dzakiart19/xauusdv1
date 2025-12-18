import asyncio
import json
import logging
import random
import time
from typing import Callable, Optional, Any
import websockets
from collections import deque

logger = logging.getLogger("DerivWS")

DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"
XAUUSD_SYMBOL = "frxXAUUSD"


class DerivWebSocket:
    def __init__(self, on_tick_callback: Optional[Callable] = None):
        self.ws: Optional[Any] = None
        self.on_tick_callback = on_tick_callback
        self.connected: bool = False
        self.current_price: Optional[float] = None
        self.price_history: deque = deque(maxlen=200)
        self.last_tick_time: Optional[int] = None
        self.last_tick_received: Optional[float] = None
        self.reconnect_attempts: int = 0
        self.max_reconnect_attempts: int = 15
        self.base_reconnect_delay: float = 2
        self.max_reconnect_delay: float = 60
        self.candles_response: Optional[dict] = None
        self.candles_event: asyncio.Event = asyncio.Event()
        self.listening: bool = False
        self.watchdog_timeout: int = 60
        self.total_reconnects: int = 0
        self.connection_start_time: Optional[float] = None
        self._watchdog_task: Optional[asyncio.Task] = None
        self._closing: bool = False
        
    def _get_jittered_delay(self, attempt: int) -> float:
        base_delay = min(self.base_reconnect_delay * (2 ** attempt), self.max_reconnect_delay)
        jitter = random.uniform(0, 0.3 * base_delay)
        return base_delay + jitter
        
    async def connect(self) -> bool:
        if self._closing:
            return False
            
        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                delay = self._get_jittered_delay(self.reconnect_attempts)
                if self.reconnect_attempts > 0:
                    logger.info(f"Waiting {delay:.1f}s before reconnect (jittered backoff)...")
                    await asyncio.sleep(delay)
                
                logger.info(f"Connecting to Deriv WebSocket... (attempt {self.reconnect_attempts + 1})")
                self.ws = await asyncio.wait_for(
                    websockets.connect(
                        DERIV_WS_URL,
                        ping_interval=30,
                        ping_timeout=10,
                        close_timeout=5
                    ),
                    timeout=30
                )
                self.connected = True
                self.reconnect_attempts = 0
                self.connection_start_time = time.time()
                self.last_tick_received = time.time()
                
                if self.total_reconnects > 0:
                    logger.info(f"Reconnected to Deriv WebSocket (total reconnects: {self.total_reconnects})")
                else:
                    logger.info("Connected to Deriv WebSocket successfully")
                
                self.total_reconnects += 1
                return True
            except asyncio.TimeoutError:
                self.reconnect_attempts += 1
                logger.error(f"Connection timeout (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")
            except Exception as e:
                self.reconnect_attempts += 1
                logger.error(f"Connection failed: {e}. (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")
        
        logger.critical("Max reconnection attempts reached")
        return False

    async def subscribe_ticks(self, symbol: str = XAUUSD_SYMBOL) -> bool:
        if not self.connected or not self.ws:
            logger.error("Not connected to WebSocket")
            return False
        
        try:
            request = {
                "ticks": symbol,
                "subscribe": 1
            }
            await self.ws.send(json.dumps(request))
            logger.info(f"Subscribed to {symbol} ticks")
            return True
        except Exception as e:
            logger.error(f"Failed to subscribe: {e}")
            return False

    async def get_candles(self, symbol: str = XAUUSD_SYMBOL, count: int = 200, granularity: int = 60) -> Optional[list]:
        if not self.connected or not self.ws:
            logger.error("Not connected to WebSocket")
            return None
        
        try:
            self.candles_event.clear()
            self.candles_response = None
            
            request = {
                "ticks_history": symbol,
                "adjust_start_time": 1,
                "count": count,
                "end": "latest",
                "granularity": granularity,
                "style": "candles"
            }
            await self.ws.send(json.dumps(request))
            
            try:
                await asyncio.wait_for(self.candles_event.wait(), timeout=15)
            except asyncio.TimeoutError:
                logger.error("Timeout waiting for candles")
                return None
            
            if self.candles_response and "candles" in self.candles_response:
                return self.candles_response["candles"]
            
            if self.candles_response and "error" in self.candles_response:
                logger.error(f"Candles error: {self.candles_response['error']['message']}")
            
            return None
        except Exception as e:
            logger.error(f"Failed to get candles: {e}")
            return None

    async def get_active_symbols(self) -> Optional[list]:
        if not self.connected or not self.ws:
            return None
        
        try:
            request = {
                "active_symbols": "brief",
                "product_type": "basic"
            }
            await self.ws.send(json.dumps(request))
            
            response = await asyncio.wait_for(self.ws.recv(), timeout=15)
            data = json.loads(response)
            
            if "active_symbols" in data:
                return data["active_symbols"]
            return None
        except asyncio.TimeoutError:
            logger.error("Timeout waiting for active symbols")
            return None
        except Exception as e:
            logger.error(f"Failed to get active symbols: {e}")
            return None

    async def _watchdog(self) -> None:
        while self.connected and not self._closing:
            await asyncio.sleep(self.watchdog_timeout / 2)
            
            if not self.connected or self._closing:
                break
                
            if self.last_tick_received:
                time_since_tick = time.time() - self.last_tick_received
                if time_since_tick > self.watchdog_timeout:
                    logger.warning(f"Watchdog: No tick for {time_since_tick:.0f}s, connection may be stale")
                    try:
                        pong_received = await self.send_ping()
                        if not pong_received:
                            logger.error("Watchdog: Ping failed, marking connection as dead")
                            self.connected = False
                            break
                        else:
                            logger.info("Watchdog: Ping succeeded, connection alive")
                    except Exception as e:
                        logger.error(f"Watchdog: Error during ping: {e}")
                        self.connected = False
                        break

    def start_watchdog(self) -> None:
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
        self._watchdog_task = asyncio.create_task(self._watchdog())
        logger.info("Watchdog timer started")

    def stop_watchdog(self) -> None:
        if self._watchdog_task:
            self._watchdog_task.cancel()
            self._watchdog_task = None

    async def listen(self) -> None:
        if not self.ws:
            return
        
        if self.listening:
            logger.warning("Already listening, skipping...")
            return
        
        self.listening = True
        self.start_watchdog()
        
        try:
            async for message in self.ws:
                if self._closing:
                    break
                    
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received: {message[:100]}")
                    continue
                
                if "tick" in data:
                    tick = data["tick"]
                    self.current_price = float(tick["quote"])
                    self.last_tick_time = tick["epoch"]
                    self.last_tick_received = time.time()
                    
                    tick_data = {
                        "price": self.current_price,
                        "epoch": self.last_tick_time,
                        "symbol": tick.get("symbol", XAUUSD_SYMBOL)
                    }
                    self.price_history.append(tick_data)
                    
                    if self.on_tick_callback:
                        try:
                            await self.on_tick_callback(tick_data)
                        except Exception as e:
                            logger.error(f"Tick callback error: {e}")
                
                elif "candles" in data or ("error" in data and "ticks_history" in str(data.get("echo_req", {}))):
                    self.candles_response = data
                    self.candles_event.set()
                
                elif "pong" in data:
                    logger.debug("Pong received from server")
                
                elif "error" in data:
                    error_msg = data.get('error', {}).get('message', 'Unknown error')
                    logger.error(f"WebSocket error: {error_msg}")
                    
        except websockets.ConnectionClosed as e:
            logger.warning(f"Connection closed: {e}")
            self.connected = False
        except asyncio.CancelledError:
            logger.info("Listen task cancelled")
        except Exception as e:
            logger.error(f"Listen error: {e}")
            self.connected = False
        finally:
            self.listening = False
            self.stop_watchdog()

    async def send_ping(self) -> bool:
        if self.ws and self.connected:
            try:
                await asyncio.wait_for(
                    self.ws.send(json.dumps({"ping": 1})),
                    timeout=5
                )
                return True
            except asyncio.TimeoutError:
                logger.error("Ping timeout")
                return False
            except Exception as e:
                logger.error(f"Ping failed: {e}")
                return False
        return False

    async def close(self) -> None:
        self._closing = True
        self.stop_watchdog()
        if self.ws:
            try:
                await asyncio.wait_for(self.ws.close(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("WebSocket close timeout")
            except Exception as e:
                logger.warning(f"WebSocket close error: {e}")
            finally:
                self.connected = False
                self.listening = False
                logger.info("WebSocket connection closed")

    def get_current_price(self) -> Optional[float]:
        return self.current_price

    def get_price_history(self) -> list:
        return list(self.price_history)

    def get_connection_stats(self) -> dict:
        uptime = 0
        if self.connection_start_time:
            uptime = time.time() - self.connection_start_time
        
        return {
            "connected": self.connected,
            "uptime_seconds": uptime,
            "total_reconnects": self.total_reconnects,
            "current_price": self.current_price,
            "last_tick_time": self.last_tick_time,
            "price_history_size": len(self.price_history)
        }


async def find_gold_symbol() -> list:
    ws = DerivWebSocket()
    try:
        if await ws.connect():
            symbols = await ws.get_active_symbols()
            await ws.close()
            
            if symbols:
                gold_symbols = [s for s in symbols if s.get('symbol', '') == 'frxXAUUSD'
                              or ('gold' in s.get('display_name', '').lower() and 'xau' in s.get('symbol', '').lower())]
                if gold_symbols:
                    return gold_symbols
                for s in symbols:
                    if 'xauusd' in s.get('symbol', '').lower():
                        return [s]
    except Exception as e:
        logger.error(f"Error finding gold symbol: {e}")
    finally:
        if ws.connected:
            await ws.close()
    
    return [{'symbol': 'frxXAUUSD', 'display_name': 'Gold/USD'}]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        print("Testing XAU/USD connection...")
        
        async def on_tick(data):
            print(f"Tick: {data['price']}")
        
        ws = DerivWebSocket(on_tick_callback=on_tick)
        if await ws.connect():
            await ws.subscribe_ticks("frxXAUUSD")
            
            listen_task = asyncio.create_task(ws.listen())
            
            await asyncio.sleep(2)
            
            print("\nGetting candles...")
            candles = await ws.get_candles("frxXAUUSD", count=10)
            if candles and isinstance(candles, list):
                print(f"Got {len(candles)} candles")
                for c in list(candles)[-3:]:
                    print(f"  Close: {c['close']}")
            
            print("\nConnection stats:")
            print(ws.get_connection_stats())
            
            await asyncio.sleep(5)
            listen_task.cancel()
            await ws.close()
    
    asyncio.run(test())

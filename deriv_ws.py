import asyncio
import json
import logging
from typing import Callable, Optional
import websockets
from collections import deque

logger = logging.getLogger("DerivWS")

DERIV_WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"
XAUUSD_SYMBOL = "frxXAUUSD"

class DerivWebSocket:
    def __init__(self, on_tick_callback: Optional[Callable] = None):
        self.ws = None
        self.on_tick_callback = on_tick_callback
        self.connected = False
        self.current_price = None
        self.price_history = deque(maxlen=200)
        self.last_tick_time = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 15
        self.base_reconnect_delay = 2
        self.max_reconnect_delay = 60
        self.candles_response = None
        self.candles_event = asyncio.Event()
        self.listening = False
        
    async def connect(self):
        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                logger.info(f"Connecting to Deriv WebSocket... (attempt {self.reconnect_attempts + 1})")
                self.ws = await websockets.connect(
                    DERIV_WS_URL,
                    ping_interval=30,
                    ping_timeout=10,
                    close_timeout=5
                )
                self.connected = True
                self.reconnect_attempts = 0
                logger.info("Connected to Deriv WebSocket successfully")
                return True
            except Exception as e:
                self.reconnect_attempts += 1
                delay = min(self.base_reconnect_delay * (2 ** self.reconnect_attempts), self.max_reconnect_delay)
                logger.error(f"Connection failed: {e}. Retrying in {delay}s... (exponential backoff)")
                await asyncio.sleep(delay)
        
        logger.critical("Max reconnection attempts reached")
        return False

    async def subscribe_ticks(self, symbol: str = XAUUSD_SYMBOL):
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

    async def get_candles(self, symbol: str = XAUUSD_SYMBOL, count: int = 200, granularity: int = 60):
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

    async def get_active_symbols(self):
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
        except Exception as e:
            logger.error(f"Failed to get active symbols: {e}")
            return None

    async def listen(self):
        if not self.ws:
            return
        
        if self.listening:
            logger.warning("Already listening, skipping...")
            return
        
        self.listening = True
        
        try:
            async for message in self.ws:
                data = json.loads(message)
                
                if "tick" in data:
                    tick = data["tick"]
                    self.current_price = float(tick["quote"])
                    self.last_tick_time = tick["epoch"]
                    
                    tick_data = {
                        "price": self.current_price,
                        "epoch": self.last_tick_time,
                        "symbol": tick.get("symbol", XAUUSD_SYMBOL)
                    }
                    self.price_history.append(tick_data)
                    
                    if self.on_tick_callback:
                        await self.on_tick_callback(tick_data)
                
                elif "candles" in data or ("error" in data and "ticks_history" in str(data.get("echo_req", {}))):
                    self.candles_response = data
                    self.candles_event.set()
                
                elif "error" in data:
                    logger.error(f"WebSocket error: {data['error']['message']}")
                    
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

    async def send_ping(self):
        if self.ws and self.connected:
            try:
                await self.ws.send(json.dumps({"ping": 1}))
                return True
            except:
                return False
        return False

    async def close(self):
        if self.ws:
            await self.ws.close()
            self.connected = False
            self.listening = False
            logger.info("WebSocket connection closed")

    def get_current_price(self) -> Optional[float]:
        return self.current_price

    def get_price_history(self) -> list:
        return list(self.price_history)


async def find_gold_symbol():
    ws = DerivWebSocket()
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
            
            await asyncio.sleep(5)
            listen_task.cancel()
            await ws.close()
    
    asyncio.run(test())

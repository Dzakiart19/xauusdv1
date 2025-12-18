import asyncio
import json
import logging
from typing import Callable, Optional
import websockets
from collections import deque
import time

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
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5
        
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
                logger.error(f"Connection failed: {e}. Retrying in {self.reconnect_delay}s...")
                await asyncio.sleep(self.reconnect_delay)
        
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
            request = {
                "ticks_history": symbol,
                "adjust_start_time": 1,
                "count": count,
                "end": "latest",
                "granularity": granularity,
                "style": "candles"
            }
            await self.ws.send(json.dumps(request))
            
            response = await asyncio.wait_for(self.ws.recv(), timeout=15)
            data = json.loads(response)
            
            if "error" in data:
                logger.error(f"Candles error: {data['error']['message']}")
                return None
            
            if "candles" in data:
                return data["candles"]
            
            return None
        except asyncio.TimeoutError:
            logger.error("Timeout getting candles")
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
                
                elif "error" in data:
                    logger.error(f"WebSocket error: {data['error']['message']}")
                    
        except websockets.ConnectionClosed as e:
            logger.warning(f"Connection closed: {e}")
            self.connected = False
        except Exception as e:
            logger.error(f"Listen error: {e}")
            self.connected = False

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
            gold_symbols = [s for s in symbols if 'gold' in s.get('display_name', '').lower() 
                          or 'xau' in s.get('symbol', '').lower()
                          or 'xau' in s.get('display_name', '').lower()]
            return gold_symbols
    return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    async def test():
        print("Finding gold symbols...")
        gold = await find_gold_symbol()
        for s in gold:
            print(f"  - {s.get('symbol')}: {s.get('display_name')}")
        
        if gold:
            symbol = gold[0].get('symbol')
            print(f"\nTesting with symbol: {symbol}")
            
            async def on_tick(data):
                print(f"Tick: {data['price']}")
            
            ws = DerivWebSocket(on_tick_callback=on_tick)
            if await ws.connect():
                await ws.subscribe_ticks(symbol)
                
                listen_task = asyncio.create_task(ws.listen())
                await asyncio.sleep(10)
                listen_task.cancel()
                await ws.close()
    
    asyncio.run(test())

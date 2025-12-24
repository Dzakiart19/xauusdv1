import logging
import os
import datetime
import asyncio
from typing import Optional, Any
from functools import wraps

import pandas as pd
import pandas_ta as ta

from config import BotConfig


class NoHttpxFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return 'httpx' not in record.name and 'HTTP Request' not in record.getMessage()


def setup_logging() -> logging.Logger:
    bot_logger = logging.getLogger("BotScalping")
    bot_logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    bot_logger.addHandler(stream_handler)
    
    file_handler = logging.FileHandler(BotConfig.LOG_FILENAME)
    file_handler.setFormatter(formatter)
    bot_logger.addHandler(file_handler)
    
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("pandas_ta").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    
    return bot_logger


bot_logger = setup_logging()


def async_retry(max_retries: int = 3, delay: float = 1.0, exceptions: tuple = (Exception,)):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception: Optional[Exception] = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        wait_time = delay * (2 ** attempt)
                        bot_logger.warning(f"Retry {attempt + 1}/{max_retries} for {func.__name__}: {e}")
                        await asyncio.sleep(wait_time)
            bot_logger.error(f"All {max_retries} retries failed for {func.__name__}: {last_exception}")
            if last_exception is not None:
                raise last_exception
            raise RuntimeError("Retry failed with unknown error")
        return wrapper
    return decorator


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df.ta.ema(length=BotConfig.MA_MEDIUM_PERIOD, append=True)
    df.ta.rsi(length=BotConfig.RSI_PERIOD, append=True)
    df.ta.adx(length=BotConfig.ADX_FILTER_PERIOD, append=True)
    df.ta.atr(length=BotConfig.ATR_PERIOD, append=True)
    return df


def format_pnl(direction: str, entry: float, current_price: Optional[float]) -> str:
    if current_price:
        if direction == 'BUY':
            pnl_pips = (current_price - entry) * 10
            pnl_percent = ((current_price - entry) / entry) * 100
        else:
            pnl_pips = (entry - current_price) * 10
            pnl_percent = ((entry - current_price) / entry) * 100
        
        pnl_emoji = "🟢" if pnl_pips >= 0 else "🔴"
        
        if pnl_percent >= 0:
            return f"{pnl_emoji} {pnl_pips:+.1f} pips | {pnl_percent:+.2f}%"
        else:
            return f"{pnl_emoji} {pnl_pips:+.1f} pips | {pnl_percent:.2f}%"
    return "N/A"


def get_win_rate_emoji(win_rate: float) -> str:
    if win_rate >= 60:
        return "🔥"
    elif win_rate >= 50:
        return "👍"
    return "📊"


def calculate_win_rate(win_count: int, loss_count: int) -> float:
    if (win_count + loss_count) > 0:
        return (win_count / (win_count + loss_count)) * 100
    return 0.0


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def sanitize_message(text: str) -> str:
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    result = text
    for char in special_chars:
        if char in ['_', '*']:
            continue
        result = result.replace(char, f'\\{char}')
    return result

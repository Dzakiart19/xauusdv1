import logging
import os
import datetime
import pandas as pd
import pandas_ta as ta
import mplfinance as mpf

from config import BotConfig


class NoHttpxFilter(logging.Filter):
    def filter(self, record):
        return 'httpx' not in record.name and 'HTTP Request' not in record.getMessage()


def setup_logging():
    bot_logger = logging.getLogger("BotV1.2")
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


def calculate_indicators(df):
    df.ta.stoch(k=BotConfig.STOCH_K, d=BotConfig.STOCH_D, smooth_k=BotConfig.STOCH_SMOOTH, append=True)
    df.ta.atr(length=BotConfig.ATR_PERIOD, append=True)
    df.ta.adx(length=BotConfig.ADX_FILTER_PERIOD, append=True)
    df.ta.ema(length=BotConfig.MA_SHORT_PERIOD, append=True)
    df.ta.rsi(length=BotConfig.RSI_PERIOD, append=True)
    return df


async def generate_chart(df, trade_info=None, title="XAU/USD Chart"):
    try:
        if len(df) < 50:
            bot_logger.warning("Not enough data for chart generation")
            return False
        
        chart_df = df.tail(100).copy()
        
        chart_style = mpf.make_mpf_style(
            base_mpf_style='charles',
            gridstyle='-',
            gridcolor='#2c3e50',
            facecolor='#1a1a2e',
            edgecolor='#ffffff',
            figcolor='#1a1a2e',
            rc={
                'axes.labelcolor': '#ffffff',
                'axes.edgecolor': '#ffffff',
                'xtick.color': '#ffffff',
                'ytick.color': '#ffffff',
                'text.color': '#ffffff',
                'figure.titlesize': 14,
                'axes.titlesize': 12
            }
        )
        
        hlines_dict = None
        if trade_info:
            entry = trade_info.get('entry_price')
            tp1 = trade_info.get('tp1_level')
            tp2 = trade_info.get('tp2_level')
            sl = trade_info.get('sl_level')
            
            if all([entry, tp1, tp2, sl]):
                hlines_dict = {
                    'hlines': [entry, tp1, tp2, sl],
                    'colors': ['#3498db', '#27ae60', '#9b59b6', '#e74c3c'],
                    'linestyle': ['--', '-', '-', '-'],
                    'linewidths': [1.5, 1.2, 1.2, 1.2]
                }
        
        fig, axes = mpf.plot(
            chart_df,
            type='candle',
            style=chart_style,
            title=title,
            ylabel='Harga (USD)',
            volume=False,
            figsize=(12, 8),
            hlines=hlines_dict,
            returnfig=True,
            tight_layout=True
        )
        
        if trade_info and hlines_dict:
            ax = axes[0]
            entry = trade_info.get('entry_price')
            tp1 = trade_info.get('tp1_level')
            tp2 = trade_info.get('tp2_level')
            sl = trade_info.get('sl_level')
            
            text_x = len(chart_df) * 1.01
            ax.text(text_x, entry, f'Entry ${entry:.2f}', color='#3498db', fontsize=8, va='center')
            ax.text(text_x, tp1, f'TP1 ${tp1:.2f}', color='#27ae60', fontsize=8, va='center')
            ax.text(text_x, tp2, f'TP2 ${tp2:.2f}', color='#9b59b6', fontsize=8, va='center')
            ax.text(text_x, sl, f'SL ${sl:.2f}', color='#e74c3c', fontsize=8, va='center')
        
        fig.savefig(BotConfig.CHART_FILENAME, dpi=150, bbox_inches='tight', facecolor='#1a1a2e')
        mpf.close(fig)
        
        return True
        
    except Exception as e:
        bot_logger.error(f"Chart generation failed: {e}")
        return False


def format_pnl(direction, entry, current_price):
    if current_price:
        if direction == 'BUY':
            pnl_pips = (current_price - entry) * 10
        else:
            pnl_pips = (entry - current_price) * 10
        pnl_emoji = "🟢" if pnl_pips >= 0 else "🔴"
        return f"{pnl_emoji} {pnl_pips:+.1f} pips"
    return "N/A"


def get_win_rate_emoji(win_rate):
    if win_rate >= 60:
        return "🔥"
    elif win_rate >= 50:
        return "👍"
    return "📊"


def calculate_win_rate(win_count, loss_count):
    if (win_count + loss_count) > 0:
        return (win_count / (win_count + loss_count)) * 100
    return 0.0

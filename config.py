import os
import datetime
import pytz


class BotConfig:
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')
    PORT = int(os.environ.get('PORT', 5000))
    GENERATE_CHARTS = os.environ.get('GENERATE_CHARTS', 'true').lower() == 'true'
    KEEP_ALIVE_INTERVAL = int(os.environ.get('KEEP_ALIVE_INTERVAL', 300))
    
    # NEW SCALPING STRATEGY - EMA 50, RSI 3, ADX 55
    # EMA 50: Trend Direction Filter
    MA_MEDIUM_PERIOD = 50
    
    # RSI 3: Entry Timing (more sensitive)
    RSI_PERIOD = 3
    RSI_OVERBOUGHT = 70
    RSI_OVERSOLD = 30
    # RSI Exit thresholds - entry when RSI exits extreme zone
    RSI_EXIT_OVERSOLD = 23  # Entry BUY when RSI rises above this after being oversold
    RSI_EXIT_OVERBOUGHT = 77  # Entry SELL when RSI drops below this after being overbought
    
    # ADX 55: Trend Strength Filter
    ADX_FILTER_PERIOD = 55
    ADX_FILTER_THRESHOLD = 30
    
    # Money Management: Fixed 3 USD target and stop loss
    FIXED_SL_USD = 3.0
    FIXED_TP_USD = 3.0
    LOT_SIZE = 0.01
    RISK_PER_TRADE_USD = 3.00
    
    # ATR for additional volatility context (kept for compatibility)
    ATR_PERIOD = 14
    
    # Analysis settings
    ANALYSIS_INTERVAL = 30
    ANALYSIS_JITTER = 10
    
    # Signal settings
    UNLIMITED_SIGNALS = True
    SIGNAL_COOLDOWN_SECONDS = 120
    
    # File names
    CHART_FILENAME = 'chart_scalping.png'
    USER_STATES_FILENAME = 'user_states.json'
    SUBSCRIBERS_FILENAME = 'subscribers.json'
    LOG_FILENAME = 'bot_scalping.log'
    
    # Timezone
    WIB_TZ = pytz.timezone('Asia/Jakarta')
    
    @classmethod
    def get_ema_medium_col(cls):
        return f'EMA_{cls.MA_MEDIUM_PERIOD}'
    
    @classmethod
    def get_rsi_col(cls):
        return f'RSI_{cls.RSI_PERIOD}'
    
    @classmethod
    def get_adx_col(cls):
        return f'ADX_{cls.ADX_FILTER_PERIOD}'
    
    @classmethod
    def get_atr_col(cls):
        return f'ATRr_{cls.ATR_PERIOD}'
    
    NY_TZ = pytz.timezone('America/New_York')
    MARKET_CLOSE_DAY = 4
    MARKET_CLOSE_HOUR = 17
    MARKET_OPEN_DAY = 6
    MARKET_OPEN_HOUR = 17
    MARKET_CHECK_INTERVAL = 300
    
    @classmethod
    def is_market_open(cls):
        now_ny = datetime.datetime.now(cls.NY_TZ)
        weekday = now_ny.weekday()
        hour = now_ny.hour
        
        if weekday == cls.MARKET_CLOSE_DAY and hour >= cls.MARKET_CLOSE_HOUR:
            return False
        if weekday == 5:
            return False
        if weekday == cls.MARKET_OPEN_DAY and hour < cls.MARKET_OPEN_HOUR:
            return False
        
        return True
    
    @classmethod
    def get_market_status(cls):
        now_ny = datetime.datetime.now(cls.NY_TZ)
        weekday = now_ny.weekday()
        hour = now_ny.hour
        
        if cls.is_market_open():
            return {
                'is_open': True,
                'status': '🟢 BUKA',
                'message': 'Market XAU/USD sedang aktif',
                'next_change': None
            }
        
        days_until_open = (cls.MARKET_OPEN_DAY - weekday) % 7
        if days_until_open == 0 and hour >= cls.MARKET_OPEN_HOUR:
            days_until_open = 7
        
        open_time = now_ny.replace(hour=cls.MARKET_OPEN_HOUR, minute=0, second=0, microsecond=0)
        open_time += datetime.timedelta(days=days_until_open)
        
        time_until = open_time - now_ny
        hours_left = int(time_until.total_seconds() // 3600)
        mins_left = int((time_until.total_seconds() % 3600) // 60)
        
        return {
            'is_open': False,
            'status': '🔴 TUTUP',
            'message': f'Market tutup (Weekend). Buka dalam ~{hours_left}j {mins_left}m',
            'next_open': open_time.strftime('%A %H:%M NY'),
            'hours_left': hours_left
        }

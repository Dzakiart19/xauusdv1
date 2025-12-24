import os
import datetime
import pytz


class BotConfig:
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')
    ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID', '')
    DERIV_API_TOKEN = os.environ.get('DERIV_API_TOKEN', '')
    PORT = int(os.environ.get('PORT', 5000))
    KEEP_ALIVE_INTERVAL = int(os.environ.get('KEEP_ALIVE_INTERVAL', 300))
    
    MA_MEDIUM_PERIOD = 50
    
    RSI_PERIOD = 3
    RSI_OVERBOUGHT = 70
    RSI_OVERSOLD = 30
    RSI_EXIT_OVERSOLD = 23
    RSI_EXIT_OVERBOUGHT = 77
    
    ADX_FILTER_PERIOD = 55
    ADX_FILTER_THRESHOLD = 22  # Sweet spot: balance between signal frequency (3-4/hr) and accuracy (65-75%)
    
    FIXED_SL_USD = 3.0
    FIXED_TP_USD = 3.0
    LOT_SIZE = 0.01
    RISK_PER_TRADE_USD = 3.00
    
    ATR_PERIOD = 14
    
    ANALYSIS_INTERVAL = 30
    ANALYSIS_JITTER = 5
    
    UNLIMITED_SIGNALS = True
    SIGNAL_COOLDOWN_SECONDS = 120
    
    USER_STATES_FILENAME = 'user_states.json'
    SUBSCRIBERS_FILENAME = 'subscribers.json'
    SIGNAL_HISTORY_FILENAME = 'signal_history.json'
    LOG_FILENAME = 'bot_scalping.log'
    
    WIB_TZ = pytz.timezone('Asia/Jakarta')
    
    TELEGRAM_RATE_LIMIT_DELAY = 0.05
    TELEGRAM_BATCH_SIZE = 25
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0
    
    DAILY_SUMMARY_HOUR = 21
    DAILY_SUMMARY_MINUTE = 0
    
    @classmethod
    def get_ema_medium_col(cls) -> str:
        return f'EMA_{cls.MA_MEDIUM_PERIOD}'
    
    @classmethod
    def get_rsi_col(cls) -> str:
        return f'RSI_{cls.RSI_PERIOD}'
    
    @classmethod
    def get_adx_col(cls) -> str:
        return f'ADX_{cls.ADX_FILTER_PERIOD}'
    
    @classmethod
    def get_atr_col(cls) -> str:
        return f'ATRr_{cls.ATR_PERIOD}'
    
    NY_TZ = pytz.timezone('America/New_York')
    MARKET_CLOSE_DAY = 4
    MARKET_CLOSE_HOUR = 17
    MARKET_OPEN_DAY = 6
    MARKET_OPEN_HOUR = 17
    MARKET_CHECK_INTERVAL = 300
    
    @classmethod
    def validate_config(cls) -> tuple[bool, list[str]]:
        errors = []
        if cls.TELEGRAM_BOT_TOKEN == 'YOUR_BOT_TOKEN':
            errors.append("TELEGRAM_BOT_TOKEN tidak dikonfigurasi")
        if cls.RSI_PERIOD < 1:
            errors.append("RSI_PERIOD harus >= 1")
        if cls.MA_MEDIUM_PERIOD < 1:
            errors.append("MA_MEDIUM_PERIOD harus >= 1")
        if cls.FIXED_SL_USD <= 0:
            errors.append("FIXED_SL_USD harus > 0")
        if cls.FIXED_TP_USD <= 0:
            errors.append("FIXED_TP_USD harus > 0")
        return len(errors) == 0, errors
    
    @classmethod
    def is_market_open(cls) -> bool:
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
    def get_market_status(cls) -> dict:
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

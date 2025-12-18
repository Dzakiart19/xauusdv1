import os
import datetime
import pytz


class BotConfig:
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')
    PORT = int(os.environ.get('PORT', 8000))
    
    STOCH_K = 8
    STOCH_D = 3
    STOCH_SMOOTH = 3
    ATR_PERIOD = 14
    ATR_MULTIPLIER = 1.8
    RR_TP1 = 1.0
    RR_TP2 = 1.5
    ADX_FILTER_PERIOD = 14
    ADX_FILTER_THRESHOLD = 15
    MA_SHORT_PERIOD = 21
    RSI_PERIOD = 14
    RSI_OVERBOUGHT = 70
    RSI_OVERSOLD = 30
    LOT_SIZE = 0.01
    RISK_PER_TRADE_USD = 2.00
    
    ANALYSIS_INTERVAL = 15
    ANALYSIS_JITTER = 5
    
    CHART_FILENAME = 'chart_v1.2.png'
    USER_STATES_FILENAME = 'user_states.json'
    SUBSCRIBERS_FILENAME = 'subscribers.json'
    LOG_FILENAME = 'bot_v1.2.log'
    
    WIB_TZ = pytz.timezone('Asia/Jakarta')
    
    @classmethod
    def get_stoch_k_col(cls):
        return f'STOCHk_{cls.STOCH_K}_{cls.STOCH_D}_{cls.STOCH_SMOOTH}'
    
    @classmethod
    def get_stoch_d_col(cls):
        return f'STOCHd_{cls.STOCH_K}_{cls.STOCH_D}_{cls.STOCH_SMOOTH}'
    
    @classmethod
    def get_adx_col(cls):
        return f'ADX_{cls.ADX_FILTER_PERIOD}'
    
    @classmethod
    def get_ema_col(cls):
        return f'EMA_{cls.MA_SHORT_PERIOD}'
    
    @classmethod
    def get_rsi_col(cls):
        return f'RSI_{cls.RSI_PERIOD}'
    
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

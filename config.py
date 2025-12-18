import os
import datetime
import pytz


class BotConfig:
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', 'YOUR_BOT_TOKEN')
    PORT = int(os.environ.get('PORT', 5000))
    GENERATE_CHARTS = os.environ.get('GENERATE_CHARTS', 'true').lower() == 'true'
    KEEP_ALIVE_INTERVAL = int(os.environ.get('KEEP_ALIVE_INTERVAL', 300))
    
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
    MA_MEDIUM_PERIOD = 50
    RSI_PERIOD = 14
    RSI_OVERBOUGHT = 70
    RSI_OVERSOLD = 30
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    BB_LENGTH = 20
    BB_MULT = 2
    LOT_SIZE = 0.01
    RISK_PER_TRADE_USD = 2.00
    
    ANALYSIS_INTERVAL = 30
    ANALYSIS_JITTER = 10
    
    UNLIMITED_SIGNALS = True
    MULTI_TIMEFRAME_ENABLED = True
    MIN_INDICATOR_CONSENSUS = 2
    SIGNAL_COOLDOWN_SECONDS = 120
    
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
    def get_ema_medium_col(cls):
        return f'EMA_{cls.MA_MEDIUM_PERIOD}'
    
    @classmethod
    def get_rsi_col(cls):
        return f'RSI_{cls.RSI_PERIOD}'
    
    @classmethod
    def get_atr_col(cls):
        return f'ATRr_{cls.ATR_PERIOD}'
    
    @classmethod
    def get_macd_cols(cls):
        return (f'MACD_{cls.MACD_FAST}_{cls.MACD_SLOW}_{cls.MACD_SIGNAL}',
                f'MACDh_{cls.MACD_FAST}_{cls.MACD_SLOW}_{cls.MACD_SIGNAL}',
                f'MACDs_{cls.MACD_FAST}_{cls.MACD_SLOW}_{cls.MACD_SIGNAL}')
    
    @classmethod
    def get_bb_cols(cls):
        return (f'BBL_{cls.BB_LENGTH}_{cls.BB_MULT}',
                f'BBM_{cls.BB_LENGTH}_{cls.BB_MULT}',
                f'BBU_{cls.BB_LENGTH}_{cls.BB_MULT}')
    
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

import os
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
    
    ANALYSIS_INTERVAL = 10
    ANALYSIS_JITTER = 3
    
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

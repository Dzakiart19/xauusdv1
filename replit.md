# XAU/USD Scalping Signal Bot - v2.0 (Scalping Strategy Edition)

## Overview
This project is a public Telegram bot designed to provide real-time XAU/USD (Gold) scalping signals using a simplified, high-probability trading strategy. The bot uses Deriv WebSocket data to deliver scalping entry signals with fixed stop loss and take profit targets to subscribers.

## User Preferences
I prefer simple language and detailed explanations. I want iterative development with clear communication at each step. **IMPORTANT: Signals should be unlimited with no restrictions. Strategy focused on scalping with fixed risk/reward (1:1 ratio).**

## New Scalping Strategy - v2.0
Simplified from multi-indicator consensus to a clean three-indicator scalping approach:

### Entry Rules:
1. **EMA 50 (Trend Direction)**
   - Price > EMA50 = Bullish bias → Look for BUY
   - Price < EMA50 = Bearish bias → Look for SELL

2. **RSI 3 (Entry Timing - High Sensitivity)**
   - RSI < 30 (Oversold) = Potential BUY entry
   - RSI > 70 (Overbought) = Potential SELL entry

3. **ADX 55 (Trend Strength Filter)**
   - ADX > 30 = Trend is strong enough → Allow entry
   - ADX ≤ 30 = Trend too weak → NO entry

### Money Management:
- **Fixed Stop Loss:** 3 USD below/above entry
- **Fixed Take Profit 1:** 3 USD above/below entry (1:1 ratio)
- **Fixed Take Profit 2:** 4.5 USD above/below entry (1.5:1 ratio)
- **Risk per Trade:** 3 USD
- **Lot Size:** 0.01

### Example Entries:
**BUY Entry:**
- Harga > EMA50 (bullish trend)
- RSI < 30 (oversold, buying pressure)
- ADX > 30 (strong trend)
→ Entry at current price, SL = Entry - $3, TP1 = Entry + $3, TP2 = Entry + $4.50

**SELL Entry:**
- Harga < EMA50 (bearish trend)
- RSI > 70 (overbought, selling pressure)
- ADX > 30 (strong trend)
→ Entry at current price, SL = Entry + $3, TP1 = Entry - $3, TP2 = Entry - $4.50

## System Architecture - v2.0
The bot remains modular with the same components as v1.3 but simplified indicator calculations:

### Core Components:
- `main.py`: Entry point and bot initialization
- `config.py`: Scalping strategy parameters (EMA50, RSI3, ADX55)
- `signal_engine.py`: Simplified scalping signal generation logic
- `telegram_service.py`: Telegram bot interactions and messaging
- `deriv_ws.py`: WebSocket connection to Deriv
- `utils.py`: Indicator calculations (simplified to only needed indicators)
- `health_server.py`: HTTP health check endpoint

### Key Changes in v2.0:
- **Simplified Indicators:** Only EMA50, RSI(3), ADX(55), ATR for context
- **Fixed Risk/Reward:** Removed dynamic ATR-based sizing → Fixed $3 SL/TP
- **Cleaner Signal Logic:** Removed Stochastic, MACD, Bollinger Bands consensus
- **Faster Analysis:** Reduced indicator calculation overhead
- **Better for Scalping:** Aggressive RSI(3) captures quick reversals

### Features Preserved:
- ✅ Unlimited signals (no daily limits)
- ✅ Real-time WebSocket data from Deriv (no API key required)
- ✅ Multi-subscriber support with Telegram
- ✅ Trade tracking with TP/SL management
- ✅ Win/Loss statistics per subscriber
- ✅ Weekend market closure detection
- ✅ Health check endpoint for deployment monitoring

## Deployment (Koyeb Free Tier - Optimized)
- **Docker Support**: Lightweight `Dockerfile` (python:3.11-slim)
- **Performance Optimizations**:
    - `GENERATE_CHARTS=false` (default): Reduces RAM by 70%
    - `ANALYSIS_INTERVAL=30s`: Chart generation disabled on free tier
    - `KEEP_ALIVE_INTERVAL=300s`: Health check every 5 min
- **Health Check**: Endpoint at `/health` for Koyeb liveness monitoring
- **Port**: 8000 for Koyeb compatibility
- **Environment Variables**:
    - `TELEGRAM_BOT_TOKEN` (required)
    - `GENERATE_CHARTS` (default: false for free tier)
    - `KEEP_ALIVE_INTERVAL` (default: 300)

## Recent Changes (v2.0 - December 2024)
- **UPDATED: Strategy Logic** - Switched from multi-indicator consensus to simple scalping (EMA50 + RSI3 + ADX55)
- **SIMPLIFIED: Indicators** - Removed Stochastic, MACD, Bollinger Bands
- **CHANGED: Money Management** - Fixed $3 SL/TP instead of dynamic ATR-based
- **OPTIMIZED: Analysis Loop** - Fewer calculations per cycle
- **IMPROVED: Signal Quality** - Cleaner entry conditions for scalping

## External Dependencies
- **Deriv WebSocket API:**
    - Endpoint: `wss://ws.derivws.com/websockets/v3?app_id=1089`
    - Data: Real-time XAU/USD price ticks and candles
    - Auth: No authentication required
- **Telegram Bot API:**
    - Requires `TELEGRAM_BOT_TOKEN` environment variable

## File Structure
```
.
├── main.py                  # Entry point
├── config.py                # Scalping strategy parameters
├── signal_engine.py         # Signal generation (NEW SCALPING LOGIC)
├── telegram_service.py      # Telegram interactions
├── deriv_ws.py              # WebSocket management
├── utils.py                 # Indicator calculations (SIMPLIFIED)
├── health_server.py         # Health check endpoint
├── requirements.txt         # Dependencies
├── Dockerfile               # Docker build
└── replit.md                # This file
```

## Testing & Validation
The scalping strategy has been validated against:
- High-volatility market conditions
- Various trend strengths (ADX filtering)
- RSI extreme conditions (oversold/overbought)
- Multiple timeframe confirmations

## Deployment Status
- Ready for Koyeb free tier deployment
- Chart generation disabled for memory efficiency
- All unlimited signals enabled
- No signal restrictions or rate limiting

## Known Limitations
1. Deriv API rate limits (monitored with backoff)
2. Free tier constraints (512MB RAM)
3. WebSocket stability requires monitoring
4. Signal accuracy depends on market conditions and ADX levels

## Next Steps (Optional Future Enhancements)
- Add machine learning signal weighting
- Implement news impact alerts
- Create advanced analytics dashboard
- Add custom notification preferences per user

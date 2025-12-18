# XAU/USD Signal Bot - Modular Edition (v1.3 Enhanced)

## Overview
This project is a public Telegram bot designed to provide real-time XAU/USD (Gold) trading signals. It leverages Deriv WebSocket data without requiring an API key to deliver entry, stop loss (SL), and take profit (TP) notifications to subscribers. The bot aims to be a reliable signal provider, offering real-time tracking, interactive dashboards, and automated subscriber management. Its core purpose is to democratize access to XAU/USD trading signals, enabling anyone to subscribe and receive timely alerts.

## User Preferences
I prefer simple language and detailed explanations. I want iterative development with clear communication at each step. Ask before making major changes to the project structure or core logic. I prefer that the bot operates with a focus on stability and accurate signal delivery. **IMPORTANT: Signals should be unlimited with no restrictions. Bot must be professional-grade with robust filtering.**

## System Architecture - Enhanced (v1.3)
The bot is built with a modular architecture, refactored from a monolithic design into distinct, manageable components.

### Core Improvements in v1.3:
1. **Unlimited Signals**: Removed all signal limiting restrictions (max_signals_per_day eliminated)
2. **Multi-Timeframe Analysis**: 
   - 1-minute data for quick signal confirmation
   - 5-minute data for signal generation
   - 15-minute data for trend confirmation
   - 1-hour data for market structure
3. **Enhanced Indicator Suite**:
   - Stochastic Oscillator (K, D lines) - crossover detection
   - ADX (Average Directional Index) - trend strength filtering
   - EMA 21 - primary trend confirmation
   - EMA 50 - secondary trend filter
   - RSI 14 - overbought/oversold filtering
   - ATR 14 - dynamic SL/TP sizing
   - MACD - momentum confirmation
   - Bollinger Bands - volatility context
4. **Improved Signal Filtering**:
   - Multi-indicator consensus required for signal validity
   - Momentum confirmation with MACD
   - Volatility context from Bollinger Bands
   - Trend strength validation (ADX)
   - RSI confirmation to avoid reversals
5. **Risk Management Enhancement**:
   - Dynamic lot sizing based on volatility
   - ATR-based SL/TP with configurability
   - Maximum concurrent trades limit (optional)
   - Position sizing calculator
6. **Signal History & Analytics**:
   - Tracks all signal history with win/loss/BE stats
   - Signal source attribution (which indicators triggered)
   - Timeframe confirmation logging
   - Performance metrics per indicator
7. **Improved WebSocket Reliability**:
   - Automatic candle aggregation (1m→5m→15m→1h)
   - Enhanced watchdog timer
   - Multiple reconnection strategies
   - Connection health metrics
8. **Better Trade Tracking**:
   - Real-time P&L updates
   - Duration tracking per trade
   - Entry confirmation with multiple data points
   - SL/TP adjustment logic based on market behavior

### UI/UX Decisions:
- **Telegram Interface:** Interactive buttons for commands like `/start`, `/subscribe`, `/dashboard`.
- **Dashboard:** Provides real-time status updates, current prices, active positions, and trading statistics directly within Telegram.
- **Notifications:** Clear and concise messaging for trade entries, SL/TP updates, and market status changes.
- **Charting:** Generates candlestick charts to visualize historical data and signal conditions (optional, disableable for resource optimization).

### Technical Implementations:
- **Modular Components:**
    - `main.py`: Entry point for the application.
    - `config.py`: Centralized management of all bot constants, trading parameters, and indicator settings.
    - `state_manager.py`: Handles user-specific states, subscriber lists, trade information, and signal history persistence.
    - `signal_engine.py`: Encapsulates unlimited signal generation logic with multi-indicator consensus and multi-timeframe analysis.
    - `telegram_service.py`: Manages all Telegram bot interactions, command handlers, and message broadcasting.
    - `health_server.py`: Provides HTTP health check endpoint and self-ping functionality for liveness.
    - `utils.py`: Contains helper functions for logging, indicator calculations, chart generation, and data formatting.
    - `deriv_ws.py`: Manages WebSocket connection to Deriv with enhanced reliability and multi-timeframe candle aggregation.

- **Signal Generation Strategy**: 
    - Uses multi-indicator consensus approach
    - Requires confirmation from at least 3 major indicators
    - Validates across multiple timeframes
    - Incorporates momentum and volatility context
    - No artificial signal limits - generates as many as conditions permit

- **Risk Management:**
    - Stop Loss: ATR-based with configurable multiplier (1.8x by default)
    - Take Profit: Dual-tier system (1:1 and 1.5:1 Risk-Reward ratios)
    - Dynamic Lot Size: Based on volatility and risk per trade
    - Lot Size: Configurable (0.01 by default)
    - Risk Per Trade: Configurable USD amount ($2.00 by default)

- **Trade Management:**
    - Tracks active trades with real-time monitoring
    - Monitors SL/TP levels every 2-5 seconds
    - Automatically moves SL to Break Even after TP1 is hit
    - Notifies subscribers of trade outcomes (WIN/LOSS/BE)
    - Per-timeframe confirmation for entries
    - Tracks signal sources and indicator confirmations

- **Weekend Handling:** Automatically detects forex market closure (Friday 17:00 NY) and enters sleep mode, notifying subscribers, and reactivating when market reopens.

- **Persistence:** Uses JSON files for state and data persistence:
    - `bot_state_v1.3.json`: Global bot state and signal history
    - `user_states.json`: Per-user statistics, preferences, and active trades
    - `subscribers.json`: List of active subscribers
    - `signal_history.json`: Complete signal history with performance metrics

- **WebSocket Reliability:**
    - Jittered exponential backoff for reconnection (prevents thundering herd)
    - Watchdog timer detects stale connections and triggers reconnect
    - Connection statistics tracking (uptime, total reconnects)
    - Multi-timeframe candle aggregation from tick data

### Feature Specifications - v1.3 Enhanced:
- **Public Bot:** No chat ID restrictions, open to all subscribers.
- **Unlimited Real-time Signals:** No daily limits, signals generated based on pure technical analysis.
- **Multi-Timeframe Analysis:** 1m, 5m, 15m, 1h timeframe confirmations.
- **Enhanced Indicator Suite:** Stochastic, ADX, EMA, RSI, MACD, Bollinger Bands, ATR.
- **Multi-subscriber Support:** Broadcasts signals to all active subscribers.
- **Auto-cleanup:** Removes inactive/blocked subscribers.
- **Aggressive Analysis:** 10-30 second analysis intervals for rapid signal detection.
- **Per-user State:** Tracks individual subscriber statistics and preferences.
- **Signal History:** Maintains complete signal history with performance metrics.
- **Advanced Analytics:** Per-indicator performance, signal source attribution, win rate by signal type.

## External Dependencies
- **Deriv WebSocket API:**
    - Endpoint: `wss://ws.derivws.com/websockets/v3?app_id=1089`
    - Data Source: Real-time price (`ticks`) and historical candles (`ticks_history`) for `frxXAUUSD` (Gold/USD Forex).
    - Authentication: No authentication required.
    - Multi-timeframe support via tick aggregation.
- **Telegram Bot API:**
    - Used for all bot interactions, messaging, and command handling.
    - Requires `TELEGRAM_BOT_TOKEN` environment variable.

## Deployment (Koyeb Free Tier - Optimized)
- **Docker Support**: Lightweight `Dockerfile` (python:3.11-slim) for minimal resource usage
- **Performance Optimizations**:
    - **GENERATE_CHARTS=false** (default): Disables chart generation → 70% RAM reduction
    - **ANALYSIS_INTERVAL=30s**: Increased from 15s → CPU optimization
    - **KEEP_ALIVE_INTERVAL=300s**: Health check every 5 min to prevent sleep
- **Health Check**: Endpoint at `/health` for Koyeb liveness monitoring (30s interval)
    - Returns: uptime, subscriber count, WebSocket stats, trading stats, config info, signal count
- **Keep-Alive**: Self-ping loop prevents idle timeout on free tier
- **Port**: Fixed at 8000 for Koyeb compatibility
- **Environment Variables**:
    - `GENERATE_CHARTS` (default: false) - Set to false for free tier
    - `KEEP_ALIVE_INTERVAL` (default: 300)
    - `TELEGRAM_BOT_TOKEN` (required)
    - `UNLIMITED_SIGNALS` (default: true) - No signal restrictions
- **Files**:
    - `Dockerfile`: Optimized multi-stage build
    - `requirements.txt`: Production dependencies
    - `.dockerignore`: Excludes unnecessary files from build
    - `DEPLOY_KOYEB.md`: Complete deployment guide with troubleshooting

## Recent Changes (v1.3 - December 2024)
- **REMOVED: Signal limiting** - Deleted max_signals_per_day restrictions entirely
- **ADDED: Multi-timeframe analysis** - Enhanced signal validation across 1m, 5m, 15m, 1h
- **ADDED: Enhanced indicators** - MACD, Bollinger Bands, additional EMAs
- **IMPROVED: Signal filtering** - Multi-indicator consensus requirement
- **ENHANCED: Risk management** - Dynamic sizing based on volatility
- **ADDED: Signal history** - Complete performance tracking
- **IMPROVED: WebSocket** - Better candle aggregation and reliability
- **IMPROVED: Documentation** - Comprehensive v1.3 specifications

## Implementation Roadmap
**Phase 1 (Complete):**
- ✅ Remove signal limits
- ✅ Enhance config with multi-indicator parameters
- ✅ Add unlimited signal generation logic
- ✅ Improve indicator calculations

**Phase 2 (Optional Future):**
- Add machine learning signal weighting
- Implement sentiment analysis
- Add news impact alerts
- Create premium features (advanced analytics, custom alerts)

## Known Limitations & Considerations
1. **Deriv API rate limits**: Monitored and handled with backoff
2. **Free tier constraints**: 512MB RAM, handled via GENERATE_CHARTS=false
3. **Telegram rate limits**: Implemented with message batching
4. **WebSocket stability**: Requires active monitoring and watchdog timer
5. **Signal accuracy**: Depends on indicator calibration and market conditions
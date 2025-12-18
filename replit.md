# XAU/USD Signal Bot - Modular Edition

## Overview
This project is a public Telegram bot designed to provide real-time XAU/USD (Gold) trading signals. It leverages Deriv WebSocket data without requiring an API key to deliver entry, stop loss (SL), and take profit (TP) notifications to subscribers. The bot aims to be a reliable signal provider, offering real-time tracking, interactive dashboards, and automated subscriber management. Its core purpose is to democratize access to XAU/USD trading signals, enabling anyone to subscribe and receive timely alerts.

## User Preferences
I prefer simple language and detailed explanations. I want iterative development with clear communication at each step. Ask before making major changes to the project structure or core logic. I prefer that the bot operates with a focus on stability and accurate signal delivery.

## System Architecture
The bot is built with a modular architecture, refactored from a monolithic design into distinct, manageable components.

**UI/UX Decisions:**
- **Telegram Interface:** Interactive buttons for commands like `/start`, `/subscribe`, `/dashboard`.
- **Dashboard:** Provides real-time status updates, current prices, active positions, and trading statistics directly within Telegram.
- **Notifications:** Clear and concise messaging for trade entries, SL/TP updates, and market status changes.
- **Charting:** Generates candlestick charts to visualize historical data and signal conditions.

**Technical Implementations:**
- **Modular Components:**
    - `main.py`: Entry point for the application.
    - `config.py`: Centralized management of all bot constants and trading parameters.
    - `state_manager.py`: Handles user-specific states, subscriber lists, and trade information persistence.
    - `signal_engine.py`: Encapsulates the core signal generation logic and trade tracking.
    - `telegram_service.py`: Manages all Telegram bot interactions, command handlers, and message broadcasting.
    - `health_server.py`: Provides an HTTP health check endpoint and self-ping functionality for liveness.
    - `utils.py`: Contains helper functions for logging, indicator calculations, chart generation, and data formatting.
    - `deriv_ws.py`: Manages the WebSocket connection to Deriv for real-time data.
- **Signal Generation:** Employs a multi-indicator strategy including:
    - **Stochastic Oscillator:** For crossover detection (bullish/bearish).
    - **ADX:** As a trend strength filter.
    - **EMA 21:** For trend confirmation.
    - **RSI:** To filter overbought/oversold conditions.
- **Risk Management:**
    - Stop Loss: Based on ATR(14) * 1.8 from entry.
    - Take Profit: Tiered at 1:1 and 1:1.5 Risk-Reward ratios.
    - Lot Size: Fixed at 0.01 with a defined risk per trade.
- **Trade Management:**
    - Tracks active trades, monitors SL/TP levels.
    - Automatically moves SL to Break Even after TP1 is hit.
    - Notifies subscribers of trade outcomes (WIN/LOSS/BE).
- **Weekend Handling:** Automatically detects forex market closure (Friday 17:00 NY) and enters a sleep mode, notifying subscribers, and reactivating when the market reopens.
- **Persistence:** Uses JSON files (`bot_state_v1.2.json`, `user_states.json`, `subscribers.json`) for state and data persistence.

**Feature Specifications:**
- **Public Bot:** No chat ID restrictions, open to all subscribers.
- **Real-time Tracking:** Updates trade positions every 5 seconds.
- **Multi-subscriber Support:** Broadcasts signals to all active subscribers.
- **Auto-cleanup:** Removes inactive subscribers.
- **Aggressive Mode:** 10-second analysis interval for rapid signal detection.
- **Per-user State:** Tracks individual subscriber win/loss/break-even statistics.

## External Dependencies
- **Deriv WebSocket API:**
    - Endpoint: `wss://ws.derivws.com/websockets/v3?app_id=1089`
    - Data Source: Real-time price (`ticks`) and historical candles (`ticks_history`) for `frxXAUUSD` (Gold/USD Forex).
    - Authentication: No authentication required.
- **Telegram Bot API:**
    - Used for all bot interactions, messaging, and command handling.
    - Requires `TELEGRAM_BOT_TOKEN` environment variable.

## Deployment (Koyeb)
- **Docker Support**: Project includes `Dockerfile` and `requirements.txt` for containerized deployment
- **Health Check**: Endpoint at `/health` for liveness monitoring
- **Self-Ping**: Bot pings itself every 45 seconds with persistent session to prevent sleeping
- **Port**: Configurable via `PORT` environment variable (default: 8000)
- **Optimizations for Free Tier**:
    - Win/lose results sent as text-only (no chart) to save storage
    - Chart files auto-deleted immediately after sending to Telegram
    - Analysis interval 15s with jitter for CPU efficiency
    - Active trades cleared on restart - always searches fresh signals
- **Files**:
    - `Dockerfile`: Docker image configuration
    - `requirements.txt`: Python dependencies for Docker
    - `.dockerignore`: Files excluded from Docker build
    - `DEPLOY_KOYEB.md`: Step-by-step deployment guide
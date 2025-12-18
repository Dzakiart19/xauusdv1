# XAU/USD Signal Bot V31 - Deriv Edition

Bot Telegram untuk signal trading XAU/USD (Gold) menggunakan data real-time dari Deriv WebSocket tanpa memerlukan API key.

## Overview

Bot ini berfungsi sebagai signal provider yang memberikan notifikasi entry, stop loss (SL), dan take profit (TP) melalui Telegram. Bot tidak mengeksekusi order secara otomatis.

## Struktur Project

```
/
├── main.py              # Entry point & signal engine
├── deriv_ws.py          # Deriv WebSocket connector module
├── bot_state_v31.json   # State persistence (win/loss/BE counts)
├── bot_v31.log          # Log file
├── chart_v31.png        # Generated chart (temporary)
└── replit.md            # Dokumentasi
```

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    BOT STARTUP                              │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  1. Load State (win_count, loss_count, be_count)            │
│  2. Initialize Telegram Bot                                 │
│  3. Find Gold Symbol dari Deriv (frxXAUUSD)                 │
│  4. Connect ke Deriv WebSocket                              │
│  5. Subscribe ke tick data                                  │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   MAIN LOOP (60 detik)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │ Ada Active Trade│    │ Tidak Ada Active Trade          │ │
│  └────────┬────────┘    └────────────────┬────────────────┘ │
│           │                              │                  │
│           ▼                              ▼                  │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │ Mode Pelacakan  │    │ Mode Pencarian Sinyal           │ │
│  │ - Cek harga 15s │    │ 1. Get candle data (200)        │ │
│  │ - Monitor SL/TP │    │ 2. Calculate indicators:        │ │
│  │                 │    │    - Stochastic (8,3,3)         │ │
│  └────────┬────────┘    │    - ATR (14)                   │ │
│           │             │    - ADX (14)                   │ │
│           ▼             │    - EMA (21)                   │ │
│  ┌─────────────────┐    │ 3. Check signal conditions      │ │
│  │ Trade Result?   │    └────────────────┬────────────────┘ │
│  │ - TP1 Hit       │                     │                  │
│  │ - TP2 Hit (WIN) │                     ▼                  │
│  │ - SL Hit (LOSS) │    ┌─────────────────────────────────┐ │
│  │ - BE            │    │ Valid Signal Found?             │ │
│  └────────┬────────┘    └────────────────┬────────────────┘ │
│           │                              │                  │
│           ▼                              ▼                  │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │ Send Telegram   │    │ YES: Generate Chart             │ │
│  │ Notification    │    │      Calculate SL/TP            │ │
│  │ Update Stats    │    │      Send Telegram Signal       │ │
│  └─────────────────┘    │      Set Active Trade           │ │
│                         │ NO:  Continue loop              │ │
│                         └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Arsitektur Komponen

### 1. deriv_ws.py - WebSocket Connector

```
DerivWebSocket Class
├── connect()           - Connect ke Deriv WebSocket
├── subscribe_ticks()   - Subscribe ke real-time tick
├── get_candles()       - Get historical OHLC data
├── get_active_symbols() - Get available symbols
├── listen()            - Listen untuk incoming messages
├── send_ping()         - Keep-alive ping
├── get_current_price() - Get latest price
└── close()             - Close connection
```

### 2. main.py - Signal Engine

```
Main Bot
├── Telegram Handlers
│   ├── /start  - Welcome message
│   ├── /stats  - Show statistics
│   └── /info   - System info
├── Data Functions
│   ├── get_historical_data()  - Get OHLC from Deriv
│   └── get_realtime_price()   - Get current price
├── Analysis
│   └── calculate_indicators() - Stoch, ATR, ADX, EMA
├── Signal Engine
│   └── signal_engine_loop()   - Main trading loop
└── Utilities
    ├── generate_chart()       - Create candlestick chart
    ├── send_photo()           - Send to Telegram
    └── save/load_state()      - Persistence
```

## Strategi Trading

### Entry Conditions

**BUY Signal:**
- Stochastic K crosses above D (bullish crossover)
- ADX >= 15 (trend strength filter)
- Close > EMA 21 (bullish trend)

**SELL Signal:**
- Stochastic K crosses below D (bearish crossover)
- ADX >= 15 (trend strength filter)
- Close < EMA 21 (bearish trend)

### Risk Management

- Stop Loss: ATR(14) * 1.8 dari entry
- Take Profit 1: Risk * 1.0 (1:1 RR)
- Take Profit 2: Risk * 1.5 (1:1.5 RR)
- Lot Size: 0.01
- Risk per Trade: ~$2.00

### Trade Management

1. **Active**: Monitoring SL dan TP1
2. **TP1 Hit**: Pindahkan SL ke entry (Break Even)
3. **TP2 Hit**: Trade ditutup sebagai WIN
4. **SL Hit**: Trade ditutup sebagai LOSS/BE

## Environment Variables

| Variable | Deskripsi |
|----------|-----------|
| TELEGRAM_BOT_TOKEN | Token dari @BotFather |
| TARGET_CHAT_ID | Chat ID untuk notifikasi |

## Data Source: Deriv WebSocket

### Endpoint
```
wss://ws.derivws.com/websockets/v3?app_id=1089
```

### Symbol
- `frxXAUUSD` - Gold/USD Forex

### API Calls (Tanpa Authentication)
- `ticks` - Real-time price
- `ticks_history` - Historical candles
- `active_symbols` - Available symbols
- `ping` - Keep-alive

## Best Practices

### 1. Connection Management
- Reconnect otomatis saat connection lost
- Keep-alive ping setiap 30 detik
- Max 10 reconnection attempts

### 2. Data Handling
- Buffer 200 candles untuk indicator calculation
- Use deque untuk efficient memory usage
- Timeout 15 detik untuk API calls

### 3. Error Handling
- Graceful degradation saat data tidak tersedia
- Logging semua error ke file
- State persistence untuk recovery

### 4. Performance
- Asyncio untuk concurrent operations
- Background task untuk WebSocket listening
- Efficient indicator calculation dengan pandas_ta

## Telegram Commands

| Command | Deskripsi |
|---------|-----------|
| /start | Welcome message |
| /stats | Lihat statistik trading |
| /info | Info sistem (connection, price) |

## Recent Changes

- **V31**: Migrasi dari Twelve Data API ke Deriv WebSocket
- Tidak memerlukan API key
- Real-time tick data
- Improved connection handling

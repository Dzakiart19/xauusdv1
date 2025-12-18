# XAU/USD Signal Bot V1.2 - Modular Edition

Bot Telegram untuk signal trading XAU/USD (Gold) menggunakan data real-time dari Deriv WebSocket tanpa memerlukan API key.

## Overview

Bot ini berfungsi sebagai signal provider yang memberikan notifikasi entry, stop loss (SL), dan take profit (TP) melalui Telegram. Bot ini bersifat PUBLIC - siapa saja bisa berlangganan dan menerima sinyal.

## Fitur Utama

- **Public Bot**: Tidak ada restriksi chat ID, semua orang bisa subscribe
- **Real-time Tracking**: Update posisi setiap 5 detik saat trade aktif
- **Dashboard Interaktif**: Lihat status koneksi, harga, posisi aktif, dan statistik
- **Multi-subscriber**: Kirim sinyal ke semua subscriber secara otomatis
- **Auto-cleanup**: Hapus subscriber yang memblokir bot
- **RSI Confirmation**: Indikator RSI untuk konfirmasi sinyal lebih akurat
- **Trailing Stop**: Otomatis mengamankan profit dengan trailing stop
- **Aggressive Mode**: Interval analisis 10 detik untuk respon cepat
- **Per-user State**: Tracking win/loss/BE per user

## Arsitektur Modular (V1.2)

```
/
├── main.py              # Entry point (~70 baris)
├── config.py            # BotConfig class - semua konstanta
├── state_manager.py     # StateManager class - manajemen state per-user
├── signal_engine.py     # SignalEngine class - logika sinyal
├── telegram_service.py  # TelegramService class - handlers & messaging
├── health_server.py     # HealthServer class - HTTP health check
├── utils.py             # Utility functions (logging, chart generation)
├── deriv_ws.py          # Deriv WebSocket connector module
├── bot_state_v1.2.json  # State persistence
├── user_states.json     # Per-user state (win/loss/BE counts)
├── subscribers.json     # Daftar subscriber
├── bot_v1.2.log         # Log file
├── chart_v1.2.png       # Generated chart (temporary)
└── replit.md            # Dokumentasi
```

## Komponen Modular

### 1. config.py - BotConfig Class

```python
BotConfig
├── Trading Parameters
│   ├── STOCH_K, STOCH_D, STOCH_SMOOTH  # Stochastic settings
│   ├── ATR_PERIOD, ATR_MULTIPLIER       # ATR settings
│   ├── RR_TP1, RR_TP2                   # Risk-reward ratios
│   ├── ADX_FILTER_PERIOD, THRESHOLD     # ADX filter
│   ├── RSI_PERIOD, OVERBOUGHT, OVERSOLD # RSI settings
│   └── LOT_SIZE, RISK_PER_TRADE_USD     # Position sizing
├── Timing
│   ├── ANALYSIS_INTERVAL                # 10 seconds
│   └── ANALYSIS_JITTER                  # 3 seconds
├── Files
│   ├── CHART_FILENAME, LOG_FILENAME
│   └── USER_STATES_FILENAME, SUBSCRIBERS_FILENAME
└── Helper Methods
    ├── get_stoch_k_col(), get_stoch_d_col()
    ├── get_adx_col(), get_ema_col()
    └── get_rsi_col(), get_atr_col()
```

### 2. state_manager.py - StateManager Class

```python
StateManager
├── User State Management
│   ├── get_user_state()        # Get/create user state
│   ├── save_user_states()      # Persist to JSON
│   ├── load_user_states()      # Load from JSON
│   └── reset_user_data()       # Reset user statistics
├── Subscriber Management
│   ├── add_subscriber()        # Add new subscriber
│   ├── remove_subscriber()     # Remove subscriber
│   ├── is_subscriber()         # Check subscription
│   ├── save_subscribers()      # Persist to JSON
│   └── load_subscribers()      # Load from JSON
├── Trade Management
│   ├── update_trade_result()   # Update win/loss/BE
│   ├── set_active_trade_for_subscribers()
│   └── clear_user_tracking_messages()
└── Signal State
    ├── current_signal          # Active trade info
    ├── last_signal_info        # Last signal sent
    ├── update_current_signal()
    └── clear_current_signal()
```

### 3. telegram_service.py - TelegramService Class

```python
TelegramService
├── Command Handlers
│   ├── start()         # /start - Welcome message
│   ├── subscribe()     # /subscribe - Join signals
│   ├── unsubscribe()   # /unsubscribe - Leave signals
│   ├── stats()         # /stats - Trading statistics
│   ├── riset()         # /riset - Reset data
│   ├── info()          # /info - System info
│   ├── dashboard()     # /dashboard - Interactive dashboard
│   └── signal()        # /signal - Last signal
├── Callback Handlers
│   └── button_callback()  # Inline button handler
├── Messaging
│   ├── send_dashboard()   # Send dashboard to user
│   ├── send_to_all_subscribers()  # Broadcast message
│   └── send_tracking_update()     # Send tracking update
└── Dependencies
    ├── state_manager      # State management
    ├── deriv_ws_getter    # WebSocket getter
    └── gold_symbol_getter # Symbol getter
```

### 4. signal_engine.py - SignalEngine Class

```python
SignalEngine
├── Data Functions
│   ├── get_historical_data()   # Get OHLC from Deriv
│   ├── get_realtime_price()    # Get current price
│   └── send_photo()            # Send chart to subscribers
├── Lifecycle
│   ├── run()                   # Main signal loop
│   └── notify_restart()        # Send restart notification
├── Signal Generation
│   ├── Stochastic crossover detection
│   ├── ADX trend filter
│   ├── EMA trend confirmation
│   └── RSI overbought/oversold filter
├── Trade Tracking
│   ├── Monitor TP1/TP2/SL levels
│   ├── Move SL to BE on TP1 hit
│   └── Update subscribers on trade result
└── Dependencies
    ├── state_manager       # State management
    ├── telegram_service    # Telegram messaging
    └── deriv_ws           # WebSocket connection
```

### 5. health_server.py - HealthServer Class

```python
HealthServer
├── HTTP Server
│   ├── health_handler()  # /health endpoint
│   ├── start()           # Start server
│   └── cleanup()         # Cleanup resources
└── Self-ping
    └── self_ping_loop()  # Keep-alive pings
```

### 6. utils.py - Utility Functions

```python
Utils
├── Logging
│   ├── NoHttpxFilter     # Filter noisy logs
│   ├── setup_logging()   # Configure logging
│   └── bot_logger        # Main logger instance
├── Indicators
│   └── calculate_indicators()  # Stoch, ATR, ADX, EMA, RSI
├── Chart
│   └── generate_chart()        # Create candlestick chart
└── Helpers
    ├── format_pnl()            # Format P&L display
    ├── get_win_rate_emoji()    # Get emoji for win rate
    └── calculate_win_rate()    # Calculate win percentage
```

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    BOT STARTUP (main.py)                     │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  1. Create StateManager, load states                        │
│  2. Create SignalEngine                                     │
│  3. Create TelegramService with callbacks                   │
│  4. Start HealthServer                                      │
│  5. Register Telegram handlers                              │
│  6. Start signal_engine.run()                               │
└─────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│               SIGNAL ENGINE LOOP (10 detik)                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │ Ada Active Trade│    │ Tidak Ada Active Trade          │ │
│  └────────┬────────┘    └────────────────┬────────────────┘ │
│           │                              │                  │
│           ▼                              ▼                  │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │ Mode Pelacakan  │    │ Mode Pencarian Sinyal           │ │
│  │ - Cek harga 5s  │    │ 1. Get candle data (200)        │ │
│  │ - Monitor SL/TP │    │ 2. Calculate indicators         │ │
│  │ - Live tracking │    │ 3. Check signal conditions      │ │
│  └────────┬────────┘    └────────────────┬────────────────┘ │
│           │                              │                  │
│           ▼                              ▼                  │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │ Trade Result?   │    │ Valid Signal Found?             │ │
│  │ - TP1/TP2 Hit   │    │ YES: Generate & Send Signal     │ │
│  │ - SL Hit        │    │ NO:  Continue loop              │ │
│  └─────────────────┘    └─────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Strategi Trading

### Entry Conditions

**BUY Signal:**
- Stochastic K crosses above D (bullish crossover)
- ADX >= 15 (trend strength filter)
- Close > EMA 21 (bullish trend)
- RSI < 70 (not overbought)

**SELL Signal:**
- Stochastic K crosses below D (bearish crossover)
- ADX >= 15 (trend strength filter)
- Close < EMA 21 (bearish trend)
- RSI > 30 (not oversold)

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

## Telegram Commands

| Command | Deskripsi |
|---------|-----------|
| /start | Welcome message dengan button interaktif |
| /subscribe | Berlangganan sinyal trading |
| /unsubscribe | Berhenti berlangganan |
| /dashboard | Dashboard real-time (harga, posisi, statistik) |
| /signal | Lihat sinyal terakhir yang dikirim |
| /stats | Lihat statistik trading |
| /riset | Reset data trading |
| /info | Info sistem (connection, price, subscriber count) |

## Environment Variables

| Variable | Deskripsi |
|----------|-----------|
| TELEGRAM_BOT_TOKEN | Token dari @BotFather |

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

## Recent Changes

- **V1.2 Modular Edition (Dec 2025)**:
  - Refactored monolithic main.py (1200+ baris) menjadi arsitektur modular
  - Buat BotConfig class untuk semua constants
  - Buat StateManager class untuk manajemen state per-user
  - Buat SignalEngine class untuk logika signal generation
  - Buat TelegramService class untuk Telegram handlers
  - Buat HealthServer class untuk HTTP health check
  - Buat utils.py untuk utility functions
  - main.py sekarang hanya ~70 baris (entry point)
  - Dependency injection pattern untuk decoupling
  - Per-user state tracking (win/loss/BE per user)

- **V31.3 Pro Update (Dec 2025)**:
  - Interval analisis dipercepat dari 20 detik menjadi 10 detik
  - Tambah indikator RSI untuk konfirmasi sinyal lebih akurat
  - Tambah command /signal untuk lihat sinyal terakhir
  - WebSocket reconnection dengan exponential backoff

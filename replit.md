# XAU/USD Signal Bot V31 - Public Edition

Bot Telegram untuk signal trading XAU/USD (Gold) menggunakan data real-time dari Deriv WebSocket tanpa memerlukan API key.

## Overview

Bot ini berfungsi sebagai signal provider yang memberikan notifikasi entry, stop loss (SL), dan take profit (TP) melalui Telegram. Bot ini bersifat PUBLIC - siapa saja bisa berlangganan dan menerima sinyal.

## Fitur Utama

- **Public Bot**: Tidak ada restriksi chat ID, semua orang bisa subscribe
- **Real-time Tracking**: Update posisi setiap 30 detik saat trade aktif
- **Dashboard Interaktif**: Lihat status koneksi, harga, posisi aktif, dan statistik
- **Multi-subscriber**: Kirim sinyal ke semua subscriber secara otomatis
- **Auto-cleanup**: Hapus subscriber yang memblokir bot

## Struktur Project

```
/
├── main.py              # Entry point & signal engine
├── deriv_ws.py          # Deriv WebSocket connector module
├── bot_state_v31.json   # State persistence (win/loss/BE counts)
├── subscribers.json     # Daftar subscriber
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
│  2. Load Subscribers dari JSON                              │
│  3. Initialize Telegram Bot (PUBLIC MODE)                   │
│  4. Find Gold Symbol dari Deriv (frxXAUUSD)                 │
│  5. Connect ke Deriv WebSocket                              │
│  6. Subscribe ke tick data                                  │
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
│  │ - Live tracking │    │    - Stochastic (8,3,3)         │ │
│  │   update setiap │    │    - ATR (14)                   │ │
│  │   30 detik      │    │    - ADX (14)                   │ │
│  └────────┬────────┘    │    - EMA (21)                   │ │
│           │             │ 3. Check signal conditions      │ │
│           ▼             └────────────────┬────────────────┘ │
│  ┌─────────────────┐                     │                  │
│  │ Trade Result?   │                     ▼                  │
│  │ - TP1 Hit       │    ┌─────────────────────────────────┐ │
│  │ - TP2 Hit (WIN) │    │ Valid Signal Found?             │ │
│  │ - SL Hit (LOSS) │    └────────────────┬────────────────┘ │
│  │ - BE            │                     │                  │
│  └────────┬────────┘                     ▼                  │
│           │             ┌─────────────────────────────────┐ │
│           ▼             │ YES: Generate Chart             │ │
│  ┌─────────────────┐    │      Calculate SL/TP            │ │
│  │ Send Telegram   │    │      Send to ALL Subscribers    │ │
│  │ to ALL subs     │    │      Set Active Trade           │ │
│  │ Update Stats    │    │ NO:  Continue loop              │ │
│  └─────────────────┘    └─────────────────────────────────┘ │
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

### 2. main.py - Signal Engine (Public Mode)

```
Main Bot
├── Telegram Handlers
│   ├── /start      - Welcome message dengan button
│   ├── /subscribe  - Berlangganan sinyal
│   ├── /unsubscribe- Berhenti berlangganan
│   ├── /dashboard  - Dashboard real-time
│   ├── /stats      - Show statistics
│   └── /info       - System info
├── Subscriber Management
│   ├── save_subscribers()      - Simpan ke JSON
│   ├── load_subscribers()      - Load dari JSON
│   └── send_to_all_subscribers()- Broadcast ke semua
├── Data Functions
│   ├── get_historical_data()   - Get OHLC from Deriv
│   └── get_realtime_price()    - Get current price
├── Dashboard & Tracking
│   ├── send_dashboard()        - Kirim dashboard interaktif
│   └── send_tracking_update()  - Update posisi real-time
├── Analysis
│   └── calculate_indicators()  - Stoch, ATR, ADX, EMA
├── Signal Engine
│   └── signal_engine_loop()    - Main trading loop
└── Utilities
    ├── generate_chart()        - Create candlestick chart
    ├── send_photo()            - Send to all subscribers
    └── save/load_state()       - Persistence
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

## Telegram Commands

| Command | Deskripsi |
|---------|-----------|
| /start | Welcome message dengan button interaktif |
| /subscribe | Berlangganan sinyal trading |
| /unsubscribe | Berhenti berlangganan |
| /dashboard | Dashboard real-time (harga, posisi, statistik) |
| /stats | Lihat statistik trading |
| /info | Info sistem (connection, price, subscriber count) |

## Dashboard Features

Dashboard menampilkan:
- Status koneksi WebSocket
- Harga XAU/USD real-time
- Posisi aktif (jika ada):
  - Arah (BUY/SELL)
  - Entry price
  - TP1, TP2, SL levels
  - Estimasi P&L dalam pips
  - Status (Aktif / BE Mode)
- Statistik trading (Win/Loss/BE)
- Tombol Refresh

## Real-time Tracking

Saat ada posisi aktif, bot mengirimkan update setiap ~30 detik berisi:
- Harga real-time
- Estimasi P&L
- Jarak ke TP1, TP2, SL
- Status posisi

## Environment Variables

| Variable | Deskripsi |
|----------|-----------|
| TELEGRAM_BOT_TOKEN | Token dari @BotFather |

**Catatan**: TARGET_CHAT_ID tidak diperlukan lagi karena bot sekarang public.

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
- Auto-remove blocked subscribers

### 4. Performance
- Asyncio untuk concurrent operations
- Background task untuk WebSocket listening
- Efficient indicator calculation dengan pandas_ta
- Rate-limited tracking updates

## Recent Changes

- **V31.2 Aggressive Update (Dec 2025)**:
  - Interval analisis dipercepat dari 60 detik menjadi 20 detik dengan random jitter
  - Active trade disimpan ke file (survive restart)
  - WebSocket reconnection logic lebih robust

- **V31.1 Friendly Update (Dec 2025)**:
  - Semua teks bot diperbarui dengan emoji yang friendly dan bersih
  - Interval tracking dipercepat dari 15 detik menjadi 5 detik
  - Bot otomatis mencari sinyal 24 jam non-stop saat dimulai
  - Format pesan lebih rapi dengan separator line (━━━)
  - Tampilan dashboard dan tracking lebih informatif

- **V31 Public Edition**: 
  - Konversi dari private ke public bot
  - Hapus restriksi TARGET_CHAT_ID
  - Tambah sistem subscriber management
  - Tambah dashboard interaktif
  - Tambah real-time tracking update
  - Tambah inline keyboard buttons
  - Auto-cleanup blocked subscribers

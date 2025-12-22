# XAU/USD Scalping Signal Bot V2.0 Pro

## Overview

Bot ini adalah sistem sinyal trading otomatis untuk XAU/USD (Gold) yang menggunakan strategi scalping dengan indikator teknikal EMA50, RSI(3), dan ADX(55). Bot terhubung ke Deriv WebSocket untuk data real-time dan mengirim sinyal trading melalui Telegram.

**Fitur Utama:**
- Sinyal unlimited 24 jam non-stop
- Money management: SL $3 | TP $3 (1:1 Ratio)
- Tracking posisi real-time dengan TP1 dan TP2
- Auto Break-Even saat TP1 tercapai
- Daily summary report otomatis
- Graceful shutdown handling
- Signal history persistence

## Arsitektur Project

```
├── main.py              # Entry point aplikasi dengan graceful shutdown
├── config.py            # Konfigurasi bot dan strategi
├── signal_engine.py     # Engine analisis sinyal trading
├── telegram_service.py  # Service untuk komunikasi Telegram
├── state_manager.py     # Manajemen state subscriber dan sinyal
├── deriv_ws.py          # WebSocket client untuk Deriv
├── health_server.py     # HTTP health check server
├── utils.py             # Utilitas dan helper functions
├── Dockerfile           # Docker configuration untuk deployment
├── requirements.txt     # Python dependencies
└── *.json               # Data persistence files
```

## Strategi Trading

### Indikator:
- **EMA 50**: Trend Direction Filter
- **RSI 3**: Entry Timing (sensitive)
- **ADX 55**: Trend Strength Filter (threshold: 30)

### Logika Entry:
- **BUY**: Price > EMA50, RSI was oversold (<30) dan exiting (>23), ADX > 30
- **SELL**: Price < EMA50, RSI was overbought (>70) dan exiting (<77), ADX > 30

### Money Management:
- SL: $3 (Fixed)
- TP1: $3 (Entry + $3)
- TP2: $4.5 (Entry + $4.5)
- Auto Break-Even: SL dipindah ke entry saat TP1 hit

## Environment Variables

| Variable | Deskripsi | Default |
|----------|-----------|---------|
| TELEGRAM_BOT_TOKEN | Token bot Telegram | (required) |
| ADMIN_CHAT_ID | Chat ID admin untuk notifikasi | (optional) |
| PORT | Port untuk health server | 5000 |
| GENERATE_CHARTS | Generate chart image | true |
| KEEP_ALIVE_INTERVAL | Interval self-ping (seconds) | 300 |

## Commands Telegram

| Command | Deskripsi |
|---------|-----------|
| /start | Menu utama bot |
| /subscribe | Berlangganan sinyal |
| /unsubscribe | Berhenti berlangganan |
| /dashboard | Lihat posisi aktif |
| /signal | Lihat sinyal terakhir |
| /stats | Statistik trading personal |
| /today | Statistik hari ini |
| /riset | Reset data trading |
| /info | Info sistem bot |

## Deployment

### Local Development
```bash
export TELEGRAM_BOT_TOKEN=your_token
python main.py
```

### Docker (Koyeb)
Bot sudah dikonfigurasi untuk deployment di Koyeb menggunakan Docker. Pastikan environment variable TELEGRAM_BOT_TOKEN sudah diset.

## Health Check

Endpoint `/health` mengembalikan JSON dengan status:
- WebSocket connection status
- Current price
- Trading statistics
- Signal history
- Memory usage
- Uptime

## Recent Changes

### V2.0 Pro (2025-12-22) - Per-User Tracking Fix
- **IMPLEMENTED**: Per-user signal history tracking (bukan global lagi)
- Setiap user punya signal_history terpisah dalam user_states.json
- `/riset` command sekarang reset SEMUA data (W/L/BE dan signal_history)
- `/today` stats sekarang per-user (hanya menampilkan signal user tersebut)
- `/info` command sekarang menampilkan "Statistik Hari Ini (Anda)" bukan global
- Subscribe tetap aktif saat reset data seperti yang diminta
- Migration logic untuk existing users (auto-add signal_history field)

### V2.0 Pro (2025-12-18)
- Upgrade Python 3.11 → 3.12 untuk kompatibilitas pandas-ta
- Tambah Rate limiting untuk Telegram API
- Implementasi Graceful shutdown handler
- Signal history persistence ke file
- Daily summary report otomatis jam 21:00 WIB
- Tambah command /today untuk statistik harian
- Improved error handling dengan retry mechanism
- Type hints untuk maintainability
- Configuration validation saat startup

## File Persistence

- `subscribers.json` - Daftar subscriber aktif
- `user_states.json` - State dan statistik per user
- `signal_history.json` - History sinyal (max 500 entries)
- `bot_scalping.log` - Log file

## Notes

- Bot menggunakan data real-time dari Deriv WebSocket
- Sinyal bersifat unlimited (tidak ada limit harian)
- Cooldown antar sinyal: 120 detik
- Analysis interval: ~30 detik

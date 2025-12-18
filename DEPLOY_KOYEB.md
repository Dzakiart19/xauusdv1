# Deploy XAU/USD Scalping Signal Bot V2.0 ke Koyeb Free Tier

## Overview
Bot trading signal XAU/USD yang sudah dioptimasi untuk Koyeb free tier dengan fitur unlimited signals dan strategi scalping (EMA50 + RSI3 + ADX55).

## Strategi Scalping V2.0

### Indikator yang Digunakan:
- **EMA 50**: Filter arah tren (harga > EMA50 = BUY, harga < EMA50 = SELL)
- **RSI 3**: Timing entry (< 30 = oversold → BUY, > 70 = overbought → SELL)
- **ADX 55**: Filter kekuatan tren (harus > 30 untuk entry)

### Kondisi Entry:
| Signal | EMA50 | RSI(3) | ADX(55) |
|--------|-------|--------|---------|
| BUY | Harga > EMA50 | < 30 (Oversold) | > 30 |
| SELL | Harga < EMA50 | > 70 (Overbought) | > 30 |

### Money Management:
- **Stop Loss:** $3 dari entry (fixed)
- **Take Profit 1:** $3 dari entry (1:1 ratio)
- **Take Profit 2:** $4.50 dari entry (1.5:1 ratio)

## Optimisasi untuk Free Tier (512MB RAM)
- **Chart generation disabled** - Menghemat ~70% RAM
- **Simplified indicators** - Hanya 4 indikator (vs 7 di V1.3)
- **Fixed SL/TP** - Tidak perlu kalkulasi ATR setiap saat
- **Keep-alive mechanism** - Mencegah bot sleep

## Langkah Deploy

### 1. Push ke GitHub
```bash
git init
git add .
git commit -m "XAU/USD Scalping Bot V2.0"
git remote add origin https://github.com/USERNAME/REPO.git
git push -u origin main
```

### 2. Deploy di Koyeb

1. Buka https://app.koyeb.com
2. Klik "Create App"
3. Pilih "GitHub" sebagai source
4. Pilih repository Anda
5. Konfigurasi:
   - **Builder**: Docker
   - **Dockerfile location**: `Dockerfile`
   - **Port**: `8000`
   - **Instance type**: Free (nano)
   - **Regions**: Pilih terdekat

### 3. Environment Variables

**WAJIB:**
```
TELEGRAM_BOT_TOKEN = your_bot_token_from_botfather
```

**OPSIONAL (dengan default optimasi free tier):**
```
PORT = 8000
GENERATE_CHARTS = false
KEEP_ALIVE_INTERVAL = 300
```

### 4. Health Check Configuration

Koyeb akan otomatis menggunakan:
- Path: `/health`
- Port: `8000`
- Interval: 30 detik
- Retries: 3

## Health Endpoint

Bot menyediakan endpoint `/health` dengan metrics lengkap:

```json
{
  "status": "ok",
  "version": "2.0-scalping",
  "uptime_human": "2h 45m",
  "subscribers": 15,
  "memory_mb": 150.5,
  "websocket": {
    "connected": true,
    "current_price": 2650.123,
    "tick_age_seconds": 0.5,
    "total_reconnects": 3
  },
  "trading": {
    "active_signal": false,
    "total_wins": 12,
    "total_losses": 3,
    "total_be": 2,
    "win_rate": 80.0
  },
  "signals": {
    "total_generated": 17,
    "history_count": 17,
    "cooldown_seconds": 120
  },
  "strategy": {
    "type": "scalping",
    "indicators": ["EMA50", "RSI3", "ADX55"],
    "sl_usd": 3.0,
    "tp_usd": 3.0
  }
}
```

## Fitur V2.0

### Unlimited Signals
- Tidak ada batasan sinyal per hari
- Signal dihasilkan berdasarkan strategi scalping
- Cooldown 120 detik untuk mencegah spam

### Scalping Strategy (EMA50 + RSI3 + ADX55)
Sinyal divalidasi dengan 3 kondisi:
1. **EMA 50** - Trend direction filter
2. **RSI 3** - Entry timing (oversold/overbought)
3. **ADX 55** - Trend strength filter (> 30)

### Money Management
- Fixed Stop Loss: $3
- Fixed Take Profit: $3 (1:1 ratio)
- TP2: $4.50 (1.5:1 ratio)
- Risk per trade: $3

## Troubleshooting

### Bot Sleeping/Tidak Aktif
1. Pastikan `GENERATE_CHARTS=false`
2. Verifikasi health endpoint: `curl https://your-app.koyeb.app/health`
3. Cek `KEEP_ALIVE_INTERVAL` di environment variables

### Out of Memory (OOM)
1. Pastikan `GENERATE_CHARTS=false`
2. Cek jumlah subscriber - broadcast besar butuh lebih banyak memory

### WebSocket Disconnects
- Normal behavior - bot punya auto-reconnection
- Cek `/health` untuk `total_reconnects` metric
- Deriv API mungkin ada maintenance

### Sinyal Tidak Tergenerate
1. Cek market buka (Sen-Jum, bukan weekend)
2. Verifikasi WebSocket connected via `/health`
3. Pastikan ADX > 30 (tren cukup kuat)
4. RSI harus < 30 (untuk BUY) atau > 70 (untuk SELL)

## Bot Commands

Users dapat berinteraksi via Telegram:

| Command | Fungsi |
|---------|--------|
| `/start` | Tampilkan menu utama |
| `/subscribe` | Berlangganan sinyal |
| `/unsubscribe` | Berhenti berlangganan |
| `/dashboard` | Lihat posisi aktif dan stats |
| `/signal` | Lihat sinyal terakhir |
| `/stats` | Statistik trading personal |
| `/riset` | Reset statistik personal |
| `/info` | Info sistem bot |

## Upgrade ke Paid Plan

Jika upgrade ke paid plan Koyeb, Anda bisa enable fitur tambahan:

```
GENERATE_CHARTS = true
ANALYSIS_INTERVAL = 15
```

Ini akan mengaktifkan chart generation dan analisis lebih cepat.

## Support

Jika ada masalah:
1. Cek `/health` endpoint untuk diagnostics
2. Review container logs di Koyeb dashboard
3. Pastikan semua environment variables sudah benar

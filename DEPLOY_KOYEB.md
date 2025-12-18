# Deploy XAU/USD Signal Bot V1.3 ke Koyeb Free Tier

## Overview
Bot trading signal XAU/USD yang sudah dioptimasi untuk Koyeb free tier dengan fitur unlimited signals dan multi-indicator consensus.

## Optimisasi untuk Free Tier (512MB RAM)
- **Chart generation disabled** - Menghemat ~70% RAM
- **Parallel message broadcast** - Lebih cepat untuk banyak subscriber
- **Atomic file writes** - Mencegah data corrupt saat crash
- **Configurable signal cooldown** - Mencegah spam signal
- **Keep-alive mechanism** - Mencegah bot sleep

## Langkah Deploy

### 1. Push ke GitHub
```bash
git init
git add .
git commit -m "XAU/USD Signal Bot V1.3"
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
KEEP_ALIVE_INTERVAL = 240
UNLIMITED_SIGNALS = true
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
  "version": "1.3",
  "uptime_human": "2h 45m",
  "subscribers": 15,
  "memory_mb": 180.5,
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
  "config": {
    "analysis_interval": 30,
    "charts_enabled": false,
    "unlimited_signals": true,
    "min_consensus": 2
  }
}
```

## Fitur V1.3

### Unlimited Signals
- Tidak ada batasan sinyal per hari
- Signal dihasilkan berdasarkan analisis teknikal murni
- Cooldown 120 detik untuk mencegah spam

### Multi-Indicator Consensus
Sinyal divalidasi dengan multiple indicator:
- **Stochastic Oscillator** - Crossover detection
- **ADX** - Trend strength filter (>15)
- **EMA 21** - Short-term trend
- **EMA 50** - Medium-term trend
- **RSI 14** - Overbought/oversold filter
- **MACD** - Momentum confirmation
- **Bollinger Bands** - Volatility context

### Signal History
- Tracking 100 sinyal terakhir
- Performance metrics per signal
- Win rate calculation otomatis

## Troubleshooting

### Bot Sleeping/Tidak Aktif
1. Pastikan `GENERATE_CHARTS=false`
2. Verifikasi health endpoint: `curl https://your-app.koyeb.app/health`
3. Cek `KEEP_ALIVE_INTERVAL` di environment variables

### Out of Memory (OOM)
1. Pastikan `GENERATE_CHARTS=false`
2. Cek jumlah subscriber - broadcast besar butuh lebih banyak memory
3. Pertimbangkan menaikkan `ANALYSIS_INTERVAL`

### WebSocket Disconnects
- Normal behavior - bot punya auto-reconnection
- Cek `/health` untuk `total_reconnects` metric
- Deriv API mungkin ada maintenance

### Sinyal Tidak Tergenerate
1. Cek market buka (Sen-Jum, bukan weekend)
2. Verifikasi WebSocket connected via `/health`
3. Review logs untuk nilai indikator
4. Pastikan `MIN_INDICATOR_CONSENSUS` tercapai (default: 2)

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

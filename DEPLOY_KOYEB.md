# Deploy ke Koyeb Free Tier - Optimized

## 🚀 Optimisasi untuk Performance & 24/7 Uptime

Bot sekarang dioptimasi khusus untuk Koyeb tier gratis:
- ✅ **Disabled chart generation** (mengurangi memory 70%)
- ✅ **Increased analysis interval** (30s → reduce CPU)
- ✅ **Optimized keep-alive** (mencegah idle sleep)
- ✅ **Lightweight Docker image** (python:3.11-slim)

## Langkah Deploy

### 1. Push ke GitHub
```bash
git init
git add .
git commit -m "Optimized for Koyeb tier gratis"
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
   - **Instance type**: Free (nano) ⭐
   - **Regions**: Pilih terdekat

### 3. Environment Variables (WAJIB)

Tambahkan di Koyeb Dashboard → Settings → Environment:
```
TELEGRAM_BOT_TOKEN = your_token_here
PORT = 8000
GENERATE_CHARTS = false
KEEP_ALIVE_INTERVAL = 300
```

⚠️ **PENTING**: `GENERATE_CHARTS=false` WAJIB untuk tier gratis!

### 4. Health Check (Already Configured)

Koyeb otomatis menggunakan:
- Path: `/health`
- Port: `8000`
- Interval: 30 detik
- Retries: 3

Bot akan keep-alive setiap 5 menit dengan self-ping.

## ⚠️ Troubleshooting

### Bot sleeping/tidak aktif
**Solusi:**
1. Pastikan `GENERATE_CHARTS=false` di env variables
2. Verifikasi health endpoint aktif: `curl https://your-app.koyeb.app/health`
3. Bot sudah ada keep-alive mechanism - tidak perlu external uptime service

### Bot heavy/lambat
**Sudah dioptimasi:**
- Chart generation disabled → RAM usage ↓70%
- Analysis interval 30s → CPU usage ↓
- Requirements sudah lightweight

### Build timeout
**Solusi:**
- Pastikan semua file di-push ke GitHub
- Cek internet connection GitHub

### Sinyal tidak terkirim
- Cek TELEGRAM_BOT_TOKEN di Koyeb Dashboard
- Lihat logs untuk error details
- Pastikan bot sudah di-subscribe di Telegram

## 🔧 Jika Ingin Enable Chart Lagi (untuk upgrade plan)

Set di Koyeb Environment:
```
GENERATE_CHARTS = true
```

Tapi ini akan membuat bot lebih berat. Rekomendasinya tetap `false` untuk tier gratis.

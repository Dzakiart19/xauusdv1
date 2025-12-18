# Deploy ke Koyeb Free Tier

## Langkah-langkah Deploy

### 1. Push ke GitHub
```bash
git init
git add .
git commit -m "Initial commit"
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
   - **Regions**: Pilih yang terdekat

### 3. Environment Variables

Tambahkan di Koyeb Dashboard:
- `TELEGRAM_BOT_TOKEN` = Token bot Telegram Anda
- `PORT` = `8000`

### 4. Health Check Settings

Koyeb akan otomatis menggunakan:
- **Path**: `/health`
- **Port**: `8000`
- **Interval**: 30 detik

## Tips Agar Bot 24 Jam Non-Stop

1. Bot sudah memiliki self-ping setiap 5 menit
2. Health endpoint tersedia di `/health`
3. Koyeb free tier tidak sleeping selama ada health check

## Troubleshooting

### Bot tidak jalan
- Pastikan `TELEGRAM_BOT_TOKEN` sudah benar
- Cek logs di Koyeb Dashboard

### Build gagal
- Pastikan semua file sudah di-push ke GitHub
- Cek Dockerfile path sudah benar

### Bot sleep/mati
- Pastikan health check di Koyeb aktif di port 8000
- Bot akan self-ping otomatis untuk mencegah idle

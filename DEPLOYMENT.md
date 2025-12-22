# Deployment Guide - Koyeb

## Setup di Koyeb

### 1. Konfigurasi Environment Variables
Di Koyeb dashboard, set environment variables:
```
TELEGRAM_BOT_TOKEN=your_token
DERIV_APP_ID=your_app_id
```

### 2. Deploy
```bash
# Koyeb akan automatically menggunakan Procfile
git push origin main
```

### 3. Memastikan Single Instance
**PENTING**: Di Koyeb, pastikan **Scalability → Min instances = 1, Max instances = 1**

Ini mencegah multiple instances conflict pada Telegram polling.

## Troubleshooting

### Error: "terminated by other getUpdates request"
- Bot mencoba polling dengan multiple instances
- **Solusi**: Set max instances = 1 di Koyeb dashboard

### Health Check Failing
- Port 8000 harus terbuka untuk health checks
- Procfile sudah configured

## Local Testing
```bash
python main.py
```

Bot akan berjalan on port 5000 (dev) atau 8000 (prod)

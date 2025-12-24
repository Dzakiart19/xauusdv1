# XAU/USD Scalping Signal Bot V2.0 Pro

## 📋 Project Overview

**XAU/USD Scalping Signal Bot V2.0 Pro** adalah bot trading signal otomatis untuk emas (XAU/USD) yang menggunakan strategi scalping dengan indikator teknikal advanced. Bot ini dirancang untuk:

- **Generate unlimited trading signals** berdasarkan strategi scalping (EMA50 + RSI3 + ADX55)
- **Track real-time price movements** setiap 5 detik dengan update langsung
- **Manage money dengan ketat** - SL $3, TP1 $3 (1:1), TP2 $4.50 (1.5:1)
- **Support per-user signals** - setiap user bisa generate signal manual (/send command)
- **Break-even protection** - SL otomatis move ke entry price saat TP1 tercapai
- **Optimized untuk Koyeb free tier** - memory efficient (512MB RAM)

**Current Version:** 2.0 Pro (Production Ready)
**Status:** ✅ Fully Functional
**Deployment Target:** Koyeb Free Tier (Nano Instance)

---

## 🏗️ Project Architecture

### File Structure
```
xauusd-bot-v2/
├── main.py                 # Entry point, async manager
├── config.py              # Configuration & market hours
├── signal_engine.py       # Signal generation + tracking logic
├── telegram_service.py    # Telegram API + user commands
├── deriv_ws.py           # WebSocket connection to Deriv
├── state_manager.py       # JSON persistence (users, signals, subs)
├── health_server.py       # /health endpoint (aiohttp)
├── utils.py              # Logging + indicator calculation
├── requirements.txt       # Python dependencies
├── Procfile              # Heroku/Koyeb deployment
├── Dockerfile            # Docker container config
├── DEPLOY_KOYEB.md       # Detailed deployment guide
└── replit.md             # This file
```

### Data Files (Persisted as JSON)
```
├── subscribers.json        # List of subscribed users (chat IDs)
├── user_states.json        # Per-user tracking (wins, losses, active_trade)
├── signal_history.json     # Last 500 signals (global history)
└── bot_scalping.log        # Application logs
```

---

## 🎯 Strategy Details

### Scalping Strategy (EMA50 + RSI3 + ADX55)

**Entry Conditions:**
| Signal | Condition | Details |
|--------|-----------|---------|
| **BUY** | Price > EMA50 **AND** RSI < 30 **AND** ADX > 30 | Oversold bounce in uptrend |
| **SELL** | Price < EMA50 **AND** RSI > 70 **AND** ADX > 30 | Overbought rejection in downtrend |

**Money Management:**
| Parameter | Value | Notes |
|-----------|-------|-------|
| Stop Loss | $3 fixed | Per trade max loss |
| Take Profit 1 | $3 | Partial close - locks in profit |
| Take Profit 2 | $4.50 | Extended target - bonus profit |
| Risk/Reward | 1:1 (TP1), 1.5:1 (TP2) | Conservative ratios |

**Break-Even Logic:**
1. TP1 tercapai → Partial close, profit $3 locked
2. SL otomatis move dari entry - $3 → entry price (BREAK EVEN)
3. Risk sekarang = $0, potensi profit = $1.50 (TP2)

---

## 💻 Key Components

### 1. Signal Engine (`signal_engine.py`)
- **Tanggung jawab:** Generate signals, track trades real-time
- **Key features:**
  - Fetch 200 candles dari Deriv WebSocket setiap 30 detik
  - Calculate EMA50, RSI3, ADX55 indicators
  - Monitor price vs TP1/TP2/SL setiap 5 detik
  - Auto-move SL ke break-even saat TP1 hit
  - 120-second cooldown antara signals
  - Market awareness (check NYSE hours)

### 2. Telegram Service (`telegram_service.py`)
- **Tanggung jawab:** Semua interaksi dengan Telegram users
- **Key features:**
  - /start, /subscribe, /unsubscribe commands
  - /send untuk manual signal generation
  - /dashboard untuk melihat active trades
  - /stats untuk statistik personal per-user
  - Real-time tracking updates (edit message every 5 sec)
  - Progress bar untuk TP2 tracking setelah TP1
  - Daily summary reports
  - Rate limiting (0.05 detik per message)

### 3. Deriv WebSocket (`deriv_ws.py`)
- **Tanggung jawab:** Real-time price data dari Deriv
- **Key features:**
  - Auto-reconnect dengan exponential backoff
  - Jitter untuk prevent thundering herd
  - Current price updates every tick
  - 200-candle history fetch (1-minute bars)
  - Connection statistics tracking

### 4. State Manager (`state_manager.py`)
- **Tanggung jawab:** Data persistence (JSON files)
- **Key features:**
  - Per-user state: wins/losses/active_trade/tracking_message_id
  - Per-user signal history (last 500 per user)
  - Global subscribers list
  - Global signal history (last 500 signals)
  - Atomic file writes (.tmp pattern)
  - Datetime serialization handling

### 5. Health Server (`health_server.py`)
- **Tanggung jawab:** Monitoring endpoint
- **Key features:**
  - `/health` endpoint (JSON response)
  - Uptime tracking
  - Memory usage reporting
  - WebSocket connection status
  - Trade statistics
  - Keep-alive self-ping mechanism

---

## 🚀 Workflow & Dependencies

### Python Packages
```
aiohttp>=3.9.0              # Async HTTP client (health server)
pandas>=2.1.0              # Data manipulation
pandas-ta>=0.4.67b0        # Technical analysis indicators
python-telegram-bot>=20.7  # Telegram Bot API
pytz>=2023.3              # Timezone handling
websockets>=12.0          # WebSocket client (Deriv)
mplfinance                # Chart generation (optional, disabled)
```

### Async Architecture
- **Main:** `asyncio.run(main())` in main.py
- **Background tasks:**
  - Signal engine loop (analyze + track)
  - WebSocket listener
  - Health server (aiohttp)
  - Keep-alive ping loop
- **Concurrency:** All tasks run simultaneously with proper cleanup

---

## 📱 User Commands (Telegram)

| Command | Function | Access |
|---------|----------|--------|
| `/start` | Show menu + status | Public |
| `/subscribe` | Join signals | Public |
| `/unsubscribe` | Stop signals | Public |
| `/send [BUY\|SELL]` | Generate manual signal | Subscribers only |
| `/dashboard` | View active positions | Subscribers only |
| `/stats` | Personal trade statistics | Subscribers only |
| `/riset` | Reset statistics | Subscribers only |
| `/info` | System information | Public |

---

## 🔄 Signal Flow

### Automatic Signal Generation
```
1. Fetch 200 candles (1-minute) from Deriv
2. Calculate indicators: EMA50, RSI3, ADX55
3. Check conditions:
   - ADX > 30? (trend strong enough)
   - Price position vs EMA50? (direction)
   - RSI oversold/overbought? (entry timing)
4. If valid: Generate signal
5. Send to ALL subscribers
6. Set current_signal for tracking
7. Wait 120 seconds (cooldown)
8. Repeat
```

### Manual Signal Generation (/send)
```
1. User sends /send BUY
2. Generate signal for THAT USER ONLY
3. Also set current_signal (triggers tracking)
4. Per-user tracking starts immediately
5. User receives updates every 5 seconds
6. Track until TP2 or SL hit
```

### Real-Time Tracking (Every 5 Seconds)
```
PHASE 1: Awaiting TP1
├─ Update message with current price
├─ Show distance to TP1
├─ Show P&L
└─ Repeat every 5 sec

PHASE 2: TP1 Hit → Break Even Mode (NEW!)
├─ Change status to "AWAITING TP2"
├─ Show TP1 ✓ (locked profit $3)
├─ Display progress bar: ████░░░░░░
├─ Show distance to TP2
├─ Show min profit guaranteed ($3)
└─ Repeat every 5 sec until TP2 or SL

PHASE 3: Trade Closed
├─ Send result (WIN/LOSS/BREAK_EVEN)
├─ Update user statistics
├─ Clear active_trade & tracking_message_id
└─ Resume signal searching
```

---

## 🌍 Deployment

### Koyeb Free Tier Setup

**Requirements:**
- Koyeb account (free tier)
- GitHub repository
- Telegram Bot Token (from @BotFather)

**Environment Variables (Minimal):**
```
TELEGRAM_BOT_TOKEN = xxxxxxxxxxx:xxxxxxxxxxxxx  # REQUIRED
PORT = 5000                                     # Optional (default)
KEEP_ALIVE_INTERVAL = 300                       # Optional (default)
```

**Deployment Steps:**
1. Push code to GitHub
2. Connect Koyeb to GitHub
3. Set deployment method: Docker
4. Add environment variables
5. Deploy (takes ~1-2 minutes)
6. Verify: `curl https://your-app.koyeb.app/health`

**Health Check Response:**
```json
{
  "status": "ok",
  "version": "2.0-pro",
  "uptime_seconds": 3600,
  "subscribers": 5,
  "memory_mb": 145.2,
  "websocket": {
    "connected": true,
    "current_price": 4482.530,
    "tick_age_seconds": 0.3
  },
  "trading": {
    "active_signal": true,
    "total_wins": 12,
    "total_losses": 3,
    "total_be": 2,
    "win_rate": 80.0
  }
}
```

---

## 🔧 Development Setup (Replit)

### Quick Start
```bash
# Install dependencies
pip install -r requirements.txt

# Run bot (direct)
python main.py

# View logs
tail -f bot_scalping.log
```

### Configuration
Edit `config.py` to adjust:
```python
SIGNAL_COOLDOWN_SECONDS = 120      # Min gap between signals
ANALYSIS_INTERVAL = 30              # Seconds between analysis
FIXED_SL_USD = 3.0                  # Stop loss amount
FIXED_TP_USD = 3.0                  # TP1 amount
MA_MEDIUM_PERIOD = 50               # EMA period
RSI_PERIOD = 3                       # RSI period
ADX_FILTER_PERIOD = 55              # ADX period
ADX_FILTER_THRESHOLD = 30           # Min ADX to trade
```

### Testing Signals
```bash
# In Telegram, send:
/send BUY      # Generate manual BUY
/send SELL     # Generate manual SELL
/dashboard     # See tracking in real-time
/stats         # View results
```

---

## 📊 State Management

### User State Structure
```json
{
  "chat_id": {
    "win_count": 12,
    "loss_count": 3,
    "be_count": 2,
    "active_trade": {
      "direction": "SELL",
      "entry_price": 4482.530,
      "tp1_level": 4475.530,
      "tp2_level": 4481.000,
      "sl_level": 4482.530,
      "status": "tp1_hit",
      "start_time_utc": "2025-12-24T13:16:00Z"
    },
    "tracking_message_id": 12345,
    "signal_history": [
      {
        "id": 1,
        "direction": "SELL",
        "entry_price": 4482.530,
        "result": "WIN",
        "timestamp": "2025-12-24T13:16:00Z",
        "closed_at": "2025-12-24T13:17:30Z"
      }
    ]
  }
}
```

### Persistence Pattern
- Write to `.tmp` file first (atomic)
- Rename `.tmp` to actual filename (ACID)
- Prevents data corruption on crashes
- Load on startup, save after every change

---

## 🐛 Troubleshooting

### Bot Not Generating Signals
1. Check `/health` endpoint (WebSocket connected?)
2. Verify market is open (NYSE hours)
3. Check ADX > 30 (trend strength)
4. Check RSI < 30 (BUY) or > 70 (SELL)
5. Review logs: `tail -f bot_scalping.log`

### WebSocket Disconnects
- Normal behavior - auto-reconnect enabled
- Check Deriv server status
- Logs show: "⚠️ WebSocket disconnected, reconnecting..."

### Users Not Receiving Messages
- Check subscriber in `subscribers.json`
- Verify TELEGRAM_BOT_TOKEN is correct
- Check Telegram user hasn't blocked bot
- Review logs for "Chat not found" errors

### Out of Memory
- Reduce ANALYSIS_INTERVAL
- Disable chart generation (GENERATE_CHARTS=false)
- Clear old logs

---

## 📈 Recent Changes

### V2.0 Pro Updates
1. **Real-Time Tracking After TP1** (Latest)
   - Progress bar to TP2 (████░░░░░░)
   - Shows distance remaining
   - Min profit protection ($3) visible
   - Updates every 5 seconds

2. **Per-User Tracking System**
   - Each user sees their own active_trade
   - Manual signals (/send) tracked per-user
   - Broadcast signals tracked for all
   - Individual entry/TP/SL per user

3. **Break-Even Protection**
   - SL moves to entry when TP1 hit
   - Risk = $0, reward = $1.50 (TP2)
   - Automatically tracked in real-time

4. **Unlimited Signals**
   - No daily limits
   - 120-second cooldown between signals
   - Strategy-based generation only

5. **Production Optimizations**
   - Memory efficient (145MB for 5 users)
   - Fast JSON persistence
   - Auto-cleanup invalid subscribers
   - Health monitoring endpoint

---

## 🎯 Performance Metrics

### Typical Performance (5 subscribers, Koyeb nano)
- **Memory:** 145-160 MB (under 512 MB limit)
- **CPU:** <5% idle, <15% during tracking
- **Response time:** <100ms per message
- **WebSocket latency:** 0.3-0.5 seconds
- **Tracking update rate:** Every 5 seconds

### Scalability
- 1-100 users: Comfortable
- 100-500 users: Monitor memory
- 500+ users: Upgrade to paid plan

---

## 📝 User Preferences & Notes

### Strategy Configuration
- **Conservative approach:** 1:1 ratio (TP1 = SL)
- **Extended profit:** TP2 at 1.5:1 ratio
- **Quick scalps:** 1-5 minute average trades
- **No leverage:** Fixed $3 risk per trade

### Market Focus
- **Instrument:** XAU/USD (Gold vs US Dollar)
- **Timeframe:** 1-minute candles
- **Market hours:** NYSE hours (Mon-Fri 17:00-17:00 NY)
- **Weekend:** Bot pauses (auto-resume Monday)

### Telegram Settings
- **Rate limit:** 0.05 sec per message
- **Batch size:** 25 users per batch
- **Retry:** 3 attempts with exponential backoff
- **Keep-alive:** 300 sec (prevent sleep)

---

## 🚀 Deployment Checklist

Before deploying to Koyeb:

- [x] All Python syntax verified
- [x] Signal generation tested
- [x] Tracking updates working
- [x] Per-user signal separation confirmed
- [x] Break-even protection active
- [x] Health endpoint responding
- [x] WebSocket auto-reconnect working
- [x] JSON persistence tested
- [x] Telegram rate limiting active
- [x] Error handling comprehensive

---

## 📞 Support & Monitoring

### Health Check
```bash
curl https://your-app.koyeb.app/health | jq .
```

### Live Logs
```bash
# Tail last 100 lines
tail -100 bot_scalping.log | grep "Tracking"

# Filter by type
grep "✅\|❌\|⚠️" bot_scalping.log
```

### Manual Testing
```bash
# In Telegram chat:
/subscribe          # Join signals
/send BUY          # Test manual signal
/dashboard         # See real-time tracking
/stats             # Check results
```

---

## 📚 References

- **Deriv API:** https://api.deriv.com
- **Telegram Bot:** https://core.telegram.org/bots/api
- **Pandas TA:** https://github.com/twopirllc/pandas-ta
- **Koyeb Docs:** https://docs.koyeb.com

---

**Last Updated:** December 24, 2025
**Status:** ✅ Production Ready for Koyeb Deployment
**Next Steps:** Add TELEGRAM_BOT_TOKEN to Koyeb environment and deploy!

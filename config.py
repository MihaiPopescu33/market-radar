"""Setări Market Radar. Modifici aici, nu în bot.py."""

# Ce bot rulează: numele apare în notificări
BOT_NAME = "Trend Bot"
# Setup-urile active (din: trend_pullback, breakout, bb_rsi_reversal, liquidity_sweep)
ENABLED_SETUPS = ["trend_pullback"]

# Nume afișat -> simbol Yahoo Finance
INSTRUMENTS = {
    "NAS100": "NQ=F",      # Nasdaq 100 futures
    "US500": "ES=F",       # S&P 500 futures
    "US30": "YM=F",        # Dow Jones futures
    "US2000": "RTY=F",     # Russell 2000 futures
    "GOLD": "GC=F",        # gold futures (CFD-ul din Trading 212 urmărește spot, diferă cu câțiva $)
    "SILVER": "SI=F",
}

# Timeframe -> cât istoric descărcăm (limitele Yahoo: 1h = 730 zile, 15m = 60 zile)
TIMEFRAMES = {"1h": "730d"}          # pentru M15 adaugi: "15m": "60d"
TF_MINUTES = {"1h": 60, "15m": 15}

# Managementul tranzacției simulate (identic în backtest și în alertă)
SL_ATR = 1.5          # stop loss = 1.5 x ATR(14)
TP_R = 1.5            # take profit = 1.5 x riscul (R:R 1:1.5)
MAX_BARS = {"1h": 48, "15m": 64}   # dacă nu atinge SL/TP în atâtea bare, se închide la market
COST_R = 0.05         # spread + comision estimat, în R, scăzut din fiecare trade

# Filtre pentru alerte
MIN_SAMPLES = 20      # minim de cazuri istorice ca să avem încredere în statistică
MIN_EXPECTANCY = 0.0  # R mediu pe trade (istoric) peste care trimitem alerta
K_NEIGHBORS = 25      # câte "situații asemănătoare" comparăm
SEND_WEAK = False     # True = trimite și setup-urile fără edge istoric (marcate ca atare)

# Știri: avertizează dacă e un eveniment cu impact mare în fereastra asta (ore)
NEWS_WINDOW_H = 2
NEWS_CURRENCIES = {k: ["USD"] for k in INSTRUMENTS}

LOCAL_TZ = "Europe/Bucharest"

"""Setări Market Radar. Modifici aici, nu în bot.py."""

# Nume afișat -> simbol Yahoo Finance
INSTRUMENTS = {
    "GOLD": "GC=F",        # gold futures (CFD-ul din Trading 212 urmărește spot, diferă cu câțiva $)
    "SILVER": "SI=F",
    "NAS100": "NQ=F",
    "SP500": "ES=F",
    "OIL": "CL=F",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
}

# Timeframe -> cât istoric descărcăm (limitele Yahoo: 1h = 730 zile, 15m = 60 zile)
TIMEFRAMES = {"1h": "730d", "15m": "60d"}
TF_MINUTES = {"1h": 60, "15m": 15}

# Managementul tranzacției simulate (identic în backtest și în alertă)
SL_ATR = 1.5          # stop loss = 1.5 x ATR(14)
TP_R = 2.0            # take profit = 2 x riscul (2R)
MAX_BARS = {"1h": 48, "15m": 64}   # dacă nu atinge SL/TP în atâtea bare, se închide la market
COST_R = 0.05         # spread + comision estimat, în R, scăzut din fiecare trade

# Filtre pentru alerte
MIN_SAMPLES = 20      # minim de cazuri istorice ca să avem încredere în statistică
MIN_EXPECTANCY = 0.0  # R mediu pe trade (istoric) peste care trimitem alerta
K_NEIGHBORS = 25      # câte "situații asemănătoare" comparăm
SEND_WEAK = False     # True = trimite și setup-urile fără edge istoric (marcate ca atare)

# Știri: avertizează dacă e un eveniment cu impact mare în fereastra asta (ore)
NEWS_WINDOW_H = 2
NEWS_CURRENCIES = {
    "GOLD": ["USD"], "SILVER": ["USD"], "NAS100": ["USD"], "SP500": ["USD"], "OIL": ["USD"],
    "EURUSD": ["USD", "EUR"], "GBPUSD": ["USD", "GBP"], "USDJPY": ["USD", "JPY"],
    "BTC": ["USD"], "ETH": ["USD"],
}

LOCAL_TZ = "Europe/Bucharest"

"""Market Radar — scanează piețele, recunoaște setup-uri și le compară cu istoricul.

Comenzi:
  python bot.py scan      caută semnale pe ultima bară închisă și trimite alerte
  python bot.py report    backtest complet pe toate instrumentele + rezumat jurnal
  python bot.py test      trimite o notificare de test pe telefon (ntfy)
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import config as C

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state.json"
JOURNAL_FILE = ROOT / "journal.csv"
REPORT_FILE = ROOT / "reports" / "backtest.md"
JOURNAL_COLS = ["signal_time", "instrument", "tf", "setup", "direction", "entry_ref",
                "sl", "tp", "hist_n", "hist_exp", "knn_exp", "status", "result_r"]


# ───────────────────────────── date ─────────────────────────────
def fetch(ticker: str, interval: str, period: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[["Open", "High", "Low", "Close"]].dropna()
    df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
    return df[~df.index.duplicated()]


def closed_bars(df: pd.DataFrame, tf: str, now: datetime) -> pd.DataFrame:
    """Scoate bara în curs de formare (semnalele se dau doar pe bare închise)."""
    return df[df.index + pd.Timedelta(minutes=C.TF_MINUTES[tf]) <= now]


# ─────────────────────────── indicatori ───────────────────────────
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c, h, l = d.Close, d.High, d.Low
    for n in (20, 50, 200):
        d[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    d["rsi"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    d["bb_up"], d["bb_lo"] = mid + 2 * sd, mid - 2 * sd
    d["don_hi"] = h.rolling(20).max().shift(1)
    d["don_lo"] = l.rolling(20).min().shift(1)
    day = d.index.floor("D")
    daily = d.groupby(day).agg(dh=("High", "max"), dl=("Low", "min")).shift(1)
    d["pdh"] = daily["dh"].reindex(day).values
    d["pdl"] = daily["dl"].reindex(day).values
    d["day"] = day
    return d


# ──────────────────────────── setup-uri ────────────────────────────
# Fiecare funcție întoarce o serie cu +1 (long), -1 (short), 0 (nimic) pe bara de semnal.
def s_trend_pullback(d):
    bull = d.Close > d.Open
    bear = d.Close < d.Open
    up = (d.ema50 > d.ema200) & (d.ema200 > d.ema200.shift(10))
    dn = (d.ema50 < d.ema200) & (d.ema200 < d.ema200.shift(10))
    long_ = up & (d.Low <= d.ema20) & (d.Close > d.ema20) & bull
    short = dn & (d.High >= d.ema20) & (d.Close < d.ema20) & bear
    return long_.astype(int) - short.astype(int)


def s_breakout(d):
    body = (d.Close - d.Open).abs()
    long_ = (d.Close > d.don_hi) & (d.Close.shift() <= d.don_hi.shift()) & (body > 0.5 * d.atr) & (d.Close > d.Open)
    short = (d.Close < d.don_lo) & (d.Close.shift() >= d.don_lo.shift()) & (body > 0.5 * d.atr) & (d.Close < d.Open)
    return long_.astype(int) - short.astype(int)


def s_bb_rsi_reversal(d):
    long_ = (d.Close.shift() < d.bb_lo.shift()) & (d.rsi.shift() < 30) & (d.Close > d.bb_lo) & (d.Close > d.Open)
    short = (d.Close.shift() > d.bb_up.shift()) & (d.rsi.shift() > 70) & (d.Close < d.bb_up) & (d.Close < d.Open)
    return long_.astype(int) - short.astype(int)


def s_liquidity_sweep(d):
    long_c = (d.Low < d.pdl) & (d.Close > d.pdl) & (d.Close > d.Open)
    short_c = (d.High > d.pdh) & (d.Close < d.pdh) & (d.Close < d.Open)
    first_l = long_c & (long_c.groupby(d.day).cumsum() == 1)
    first_s = short_c & (short_c.groupby(d.day).cumsum() == 1)
    return first_l.astype(int) - first_s.astype(int)


ALL_SETUPS = {
    "trend_pullback": (s_trend_pullback, "Pullback în trend (atinge EMA20, EMA50 vs EMA200 dă direcția)"),
    "breakout": (s_breakout, "Breakout din range-ul ultimelor 20 de bare, cu lumânare puternică"),
    "bb_rsi_reversal": (s_bb_rsi_reversal, "Revenire din extremă (în afara Bollinger + RSI 30/70)"),
    "liquidity_sweep": (s_liquidity_sweep, "Sweep peste/sub extrema zilei anterioare, închidere înapoi"),
}
SETUPS = {k: v for k, v in ALL_SETUPS.items() if k in C.ENABLED_SETUPS}


# ──────────────────── simulare rezultat & statistici ────────────────────
def simulate(d: pd.DataFrame, i: int, direction: int, tf: str) -> float:
    """Intrare la deschiderea barei următoare, SL = SL_ATR*ATR, TP = TP_R*risc.
    Dacă SL și TP sunt atinse în aceeași bară, considerăm pierdere (conservator).
    NaN = încă nerezolvat."""
    o, h, l, c, atr = (d[k].values for k in ("Open", "High", "Low", "Close", "atr"))
    n, max_bars = len(d), C.MAX_BARS[tf]
    if i + 1 >= n or not np.isfinite(atr[i]) or atr[i] <= 0:
        return np.nan
    entry, risk = o[i + 1], C.SL_ATR * atr[i]
    sl, tp = entry - direction * risk, entry + direction * C.TP_R * risk
    end = min(i + 1 + max_bars, n)
    for j in range(i + 1, end):
        hit_sl = l[j] <= sl if direction == 1 else h[j] >= sl
        hit_tp = h[j] >= tp if direction == 1 else l[j] <= tp
        if hit_sl:
            return -1.0 - C.COST_R
        if hit_tp:
            return C.TP_R - C.COST_R
    if end - (i + 1) < max_bars:
        return np.nan
    return direction * (c[end - 1] - entry) / risk - C.COST_R


def features(d: pd.DataFrame) -> pd.DataFrame:
    """Descrierea 'contextului' unei bare, folosită ca să găsim situații asemănătoare."""
    f = pd.DataFrame(index=d.index)
    f["rsi"] = d.rsi
    f["dist_ema200"] = (d.Close - d.ema200) / d.atr
    f["ema_spread"] = (d.ema50 - d.ema200) / d.atr
    f["mom5"] = (d.Close - d.Close.shift(5)) / d.atr
    f["vol_regime"] = d.atr.rolling(100).rank(pct=True)
    f["bb_pos"] = (d.Close - d.bb_lo) / (d.bb_up - d.bb_lo)
    hr = d.index.hour + d.index.minute / 60
    f["hour_sin"], f["hour_cos"] = np.sin(2 * np.pi * hr / 24), np.cos(2 * np.pi * hr / 24)
    return f


def stats(r) -> dict:
    r = pd.Series(r, dtype=float).dropna()
    if r.empty:
        return {"n": 0, "win": np.nan, "exp": np.nan, "pf": np.nan}
    pos, neg = r[r > 0].sum(), -r[r < 0].sum()
    return {"n": len(r), "win": (r > 0).mean(), "exp": r.mean(), "pf": pos / neg if neg > 0 else np.inf}


def history_for(d: pd.DataFrame, sig: pd.Series, direction: int, tf: str, upto: int) -> pd.DataFrame:
    """Toate aparițiile trecute ale setup-ului (înainte de bara `upto`) cu rezultatul lor."""
    idx = [i for i in np.flatnonzero(sig.values == direction) if i < upto and i >= 200]
    rows = [(i, simulate(d.iloc[:upto], i, direction, tf)) for i in idx]
    return pd.DataFrame(rows, columns=["i", "r"]).dropna()


def similar_cases(feat: pd.DataFrame, hist: pd.DataFrame, i_now: int) -> dict:
    if len(hist) < 5:
        return stats([]) | {"k": 0}
    X = feat.iloc[hist.i.values].values
    x0 = feat.iloc[i_now].values
    ok = np.isfinite(X).all(axis=1)
    X, r = X[ok], hist.r.values[ok]
    if len(X) < 5 or not np.isfinite(x0).all():
        return stats([]) | {"k": 0}
    mu, sd = X.mean(0), X.std(0) + 1e-9
    dist = np.sqrt((((X - mu) / sd - (x0 - mu) / sd) ** 2).sum(1))
    k = min(C.K_NEIGHBORS, len(X))
    return stats(r[np.argsort(dist)[:k]]) | {"k": k}


def stability(hist: pd.DataFrame) -> bool:
    """Edge-ul există în ambele jumătăți ale istoricului? (test simplu anti-noroc)"""
    if len(hist) < 2 * 10:
        return False
    half = len(hist) // 2
    return hist.r.iloc[:half].mean() > 0 and hist.r.iloc[half:].mean() > 0


# ─────────────────────────── știri ───────────────────────────
_news_cache = None


def upcoming_news(instrument: str, now: datetime) -> list:
    global _news_cache
    if _news_cache is None:
        try:
            _news_cache = requests.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=10).json()
        except Exception:
            _news_cache = []
    out = []
    cur = C.NEWS_CURRENCIES.get(instrument, ["USD"])
    for ev in _news_cache:
        try:
            if ev.get("impact") != "High" or ev.get("country") not in cur:
                continue
            t = datetime.fromisoformat(ev["date"]).astimezone(timezone.utc)
            if -timedelta(hours=1) <= t - now <= timedelta(hours=C.NEWS_WINDOW_H):
                out.append(f"{ev['country']} {ev['title']} la {t.astimezone(_tz()).strftime('%H:%M')}")
        except Exception:
            continue
    return out


# ────────────────────────── utilitare ──────────────────────────
def _tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo(C.LOCAL_TZ)


def send(text: str, priority: int = 4):
    """Trimite notificarea pe telefon prin ntfy.sh (topic setat în secretul NTFY_TOPIC)."""
    import html
    import re
    plain = html.unescape(re.sub(r"<[^>]+>", "", text)).strip()
    title, _, body = plain.partition("\n")
    topic = os.getenv("NTFY_TOPIC", "").strip()
    if not topic:
        print("── (NTFY_TOPIC nesetat, afișez mesajul) ──\n" + plain + "\n")
        return
    server = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    for chunk in [body[i:i + 3500] for i in range(0, max(len(body), 1), 3500)]:
        r = requests.post(server, json={"topic": topic, "title": title, "message": chunk.strip() or title,
                                        "priority": priority}, timeout=15)
        if not r.ok:
            print("Eroare ntfy:", r.status_code, r.text)


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"alerted": {}, "heartbeat": ""}


def save_state(st: dict):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    st["alerted"] = {k: v for k, v in st["alerted"].items() if v >= cutoff}
    STATE_FILE.write_text(json.dumps(st, indent=1, sort_keys=True))


def load_journal() -> list:
    if not JOURNAL_FILE.exists():
        return []
    with JOURNAL_FILE.open() as f:
        return list(csv.DictReader(f))


def save_journal(rows: list):
    with JOURNAL_FILE.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=JOURNAL_COLS)
        w.writeheader()
        w.writerows(rows)


def fmt_price(x: float, ref: float | None = None) -> str:
    ref = abs(ref if ref is not None else x)
    dec = 5 if ref < 10 else 3 if ref < 200 else 2
    return f"{x:,.{dec}f}"


def pct(x):
    return "–" if not np.isfinite(x) else f"{x * 100:.0f}%"


def r_(x):
    return "–" if not np.isfinite(x) else f"{x:+.2f}R"


def trend_label(d: pd.DataFrame) -> str:
    last = d.iloc[-1]
    if last.ema50 > last.ema200 and last.Close > last.ema200:
        return "bullish"
    if last.ema50 < last.ema200 and last.Close < last.ema200:
        return "bearish"
    return "neutru"


# ──────────────────────────── SCAN ────────────────────────────
def scan(now: datetime | None = None):
    now = now or datetime.now(timezone.utc)
    st = load_state()
    journal = load_journal()
    for row in journal:
        if row["status"] == "open" and (row["tf"] not in C.TIMEFRAMES or row["setup"] not in SETUPS):
            row["status"] = "expired"
    sent = 0
    for name, ticker in C.INSTRUMENTS.items():
        frames = {}
        for tf, period in C.TIMEFRAMES.items():
            try:
                raw = fetch(ticker, tf, period)
            except Exception as e:
                print(f"[{name} {tf}] eroare date: {e}")
                continue
            if len(raw) < 300:
                print(f"[{name} {tf}] prea puține date ({len(raw)})")
                continue
            frames[tf] = add_indicators(closed_bars(raw, tf, now))
        h1_trend = trend_label(frames["1h"]) if "1h" in frames else "?"

        for tf, d in frames.items():
            update_journal(journal, name, tf, d)
            i_now = len(d) - 1
            bar_close = d.index[-1] + pd.Timedelta(minutes=C.TF_MINUTES[tf])
            if now - bar_close > timedelta(minutes=2 * C.TF_MINUTES[tf]):
                continue  # piața e închisă / date vechi
            feat = features(d)
            for setup, (fn, desc) in SETUPS.items():
                sig = fn(d).fillna(0).astype(int)
                direction = int(sig.iloc[-1])
                if direction == 0:
                    continue
                key = f"{name}|{tf}|{setup}|{d.index[-1].isoformat()}"
                if key in st["alerted"]:
                    continue
                hist = history_for(d, sig, direction, tf, upto=i_now)
                h = stats(hist.r)
                knn = similar_cases(feat, hist, i_now)
                stable = stability(hist)
                has_edge = h["n"] >= C.MIN_SAMPLES and h["exp"] > C.MIN_EXPECTANCY and stable and \
                    (knn["k"] == 0 or knn["exp"] > 0)
                st["alerted"][key] = now.isoformat()
                if not has_edge and not C.SEND_WEAK:
                    print(f"[{name} {tf}] {setup} {direction:+d} filtrat (n={h['n']}, exp={h['exp']})")
                    continue
                last = d.iloc[-1]
                risk = C.SL_ATR * last.atr
                sl, tp = last.Close - direction * risk, last.Close + direction * C.TP_R * risk
                news = upcoming_news(name, now)
                send(format_alert(name, tf, setup, desc, direction, last, bar_close, risk, sl, tp,
                                  h, knn, stable, h1_trend, news, has_edge))
                sent += 1
                journal.append({"signal_time": d.index[-1].isoformat(), "instrument": name, "tf": tf,
                                "setup": setup, "direction": direction, "entry_ref": round(last.Close, 5),
                                "sl": round(sl, 5), "tp": round(tp, 5), "hist_n": h["n"],
                                "hist_exp": round(h["exp"], 3) if np.isfinite(h["exp"]) else "",
                                "knn_exp": round(knn["exp"], 3) if np.isfinite(knn["exp"]) else "",
                                "status": "open", "result_r": ""})
    today = now.strftime("%Y-%m-%d")
    if st.get("heartbeat") != today:
        st["heartbeat"] = today  # un commit pe zi ține workflow-ul GitHub activ
    save_state(st)
    save_journal(journal)
    print(f"Scan terminat: {sent} alerte trimise.")


def format_alert(name, tf, setup, desc, direction, last, bar_close, risk, sl, tp,
                 h, knn, stable, h1_trend, news, has_edge) -> str:
    side = "🟢 LONG" if direction == 1 else "🔴 SHORT"
    tf_label = tf.upper() if tf == "1h" else "M15"
    local = bar_close.tz_convert(_tz()).strftime("%d.%m %H:%M")
    agree = (h1_trend == "bullish" and direction == 1) or (h1_trend == "bearish" and direction == -1)
    lines = [
        f"<b>{side} {name}</b> ({tf_label}) — {setup.replace('_', ' ')} · {C.BOT_NAME}",
        f"<i>{desc}</i>",
        "",
        f"Preț la semnal: <b>{fmt_price(last.Close)}</b> (bară închisă {local})",
        f"SL: {fmt_price(sl)}  ({'-' if direction == 1 else '+'}{fmt_price(risk, last.Close)} = {C.SL_ATR}×ATR)",
        f"TP: {fmt_price(tp)}  ({'+' if direction == 1 else '-'}{fmt_price(risk * C.TP_R, last.Close)} = {C.TP_R:g}R)",
        "",
        f"📊 <b>Istoric</b> ({name} {tf_label}, aceeași direcție): {h['n']} cazuri · "
        f"{pct(h['win'])} câștigătoare · {r_(h['exp'])}/trade · PF {h['pf']:.2f}" if h["n"] else
        "📊 Istoric: fără cazuri suficiente",
        f"🔎 <b>Cele mai asemănătoare {knn['k']} situații</b>: {pct(knn['win'])} câștigătoare · {r_(knn['exp'])}/trade"
        if knn["k"] else "🔎 Situații asemănătoare: prea puține",
        f"{'✅ Edge prezent în ambele jumătăți ale istoricului' if stable else '⚠️ Edge instabil în timp (doar într-o parte a istoricului)'}",
        f"🧭 Trend H1: {h1_trend} {'(în favoare)' if agree else '(contra trendului)' if h1_trend != 'neutru' else ''}",
    ]
    if news:
        lines.append("📰 <b>Știri cu impact mare:</b> " + "; ".join(news))
    if not has_edge:
        lines.append("❗ Setup fără edge istoric clar — doar informativ.")
    lines.append("")
    lines.append("<i>Prețurile sunt din feed-ul Yahoo; la broker aplică aceleași distanțe SL/TP față de prețul tău.</i>")
    return "\n".join(lines)


def update_journal(journal: list, name: str, tf: str, d: pd.DataFrame):
    for row in journal:
        if row["status"] != "open" or row["instrument"] != name or row["tf"] != tf:
            continue
        ts = pd.Timestamp(row["signal_time"])
        if ts not in d.index:
            if ts < d.index[0]:
                row["status"] = "expired"
            continue
        r = simulate(d, d.index.get_loc(ts), int(row["direction"]), tf)
        if np.isfinite(r):
            row["status"] = "win" if r > 0 else "loss"
            row["result_r"] = round(r, 3)


# ─────────────────────────── REPORT ───────────────────────────
def report():
    rows = []
    for name, ticker in C.INSTRUMENTS.items():
        for tf, period in C.TIMEFRAMES.items():
            try:
                raw = fetch(ticker, tf, period)
            except Exception as e:
                print(f"[{name} {tf}] eroare: {e}")
                continue
            if len(raw) < 300:
                continue
            d = add_indicators(raw)
            for setup, (fn, _) in SETUPS.items():
                sig = fn(d).fillna(0).astype(int)
                for direction in (1, -1):
                    hist = history_for(d, sig, direction, tf, upto=len(d))
                    s = stats(hist.r)
                    rows.append({"instrument": name, "tf": tf, "setup": setup,
                                 "dir": "long" if direction == 1 else "short",
                                 **s, "stable": stability(hist)})
    df = pd.DataFrame(rows)
    if df.empty:
        send("Raport: nu am putut descărca date.")
        return
    df = df.sort_values("exp", ascending=False)
    REPORT_FILE.parent.mkdir(exist_ok=True)
    with REPORT_FILE.open("w") as f:
        f.write(f"# Backtest Market Radar — {datetime.now(timezone.utc):%Y-%m-%d}\n\n")
        f.write(f"SL {C.SL_ATR}×ATR, TP {C.TP_R}R, cost {C.COST_R}R/trade. Expectancy = R mediu pe trade.\n\n")
        f.write("| Instrument | TF | Setup | Dir | N | Win | Exp | PF | Stabil |\n|---|---|---|---|---|---|---|---|---|\n")
        for _, x in df.iterrows():
            f.write(f"| {x.instrument} | {x.tf} | {x.setup} | {x.dir} | {x.n} | {pct(x.win)} | "
                    f"{r_(x.exp)} | {x.pf:.2f} | {'da' if x.stable else 'nu'} |\n")
    good = df[(df.n >= C.MIN_SAMPLES) & (df.exp > 0) & df.stable]
    msg = [f"<b>📈 Raport săptămânal · {C.BOT_NAME}</b>",
           f"Combinații testate: {len(df)} · cu edge stabil (≥{C.MIN_SAMPLES} cazuri): <b>{len(good)}</b>", ""]
    msg.append("<b>Top setup-uri:</b>")
    for _, x in good.head(10).iterrows():
        msg.append(f"• {x.instrument} {x.tf} {x.setup} {x.dir}: {x.n} cazuri, {pct(x.win)}, {r_(x.exp)}")
    if good.empty:
        msg.append("• niciunul nu trece filtrele acum")
    j = pd.DataFrame(load_journal())
    if not j.empty:
        done = j[j.status.isin(["win", "loss"])]
        r = pd.to_numeric(done.result_r, errors="coerce")
        msg += ["", f"<b>Jurnal alerte:</b> {len(j)} total · {len(done)} închise · "
                f"{pct((r > 0).mean()) if len(r) else '–'} câștigătoare · {r.sum():+.1f}R cumulat"]
    send("\n".join(msg), priority=3)
    print(f"Raport scris în {REPORT_FILE}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if cmd == "scan":
        scan()
    elif cmd == "report":
        report()
    elif cmd == "test":
        send(f"✅ {C.BOT_NAME} e conectat\nSetup-uri: {', '.join(SETUPS)} · TF: {', '.join(C.TIMEFRAMES)} · SL {C.SL_ATR}×ATR · TP {C.TP_R:g}R")
    else:
        print(__doc__)

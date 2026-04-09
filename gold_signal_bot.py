"""
╔══════════════════════════════════════════════════════════╗
║         GOLD SIGNAL BOT PRO v2 — XAU/USD                ║
║         Multi-Timeframe: M15 + H1 + H4 + D1             ║
║         Scalping & Swing | Telegram Alert                ║
╚══════════════════════════════════════════════════════════╝
"""

import requests
import pandas as pd
import numpy as np
import schedule
import time
from datetime import datetime, timezone, timedelta

# ═══════════════════════════════════════════════════════════
#  ⚙️  KONFIGURASI — ISI BAGIAN INI SAJA
# ═══════════════════════════════════════════════════════════
TELEGRAM_TOKEN  = "8730178125:AAGDKqhgTs7E21LrjUEf76j2J0TeYBI60gY"
CHAT_ID         = "7118844737"
TWELVE_DATA_KEY = "100d92529e674de18d861f050118c7b4"

MODAL_USDT      = 400       # modal kamu dalam USDT
RISK_PERSEN     = 1.0       # risk per trade (%)
LOT_SIZE        = 0.01      # lot size tetap
SYMBOL          = "XAU/USD"
MIN_SCORE       = 5.0       # minimum score untuk kirim sinyal
SCAN_MENIT      = 15        # scan setiap X menit
# ═══════════════════════════════════════════════════════════


# ───────────────────────────────────────────────────────────
#  WAKTU & SESI
# ───────────────────────────────────────────────────────────
def wib():
    return datetime.now(timezone.utc) + timedelta(hours=7)

def utc_h():
    return datetime.now(timezone.utc).hour

def sesi_aktif():
    h = utc_h()
    s = []
    if 7  <= h < 16: s.append("London 🇬🇧")
    if 12 <= h < 21: s.append("New York 🇺🇸")
    if 23 <= h or h < 7: s.append("Tokyo/Sydney 🌏")
    return s or ["Off-session ⏸"]

def is_prime_session():
    h = utc_h()
    return (7 <= h < 16) or (12 <= h < 21)


# ───────────────────────────────────────────────────────────
#  AMBIL DATA
# ───────────────────────────────────────────────────────────
def fetch_data(interval="1h", bars=200):
    try:
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol":     SYMBOL,
                "interval":   interval,
                "outputsize": bars,
                "apikey":     TWELVE_DATA_KEY,
                "format":     "JSON"
            }, timeout=15
        )
        d = r.json()
        if "values" not in d:
            raise ValueError(d.get("message", "No values"))

        df = pd.DataFrame(d["values"])
        for c in ["open","high","low","close"]:
            df[c] = pd.to_numeric(df[c])
        df["volume"] = pd.to_numeric(df.get("volume", pd.Series([5000]*len(df)))).fillna(5000)
        df = df.sort_values("datetime").reset_index(drop=True)
        return df
    except Exception as e:
        print(f"  Gagal ambil data {interval}: {e}")
        return None


# ───────────────────────────────────────────────────────────
#  INDIKATOR
# ───────────────────────────────────────────────────────────
def ema(s, n):  return s.ewm(span=n, adjust=False).mean()
def sma(s, n):  return s.rolling(n).mean()

def calc_rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def calc_macd(s):
    ml = ema(s,12) - ema(s,26)
    sg = ema(ml, 9)
    return ml, sg, ml - sg

def calc_atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def calc_bb(s, n=20, k=2):
    mid = sma(s, n)
    std = s.rolling(n).std()
    return mid + k*std, mid, mid - k*std

def calc_stoch(df, k=14, d=3):
    lo = df["low"].rolling(k).min()
    hi = df["high"].rolling(k).max()
    kk = 100 * (df["close"] - lo) / (hi - lo).replace(0, np.nan)
    return kk, kk.rolling(d).mean()

def calc_supertrend(df, n=10, mult=3.0):
    atr_v = calc_atr(df, n)
    hl2   = (df["high"] + df["low"]) / 2
    up    = hl2 - mult * atr_v
    dn    = hl2 + mult * atr_v
    trend = pd.Series(1, index=df.index)
    sup   = up.copy()
    sdn   = dn.copy()
    for i in range(1, len(df)):
        sup.iloc[i] = max(up.iloc[i], sup.iloc[i-1]) if df["close"].iloc[i-1] > sup.iloc[i-1] else up.iloc[i]
        sdn.iloc[i] = min(dn.iloc[i], sdn.iloc[i-1]) if df["close"].iloc[i-1] < sdn.iloc[i-1] else dn.iloc[i]
        if df["close"].iloc[i] > sdn.iloc[i-1]:    trend.iloc[i] = 1
        elif df["close"].iloc[i] < sup.iloc[i-1]:  trend.iloc[i] = -1
        else: trend.iloc[i] = trend.iloc[i-1]
    return trend

def detect_sr(df, lookback=50):
    recent = df.tail(lookback)
    highs  = recent["high"].values
    lows   = recent["low"].values
    supports, resistances = [], []
    for i in range(2, len(highs)-2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            resistances.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            supports.append(lows[i])
    return supports, resistances

def add_indicators(df):
    df = df.copy()
    c  = df["close"]
    df["ema20"]  = ema(c, 20)
    df["ema50"]  = ema(c, 50)
    df["ema200"] = ema(c, 200)
    df["rsi"]    = calc_rsi(c, 14)
    df["macd_l"], df["macd_s"], df["macd_h"] = calc_macd(c)
    df["stoch_k"], df["stoch_d"] = calc_stoch(df)
    df["atr"]    = calc_atr(df, 14)
    df["bb_up"], df["bb_mid"], df["bb_lo"] = calc_bb(c, 20)
    df["supertrend"] = calc_supertrend(df, 10, 3.0)
    df["vol_ma"] = sma(df["volume"], 20)
    df["vol_r"]  = df["volume"] / df["vol_ma"].replace(0, np.nan)
    return df.dropna()


# ───────────────────────────────────────────────────────────
#  ANALISA SINYAL
# ───────────────────────────────────────────────────────────
def analyze(df, tf_type="swing"):
    n  = df.iloc[-1]
    n1 = df.iloc[-2]

    p    = n["close"]
    bull = 0.0
    bear = 0.0
    info = {}

    # 1. EMA Stack (bobot 2)
    if n["ema20"] > n["ema50"] > n["ema200"]:
        bull += 2.0; info["1. EMA Stack"] = "✅ Bullish (20>50>200)"
    elif n["ema20"] < n["ema50"] < n["ema200"]:
        bear += 2.0; info["1. EMA Stack"] = "✅ Bearish (20<50<200)"
    else:
        info["1. EMA Stack"] = "⚪ Mixed"

    # 2. Supertrend (bobot 2)
    if n["supertrend"] == 1:
        bull += 2.0; info["2. Supertrend"] = "✅ Bullish"
    else:
        bear += 2.0; info["2. Supertrend"] = "✅ Bearish"

    # 3. RSI
    rsi = n["rsi"]
    if 40 <= rsi <= 60:
        info["3. RSI"] = f"⚪ Netral ({rsi:.1f})"
    elif rsi < 40:
        bull += 1.0; info["3. RSI"] = f"✅ Oversold ({rsi:.1f})"
    else:
        bear += 1.0; info["3. RSI"] = f"✅ Overbought ({rsi:.1f})"

    # 4. MACD
    if n["macd_l"] > n["macd_s"] and n["macd_h"] > n1["macd_h"]:
        bull += 1.0; info["4. MACD"] = "✅ Bullish momentum"
    elif n["macd_l"] < n["macd_s"] and n["macd_h"] < n1["macd_h"]:
        bear += 1.0; info["4. MACD"] = "✅ Bearish momentum"
    else:
        info["4. MACD"] = "⚪ Netral"

    # 5. Stochastic
    sk, sd = n["stoch_k"], n["stoch_d"]
    if sk < 25 and sk > sd:
        bull += 1.0; info["5. Stoch"] = f"✅ Oversold cross up ({sk:.0f})"
    elif sk > 75 and sk < sd:
        bear += 1.0; info["5. Stoch"] = f"✅ Overbought cross dn ({sk:.0f})"
    else:
        info["5. Stoch"] = f"⚪ Netral ({sk:.0f})"

    # 6. Bollinger Band
    if p <= n["bb_lo"] * 1.001:
        bull += 1.0; info["6. BB"] = "✅ Harga di BB bawah"
    elif p >= n["bb_up"] * 0.999:
        bear += 1.0; info["6. BB"] = "✅ Harga di BB atas"
    else:
        info["6. BB"] = "⚪ Di dalam BB"

    # 7. Volume
    if n["vol_r"] > 1.3:
        if n["close"] > n["open"]: bull += 0.5; info["7. Volume"] = f"✅ Volume spike bullish ({n['vol_r']:.1f}x)"
        else: bear += 0.5; info["7. Volume"] = f"✅ Volume spike bearish ({n['vol_r']:.1f}x)"
    else:
        info["7. Volume"] = f"⚪ Volume normal ({n['vol_r']:.1f}x)"

    # 8. Support/Resistance
    supports, resistances = detect_sr(df)
    if supports:
        ns = min(supports, key=lambda x: abs(x-p))
        if abs(p - ns) / p < 0.003:
            bull += 1.0; info["8. S/R"] = f"✅ Dekat support ${ns:.2f}"
        else:
            info["8. S/R"] = f"⚪ Support terdekat ${ns:.2f}"
    if resistances:
        nr = min(resistances, key=lambda x: abs(x-p))
        if abs(p - nr) / p < 0.003:
            bear += 1.0; info["8. S/R"] = f"✅ Dekat resistance ${nr:.2f}"

    # 9. Candle pattern
    body  = abs(n["close"] - n["open"])
    rang  = n["high"] - n["low"]
    lwk   = min(n["close"], n["open"]) - n["low"]
    uwk   = n["high"] - max(n["close"], n["open"])
    if rang > 0:
        if lwk > body * 2 and uwk < body:
            bull += 0.5; info["9. Candle"] = "✅ Pin bar bullish"
        elif uwk > body * 2 and lwk < body:
            bear += 0.5; info["9. Candle"] = "✅ Pin bar bearish"
        elif n["close"] > n["open"] and n1["close"] < n1["open"] and n["open"] < n1["close"] and n["close"] > n1["open"]:
            bull += 0.5; info["9. Candle"] = "✅ Engulfing bullish"
        elif n["close"] < n["open"] and n1["close"] > n1["open"] and n["open"] > n1["close"] and n["close"] < n1["open"]:
            bear += 0.5; info["9. Candle"] = "✅ Engulfing bearish"
        else:
            info["9. Candle"] = "⚪ Normal"

    # 10. Sesi trading
    if is_prime_session():
        if bull > bear: bull += 0.5
        elif bear > bull: bear += 0.5
        info["10. Sesi"] = "✅ Prime session aktif"
    else:
        info["10. Sesi"] = "⚪ Off-session"

    score = max(bull, bear)
    total = 10.0

    if bull > bear and bull >= MIN_SCORE:
        direction = "BUY"
    elif bear > bull and bear >= MIN_SCORE:
        direction = "SELL"
    else:
        direction = "WAIT"

    # Hitung SL/TP
    atr = n["atr"]
    if tf_type == "scalping":
        sl_mult, tp_mult = 1.0, 1.5
    else:
        sl_mult, tp_mult = 1.5, 3.0

    if direction == "BUY":
        sl  = round(p - atr * sl_mult, 2)
        tp1 = round(p + atr * tp_mult, 2)
        tp2 = round(p + atr * tp_mult * 1.5, 2)
    elif direction == "SELL":
        sl  = round(p + atr * sl_mult, 2)
        tp1 = round(p - atr * tp_mult, 2)
        tp2 = round(p - atr * tp_mult * 1.5, 2)
    else:
        sl = tp1 = tp2 = p

    sl_d      = abs(p - sl)
    lot       = LOT_SIZE
    # Risk sebenarnya: jarak SL x lot x 100 (1 lot gold = $100 per $1)
    risk_real = round(sl_d * lot * 100, 2)
    rr        = round(abs(tp1 - p) / sl_d, 1) if sl_d > 0 else 0
    wr        = min(50 + int(score * 4), 82)

    return {
        "direction":  direction,
        "score":      round(score, 1),
        "max":        total,
        "bull":       round(bull, 1),
        "bear":       round(bear, 1),
        "price":      round(p, 3),
        "sl":         sl, "tp1": tp1, "tp2": tp2,
        "sl_d":       round(sl_d, 2),
        "lot":        lot,
        "risk_real":  risk_real,
        "rr":         rr, "wr": wr,
        "atr":        round(atr, 2),
        "ema20":      round(n["ema20"], 2),
        "ema50":      round(n["ema50"], 2),
        "ema200":     round(n["ema200"], 2),
        "rsi":        round(rsi, 1),
        "sessions":   sesi_aktif(),
        "info":       info,
    }


# ───────────────────────────────────────────────────────────
#  FORMAT PESAN TELEGRAM
# ───────────────────────────────────────────────────────────
def buat_pesan(s, tf_label, tf_type):
    d   = s["direction"]
    now = wib()

    if d == "BUY":
        head = "🟢🟢🟢 <b>SINYAL BUY — GOLD XAU/USD</b> 🟢🟢🟢"
        icon = "▲"
    elif d == "SELL":
        head = "🔴🔴🔴 <b>SINYAL SELL — GOLD XAU/USD</b> 🔴🔴🔴"
        icon = "▼"
    else:
        return None

    bar  = "█" * int(s["score"]) + "░" * max(0, int(s["max"] - s["score"]))
    tipe = "⚡ SCALPING" if tf_type == "scalping" else "🌊 SWING"

    msg = (
        f"{head}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {now.strftime('%d %b %Y  %H:%M')} WIB\n"
        f"{tipe} | TF: {tf_label}\n"
        f"📡 Sesi: {' | '.join(s['sessions'])}\n\n"
        f"💰 Harga  : <b>${s['price']:,.3f}</b>\n"
        f"{icon} Arah   : <b>{d}</b>\n\n"
        f"📊 <b>Score: {s['score']}/{s['max']}</b>\n"
        f"[{bar}]\n"
        f"🎯 Est. Win Rate : <b>{s['wr']}%</b>\n"
        f"💹 Risk/Reward   : <b>1:{s['rr']}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>RENCANA ENTRY:</b>\n"
        f"├ Entry     : <b>${s['price']:,.3f}</b>\n"
        f"├ TP 1      : <b>${s['tp1']:,.3f}</b>\n"
        f"├ TP 2      : <b>${s['tp2']:,.3f}</b>\n"
        f"└ Stop Loss : <b>${s['sl']:,.3f}</b>\n\n"
        f"💼 Risk: <b>${s['risk_real']:.2f}</b> | Lot: <b>{s['lot']}</b> | ATR: ${s['atr']:.2f}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 <b>HASIL ANALISA:</b>\n"
    )
    for k, v in s["info"].items():
        msg += f"{k}: {v}\n"

    msg += (
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 EMA20: ${s['ema20']:,.2f} | EMA50: ${s['ema50']:,.2f} | EMA200: ${s['ema200']:,.2f}\n"
        f"📌 RSI: {s['rsi']} | Bull: {s['bull']} | Bear: {s['bear']}\n\n"
        f"⚠️ <i>Eksekusi MANUAL. Selalu pasang SL sebelum entry!\n"
        f"Jangan FOMO. Trading konsisten > trading sering.</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )
    return msg


def kirim_telegram(pesan):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": pesan, "parse_mode": "HTML"},
            timeout=12
        )
        if r.status_code == 200:
            print("  Telegram terkirim")
            return True
        print(f"  Telegram error: {r.text[:100]}")
        return False
    except Exception as e:
        print(f"  Telegram exception: {e}")
        return False


def buat_pesan_startup():
    now = wib()
    return (
        f"🤖 <b>GOLD SIGNAL BOT PRO v2 — AKTIF!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Pair       : XAU/USD (Gold)\n"
        f"✅ Timeframe  : M15 + H1 (Scalping) | H4 + D1 (Swing)\n"
        f"✅ Modal      : ${MODAL_USDT} USDT\n"
        f"✅ Lot Size   : {LOT_SIZE}\n"
        f"✅ Min Score  : {MIN_SCORE}/10\n\n"
        f"📊 <b>10 Filter Analisa:</b>\n"
        f"1. EMA Stack 20/50/200\n"
        f"2. Supertrend\n"
        f"3. RSI 14\n"
        f"4. MACD\n"
        f"5. Stochastic\n"
        f"6. Bollinger Band\n"
        f"7. Volume Spike\n"
        f"8. Support/Resistance\n"
        f"9. Candlestick Pattern\n"
        f"10. Session Filter\n\n"
        f"⏱️ Scan otomatis setiap {SCAN_MENIT} menit\n"
        f"🏆 Sesi terbaik: London & New York\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━"
    )


# ───────────────────────────────────────────────────────────
#  MAIN LOOP
# ───────────────────────────────────────────────────────────
sinyal_terakhir = {}

def jalankan_analisa():
    global sinyal_terakhir
    now = wib()
    print(f"\n{'='*50}")
    print(f"  Analisa: {now.strftime('%d %b %Y %H:%M')} WIB")
    print(f"{'='*50}")

    sinyal_dikirim = 0

    # SCALPING: M15 + H1
    df_m15 = fetch_data("15min", 200)
    df_h1  = fetch_data("1h", 200)

    if df_m15 is not None and df_h1 is not None and len(df_m15) > 50 and len(df_h1) > 50:
        df_m15  = add_indicators(df_m15)
        df_h1   = add_indicators(df_h1)
        sig_m15 = analyze(df_m15, "scalping")
        sig_h1  = analyze(df_h1,  "scalping")

        print(f"  SCALP M15: {sig_m15['direction']} score={sig_m15['score']} | H1: {sig_h1['direction']} score={sig_h1['score']}")

        if sig_m15["direction"] == sig_h1["direction"] and sig_m15["direction"] != "WAIT":
            sig_gabung = sig_m15.copy()
            sig_gabung["score"] = min(round((sig_m15["score"] + sig_h1["score"]) / 2 * 1.1, 1), 10)
            key = f"SCALP_{sig_gabung['direction']}_{int(sig_gabung['price'])}"
            if key != sinyal_terakhir.get("scalp"):
                pesan = buat_pesan(sig_gabung, "M15 + H1", "scalping")
                if pesan and kirim_telegram(pesan):
                    sinyal_terakhir["scalp"] = key
                    sinyal_dikirim += 1

    # SWING: H4 + D1
    df_h4 = fetch_data("4h", 200)
    df_d1 = fetch_data("1day", 200)

    if df_h4 is not None and df_d1 is not None and len(df_h4) > 50 and len(df_d1) > 50:
        df_h4  = add_indicators(df_h4)
        df_d1  = add_indicators(df_d1)
        sig_h4 = analyze(df_h4, "swing")
        sig_d1 = analyze(df_d1, "swing")

        print(f"  SWING  H4: {sig_h4['direction']} score={sig_h4['score']} | D1: {sig_d1['direction']} score={sig_d1['score']}")

        if sig_h4["direction"] == sig_d1["direction"] and sig_h4["direction"] != "WAIT":
            sig_gabung = sig_h4.copy()
            sig_gabung["score"] = min(round((sig_h4["score"] + sig_d1["score"]) / 2 * 1.1, 1), 10)
            key = f"SWING_{sig_gabung['direction']}_{int(sig_gabung['price'])}"
            if key != sinyal_terakhir.get("swing"):
                pesan = buat_pesan(sig_gabung, "H4 + D1", "swing")
                if pesan and kirim_telegram(pesan):
                    sinyal_terakhir["swing"] = key
                    sinyal_dikirim += 1

    if sinyal_dikirim == 0:
        print(f"  Tidak ada sinyal valid saat ini.")


# ───────────────────────────────────────────────────────────
#  START
# ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("="*50)
    print("  GOLD SIGNAL BOT PRO v2 — XAU/USD")
    print(f"  Lot: {LOT_SIZE} | Min Score: {MIN_SCORE}/10")
    print("="*50)

    kirim_telegram(buat_pesan_startup())
    time.sleep(10)
    jalankan_analisa()

    schedule.every(SCAN_MENIT).minutes.do(jalankan_analisa)

    print(f"\nBot berjalan! Scan setiap {SCAN_MENIT} menit.")
    print("Tekan Ctrl+C untuk berhenti.\n")

    while True:
        schedule.run_pending()
        time.sleep(30)

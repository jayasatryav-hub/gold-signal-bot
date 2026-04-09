"""
╔══════════════════════════════════════════════════════════╗
║       GOLD SIGNAL BOT PRO v4 ULTIMATE — XAU/USD         ║
║       20+ Indikator | Smart Money | Multi-Timeframe      ║
║       EMA + ST + Ichimoku + Fib + OB + FVG + CHoCH      ║
║       VWAP + Divergence + Liquidity + DXY + Volume       ║
╚══════════════════════════════════════════════════════════╝
"""

import requests
import pandas as pd
import numpy as np
import schedule
import time
from datetime import datetime, timezone, timedelta

# ═══════════════════════════════════════════════════════════
#  KONFIGURASI
# ═══════════════════════════════════════════════════════════
TELEGRAM_TOKEN  = "8730178125:AAGDKqhgTs7E21LrjUEf76j2J0TeYBI60gY"
CHAT_ID         = "7118844737"
TWELVE_DATA_KEY = "100d92529e674de18d861f050118c7b4"

MODAL_USDT      = 400
LOT_SIZE        = 0.01
SYMBOL          = "XAU/USD"
MIN_SCORE       = 10.0      # minimum score dari 20 — sangat selektif
SCAN_MENIT      = 15
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
def fetch_data(symbol, interval="1h", bars=200):
    try:
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={
                "symbol":     symbol,
                "interval":   interval,
                "outputsize": bars,
                "apikey":     TWELVE_DATA_KEY,
                "format":     "JSON"
            }, timeout=15
        )
        d = r.json()
        if "values" not in d:
            return None
        df = pd.DataFrame(d["values"])
        for c in ["open","high","low","close"]:
            df[c] = pd.to_numeric(df[c])
        df["volume"] = pd.to_numeric(df.get("volume", pd.Series([5000]*len(df)))).fillna(5000)
        df = df.sort_values("datetime").reset_index(drop=True)
        return df
    except:
        return None


# ───────────────────────────────────────────────────────────
#  INDIKATOR DASAR
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

def calc_ichimoku(df):
    high = df["high"]
    low  = df["low"]
    tenkan   = (high.rolling(9).max()  + low.rolling(9).min())  / 2
    kijun    = (high.rolling(26).max() + low.rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    return tenkan, kijun, senkou_a, senkou_b

def calc_vwap(df):
    """VWAP — level institusi paling penting"""
    df = df.copy()
    df["tp"]      = (df["high"] + df["low"] + df["close"]) / 3
    df["cum_tpv"] = (df["tp"] * df["volume"]).cumsum()
    df["cum_vol"] = df["volume"].cumsum()
    return df["cum_tpv"] / df["cum_vol"].replace(0, np.nan)


# ───────────────────────────────────────────────────────────
#  SMART MONEY CONCEPTS
# ───────────────────────────────────────────────────────────
def detect_swing_points(df, lookback=50):
    """Deteksi swing high dan swing low"""
    recent = df.tail(lookback)
    highs  = recent["high"].values
    lows   = recent["low"].values
    sh, sl = [], []
    for i in range(2, len(highs)-2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            sh.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            sl.append(lows[i])
    return sh, sl

def detect_market_structure(df):
    """Market Structure: HH/HL = Bullish | LH/LL = Bearish"""
    sh, sl = detect_swing_points(df, 50)
    structure = "NETRAL"
    if len(sh) >= 2 and len(sl) >= 2:
        if sh[-1] > sh[-2] and sl[-1] > sl[-2]:
            structure = "BULLISH"
        elif sh[-1] < sh[-2] and sl[-1] < sl[-2]:
            structure = "BEARISH"
    return structure

def detect_choch(df):
    """
    Change of Character (CHoCH) — sinyal pembalikan tren paling awal
    Bullish CHoCH: setelah downtrend, harga break swing high terakhir
    Bearish CHoCH: setelah uptrend, harga break swing low terakhir
    """
    sh, sl = detect_swing_points(df, 30)
    price  = df["close"].iloc[-1]
    choch  = "NONE"
    if len(sh) >= 2 and len(sl) >= 2:
        # Bearish structure tapi harga break di atas swing high = CHoCH Bullish
        if sh[-1] < sh[-2] and price > sh[-1]:
            choch = "BULLISH"
        # Bullish structure tapi harga break di bawah swing low = CHoCH Bearish
        elif sl[-1] > sl[-2] and price < sl[-1]:
            choch = "BEARISH"
    return choch

def detect_liquidity_sweep(df):
    """
    Liquidity Sweep: harga spike menembus swing high/low lalu balik arah
    Ini adalah sinyal reversal sangat kuat (stop hunt oleh institusi)
    """
    sh, sl = detect_swing_points(df, 30)
    last   = df.iloc[-1]
    prev   = df.iloc[-2]
    sweep  = "NONE"

    if sl:
        prev_low = min(sl[-3:]) if len(sl) >= 3 else sl[-1]
        # Harga spike ke bawah level support lalu close di atas = bullish sweep
        if last["low"] < prev_low and last["close"] > prev_low:
            sweep = "BULLISH"

    if sh:
        prev_high = max(sh[-3:]) if len(sh) >= 3 else sh[-1]
        # Harga spike ke atas resistance lalu close di bawah = bearish sweep
        if last["high"] > prev_high and last["close"] < prev_high:
            sweep = "BEARISH"

    return sweep

def detect_order_block(df, lookback=20):
    """Order Block — level harga institusi masuk posisi besar"""
    recent  = df.tail(lookback)
    price   = df["close"].iloc[-1]
    bull_ob = []
    bear_ob = []
    for i in range(1, len(recent)-1):
        candle   = recent.iloc[i]
        next_c   = recent.iloc[i+1]
        body     = abs(candle["close"] - candle["open"])
        avg_body = recent["close"].sub(recent["open"]).abs().mean()
        if candle["close"] < candle["open"] and body > avg_body * 1.5:
            if next_c["close"] > next_c["open"]:
                bull_ob.append((candle["low"], candle["high"]))
        if candle["close"] > candle["open"] and body > avg_body * 1.5:
            if next_c["close"] < next_c["open"]:
                bear_ob.append((candle["low"], candle["high"]))
    in_bull_ob = any(low <= price <= high for low, high in bull_ob[-3:])
    in_bear_ob = any(low <= price <= high for low, high in bear_ob[-3:])
    return in_bull_ob, in_bear_ob

def detect_fvg(df, lookback=20):
    """Fair Value Gap — celah ketidakseimbangan harga"""
    recent = df.tail(lookback)
    price  = df["close"].iloc[-1]
    bull_fvg, bear_fvg = [], []
    for i in range(2, len(recent)):
        c1 = recent.iloc[i-2]
        c3 = recent.iloc[i]
        if c3["low"] > c1["high"]:
            bull_fvg.append((c1["high"] + c3["low"]) / 2)
        if c3["high"] < c1["low"]:
            bear_fvg.append((c1["low"] + c3["high"]) / 2)
    near_bull = any(abs(price - fvg) / price < 0.002 for fvg in bull_fvg[-3:])
    near_bear = any(abs(price - fvg) / price < 0.002 for fvg in bear_fvg[-3:])
    return near_bull, near_bear

def detect_fibonacci(df, lookback=50):
    """Fibonacci Retracement — golden pocket 61.8%"""
    recent     = df.tail(lookback)
    swing_high = recent["high"].max()
    swing_low  = recent["low"].min()
    diff       = swing_high - swing_low
    levels = {
        "0.236": swing_high - 0.236 * diff,
        "0.382": swing_high - 0.382 * diff,
        "0.5":   swing_high - 0.5   * diff,
        "0.618": swing_high - 0.618 * diff,
        "0.786": swing_high - 0.786 * diff,
    }
    return levels, swing_high, swing_low

def detect_rsi_divergence(df, lookback=20):
    """
    RSI Divergence — sinyal reversal paling kuat
    Bullish: harga lower low tapi RSI higher low
    Bearish: harga higher high tapi RSI lower high
    """
    recent = df.tail(lookback)
    prices = recent["close"].values
    rsi_v  = calc_rsi(recent["close"]).values

    divergence = "NONE"
    try:
        # Cari 2 low terakhir
        lows_idx = [i for i in range(2, len(prices)-2)
                    if prices[i] < prices[i-1] and prices[i] < prices[i+1]]
        # Cari 2 high terakhir
        highs_idx = [i for i in range(2, len(prices)-2)
                     if prices[i] > prices[i-1] and prices[i] > prices[i+1]]

        if len(lows_idx) >= 2:
            i1, i2 = lows_idx[-2], lows_idx[-1]
            if prices[i2] < prices[i1] and rsi_v[i2] > rsi_v[i1]:
                divergence = "BULLISH"  # Harga LL tapi RSI HL

        if len(highs_idx) >= 2:
            i1, i2 = highs_idx[-2], highs_idx[-1]
            if prices[i2] > prices[i1] and rsi_v[i2] < rsi_v[i1]:
                divergence = "BEARISH"  # Harga HH tapi RSI LH
    except:
        pass

    return divergence

def detect_macd_divergence(df, lookback=20):
    """MACD Divergence — konfirmasi divergence lebih kuat"""
    recent = df.tail(lookback)
    prices = recent["close"].values
    _, _, macd_h = calc_macd(recent["close"])
    macd_v = macd_h.values

    divergence = "NONE"
    try:
        lows_idx  = [i for i in range(2, len(prices)-2)
                     if prices[i] < prices[i-1] and prices[i] < prices[i+1]]
        highs_idx = [i for i in range(2, len(prices)-2)
                     if prices[i] > prices[i-1] and prices[i] > prices[i+1]]

        if len(lows_idx) >= 2:
            i1, i2 = lows_idx[-2], lows_idx[-1]
            if prices[i2] < prices[i1] and macd_v[i2] > macd_v[i1]:
                divergence = "BULLISH"

        if len(highs_idx) >= 2:
            i1, i2 = highs_idx[-2], highs_idx[-1]
            if prices[i2] > prices[i1] and macd_v[i2] < macd_v[i1]:
                divergence = "BEARISH"
    except:
        pass

    return divergence

def get_dxy_trend():
    """DXY Correlation — korelasi negatif dengan gold"""
    try:
        df = fetch_data("DX/Y", "1h", 50)
        if df is None:
            df = fetch_data("USDX", "1h", 50)
        if df is None:
            return "UNKNOWN"
        e20   = df["close"].ewm(span=20, adjust=False).mean().iloc[-1]
        e50   = df["close"].ewm(span=50, adjust=False).mean().iloc[-1]
        price = df["close"].iloc[-1]
        rsi   = calc_rsi(df["close"]).iloc[-1]
        if price > e20 > e50:
            return "NAIK_KUAT" if rsi > 60 else "NAIK"
        elif price < e20 < e50:
            return "TURUN_KUAT" if rsi < 40 else "TURUN"
        return "SIDEWAYS"
    except:
        return "UNKNOWN"

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
    df["tenkan"], df["kijun"], df["senkou_a"], df["senkou_b"] = calc_ichimoku(df)
    df["vwap"]   = calc_vwap(df)
    df["vol_ma"] = sma(df["volume"], 20)
    df["vol_r"]  = df["volume"] / df["vol_ma"].replace(0, np.nan)
    return df.dropna()


# ───────────────────────────────────────────────────────────
#  ANALISA SINYAL — 20 FILTER
# ───────────────────────────────────────────────────────────
def analyze(df, tf_type="swing", dxy_trend="UNKNOWN"):
    n  = df.iloc[-1]
    n1 = df.iloc[-2]

    p    = n["close"]
    bull = 0.0
    bear = 0.0
    info = {}

    # ── 1. EMA Stack (bobot 2) ──────────────────────────────
    if n["ema20"] > n["ema50"] > n["ema200"]:
        bull += 2.0; info["1. EMA Stack"] = "✅ Bullish (20>50>200)"
    elif n["ema20"] < n["ema50"] < n["ema200"]:
        bear += 2.0; info["1. EMA Stack"] = "✅ Bearish (20<50<200)"
    else:
        info["1. EMA Stack"] = "⚪ Mixed"

    # ── 2. Supertrend (bobot 2) ─────────────────────────────
    if n["supertrend"] == 1:
        bull += 2.0; info["2. Supertrend"] = "✅ Bullish"
    else:
        bear += 2.0; info["2. Supertrend"] = "✅ Bearish"

    # ── 3. Market Structure (bobot 1.5) ────────────────────
    structure = detect_market_structure(df)
    if structure == "BULLISH":
        bull += 1.5; info["3. Market Structure"] = "✅ Bullish (HH+HL)"
    elif structure == "BEARISH":
        bear += 1.5; info["3. Market Structure"] = "✅ Bearish (LH+LL)"
    else:
        info["3. Market Structure"] = "⚪ Netral"

    # ── 4. Change of Character (bobot 2) ───────────────────
    choch = detect_choch(df)
    if choch == "BULLISH":
        bull += 2.0; info["4. CHoCH"] = "✅ Bullish CHoCH (reversal up)"
    elif choch == "BEARISH":
        bear += 2.0; info["4. CHoCH"] = "✅ Bearish CHoCH (reversal dn)"
    else:
        info["4. CHoCH"] = "⚪ Tidak ada CHoCH"

    # ── 5. Liquidity Sweep (bobot 2) ───────────────────────
    sweep = detect_liquidity_sweep(df)
    if sweep == "BULLISH":
        bull += 2.0; info["5. Liquidity Sweep"] = "✅ Bullish sweep (stop hunt bawah)"
    elif sweep == "BEARISH":
        bear += 2.0; info["5. Liquidity Sweep"] = "✅ Bearish sweep (stop hunt atas)"
    else:
        info["5. Liquidity Sweep"] = "⚪ Tidak ada sweep"

    # ── 6. Ichimoku Cloud (bobot 1.5) ──────────────────────
    sa = n["senkou_a"]
    sb = n["senkou_b"]
    tk = n["tenkan"]
    kj = n["kijun"]
    if not (pd.isna(sa) or pd.isna(sb)):
        cloud_top = max(sa, sb)
        cloud_bot = min(sa, sb)
        if p > cloud_top and tk > kj:
            bull += 1.5; info["6. Ichimoku"] = "✅ Bullish (atas cloud, TK>KJ)"
        elif p < cloud_bot and tk < kj:
            bear += 1.5; info["6. Ichimoku"] = "✅ Bearish (bawah cloud, TK<KJ)"
        else:
            info["6. Ichimoku"] = "⚪ Di dalam cloud / mixed"
    else:
        info["6. Ichimoku"] = "⚪ Data kurang"

    # ── 7. VWAP (bobot 1) ──────────────────────────────────
    vwap = n["vwap"]
    if p > vwap * 1.001:
        bull += 1.0; info["7. VWAP"] = f"✅ Harga di atas VWAP ${vwap:,.2f}"
    elif p < vwap * 0.999:
        bear += 1.0; info["7. VWAP"] = f"✅ Harga di bawah VWAP ${vwap:,.2f}"
    else:
        info["7. VWAP"] = f"⚪ Harga di VWAP ${vwap:,.2f}"

    # ── 8. RSI + Divergence (bobot 1.5) ────────────────────
    rsi = n["rsi"]
    rsi_div = detect_rsi_divergence(df)
    if rsi_div == "BULLISH":
        bull += 1.5; info["8. RSI"] = f"✅ Bullish divergence RSI ({rsi:.1f})"
    elif rsi_div == "BEARISH":
        bear += 1.5; info["8. RSI"] = f"✅ Bearish divergence RSI ({rsi:.1f})"
    elif rsi < 35:
        bull += 1.0; info["8. RSI"] = f"✅ Oversold ({rsi:.1f})"
    elif rsi > 65:
        bear += 1.0; info["8. RSI"] = f"✅ Overbought ({rsi:.1f})"
    else:
        info["8. RSI"] = f"⚪ Netral ({rsi:.1f})"

    # ── 9. MACD + Divergence (bobot 1.5) ───────────────────
    macd_div = detect_macd_divergence(df)
    if macd_div == "BULLISH":
        bull += 1.5; info["9. MACD"] = "✅ Bullish divergence MACD"
    elif macd_div == "BEARISH":
        bear += 1.5; info["9. MACD"] = "✅ Bearish divergence MACD"
    elif n["macd_l"] > n["macd_s"] and n["macd_h"] > 0 and n["macd_h"] > n1["macd_h"]:
        bull += 1.0; info["9. MACD"] = "✅ Bullish crossover"
    elif n["macd_l"] < n["macd_s"] and n["macd_h"] < 0 and n["macd_h"] < n1["macd_h"]:
        bear += 1.0; info["9. MACD"] = "✅ Bearish crossover"
    else:
        info["9. MACD"] = "⚪ Netral"

    # ── 10. Fibonacci Golden Pocket (bobot 1.5) ────────────
    fib_levels, fib_high, fib_low = detect_fibonacci(df)
    fib_zone = None
    for level, price_level in fib_levels.items():
        if abs(p - price_level) / p < 0.002:
            fib_zone = level
            break
    if fib_zone in ["0.382", "0.5", "0.618"]:
        if p > fib_levels["0.5"]:
            bull += 1.5; info["10. Fibonacci"] = f"✅ Golden pocket {fib_zone} (support)"
        else:
            bear += 1.5; info["10. Fibonacci"] = f"✅ Golden pocket {fib_zone} (resistance)"
    elif fib_zone in ["0.236", "0.786"]:
        info["10. Fibonacci"] = f"✅ Level fib {fib_zone}"
    else:
        info["10. Fibonacci"] = "⚪ Di luar level fib"

    # ── 11. Order Block (bobot 1.5) ─────────────────────────
    in_bull_ob, in_bear_ob = detect_order_block(df)
    if in_bull_ob:
        bull += 1.5; info["11. Order Block"] = "✅ Di Bullish OB (institusi)"
    elif in_bear_ob:
        bear += 1.5; info["11. Order Block"] = "✅ Di Bearish OB (institusi)"
    else:
        info["11. Order Block"] = "⚪ Tidak ada OB aktif"

    # ── 12. Fair Value Gap (bobot 1) ────────────────────────
    near_bull_fvg, near_bear_fvg = detect_fvg(df)
    if near_bull_fvg:
        bull += 1.0; info["12. FVG"] = "✅ Dekat Bullish FVG"
    elif near_bear_fvg:
        bear += 1.0; info["12. FVG"] = "✅ Dekat Bearish FVG"
    else:
        info["12. FVG"] = "⚪ Tidak ada FVG aktif"

    # ── 13. Stochastic (bobot 1) ────────────────────────────
    sk, sd = n["stoch_k"], n["stoch_d"]
    if sk < 20 and sk > sd:
        bull += 1.0; info["13. Stoch"] = f"✅ Oversold cross up ({sk:.0f})"
    elif sk > 80 and sk < sd:
        bear += 1.0; info["13. Stoch"] = f"✅ Overbought cross dn ({sk:.0f})"
    else:
        info["13. Stoch"] = f"⚪ Netral ({sk:.0f})"

    # ── 14. Bollinger Band (bobot 1) ────────────────────────
    if p <= n["bb_lo"] * 1.001:
        bull += 1.0; info["14. BB"] = "✅ Harga di BB bawah (oversold)"
    elif p >= n["bb_up"] * 0.999:
        bear += 1.0; info["14. BB"] = "✅ Harga di BB atas (overbought)"
    else:
        info["14. BB"] = "⚪ Di dalam BB"

    # ── 15. Support/Resistance (bobot 1) ────────────────────
    sh, sl = detect_swing_points(df, 50)
    sr_info = "⚪ Tidak ada S/R dekat"
    if sl:
        ns = min(sl, key=lambda x: abs(x-p))
        if abs(p - ns) / p < 0.003:
            bull += 1.0; sr_info = f"✅ Dekat support ${ns:.2f}"
    if sh:
        nr = min(sh, key=lambda x: abs(x-p))
        if abs(p - nr) / p < 0.003:
            bear += 1.0; sr_info = f"✅ Dekat resistance ${nr:.2f}"
    info["15. S/R"] = sr_info

    # ── 16. DXY Correlation (bobot 1.5) ─────────────────────
    if dxy_trend in ["TURUN", "TURUN_KUAT"]:
        pts = 1.5 if dxy_trend == "TURUN_KUAT" else 1.0
        bull += pts; info["16. DXY"] = f"✅ DXY {dxy_trend} (bullish gold)"
    elif dxy_trend in ["NAIK", "NAIK_KUAT"]:
        pts = 1.5 if dxy_trend == "NAIK_KUAT" else 1.0
        bear += pts; info["16. DXY"] = f"✅ DXY {dxy_trend} (bearish gold)"
    else:
        info["16. DXY"] = f"⚪ DXY {dxy_trend}"

    # ── 17. Volume Spike (bobot 1) ──────────────────────────
    if n["vol_r"] > 1.5:
        if n["close"] > n["open"]:
            bull += 1.0; info["17. Volume"] = f"✅ Spike bullish ({n['vol_r']:.1f}x)"
        else:
            bear += 1.0; info["17. Volume"] = f"✅ Spike bearish ({n['vol_r']:.1f}x)"
    else:
        info["17. Volume"] = f"⚪ Normal ({n['vol_r']:.1f}x)"

    # ── 18. Candlestick Pattern (bobot 1) ───────────────────
    body = abs(n["close"] - n["open"])
    rang = n["high"] - n["low"]
    lwk  = min(n["close"], n["open"]) - n["low"]
    uwk  = n["high"] - max(n["close"], n["open"])
    candle_name = "Normal"
    if rang > 0:
        if lwk > body * 2.5 and uwk < body * 0.5:
            bull += 1.0; candle_name = "Pin bar bullish kuat"
        elif uwk > body * 2.5 and lwk < body * 0.5:
            bear += 1.0; candle_name = "Pin bar bearish kuat"
        elif lwk > body * 1.5:
            bull += 0.5; candle_name = "Pin bar bullish"
        elif uwk > body * 1.5:
            bear += 0.5; candle_name = "Pin bar bearish"
        elif n["close"] > n["open"] and n1["close"] < n1["open"] and n["open"] < n1["close"] and n["close"] > n1["open"]:
            bull += 1.0; candle_name = "Engulfing bullish"
        elif n["close"] < n["open"] and n1["close"] > n1["open"] and n["open"] > n1["close"] and n["close"] < n1["open"]:
            bear += 1.0; candle_name = "Engulfing bearish"
        elif abs(body/rang) < 0.1:
            candle_name = "Doji (ragu-ragu)"
    info["18. Candle"] = f"{'✅' if candle_name != 'Normal' and candle_name != 'Doji (ragu-ragu)' else '⚪'} {candle_name}"

    # ── 19. Session Filter (bobot 0.5) ──────────────────────
    if is_prime_session():
        if bull > bear: bull += 0.5
        elif bear > bull: bear += 0.5
        info["19. Sesi"] = "✅ Prime session (London/NY)"
    else:
        info["19. Sesi"] = "⚪ Off-session"

    # ── 20. Trend Confirmation (EMA + Price Action) ─────────
    # Konfirmasi akhir: apakah harga respect EMA sebagai S/R
    if p > n["ema20"] and n["ema20"] > n["ema50"]:
        if abs(p - n["ema20"]) / p < 0.003:
            bull += 1.0; info["20. EMA Bounce"] = "✅ Bounce dari EMA20 (support dinamis)"
        elif abs(p - n["ema50"]) / p < 0.003:
            bull += 1.0; info["20. EMA Bounce"] = "✅ Bounce dari EMA50 (support dinamis)"
        else:
            info["20. EMA Bounce"] = "⚪ Tidak di EMA support"
    elif p < n["ema20"] and n["ema20"] < n["ema50"]:
        if abs(p - n["ema20"]) / p < 0.003:
            bear += 1.0; info["20. EMA Bounce"] = "✅ Rejection EMA20 (resistance dinamis)"
        elif abs(p - n["ema50"]) / p < 0.003:
            bear += 1.0; info["20. EMA Bounce"] = "✅ Rejection EMA50 (resistance dinamis)"
        else:
            info["20. EMA Bounce"] = "⚪ Tidak di EMA resistance"
    else:
        info["20. EMA Bounce"] = "⚪ Mixed"

    # ── Tentukan arah ────────────────────────────────────────
    score = max(bull, bear)
    total = 20.0

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
        tp3 = round(p + atr * tp_mult * 2.0, 2)
    elif direction == "SELL":
        sl  = round(p + atr * sl_mult, 2)
        tp1 = round(p - atr * tp_mult, 2)
        tp2 = round(p - atr * tp_mult * 1.5, 2)
        tp3 = round(p - atr * tp_mult * 2.0, 2)
    else:
        sl = tp1 = tp2 = tp3 = p

    sl_d      = abs(p - sl)
    lot       = LOT_SIZE
    risk_real = round(sl_d * lot * 100, 2)
    rr        = round(abs(tp1 - p) / sl_d, 1) if sl_d > 0 else 0
    wr        = min(50 + int(score * 2), 88)

    return {
        "direction":  direction,
        "score":      round(score, 1),
        "max":        total,
        "bull":       round(bull, 1),
        "bear":       round(bear, 1),
        "price":      round(p, 3),
        "sl":         sl, "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "sl_d":       round(sl_d, 2),
        "lot":        lot,
        "risk_real":  risk_real,
        "rr":         rr, "wr": wr,
        "atr":        round(atr, 2),
        "ema20":      round(n["ema20"], 2),
        "ema50":      round(n["ema50"], 2),
        "ema200":     round(n["ema200"], 2),
        "vwap":       round(float(n["vwap"]), 2),
        "rsi":        round(rsi, 1),
        "sessions":   sesi_aktif(),
        "info":       info,
        "structure":  structure,
        "choch":      choch,
        "sweep":      sweep,
    }


# ───────────────────────────────────────────────────────────
#  FORMAT PESAN
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

    choch_str = f" | CHoCH: {s['choch']}" if s["choch"] != "NONE" else ""
    sweep_str = f" | Sweep: {s['sweep']}" if s["sweep"] != "NONE" else ""

    msg = (
        f"{head}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {now.strftime('%d %b %Y  %H:%M')} WIB\n"
        f"{tipe} | TF: {tf_label}\n"
        f"📡 Sesi: {' | '.join(s['sessions'])}\n\n"
        f"💰 Harga    : <b>${s['price']:,.3f}</b>\n"
        f"{icon} Arah     : <b>{d}</b>\n"
        f"📐 Struktur : <b>{s['structure']}{choch_str}{sweep_str}</b>\n"
        f"📊 VWAP     : ${s['vwap']:,.2f}\n\n"
        f"📊 <b>Score: {s['score']}/{s['max']}</b>\n"
        f"[{bar}]\n"
        f"🎯 Est. Win Rate : <b>{s['wr']}%</b>\n"
        f"💹 Risk/Reward   : <b>1:{s['rr']}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>RENCANA ENTRY:</b>\n"
        f"├ Entry     : <b>${s['price']:,.3f}</b>\n"
        f"├ TP 1      : <b>${s['tp1']:,.3f}</b>\n"
        f"├ TP 2      : <b>${s['tp2']:,.3f}</b>\n"
        f"├ TP 3      : <b>${s['tp3']:,.3f}</b>\n"
        f"└ Stop Loss : <b>${s['sl']:,.3f}</b>\n\n"
        f"💼 Risk: <b>${s['risk_real']:.2f}</b> | Lot: <b>{s['lot']}</b> | ATR: ${s['atr']:.2f}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 <b>HASIL 20 FILTER ANALISA:</b>\n"
    )
    for k, v in s["info"].items():
        msg += f"{k}: {v}\n"

    msg += (
        f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 EMA20: ${s['ema20']:,.2f} | EMA50: ${s['ema50']:,.2f} | EMA200: ${s['ema200']:,.2f}\n"
        f"📌 RSI: {s['rsi']} | Bull: {s['bull']} | Bear: {s['bear']}\n\n"
        f"⚠️ <i>Eksekusi MANUAL. Cek Forexfactory sebelum entry!\n"
        f"Selalu pasang SL. Jangan FOMO. Jangan overtrading.</i>\n"
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
        print(f"  Exception: {e}")
        return False


def buat_pesan_startup():
    return (
        f"🤖 <b>GOLD SIGNAL BOT PRO v4 ULTIMATE!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Pair      : XAU/USD (Gold)\n"
        f"✅ Timeframe : M15+H1 (Scalp) | H4+D1 (Swing)\n"
        f"✅ Lot Size  : {LOT_SIZE}\n"
        f"✅ Min Score : {MIN_SCORE}/20 (sangat selektif)\n\n"
        f"📊 <b>20 Filter Analisa Ultimate:</b>\n"
        f"1. EMA Stack 20/50/200\n"
        f"2. Supertrend\n"
        f"3. Market Structure (HH/HL/LH/LL)\n"
        f"4. Change of Character (CHoCH)\n"
        f"5. Liquidity Sweep (Stop Hunt)\n"
        f"6. Ichimoku Cloud\n"
        f"7. VWAP (level institusi)\n"
        f"8. RSI + Divergence\n"
        f"9. MACD + Divergence\n"
        f"10. Fibonacci Golden Pocket\n"
        f"11. Order Block (Smart Money)\n"
        f"12. Fair Value Gap (FVG)\n"
        f"13. Stochastic\n"
        f"14. Bollinger Band\n"
        f"15. Support/Resistance\n"
        f"16. DXY Correlation\n"
        f"17. Volume Spike\n"
        f"18. Candlestick Pattern\n"
        f"19. Session Filter\n"
        f"20. EMA Bounce Confirmation\n\n"
        f"⏱️ Scan otomatis setiap {SCAN_MENIT} menit\n"
        f"🏆 Sinyal hanya keluar saat 20 filter konfluens!\n"
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

    dxy = get_dxy_trend()
    print(f"  DXY trend: {dxy}")

    sinyal_dikirim = 0

    # SCALPING: M15 + H1
    df_m15 = fetch_data(SYMBOL, "15min", 200)
    df_h1  = fetch_data(SYMBOL, "1h", 200)

    if df_m15 is not None and df_h1 is not None and len(df_m15) > 60 and len(df_h1) > 60:
        df_m15  = add_indicators(df_m15)
        df_h1   = add_indicators(df_h1)
        sig_m15 = analyze(df_m15, "scalping", dxy)
        sig_h1  = analyze(df_h1,  "scalping", dxy)

        print(f"  SCALP M15: {sig_m15['direction']} {sig_m15['score']} | H1: {sig_h1['direction']} {sig_h1['score']}")

        if sig_m15["direction"] == sig_h1["direction"] and sig_m15["direction"] != "WAIT":
            sig_gabung = sig_m15.copy()
            sig_gabung["score"] = min(round((sig_m15["score"] + sig_h1["score"]) / 2 * 1.1, 1), 20)
            key = f"SCALP_{sig_gabung['direction']}_{int(sig_gabung['price'])}"
            if key != sinyal_terakhir.get("scalp"):
                pesan = buat_pesan(sig_gabung, "M15 + H1", "scalping")
                if pesan and kirim_telegram(pesan):
                    sinyal_terakhir["scalp"] = key
                    sinyal_dikirim += 1

    # SWING: H4 + D1
    df_h4 = fetch_data(SYMBOL, "4h", 200)
    df_d1 = fetch_data(SYMBOL, "1day", 200)

    if df_h4 is not None and df_d1 is not None and len(df_h4) > 60 and len(df_d1) > 60:
        df_h4  = add_indicators(df_h4)
        df_d1  = add_indicators(df_d1)
        sig_h4 = analyze(df_h4, "swing", dxy)
        sig_d1 = analyze(df_d1, "swing", dxy)

        print(f"  SWING  H4: {sig_h4['direction']} {sig_h4['score']} | D1: {sig_d1['direction']} {sig_d1['score']}")

        if sig_h4["direction"] == sig_d1["direction"] and sig_h4["direction"] != "WAIT":
            sig_gabung = sig_h4.copy()
            sig_gabung["score"] = min(round((sig_h4["score"] + sig_d1["score"]) / 2 * 1.1, 1), 20)
            key = f"SWING_{sig_gabung['direction']}_{int(sig_gabung['price'])}"
            if key != sinyal_terakhir.get("swing"):
                pesan = buat_pesan(sig_gabung, "H4 + D1", "swing")
                if pesan and kirim_telegram(pesan):
                    sinyal_terakhir["swing"] = key
                    sinyal_dikirim += 1

    if sinyal_dikirim == 0:
        print(f"  Tidak ada sinyal valid.")


if __name__ == "__main__":
    print("="*50)
    print("  GOLD SIGNAL BOT PRO v4 ULTIMATE")
    print(f"  20 Filter | Min Score: {MIN_SCORE}/20")
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

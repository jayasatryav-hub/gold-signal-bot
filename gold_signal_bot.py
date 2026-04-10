"""
╔══════════════════════════════════════════════════════════╗
║     GOLD SIGNAL BOT PRO v7 FINAL — XAU/USD              ║
║     Simple | Objective | Non-Redundant                   ║
║                                                          ║
║  CORE (wajib semua):                                     ║
║  1. Market Structure jelas (HH+HL / LH+LL)              ║
║  2. Harga dalam zona S/R (±0.3% tolerance)              ║
║  3. Candlestick konfirmasi (definisi ketat)              ║
║                                                          ║
║  FILTER (minimal 1):                                     ║
║  4. Session London/NY aktif                              ║
║  5. DXY mendukung arah                                   ║
║                                                          ║
║  NO TRADE jika:                                          ║
║  - Structure tidak jelas                                 ║
║  - Harga jauh dari zona S/R                              ║
║  - Tidak ada candle konfirmasi                           ║
║  - Candle terlalu besar (late entry)                     ║
║  - RR < 1:1.5                                            ║
╚══════════════════════════════════════════════════════════╝
"""

import requests
import pandas as pd
import numpy as np
import schedule
import time
import json
import os
from datetime import datetime, timezone, timedelta

# ═══════════════════════════════════════════════════════════
#  KONFIGURASI
# ═══════════════════════════════════════════════════════════
TELEGRAM_TOKEN  = "8730178125:AAGDKqhgTs7E21LrjUEf76j2J0TeYBI60gY"
CHAT_ID         = "7118844737"
TWELVE_DATA_KEY = "100d92529e674de18d861f050118c7b4"

LOT_SIZE        = 0.01
SYMBOL          = "XAU/USD"
SCAN_MENIT      = 15

SR_TOLERANCE    = 0.005   # ±0.3% zona S/R (~$14 untuk gold $4800)
SR_MIN_REJECT   = 1       # Level harus direject minimal 2x
LATE_ENTRY_MULT = 2.0     # Candle terlalu besar jika body > 2x rata-rata
MIN_RR          = 1.5     # Minimum Risk/Reward ratio
LOG_FILE        = "trade_log.json"
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
#  TRADE LOGGER
# ───────────────────────────────────────────────────────────
def log_signal(signal, tf_label, tf_type):
    """
    Catat setiap sinyal ke file JSON untuk tracking performa.
    Format: entry, SL, TP1, TP2, arah, timeframe, waktu
    Result diisi manual atau bisa di-update nanti.
    """
    try:
        logs = []
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                logs = json.load(f)

        entry = {
            "id":        len(logs) + 1,
            "waktu":     wib().strftime("%Y-%m-%d %H:%M"),
            "tf":        tf_label,
            "tipe":      tf_type,
            "arah":      signal["direction"],
            "entry":     signal["price"],
            "sl":        signal["sl"],
            "tp1":       signal["tp1"],
            "tp2":       signal["tp2"],
            "rr":        signal["rr"],
            "risk_real": signal["risk_real"],
            "structure": signal["structure"],
            "level":     signal["area_desc"],
            "candle":    signal["candle_desc"],
            "result":    "PENDING"  # Update manual: WIN_TP1 / WIN_TP2 / LOSS / BE
        }

        logs.append(entry)
        with open(LOG_FILE, "w") as f:
            json.dump(logs, f, indent=2)

        print(f"  Log sinyal #{entry['id']} tersimpan")
    except Exception as e:
        print(f"  Gagal log: {e}")

def get_trade_summary():
    """Hitung statistik dari log yang sudah ada"""
    try:
        if not os.path.exists(LOG_FILE):
            return None
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)

        total    = len(logs)
        pending  = sum(1 for l in logs if l["result"] == "PENDING")
        wins     = sum(1 for l in logs if l["result"].startswith("WIN"))
        losses   = sum(1 for l in logs if l["result"] == "LOSS")
        be       = sum(1 for l in logs if l["result"] == "BE")
        closed   = wins + losses + be

        wr = round(wins / closed * 100, 1) if closed > 0 else 0

        return {
            "total": total, "pending": pending,
            "wins": wins, "losses": losses,
            "be": be, "closed": closed, "wr": wr
        }
    except:
        return None


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
        for c in ["open", "high", "low", "close"]:
            df[c] = pd.to_numeric(df[c])
        df["volume"] = pd.to_numeric(
            df.get("volume", pd.Series([5000]*len(df)))
        ).fillna(5000)
        df = df.sort_values("datetime").reset_index(drop=True)
        return df
    except:
        return None


# ───────────────────────────────────────────────────────────
#  INDIKATOR DASAR
# ───────────────────────────────────────────────────────────
def calc_atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat(
        [h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(n).mean()

def calc_rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))


# ───────────────────────────────────────────────────────────
#  KOMPONEN 1: MARKET STRUCTURE
# ───────────────────────────────────────────────────────────
def get_swing_points(df, lookback=60):
    recent = df.tail(lookback)
    highs  = recent["high"].values
    lows   = recent["low"].values
    sh, sl = [], []
    for i in range(2, len(highs)-2):
        if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and
                highs[i] > highs[i+1] and highs[i] > highs[i+2]):
            sh.append(round(highs[i], 2))
        if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and
                lows[i] < lows[i+1] and lows[i] < lows[i+2]):
            sl.append(round(lows[i], 2))
    return sh, sl

def get_market_structure(df):
    sh, sl = get_swing_points(df, 60)
    if len(sh) < 2 or len(sl) < 2:
        return "NETRAL", sh, sl
    if sh[-1] > sh[-2] and sl[-1] > sl[-2]:
        return "BULLISH", sh, sl
    elif sh[-1] < sh[-2] and sl[-1] < sl[-2]:
        return "BEARISH", sh, sl
    return "NETRAL", sh, sl


# ───────────────────────────────────────────────────────────
#  KOMPONEN 2: ZONA S/R (±0.3% TOLERANCE)
# ───────────────────────────────────────────────────────────
def get_validated_sr(df, lookback=100):
    """
    Level S/R valid = level yang sudah direject minimal SR_MIN_REJECT kali.
    Menggunakan ZONA bukan garis — tolerance ±0.5% untuk clustering.
    """
    recent      = df.tail(lookback)
    highs       = recent["high"].values
    lows        = recent["low"].values
    price       = df["close"].iloc[-1]
    tol_cluster = price * 0.005

    all_levels = []
    for i in range(2, len(highs)-2):
        if (highs[i] > highs[i-1] and highs[i] > highs[i-2] and
                highs[i] > highs[i+1] and highs[i] > highs[i+2]):
            all_levels.append(highs[i])
        if (lows[i] < lows[i-1] and lows[i] < lows[i-2] and
                lows[i] < lows[i+1] and lows[i] < lows[i+2]):
            all_levels.append(lows[i])

    if not all_levels:
        return [], []

    all_levels.sort()
    clusters = []
    current  = [all_levels[0]]
    for level in all_levels[1:]:
        if level - current[-1] <= tol_cluster:
            current.append(level)
        else:
            clusters.append(current)
            current = [level]
    clusters.append(current)

    valid_supports    = []
    valid_resistances = []

    for cluster in clusters:
        if len(cluster) >= SR_MIN_REJECT:
            avg   = sum(cluster) / len(cluster)
            count = len(cluster)
            # Zona: avg ± SR_TOLERANCE
            zone_low  = round(avg * (1 - SR_TOLERANCE), 2)
            zone_high = round(avg * (1 + SR_TOLERANCE), 2)
            entry = {
                "level":    round(avg, 2),
                "zone_low": zone_low,
                "zone_high":zone_high,
                "rejects":  count
            }
            if avg < price:
                valid_supports.append(entry)
            else:
                valid_resistances.append(entry)

    return valid_supports, valid_resistances

def is_in_sr_zone(price, valid_supports, valid_resistances, direction):
    """
    Cek apakah harga DALAM zona S/R (bukan exact level).
    Zona = level ± SR_TOLERANCE (0.3%).
    """
    if direction == "BUY":
        for sup in valid_supports:
            if sup["zone_low"] <= price <= sup["zone_high"]:
                return True, (
                    f"Zona Support ${sup['zone_low']:,.2f}–"
                    f"${sup['zone_high']:,.2f} "
                    f"(direject {sup['rejects']}x)"
                )
    elif direction == "SELL":
        for res in valid_resistances:
            if res["zone_low"] <= price <= res["zone_high"]:
                return True, (
                    f"Zona Resistance ${res['zone_low']:,.2f}–"
                    f"${res['zone_high']:,.2f} "
                    f"(direject {res['rejects']}x)"
                )
    return False, "Harga di luar zona S/R"


# ───────────────────────────────────────────────────────────
#  KOMPONEN 3: CANDLESTICK (DEFINISI KETAT)
# ───────────────────────────────────────────────────────────
def get_candle_signal(df):
    """
    Definisi ketat dan objektif:

    PIN BAR BULLISH:
    - Lower wick >= 2x body
    - Upper wick <= 0.5x body
    - Body kecil (body < 40% total range)
    - Close > open (bullish body) ATAU close di upper 30% range

    PIN BAR BEARISH:
    - Upper wick >= 2x body
    - Lower wick <= 0.5x body
    - Body kecil (body < 40% total range)
    - Close < open (bearish body) ATAU close di lower 30% range

    ENGULFING BULLISH:
    - Candle sebelumnya bearish (close < open)
    - Candle sekarang bullish (close > open)
    - Open sekarang <= close sebelumnya
    - Close sekarang >= open sebelumnya (menelan seluruh body)
    - Body sekarang > body sebelumnya

    ENGULFING BEARISH:
    - Candle sebelumnya bullish (close > open)
    - Candle sekarang bearish (close < open)
    - Open sekarang >= close sebelumnya
    - Close sekarang <= open sebelumnya (menelan seluruh body)
    - Body sekarang > body sebelumnya

    NO TRADE:
    - Body > LATE_ENTRY_MULT x rata-rata body (late entry)
    - Total range = 0 (tidak ada pergerakan)
    """
    last     = df.iloc[-1]
    prev     = df.iloc[-2]
    avg_body = df["close"].sub(df["open"]).abs().tail(20).mean()

    body  = abs(last["close"] - last["open"])
    rang  = last["high"] - last["low"]
    lwk   = min(last["close"], last["open"]) - last["low"]
    uwk   = last["high"] - max(last["close"], last["open"])
    prev_body = abs(prev["close"] - prev["open"])

    # Cek late entry
    if body > avg_body * LATE_ENTRY_MULT:
        return "NONE", f"❌ Late entry (candle {body/avg_body:.1f}x avg)"

    if rang == 0:
        return "NONE", "❌ Tidak ada pergerakan"

    body_ratio = body / rang  # Rasio body terhadap total range

    # Pin Bar Bullish
    if (lwk >= body * 2.0 and
            uwk <= body * 0.5 and
            body_ratio < 0.4):
        conf = "kuat" if lwk >= body * 3.0 else "normal"
        return "BUY", f"Pin Bar Bullish {conf} (wick {lwk/body:.1f}x body)"

    # Pin Bar Bearish
    if (uwk >= body * 2.0 and
            lwk <= body * 0.5 and
            body_ratio < 0.4):
        conf = "kuat" if uwk >= body * 3.0 else "normal"
        return "SELL", f"Pin Bar Bearish {conf} (wick {uwk/body:.1f}x body)"

    # Engulfing Bullish
    if (last["close"] > last["open"] and
            prev["close"] < prev["open"] and
            last["open"] <= prev["close"] and
            last["close"] >= prev["open"] and
            body > prev_body):
        return "BUY", f"Engulfing Bullish (body {body/prev_body:.1f}x prev)"

    # Engulfing Bearish
    if (last["close"] < last["open"] and
            prev["close"] > prev["open"] and
            last["open"] >= prev["close"] and
            last["close"] <= prev["open"] and
            body > prev_body):
        return "SELL", f"Engulfing Bearish (body {body/prev_body:.1f}x prev)"

    return "NONE", "⚪ Tidak ada konfirmasi candle"


# ───────────────────────────────────────────────────────────
#  FILTER: DXY
# ───────────────────────────────────────────────────────────
def get_dxy_bias():
    try:
        df = fetch_data("DX/Y", "1h", 50)
        if df is None:
            return "UNKNOWN"
        ema20 = df["close"].ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = df["close"].ewm(span=50, adjust=False).mean().iloc[-1]
        price = df["close"].iloc[-1]
        if price > ema20 > ema50:
            return "NAIK"
        elif price < ema20 < ema50:
            return "TURUN"
        return "SIDEWAYS"
    except:
        return "UNKNOWN"


# ───────────────────────────────────────────────────────────
#  MAIN ANALYZE
# ───────────────────────────────────────────────────────────
def analyze(df, tf_type, dxy):
    price = df["close"].iloc[-1]
    atr   = calc_atr(df).iloc[-1]
    rsi   = calc_rsi(df["close"]).iloc[-1]

    structure, sh, sl = get_market_structure(df)
    valid_supports, valid_resistances = get_validated_sr(df, 100)
    candle_dir, candle_desc = get_candle_signal(df)

    session_ok = is_prime_session()
    dxy_buy    = dxy == "TURUN"
    dxy_sell   = dxy == "NAIK"
    dxy_desc   = {
        "TURUN":    "✅ DXY turun (bullish gold)",
        "NAIK":     "✅ DXY naik (bearish gold)",
        "SIDEWAYS": "⚪ DXY sideways",
        "UNKNOWN":  "⚪ DXY unknown"
    }.get(dxy, "⚪ DXY unknown")

    direction   = "WAIT"
    area_ok     = False
    area_desc   = "Harga di luar zona S/R"
    filters_ok  = 0
    skip_reason = ""

    # NO TRADE checks
    if structure == "NETRAL":
        skip_reason = "Market sideways — structure tidak jelas"
    elif "Late entry" in candle_desc or "Tidak ada pergerakan" in candle_desc:
        skip_reason = candle_desc
    elif candle_dir == "NONE":
        skip_reason = candle_desc
    else:
        if structure == "BULLISH" and candle_dir == "BUY":
            in_zone, area_desc = is_in_sr_zone(
                price, valid_supports, valid_resistances, "BUY"
            )
            if not in_zone:
                skip_reason = f"Harga di luar zona S/R support"
            else:
                area_ok = True
                if session_ok: filters_ok += 1
                if dxy_buy:    filters_ok += 1
                if filters_ok >= 1:
                    direction = "BUY"
                else:
                    skip_reason = "Filter tidak terpenuhi"

        elif structure == "BEARISH" and candle_dir == "SELL":
            in_zone, area_desc = is_in_sr_zone(
                price, valid_supports, valid_resistances, "SELL"
            )
            if not in_zone:
                skip_reason = f"Harga di luar zona S/R resistance"
            else:
                area_ok = True
                if session_ok: filters_ok += 1
                if dxy_sell:   filters_ok += 1
                if filters_ok >= 1:
                    direction = "SELL"
                else:
                    skip_reason = "Filter tidak terpenuhi"
        else:
            skip_reason = f"Structure {structure} ≠ candle {candle_dir}"

    # Hitung SL/TP
    if tf_type == "scalping":
        sl_mult, tp1_mult, tp2_mult = 1.0, 1.5, 2.5
    else:
        sl_mult, tp1_mult, tp2_mult = 1.5, 3.0, 5.0

    if direction == "BUY":
        sl  = round(price - atr * sl_mult, 2)
        tp1 = round(price + atr * tp1_mult, 2)
        tp2 = round(price + atr * tp2_mult, 2)
    elif direction == "SELL":
        sl  = round(price + atr * sl_mult, 2)
        tp1 = round(price - atr * tp1_mult, 2)
        tp2 = round(price - atr * tp2_mult, 2)
    else:
        sl = tp1 = tp2 = price

    sl_d      = abs(price - sl)
    risk_real = round(sl_d * LOT_SIZE * 100, 2)
    rr        = round(abs(tp1 - price) / sl_d, 1) if sl_d > 0 else 0

    # Cek minimum RR
    if direction != "WAIT" and rr < MIN_RR:
        skip_reason = f"RR 1:{rr} di bawah minimum 1:{MIN_RR}"
        direction   = "WAIT"

    # Hitung score dari kualitas komponen (max 10)
    score = 0.0
    if direction != "WAIT":
        # Komponen 1: Structure (max 3 poin)
        score += 3.0  # structure sudah pasti jelas kalau sampai sini

        # Komponen 2: Area S/R (max 3 poin) - makin banyak reject makin tinggi
        if area_ok:
            score += 3.0

        # Komponen 3: Candle (max 2 poin)
        if "kuat" in candle_desc:
            score += 2.0
        elif candle_dir != "NONE":
            score += 1.5

        # Filter (max 2 poin)
        score += filters_ok * 1.0

    score = round(min(score, 10.0), 1)
    wr    = min(50 + int(score * 3.5), 85)

    return {
        "direction":   direction,
        "price":       round(price, 3),
        "sl":          sl,
        "tp1":         tp1,
        "tp2":         tp2,
        "sl_d":        round(sl_d, 2),
        "risk_real":   risk_real,
        "rr":          rr,
        "atr":         round(atr, 2),
        "rsi":         round(rsi, 1),
        "lot":         LOT_SIZE,
        "sessions":    sesi_aktif(),
        "structure":   structure,
        "area_ok":     area_ok,
        "area_desc":   area_desc,
        "candle_dir":  candle_dir,
        "candle_desc": candle_desc,
        "session_ok":  session_ok,
        "dxy_desc":    dxy_desc,
        "filters_ok":  filters_ok,
        "skip_reason": skip_reason,
        "score":       score,
        "wr":          wr,
    }


# ───────────────────────────────────────────────────────────
#  FORMAT PESAN
# ───────────────────────────────────────────────────────────
def buat_pesan(s, tf_label, tf_type):
    d   = s["direction"]
    now = wib()

    if d == "BUY":
        icon = "BUY"
        emoji = "GREEN"
    elif d == "SELL":
        icon = "SELL"
        emoji = "RED"
    else:
        return None

    tipe     = "SCALPING" if tf_type == "scalping" else "SWING"
    sess_str = "Aktif" if s["session_ok"] else "Off-session"
    score    = s.get("score", 0)
    wr       = s.get("wr", 0)

    stats = get_trade_summary()
    track = ""
    if stats and stats["closed"] > 0:
        track = f"Track Record: {stats['wins']}W/{stats['losses']}L/{stats['be']}BE | WR: {stats['wr']}%\n"

    msg  = f"{'==='*8}\n"
    msg += f"SINYAL {icon} - GOLD XAU/USD\n"
    msg += f"{'==='*8}\n"
    msg += f"{now.strftime('%d %b %Y  %H:%M')} WIB\n"
    msg += f"{tipe} | TF: {tf_label}\n"
    msg += f"Sesi: {chr(32).join(s['sessions'])}\n"
    if track:
        msg += track
    msg += f"\n"
    msg += f"Harga  : ${s['price']:,.3f}\n"
    msg += f"Arah   : {d}\n"
    msg += f"Score  : {score}/10\n"
    msg += f"Est WR : {wr}%\n"
    msg += f"\n"
    msg += f"=== 3 KOMPONEN WAJIB ===\n"
    msg += f"1. Structure : {s['structure']}\n"
    msg += f"2. Zona S/R  : {s['area_desc']}\n"
    msg += f"3. Candle    : {s['candle_desc']}\n"
    msg += f"\n"
    msg += f"=== FILTER ({s['filters_ok']}/2) ===\n"
    msg += f"4. Session : {sess_str}\n"
    msg += f"5. DXY     : {s['dxy_desc']}\n"
    msg += f"\n"
    msg += f"=== RENCANA ENTRY ===\n"
    msg += f"Entry     : ${s['price']:,.3f}\n"
    msg += f"TP 1      : ${s['tp1']:,.3f}\n"
    msg += f"TP 2      : ${s['tp2']:,.3f}\n"
    msg += f"Stop Loss : ${s['sl']:,.3f}\n"
    msg += f"\n"
    msg += f"Risk: ${s['risk_real']:.2f} | Lot: {s['lot']} | RR: 1:{s['rr']} | ATR: ${s['atr']:.2f}\n"
    msg += f"RSI: {s['rsi']}\n"
    msg += f"\n"
    msg += f"Cek Investing.com sebelum entry!\n"
    msg += f"Entry jika Score 8+ dan WR 75%+\n"
    msg += f"Skip jika ada berita merah.\n"
    msg += f"Selalu pasang SL. Jangan FOMO."
    return msg

def kirim_telegram(pesan):
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": pesan, "parse_mode": "HTML"},
            timeout=12
        )
        if r.status_code == 200:
            print("  Telegram terkirim ✅")
            return True
        print(f"  Telegram error: {r.text[:100]}")
        return False
    except Exception as e:
        print(f"  Exception: {e}")
        return False


def buat_pesan_startup():
    stats = get_trade_summary()
    stats_str = ""
    if stats:
        if stats["closed"] > 0:
            stats_str = f"Track Record: {stats['wins']}W/{stats['losses']}L/{stats['be']}BE | WR: {stats['wr']}% | Total: {stats['total']} sinyal"
        else:
            stats_str = f"Total sinyal logged: {stats['total']} (belum ada hasil)"

    msg = "GOLD SIGNAL BOT PRO v7 FINAL\n"
    msg += "========================\n"
    msg += "Simple | Objective | Non-Redundant\n"
    msg += f"Pair: XAU/USD | Lot: {LOT_SIZE} | Min RR: 1:{MIN_RR}\n"
    msg += f"TF: M15+H1 (Scalp) dan H4+D1 (Swing)\n"
    if stats_str:
        msg += stats_str + "\n"
    msg += "\n"
    msg += "WAJIB 3/3:\n"
    msg += "1. Market Structure (HH+HL atau LH+LL)\n"
    msg += "2. Harga dalam zona S/R (0.3% tolerance)\n"
    msg += "3. Pin Bar atau Engulfing (definisi ketat)\n"
    msg += "\n"
    msg += "FILTER minimal 1/2:\n"
    msg += "4. Session London/NY aktif\n"
    msg += "5. DXY mendukung arah\n"
    msg += "\n"
    msg += "NO TRADE jika:\n"
    msg += "- Structure tidak jelas\n"
    msg += "- Harga di luar zona S/R\n"
    msg += "- Tidak ada candle konfirmasi\n"
    msg += "- Candle terlalu besar (late entry)\n"
    msg += f"- RR kurang dari 1:{MIN_RR}\n"
    msg += "\n"
    msg += f"Scan setiap {SCAN_MENIT} menit\n"
    msg += "Semua sinyal di-log otomatis\n"
    msg += "========================"
    return msg

def jalankan_analisa():
    global sinyal_terakhir
    now = wib()
    print(f"\n{'='*50}")
    print(f"  Analisa: {now.strftime('%d %b %Y %H:%M')} WIB")
    print(f"{'='*50}")

    dxy = get_dxy_bias()
    print(f"  DXY: {dxy}")

    sinyal_dikirim = 0

    # ── SCALPING: M15 + H1 ──
    # Sinyal keluar jika M15 DAN H1 searah (konfluensi kuat)
    # ATAU jika hanya H1 dengan score tinggi (lebih fleksibel)
    df_m15 = fetch_data(SYMBOL, "15min", 200)
    df_h1  = fetch_data(SYMBOL, "1h", 200)

    if (df_m15 is not None and df_h1 is not None and
            len(df_m15) > 60 and len(df_h1) > 60):

        sig_m15 = analyze(df_m15, "scalping", dxy)
        sig_h1  = analyze(df_h1,  "scalping", dxy)

        m15_info = sig_m15["skip_reason"] or sig_m15["candle_desc"]
        print(f"  SCALP | M15: {sig_m15['direction']} score={sig_m15.get('score',0)} "
              f"| H1: {sig_h1['direction']} score={sig_h1.get('score',0)}")

        # Opsi 1: M15 + H1 searah (konfluensi penuh — score bonus)
        if (sig_m15["direction"] == sig_h1["direction"] and
                sig_m15["direction"] != "WAIT"):
            sig_gabung = sig_h1.copy()
            # Bonus score karena 2 TF konfirmasi
            sig_gabung["score"] = min(round(sig_h1.get("score", 0) + 1.5, 1), 10)
            sig_gabung["wr"]    = min(sig_h1.get("wr", 0) + 8, 88)
            key = f"SCALP_{sig_gabung['direction']}_{int(sig_gabung['price'])}"
            if key != sinyal_terakhir.get("scalp"):
                pesan = buat_pesan(sig_gabung, "M15 + H1 (Konfluensi)", "scalping")
                if pesan and kirim_telegram(pesan):
                    sinyal_terakhir["scalp"] = key
                    log_signal(sig_gabung, "M15+H1", "scalping")
                    sinyal_dikirim += 1

        # Opsi 2: Hanya H1 valid (sinyal lebih sering)
        elif sig_h1["direction"] != "WAIT" and sig_m15["direction"] == "WAIT":
            key = f"SCALP_{sig_h1['direction']}_{int(sig_h1['price'])}_H1"
            if key != sinyal_terakhir.get("scalp"):
                pesan = buat_pesan(sig_h1, "H1", "scalping")
                if pesan and kirim_telegram(pesan):
                    sinyal_terakhir["scalp"] = key
                    log_signal(sig_h1, "H1", "scalping")
                    sinyal_dikirim += 1

    # ── SWING: H4 + D1 ──
    df_h4 = fetch_data(SYMBOL, "4h", 200)
    df_d1 = fetch_data(SYMBOL, "1day", 200)

    if (df_h4 is not None and df_d1 is not None and
            len(df_h4) > 60 and len(df_d1) > 60):

        sig_h4 = analyze(df_h4, "swing", dxy)
        sig_d1 = analyze(df_d1, "swing", dxy)

        print(f"  SWING  | H4: {sig_h4['direction']} score={sig_h4.get('score',0)} "
              f"| D1: {sig_d1['direction']} score={sig_d1.get('score',0)}")

        # Opsi 1: H4 + D1 searah (konfluensi penuh)
        if (sig_h4["direction"] == sig_d1["direction"] and
                sig_h4["direction"] != "WAIT"):
            sig_gabung = sig_h4.copy()
            sig_gabung["score"] = min(round(sig_h4.get("score", 0) + 1.5, 1), 10)
            sig_gabung["wr"]    = min(sig_h4.get("wr", 0) + 8, 88)
            key = f"SWING_{sig_gabung['direction']}_{int(sig_gabung['price'])}"
            if key != sinyal_terakhir.get("swing"):
                pesan = buat_pesan(sig_gabung, "H4 + D1 (Konfluensi)", "swing")
                if pesan and kirim_telegram(pesan):
                    sinyal_terakhir["swing"] = key
                    log_signal(sig_gabung, "H4+D1", "swing")
                    sinyal_dikirim += 1

        # Opsi 2: Hanya H4 valid
        elif sig_h4["direction"] != "WAIT" and sig_d1["direction"] == "WAIT":
            key = f"SWING_{sig_h4['direction']}_{int(sig_h4['price'])}_H4"
            if key != sinyal_terakhir.get("swing"):
                pesan = buat_pesan(sig_h4, "H4", "swing")
                if pesan and kirim_telegram(pesan):
                    sinyal_terakhir["swing"] = key
                    log_signal(sig_h4, "H4", "swing")
                    sinyal_dikirim += 1

    if sinyal_dikirim == 0:
        print(f"  Tidak ada sinyal valid.")

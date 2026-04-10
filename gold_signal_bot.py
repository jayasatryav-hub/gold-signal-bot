import requests
import pandas as pd
import numpy as np
import schedule
import time
import json
import os
from datetime import datetime, timezone, timedelta

TELEGRAM_TOKEN  = "8730178125:AAGDKqhgTs7E21LrjUEf76j2J0TeYBI60gY"
CHAT_ID         = "7118844737"
TWELVE_DATA_KEY = "100d92529e674de18d861f050118c7b4"
LOT_SIZE        = 0.01
SYMBOL          = "XAU/USD"
SCAN_MENIT      = 15
SR_TOLERANCE    = 0.005
SR_MIN_REJECT   = 1
LATE_ENTRY_MULT = 2.0
MIN_RR          = 1.5
LOG_FILE        = "trade_log.json"

def wib():
    return datetime.now(timezone.utc) + timedelta(hours=7)

def utc_h():
    return datetime.now(timezone.utc).hour

def sesi_aktif():
    h = utc_h()
    s = []
    if 7  <= h < 16: s.append("London")
    if 12 <= h < 21: s.append("New York")
    if 23 <= h or h < 7: s.append("Tokyo/Sydney")
    return s or ["Off-session"]

def is_prime_session():
    h = utc_h()
    return (7 <= h < 16) or (12 <= h < 21)

def log_signal(signal, tf_label, tf_type):
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
            "score":     signal.get("score", 0),
            "wr":        signal.get("wr", 0),
            "result":    "PENDING"
        }
        logs.append(entry)
        with open(LOG_FILE, "w") as f:
            json.dump(logs, f, indent=2)
        print("  Log sinyal #{} tersimpan".format(entry["id"]))
    except Exception as e:
        print("  Gagal log: {}".format(e))

def get_trade_summary():
    try:
        if not os.path.exists(LOG_FILE):
            return None
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
        total   = len(logs)
        pending = sum(1 for l in logs if l["result"] == "PENDING")
        wins    = sum(1 for l in logs if l["result"].startswith("WIN"))
        losses  = sum(1 for l in logs if l["result"] == "LOSS")
        be      = sum(1 for l in logs if l["result"] == "BE")
        closed  = wins + losses + be
        wr      = round(wins / closed * 100, 1) if closed > 0 else 0
        return {"total": total, "pending": pending, "wins": wins,
                "losses": losses, "be": be, "closed": closed, "wr": wr}
    except:
        return None

def fetch_data(symbol, interval="1h", bars=200):
    try:
        r = requests.get(
            "https://api.twelvedata.com/time_series",
            params={"symbol": symbol, "interval": interval,
                    "outputsize": bars, "apikey": TWELVE_DATA_KEY, "format": "JSON"},
            timeout=15
        )
        d = r.json()
        if "values" not in d:
            return None
        df = pd.DataFrame(d["values"])
        for c in ["open", "high", "low", "close"]:
            df[c] = pd.to_numeric(df[c])
        df["volume"] = pd.to_numeric(df.get("volume", pd.Series([5000]*len(df)))).fillna(5000)
        df = df.sort_values("datetime").reset_index(drop=True)
        return df
    except:
        return None

def calc_atr(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def calc_rsi(s, n=14):
    d = s.diff()
    g = d.clip(lower=0).rolling(n).mean()
    l = (-d.clip(upper=0)).rolling(n).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))

def get_swing_points(df, lookback=60):
    recent = df.tail(lookback)
    highs  = recent["high"].values
    lows   = recent["low"].values
    sh, sl = [], []
    for i in range(2, len(highs)-2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            sh.append(round(highs[i], 2))
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            sl.append(round(lows[i], 2))
    return sh, sl

def get_market_structure(df):
    sh, sl = get_swing_points(df, 60)
    if len(sh) < 2 or len(sl) < 2:
        return "NETRAL"
    if sh[-1] > sh[-2] and sl[-1] > sl[-2]:
        return "BULLISH"
    elif sh[-1] < sh[-2] and sl[-1] < sl[-2]:
        return "BEARISH"
    return "NETRAL"

def get_validated_sr(df, lookback=100):
    recent      = df.tail(lookback)
    highs       = recent["high"].values
    lows        = recent["low"].values
    price       = df["close"].iloc[-1]
    tol_cluster = price * 0.005
    all_levels  = []
    for i in range(2, len(highs)-2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            all_levels.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
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
            avg       = sum(cluster) / len(cluster)
            count     = len(cluster)
            zone_low  = round(avg * (1 - SR_TOLERANCE), 2)
            zone_high = round(avg * (1 + SR_TOLERANCE), 2)
            entry = {"level": round(avg, 2), "zone_low": zone_low, "zone_high": zone_high, "rejects": count}
            if avg < price:
                valid_supports.append(entry)
            else:
                valid_resistances.append(entry)
    return valid_supports, valid_resistances

def is_in_sr_zone(price, valid_supports, valid_resistances, direction):
    if direction == "BUY":
        for sup in valid_supports:
            if sup["zone_low"] <= price <= sup["zone_high"]:
                return True, "Support ${:,.2f}-${:,.2f} ({}x reject)".format(sup["zone_low"], sup["zone_high"], sup["rejects"])
    elif direction == "SELL":
        for res in valid_resistances:
            if res["zone_low"] <= price <= res["zone_high"]:
                return True, "Resistance ${:,.2f}-${:,.2f} ({}x reject)".format(res["zone_low"], res["zone_high"], res["rejects"])
    return False, "Di luar zona S/R"

def get_candle_signal(df):
    last      = df.iloc[-1]
    prev      = df.iloc[-2]
    avg_body  = df["close"].sub(df["open"]).abs().tail(20).mean()
    body      = abs(last["close"] - last["open"])
    rang      = last["high"] - last["low"]
    lwk       = min(last["close"], last["open"]) - last["low"]
    uwk       = last["high"] - max(last["close"], last["open"])
    prev_body = abs(prev["close"] - prev["open"])
    if body > avg_body * LATE_ENTRY_MULT:
        return "NONE", "Late entry (candle {:.1f}x avg)".format(body/avg_body)
    if rang == 0 or body == 0:
        return "NONE", "Tidak ada pergerakan"
    body_ratio = body / rang
    if lwk >= body * 2.0 and uwk <= body * 0.5 and body_ratio < 0.4:
        conf = "kuat" if lwk >= body * 3.0 else "normal"
        return "BUY", "Pin Bar Bullish {} (wick {:.1f}x)".format(conf, lwk/body)
    if uwk >= body * 2.0 and lwk <= body * 0.5 and body_ratio < 0.4:
        conf = "kuat" if uwk >= body * 3.0 else "normal"
        return "SELL", "Pin Bar Bearish {} (wick {:.1f}x)".format(conf, uwk/body)
    if last["close"] > last["open"] and prev["close"] < prev["open"] and last["open"] <= prev["close"] and last["close"] >= prev["open"] and body > prev_body:
        return "BUY", "Engulfing Bullish ({:.1f}x prev)".format(body/prev_body)
    if last["close"] < last["open"] and prev["close"] > prev["open"] and last["open"] >= prev["close"] and last["close"] <= prev["open"] and body > prev_body:
        return "SELL", "Engulfing Bearish ({:.1f}x prev)".format(body/prev_body)
    return "NONE", "Tidak ada konfirmasi candle"

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

def analyze(df, tf_type, dxy):
    price  = df["close"].iloc[-1]
    atr    = calc_atr(df).iloc[-1]
    rsi    = calc_rsi(df["close"]).iloc[-1]
    structure = get_market_structure(df)
    valid_supports, valid_resistances = get_validated_sr(df, 100)
    candle_dir, candle_desc = get_candle_signal(df)
    session_ok = is_prime_session()
    dxy_buy    = dxy == "TURUN"
    dxy_sell   = dxy == "NAIK"
    dxy_map    = {"TURUN": "DXY turun (bullish gold)", "NAIK": "DXY naik (bearish gold)",
                  "SIDEWAYS": "DXY sideways", "UNKNOWN": "DXY unknown"}
    dxy_desc   = dxy_map.get(dxy, "DXY unknown")

    direction   = "WAIT"
    area_ok     = False
    area_desc   = "Di luar zona S/R"
    filters_ok  = 0
    skip_reason = ""

    if structure == "NETRAL":
        skip_reason = "Market sideways"
    elif "Late entry" in candle_desc or "Tidak ada pergerakan" in candle_desc:
        skip_reason = candle_desc
    elif candle_dir == "NONE":
        skip_reason = candle_desc
    else:
        if structure == "BULLISH" and candle_dir == "BUY":
            in_zone, area_desc = is_in_sr_zone(price, valid_supports, valid_resistances, "BUY")
            if not in_zone:
                skip_reason = "Harga di luar zona support"
            else:
                area_ok = True
                if session_ok: filters_ok += 1
                if dxy_buy:    filters_ok += 1
                if filters_ok >= 1:
                    direction = "BUY"
                else:
                    skip_reason = "Filter tidak terpenuhi"
        elif structure == "BEARISH" and candle_dir == "SELL":
            in_zone, area_desc = is_in_sr_zone(price, valid_supports, valid_resistances, "SELL")
            if not in_zone:
                skip_reason = "Harga di luar zona resistance"
            else:
                area_ok = True
                if session_ok: filters_ok += 1
                if dxy_sell:   filters_ok += 1
                if filters_ok >= 1:
                    direction = "SELL"
                else:
                    skip_reason = "Filter tidak terpenuhi"
        else:
            skip_reason = "Structure tidak sesuai candle"

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

    if direction != "WAIT" and rr < MIN_RR:
        skip_reason = "RR 1:{} di bawah minimum 1:{}".format(rr, MIN_RR)
        direction   = "WAIT"

    score = 0.0
    if direction != "WAIT":
        score += 3.0
        if area_ok:
            score += 3.0
        if "kuat" in candle_desc:
            score += 2.0
        elif candle_dir != "NONE":
            score += 1.5
        score += filters_ok * 1.0
    score = round(min(score, 10.0), 1)
    wr    = min(50 + int(score * 3.5), 85)

    return {
        "direction":   direction,
        "price":       round(price, 3),
        "sl":          sl, "tp1": tp1, "tp2": tp2,
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

def buat_pesan(s, tf_label, tf_type):
    d = s["direction"]
    if d not in ("BUY", "SELL"):
        return None
    now      = wib()
    tipe     = "SCALPING" if tf_type == "scalping" else "SWING"
    sess_str = "Aktif" if s["session_ok"] else "Off-session"
    score    = s.get("score", 0)
    wr       = s.get("wr", 0)
    stats    = get_trade_summary()
    track    = ""
    if stats and stats["closed"] > 0:
        track = "Track: {}W/{}L/{}BE | WR: {}%\n".format(stats["wins"], stats["losses"], stats["be"], stats["wr"])
    msg  = "SINYAL {} - GOLD XAU/USD\n".format(d)
    msg += "========================\n"
    msg += "{} WIB\n".format(now.strftime("%d %b %Y  %H:%M"))
    msg += "{} | TF: {}\n".format(tipe, tf_label)
    msg += "Sesi: {}\n".format(" | ".join(s["sessions"]))
    if track:
        msg += track
    msg += "\n"
    msg += "Harga  : ${:,.3f}\n".format(s["price"])
    msg += "Arah   : {}\n".format(d)
    msg += "Score  : {}/10\n".format(score)
    msg += "Est WR : {}%\n".format(wr)
    msg += "\n"
    msg += "=== 3 KOMPONEN WAJIB ===\n"
    msg += "1. Structure : {}\n".format(s["structure"])
    msg += "2. Zona S/R  : {}\n".format(s["area_desc"])
    msg += "3. Candle    : {}\n".format(s["candle_desc"])
    msg += "\n"
    msg += "=== FILTER ({}/2) ===\n".format(s["filters_ok"])
    msg += "4. Session : {}\n".format(sess_str)
    msg += "5. DXY     : {}\n".format(s["dxy_desc"])
    msg += "\n"
    msg += "=== RENCANA ENTRY ===\n"
    msg += "Entry     : ${:,.3f}\n".format(s["price"])
    msg += "TP 1      : ${:,.3f}\n".format(s["tp1"])
    msg += "TP 2      : ${:,.3f}\n".format(s["tp2"])
    msg += "Stop Loss : ${:,.3f}\n".format(s["sl"])
    msg += "\n"
    msg += "Risk: ${:.2f} | Lot: {} | RR: 1:{} | ATR: ${:.2f}\n".format(s["risk_real"], s["lot"], s["rr"], s["atr"])
    msg += "RSI: {}\n".format(s["rsi"])
    msg += "\n"
    msg += "Entry jika Score 8+ dan WR 75%+\n"
    msg += "Cek Investing.com sebelum entry!\n"
    msg += "Skip jika ada berita merah.\n"
    msg += "Selalu pasang SL. Jangan FOMO."
    return msg

def kirim_telegram(pesan):
    try:
        r = requests.post(
            "https://api.telegram.org/bot{}/sendMessage".format(TELEGRAM_TOKEN),
            json={"chat_id": CHAT_ID, "text": pesan},
            timeout=12
        )
        if r.status_code == 200:
            print("  Telegram terkirim")
            return True
        print("  Telegram error: {}".format(r.text[:100]))
        return False
    except Exception as e:
        print("  Exception: {}".format(e))
        return False

def buat_pesan_startup():
    stats = get_trade_summary()
    track = ""
    if stats and stats["closed"] > 0:
        track = "Track: {}W/{}L/{}BE | WR: {}%\n".format(stats["wins"], stats["losses"], stats["be"], stats["wr"])
    msg  = "GOLD SIGNAL BOT PRO v7\n"
    msg += "========================\n"
    msg += "Simple | Objective | Non-Redundant\n"
    msg += "Pair: XAU/USD | Lot: {} | Min RR: 1:{}\n".format(LOT_SIZE, MIN_RR)
    msg += "TF: M15+H1 (Scalp) dan H4+D1 (Swing)\n"
    if track:
        msg += track
    msg += "\n"
    msg += "WAJIB 3/3:\n"
    msg += "1. Market Structure (HH+HL atau LH+LL)\n"
    msg += "2. Harga dalam zona S/R\n"
    msg += "3. Pin Bar atau Engulfing\n"
    msg += "\n"
    msg += "FILTER minimal 1/2:\n"
    msg += "4. Session London/NY aktif\n"
    msg += "5. DXY mendukung arah\n"
    msg += "\n"
    msg += "Entry jika Score 8+\n"
    msg += "Scan setiap {} menit\n".format(SCAN_MENIT)
    msg += "========================"
    return msg

sinyal_terakhir = {}

def jalankan_analisa():
    global sinyal_terakhir
    now = wib()
    print("\n" + "="*50)
    print("  Analisa: {} WIB".format(now.strftime("%d %b %Y %H:%M")))
    print("="*50)

    dxy = get_dxy_bias()
    print("  DXY: {}".format(dxy))

    sinyal_dikirim = 0

    df_m15 = fetch_data(SYMBOL, "15min", 200)
    df_h1  = fetch_data(SYMBOL, "1h", 200)

    if df_m15 is not None and df_h1 is not None and len(df_m15) > 60 and len(df_h1) > 60:
        sig_m15 = analyze(df_m15, "scalping", dxy)
        sig_h1  = analyze(df_h1,  "scalping", dxy)
        print("  SCALP | M15: {} score={} | H1: {} score={}".format(
            sig_m15["direction"], sig_m15.get("score",0),
            sig_h1["direction"],  sig_h1.get("score",0)))

        if sig_m15["direction"] == sig_h1["direction"] and sig_m15["direction"] != "WAIT":
            sig_gabung = sig_h1.copy()
            sig_gabung["score"] = min(round(sig_h1.get("score", 0) + 1.5, 1), 10)
            sig_gabung["wr"]    = min(sig_h1.get("wr", 0) + 8, 88)
            key = "SCALP_{}_{}".format(sig_gabung["direction"], int(sig_gabung["price"]))
            if key != sinyal_terakhir.get("scalp"):
                pesan = buat_pesan(sig_gabung, "M15+H1 Konfluensi", "scalping")
                if pesan and kirim_telegram(pesan):
                    sinyal_terakhir["scalp"] = key
                    log_signal(sig_gabung, "M15+H1", "scalping")
                    sinyal_dikirim += 1
        elif sig_h1["direction"] != "WAIT":
            key = "SCALP_{}_{}_H1".format(sig_h1["direction"], int(sig_h1["price"]))
            if key != sinyal_terakhir.get("scalp"):
                pesan = buat_pesan(sig_h1, "H1", "scalping")
                if pesan and kirim_telegram(pesan):
                    sinyal_terakhir["scalp"] = key
                    log_signal(sig_h1, "H1", "scalping")
                    sinyal_dikirim += 1

    df_h4 = fetch_data(SYMBOL, "4h", 200)
    df_d1 = fetch_data(SYMBOL, "1day", 200)

    if df_h4 is not None and df_d1 is not None and len(df_h4) > 60 and len(df_d1) > 60:
        sig_h4 = analyze(df_h4, "swing", dxy)
        sig_d1 = analyze(df_d1, "swing", dxy)
        print("  SWING  | H4: {} score={} | D1: {} score={}".format(
            sig_h4["direction"], sig_h4.get("score",0),
            sig_d1["direction"], sig_d1.get("score",0)))

        if sig_h4["direction"] == sig_d1["direction"] and sig_h4["direction"] != "WAIT":
            sig_gabung = sig_h4.copy()
            sig_gabung["score"] = min(round(sig_h4.get("score", 0) + 1.5, 1), 10)
            sig_gabung["wr"]    = min(sig_h4.get("wr", 0) + 8, 88)
            key = "SWING_{}_{}".format(sig_gabung["direction"], int(sig_gabung["price"]))
            if key != sinyal_terakhir.get("swing"):
                pesan = buat_pesan(sig_gabung, "H4+D1 Konfluensi", "swing")
                if pesan and kirim_telegram(pesan):
                    sinyal_terakhir["swing"] = key
                    log_signal(sig_gabung, "H4+D1", "swing")
                    sinyal_dikirim += 1
        elif sig_h4["direction"] != "WAIT":
            key = "SWING_{}_{}_H4".format(sig_h4["direction"], int(sig_h4["price"]))
            if key != sinyal_terakhir.get("swing"):
                pesan = buat_pesan(sig_h4, "H4", "swing")
                if pesan and kirim_telegram(pesan):
                    sinyal_terakhir["swing"] = key
                    log_signal(sig_h4, "H4", "swing")
                    sinyal_dikirim += 1

    if sinyal_dikirim == 0:
        print("  Tidak ada sinyal valid.")

if __name__ == "__main__":
    print("="*50)
    print("  GOLD SIGNAL BOT PRO v7")
    print("  Simple | Objective | Non-Redundant")
    print("="*50)
    kirim_telegram(buat_pesan_startup())
    time.sleep(10)
    jalankan_analisa()
    schedule.every(SCAN_MENIT).minutes.do(jalankan_analisa)
    print("\nBot berjalan! Scan setiap {} menit.".format(SCAN_MENIT))
    while True:
        schedule.run_pending()
        time.sleep(30)

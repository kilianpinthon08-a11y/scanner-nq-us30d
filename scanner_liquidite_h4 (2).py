#!/usr/bin/env python3
import requests
import yfinance as yf
import json
import os
from datetime import datetime, timezone

TELEGRAM_TOKEN   = "8499381222:AAFanxc9zw8Cx5128FV_xyrWIufuL0heVV4"
TELEGRAM_CHAT_ID = "1734502645"

LOOKBACK_H4  = 10
LOOKBACK_M15 = 5
WINDOW_H     = 4
JOURNAL_FILE = "journal.json"

TICKERS = {
    "NQ=F": "🔵 Nasdaq (NQ)",
    "YM=F": "🟡 US30 (Dow Jones)",
}

def is_trading_session():
    now_utc  = datetime.now(timezone.utc)
    time_val = now_utc.hour * 60 + now_utc.minute
    london   = 7 * 60 <= time_val <= 12 * 60
    new_york = 13 * 60 + 30 <= time_val <= 20 * 60
    if london:
        return True, "🇬🇧 Session London"
    if new_york:
        return True, "🇺🇸 Session New York"
    return False, "Session fermée"

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "HTML"
        }, timeout=10)
        if not resp.ok:
            print(f"  [Telegram] Erreur : {resp.text}")
    except Exception as e:
        print(f"  [Telegram] Erreur : {e}")

def load_journal():
    if os.path.exists(JOURNAL_FILE):
        with open(JOURNAL_FILE, "r") as f:
            return json.load(f)
    return {"trades": []}

def save_journal(journal):
    with open(JOURNAL_FILE, "w") as f:
        json.dump(journal, f, indent=2, default=str)

def add_to_journal(ticker, name, session, h4, m15_result, fvg):
    journal = load_journal()
    trade = {
        "id":           len(journal["trades"]) + 1,
        "date":         datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M"),
        "ticker":       ticker,
        "instrument":   name,
        "session":      session,
        "direction":    h4["direction"],
        "h4_time":      str(h4["time"]),
        "h4_price":     h4["price"],
        "h4_high":      h4["h4_high"],
        "h4_low":       h4["h4_low"],
        "m15_time":     str(m15_result["time"]),
        "m15_price":    m15_result["price"],
        "fvg_detected": fvg is not None,
        "fvg_high":     fvg["high"] if fvg else None,
        "fvg_low":      fvg["low"]  if fvg else None,
        "sl":           h4["h4_low"]    if h4["direction"] == "bullish" else h4["h4_high"],
        "tp":           h4["swing_high"] if h4["direction"] == "bullish" else h4["swing_low"],
        "result":       "en cours",
    }
    journal["trades"].append(trade)
    save_journal(journal)
    return trade

def get_data(ticker, interval, period):
    df = yf.download(ticker, period=period, interval=interval,
                     progress=False, auto_adjust=True)
    df.dropna(inplace=True)
    return df

def to_float(val):
    try:
        return float(val.iloc[0])
    except Exception:
        return float(val)

def detect_fvg(df_m15, h4_grab):
    h4_time    = h4_grab["time"]
    window_end = h4_time.timestamp() + WINDOW_H * 3600
    h4_high    = h4_grab["h4_high"]
    h4_low     = h4_grab["h4_low"]
    fvgs = []
    for i in range(2, len(df_m15)):
        ts = df_m15.index[i]
        if not hasattr(ts, 'tzinfo') or ts.tzinfo is None:
            ts = ts.tz_localize('UTC')
        if not (h4_time.timestamp() < ts.timestamp() <= window_end):
            continue
        high_curr  = to_float(df_m15.iloc[i]["High"])
        low_curr   = to_float(df_m15.iloc[i]["Low"])
        high_prev2 = to_float(df_m15.iloc[i-2]["High"])
        low_prev2  = to_float(df_m15.iloc[i-2]["Low"])
        if low_curr > high_prev2 and low_curr >= h4_low and high_prev2 <= h4_high:
            fvgs.append({"direction": "bullish", "high": low_curr, "low": high_prev2, "time": ts})
        elif high_curr < low_prev2 and high_curr <= h4_high and low_prev2 >= h4_low:
            fvgs.append({"direction": "bearish", "high": low_prev2, "low": high_curr, "time": ts})
    return fvgs[-1] if fvgs else None

def detect_grabs_h4(df, lookback):
    grabs = []
    for i in range(lookback + 1, len(df) - 1):
        candle       = df.iloc[i]
        prev_candles = df.iloc[i - lookback : i]
        swing_high   = prev_candles["High"].max()
        swing_low    = prev_candles["Low"].min()
        high_val     = to_float(candle["High"])
        low_val      = to_float(candle["Low"])
        close_val    = to_float(candle["Close"])
        sh_val       = to_float(swing_high)
        sl_val       = to_float(swing_low)
        ts = df.index[i]
        if not hasattr(ts, 'tzinfo') or ts.tzinfo is None:
            ts = ts.tz_localize('UTC')
        if high_val > sh_val and close_val < sh_val:
            grabs.append({"direction": "bearish", "price": close_val,
                          "h4_high": high_val, "h4_low": low_val,
                          "swing_high": sh_val, "swing_low": sl_val, "time": ts})
        elif low_val < sl_val and close_val > sl_val:
            grabs.append({"direction": "bullish", "price": close_val,
                          "h4_high": high_val, "h4_low": low_val,
                          "swing_high": sh_val, "swing_low": sl_val, "time": ts})
    return grabs

def detect_internal_m15_grab(df_m15, h4_grab, lookback_m15):
    h4_time    = h4_grab["time"]
    h4_high    = h4_grab["h4_high"]
    h4_low     = h4_grab["h4_low"]
    window_end = h4_time.timestamp() + WINDOW_H * 3600
    m15_in_window = []
    for i in range(len(df_m15)):
        ts = df_m15.index[i]
        if not hasattr(ts, 'tzinfo') or ts.tzinfo is None:
            ts = ts.tz_localize('UTC')
        if h4_time.timestamp() < ts.timestamp() <= window_end:
            m15_in_window.append((i, ts))
    if len(m15_in_window) < lookback_m15 + 2:
        return None
    for idx, (i, ts) in enumerate(m15_in_window):
        if idx < lookback_m15 + 1:
            continue
        candle    = df_m15.iloc[i]
        high_val  = to_float(candle["High"])
        low_val   = to_float(candle["Low"])
        close_val = to_float(candle["Close"])
        prev_indices  = [m15_in_window[j][0] for j in range(idx - lookback_m15, idx)]
        prev_highs    = [to_float(df_m15.iloc[pi]["High"]) for pi in prev_indices]
        prev_lows     = [to_float(df_m15.iloc[pi]["Low"])  for pi in prev_indices]
        internal_high = min(max(prev_highs), h4_high)
        internal_low  = max(min(prev_lows),  h4_low)
        if high_val > internal_high and close_val < internal_high:
            return {"direction": "bearish", "price": close_val,
                    "internal_high": internal_high, "internal_low": internal_low, "time": ts}
        elif low_val < internal_low and close_val > internal_low:
            return {"direction": "bullish", "price": close_val,
                    "internal_high": internal_high, "internal_low": internal_low, "time": ts}
    return None

def check_ticker(ticker, name, session_name):
    now = datetime.now(timezone.utc)
    df_h4     = get_data(ticker, "4h", "30d")
    grabs_h4  = detect_grabs_h4(df_h4, LOOKBACK_H4)
    recent_h4 = [g for g in grabs_h4
                 if (now - g["time"]).total_seconds() <= 8 * 3600]
    if not recent_h4:
        return f"  {name} : aucun grab H4 récent"
    df_m15 = get_data(ticker, "15m", "5d")
    for h4 in recent_h4:
        m15_result = detect_internal_m15_grab(df_m15, h4, LOOKBACK_M15)
        if not m15_result:
            continue
        fvg    = detect_fvg(df_m15, h4)
        sl     = h4["h4_low"]    if h4["direction"] == "bullish" else h4["h4_high"]
        tp     = h4["swing_high"] if h4["direction"] == "bullish" else h4["swing_low"]
        risk   = abs(m15_result["price"] - sl)
        reward = abs(tp - m15_result["price"])
        rr     = round(reward / risk, 1) if risk > 0 else 0
        add_to_journal(ticker, name, session_name, h4, m15_result, fvg)
        emoji     = "🟢" if h4["direction"] == "bullish" else "🔴"
        label_h4  = "HAUSSIER" if h4["direction"] == "bullish" else "BAISSIER"
        label_m15 = "haussière" if m15_result["direction"] == "bullish" else "baissière"
        ssl_bsl   = f"🔻 SSL sweepé : {h4['swing_low']:.2f}" if h4["direction"] == "bullish" else f"🔺 BSL sweepé : {h4['swing_high']:.2f}"
        fvg_line  = f"📐 FVG M15 : {fvg['low']:.2f} → {fvg['high']:.2f}\n" if fvg else ""
        send_telegram(
            f"{emoji} <b>SETUP H4 + M15 Interne</b>\n"
            f"📊 {name} | {session_name}\n\n"
            f"<b>— Grab H4 {label_h4} —</b>\n"
            f"🕐 {h4['time'].strftime('%d/%m %H:%M')} UTC\n"
            f"💰 Prix H4 : {h4['price']:.2f}\n"
            f"{ssl_bsl}\n"
            f"📦 Range H4 : {h4['h4_low']:.2f} → {h4['h4_high']:.2f}\n\n"
            f"<b>— Liquidité M15 interne ({label_m15}) —</b>\n"
            f"🕐 {m15_result['time'].strftime('%d/%m %H:%M')} UTC\n"
            f"💰 Prix M15 : {m15_result['price']:.2f}\n"
            f"{fvg_line}\n"
            f"<b>— Gestion du trade —</b>\n"
            f"🛑 Stop Loss : {sl:.2f}\n"
            f"🎯 Take Profit : {tp:.2f}\n"
            f"⚖️ Risk/Reward : 1:{rr}\n\n"
            f"⚡ <b>Setup confirmé — Liquidité interne prise !</b>"
        )
        return f"  {name} : ALERTE envoyée ! RR 1:{rr}"
    return f"  {name} : grab H4 détecté, en attente M15 interne"

print(f"[{datetime.now().strftime('%H:%M:%S')}] Scanner démarré...")
in_session, session_name = is_trading_session()
if not in_session:
    print(f"  Hors session — pas de scan.")
    send_telegram(
        f"😴 <b>Scanner H4 + M15</b>\n"
        f"Hors session de trading\n"
        f"Prochain scan dans 15 min."
    )
else:
    print(f"  Session active : {session_name}")
    resultats = []
    for ticker, name in TICKERS.items():
        try:
            res = check_ticker(ticker, name, session_name)
            resultats.append(res)
            print(res)
        except Exception as e:
            msg = f"  {name} : ERREUR — {e}"
            resultats.append(msg)
            print(msg)
    rapport = "\n".join(resultats)
    send_telegram(
        f"🔍 <b>Scanner H4 + M15 — Rapport</b>\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')} UTC\n"
        f"📍 {session_name}\n\n"
        f"{rapport}"
    )
print("Vérification terminée.")

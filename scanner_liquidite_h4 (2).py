#!/usr/bin/env python3
import requests
import yfinance as yf
from datetime import datetime, timezone

TELEGRAM_TOKEN   = "8499381222:AAFanxc9zw8Cx5128FV_xyrWIufuL0heVV4"
TELEGRAM_CHAT_ID = "1734502645"

LOOKBACK_H4  = 10
LOOKBACK_M15 = 5
WINDOW_H     = 4

TICKERS = {
    "NQ=F": "🔵 Nasdaq (NQ)",
    "YM=F": "🟡 US30 (Dow Jones)",
}

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

def detect_grabs_h4(df, lookback):
    grabs = []
    for i in range(lookback + 1, len(df) - 1):
        candle       = df.iloc[i]
        prev_candles = df.iloc[i - lookback : i]
        swing_high = prev_candles["High"].max()
        swing_low  = prev_candles["Low"].min()
        high_val  = to_float(candle["High"])
        low_val   = to_float(candle["Low"])
        close_val = to_float(candle["Close"])
        sh_val    = to_float(swing_high)
        sl_val    = to_float(swing_low)
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
        prev_indices = [m15_in_window[j][0] for j in range(idx - lookback_m15, idx)]
        prev_highs   = [to_float(df_m15.iloc[pi]["High"]) for pi in prev_indices]
        prev_lows    = [to_float(df_m15.iloc[pi]["Low"])  for pi in prev_indices]
        internal_high = min(max(prev_highs), h4_high)
        internal_low  = max(min(prev_lows),  h4_low)
        if high_val > internal_high and close_val < internal_high:
            return {"direction": "bearish", "price": close_val,
                    "internal_high": internal_high, "internal_low": internal_low, "time": ts}
        elif low_val < internal_low and close_val > internal_low:
            return {"direction": "bullish", "price": close_val,
                    "internal_high": internal_high, "internal_low": internal_low, "time": ts}
    return None

def check_ticker(ticker, name):
    now = datetime.now(timezone.utc)
    df_h4    = get_data(ticker, "4h", "30d")
    grabs_h4 = detect_grabs_h4(df_h4, LOOKBACK_H4)
    recent_h4 = [g for g in grabs_h4
                 if (now - g["time"]).total_seconds() <= 8 * 3600]
    if not recent_h4:
        return f"  {name} : aucun grab H4 récent"
    df_m15 = get_data(ticker, "15m", "5d")
    for h4 in recent_h4:
        result = detect_internal_m15_grab(df_m15, h4, LOOKBACK_M15)
        if result:
            emoji     = "🟢" if h4["direction"] == "bullish" else "🔴"
            label_h4  = "HAUSSIER" if h4["direction"] == "bullish" else "BAISSIER"
            label_m15 = "haussière" if result["direction"] == "bullish" else "baissière"
            ssl_bsl   = f"🔻 SSL sweepé : {h4['swing_low']:.2f}" if h4["direction"] == "bullish" else f"🔺 BSL sweepé : {h4['swing_high']:.2f}"
            send_telegram(
                f"{emoji} <b>SETUP H4 + Liquidité M15 Interne</b>\n"
                f"📊 {name}\n\n"
                f"<b>— Grab H4 {label_h4} —</b>\n"
                f"🕐 {h4['time'].strftime('%d/%m %H:%M')} UTC\n"
                f"💰 Prix H4 : {h4['price']:.2f}\n"
                f"{ssl_bsl}\n"
                f"📦 Range H4 : {h4['h4_low']:.2f} → {h4['h4_high']:.2f}\n\n"
                f"<b>— Liquidité M15 interne ({label_m15}) —</b>\n"
                f"🕐 {result['time'].strftime('%d/%m %H:%M')} UTC\n"
                f"💰 Prix M15 : {result['price']:.2f}\n"
                f"📍 Niveau sweepé : {result['internal_high']:.2f} / {result['internal_low']:.2f}\n\n"
                f"⚡ <b>Liquidité interne prise — Setup actif !</b>"
            )
            return f"  {name} : ALERTE envoyée !"
    return f"  {name} : grab H4 détecté, en attente liquidité M15 interne"

print(f"[{datetime.now().strftime('%H:%M:%S')}] Scanner H4 + M15 Interne en cours...")
resultats = []
for ticker, name in TICKERS.items():
    try:
        res = check_ticker(ticker, name)
        resultats.append(res)
        print(res)
    except Exception as e:
        msg = f"  {name} : ERREUR — {e}"
        resultats.append(msg)
        print(msg)
rapport = "\n".join(resultats)
send_telegram(
    f"🔍 <b>Scanner H4 + M15 Interne — Rapport</b>\n"
    f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')} UTC\n\n"
    f"{rapport}"
)
print("Vérification terminée.")

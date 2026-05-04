#!/usr/bin/env python3
import requests
import yfinance as yf
from datetime import datetime, timezone

TELEGRAM_TOKEN   = "8499381222:AAFanxc9zw8Cx5128FV_xyrWIufuL0heVV4"
TELEGRAM_CHAT_ID = "1734502645"

LOOKBACK_H4  = 10
LOOKBACK_M15 = 20
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

def detect_grabs(df, lookback):
    grabs = []
    for i in range(lookback + 1, len(df) - 1):
        candle       = df.iloc[i]
        prev_candles = df.iloc[i - lookback : i]
        swing_high = prev_candles["High"].max()
        swing_low  = prev_candles["Low"].min()
        try:
            high_val  = float(candle["High"].iloc[0])
            low_val   = float(candle["Low"].iloc[0])
            close_val = float(candle["Close"].iloc[0])
            sh_val    = float(swing_high.iloc[0])
            sl_val    = float(swing_low.iloc[0])
        except Exception:
            high_val  = float(candle["High"])
            low_val   = float(candle["Low"])
            close_val = float(candle["Close"])
            sh_val    = float(swing_high)
            sl_val    = float(swing_low)
        ts = df.index[i]
        if not hasattr(ts, 'tzinfo') or ts.tzinfo is None:
            ts = ts.tz_localize('UTC')
        if high_val > sh_val and close_val < sh_val:
            grabs.append({"direction": "bearish", "price": close_val,
                          "swing_high": sh_val, "swing_low": sl_val, "time": ts})
        elif low_val < sl_val and close_val > sl_val:
            grabs.append({"direction": "bullish", "price": close_val,
                          "swing_high": sh_val, "swing_low": sl_val, "time": ts})
    return grabs

def check_confirmation(ticker, name):
    now = datetime.now(timezone.utc)
    df_h4 = get_data(ticker, "4h", "30d")
    grabs_h4 = detect_grabs(df_h4, LOOKBACK_H4)
    recent_h4 = [g for g in grabs_h4
                 if (now - g["time"]).total_seconds() <= 8 * 3600]
    if not recent_h4:
        return f"  {name} : aucun grab H4 récent"
    df_m15 = get_data(ticker, "15m", "5d")
    grabs_m15 = detect_grabs(df_m15, LOOKBACK_M15)
    for h4 in recent_h4:
        h4_time    = h4["time"]
        h4_dir     = h4["direction"]
        window_end = h4_time.timestamp() + WINDOW_H * 3600
        for m15 in grabs_m15:
            m15_time = m15["time"]
            if not hasattr(m15_time, 'tzinfo') or m15_time.tzinfo is None:
                m15_time = m15_time.tz_localize('UTC')
            in_window = h4_time.timestamp() < m15_time.timestamp() <= window_end
            same_dir  = m15["direction"] == h4_dir
            if in_window and same_dir:
                emoji = "🟢" if h4_dir == "bullish" else "🔴"
                label = "HAUSSIÈRE" if h4_dir == "bullish" else "BAISSIÈRE"
                ssl_bsl = f"🔻 SSL sweepé : {h4['swing_low']:.2f}" if h4_dir == "bullish" else f"🔺 BSL sweepé : {h4['swing_high']:.2f}"
                send_telegram(
                    f"{emoji} <b>CONFIRMATION H4 + M15 — {label}</b>\n"
                    f"📊 {name}\n\n"
                    f"<b>— Grab H4 —</b>\n"
                    f"🕐 {h4_time.strftime('%d/%m %H:%M')} UTC\n"
                    f"💰 Prix : {h4['price']:.2f}\n"
                    f"{ssl_bsl}\n\n"
                    f"<b>— Confirmation M15 —</b>\n"
                    f"🕐 {m15_time.strftime('%d/%m %H:%M')} UTC\n"
                    f"💰 Prix : {m15['price']:.2f}\n\n"
                    f"⚡ <b>Setup confirmé — H4 + M15 alignés !</b>"
                )
                return f"  {name} : ALERTE envoyée ! {h4_dir}"
    return f"  {name} : grab H4 détecté mais pas encore de confirmation M15"

print(f"[{datetime.now().strftime('%H:%M:%S')}] Scanner H4 + M15 en cours...")

resultats = []
for ticker, name in TICKERS.items():
    try:
        res = check_confirmation(ticker, name)
        resultats.append(res)
    except Exception as e:
        resultats.append(f"  {name} : ERREUR — {e}")

rapport = "\n".join(resultats)
send_telegram(
    f"🔍 <b>Scanner H4 + M15 — Rapport</b>\n"
    f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')} UTC\n\n"
    f"{rapport}"
)
print("Vérification terminée.")

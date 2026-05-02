#!/usr/bin/env python3
import requests
import yfinance as yf
from datetime import datetime

TELEGRAM_TOKEN   = "8499381222:AAFanxc9zw8Cx5128FV_xyrWIufuL0heVV4"
TELEGRAM_CHAT_ID = "1734502645"
LOOKBACK         = 10

TICKERS = {
    "NQ=F": "🔵 Nasdaq (NQ)",
    "YM=F": "🟡 US30 (Dow Jones)",
}

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }, timeout=10)
        if not resp.ok:
            print(f"  [Telegram] Erreur : {resp.text}")
    except Exception as e:
        print(f"  [Telegram] Erreur : {e}")

def get_h4_data(ticker):
    df = yf.download(ticker, period="60d", interval="4h",
                     progress=False, auto_adjust=True)
    df.dropna(inplace=True)
    return df

def detect_grab(df, lookback=10):
    if len(df) < lookback + 3:
        return None
    idx          = -2
    candle       = df.iloc[idx]
    prev_candles = df.iloc[idx - lookback : idx]
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
    return {
        "bullish":    low_val  < sl_val and close_val > sl_val,
        "bearish":    high_val > sh_val and close_val < sh_val,
        "price":      close_val,
        "swing_high": sh_val,
        "swing_low":  sl_val,
        "time":       df.index[idx],
    }

print(f"[{datetime.now().strftime('%H:%M:%S')}] Vérification H4 en cours...")

resultats = []

for ticker, name in TICKERS.items():
    try:
        df     = get_h4_data(ticker)
        result = detect_grab(df, LOOKBACK)
        if result is None:
            resultats.append(f"  {name} : pas assez de données")
            continue

        if result["bullish"]:
            send_telegram(
                f"🟢 <b>H4 — Prise de liquidité HAUSSIÈRE</b>\n"
                f"📊 {name}\n\n"
                f"💰 Clôture   : <b>{result['price']:.2f}</b>\n"
                f"🔻 SSL sweepé : {result['swing_low']:.2f}\n"
                f"🕐 Bougie    : {result['time']}\n\n"
                f"⚡ Stops vendeurs chassés → setup haussier potentiel"
            )
            resultats.append(f"  {name} : GRAB HAUSSIER @ {result['price']:.2f}")

        elif result["bearish"]:
            send_telegram(
                f"🔴 <b>H4 — Prise de liquidité BAISSIÈRE</b>\n"
                f"📊 {name}\n\n"
                f"💰 Clôture   : <b>{result['price']:.2f}</b>\n"
                f"🔺 BSL sweepé : {result['swing_high']:.2f}\n"
                f"🕐 Bougie    : {result['time']}\n\n"
                f"⚡ Stops acheteurs chassés → setup baissier potentiel"
            )
            resultats.append(f"  {name} : GRAB BAISSIER @ {result['price']:.2f}")

        else:
            resultats.append(f"  {name} : aucun grab")

    except Exception as e:
        resultats.append(f"  {name} : ERREUR — {e}")

rapport = "\n".join(resultats)
send_telegram(
    f"✅ <b>Scanner H4 — Vérification terminée</b>\n"
    f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
    f"{rapport}"
)
print("Vérification terminée.")

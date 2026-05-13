#!/usr/bin/env python3
import requests
import yfinance as yf
from datetime import datetime, timezone

TELEGRAM_TOKEN   = "8499381222:AAFanxc9zw8Cx5128FV_xyrWIufuL0heVV4"
TELEGRAM_CHAT_ID = "1734502645"

LOOKBACK_H4  = 10
LOOKBACK_M15 = 3
WINDOW_H     = 4

TICKERS = {
    "NQ=F": "🔵 Nasdaq (NQ)",
    "YM=F": "🟡 US30 (Dow Jones)",
}

def is_trading_session():
    now_utc  = datetime.now(timezone.utc)
    time_val = now_utc.hour * 60 + now_utc.minute
    if 7 * 60 <= time_val <= 12 * 60:
        return True, "🇬🇧 Session London"
    if 13 * 60 + 30 <= time_val <= 20 * 60:
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

def localize(ts):
    if not hasattr(ts, 'tzinfo') or ts.tzinfo is None:
        return ts.tz_localize('UTC')
    return ts

def detect_grabs_h4(df, lookback):
    grabs = []
    for i in range(lookback + 1, len(df) - 1):
        candle = df.iloc[i]
        prev   = df.iloc[i - lookback : i]
        sh     = to_float(prev["High"].max())
        sl     = to_float(prev["Low"].min())
        high   = to_float(candle["High"])
        low    = to_float(candle["Low"])
        close  = to_float(candle["Close"])
        ts     = localize(df.index[i])
        if high > sh and close < sh:
            grabs.append({"direction": "bearish", "price": close,
                          "h4_high": high, "h4_low": low,
                          "swing_high": sh, "swing_low": sl, "time": ts})
        elif low < sl and close > sl:
            grabs.append({"direction": "bullish", "price": close,
                          "h4_high": high, "h4_low": low,
                          "swing_high": sh, "swing_low": sl, "time": ts})
    return grabs

def detect_m15_internal_liquidity(df_m15, h4_grab, lookback_m15):
    h4_time    = h4_grab["time"]
    h4_high    = h4_grab["h4_high"]
    h4_low     = h4_grab["h4_low"]
    window_end = h4_time.timestamp() + WINDOW_H * 3600
    m15_window = []
    for i in range(len(df_m15)):
        ts   = localize(df_m15.index[i])
        high = to_float(df_m15.iloc[i]["High"])
        low  = to_float(df_m15.iloc[i]["Low"])
        if h4_time.timestamp() < ts.timestamp() <= window_end and low >= h4_low and high <= h4_high:
            m15_window.append((i, ts))
    if len(m15_window) < lookback_m15 + 2:
        return None
    for idx in range(lookback_m15 + 1, len(m15_window)):
        curr_i, curr_ts = m15_window[idx]
        curr_candle     = df_m15.iloc[curr_i]
        curr_high       = to_float(curr_candle["High"])
        curr_low        = to_float(curr_candle["Low"])
        curr_close      = to_float(curr_candle["Close"])
        prev_indices    = [m15_window[j][0] for j in range(idx - lookback_m15, idx)]
        prev_highs      = [to_float(df_m15.iloc[pi]["High"]) for pi in prev_indices]
        prev_lows       = [to_float(df_m15.iloc[pi]["Low"])  for pi in prev_indices]
        m15_swing_high  = max(prev_highs)
        m15_swing_low   = min(prev_lows)
        if curr_high > m15_swing_high and curr_close < m15_swing_high:
            return {"direction": "bearish", "price": curr_close,
                    "swept_level": m15_swing_high,
                    "swing_high": m15_swing_high, "swing_low": m15_swing_low, "time": curr_ts}
        elif curr_low < m15_swing_low and curr_close > m15_swing_low:
            return {"direction": "bullish", "price": curr_close,
                    "swept_level": m15_swing_low,
                    "swing_high": m15_swing_high, "swing_low": m15_swing_low, "time": curr_ts}
    return None

def detect_fvg(df_m15, h4_grab, m15_result):
    h4_high    = h4_grab["h4_high"]
    h4_low     = h4_grab["h4_low"]
    m15_time   = m15_result["time"]
    window_end = m15_time.timestamp() + WINDOW_H * 3600
    fvgs = []
    for i in range(2, len(df_m15)):
        ts = localize(df_m15.index[i])
        if not (m15_time.timestamp() < ts.timestamp() <= window_end):
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

def check_ticker(ticker, name, session_name):
    now = datetime.now(timezone.utc)
    df_h4     = get_data(ticker, "4h", "30d")
    grabs_h4  = detect_grabs_h4(df_h4, LOOKBACK_H4)
    recent_h4 = [g for g in grabs_h4 if (now - g["time"]).total_seconds() <= 8 * 3600]
    if not recent_h4:
        return f"  {name} : aucun grab H4 récent"
    df_m15 = get_data(ticker, "15m", "5d")
    for h4 in recent_h4:
        m15_result = detect_m15_internal_liquidity(df_m15, h4, LOOKBACK_M15)
        if not m15_result:
            continue
        fvg      = detect_fvg(df_m15, h4, m15_result)
        sl       = h4["h4_low"]     if h4["direction"] == "bullish" else h4["h4_high"]
        tp       = h4["swing_high"] if h4["direction"] == "bullish" else h4["swing_low"]
        risk     = abs(m15_result["price"] - sl)
        reward   = abs(tp - m15_result["price"])
        rr       = round(reward / risk, 1) if risk > 0 else 0
        emoji    = "🟢" if h4["direction"] == "bullish" else "🔴"
        label_h4 = "HAUSSIER" if h4["direction"] == "bullish" else "BAISSIER"
        ssl_bsl  = f"🔻 SSL sweepé : {h4['swing_low']:.2f}" if h4["direction"] == "bullish" else f"🔺 BSL sweepé : {h4['swing_high']:.2f}"
        fvg_line = f"📐 FVG M15 : {fvg['low']:.2f} → {fvg['high']:.2f}\n" if fvg else "📐 FVG : non détecté\n"
        liq_dir  = "haussière" if m15_result["direction"] == "bullish" else "baissière"
        send_telegram(
            f"{emoji} <b>SETUP H4 + Liquidité M15 Interne</b>\n"
            f"📊 {name} | {session_name}\n\n"
            f"<b>— Grab H4 {label_h4} —</b>\n"
            f"🕐 {h4['time'].strftime('%d/%m %H:%M')} UTC\n"
            f"💰 Prix H4 : {h4['price']:.2f}\n"
            f"{ssl_bsl}\n"
            f"📦 Range H4 : {h4['h4_low']:.2f} → {h4['h4_high']:.2f}\n\n"
            f"<b>— Liquidité M15 interne ({liq_dir}) —</b>\n"
            f"🕐 {m15_result['time'].strftime('%d/%m %H:%M')} UTC\n"
            f"💰 Prix M15 : {m15_result['price']:.2f}\n"
            f"📍 Niveau sweepé : {m15_result['swept_level']:.2f}\n"
            f"{fvg_line}\n"
            f"<b>— Gestion du trade —</b>\n"
            f"🛑 Stop Loss  : {sl:.2f}\n"
            f"🎯 Take Profit : {tp:.2f}\n"
            f"⚖️ Risk/Reward : 1:{rr}\n\n"
            f"⚡ <b>Liquidité M15 interne prise — Setup actif !</b>"
        )
        return f"  {name} : ALERTE envoyée ! RR 1:{rr}"
    return f"  {name} : grab H4 détecté, en attente liquidité M15 interne"

print(f"[{datetime.now().strftime('%H:%M:%S')}] Scanner démarré...")
in_session, session_name = is_trading_session()
if not in_session:
    print(f"  Hors session — pas de scan.")
    send_telegram(
        f"😴 <b>Scanner H4 + M15 Interne</b>\n"
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

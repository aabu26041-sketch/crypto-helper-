import os, re, json, time, requests
import xml.etree.ElementTree as ET

TOKEN = os.environ["TG_TOKEN"]
CHAT = os.environ["TG_CHAT"]
COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "ADA", "AVAX", "LINK", "TON", "TRX", "LTC", "DOT", "SUI", "NEAR"]
DEP, RISK, RR, ATRX = 1000, 20, 1.5, 2.0
MOVE, VOLX = 1.0, 3.0
HOLD = 24 * 3600 * 1000
FEE_RT = 0.0014
MAXNEWS = 3
STRONG = re.compile(r"\b(etf|sec|liquidat\w*|binance|okx|stablecoin\w*)\b")
CONTEXT = re.compile(r"\b(hack\w*|exploit\w*|stolen|breach\w*|bans?|banned|lawsuit\w*|fed|crash\w*)\b")
CRYPTO = re.compile(r"bitcoin|btc|ethereum|\beth\b|crypto|exchange|coinbase|bybit|kraken|tether|usdt|usdc|solana|\bxrp\b|ripple|doge|token|blockchain|defi|wallet|altcoin")
BASE = "https://www.okx.com/api/v5/"
H = {"User-Agent": "Mozilla/5.0"}
NOTE = "ℹ️ Не инвестиционная рекомендация. Стоп и тейк - расчёт риска, а не прогноз."

try:
    st = json.load(open("state.json"))
except Exception:
    st = {}
st.setdefault("last", {})
st.setdefault("seen", [])
st.setdefault("open", [])
st.setdefault("closed", [])

def send(t, preview=False):
    ok = False
    for chat in CHAT.split(","):
        try:
            data = {"chat_id": chat.strip(), "text": t}
            if not preview:
                data["link_preview_options"] = json.dumps({"is_disabled": True})
            r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data, timeout=20)
            if not r.ok:
                print("Telegram:", r.status_code, r.text[:200])
            ok = ok or r.ok
        except Exception as e:
            print("Telegram error:", type(e).__name__)
    return ok

def get(path, **params):
    r = requests.get(BASE + path, params=params, headers=H, timeout=20)
    r.raise_for_status()
    return r.json()["data"]

def candles(i, bar, n):
    return [[float(x) for x in c[1:6]] for c in get("market/candles", instId=i, bar=bar, limit=n)]

def fmt(p):
    if p >= 1000:
        return f"{p:,.0f}".replace(",", " ")
    if p >= 10:
        return f"{p:.2f}"
    if p >= 1:
        return f"{p:.3f}"
    if p >= 0.1:
        return f"{p:.4f}"
    return f"{p:.5f}"

def dist_of(i):
    k = candles(i, "1H", 30)
    tr = [max(k[j][1] - k[j][2], abs(k[j][1] - k[j + 1][3]), abs(k[j][2] - k[j + 1][3])) for j in range(15)]
    return ATRX * sum(tr[:14]) / 14

def plan(p, dist):
    size = RISK / (dist / p)
    txt = (f"Размер ${size:,.0f} (риск ${RISK}), при депозите ${DEP} нужно плечо ~{size / DEP:.1f}x\n"
           f"Лонг: стоп {fmt(p - dist)} -> тейк {fmt(p + RR * dist)}\n"
           f"Шорт: стоп {fmt(p + dist)} -> тейк {fmt(p - RR * dist)}")
    if size > DEP * 3:
        txt += "\n⚠️ Позиция больше 3x депозита: уменьши размер"
    return txt

def buyers(c):
    try:
        d = get("rubik/stat/taker-volume", ccy=c, instType="CONTRACTS", period="5m")[:3]
        sell = sum(float(x[1]) for x in d)
        buy = sum(float(x[2]) for x in d)
        return buy / (buy + sell) * 100 if buy + sell else None
    except Exception:
        return None

def funding(i):
    try:
        return float(get("public/funding-rate", instId=i)[0]["fundingRate"]) * 100
    except Exception:
        return None

def paper(c, i, p, ch, dist):
    if len(st["open"]) >= 60:
        return
    for mode, side in (("trend", 1 if ch > 0 else -1), ("counter", -1 if ch > 0 else 1)):
        if any(t["coin"] == c and t["mode"] == mode for t in st["open"]):
            continue
        st["open"].append({"coin": c, "inst": i, "mode": mode, "side": side, "e": p,
                           "sl": p - side * dist, "tp": p + side * RR * dist,
                           "size": RISK / (dist / p), "t": int(time.time() * 1000)})

def market():
    rows, moves = [], []
    for c in COINS:
        i = c + "-USDT-SWAP"
        try:
            k = candles(i, "5m", 50)
        except Exception as e:
            print("пропуск", c, type(e).__name__)
            continue
        p = k[0][3]
        ch = (p / k[3][3] - 1) * 100
        avg = sum(r[4] for r in k[2:]) / len(k[2:])
        vx = k[1][4] / avg if avg else 0
        moves.append(ch)
        if (abs(ch) >= MOVE or vx >= VOLX) and time.time() - st["last"].get(c, 0) > 1800:
            rows.append((c, i, p, ch, vx))
    if not rows:
        return
    rows.sort(key=lambda r: -abs(r[3]))
    rows = rows[:6]
    down = sum(1 for m in moves if m < 0)
    up = len(moves) - down
    parts = [f"📊 Рынок: падают {down} из {len(moves)} монет, растут {up}"]
    sent = []
    for c, i, p, ch, vx in rows:
        try:
            dist = dist_of(i)
        except Exception as e:
            print("atr", c, type(e).__name__)
            continue
        b = buyers(c)
        f = funding(i)
        lines = [f"⚡ {c}: {ch:+.2f}% за 15 мин, цена {fmt(p)}", f"Объём x{vx:.1f} от обычного"]
        if b is not None:
            lines.append(f"Покупатели {b:.0f}% / продавцы {100 - b:.0f}% (15 мин)")
        if f is not None:
            lines.append(f"Фандинг {f:+.3f}%")
        lines.append(plan(p, dist))
        parts.append("\n".join(lines))
        paper(c, i, p, ch, dist)
        sent.append(c)
    if not sent:
        return
    parts.append(NOTE)
    if send("\n\n".join(parts)[:4000]):
        for c in sent:
            st["last"][c] = time.time()

def journal():
    now = int(time.time() * 1000)
    cache, keep = {}, []
    for t in st["open"]:
        try:
            if t["inst"] not in cache:
                d = get("market/candles", instId=t["inst"], bar="5m", limit=300)
                cache[t["inst"]] = sorted([[float(x) for x in c[:5]] for c in d], key=lambda r: r[0])
                time.sleep(0.15)
            k = [r for r in cache[t["inst"]] if r[0] > t["t"]]
        except Exception as e:
            print("журнал", t["coin"], type(e).__name__)
            keep.append(t)
            continue
        s = t["side"]
        x = why = None
        for ts, o, h, l, cl in k:
            hit_sl = l <= t["sl"] if s == 1 else h >= t["sl"]
            hit_tp = h >= t["tp"] if s == 1 else l <= t["tp"]
            if hit_sl:
                x, why = t["sl"], "стоп"
                break
            if hit_tp:
                x, why = t["tp"], "тейк"
                break
        if x is None and now - t["t"] > HOLD:
            x, why = (k[-1][4] if k else t["e"]), "время"
        if x is None:
            keep.append(t)
            continue
        pnl = s * (x - t["e"]) / t["e"] * t["size"] - t["size"] * FEE_RT
        t.update({"x": x, "why": why, "pnl": round(pnl, 2), "tc": now})
        st["closed"].append(t)
    st["open"] = keep
    st["closed"] = st["closed"][-1000:]

def report():
    if not st["closed"] or time.time() - st.get("last_report", 0) < 86000:
        return
    lines = [f"📒 Журнал виртуальных сделок (риск ${RISK} на сделку, комиссии учтены)"]
    small = False
    for m, name in (("trend", "По движению"), ("counter", "Против движения")):
        c = [t for t in st["closed"] if t["mode"] == m]
        if len(c) < 50:
            small = True
        if not c:
            lines.append(f"{name}: пока нет закрытых")
            continue
        w = sum(1 for t in c if t["pnl"] > 0)
        tot = sum(t["pnl"] for t in c)
        lines.append(f"{name}: {len(c)} сделок, прибыльных {w / len(c) * 100:.0f}%, итог {tot:+.0f}$")
    lines.append(f"Открыто сейчас: {len(st['open'])}")
    lines.append("Чтобы выйти в ноль, нужно примерно 42% прибыльных.")
    if small:
        lines.append("⏳ Пока меньше 50 сделок на вариант: выводы делать рано.")
    if send("\n".join(lines)):
        st["last_report"] = time.time()

def tag(t):
    if re.search(r"hack|exploit|stolen|breach", t):
        return "🚨"
    if re.search(r"\b(sec|etf|lawsuit|ban|bans)\b", t):
        return "⚖️"
    if re.search(r"crash|liquidat|\bfed\b", t):
        return "📉"
    return "📰"

def news():
    first = not st["seen"]
    sent = 0
    for u in ["https://www.coindesk.com/arc/outboundfeeds/rss/", "https://cointelegraph.com/rss"]:
        root = ET.fromstring(requests.get(u, headers=H, timeout=20).content)
        for it in list(root.iter("item"))[:10]:
            t = it.find("title").text or ""
            if t in st["seen"]:
                continue
            st["seen"].append(t)
            low = t.lower()
            ok = STRONG.search(low) or (CONTEXT.search(low) and CRYPTO.search(low))
            if not first and ok and sent < MAXNEWS:
                send(tag(low) + " " + t + "\n" + (it.find("link").text or ""))
                sent += 1
    st["seen"] = st["seen"][-300:]

if not st.get("started"):
    if send("Помощник запущен ✅"):
        st["started"] = True
    else:
        raise SystemExit("Не удалось отправить в Telegram: проверь секреты TG_TOKEN и TG_CHAT")
for f in (market, journal, report, news):
    try:
        f()
        st.pop("err_" + f.__name__, None)
    except Exception as e:
        print("ошибка", f.__name__, e)
        if not st.get("err_" + f.__name__):
            st["err_" + f.__name__] = True
            send(f"⚠️ {f.__name__}: ошибка {str(e)[:150]}")
json.dump(st, open("state.json", "w"))

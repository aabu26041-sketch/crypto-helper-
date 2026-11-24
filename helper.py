import os, re, json, time, requests
import xml.etree.ElementTree as ET

TOKEN = os.environ["TG_TOKEN"]
CHAT = os.environ["TG_CHAT"]
COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
DEP, RISK, RR, ATRX = 1000, 20, 1.5, 2.0
MOVE, VOLX = 1.0, 3.0
WORDS = re.compile(r"\b(sec|etf|hack\w*|exploit\w*|liquidat\w*|bans?|lawsuit\w*|fed|crash\w*|binance|okx)\b")
BASE = "https://www.okx.com/api/v5/"
H = {"User-Agent": "Mozilla/5.0"}
NOTE = "ℹ️ Не инвестиционная рекомендация. Стоп и тейк - расчёт риска, а не прогноз."

try:
    st = json.load(open("state.json"))
except Exception:
    st = {}
st.setdefault("last", {})
st.setdefault("seen", [])

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

def plan(i, p):
    k = candles(i, "1H", 30)
    tr = [max(k[j][1] - k[j][2], abs(k[j][1] - k[j + 1][3]), abs(k[j][2] - k[j + 1][3])) for j in range(15)]
    dist = ATRX * sum(tr[:14]) / 14
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

def market():
    rows, moves = [], []
    for c in COINS:
        i = c + "-USDT-SWAP"
        k = candles(i, "5m", 50)
        p = k[0][3]
        ch = (p / k[3][3] - 1) * 100
        vx = k[1][4] / (sum(r[4] for r in k[2:]) / len(k[2:]))
        moves.append(ch)
        if (abs(ch) >= MOVE or vx >= VOLX) and time.time() - st["last"].get(c, 0) > 1800:
            rows.append((c, i, p, ch, vx))
    if not rows:
        return
    down = sum(1 for m in moves if m < 0)
    up = len(moves) - down
    parts = [f"📊 Рынок: падают {down} из {len(moves)} монет, растут {up}"]
    for c, i, p, ch, vx in rows:
        b = buyers(c)
        f = funding(i)
        lines = [f"⚡ {c}: {ch:+.2f}% за 15 мин, цена {fmt(p)}", f"Объём x{vx:.1f} от обычного"]
        if b is not None:
            lines.append(f"Покупатели {b:.0f}% / продавцы {100 - b:.0f}% (15 мин)")
        if f is not None:
            lines.append(f"Фандинг {f:+.3f}%")
        lines.append(plan(i, p))
        parts.append("\n".join(lines))
    parts.append(NOTE)
    if send("\n\n".join(parts)):
        for r in rows:
            st["last"][r[0]] = time.time()

def tag(t):
    if re.search(r"hack|exploit|stolen", t):
        return "🚨"
    if re.search(r"\b(sec|etf|lawsuit|ban|bans)\b", t):
        return "⚖️"
    if re.search(r"crash|liquidat|\bfed\b", t):
        return "📉"
    return "📰"

def news():
    first = not st["seen"]
    for u in ["https://www.coindesk.com/arc/outboundfeeds/rss/", "https://cointelegraph.com/rss"]:
        root = ET.fromstring(requests.get(u, headers=H, timeout=20).content)
        for it in list(root.iter("item"))[:10]:
            t = it.find("title").text or ""
            if t in st["seen"]:
                continue
            st["seen"].append(t)
            if not first and WORDS.search(t.lower()):
                send(tag(t.lower()) + " " + t + "\n" + (it.find("link").text or ""))
    st["seen"] = st["seen"][-300:]

if not st.get("started"):
    if send("Помощник запущен ✅"):
        st["started"] = True
    else:
        raise SystemExit("Не удалось отправить в Telegram: проверь секреты TG_TOKEN и TG_CHAT")
for f in (market, news):
    try:
        f()
        st.pop("err_" + f.__name__, None)
    except Exception as e:
        print("ошибка", f.__name__, e)
        if not st.get("err_" + f.__name__):
            st["err_" + f.__name__] = True
            send(f"⚠️ {f.__name__}: ошибка {str(e)[:150]}")
json.dump(st, open("state.json", "w"))

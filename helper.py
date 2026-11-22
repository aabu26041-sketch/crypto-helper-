import os, re, json, time, requests
import xml.etree.ElementTree as ET

TOKEN = os.environ["TG_TOKEN"]
CHAT = os.environ["TG_CHAT"]
COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
RISK, RR, ATRX = 20, 1.5, 2.0
MOVE, VOLX = 5.0, 3.0
WORDS = re.compile(r"\b(sec|etf|hack\w*|exploit\w*|liquidat\w*|bans?|lawsuit\w*|fed|crash\w*|binance|okx)\b")
URL = "https://www.okx.com/api/v5/market/candles"
H = {"User-Agent": "Mozilla/5.0"}

try:
    st = json.load(open("state.json"))
except Exception:
    st = {}
st.setdefault("last", {})
st.setdefault("seen", [])

def send(t):
    try:
        r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                          data={"chat_id": CHAT, "text": t}, timeout=20)
        if not r.ok:
            print("Telegram:", r.status_code, r.text[:200])
        return r.ok
    except Exception as e:
        print("Telegram error:", type(e).__name__)
        return False

def candles(i, bar, n):
    r = requests.get(URL, params={"instId": i, "bar": bar, "limit": n}, timeout=20)
    r.raise_for_status()
    return [[float(x) for x in c[1:6]] for c in r.json()["data"]]

def plan(i, p):
    k = candles(i, "1H", 30)
    tr = [max(k[j][1] - k[j][2], abs(k[j][1] - k[j + 1][3]), abs(k[j][2] - k[j + 1][3])) for j in range(15)]
    dist = ATRX * sum(tr[:14]) / 14
    size = RISK / (dist / p)
    return (f"Размер ${size:.0f} (риск ${RISK})\n"
            f"Лонг: стоп {p - dist:.4g}, тейк {p + RR * dist:.4g}\n"
            f"Шорт: стоп {p + dist:.4g}, тейк {p - RR * dist:.4g}")

def market():
    for c in COINS:
        i = c + "-USDT-SWAP"
        k = candles(i, "5m", 50)
        p = k[0][3]
        ch = (p / k[3][3] - 1) * 100
        vx = k[1][4] / (sum(r[4] for r in k[2:]) / len(k[2:]))
        if (abs(ch) >= MOVE or vx >= VOLX) and time.time() - st["last"].get(c, 0) > 1800:
            msg = f"⚡ {c}: {ch:+.2f}% за 15 мин, объём x{vx:.1f}, цена {p}\n" + plan(i, p)
            if send(msg):
                st["last"][c] = time.time()

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
                send("📰 " + t + "\n" + (it.find("link").text or ""))
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

# Read-only Binance breakout alert, run by GitHub Actions every ~5 minutes.
# Each run: pick the 6 coins with the most traded value in the last 30 minutes (from the 30 busiest
# over 24h, excluding BTC/ETH/SOL, stablecoins and tokenized stocks), then look at every 1-minute
# candle closed since the previous run. A candle is a breakout when:
#   - its traded value >= 3x the average of the 12 candles before it (the base)
#   - it closes above the highest high of that base, in the top 30% of its own range
#   - and traded value of the 15 minutes up to it >= 1.5x the 15 minutes before that
# Matches go to the ntfy app. Already-sent candles are remembered in seen.json (kept by actions/cache).
import json, os, time, datetime, urllib.request

API = "https://data-api.binance.vision/api/v3/"     # public market data, not geo-blocked
TOP_N, LOOKBACK = 6, 15                             # check candles closed in the last 15 minutes
EXCLUDE = {"BTC", "ETH", "SOL"}
STABLE = {"USDC","FDUSD","TUSD","USDP","DAI","EUR","USD1","BUSD","USDE","XUSD","RLUSD","EURI","AEUR","PAXG","XAUT"}
STOCKS = {"NVDA","SNDK","TSLA","AAPL","MSTR","COIN","AMZN","GOOGL","META","MSFT","HOOD","CRCL","SPY","QQQ"}
CAIRO = datetime.timezone(datetime.timedelta(hours=2))
TOPIC = os.environ.get("NTFY_TOPIC", "").strip()

def get(p): return json.load(urllib.request.urlopen(API + p, timeout=20))
def hm(ms): return datetime.datetime.fromtimestamp(ms / 1000, CAIRO).strftime("%H:%M")

def phone(title, msg):
    if not TOPIC: print("no NTFY_TOPIC"); return
    req = urllib.request.Request(f"https://ntfy.sh/{TOPIC}", data=msg.encode(),
          headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"})
    urllib.request.urlopen(req, timeout=15)

def ok(b): return b not in STABLE | EXCLUDE | STOCKS and not (b.endswith("B") and b[:-1] in STOCKS)

def top_coins():
    t = [x for x in get("ticker/24hr") if x["symbol"].endswith("USDT") and ok(x["symbol"][:-4])]
    pool = sorted(t, key=lambda x: -float(x["quoteVolume"]))[:30]
    for x in pool:
        x["k"] = get(f"klines?symbol={x['symbol']}&interval=1m&limit={31 + LOOKBACK}")[:-1]  # drop forming candle
        x["qv30"] = sum(float(r[7]) for r in x["k"][-30:])
    return sorted(pool, key=lambda x: -x["qv30"])[:TOP_N]

def scan(x):
    k = x["k"]; h, l, c, qv, tb = [[float(r[i]) for r in k] for i in (2, 3, 4, 7, 10)]
    out = []
    for i in range(max(30, len(k) - LOOKBACK), len(k)):
        base = slice(i - 12, i)
        bh, bl, bavg = max(h[base]), min(l[base]), sum(qv[base]) / 12
        rng = h[i] - l[i]
        top30 = rng == 0 or (c[i] - l[i]) / rng >= 0.7
        vol_rise = sum(qv[i - 14:i + 1]) / max(sum(qv[i - 29:i - 14]), 1e-9)
        if qv[i] >= 3 * bavg and c[i] > bh and top30 and vol_rise >= 1.5:
            buy = sum(tb[i - 14:i + 1]) / sum(qv[i - 14:i + 1]) * 100
            out.append(dict(ms=k[i][0], close=c[i], mult=qv[i] / bavg, bl=bl, bh=bh, vol_rise=vol_rise, buy=buy,
                            now=c[-1], ch30=(c[-1] - float(k[-30][1])) / float(k[-30][1]) * 100))
    return out

seen = set(json.load(open("seen.json"))) if os.path.exists("seen.json") else set()
cut = (time.time() - 3 * 3600) * 1000
coins = top_coins()
print("top:", ", ".join(f"{x['symbol'][:-4]} {x['qv30']/1e6:.1f}M$" for x in coins))
for x in coins:
    for m in scan(x):
        key = f"{x['symbol']}-{m['ms']}"
        recent = [int(s.rsplit("-", 1)[1]) for s in seen if s.startswith(x["symbol"] + "-")]
        if key in seen or any(0 <= m["ms"] - t < 30 * 60000 for t in recent): continue   # 30-min cooldown per coin
        seen.add(key)
        sym = x["symbol"][:-4]
        msg = (f"{sym} الساعة {hm(m['ms'])}: قفل {m['close']:g} بحجم {m['mult']:.1f}x القاعدة\n"
               f"كسر القاعدة {m['bl']:g} - {m['bh']:g} | السعر دلوقتي {m['now']:g}\n"
               f"حجم آخر ربع ساعة {m['vol_rise']:.1f}x | شراء ماركت {m['buy']:.0f}% | نص ساعة {m['ch30']:+.2f}%\n"
               f"أرقام بس، مش نصيحة")
        print("MATCH", msg.replace("\n", " | "))
        phone(f"{sym} breakout + volume", msg)
json.dump(sorted(s for s in seen if int(s.rsplit("-", 1)[1]) > cut), open("seen.json", "w"))

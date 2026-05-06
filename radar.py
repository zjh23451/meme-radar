import requests, os, json, time

TG_TOKEN   = os.environ["TG_TOKEN"]
TG_CHAT_ID = os.environ["TG_CHAT_ID"]
STATE_FILE = "seen.json"

# ── 过滤条件 ──────────────────────────
MCAP_MIN   = 1_000_000      # 市值 ≥ $1M
VOL5M_MIN  = 100_000        # 5分钟成交额 ≥ $100k
LIQ_MIN    = 30_000         # 流动性 ≥ $30k
CHG5M_MIN  = 0              # 5分钟涨幅 > 0
CHG1H_MIN  = 0              # 1小时涨幅 > 0
CHAINS     = ["ethereum", "solana"]

# 多关键词聚合，覆盖热门交易对
SEARCH_TERMS = [
    "WETH", "USDC", "USDT", "SOL", "WSOL",
    "PEPE", "DOGE", "SHIB", "BONK", "WIF",
    "MOG", "TRUMP", "AI", "MEME", "CAT",
    "FROG", "DOG", "ELON", "BABY", "MOON",
]

GOPLUS_CHAIN = {"ethereum": "1", "solana": "solana"}

def send_tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10
        )
    except: pass

def fmt(n):
    if n >= 1e9: return f"${n/1e9:.2f}B"
    if n >= 1e6: return f"${n/1e6:.2f}M"
    if n >= 1e3: return f"${n/1e3:.1f}K"
    return f"${n:.2f}"

def is_honeypot(chain, token_address):
    goplus_chain = GOPLUS_CHAIN.get(chain)
    if not goplus_chain or not token_address:
        return False
    try:
        if chain == "solana":
            url = f"https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses={token_address}"
        else:
            url = f"https://api.gopluslabs.io/api/v1/token_security/{goplus_chain}?contract_addresses={token_address}"
        r = requests.get(url, timeout=8)
        if not r.ok: return False
        data = r.json().get("result", {})
        info = data.get(token_address.lower()) or data.get(token_address) or {}
        if not info: return False
        if str(info.get("is_honeypot", "0")) == "1":     return True
        if str(info.get("cannot_sell_all", "0")) == "1": return True
        if str(info.get("is_blacklisted", "0")) == "1":  return True
        try:
            if float(info.get("sell_tax", 0) or 0) > 0.10: return True
            if float(info.get("buy_tax", 0)  or 0) > 0.10: return True
        except: pass
        return False
    except:
        return False

def search_pairs(query):
    """通过 DexScreener 搜索接口拉取交易对"""
    try:
        r = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={query}", timeout=12)
        if not r.ok: return []
        return r.json().get("pairs") or []
    except: return []

# 读取上次已推送
try:
    seen = set(json.load(open(STATE_FILE)))
except:
    seen = set()

# 聚合所有交易对
all_pairs = []
seen_pids = set()
for q in SEARCH_TERMS:
    pairs = search_pairs(q)
    for p in pairs:
        pid = p.get("pairAddress")
        if pid and pid not in seen_pids:
            seen_pids.add(pid)
            all_pairs.append(p)
    time.sleep(0.2)

print(f"聚合到 {len(all_pairs)} 个交易对")

alerts = []
checked = 0

for p in all_pairs:
    chain = p.get("chainId")
    if chain not in CHAINS:
        continue

    pid    = p.get("pairAddress", "")
    mcap   = p.get("marketCap") or p.get("fdv") or 0
    vol5m  = (p.get("volume") or {}).get("m5") or 0
    liq    = (p.get("liquidity") or {}).get("usd") or 0
    chg5m  = (p.get("priceChange") or {}).get("m5") or 0
    chg1h  = (p.get("priceChange") or {}).get("h1") or 0
    token_addr = (p.get("baseToken") or {}).get("address", "")

    # ── 基础过滤 ──
    if mcap < MCAP_MIN:    continue
    if vol5m < VOL5M_MIN:  continue
    if liq < LIQ_MIN:      continue
    if chg5m <= CHG5M_MIN: continue
    if chg1h <= CHG1H_MIN: continue
    if pid in seen:        continue

    checked += 1
    # ── 貔貅检测 ──
    if is_honeypot(chain, token_addr):
        print(f"[貔貅过滤] {(p.get('baseToken') or {}).get('symbol')} on {chain}")
        continue
    time.sleep(0.25)

    seen.add(pid)
    sym = (p.get("baseToken") or {}).get("symbol", "???")
    tag = {"ethereum":"ETH","solana":"SOL"}.get(chain, chain.upper())

    alerts.append(
        f"🔥 <b>新信号 [{tag}]</b>\n"
        f"代币：<b>${sym}</b>\n"
        f"市值：{fmt(mcap)}\n"
        f"5M成交额：{fmt(vol5m)}\n"
        f"流动性：{fmt(liq)}\n"
        f"5M涨幅：🟢 +{chg5m:.1f}%\n"
        f"1H涨幅：🟢 +{chg1h:.1f}%\n"
        f"✅ 貔貅检测：通过\n"
        f"🔗 <a href='{p.get('url','#')}'>DEX Screener</a>"
    )

for msg in alerts:
    send_tg(msg)
    time.sleep(0.5)

json.dump(list(seen)[-1000:], open(STATE_FILE, "w"))
print(f"完成 | 候选 {checked} | 推送 {len(alerts)}")

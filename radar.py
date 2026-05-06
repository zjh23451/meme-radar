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

# GeckoTerminal 链ID
GT_CHAINS = {
    "eth": "ETH",
    "solana": "SOL",
}

# DexScreener 链名映射（用于貔貅检测）
DS_CHAIN_MAP = {
    "eth": "ethereum",
    "solana": "solana",
}

GOPLUS_CHAIN = {
    "eth": "1",
    "solana": "solana",
}

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
    n = float(n or 0)
    if n >= 1e9: return f"${n/1e9:.2f}B"
    if n >= 1e6: return f"${n/1e6:.2f}M"
    if n >= 1e3: return f"${n/1e3:.1f}K"
    return f"${n:.2f}"

def is_honeypot(chain, token_address):
    """通过 GoPlus 检查貔貅"""
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

def fetch_gecko(chain, endpoint, pages=2):
    """从 GeckoTerminal 拉取榜单"""
    all_pools = []
    for page in range(1, pages + 1):
        try:
            url = f"https://api.geckoterminal.com/api/v2/networks/{chain}/{endpoint}?page={page}"
            r = requests.get(url, timeout=12, headers={"Accept": "application/json"})
            if not r.ok: break
            data = r.json().get("data", [])
            if not data: break
            all_pools.extend(data)
            time.sleep(0.4)  # 避免限速
        except:
            break
    return all_pools

def parse_pool(pool, chain):
    """解析 GeckoTerminal 池数据"""
    attr = pool.get("attributes", {})
    rel  = pool.get("relationships", {})

    base_token_id = (rel.get("base_token", {}).get("data", {}) or {}).get("id", "")
    token_addr = base_token_id.split("_", 1)[1] if "_" in base_token_id else ""

    return {
        "chain":      chain,
        "pair_addr":  attr.get("address", ""),
        "token_addr": token_addr,
        "symbol":     (attr.get("name") or "").split(" / ")[0] or "???",
        "price":      float(attr.get("base_token_price_usd") or 0),
        "mcap":       float(attr.get("market_cap_usd") or attr.get("fdv_usd") or 0),
        "liq":        float(attr.get("reserve_in_usd") or 0),
        "vol5m":      float((attr.get("volume_usd") or {}).get("m5") or 0),
        "vol1h":      float((attr.get("volume_usd") or {}).get("h1") or 0),
        "chg5m":      float((attr.get("price_change_percentage") or {}).get("m5") or 0),
        "chg1h":      float((attr.get("price_change_percentage") or {}).get("h1") or 0),
        "url":        f"https://www.geckoterminal.com/{chain}/pools/{attr.get('address','')}",
    }

# ── 读取上次状态 ──
try:
    seen = set(json.load(open(STATE_FILE)))
except:
    seen = set()

# ── 聚合双榜单 ──
all_pools = []
seen_addrs = set()

for chain in GT_CHAINS.keys():
    # 按成交额榜单（top pools 按 24H 成交额排序，每页 20 个，拉 5 页 = 100 个）
    top = fetch_gecko(chain, "pools", pages=5)
    # 热门榜单
    trend = fetch_gecko(chain, "trending_pools", pages=2)
    # 最新池
    new = fetch_gecko(chain, "new_pools", pages=2)

    for pool in top + trend + new:
        addr = (pool.get("attributes") or {}).get("address", "")
        if addr and addr not in seen_addrs:
            seen_addrs.add(addr)
            all_pools.append((chain, pool))

print(f"聚合到 {len(all_pools)} 个交易对")

alerts = []
candidates = 0

for chain, pool in all_pools:
    try:
        d = parse_pool(pool, chain)
    except:
        continue

    # ── 基础过滤 ──
    if d["mcap"] < MCAP_MIN:    continue
    if d["vol5m"] < VOL5M_MIN:  continue
    if d["liq"] < LIQ_MIN:      continue
    if d["chg5m"] <= CHG5M_MIN: continue
    if d["chg1h"] <= CHG1H_MIN: continue
    if d["pair_addr"] in seen:  continue

    candidates += 1

    # ── 貔貅检测 ──
    if is_honeypot(chain, d["token_addr"]):
        print(f"[貔貅过滤] {d['symbol']} on {chain}")
        continue
    time.sleep(0.25)

    seen.add(d["pair_addr"])
    tag = GT_CHAINS.get(chain, chain.upper())

    alerts.append(
        f"🔥 <b>新信号 [{tag}]</b>\n"
        f"代币：<b>${d['symbol']}</b>\n"
        f"市值：{fmt(d['mcap'])}\n"
        f"5M成交额：{fmt(d['vol5m'])}\n"
        f"1H成交额：{fmt(d['vol1h'])}\n"
        f"流动性：{fmt(d['liq'])}\n"
        f"5M涨幅：🟢 +{d['chg5m']:.1f}%\n"
        f"1H涨幅:🟢 +{d['chg1h']:.1f}%\n"
        f"✅ 貔貅检测：通过\n"
        f"🔗 <a href='{d['url']}'>查看图表</a>"
    )

for msg in alerts:
    send_tg(msg)
    time.sleep(0.5)

json.dump(list(seen)[-1500:], open(STATE_FILE, "w"))
print(f"完成 | 聚合 {len(all_pools)} | 候选 {candidates} | 推送 {len(alerts)}")

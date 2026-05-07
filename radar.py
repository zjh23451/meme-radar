import requests, os, json, time

TG_TOKEN    = os.environ["TG_TOKEN"]
TG_CHAT_ID  = os.environ["TG_CHAT_ID"]
AVE_API_KEY = os.environ["AVE_API_KEY"]
STATE_FILE  = "seen.json"

# ── 过滤条件 ──────────────────────────
MCAP_MIN   = 1_000_000     # 市值 ≥ $1M
VOL5M_MIN  = 100_000       # 5M 成交额 ≥ $100k
LIQ_MIN    = 30_000        # 流动性 ≥ $30k
CHG5M_MIN  = 0             # 5M 涨幅 > 0
CHG1H_MIN  = 0             # 1H 涨幅 > 0

# 去重窗口:同一代币 N 秒内不重复推送
DEDUP_WINDOW_SEC = 24 * 3600   # 24 小时

CHAINS = ["solana", "eth"]
CHAIN_LABEL = {"solana": "SOL", "eth": "ETH"}

HEADERS = {
    "X-API-KEY": AVE_API_KEY,
    "Accept": "application/json",
}

def send_tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10
        )
    except Exception as e:
        print(f"TG发送失败: {e}")

def fmt(n):
    n = float(n or 0)
    if n >= 1e9: return f"${n/1e9:.2f}B"
    if n >= 1e6: return f"${n/1e6:.2f}M"
    if n >= 1e3: return f"${n/1e3:.1f}K"
    return f"${n:.2f}"

def safe_float(v, default=0):
    try: return float(v or 0)
    except: return default

def fetch_trending(chain, page_size=50):
    tokens = []
    try:
        for page in range(0, 4):
            url = f"https://prod.ave-api.com/v2/tokens/trending?chain={chain}&current_page={page}&page_size={page_size}"
            r = requests.get(url, headers=HEADERS, timeout=15)
            if not r.ok:
                print(f"  [{chain}] trending p{page} HTTP {r.status_code}")
                break
            data = (r.json().get("data") or {})
            page_tokens = data.get("tokens") or []
            if not page_tokens:
                break
            tokens.extend(page_tokens)
            if not data.get("next_page"):
                break
            time.sleep(0.5)
    except Exception as e:
        print(f"  [{chain}] trending 失败: {e}")
    return tokens

def fetch_rank(topic):
    try:
        url = f"https://prod.ave-api.com/v2/ranks?topic={topic}&limit=200"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if not r.ok:
            print(f"  rank {topic} HTTP {r.status_code}")
            return []
        return r.json().get("data") or []
    except Exception as e:
        print(f"  rank {topic} 失败: {e}")
        return []

# ── 读取已推送状态(地址 -> 上次推送时间戳) ──
now_ts = int(time.time())
seen = {}
try:
    raw = json.load(open(STATE_FILE))
    if isinstance(raw, list):
        # 兼容旧格式
        seen = {addr: now_ts for addr in raw}
    elif isinstance(raw, dict):
        seen = {k: int(v) for k, v in raw.items()}
except:
    seen = {}

# ── 多榜单聚合 ──
all_tokens = []
seen_addrs = set()

for chain in CHAINS:
    tokens = fetch_trending(chain)
    print(f"[{chain}] trending: {len(tokens)}")
    for t in tokens:
        addr = t.get("token", "")
        if addr and addr not in seen_addrs:
            seen_addrs.add(addr)
            all_tokens.append(t)

for topic in ["hot", "gainer", "meme"]:
    tokens = fetch_rank(topic)
    print(f"[rank {topic}] {len(tokens)}")
    for t in tokens:
        addr = t.get("token", "")
        chain = t.get("chain", "")
        if addr and chain in CHAINS and addr not in seen_addrs:
            seen_addrs.add(addr)
            all_tokens.append(t)
    time.sleep(0.5)

print(f"\n聚合到 {len(all_tokens)} 个代币")

alerts = []
candidates = 0

for t in all_tokens:
    chain = t.get("chain", "")
    if chain not in CHAINS:
        continue

    addr   = t.get("token", "")
    mcap   = safe_float(t.get("market_cap") or t.get("fdv"))
    liq    = safe_float(t.get("tvl") or t.get("main_pair_tvl"))
    vol5m  = safe_float(t.get("token_tx_volume_usd_5m"))
    vol1h  = safe_float(t.get("token_tx_volume_usd_1h"))
    chg5m  = safe_float(t.get("token_price_change_5m"))
    chg1h  = safe_float(t.get("token_price_change_1h"))
    sym    = t.get("symbol", "???")

    if mcap < MCAP_MIN:    continue
    if vol5m < VOL5M_MIN:  continue
    if liq < LIQ_MIN:      continue
    if chg5m <= CHG5M_MIN: continue
    if chg1h <= CHG1H_MIN: continue

    # ── 24 小时去重 ──
    last_ts = seen.get(addr, 0)
    if now_ts - last_ts < DEDUP_WINDOW_SEC:
        continue

    candidates += 1

    # 安全检测
    if t.get("is_honeypot") is True:
        print(f"[貔貅过滤] {sym} on {chain}")
        continue
    if t.get("is_in_blacklist") is True:
        print(f"[黑名单过滤] {sym} on {chain}")
        continue
    risk_level = t.get("ave_risk_level", 0)
    if isinstance(risk_level, (int, float)) and risk_level >= 2:
        print(f"[高风险过滤] {sym} 风险={risk_level}")
        continue

    seen[addr] = now_ts
    tag = CHAIN_LABEL.get(chain, chain.upper())
    risk_score = t.get("risk_score", "?")

    is_repeat = last_ts > 0
    flag = "🔁 <b>再次触发</b>" if is_repeat else "🔥 <b>新信号</b>"

    alerts.append(
        f"{flag} [{tag}]\n"
        f"代币：<b>${sym}</b>\n"
        f"市值：{fmt(mcap)}\n"
        f"流动性：{fmt(liq)}\n"
        f"5M成交额：{fmt(vol5m)}\n"
        f"1H成交额：{fmt(vol1h)}\n"
        f"5M涨幅：🟢 +{chg5m:.1f}%\n"
        f"1H涨幅：🟢 +{chg1h:.1f}%\n"
        f"安全分：{risk_score} ✅\n"
        f"\n"
        f"📋 CA(点击复制):\n"
        f"<code>{addr}</code>\n"
        f"\n"
        f"🔗 <a href='https://ave.ai/token/{addr}-{chain}'>Ave.ai</a> | "
        f"<a href='https://gmgn.ai/{chain}/token/{addr}'>GMGN</a> | "
        f"<a href='https://dexscreener.com/{chain}/{addr}'>DEX</a>"
    )

for msg in alerts:
    send_tg(msg)
    time.sleep(0.5)

# 清理过期记录(超过 7 天的)
expire_ts = now_ts - 7 * 24 * 3600
seen = {k: v for k, v in seen.items() if v > expire_ts}

json.dump(seen, open(STATE_FILE, "w"))
print(f"\n完成 | 聚合 {len(all_tokens)} | 候选 {candidates} | 推送 {len(alerts)} | 已记录 {len(seen)}")

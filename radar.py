import requests, os, json, time

TG_TOKEN   = os.environ["TG_TOKEN"]
TG_CHAT_ID = os.environ["TG_CHAT_ID"]
STATE_FILE = "seen.json"

MCAP_MIN  = 1_000_000
VOL1H_MIN = 1_000_000
LIQ_MIN   = 10_000
CHAINS    = ["ethereum", "solana", "bsc"]

GOPLUS_CHAIN = {
    "ethereum": "1",
    "bsc": "56",
    "solana": "solana"
}

def send_tg(msg):
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": msg,
              "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=10
    )

def fmt(n):
    if n >= 1e9: return f"${n/1e9:.2f}B"
    if n >= 1e6: return f"${n/1e6:.2f}M"
    if n >= 1e3: return f"${n/1e3:.1f}K"
    return f"${n:.2f}"

def is_honeypot(chain, token_address):
    goplus_chain = GOPLUS_CHAIN.get(chain)
    if not goplus_chain:
        return False
    try:
        if chain == "solana":
            url = f"https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses={token_address}"
        else:
            url = f"https://api.gopluslabs.io/api/v1/token_security/{goplus_chain}?contract_addresses={token_address}"
        r = requests.get(url, timeout=8)
        if not r.ok:
            return False
        data = r.json().get("result", {})
        info = data.get(token_address.lower()) or data.get(token_address) or {}
        if not info:
            return False
        if str(info.get("is_honeypot", "0")) == "1":
            return True
        if str(info.get("cannot_sell_all", "0")) == "1":
            return True
        if str(info.get("is_blacklisted", "0")) == "1":
            return True
        sell_tax = float(info.get("sell_tax", 0) or 0)
        if sell_tax > 0.10:
            return True
        return False
    except:
        return False

def fetch(chain):
    try:
        r = requests.get("https://api.dexscreener.com/token-boosts/top/v1", timeout=10)
        addrs = [b["tokenAddress"] for b in r.json() if b.get("chainId") == chain][:30]
        if not addrs: return []
        r2 = requests.get(f"https://api.dexscreener.com/tokens/v1/{chain}/{','.join(addrs)}", timeout=10)
        return r2.json() if r2.ok else []
    except: return []

try:
    seen = set(json.load(open(STATE_FILE)))
except:
    seen = set()

alerts = []
for chain in CHAINS:
    for p in fetch(chain):
        pid        = p.get("pairAddress", "")
        mcap       = p.get("marketCap") or p.get("fdv") or 0
        vol1h      = (p.get("volume") or {}).get("h1") or 0
        liq        = (p.get("liquidity") or {}).get("usd") or 0
        token_addr = (p.get("baseToken") or {}).get("address", "")

        if mcap < MCAP_MIN:   continue
        if vol1h < VOL1H_MIN: continue
        if liq < LIQ_MIN:     continue
        if pid in seen:       continue

        if is_honeypot(chain, token_addr):
            print(f"[跳过貔貅] {(p.get('baseToken') or {}).get('symbol')} on {chain}")
            continue
        time.sleep(0.3)

        seen.add(pid)
        sym  = (p.get("baseToken") or {}).get("symbol", "???")
        chg  = (p.get("priceChange") or {}).get("h1") or 0
        tag  = {"ethereum":"ETH","solana":"SOL","bsc":"BSC"}.get(chain, chain.upper())

        alerts.append(
            f"🔥 <b>新信号 [{tag}]</b>\n"
            f"代币：<b>${sym}</b>\n"
            f"市值：{fmt(mcap)}\n"
            f"1H成交额：{fmt(vol1h)}\n"
            f"流动性：{fmt(liq)}\n"
            f"1H涨跌：{'🟢+' if chg>=0 else '🔴'}{chg:.1f}%\n"
            f"✅ 貔貅检测：通过\n"
            f"🔗 <a href='{p.get('url','#')}'>DEX Screener</a>"
        )

for msg in alerts:
    send_tg(msg)
    time.sleep(0.5)

json.dump(list(seen)[-500:], open(STATE_FILE, "w"))
print(f"完成，新信号 {len(alerts)} 个")

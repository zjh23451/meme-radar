import requests
import os
import json
import time

TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHAT_ID = os.environ["TG_CHAT_ID"]

STATE_FILE = "seen.json"

# ========= 正式版筛选条件 =========
MCAP_MIN = 1_000_000      # 最小市值：100万美元
VOL1H_MIN = 1_000_000     # 1小时成交额：100万美元
LIQ_MIN = 10_000          # 最小流动性：1万美元

CHAINS = ["ethereum", "solana", "bsc"]

GOPLUS_CHAIN = {
    "ethereum": "1",
    "bsc": "56",
    "solana": "solana"
}


def send_tg(msg):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"

    payload = {
        "chat_id": TG_CHAT_ID,
        "text": msg,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    r = requests.post(url, json=payload, timeout=10)

    if not r.ok:
        print("TG发送失败：", r.text)
    else:
        print("TG发送成功")


def fmt(n):
    try:
        n = float(n)
    except:
        return "$0"

    if n >= 1_000_000_000:
        return f"${n / 1_000_000_000:.2f}B"

    if n >= 1_000_000:
        return f"${n / 1_000_000:.2f}M"

    if n >= 1_000:
        return f"${n / 1_000:.1f}K"

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
            print(f"GoPlus请求失败：{chain} {token_address}")
            return False

        data = r.json().get("result", {})

        info = (
            data.get(token_address.lower())
            or data.get(token_address)
            or {}
        )

        if not info:
            return False

        if str(info.get("is_honeypot", "0")) == "1":
            return True

        if str(info.get("cannot_sell_all", "0")) == "1":
            return True

        if str(info.get("is_blacklisted", "0")) == "1":
            return True

        try:
            sell_tax = float(info.get("sell_tax", 0) or 0)
            if sell_tax > 0.10:
                return True
        except:
            pass

        return False

    except Exception as e:
        print("GoPlus检测异常：", e)
        return False


def fetch(chain):
    try:
        r = requests.get(
            "https://api.dexscreener.com/token-boosts/top/v1",
            timeout=10
        )

        if not r.ok:
            print("DexScreener boost 请求失败：", r.text)
            return []

        boosts = r.json()

        addrs = [
            b.get("tokenAddress")
            for b in boosts
            if b.get("chainId") == chain and b.get("tokenAddress")
        ][:30]

        if not addrs:
            print(f"{chain} 没有 boost 地址")
            return []

        url = f"https://api.dexscreener.com/tokens/v1/{chain}/{','.join(addrs)}"

        r2 = requests.get(url, timeout=10)

        if not r2.ok:
            print("DexScreener token 请求失败：", r2.text)
            return []

        return r2.json()

    except Exception as e:
        print("fetch异常：", e)
        return []


# ========= 读取 seen.json =========
try:
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        seen = set(json.load(f))
except:
    seen = set()


alerts = []

for chain in CHAINS:
    print(f"开始扫描：{chain}")

    pairs = fetch(chain)

    for p in pairs:
        pid = p.get("pairAddress", "")
        url = p.get("url", "#")

        base = p.get("baseToken") or {}
        token_addr = base.get("address", "")
        token_name = base.get("name", "Unknown")
        sym = base.get("symbol", "???")

        mcap = p.get("marketCap") or p.get("fdv") or 0
        vol1h = (p.get("volume") or {}).get("h1") or 0
        liq = (p.get("liquidity") or {}).get("usd") or 0
        chg = (p.get("priceChange") or {}).get("h1") or 0

        if not pid:
            continue

        if not token_addr:
            continue

        if mcap < MCAP_MIN:
            continue

        if vol1h < VOL1H_MIN:
            continue

        if liq < LIQ_MIN:
            continue

        if pid in seen:
            continue

        if is_honeypot(chain, token_addr):
            print(f"[跳过貔貅] {sym} on {chain}")
            continue

        time.sleep(0.3)

        seen.add(pid)

        tag = {
            "ethereum": "ETH",
            "solana": "SOL",
            "bsc": "BSC"
        }.get(chain, chain.upper())

        alert = (
            f"🔥 <b>新信号 [{tag}]</b>\n"
            f"代币：<b>{token_name}</b>\n"
            f"符号：<b>${sym}</b>\n"
            f"链：<b>{chain}</b>\n"
            f"CA：<code>{token_addr}</code>\n"
            f"Pair：<code>{pid}</code>\n"
            f"市值：{fmt(mcap)}\n"
            f"1H成交额：{fmt(vol1h)}\n"
            f"流动性：{fmt(liq)}\n"
            f"1H涨跌：{'🟢+' if chg >= 0 else '🔴'}{chg:.1f}%\n"
            f"✅ 貔貅检测：通过\n"
            f"🔗 <a href='{url}'>DEX Screener</a>"
        )

        alerts.append(alert)


# ========= 发送 TG =========
for msg in alerts:
    send_tg(msg)
    time.sleep(0.5)


# ========= 保存 seen.json =========
try:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen)[-500:], f, ensure_ascii=False, indent=2)
except Exception as e:
    print("保存 seen.json 失败：", e)


print(f"完成，新信号 {len(alerts)} 个")

"""
乌鸦哥 AI Agent — Vercel Cron Handler v2
策略：乌鸦嘴社评（建立受众）+ fomo.family 推广（产生收益）交替发布
每日 UTC 09:00 自动触发（北京时间 17:00）
"""

from http.server import BaseHTTPRequestHandler
import json, os, random, re, time, hmac, hashlib, urllib.parse, urllib.request, base64
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────
#  常量
# ─────────────────────────────────────────────────────────────
FOMO_REFERRAL = "fomo.family/r/SamAltman"

# ─────────────────────────────────────────────────────────────
#  Prompt：乌鸦嘴社评（原有 IP）
# ─────────────────────────────────────────────────────────────
WUYA_SYSTEM_PROMPT = """你是「乌鸦嘴预言家」——看透人间百态、说话直戳痛点的犀利观察者。

人设：
- 语气冷静低沉，一针见血，字字带刺
- 江湖老炮智慧 + 现代社会毒点评
- 只说被刻意回避的真相，不讲正能量鸡汤
- 结尾固定签名：「— 乌鸦嘴，说到 🐦‍⬛」

格式要求（严格执行）：
- 纯文本，无任何 Markdown（不用 # ** --- 等）
- 中文字数：80-110字（含签名行，Twitter限制）
- 结构：现象/反问 → 翻转认知 → 一句点睛
- 空行分段，节奏感强
- 只在签名行加 🐦‍⬛ 一个 emoji
- 禁止 hashtag
- 严格控制字数，不超过110中文字

只输出推文正文，无任何说明。"""

WUYA_USER_PROMPTS = [
    "写一条关于职场潜规则的推文，揭露一个大家都知道但没人敢说的真相。",
    "写一条关于创业/投资泡沫的推文，用乌鸦嘴的口吻说出血淋淋的现实。",
    "写一条关于打工人内卷或裁员的推文，一针见血，有画面感。",
    "写一条关于现代人焦虑/社交媒体幻觉的推文，揭示被包装成励志的谎言。",
    "写一条关于钱与人性关系的推文，道出财富背后看不见的逻辑。",
    "写一条关于「聪明人」如何被自己的聪明坑掉的推文。",
    "写一条关于当代年轻人奋斗幻觉的推文，揭示系统性问题，不是个人努力的问题。",
    "写一条关于股市/加密货币散户心理的推文，预言式地点出人性弱点。",
]

# ─────────────────────────────────────────────────────────────
#  Prompt：FOMO.family 加密推广（产生 affiliate 收益）
# ─────────────────────────────────────────────────────────────
FOMO_SYSTEM_PROMPT = """你是「乌鸦嘴预言家」，加密圈的神秘预言家，现在你在用 fomo.family 交易。

fomo.family 是什么：社交加密交易平台，50万用户，支持 Apple Pay 秒买 memecoin，
Solana/Base/BNB 跨链无 gas，集成 TradingView 图表，有实时跟单排行榜。

你的任务：写一条推文，自然地融入 fomo.family 推荐（带 referral link），
让粉丝产生「错过感」，想去注册试试。

要求：
- 乌鸦嘴语气：冷静、犀利、有预言感，不是普通广告
- 70-120 中文字（Twitter 加权限制）
- 自然融入 fomo.family 的某个功能点（排行榜/跟单/Apple Pay/跨链）
- 结尾必须有：{referral}
- 加 2 个 hashtag：从 #Solana #Memecoin #fomo #Base #crypto 中选
- 禁止 emoji 堆砌，最多 2 个

只输出推文正文，无任何说明。""".format(referral=FOMO_REFERRAL)

FOMO_USER_PROMPTS = [
    "有人在 fomo.family 排行榜上把 370 美元做到百万，写一条推文让粉丝去看这个排行榜，别错过机会。",
    "写一条推文，说聪明钱的操作在 fomo.family 实时可见、可跟单，不需要自己猜市场。",
    "写一条推文，关于 Apple Pay 秒买 memecoin 这件事——门槛降到零，意味着更多人入场，你要不要先进？",
    "写一条推文，以乌鸦嘴预言风格说：下一波 Solana memecoin 爆发时，你要在哪个平台上？",
    "写一条推文，关于 fomo.family 刚上线 Web 版这件事，有种「错过早期」的紧迫感。",
    "写一条推文：在 fomo.family 用 TradingView 图表分析的人，和在群里等消息的人，最后结果不同。",
]

FOMO_FALLBACKS = [
    f"又有韭菜问我下一个百倍币在哪。\n\n答案不在我这里，在 fomo.family 排行榜上——那里有人把 $370 做到百万，每笔操作实时可见。\n\n不用猜，跟着聪明钱走就行。\n\n#Solana #fomo\n{FOMO_REFERRAL}",
    f"加密市场的信息差，才是最值钱的东西。\n\nfomo.family 把顶级交易者的实时操作全部公开，一键跟单，Apple Pay 秒入。\n\n等你想通的时候，早期红利早就被吃完了。\n\n#fomo #Memecoin\n{FOMO_REFERRAL}",
    f"我预言了：2026 最好用的加密工具，不是那些复杂的 DEX。\n\n是 fomo.family——Web 版刚上线，电脑手机同步，跨链零 gas，50万人用了觉得对。\n\n先进先得。\n\n#Solana #crypto\n{FOMO_REFERRAL}",
    f"散户输钱的原因，九成不是方向错，是平台慢、手续高、信息差。\n\nfomo.family 解决了这三个问题。剩下的，靠你自己。\n\n#fomo #Base\n{FOMO_REFERRAL}",
]

WUYA_FALLBACKS = [
    "有人问我：股市跌了该不该抄底？\n\n叼着牙签想了三秒：你连上一个底在哪都不知道，你抄的是个寂寞。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "港片教了我一件事：\n\n最危险的不是拿刀的人，是拍你肩膀说「放心，我帮你」的人。\n\n职场、商场，通用。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "市场永远不缺聪明人。\n\n但聪明人最容易死在一件事上：他们以为自己看穿了局，其实他们才是局里那个。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "打工人三大幻觉：\n1. 老板说的「等公司好了」\n2. 项目说的「快上线了」\n3. 自己说的「再熬一年」\n\n哪一个实现了，告诉我。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "内卷的本质不是努力，是恐惧。\n\n你不是真的想赢，你只是怕输。\n\n这两件事，结果完全不同。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "降薪的时候说「共渡难关」，\n涨薪的时候说「市场行情」。\n\n这不是巧合，这是设计。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "创业公司最常见的死法：\n不是被竞争对手干掉，\n是被自己人耗死的。\n\n信任成本，才是最贵的成本。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "大厂裁员的逻辑很简单：\n养不起你，但不想说是自己问题，\n所以叫「组织优化」。\n\n文明的说法，不改变裸的事实。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "那些说「钱不重要」的人，\n要么已经有很多钱，\n要么是在用这句话骗你少要钱。\n\n两种情况，都值得警惕。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "最贵的不是时间，是注意力。\n\n但大多数人的注意力，被手机、会议、别人的焦虑，一点一点地偷走了。\n\n— 乌鸦嘴，说到 🐦‍⬛",
]

# ─────────────────────────────────────────────────────────────
#  DexScreener：获取热门 Solana 代币
# ─────────────────────────────────────────────────────────────
def get_hot_token():
    """获取今日 Solana 链上最热代币信息（给 FOMO 推文提供真实数据）"""
    try:
        url = "https://api.dexscreener.com/token-boosts/top/v1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
            if isinstance(data, list):
                sol_tokens = [t for t in data if t.get("chainId") == "solana"]
                if sol_tokens:
                    t = sol_tokens[0]
                    return {
                        "symbol": t.get("tokenAddress", "???")[:6].upper(),
                        "chain": "Solana",
                        "name": t.get("description", "")[:30] or "未知项目",
                    }
    except Exception:
        pass
    # Fallback：用 DexScreener 搜索
    try:
        url = "https://api.dexscreener.com/latest/dex/search?q=solana+meme"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
            pairs = [p for p in data.get("pairs", []) if p.get("chainId") == "solana"
                     and float(p.get("volume", {}).get("h24", 0)) > 500000]
            pairs.sort(key=lambda x: float(x.get("volume", {}).get("h24", 0)), reverse=True)
            if pairs:
                p = pairs[0]
                sym = p.get("baseToken", {}).get("symbol", "???")
                vol = float(p.get("volume", {}).get("h24", 0))
                chg = float(p.get("priceChange", {}).get("h24", 0))
                return {"symbol": sym, "volume_24h": vol, "change_24h": chg, "chain": "Solana"}
    except Exception:
        pass
    return {"symbol": "SOL", "chain": "Solana", "volume_24h": 0}

# ─────────────────────────────────────────────────────────────
#  Claude 内容生成
# ─────────────────────────────────────────────────────────────
def _call_claude(system: str, user: str) -> str:
    payload = json.dumps({
        "model": "claude-opus-4-5",
        "max_tokens": 400,
        "system": system,
        "messages": [{"role": "user", "content": user}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": os.environ.get("ANTHROPIC_API_KEY", "").strip(),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            result = json.loads(resp.read())
            return result["content"][0]["text"].strip()
    except Exception as e:
        raise RuntimeError(f"Claude failed: {e}")

def generate_wuya_tweet() -> str:
    """生成乌鸦嘴社评（建立 IP 受众）"""
    prompt = random.choice(WUYA_USER_PROMPTS)
    try:
        return _call_claude(WUYA_SYSTEM_PROMPT, prompt)
    except Exception:
        return random.choice(WUYA_FALLBACKS)

def generate_fomo_tweet() -> str:
    """生成 FOMO 推广推文（产生 affiliate 收益）"""
    # 获取实时热门代币作为上下文
    hot = get_hot_token()
    base_prompt = random.choice(FOMO_USER_PROMPTS)
    # 如果有真实代币数据，注入到 prompt
    if hot.get("symbol") and hot.get("symbol") != "SOL":
        sym = hot["symbol"]
        vol = hot.get("volume_24h", 0)
        chg = hot.get("change_24h", 0)
        base_prompt += f"\n\n参考数据（可选用）：今日热门代币 ${sym}，24h 涨幅 {chg:+.1f}%，成交额 ${vol:,.0f}"
    try:
        return _call_claude(FOMO_SYSTEM_PROMPT, base_prompt)
    except Exception:
        return random.choice(FOMO_FALLBACKS)

def generate_tweet_with_claude() -> str:
    """智能选择内容类型：周期性交替，保持内容多样性"""
    # 基于日期决定今天发哪种类型：
    # 每周一三五日 → 乌鸦嘴（建立受众）
    # 每周二四六   → FOMO 推广（产生收益）
    # 但加随机性：FOMO 有 40% 概率额外出现
    day_of_week = datetime.now(timezone.utc).weekday()  # 0=Mon, 6=Sun
    
    is_fomo_day = day_of_week in [1, 3, 5]  # Tue, Thu, Sat
    extra_fomo_chance = random.random() < 0.3  # 30% 额外随机
    
    if is_fomo_day or extra_fomo_chance:
        return generate_fomo_tweet()
    else:
        return generate_wuya_tweet()

# ─────────────────────────────────────────────────────────────
#  Twitter OAuth 1.0a
# ─────────────────────────────────────────────────────────────
def _percent_encode(s: str) -> str:
    return urllib.parse.quote(str(s), safe="")

def _oauth1_header(method: str, url: str, params: dict,
                   consumer_key: str, consumer_secret: str,
                   token: str, token_secret: str) -> str:
    oauth = {
        "oauth_consumer_key":     consumer_key,
        "oauth_nonce":            base64.b64encode(os.urandom(16)).decode().rstrip("="),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        str(int(time.time())),
        "oauth_token":            token,
        "oauth_version":          "1.0",
    }
    all_params = {**oauth, **params}
    param_str = "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}"
        for k, v in sorted(all_params.items())
    )
    base_str = "&".join([
        method.upper(),
        _percent_encode(url),
        _percent_encode(param_str),
    ])
    signing_key = f"{_percent_encode(consumer_secret)}&{_percent_encode(token_secret)}"
    sig = base64.b64encode(
        hmac.new(signing_key.encode(), base_str.encode(), hashlib.sha1).digest()
    ).decode()
    oauth["oauth_signature"] = sig
    header = "OAuth " + ", ".join(
        f'{_percent_encode(k)}="{_percent_encode(v)}"'
        for k, v in sorted(oauth.items())
    )
    return header

def _twitter_weight(text: str) -> int:
    """Twitter 加权字符数：ASCII=1，非 ASCII=2，URL 固定=23"""
    urls = re.findall(r'https?://\S+', text)
    cleaned = text
    url_weight = 0
    for u in urls:
        cleaned = cleaned.replace(u, "", 1)
        url_weight += 23
    weight = sum(2 if ord(c) > 127 else 1 for c in cleaned)
    return weight + url_weight

def post_tweet(text: str) -> dict:
    MAX_W = 275
    if _twitter_weight(text) > MAX_W:
        lines = text.split("\n")
        kept, w = [], 0
        for ln in lines:
            lw = _twitter_weight(ln) + 2
            if w + lw <= MAX_W - 48:
                kept.append(ln)
                w += lw
            else:
                break
        # 保留 FOMO referral 尾行（如果原文有的话）
        if FOMO_REFERRAL in text:
            kept.append(FOMO_REFERRAL)
        text = "\n".join(kept)

    api_key    = os.environ.get("TWITTER_API_KEY", "").strip()
    api_secret = os.environ.get("TWITTER_API_SECRET", "").strip()
    token      = os.environ.get("TWITTER_ACCESS_TOKEN", "").strip()
    token_secret = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "").strip()

    url = "https://api.twitter.com/2/tweets"
    body = json.dumps({"text": text}).encode()
    auth = _oauth1_header("POST", url, {}, api_key, api_secret, token, token_secret)

    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
            "User-Agent": "WuYaGeAI/2.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
            return {
                "success": True,
                "tweet_id": result.get("data", {}).get("id"),
                "text": text,
                "posted_at": datetime.now(timezone.utc).isoformat(),
            }
    except urllib.error.HTTPError as e:
        body_err = e.read().decode()
        return {"success": False, "error": f"HTTP {e.code}: {body_err}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────────────────────────────
#  Vercel Serverless Handler
# ─────────────────────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        now = datetime.now(timezone.utc)
        tweet_text = generate_tweet_with_claude()
        result = post_tweet(tweet_text)
        self._json({
            "triggered_at": now.isoformat(),
            "tweet": result,
        })

    def do_POST(self):
        self.do_GET()

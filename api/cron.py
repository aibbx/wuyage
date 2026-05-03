"""
乌鸦哥 AI Agent — Vercel Cron Handler v3
策略：乌鸦嘴社评（建立受众）+ fomo.family 推广（产生收益）
3:1 比例交替 — 每3条社评穿插1条 FOMO 推广
每日 UTC 09:00 自动触发（北京时间 17:00）
"""

from http.server import BaseHTTPRequestHandler
import json, os, random, re, time, urllib.parse, urllib.request
from datetime import datetime, timezone

FOMO_REFERRAL = "https://fomo.family/r/SamAltman"

# ─────────────────────────────────────────────────────────────
#  乌鸦嘴 Prompt — 12个不同方向，每次随机选一个避免重复
# ─────────────────────────────────────────────────────────────
WUYA_SYSTEM = """你是「乌鸦嘴预言家」——港片老炮加网络毒舌合体，专说没人敢说的真相。

文风特征：
• 开头用一个具体的场景/对话/数字切入，不说废话
• 中间翻转：表面看X，其实是Y
• 结尾一句话点杀，让人发出"妈的说得对"
• 语气：冷静、讽刺、带一点江湖残忍感
• 签名固定：「— 乌鸦嘴，说到 🐦‍⬛」

格式硬性规定：
• 纯文字，无 Markdown，无 hashtag，无多余emoji
• 只有签名行有 🐦‍⬛
• 中文字数 75-105字（含签名），严格不超过110字
• 分2-3段，每段1-3句，节奏干净利落

只输出推文正文。"""

# 12个主题方向 — 轮换选取，避免重复
WUYA_TOPICS = [
    # 职场 / 打工
    "今天写职场话题。一个打工人最终明白：公司不是家，但你付出的是家人的代价。要有具体场景（如绩效/升职/加班），要有翻转，结尾一刀。",
    "今天写裁员话题。裁员通知、HR话术、「我们会支持你」——用犀利视角拆穿这套语言系统背后的冷血逻辑。要有画面感。",
    "今天写职场潜规则。写一个「聪明人明白但新人不知道」的职场生存真相，越具体越好，要有反差感。",
    # 钱 / 投资
    "今天写韭菜心理话题。写散户/普通投资者最经典的一种自我欺骗行为，用乌鸦嘴的预言风格，要有具体数字或场景。",
    "今天写财富与认知的关系。穷人和富人对同一件事的理解有什么本质差异？不是鸡汤，是解剖，要残忍，要真实。",
    "今天写创业泡沫话题。一个创业者/投资人说过的最冠冕堂皇的谎言，用乌鸦嘴视角还原真相。要有具体细节。",
    # 人性 / 社会
    "今天写「信息茧房/社交媒体幻觉」话题。人们在刷手机时看到的「成功」和「真实」之间的差距，一刀见血的方式说出来。",
    "今天写「聪明人如何被聪明坑死」话题。一个具体的认知陷阱，越多聪明人踩越好，越反直觉越好。",
    "今天写「努力的幻觉」话题。你以为在努力，其实你只是在忙——用一个很具体的例子区分真努力和假努力。",
    # 关系 / 人际
    "今天写「信任」话题，但要换一个角度：不写被辜负，写「信任是怎么被日常小事慢慢吃掉的」，要有画面感。避开说教。",
    "今天写「讨好型人格」话题。说出讨好者从来不承认但深夜清醒时自己知道的那个真相。越扎心越好，不说教。",
    # 时代 / 大势
    "今天写「年轻人为什么越来越不结婚/不生育」这件事，不讲道理，用乌鸦嘴视角说出那个没人承认的根本原因。",
]

WUYA_FALLBACKS = [
    "有人问我：为什么努力了还是赚不到钱？\n\n你努力的方向，是让老板放心，不是让市场付钱。\n这是两件事。\n\n大多数人一辈子没搞清楚。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "裁员通知永远这么写：「感谢你的贡献，公司艰难时期……」\n\n翻译一下：你的价值已经被榨完了，我们不想再付钱养你。\n\n「感谢」两个字是给你脸，不是给你钱。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "股市里亏钱最快的方式：\n不是不懂技术面，是太懂自己的「感觉」。\n\n你感觉要涨，你感觉是底部，你感觉这次不一样。\n\n市场最喜欢有感觉的人。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "老板说：「我把你当自己人。」\n\n自己人的意思是：\n可以多干，可以少拿，出了事可以顶锅。\n\n听到这句话，谈钱。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "大多数人的焦虑，不是真的怕失败，是怕别人看见自己失败。\n\n这两种恐惧，解法完全不同。\n搞混了，就永远在解错题。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "「再熬一年就好了。」\n\n你三年前也是这么说的。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "聪明人最危险的习惯：\n用智商给自己的错误找理由。\n\n普通人是认错，聪明人是辩解——越聪明越拖得久，越拖越难看。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "所有说「钱不是最重要的人」，要么已经有够多的钱，要么在用这句话让你接受更少的钱。\n\n没有第三种。\n\n— 乌鸦嘴，说到 🐦‍⬛",
]

# ─────────────────────────────────────────────────────────────
#  FOMO.family Prompt — 自然融入，不像广告
# ─────────────────────────────────────────────────────────────
FOMO_SYSTEM = f"""你是「乌鸦嘴预言家」，最近在用 fomo.family 做加密交易。

fomo.family 核心卖点：
• 50万用户的社交加密平台（Solana/Base/BNB 三链）
• 顶级交易者实时操作全公开，一键跟单
• Apple Pay 秒买 memecoin，零门槛进场
• 内置 TradingView 图表，跨链零 gas
• 有人从 $370 做到百万美元（排行榜可验证）
• Referral link：{FOMO_REFERRAL}

写一条推文：
• 乌鸦嘴语气——冷静、有预言感、不是广告腔
• 用「错过感」和「聪明人早就进了」的暗示
• 自然带出 fomo.family 的一个具体功能
• 结尾必须有 referral link：{FOMO_REFERRAL}
• 加 1-2 个 hashtag，从 #Solana #fomo #Memecoin #Base #crypto 中选
• 70-110 中文字（不含链接），最多 2 个 emoji
• 无 Markdown，纯文字

只输出推文正文，无任何说明。"""

FOMO_ANGLES = [
    "写关于：你不上排行榜跟单，凭什么赢？散户靠感觉，聪明钱靠数据——在 fomo.family 上，差距一目了然。",
    "写关于：Apple Pay 买 memecoin 这件事的意义——门槛低到零意味着更多新韭菜涌入，你要不要在他们前面？",
    "写关于：信息差才是加密市场最值钱的东西。fomo.family 把顶级玩家的实时操作全部公开了，用了才知道自己之前多盲。",
    "写关于：2026 年还在用 DEX 手动操作的人——和用 fomo.family 一键跟单的人，六个月后会是两种命运。",
    "写关于：fomo.family 排行榜上有人从 $370 做到百万——这不是 KOL 吹牛，链上数据可查，让粉丝自己去验证。",
    "写关于：跨链零 gas 这件事的本质——平台把钱省下来，是让你多买一点，还是让平台多赚一点？fomo.family 的逻辑是前者。",
]

FOMO_FALLBACKS = [
    f"韭菜和玩家的区别，不是智商，是信息。\n\n顶级交易者怎么操作，fomo.family 上实时看得到，一键跟单。\n你不知道，不代表没人知道。\n\n#Solana #fomo\n{FOMO_REFERRAL}",
    f"有人把 $370 做到了百万。不是传说，是 fomo.family 排行榜上的链上记录。\n\n聪明钱早进了。你在等什么信号？\n\n#Memecoin #fomo\n{FOMO_REFERRAL}",
    f"Apple Pay 买 Solana memecoin，10秒到账，零门槛。\n\n门槛越低，韭菜越多，先进去的人越赚。\n逻辑很简单，动不动是你的事。\n\n#Solana #crypto\n{FOMO_REFERRAL}",
    f"还在手动搜 DEX、付高 gas 的人：\nfomo.family 三链跨链零 gas，TradingView 图表内置，省的是钱，不是时间。\n\n#Base #Solana\n{FOMO_REFERRAL}",
]

# ─────────────────────────────────────────────────────────────
#  获取热门 Solana 代币（可选，丰富 FOMO 推文素材）
# ─────────────────────────────────────────────────────────────
def get_hot_token():
    try:
        url = "https://api.dexscreener.com/token-boosts/top/v1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read())
            if isinstance(data, list):
                sol_tokens = [t for t in data if t.get("chainId") == "solana"]
                if sol_tokens:
                    t = sol_tokens[0]
                    sym = (t.get("tokenAddress") or "??")[:6].upper()
                    return {"symbol": f"${sym}", "chain": "Solana"}
    except Exception:
        pass
    samples = ["$BONK", "$WIF", "$POPCAT", "$MEW", "$BOME"]
    return {"symbol": random.choice(samples), "chain": "Solana"}

# ─────────────────────────────────────────────────────────────
#  Claude 内容生成
# ─────────────────────────────────────────────────────────────
def call_claude(system_prompt: str, user_prompt: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ""
    payload = json.dumps({
        "model": "claude-haiku-4-5",
        "max_tokens": 300,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            result = json.loads(resp.read())
            return result["content"][0]["text"].strip()
    except Exception as e:
        print(f"Claude error: {e}")
        return ""

# ─────────────────────────────────────────────────────────────
#  推文字数校验（Twitter 加权：中文=2, ASCII=1）
# ─────────────────────────────────────────────────────────────
def weighted_len(text: str) -> int:
    return sum(2 if ord(c) > 127 else 1 for c in text)

def trim_tweet(text: str, limit: int = 270) -> str:
    if weighted_len(text) <= limit:
        return text
    # 找签名行并保留
    lines = text.split("\n")
    sig_line = ""
    for i, l in enumerate(lines):
        if "乌鸦嘴" in l or "🐦" in l:
            sig_line = "\n" + "\n".join(lines[i:])
            lines = lines[:i]
            break
    body = "\n".join(lines)
    while weighted_len(body + sig_line) > limit - 3 and body:
        # 按句截断
        for sep in ["。", "！", "？", "…", "，", " "]:
            idx = body.rfind(sep)
            if idx > 10:
                body = body[:idx + 1]
                break
        else:
            body = body[:-5]
    return (body + "…" + sig_line).strip()

# ─────────────────────────────────────────────────────────────
#  决策：今天发乌鸦嘴还是 FOMO？（3:1 轮换，基于日期）
# ─────────────────────────────────────────────────────────────
def should_post_fomo(day_of_year: int) -> bool:
    # 每4天发一次 FOMO（第4天），其余发乌鸦嘴
    return day_of_year % 4 == 0

# ─────────────────────────────────────────────────────────────
#  生成推文
# ─────────────────────────────────────────────────────────────
def generate_tweet(is_fomo: bool) -> str:
    if is_fomo:
        token = get_hot_token()
        angle = random.choice(FOMO_ANGLES)
        # 把热门代币信息注入 prompt
        user_prompt = f"{angle}\n\n今日热门代币参考（可用可不用）：{token['symbol']}（{token['chain']}链）"
        text = call_claude(FOMO_SYSTEM, user_prompt)
        if text and 40 < weighted_len(text) < 560:
            return trim_tweet(text)
        return FOMO_FALLBACKS[(seed+1) % len(FOMO_FALLBACKS)]
    else:
        # 基于当前时间的哈希选一个话题方向，保证不重复
        seed = int(time.time()) // 86400  # 每天一个种子
        topic_idx = seed % len(WUYA_TOPICS)
        topic = WUYA_TOPICS[topic_idx]
        text = call_claude(WUYA_SYSTEM, topic)
        if text and 40 < weighted_len(text) < 560:
            return trim_tweet(text)
        return WUYA_FALLBACKS[seed % len(WUYA_FALLBACKS)]

# ─────────────────────────────────────────────────────────────
#  Twitter OAuth 1.0a 发推
# ─────────────────────────────────────────────────────────────
def post_tweet(text: str) -> dict:
    import hmac, hashlib, base64

    api_key    = os.environ.get("TWITTER_API_KEY", "").strip()
    api_secret = os.environ.get("TWITTER_API_SECRET", "").strip()
    acc_token  = os.environ.get("TWITTER_ACCESS_TOKEN", "").strip()
    acc_secret = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "").strip()

    if not all([api_key, api_secret, acc_token, acc_secret]):
        return {"success": False, "error": "Missing Twitter credentials"}

    url = "https://api.twitter.com/2/tweets"
    body = json.dumps({"text": text}).encode("utf-8")

    ts    = str(int(time.time()))
    nonce = base64.b64encode(os.urandom(16)).decode().rstrip("=")

    params = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": ts,
        "oauth_token": acc_token,
        "oauth_version": "1.0",
    }

    # 签名基础字符串
    param_str = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(params.items())
    )
    base_str = "&".join([
        "POST",
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(param_str, safe=""),
    ])
    signing_key = f"{urllib.parse.quote(api_secret, safe='')}&{urllib.parse.quote(acc_secret, safe='')}"
    sig = base64.b64encode(
        hmac.new(signing_key.encode(), base_str.encode(), hashlib.sha1).digest()
    ).decode()

    params["oauth_signature"] = sig
    auth_header = "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(params.items())
    )

    req = urllib.request.Request(
        url, data=body,
        headers={
            "Authorization": auth_header,
            "Content-Type": "application/json",
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            tid = result.get("data", {}).get("id", "")
            return {
                "success": True,
                "tweet_id": tid,
                "url": f"https://x.com/WuYaGeAI/status/{tid}",
                "content": text,
                "weighted_chars": weighted_len(text),
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
        now     = datetime.now(timezone.utc)
        day_num = now.timetuple().tm_yday
        is_fomo = should_post_fomo(day_num)

        tweet_text = generate_tweet(is_fomo)
        result     = post_tweet(tweet_text)

        self._json({
            "triggered_at": now.isoformat(),
            "mode": "fomo" if is_fomo else "wuya",
            "day_of_year": day_num,
            "tweet": result,
        })

    def do_POST(self):
        self.do_GET()

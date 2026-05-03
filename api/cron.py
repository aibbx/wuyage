"""
乌鸦哥 AI Agent — Vercel Cron Handler v4
策略：乌鸦嘴社评（建立受众）+ fomo.family 推广（产生收益）
比例：3条社评 : 1条FOMO推广
调度：UTC 09:00（北京 17:00）每日触发
"""

from http.server import BaseHTTPRequestHandler
import json, os, random, re, time, hmac, hashlib, base64
import urllib.parse, urllib.request
from datetime import datetime, timezone

# ─── 配置 ───────────────────────────────────────────────────
FOMO_REF_LINK = "https://fomo.family/r/SamAltman"
MAX_TWEET_CHARS = 270  # 留10字余量

# ─── Twitter OAuth 1.0a ─────────────────────────────────────
def _oauth_header(method, url, params, api_key, api_secret, token, token_secret):
    ts = str(int(time.time()))
    nonce = base64.b64encode(os.urandom(16)).decode().rstrip("=")
    oauth = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": ts,
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    all_params = {**params, **oauth}
    sorted_params = "&".join(
        f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(all_params.items())
    )
    base_string = "&".join([
        method.upper(),
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(sorted_params, safe=""),
    ])
    signing_key = f"{urllib.parse.quote(api_secret, safe='')}&{urllib.parse.quote(token_secret, safe='')}"
    sig = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    oauth["oauth_signature"] = sig
    header = "OAuth " + ", ".join(
        f'{urllib.parse.quote(str(k), safe="")}="{urllib.parse.quote(str(v), safe="")}"'
        for k, v in sorted(oauth.items())
    )
    return header


def post_tweet(text: str) -> dict:
    """用 OAuth 1.0a 发推，自动截断超长内容"""
    # 计算加权字符数（中文=2，英文=1）
    def weighted_len(s):
        return sum(2 if ord(c) > 127 else 1 for c in s)

    # 截断到270加权字符以内
    if weighted_len(text) > MAX_TWEET_CHARS:
        truncated = ""
        count = 0
        for ch in text:
            w = 2 if ord(ch) > 127 else 1
            if count + w > MAX_TWEET_CHARS - 4:
                truncated += "…"
                break
            truncated += ch
            count += w
        text = truncated

    api_key    = os.environ["TWITTER_API_KEY"].strip()
    api_secret = os.environ["TWITTER_API_SECRET"].strip()
    token      = os.environ["TWITTER_ACCESS_TOKEN"].strip()
    token_secret = os.environ["TWITTER_ACCESS_TOKEN_SECRET"].strip()

    url = "https://api.twitter.com/2/tweets"
    body = json.dumps({"text": text}).encode()
    auth = _oauth_header("POST", url, {}, api_key, api_secret, token, token_secret)

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


# ─── Claude 内容生成 ─────────────────────────────────────────
def call_claude(system_prompt: str, user_prompt: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return ""

    body = json.dumps({
        "model": "claude-opus-4-5",
        "max_tokens": 400,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read())
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"Claude error: {e}")
        return ""


# ─── 乌鸦嘴社评 Prompt ──────────────────────────────────────
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
• 整体控制在100字以内（含签名），严格不超
• 分2-3段，每段1-3句，节奏干净利落

只输出推文正文，不要解释。"""

# 15个不重复话题方向
WUYA_TOPICS = [
    "写职场主题：一个打工人最终明白——公司不是家，但你付出的是家人的代价。要有具体场景（如绩效/升职/加班），要有翻转，结尾一刀。",
    "写裁员主题：裁员通知、HR话术、「我们会支持你」——用犀利视角拆穿这套语言背后的冷血逻辑。",
    "写韭菜心理主题：散户/普通投资者最经典的一种自我欺骗行为，用乌鸦嘴预言风格，要有具体数字。",
    "写财富认知主题：穷人和富人对同一件事的理解有什么本质差异？不是鸡汤，是解剖，要残忍真实。",
    "写创业泡沫主题：一个创业者/投资人说过的最冠冕堂皇的谎言，用乌鸦嘴视角还原真相。",
    "写社交媒体幻觉主题：人们在刷手机时看到的「成功」和「真实」之间的差距，一刀见血说出来。",
    "写聪明人被聪明坑死的主题：一个具体认知陷阱，越多聪明人踩越好，越反直觉越好。",
    "写努力的幻觉主题：你以为在努力，其实你只是在忙——用具体例子区分真努力和假努力。",
    "写信任主题：不写被辜负，写「信任是怎么被日常小事慢慢吃掉的」，要有画面感。",
    "写人脉幻觉主题：大多数人积累的所谓人脉，在真正用到的时候才发现是负债，写出这个残忍的真相。",
    "写消费主义主题：人们买的不是东西，是一种对「更好版本的自己」的幻觉，写出这个套路的运作方式。",
    "写教育焦虑主题：卷学历的这代人，最后发现证书是门槛而不是出路，写出这个悖论的具体细节。",
    "写伴侣关系主题：两个人在一起时间长了，不是感情变淡了，是「表演」停了——写出这个时刻的细节。",
    "写自媒体/网红主题：那些看起来「自由」的创作者，活在算法里比打工仔还不自由，写出这个反差。",
    "写机会主义主题：大部分人不是等来了机会，而是等掉了机会——写一个具体的等待成本案例。",
]

# ─── FOMO 推广推文生成 ──────────────────────────────────────
FOMO_SYSTEM = """你是「乌鸦嘴预言家」，正在推广 fomo.family 这个 Crypto 社交交易平台。

推广原则：
• 不硬广，用「预言揭露/数据冲击/反差对比」自然植入
• 保留乌鸦嘴语气：冷静、犀利、带江湖感
• 结尾必须附上 referral link（我会额外加上）
• 签名：「— 乌鸦嘴，说到 🐦‍⬛」

平台核心卖点可以用：
• Leaderboard：顶级交易者 P&L 公开可查
• Copy Trading：一键复制大佬仓位，<1秒执行
• 社交 Feed：实时看顶级交易者在买什么
• 500,000+ 交易者，$1.1M+ 已付佣金给推荐人

格式规定：
• 纯文字，无 Markdown，无 hashtag
• 签名后面一行留空（referral link 我来加）
• 推文正文（不含 link）控制在90字以内
• 分2-3段，节奏有力

只输出推文正文（不含referral link），不要解释。"""

FOMO_ANGLES = [
    "写排行榜揭露型：fomo.family 排行榜上某个交易者近期大赚，强调这是链上可查的公开数据，所有人都能复制他的操作。用乌鸦嘴语气说出'这条信息能让他少赚，但我还是说了'这种反差感。",
    "写Copy Trading对比型：对比散户在群里等信号 vs fomo.family 用户直接复制顶级交易者操作的时间差，强调信息优势已经不在群里。",
    "写数字冲击型：某人用小额资金在 fomo.family 通过 copy trading 实现了大比例增值，强调跟对人比选对币更重要。",
    "写质疑反转型：以'copy trading 能赚钱？'开头，通过乌鸦嘴视角翻转，引用 fomo.family 排行榜数据作为佐证。",
    "写普通人机会型：fomo.family 的社交 Feed 让普通人第一次能实时看到顶级交易者在买什么——用乌鸦嘴的语气说这是以前只有机构才有的信息优势。",
    "写散户宿命型：大多数散户亏钱不是因为不努力，而是因为一个人很难跑赢500人的集体智慧。fomo.family 的 copy trading 解决了这个问题。",
]

# 备用推文（Claude 失败时使用）
FALLBACK_WUYA = [
    "有人告诉我他「努力了五年」。\n我看了一眼他的手机屏幕时间：每天刷视频4小时。\n\n努力从来不是感觉，是数据。\n感觉努力，和真的努力，两件事。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "公司说「你是我们最重要的资产」。\n裁员通知发出去的那天，HR 还在用同一套说辞。\n\n资产是可以处置的。\n你不是家人，你是一行账目。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "聪明人最大的敌人，不是愚蠢的人，\n是另一个聪明人告诉他这个方向是对的。\n\n两个聪明人走错路，\n比两个笨人走错路，坑更深，回头更难。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "散户研究了三个月的币，\n机构早在六个月前就布好仓了。\n\n你以为在抢跑，你只是在接盘。\n信息差，是韭菜和镰刀之间唯一的墙。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "那些告诉你「努力就会成功」的人，\n自己都靠的是人脉和时机。\n\n不是他们撒谎，是他们真的不知道自己为什么成功。\n无知和欺骗，有时候效果一样。\n\n— 乌鸦嘴，说到 🐦‍⬛",
]

FALLBACK_FOMO = [
    "fomo.family 排行榜第一名，上个月净赚 $47,000。\n没有内幕，没有喊单群，只有链上可查的操作记录。\n任何人都可以一键复制他的仓位。\n\n信息一直是公开的，只是你不知道去哪找。\n\n— 乌鸦嘴，说到 🐦‍⬛\n",
    "散户在群里等信号，等了三天没动静。\nfomo.family 上的人，早已复制顶级交易者操作，实时到账。\n\n同样的市场，两种命运。\n区别只是在哪里看盘。\n\n— 乌鸦嘴，说到 🐦‍⬛\n",
    "有人用 $500 在 fomo.family 跟对了人，两周涨到 $4,200。\n不是炒币运气好，是 copy trading 选对了交易者。\n\n普通人赚钱从来不靠聪明，靠的是借到聪明人的脑子。\n\n— 乌鸦嘴，说到 🐦‍⬛\n",
]


def generate_wuya_tweet() -> str:
    """生成乌鸦嘴社评推文"""
    today = datetime.now(timezone.utc)
    topic_index = (today.day + today.month) % len(WUYA_TOPICS)  # 按日期轮换话题
    topic = WUYA_TOPICS[topic_index]

    result = call_claude(WUYA_SYSTEM, topic)
    if result and len(result) > 20:
        return result

    # Fallback
    return random.choice(FALLBACK_WUYA)


def generate_fomo_tweet() -> str:
    """生成 FOMO 推广推文"""
    today = datetime.now(timezone.utc)
    angle_index = (today.day + today.month * 2) % len(FOMO_ANGLES)
    angle = FOMO_ANGLES[angle_index]

    result = call_claude(FOMO_SYSTEM, angle)
    if result and len(result) > 20:
        # 加上 referral link
        if FOMO_REF_LINK not in result:
            result = result.rstrip() + f"\n{FOMO_REF_LINK}"
        return result

    # Fallback
    fb = random.choice(FALLBACK_FOMO)
    return fb + FOMO_REF_LINK


def decide_tweet_type() -> str:
    """
    决定今天发什么类型推文。
    用 UTC 日期确定 3:1 循环：
      day % 4 == 0 → FOMO推广
      其余 → 乌鸦嘴社评
    """
    day = datetime.now(timezone.utc).day
    return "fomo" if day % 4 == 0 else "wuya"


# ─── HTTP Handler（Vercel Serverless）───────────────────────
class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 静默日志

    def do_GET(self):
        path = self.path.split("?")[0]

        # ── 健康检查 ──────────────────────────────────────────
        if path == "/api/health":
            self._json(200, {
                "status": "ok",
                "twitter": bool(os.environ.get("TWITTER_ACCESS_TOKEN")),
                "claude": bool(os.environ.get("ANTHROPIC_API_KEY")),
                "fomo_ref": FOMO_REF_LINK,
                "time_utc": datetime.now(timezone.utc).isoformat(),
            })
            return

        # ── 手动测试生成（不发推）─────────────────────────────
        if path == "/api/preview":
            tweet_type = self.path.split("type=")[-1] if "type=" in self.path else decide_tweet_type()
            if tweet_type == "fomo":
                text = generate_fomo_tweet()
            else:
                text = generate_wuya_tweet()
            self._json(200, {"type": tweet_type, "text": text, "len": len(text)})
            return

        # ── Cron 触发（正式发推）──────────────────────────────
        if path in ("/api/cron", "/api/cron/"):
            # 验证 Vercel Cron Secret（防止外部触发）
            cron_secret = os.environ.get("CRON_SECRET", "")
            if cron_secret:
                auth_header = self.headers.get("authorization", "")
                if auth_header != f"Bearer {cron_secret}":
                    self._json(401, {"error": "unauthorized"})
                    return

            tweet_type = decide_tweet_type()
            print(f"[Cron] UTC day={datetime.now(timezone.utc).day}, type={tweet_type}")

            if tweet_type == "fomo":
                text = generate_fomo_tweet()
            else:
                text = generate_wuya_tweet()

            print(f"[Cron] Tweet ({len(text)} chars): {text[:80]}...")

            try:
                result = post_tweet(text)
                tweet_id = result.get("data", {}).get("id", "unknown")
                print(f"[Cron] ✅ Posted tweet_id={tweet_id}")
                self._json(200, {
                    "ok": True,
                    "type": tweet_type,
                    "tweet_id": tweet_id,
                    "text_preview": text[:100],
                })
            except Exception as e:
                print(f"[Cron] ❌ Failed: {e}")
                self._json(500, {"ok": False, "error": str(e), "text": text[:100]})
            return

        self._json(404, {"error": "not found", "path": path})

    def do_POST(self):
        self.do_GET()

    def _json(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

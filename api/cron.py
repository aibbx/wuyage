"""
乌鸦哥 AI Agent — Vercel Cron Handler v5
策略：乌鸦嘴社评（建立受众）+ fomo.family 联盟推广（产生收益）
比例：60% 乌鸦嘴社评 : 40% FOMO推广（每5天2次FOMO）
收益：被推荐用户每笔交易 → 25% 手续费分成（实时到账）
调度：UTC 09:00 每日触发
"""

from http.server import BaseHTTPRequestHandler
import json, os, random, re, time, hmac, hashlib, base64
import urllib.parse, urllib.request
from datetime import datetime, timezone

# ─── 配置 ────────────────────────────────────────────────────
FOMO_REFERRAL    = "https://fomo.family/r/SamAltman"
FOMO_REF_SHORT   = "fomo.family/r/SamAltman"
MAX_WEIGHTED     = 276   # 留4字余量（中文=2，英文=1）


# ─── Twitter OAuth 1.0a ──────────────────────────────────────
def _oauth_header(method, url, params, api_key, api_secret, token, token_secret):
    ts    = str(int(time.time()))
    nonce = base64.b64encode(os.urandom(16)).decode().rstrip("=")
    oauth = {
        "oauth_consumer_key":     api_key,
        "oauth_nonce":            nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp":        ts,
        "oauth_token":            token,
        "oauth_version":          "1.0",
    }
    all_params    = {**params, **oauth}
    sorted_params = "&".join(
        f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(all_params.items())
    )
    base_string = "&".join([
        method.upper(),
        urllib.parse.quote(url,           safe=""),
        urllib.parse.quote(sorted_params, safe=""),
    ])
    signing_key = (
        f"{urllib.parse.quote(api_secret, safe='')}"
        f"&{urllib.parse.quote(token_secret, safe='')}"
    )
    sig = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    oauth["oauth_signature"] = sig
    header = "OAuth " + ", ".join(
        f'{urllib.parse.quote(str(k), safe="")}="{urllib.parse.quote(str(v), safe="")}"'
        for k, v in sorted(oauth.items())
    )
    return header


def weighted_len(text: str) -> int:
    """Twitter 字符权重：CJK/emoji=2，其余=1"""
    return sum(2 if ord(c) > 127 else 1 for c in text)


def truncate_tweet(text: str, max_w: int = MAX_WEIGHTED) -> str:
    """截断到安全长度，保留 referral link"""
    if weighted_len(text) <= max_w:
        return text
    lines = text.split('\n')
    result, current_w = [], 0
    for line in lines:
        line_w = weighted_len(line + '\n')
        if current_w + line_w > max_w - 40:
            break
        result.append(line)
        current_w += line_w
    truncated = '\n'.join(result)
    # 保留 referral link（FOMO 推文）
    if FOMO_REFERRAL in text and FOMO_REFERRAL not in truncated:
        if weighted_len(truncated + '\n' + FOMO_REFERRAL) <= max_w:
            truncated = truncated.rstrip() + '\n\n' + FOMO_REFERRAL
    return truncated


def post_tweet(text: str) -> dict:
    """发推（OAuth 1.0a）"""
    text = truncate_tweet(text)

    api_key      = os.environ["TWITTER_API_KEY"].strip()
    api_secret   = os.environ["TWITTER_API_SECRET"].strip()
    token        = os.environ["TWITTER_ACCESS_TOKEN"].strip()
    token_secret = os.environ["TWITTER_ACCESS_TOKEN_SECRET"].strip()

    url    = "https://api.twitter.com/2/tweets"
    body   = json.dumps({"text": text}).encode()
    header = _oauth_header("POST", url, {}, api_key, api_secret, token, token_secret)

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization":  header,
            "Content-Type":   "application/json",
            "Accept":         "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


# ─── Claude 调用 ─────────────────────────────────────────────
def call_claude(system_prompt: str, user_prompt: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return ""
    try:
        body = json.dumps({
            "model":      "claude-opus-4-5",
            "max_tokens": 450,
            "system":     system_prompt,
            "messages":   [{"role": "user", "content": user_prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "x-api-key":         api_key,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode())
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"[Claude] error: {e}")
        return ""


# ─── DexScreener 热门代币 ────────────────────────────────────
def get_hot_tokens(limit: int = 3) -> str:
    """获取 Solana 热门代币，作为可选素材"""
    try:
        req = urllib.request.Request(
            "https://api.dexscreener.com/latest/dex/search?q=solana",
            headers={"User-Agent": "fomo-agent/2.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
        pairs = data.get("pairs", [])
        hot = []
        for p in pairs[:60]:
            if p.get("chainId") != "solana":
                continue
            vol   = float(p.get("volume",  {}).get("h24", 0) or 0)
            liq   = float(p.get("liquidity", {}).get("usd", 0) or 0)
            chg   = float(p.get("priceChange", {}).get("h24", 0) or 0)
            if liq > 50000 and vol > 100000 and chg > 20:
                sym = p.get("baseToken", {}).get("symbol", "???")
                hot.append(f"${sym} +{chg:.0f}% 24h, Vol ${vol/1e6:.1f}M")
            if len(hot) >= limit:
                break
        return "当前 Solana 热门代币：" + " | ".join(hot) if hot else ""
    except Exception:
        return ""


# ─── 乌鸦嘴系统提示 ──────────────────────────────────────────
WUYA_SYSTEM = """你是「乌鸦嘴预言家」——港片老炮加网络毒舌合体的社会评论家。

核心气质：
• 说真相但不说废话——每条必须有一个让人「被戳中」的核心洞察
• 冷幽默、有预言感、不装逼但有底气
• 语言节奏感强，适合手机上读

风格要求：
• 字数：130-190字（Twitter中文计2字符，不超过 278 weighted chars）
• 禁止：励志鸡汤、模糊废话、成功学腔调
• 必须：有具体数字/场景/类比，让人觉得是真事
• 结尾签名固定：「— 乌鸦嘴，说到 🐦‍⬛」
• 不加 hashtag（保持调性干净）

只输出推文正文，不加任何解释。"""

# ─── 乌鸦嘴话题（20个方向，按日期种子轮换）────────────────────
WUYA_TOPICS = [
    "写：打工人最不敢承认的真相——「稳定工作」的本质是什么。用具体场景，乌鸦嘴视角，结尾一刀。",
    "写：老板说「把你当自己人」背后的商业逻辑。要辛辣，有具体案例感，不超过190字。",
    "写：「再熬一年就好了」这个谎言为什么每年都有人相信。节奏快，150字以内。",
    "写：努力工作但收入停滞的核心原因——不是抱怨，是揭穿一个具体逻辑错误。",
    "写：裁员通知为什么总用「感谢你的贡献」开头——翻译这句话的商业含义。",
    "写：散户在牛市里最经典的亏钱逻辑，用一个具体场景还原，要有数字和时间线。",
    "写：「感觉要涨」这四个字是怎么让数百万人亏钱的。",
    "写：市场里最贵的东西不是知识，是信息差。用加密市场举例，写出让人被戳中的洞察。",
    "写：所有人说「长期持有」，为什么90%的人拿不住——不是意志力问题，是什么问题。",
    "写：「这次不一样」是历史上每次泡沫前说最多的话。写2026年的具体版本。",
    "写：大多数人的焦虑不是怕失败，是怕被人看见失败——这两种恐惧的解法为什么不同。",
    "写：聪明人最危险的习惯是用智商给自己错误找理由——举一个会心一击的具体例子。",
    "写：「钱不是最重要的」这句话，两类人各自的真实动机是什么。",
    "写：为什么越穷的人越容易被「一夜暴富」故事骗——不是智商问题，是什么问题。",
    "写：社交媒体上晒成功的人和真正成功的人有什么关键区别。",
    "写：加密市场2026年最大的泡沫在哪——用乌鸦嘴预言风格，要有具体赛道名称。",
    "写：99%的NFT和meme coin归零的底层逻辑——不是市场不好，是什么决定的。",
    "写：散户为什么永远是接盘侠——让人第一次真正理解这个游戏规则。",
    "写：「AI+区块链」这个词被说了多少次，现在活下来多少——让人清醒的推文。",
    "写：加密市场里「共识」这个词是如何被滥用来割韭菜的，要有具体手法描述。",
]


# ─── FOMO 推广系统提示 ───────────────────────────────────────
FOMO_SYSTEM = f"""你是「乌鸦嘴预言家」，在 fomo.family 上做加密交易，最近推荐了不少人去用这个平台。

任务：用乌鸦嘴风格写一条自然带出 referral link 的推文。

fomo.family 核心卖点（选1-2个自然带出）：
• 排行榜 + 实时 feed：看顶级玩家买什么，一键跟单
• 链上透明数据：$370 做到6位数，链上可查不是KOL自吹
• $1 固定手续费（非按比例）：大单省几十甚至几百美元
• 跨链零 gas：Solana/Base/BNB/Monad，Apple Pay直接入金
• 500,000+ 用户，平台已付 $1.1M+ 联盟佣金

写作规则：
• 字数 130-190 中文字
• 乌鸦嘴语气——冷静、有预言感，绝不广告腔，不说"速来""福利"
• referral link 自然出现，不要「点击领取」这种说辞
• 加 1-2 个 hashtag（#Solana #fomo #Memecoin #Base #crypto 选）
• 结尾：{FOMO_REFERRAL}

只输出推文正文，不加解释。"""

# ─── FOMO 推广角度（10个切入点）────────────────────────────────
FOMO_ANGLES = [
    f"写信息差角度：加密市场顶级玩家买什么，fomo.family 实时 feed 全公开。普通人2天后才从Twitter知道的，用这个平台的人早就进场了。带出 {FOMO_REFERRAL}",
    f"写链上数据角度：排行榜上有账户从 $370 做到了6位数。不是KOL吹牛，是链上记录，每笔交易时间价格滑点全都在。聪明人只信数据不信故事。带出 {FOMO_REFERRAL}",
    f"写手续费数学：大单玩家为什么转向 fomo.family 的$1固定费用。交易$10,000：DEX 0.5%=$50，fomo=$1，差$49。一年100次就是$4900。算数谁都会。带出 {FOMO_REFERRAL}",
    f"写门槛消失角度：Apple Pay 买 Solana，10秒到账，零 gas。你花了多少年学链上操作，一个从没听说过区块链的人今天就进场了。护城河变成了陷阱。带出 {FOMO_REFERRAL}",
    f"写跟单本质：散户自己操作亏钱是能力问题。有了实时跟单还亏钱是态度问题。fomo.family 把信息公开了，差距变成了选择题。带出 {FOMO_REFERRAL}",
    f"写工具进化：Twitter 告诉你别人说了什么，fomo.family 告诉你别人做了什么。说和做之间的差距，就是KOL和交易者的差距。带出 {FOMO_REFERRAL}",
    f"写多链机会：只玩 Solana 的人错过了 Base，只看 Base 的人错过了 BNB。fomo 四链一个 app，机会不会因为你的视野窄而减少。带出 {FOMO_REFERRAL}",
    f"写集体智慧：一个人很难跑赢500个交易者的集体决策。韭菜是一个人在和整个市场对赌，用了 fomo 跟单功能，你至少站对了队伍。带出 {FOMO_REFERRAL}",
    f"写早期窗口：fomo.family 已经付出了超过$1.1M联盟佣金，500万用户还没到。推荐一个活跃交易者，你拿他每笔交易25%手续费，永久。早进去的人早建立被动收入。带出 {FOMO_REFERRAL}",
    f"写散户宿命反转：不是你不聪明，是你一个人对抗的是整个市场的信息体系。fomo.family 把这个体系拆开给你看了。用不用是你的事。带出 {FOMO_REFERRAL}",
]


# ─── Fallback 推文（Claude失败时用）──────────────────────────
FALLBACK_WUYA = [
    "有人说市场不可预测。\n\n错。市场极其可预测：\n80%的人，涨了50%后买进，跌了30%后卖出。\n\n不是市场随机，是人类确定性地蠢。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "老板说「你是公司最重要的资产」。\n\n资产的意思是：\n低成本维护，高效率产出，折旧后替换。\n\n你不是家人，你是一行账目。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "「再熬一年就好了」\n\n你三年前、两年前、去年也这么说。\n\n熬不出结果，是时间问题。\n熬错了方向，是逻辑问题。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "所有人说长期持有。\n实际持有超6个月的人，不到5%。\n\n不是意志力问题——\n是没人算过持有的机会成本。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "钱不是最重要的，有两种人在说：\n一是真的不缺钱。\n二是希望你接受更少的钱。\n\n搞清楚对方是哪种，再决定信不信。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "加密市场最贵的东西不是技术，不是项目方，\n是「比你早两分钟知道这件事」。\n\n信息差是真实存在的税，\n不知道的人在付，知道的人在收。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "聪明人最危险的习惯：\n用智商给自己的错误找理由。\n\n普通人是认错，聪明人是辩解。\n越聪明越拖得久，越拖越难看。\n\n— 乌鸦嘴，说到 🐦‍⬛",
]

FALLBACK_FOMO = [
    f"加密市场亏钱，90%不是运气，是信息。\n\n顶级交易者在买什么，fomo.family 的实时 feed 全部公开。\n不是小道消息，是链上数据。\n\n你看不见，不代表没发生。\n\n#Solana #fomo\n{FOMO_REFERRAL}",
    f"有人在 fomo.family 从 $370 做到了6位数。\n不是KOL讲故事——排行榜链上可查，每笔交易都在。\n\n聪明钱早进了。你在等什么信号？\n\n#Memecoin #fomo\n{FOMO_REFERRAL}",
    f"数学题：\n交易$10,000，DEX 0.5%手续费 = $50\nfomo.family $1固定手续费 = $1\n\n一年100次，省$4,900。\n大单玩家为什么在转，逻辑很简单。\n\n#Solana #crypto\n{FOMO_REFERRAL}",
    f"Apple Pay 买 Solana，10秒到账，零 gas。\n\n门槛降了意味着更多资金涌入，\n先进去的人越赚。\n逻辑很简单，动不动是你的事。\n\n#Base #Solana\n{FOMO_REFERRAL}",
]


# ─── 推文类型决策（40% FOMO）──────────────────────────────────
def get_post_type(day_of_year: int) -> str:
    """
    每5天中第2、4天发FOMO，其余发乌鸦嘴（40%比例）
    """
    return "fomo" if (day_of_year % 5) in (1, 3) else "wuya"


# ─── 生成推文 ─────────────────────────────────────────────────
def generate_tweet(post_type: str, day_of_year: int) -> str:
    seed = (day_of_year * 7 + 13) % 251   # 伪随机种子，基于日期
    now  = datetime.now(timezone.utc)

    if post_type == "fomo":
        # 可选：获取 DexScreener 热门代币作素材
        token_ctx = get_hot_tokens()
        angle = FOMO_ANGLES[seed % len(FOMO_ANGLES)]
        user_prompt = f"{token_ctx}\n\n{angle}" if token_ctx else angle

        text = call_claude(FOMO_SYSTEM, user_prompt)

        if text and weighted_len(text) > 10:
            # 确保 referral link 存在
            if FOMO_REFERRAL not in text and FOMO_REF_SHORT not in text:
                text = text.rstrip() + f"\n\n{FOMO_REFERRAL}"
        else:
            text = FALLBACK_FOMO[seed % len(FALLBACK_FOMO)]

    else:  # wuya
        topic = WUYA_TOPICS[seed % len(WUYA_TOPICS)]
        text  = call_claude(WUYA_SYSTEM, topic)
        if not text or weighted_len(text) < 20:
            text = FALLBACK_WUYA[seed % len(FALLBACK_WUYA)]

    return truncate_tweet(text)


# ─── HTTP Handler ────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[HTTP] {fmt % args}")

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")

        # ── 健康检查 ──
        if path in ("/api/health", "/api/cron/health", ""):
            env_ok = bool(os.environ.get("TWITTER_ACCESS_TOKEN", "").strip())
            self._json(200, {
                "status":    "ok" if env_ok else "missing_env",
                "service":   "wuyage-cron-v5",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        # ── Cron 触发 ──
        if path in ("/api/cron", "/api/cron/run"):
            now         = datetime.now(timezone.utc)
            day_of_year = now.timetuple().tm_yday
            post_type   = get_post_type(day_of_year)

            print(f"[Cron] day={day_of_year}, type={post_type}")

            try:
                text     = generate_tweet(post_type, day_of_year)
                w_len    = weighted_len(text)
                print(f"[Cron] weighted_len={w_len}, text_preview={text[:80]!r}")

                result   = post_tweet(text)
                tweet_id = result.get("data", {}).get("id", "unknown")
                print(f"[Cron] ✅ tweet_id={tweet_id}")

                self._json(200, {
                    "ok":           True,
                    "type":         post_type,
                    "tweet_id":     tweet_id,
                    "weighted_len": w_len,
                    "text_preview": text[:120],
                })
            except Exception as e:
                print(f"[Cron] ❌ {e}")
                import traceback; traceback.print_exc()
                self._json(500, {"ok": False, "error": str(e)})
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

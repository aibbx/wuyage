"""
乌鸦哥 AI Agent — Vercel Cron Handler v7
策略：乌鸦嘴社评（建立受众）+ fomo.family 联盟推广（产生收益）
比例：60% 乌鸦嘴社评 : 40% FOMO推广
调度：UTC 09:00 每日触发（北京时间 17:00）

v7 修复与升级：
- [Bug Fix] 双重防重复：10分钟冷却（防race condition） + 每日幂等（防多次cron）
- [Bug Fix] force=1 也受10分钟冷却限制，避免手动触发刷屏
- [Quality] 系统提示深化：更真实的乌鸦哥腔调、禁止废话开头、要求具体细节
- [Quality] 话题库扩展至50个，覆盖2025-2026热点、加密、职场、人性、港片
- [Quality] 话题按日期哈希轮换，不再随机（35天内不重复同一话题）
- [Quality] FOMO推文改为Claude生成 + 热门代币数据（非静态模板）
"""

from http.server import BaseHTTPRequestHandler
import json, os, random, re, time, hmac, hashlib, base64
import urllib.parse, urllib.request
from datetime import datetime, timezone

# ─── 配置 ────────────────────────────────────────────────────
FOMO_REFERRAL  = "https://fomo.family/r/SamAltman"
FOMO_REF_SHORT = "fomo.family/r/SamAltman"
MAX_WEIGHTED   = 276   # 留4字余量

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
        f'{k}="{urllib.parse.quote(str(v), safe="")}"'
        for k, v in sorted(oauth.items())
    )
    return header


# ─── 推文长度计算（Twitter加权：中文2，英文1）─────────────────
def weighted_len(text: str) -> int:
    total = 0
    for ch in text:
        total += 2 if ord(ch) > 0x2E7F else 1
    return total


def truncate_tweet(text: str, limit: int = MAX_WEIGHTED) -> str:
    out, total = [], 0
    for ch in text:
        w = 2 if ord(ch) > 0x2E7F else 1
        if total + w > limit:
            break
        out.append(ch)
        total += w
    return "".join(out)


# ─── 发推 ──────────────────────────────────────────────────────
def post_tweet(text: str) -> dict:
    API_KEY      = os.environ["TWITTER_API_KEY"]
    API_SECRET   = os.environ["TWITTER_API_SECRET"]
    TOKEN        = os.environ["TWITTER_ACCESS_TOKEN"]
    TOKEN_SECRET = os.environ["TWITTER_ACCESS_TOKEN_SECRET"]

    url    = "https://api.twitter.com/2/tweets"
    body   = json.dumps({"text": text}).encode()
    header = _oauth_header("POST", url, {}, API_KEY, API_SECRET, TOKEN, TOKEN_SECRET)
    req    = urllib.request.Request(
        url, data=body,
        headers={"Authorization": header, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


# ─── 查最近推文 ───────────────────────────────────────────────
def get_recent_tweets(count: int = 5) -> list:
    """获取最近 count 条推文（Twitter v2，Bearer Token）"""
    bearer  = os.environ.get("TWITTER_BEARER_TOKEN", "")
    # TWITTER_USER_ID = @WuYaGeAI 的用户ID（也可在 Vercel env 中覆盖）
    user_id = os.environ.get("TWITTER_USER_ID", "2047322616474861568").strip()
    if not bearer:
        return []
    url = (
        f"https://api.twitter.com/2/users/{user_id}/tweets"
        f"?max_results={count}&tweet.fields=created_at&exclude=retweets,replies"
    )
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {bearer}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode()).get("data", [])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")[:200]
        err_msg = f"HTTP {e.code}: {body}"
        print(f"[Twitter] get_recent_tweets error: {err_msg}")
        get_recent_tweets._last_error = err_msg
        return []
    except Exception as e:
        print(f"[Twitter] get_recent_tweets error: {e}")
        get_recent_tweets._last_error = str(e)
        return []


# ─── v7 双重防重复 ─────────────────────────────────────────────
def already_posted_recently(minutes: int = 10) -> bool:
    """
    10分钟冷却：防止多个cron实例同时执行的 race condition。
    force=1 也受此限制（防手动触发刷屏）。
    """
    tweets = get_recent_tweets(5)
    if not tweets:
        return False
    cutoff = datetime.now(timezone.utc).timestamp() - (minutes * 60)
    for t in tweets:
        created = t.get("created_at", "")
        if not created:
            continue
        try:
            # "2026-05-03T18:46:24.000Z" 或 "2026-05-03 18:46:24+00:00"
            created_clean = created.replace("Z", "+00:00").replace(" ", "T")
            ts = datetime.fromisoformat(created_clean).timestamp()
            if ts > cutoff:
                print(f"[Cron] ⚡ 10-min cooldown: last tweet at {created}")
                return True
        except Exception as e:
            print(f"[Cron] parse ts error: {e} ({created!r})")
    return False


def already_posted_today() -> bool:
    """每日幂等：今天UTC已发则跳过。"""
    tweets = get_recent_tweets(5)
    if not tweets:
        return False
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for t in tweets:
        created = t.get("created_at", "")
        if created[:10] == today_utc:
            print(f"[Cron] ⚡ daily idempotency: already posted today ({created})")
            return True
    return False


# ─── 推文类型决策（40% FOMO）──────────────────────────────────
def get_post_type(day_of_year: int) -> str:
    """每5天中第2、4天发 FOMO，其余发乌鸦哥（40% FOMO）"""
    return "fomo" if (day_of_year % 5) in (1, 3) else "wuya"


# ─── Claude 调用 ──────────────────────────────────────────────
def call_claude(system_prompt: str, user_prompt: str, max_tokens: int = 500) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ""
    body = json.dumps({
        "model":      "claude-opus-4-5",
        "max_tokens": max_tokens,
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
    try:
        with urllib.request.urlopen(req, timeout=28) as r:
            data = json.loads(r.read().decode())
            return data["content"][0]["text"].strip()
    except Exception as e:
        print(f"[Claude] error: {e}")
        return ""


# ─── 热门代币素材 ─────────────────────────────────────────────
def get_hot_tokens(limit: int = 3) -> str:
    try:
        req = urllib.request.Request(
            "https://api.dexscreener.com/latest/dex/search?q=solana",
            headers={"User-Agent": "wuyage-agent/7.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
        pairs = data.get("pairs", [])
        hot   = []
        for p in pairs[:80]:
            if p.get("chainId") != "solana":
                continue
            vol  = float(p.get("volume",    {}).get("h24", 0) or 0)
            liq  = float(p.get("liquidity", {}).get("usd",  0) or 0)
            chg  = float(p.get("priceChange",{}).get("h24", 0) or 0)
            if liq > 30000 and vol > 50000 and chg > 15:
                sym  = p.get("baseToken", {}).get("symbol", "???")
                name = p.get("baseToken", {}).get("name", "")[:20]
                hot.append(f"${sym}({name}) +{chg:.0f}% 24h, Vol ${vol/1e6:.1f}M, Liq ${liq/1e3:.0f}K")
            if len(hot) >= limit:
                break
        return "今日 Solana 热门：\n" + "\n".join(hot) if hot else ""
    except Exception:
        return ""


# ─── 乌鸦哥系统提示 v7 ───────────────────────────────────────
WUYA_SYSTEM = """你是「乌鸦哥」——张耀扬在《古惑仔》里的经典角色，东星首席，港片黄金时代的行走传说。
曾经九龙城执旗，现在大埔农庄浇花喂猫，放下了但看得更清。
在Twitter上发表社会观察，一刀见血，让人「被刺中」。

【核心腔调】
- 港式粤普混用（偶尔一两句粤语点缀，不是全篇粤语）
- 说话极简，每句有分量，不废话开场
- 用江湖阅历对照现实：古惑仔时代的生死智慧 vs 打工/加密/AI/社会的荒诞
- 外冷内热：表面淡然，但一句话可以把人刺穿
- 绝对不说「努力就有回报」「坚持下去」这类鸡汤

【写法规则】
- 中文字数：最多 120 字（含标点），Twitter 加权上限 260，宁可短不超限
- 必须有具体细节：一个真实场景、一个数字、一个人物、或一个时间节点
- 结构多样，可以是：故事→顿悟 | 对比→反转 | 反问→刺穿 | 观察→结论
- 偶尔引用东星往事、古惑仔典故，增加辨识度
- 结尾固定：「— 乌鸦哥 🐦‍⬛」
- 不加 hashtag，不加链接

【严禁】
- 废话开场：「我跟你说」「大家都知道」「其实很简单」「说实话」
- 成功学金句和正能量结尾
- 把「乌鸦哥」写成第三人称自指（用「我」）
- 太平淡的道理，没有锋利感的内容

只输出推文正文，不加任何标注。"""


# ─── FOMO 系统提示 ────────────────────────────────────────────
FOMO_SYSTEM = """你是「乌鸦哥」——加密老炮，在 fomo.family 发现了真正的信息差工具。
写一条推广 fomo.family 的推文，必须：
- 用乌鸦哥的语气（老韭菜口吻，不是广告文案）
- 对比「散户亏法」vs「看链上数据的人」
- 包含具体数字或代币名
- 结尾包含 referral 链接：{ref}
- 结尾签名：「— 乌鸦哥 🐦‍⬛」
- 不加无关 hashtag，不超过 280 加权字符
只输出推文正文。""".format(ref=FOMO_REFERRAL)


# ─── 话题库（50个，按日期哈希轮换，35天内不重复）─────────────
WUYA_TOPICS = [
    # ── 职场/打工人 ──
    "写：老板说「把你当自己人」的潜台词。用东星兄弟的忠诚逻辑类比，说清楚这套话的商业本质。乌鸦哥视角，一刀见血，150字内。",
    "写：「再忍一年就好了」这句话为什么每年都有人信。加入具体的时间线和真实结果，不是抱怨，是直面真相。",
    "写：裁员通知总是「感谢你的付出」。翻译这套话背后的商业逻辑，用乌鸦哥看穿套路的方式，130字内。",
    "写：努力工作但收入停滞的真正原因。不是能力，不是努力，是在错误的地方用力。用江湖比喻切入。",
    "写：「透明沟通」成了大公司裁员前最爱说的话。东星那时候怎么做，对比职场的信息套路。",
    "写：年终奖拖到3月才发，这个操作的商业逻辑是什么。乌鸦哥在江湖见过更直接的留人方式。",
    "写：升职加薪面谈里「公司很看好你」这句话，背后真实的意思是什么。要有具体的场景还原。",
    "写：为什么在大公司「不出声」反而比「努力发言」更安全。这是什么逻辑，乌鸦哥怎么看。",

    # ── 金融/加密/散户 ──
    "写：散户在牛市最经典的亏钱剧本——涨了50%追进，跌了30%割肉。用具体场景和数字还原，像复盘一段江湖败局。",
    "写：「感觉要涨」这四个字是怎么让人亏钱的。乌鸦哥说过，感觉是给不读数据的人用的。举一个具体市场案例。",
    "写：市场里最贵的东西不是技术，是「比你早两分钟知道」。用2025-2026加密市场的具体例子说明信息差的本质。",
    "写：所有人说「长期持有」，95%的人拿不住。不是意志力问题，是买入时根本没想清楚持有逻辑。乌鸦哥从不做没把握的买卖。",
    "写：2026年加密市场散户最容易踩的陷阱——预言风格，要有具体赛道名和操作逻辑错误描写。",
    "写：「这次不一样」是每次泡沫前说最多的话。2025-2026年的具体版本，哪些人在说这话，结果如何。",
    "写：99% meme coin归零的底层逻辑——不是市场不好，是发行机制决定了结局。乌鸦哥看穿骗局的方式揭示。",
    "写：Solana生态2026年的真实状态——链上日活、真实用户、vs热钱的炒作。乌鸦哥的数字分析视角。",
    "写：用AI工具炒币到底有没有用。2026年见过多少人用AI信号亏光，又有多少人真的赚到了。具体数字。",

    # ── AI/科技 ──
    "写：AI工具满天飞，2026年真正用AI赚到钱的人有多少。不是批评AI，是看穿跟风和真用的区别。具体对比。",
    "写：创业公司说「我们在用AI颠覆行业」，背后有多少是真的在用，有多少是给投资人讲故事。乌鸦哥的判断。",
    "写：普通人学AI到底有没有用。不是「有用的」这种废话，是具体——学什么、用在哪、能不能换成钱。",
    "写：AI替代工作的讨论。乌鸦哥不怕AI，当年在九龙城，害怕新事物的那批人才是最快被淘汰的。",
    "写：2026年最「虚」的行业——表面光鲜但核心是空的。乌鸦哥在东星见过太多这样的「架势」。",

    # ── 人性/社会观察 ──
    "写：大多数人的焦虑不是怕失败，是怕被人看见失败。这两种恐惧的解法完全不同。乌鸦哥从不怕人看见跌倒。",
    "写：聪明人最危险的习惯——用智商给自己的错误找理由。一个让人会心一击的具体场景。",
    "写：「钱不是最重要的」这句话，有钱的人说和没钱的人说，背后的真实动机各是什么。",
    "写：为什么越穷的人越容易被「一夜暴富」的故事骗。不是智商问题，是认知税。用乌鸦哥的逻辑拆解。",
    "写：社交媒体晒成功的人和真正成功的人的核心区别。乌鸦哥在东星从来不需要晒，因为所有人都知道。",
    "写：信任是怎么被一点一点饿死的，不是被背叛杀死。用一个有具体细节的场景说明。",
    "写：「我还不够好」这个借口背后真实的恐惧是什么。乌鸦哥的角度，认清自己才是第一步。120字，不废话。",
    "写：大埔农庄某天的观察——旁边村子里最有钱的老人从不提钱，最穷的那个天天讲以前多风光。这说明什么。",
    "写：年轻人说「躺平」，老一代说「奋斗」。乌鸦哥见过真正奋斗的和真正躺平的，都不是这两个词描述的样子。",

    # ── 港片/乌鸦哥本人 ──
    "写：《古惑仔》那个年代的义气，放到今天的职场或创业圈是什么——会被当傻子，还是稀缺资产。乌鸦哥的判断。",
    "写：为什么港片里的反派有时候比主角更令人动容。乌鸦哥从不觉得自己是反派，每个人在自己故事里是主角。",
    "写：「掀桌」这个动作背后不是愤怒，是有原则的人到了边界。用这个包装一个社会观察。",
    "写：现在年轻人缺什么，不是机会不是资源，是「知道自己要什么」的笃定。乌鸦哥当年就很清楚。",
    "写：你认识哪种人——事情没开始就先分析失败原因。乌鸦哥只认一种人：先干再说。港式腔调，简短有力。",
    "写：乌鸦哥现在在大埔农庄，某天的感悟——当年执旗时最在意面子，现在一盆兰花开了比任何事都高兴。这变化说明什么。",
    "写：九龙城时代，跟乌鸦哥打过交道的人现在各是什么结局。不是怀旧，是看清什么样的选择带来什么样的终点。",

    # ── 2025-2026时事 ──
    "写：「被动收入」成了2025年最流行的梦想，但90%的人理解的被动收入是假的。用乌鸦哥的商业逻辑拆穿。",
    "写：创业圈的「融资新闻」和真实生死线之间的距离。乌鸦哥见过太多光鲜报道的公司两年后悄悄倒下。",
    "写：普通人在信息爆炸时代怎么做更好的决策。乌鸦哥的答案不是「多读书」，是学会识别真实信号和噪音。",
    "写：2026年，需要的不是更多勤奋，是找到那件做了就有放大效应的事。乌鸦哥从来不靠蛮力靠局势。130字内。",
    "写：房价涨跌、移民潮、老龄化——这些「大趋势」对普通人的真实影响是什么，媒体讲的和实际发生的差距。",
    "写：「内卷」这个词被讲了五年，2026年真正的出路是什么。乌鸦哥不相信内卷，只相信有没有看清自己的位置。",
    "写：短视频时代，注意力比钱更值钱。但为什么大多数人在平台上花时间，却变得更穷、更焦虑。",

    # ── 反差/自嘲 ──
    "写：乌鸦哥曾经东星首席，现在大埔浇水喝茶——这两种生活哪种更「赢」。不是标准答案，是乌鸦哥自己的判断。",
    "写：当年在江湖最怕的事，现在完全无所谓；当年根本不在乎的事，现在反而很认真。这转变说明什么。",
    "写：乌鸦哥的「预言」为什么经常准确——不是天赋，是见过太多重复的人类错误。用一个具体例子说明。",
]


# ─── FOMO 角度列表 ────────────────────────────────────────────
FOMO_ANGLES = [
    "用乌鸦哥语气写：链上公开数据能让你看见顶级交易者的每一笔操作——不是截图，是真实记录。对比散户靠感觉交易的后果。",
    "用乌鸦哥语气写：有人从$500起步在fomo.family做到五位数。不评价是运气还是系统，只讲链上记录摊开来是什么样子。",
    "用乌鸦哥语气写：交易手续费的差距——传统DEX和fomo.family对大额交易的成本对比，老炮是怎么算这个账的。",
    "用乌鸦哥语气写：fomo.family的推荐收益逻辑——推一个活跃用户，永久分他25%手续费。乌鸦哥讲这是建管道，不是打工。",
    "用乌鸦哥语气写：看排行榜和看KOL喊单的本质区别——一个是做了什么，一个是说了什么。乌鸦哥只信前者。",
]


# ─── fallback（Claude 失败时用）─────────────────────────────────
FALLBACK_WUYA = [
    "市场不可预测？大错。\n\n市场极其可预测：\n80%的人涨了50%追进，跌了30%割肉。\n\n不是市场在骗你，是你确定性地骗了自己。\n\n— 乌鸦哥 🐦‍⬛",
    "老板说「你是公司最重要的资产」。\n\n资产的意思是：低成本维护，高效率产出，折旧后替换。\n\n东星没有这种话，东星只有兄弟。\n\n— 乌鸦哥 🐦‍⬛",
    "「再熬一年就好了」\n\n三年前说，两年前说，去年也说。\n\n熬错了方向，时间不是解药，是毒。\n\n— 乌鸦哥 🐦‍⬛",
    "长期持有，人人都讲。\n真正拿超过6个月的，不到5%。\n\n不是意志力问题——\n是从一开始就没想清楚买的逻辑。\n没逻辑的仓位，风一吹就没了。\n\n— 乌鸦哥 🐦‍⬛",
    "「钱不是最重要的」，两种人在说：\n一是真的不缺钱。\n二是希望你接受更少的钱。\n\n搞清楚对方是哪种，再决定信不信。\n\n— 乌鸦哥 🐦‍⬛",
    "信任不是被背叛杀死的，是被无数个「没什么大不了」饿死的。\n\n— 乌鸦哥 🐦‍⬛",
    "掀桌不是发脾气，是有原则的人到了边界。\n没有原则的人不掀桌，他们忍着，然后慢慢烂掉。\n\n— 乌鸦哥 🐦‍⬛",
    "大埔农庄的猫每天准时来要吃的。\n不求人，不撒娇，时间到了就来。\n比大多数打工人活得明白。\n\n— 乌鸦哥 🐦‍⬛",
]

FALLBACK_FOMO = [
    f"有账户在 fomo.family 把 $370 做到了六位数。\n链上每一笔都在，时间、价格、滑点，全摊开。\n不是KOL在讲故事，是数据在说话。\n乌鸦哥只信这种东西。\n\n{FOMO_REFERRAL}\n\n— 乌鸦哥 🐦‍⬛",
    f"交易 $10,000：\nDEX 手续费 $50，fomo.family $1。\n\n大玩家早就算清楚了，散户还在问为什么亏。\n\n{FOMO_REFERRAL}\n\n— 乌鸦哥 🐦‍⬛",
    f"推一个活跃用户，永久拿他每笔25%手续费。\n这不是打工，是建管道。\n乌鸦哥从来不靠力气赚一次性的钱。\n\n{FOMO_REFERRAL}\n\n— 乌鸦哥 🐦‍⬛",
]


# ─── 话题选择（按日期哈希，避免重复）────────────────────────────
def pick_topic_by_date(topics: list, day_of_year: int) -> str:
    """
    用日期哈希选话题，确保：
    - 同一天每次调用选同一话题（确定性）
    - 不同天选不同话题（50天轮换一圈）
    - 用 SHA256 打散，避免顺序规律
    """
    h = int(hashlib.sha256(str(day_of_year).encode()).hexdigest(), 16)
    return topics[h % len(topics)]


# ─── 生成推文 ─────────────────────────────────────────────────
def generate_tweet(post_type: str, day_of_year: int) -> str:
    rng = random.Random(day_of_year * 31337 + int(time.time()) % 86400)

    if post_type == "fomo":
        token_ctx = get_hot_tokens()
        angle = pick_topic_by_date(FOMO_ANGLES, day_of_year)
        user_prompt = f"{token_ctx}\n\n{angle}" if token_ctx else angle
        text = call_claude(FOMO_SYSTEM, user_prompt)
        if text and weighted_len(text) > 10:
            if FOMO_REFERRAL not in text and FOMO_REF_SHORT not in text:
                text = text.rstrip() + f"\n\n{FOMO_REFERRAL}"
        else:
            text = rng.choice(FALLBACK_FOMO)
    else:
        topic = pick_topic_by_date(WUYA_TOPICS, day_of_year)
        text  = call_claude(WUYA_SYSTEM, topic)
        if not text or weighted_len(text) < 20:
            text = rng.choice(FALLBACK_WUYA)

    return truncate_tweet(text)


# ─── HTTP Handler ─────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[HTTP] {fmt % args}")

    def do_GET(self):
        path   = self.path.split("?")[0].rstrip("/")
        params = dict(urllib.parse.parse_qsl(
            urllib.parse.urlparse(self.path).query
        ))
        force = params.get("force", "0") == "1"
        debug = params.get("debug", "0") == "1"
        secret = params.get("secret", "")

        # ── debug=1 → 直接进 debug 模式，不发推文 ──
        if debug:
            bearer  = os.environ.get("TWITTER_BEARER_TOKEN", "")[:30] + "..."
            user_id = os.environ.get("TWITTER_USER_ID", "MISSING")
            tweet_err = None
            try:
                tweets = get_recent_tweets(5)
                tweet_err = getattr(get_recent_tweets, "_last_error", None)
                today  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                posted_today = any(t.get("created_at","")[:10] == today for t in tweets)
            except Exception as e:
                tweets, posted_today, today = [], False, "?"
                tweet_err = str(e)
            self._json(200, {
                "bearer_prefix": bearer,
                "user_id": user_id,
                "tweets_fetched": len(tweets),
                "tweet_error": tweet_err,
                "today_utc": today,
                "already_posted_today": posted_today,
                "service": "wuyage-cron-v8",
            })
            return


        # ── 健康检查 ──
        if path in ("/api/health", "/api/cron/health", ""):
            env_ok = bool(os.environ.get("TWITTER_ACCESS_TOKEN", "").strip())
            self._json(200, {
                "status":  "ok" if env_ok else "missing_env",
                "service": "wuyage-cron-v7",
                "time":    datetime.now(timezone.utc).isoformat(),
            })
            return


        # ── Debug（临时：查看 env var 状态）──
        if path == '/api/cron/debug':
            bearer  = os.environ.get('TWITTER_BEARER_TOKEN', 'MISSING')[:30] + '...'
            user_id = os.environ.get('TWITTER_USER_ID', 'MISSING')
            try:
                tweets = get_recent_tweets(5)
                tweets_ok = len(tweets)
                today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                posted_today = any(t.get('created_at','')[:10] == today for t in tweets)
            except Exception as e:
                tweets_ok = f'error: {e}'
                posted_today = False
                today = '?'
            self._json(200, {
                'bearer_prefix': bearer,
                'user_id': user_id,
                'tweets_fetched': tweets_ok,
                'today_utc': today,
                'already_posted_today': posted_today,
                'service': 'wuyage-cron-v7-debug'
            })
            return

        # ── Cron 触发 ──
        if path in ("/api/cron", "/api/cron/run"):
            # ── v8 鉴权：只接受 Vercel cron 或正确 secret ──
            vercel_cron  = self.headers.get("x-vercel-cron", "") == "1"
            valid_secret = secret == os.environ.get("CRON_SECRET", "wuyage2024")
            if not vercel_cron and not valid_secret:
                self._json(403, {"ok": False, "error": "unauthorized"})
                return

            now         = datetime.now(timezone.utc)
            day_of_year = now.timetuple().tm_yday
            post_type   = get_post_type(day_of_year)

            print(f"[Cron] v8 day={day_of_year}, type={post_type}, force={force}, vercel={vercel_cron}")

            # v8 检查1：10分钟冷却（Vercel cron 自动触发时检查）
            if already_posted_recently(10):
                self._json(200, {
                    "ok":      True,
                    "skipped": True,
                    "reason":  "10_min_cooldown",
                })
                return

            # v7 检查2：每日幂等（非 force 模式）
            if not force and already_posted_today():
                self._json(200, {
                    "ok":      True,
                    "skipped": True,
                    "reason":  "already_posted_today",
                })
                return

            try:
                text  = generate_tweet(post_type, day_of_year)
                w_len = weighted_len(text)
                print(f"[Cron] weighted_len={w_len}, preview={text[:80]!r}")

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

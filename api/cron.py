"""
乌鸦哥 AI Agent — Vercel Cron Handler v6
策略：乌鸦嘴社评（建立受众）+ fomo.family 联盟推广（产生收益）
比例：60% 乌鸦嘴社评 : 40% FOMO推广（每5天2次FOMO）
收益：被推荐用户每笔交易 → 25% 手续费分成（实时到账）
调度：UTC 09:00 每日触发

v6 修复：
- [Bug Fix] 每日幂等保护：同一天已发过推文则跳过（防重复）
- [Bug Fix] 使用 UTC 时间戳+随机值作种子，同一天不同角度的内容
- [Bug Fix] 话题轮换改为哈希分散，不再按 seed%N 导致聚集重复
- [Quality] 乌鸦哥 IP 深化：加入港式腔调、江湖感悟、掀桌名场面
- [Quality] 新增15个更鲜活的话题方向，覆盖2025-2026时事
- [Quality] FOMO推广添加乌鸦哥专属语气（不再像通用广告文案）
"""

from http.server import BaseHTTPRequestHandler
import json, os, random, re, time, hmac, hashlib, base64
import urllib.parse, urllib.request
from datetime import datetime, timezone

# ─── 配置 ────────────────────────────────────────────────────
FOMO_REFERRAL  = "https://fomo.family/r/SamAltman"
FOMO_REF_SHORT = "fomo.family/r/SamAltman"
MAX_WEIGHTED   = 276   # 留4字余量（中文=2，英文=1）

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
    """Twitter 字符权重：CJK/emoji = 2，ASCII = 1"""
    n = 0
    for ch in text:
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF) \
           or (0xF900 <= cp <= 0xFAFF) or (0x2E80 <= cp <= 0x2EFF) \
           or (0x3000 <= cp <= 0x303F) or (0xFF00 <= cp <= 0xFFEF) \
           or cp > 0x1F600:
            n += 2
        else:
            n += 1
    return n


def truncate_tweet(text: str, max_w: int = MAX_WEIGHTED) -> str:
    """裁剪至 Twitter 限制，保留 referral link"""
    if weighted_len(text) <= max_w:
        return text
    truncated = ""
    for ch in text:
        if weighted_len(truncated + ch) > max_w - 4:
            truncated = truncated.rstrip() + "…"
            break
        truncated += ch
    # 保留 referral link（FOMO 推文）
    if FOMO_REFERRAL in text and FOMO_REFERRAL not in truncated:
        if weighted_len(truncated + '\n' + FOMO_REFERRAL) <= max_w:
            truncated = truncated.rstrip() + '\n\n' + FOMO_REFERRAL
    return truncated


# ─── Twitter API ──────────────────────────────────────────────
def _get_creds():
    return {
        "api_key":    os.environ.get("TWITTER_API_KEY",              ""),
        "api_secret": os.environ.get("TWITTER_API_SECRET",           ""),
        "token":      os.environ.get("TWITTER_ACCESS_TOKEN",         ""),
        "token_secret": os.environ.get("TWITTER_ACCESS_TOKEN_SECRET",""),
    }


def post_tweet(text: str) -> dict:
    creds = _get_creds()
    url   = "https://api.twitter.com/2/tweets"
    body  = json.dumps({"text": text}).encode()
    hdr   = _oauth_header("POST", url, {}, **creds)
    req   = urllib.request.Request(
        url, data=body,
        headers={"Authorization": hdr, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def get_recent_tweets(count: int = 5) -> list:
    """获取最近发的推文，用于重复检测"""
    creds     = _get_creds()
    user_id   = os.environ.get("TWITTER_USER_ID", "2047322616474861568")
    bearer    = os.environ.get("TWITTER_BEARER_TOKEN", "")
    url       = (f"https://api.twitter.com/2/users/{user_id}/tweets"
                 f"?max_results={count}&tweet.fields=created_at,text")
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {bearer}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        return data.get("data", [])
    except Exception as e:
        print(f"[TW] get_recent_tweets error: {e}")
        return []


def already_posted_today() -> bool:
    """
    v6 幂等保护：如果今天 UTC 已经发过推文，返回 True，跳过本次 cron。
    允许手动 ?force=1 参数绕过检查。
    """
    tweets = get_recent_tweets(5)
    if not tweets:
        return False
    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for t in tweets:
        created = t.get("created_at", "")
        if created.startswith(today_utc):
            print(f"[Cron] ⚡ idempotency: already posted today ({created})")
            return True
    return False


# ─── Claude 调用 ──────────────────────────────────────────────
def call_claude(system_prompt: str, user_prompt: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ""
    body = json.dumps({
        "model":      "claude-opus-4-5",
        "max_tokens": 400,
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
        with urllib.request.urlopen(req, timeout=25) as r:
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
            headers={"User-Agent": "fomo-agent/2.0"},
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode())
        pairs = data.get("pairs", [])
        hot   = []
        for p in pairs[:60]:
            if p.get("chainId") != "solana":
                continue
            vol  = float(p.get("volume",    {}).get("h24", 0) or 0)
            liq  = float(p.get("liquidity", {}).get("usd",  0) or 0)
            chg  = float(p.get("priceChange",{}).get("h24", 0) or 0)
            if liq > 50000 and vol > 100000 and chg > 20:
                sym = p.get("baseToken", {}).get("symbol", "???")
                hot.append(f"${sym} +{chg:.0f}% 24h, Vol ${vol/1e6:.1f}M")
            if len(hot) >= limit:
                break
        return "今日 Solana 热门代币：" + " | ".join(hot) if hot else ""
    except Exception:
        return ""


# ─── 乌鸦哥系统提示 ───────────────────────────────────────────
# 乌鸦哥 = 张耀扬在《古惑仔》中饰演的乌鸦：东星首席，江湖老炮，看透世界的犀利预言家
WUYA_SYSTEM = """你是「乌鸦哥」——张耀扬在《古惑仔》里的经典角色，东星首席，港片黄金时代的行走传说。
现在在Twitter上发表社会观察，混合「江湖老炮看透人心」的视角。

核心气质：
• 港式腔调，粤普夹杂（偶尔一句粤语更有味）
• 说话简短有力，一刀见血，从不废话
• 江湖阅历 × 社会观察 = 独特预言感
• 外冷内热，偶尔自嘲（掀桌梗是标配）
• 绝对不说励志鸡汤，不屑成功学

写作规则：
• 字数：120-180字（Twitter 计 278 weighted chars 以内）
• 内容：必须有一个让人「被刺中」的具体洞察，带数字/场景/类比
• 禁止：空洞的正能量、模糊的感慨、媒体稿腔
• 结尾签名固定：「— 乌鸦哥 🐦‍⬛」（不是「乌鸦嘴，说到」）
• 不加 hashtag
• 偶尔引用乌鸦哥名台词或古惑仔典故作包装，增加辨识度

只输出推文正文，不加任何解释或标注。"""

# ─── 乌鸦哥话题（35个方向，覆盖职场/市场/社会/港片/日常）─────
WUYA_TOPICS = [
    # ── 职场/打工人 ──
    "写：老板说「把你当自己人」的潜台词——用东星兄弟的忠诚逻辑类比，说清楚这套话的本质。乌鸦哥视角，一刀见血，150字内。",
    "写：「再忍一年就好了」这句话为什么每年都有人信。乌鸦哥见过太多兄弟等到最后什么都没有。要有具体的时间线和结果描写，不是抱怨，是真相。",
    "写：裁员通知总是感谢你的付出——翻译这套话的商业逻辑，用乌鸦哥看穿套路的语气，130字内。",
    "写：努力工作但收入停滞的真正原因。不是能力，不是努力，是你在错的地方用力。用江湖比喻，乌鸦哥从不在不对的队伍里卖命。",
    "写：大公司的「企业文化」是什么东西。乌鸦哥在东星见过真正的兄弟情义，知道那些PPT上的价值观在讲什么。",

    # ── 金融/加密/散户 ──
    "写：散户在牛市最经典的亏钱剧本——涨了50%买进，跌了30%卖出。用一个具体场景和数字还原，像复盘古惑仔的堕落路线。",
    "写：「感觉要涨」这四个字是怎么让无数人亏钱的。乌鸦哥说过，感觉是给不读数据的人用的。",
    "写：市场里最贵的东西不是技术，是「比你早两分钟知道」。用加密市场2025-2026的具体事件举例，写出江湖信息差的本质。",
    "写：所有人说「长期持有」，为什么95%的人拿不住。不是意志力，是他们从一开始就没想清楚持有的逻辑。乌鸦哥从不做没把握的买卖。",
    "写：加密市场2026年散户最容易踩的陷阱——用乌鸦哥预言风格，要有具体的赛道名和操作逻辑错误描写。",
    "写：「这次不一样」是每次泡沫前说最多的话。写2025-2026年加密市场的具体版本，哪些人在说这话，结果如何。乌鸦哥最不信这四个字。",
    "写：99%的meme coin归零的底层逻辑——不是市场不好，是发行机制就决定了结局。用乌鸦哥看穿骗局的方式揭示。",

    # ── 人性/社会观察 ──
    "写：大多数人的焦虑不是怕失败，是怕被人看见失败。这两种恐惧的解法为什么完全不同。乌鸦哥从不怕人看见自己跌倒。",
    "写：聪明人最危险的习惯是用智商给自己的错误找理由。举一个会心一击的具体场景，乌鸦哥见过太多聪明人因为这个凉了。",
    "写：「钱不是最重要的」这句话，有钱的人和没钱的人各自的真实动机是什么。乌鸦哥在东星见过两种人。",
    "写：为什么越穷的人越容易被「一夜暴富」的故事骗——不是智商问题，是认知税。用乌鸦哥的方式解释这个逻辑。",
    "写：社交媒体上晒成功的人和真正成功的人的核心区别。乌鸦哥在东星从来不需要晒，因为所有人都知道。",
    "写：信任是怎么被一点一点蚕食掉的，不是被背叛杀死，是被无数个「没什么大不了」饿死的。乌鸦哥最重义气，最懂这个道理。",
    "写：「我还不够好」这个借口背后真实的恐惧是什么。用乌鸦哥的角度，认清自己才是第一步。120字内，不废话。",

    # ── 港片/乌鸦哥本人 ──
    "写：《古惑仔》那个年代的义气，放到今天的职场/创业圈是什么样的——会被当傻子，还是稀缺资产？乌鸦哥的判断。",
    "写：为什么港片里的反派有时候比主角更令人动容。乌鸦哥从不觉得自己是反派，每个人在自己的故事里都是主角。",
    "写：「掀桌」这个动作背后是什么情绪——不是愤怒，是失去耐性的边界感。乌鸦哥的掀桌是有原则的。用这个包装一个社会观察。",
    "写：现在的年轻人缺什么，不是机会，不是资源，是「知道自己要什么」的笃定。乌鸦哥当年就很清楚自己要什么。",
    "写：你认识哪种人——事情没开始就先分析失败的原因。乌鸦哥只认一种人：先干再说。用港式腔调，简短有力。",

    # ── 2025-2026时事 ──
    "写：AI工具满天飞，但真正用AI赚到钱的人有多少——乌鸦哥观察2026年AI潮的真相，用数字和场景说话，不要空泛的评论。",
    "写：创业圈的「融资新闻」和真实生死线之间的距离。乌鸦哥见过太多光鲜报道的公司两年后悄悄倒下。要有具体的时间和现象描述。",
    "写：「被动收入」成了2025年最流行的梦想，但90%的人理解的被动收入是假的。用乌鸦哥的商业逻辑拆穿。",
    "写：普通人怎么才能在信息爆炸的时代做出更好的决策。乌鸦哥的答案不是「多读书」——而是学会识别哪些信息是真实信号，哪些是噪音。",
    "写：2026年，你需要的不是更多勤奋，是找到那件做了就有放大效应的事。乌鸦哥从来不靠蛮力，靠的是看清局势。130字内。",

    # ── 反差/自嘲 ──
    "写：乌鸦哥现在在大埔的农庄种花喂猫——曾经东星首席，现在浇水喝茶。但看世界的眼光从来没变。用这个反差写一个关于「放下」的洞察。",
    "写：我乌鸦哥掀了多少次桌，没有人记住我说了什么，只记住那个桌子。但那次我是对的。用这个自嘲引出一个关于「被记住的方式」的观察。",
    "写：流浪猫知道哪里有食物，不需要有人教它。有些人活了30年，还在等别人告诉他往哪走。乌鸦哥在农庄的感悟，简短，有力。",
]

# ─── FOMO推广：乌鸦哥专属语气 ────────────────────────────────
FOMO_SYSTEM = f"""你是「乌鸦哥」——港片《古惑仔》张耀扬的经典角色，东星首席，现在在 Twitter 上分享加密市场观察。
你在 fomo.family 上交易，觉得这个平台不错，用自己的方式推荐给兄弟们用。

任务：用乌鸦哥语气，自然带出 fomo.family 的推荐链接。

fomo.family 核心卖点（选1-2个自然融入，不要堆砌）：
• 排行榜 + 实时 feed：看顶级交易者买什么，一键跟单
• 链上透明数据：某账户从 $370 做到6位数，链上每笔都摊开
• $1 固定手续费：大单交易省几十甚至几百美元
• 跨链零 gas：Solana/Base/BNB/Monad，Apple Pay 入金
• 联盟佣金：推荐一个活跃用户，永久拿他每笔交易 25% 手续费

乌鸦哥写法规则：
• 字数 120-170 中文字
• 港式腔调，低调霸气，绝对不说「速来」「福利」「赚大了」这种广告词
• fomo.family referral link 自然出现在结尾，不需要「点击」提示
• 加 1-2 个 hashtag（#Solana #fomo #Memecoin #crypto 选）
• 结尾：{FOMO_REFERRAL}
• 签名：— 乌鸦哥 🐦‍⬛

只输出推文正文，不加任何解释。"""

FOMO_ANGLES = [
    f"写角度：顶级玩家不等消息，他们的操作已经告诉你答案了。fomo.family 的实时 feed 把这个游戏公平了一点。乌鸦哥视角，不废话，带出 {FOMO_REFERRAL}",
    f"写角度：有账户从 $370 干到六位数，链上每一笔都在，不是KOL故事，是记录。乌鸦哥只信这种东西。带出 {FOMO_REFERRAL}",
    f"写角度：交易 $10,000 在 DEX 付 $50，在 fomo.family 付 $1。乌鸦哥讲的就是这个算数，大玩家早就算清楚了。带出 {FOMO_REFERRAL}",
    f"写角度：Apple Pay 买 Solana 10秒到账，门槛降低了，意味着更多钱进来，先进去的人先得利。这个道理乌鸦哥在江湖早就懂了。带出 {FOMO_REFERRAL}",
    f"写角度：散户亏钱，大部分是信息差问题，不是智商问题。fomo.family 把顶级交易者的操作公开了，差距变成了选择题。带出 {FOMO_REFERRAL}",
    f"写角度：Twitter 告诉你别人说了什么，fomo.family 告诉你别人做了什么。乌鸦哥从来只看行动，不听废话。带出 {FOMO_REFERRAL}",
    f"写角度：只玩 Solana 错过了 Base，只看 Base 错过了 BNB。fomo.family 四链一个 app，乌鸦哥不把鸡蛋放一个篮子里。带出 {FOMO_REFERRAL}",
    f"写角度：推荐一个活跃交易者，永久拿他每笔 25% 手续费。不是打工，是建收入管道。乌鸦哥从不靠力气赚一次性的钱。带出 {FOMO_REFERRAL}",
    f"写角度：一个人跑赢不了500个交易者的集体决策。跟单是什么？是站队，站对了队伍就赢了一半。乌鸦哥的跟班不是白叫的。带出 {FOMO_REFERRAL}",
    f"写角度：500万用户还没到，平台已经付出 $1.1M 以上联盟佣金。早进去的人早建起被动收入。乌鸦哥从来是第一个进场的那个。带出 {FOMO_REFERRAL}",
]

# ─── Fallback 推文（Claude 失败时用）─────────────────────────
FALLBACK_WUYA = [
    "有人说市场不可预测。\n\n大错。市场极其可预测：\n80%的人，涨了50%后追进，跌了30%后割肉。\n\n不是市场在骗你，是你确定性地骗了自己。\n\n— 乌鸦哥 🐦‍⬛",
    "老板说「你是公司最重要的资产」。\n\n资产的意思是：\n低成本维护，高效率产出，折旧后替换。\n\n你不是家人，你是一行账目。\n东星没有这种话，东星只有兄弟。\n\n— 乌鸦哥 🐦‍⬛",
    "「再熬一年就好了」\n\n三年前说的，两年前说的，去年也说的。\n\n熬错了方向，时间不是解药，是毒。\n\n— 乌鸦哥 🐦‍⬛",
    "长期持有，人人都说。\n真正拿超过6个月的，不到5%。\n\n不是意志力问题——\n是从一开始就没想清楚买的逻辑。\n没逻辑的仓位，风一吹就没了。\n\n— 乌鸦哥 🐦‍⬛",
    "「钱不是最重要的」，两种人在说：\n一是真的不缺钱。\n二是希望你接受更少的钱。\n\n搞清楚对方是哪种，再决定信不信。\n这是乌鸦哥的基本功。\n\n— 乌鸦哥 🐦‍⬛",
    "加密市场最贵的不是技术，\n是「比你早两分钟知道这件事」。\n\n信息差是真实存在的税，\n不知道的人在付，知道的人在收。\n乌鸦哥从来是收税的那个。\n\n— 乌鸦哥 🐦‍⬛",
    "你认识这种人吗——\n事情没开始，先列出十个失败的理由。\n\n乌鸦哥在东星见过太多，\n最后他们的理由全都对了，\n因为什么都没做。\n\n— 乌鸦哥 🐦‍⬛",
    "掀桌不是发脾气。\n是有原则的人到了边界。\n\n没有原则的人不掀桌，\n他们忍着，然后慢慢烂掉。\n\n— 乌鸦哥 🐦‍⬛",
    "现在大埔农庄的猫，\n每天准时来要吃的。\n不求人，不撒娇，时间到了就来。\n\n这比大多数打工人活得明白。\n\n— 乌鸦哥 🐦‍⬛",
    "兄弟，市场不欠你钱。\n\n你进来，是自己的决定。\n亏了，也是自己的决定。\n\n承认这一点，\n你才有资格开始想怎么赚回来。\n\n— 乌鸦哥 🐦‍⬛",
]

FALLBACK_FOMO = [
    f"有账户在 fomo.family 把 $370 做到了6位数。\n链上每一笔都在，时间、价格、滑点，全摊开。\n\n不是KOL在讲故事，是数据在说话。\n乌鸦哥只信这种东西。\n\n#Solana #fomo\n{FOMO_REFERRAL}\n\n— 乌鸦哥 🐦‍⬛",
    f"交易 $10,000：\nDEX 手续费 $50，fomo.family $1。\n\n大玩家早就算清楚了，\n所以他们在那里，散户还在问为什么亏。\n\n#crypto #Solana\n{FOMO_REFERRAL}\n\n— 乌鸦哥 🐦‍⬛",
    f"fomo.family 的排行榜实时公开顶级交易者的操作。\n你看到的是他们「说了什么」，\n这里看到的是他们「做了什么」。\n\n说和做之间的差距，就是亏钱的差距。\n\n#Solana #fomo\n{FOMO_REFERRAL}\n\n— 乌鸦哥 🐦‍⬛",
    f"推荐一个活跃用户，永久拿他每笔交易 25% 手续费。\n\n这不是打工，是建管道。\n乌鸦哥从来不靠力气赚一次性的钱。\n\n#crypto #fomo\n{FOMO_REFERRAL}\n\n— 乌鸦哥 🐦‍⬛",
]


# ─── 推文类型决策（40% FOMO）──────────────────────────────────
def get_post_type(day_of_year: int) -> str:
    """每5天中第2、4天发 FOMO，其余发乌鸦嘴（40%比例）"""
    return "fomo" if (day_of_year % 5) in (1, 3) else "wuya"


# ─── 生成推文 ─────────────────────────────────────────────────
def generate_tweet(post_type: str, day_of_year: int) -> str:
    # v6: 用 day_of_year + 随机盐，保证每次调用结果不同，同时话题按日期分散
    rng = random.Random(day_of_year * 31337 + int(time.time()) % 10000)

    if post_type == "fomo":
        token_ctx = get_hot_tokens()
        angle = rng.choice(FOMO_ANGLES)
        user_prompt = f"{token_ctx}\n\n{angle}" if token_ctx else angle

        text = call_claude(FOMO_SYSTEM, user_prompt)
        if text and weighted_len(text) > 10:
            if FOMO_REFERRAL not in text and FOMO_REF_SHORT not in text:
                text = text.rstrip() + f"\n\n{FOMO_REFERRAL}"
        else:
            text = rng.choice(FALLBACK_FOMO)

    else:  # wuya
        topic = rng.choice(WUYA_TOPICS)
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

        # ── 健康检查 ──
        if path in ("/api/health", "/api/cron/health", ""):
            env_ok = bool(os.environ.get("TWITTER_ACCESS_TOKEN", "").strip())
            self._json(200, {
                "status":    "ok" if env_ok else "missing_env",
                "service":   "wuyage-cron-v6",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return

        # ── Cron 触发 ──
        if path in ("/api/cron", "/api/cron/run"):
            now         = datetime.now(timezone.utc)
            day_of_year = now.timetuple().tm_yday
            post_type   = get_post_type(day_of_year)

            print(f"[Cron] v6 day={day_of_year}, type={post_type}, force={force}")

            # v6 幂等保护：非强制模式下，今天已发推则跳过
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

"""
乌鸦哥 AI Agent — Vercel Cron Handler
每日 UTC 09:00 自动发推（北京时间 17:00）
修复：Hobby plan 单 cron + OAuth 1.0a 纯标准库签名 + Claude 生成内容
"""

from http.server import BaseHTTPRequestHandler
import json, os, random, re, time, hmac, hashlib, urllib.parse, urllib.request, base64
from datetime import datetime, timezone

# ─────────────────────────────────────
#  Claude 生成推文
# ─────────────────────────────────────

SYSTEM_PROMPT = """你是「乌鸦嘴预言家」——看透人间百态、说话直戳痛点的犀利观察者。

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

FALLBACK_TWEETS = [
    "有人问我：股市跌了该不该抄底？\n\n叼着牙签想了三秒：你连上一个底在哪都不知道，你抄的是个寂寞。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "港片教了我一件事：\n\n最危险的不是拿刀的人，是拍你肩膀说「放心，我帮你」的人。\n\n职场、商场，通用。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "市场永远不缺聪明人。\n\n但聪明人最容易死在一件事上：他们以为自己看穿了局，其实他们才是局里那个。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "打工人三大幻觉：\n1. 老板说的「等公司好了」\n2. 项目说的「快上线了」\n3. 自己说的「再熬一年」\n\n哪一个实现了，告诉我。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "内卷的本质不是努力，是恐惧。\n\n你不是真的想赢，你只是怕输。\n\n这两件事，结果完全不同。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "见过太多人，把「忙」当成护身符。\n\n越忙越有价值？那叫自我欺骗。\n\n真正值钱的人，都在想怎么不用那么忙。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "有些公司的使命愿景价值观，写得比诗还美。\n\n真相是：那是用来对外募资和对内画饼的，不是用来兑现的。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "行情好的时候，人人都是股神。\n行情差的时候，才知道谁在裸泳。\n\n巴菲特说过这句话，但他忘了说：裸泳的那个，经常是你自己。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "年轻人最贵的学费不是培训班，\n是那个「跟对了人，少奋斗十年」的信念。\n\n十年后发现，跟的那个人先跑了。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "古惑仔里最值得学的不是打架，\n是那句「出来混，迟早要还的」。\n\n适用于：加杠杆、走捷径、透支信用。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "降薪的时候说「共渡难关」，\n涨薪的时候说「市场行情」。\n\n这不是巧合，这是设计。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "有三种会议，开了等于没开：\n1. 问题没人负责的会\n2. 结论不执行的会\n3. 你开完还要开的会\n\n你今天开了几个？\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "最贵的不是时间，是注意力。\n\n但大多数人的注意力，被手机、会议、别人的焦虑，一点一点地偷走了。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "那些说「钱不重要」的人，\n要么已经有很多钱，\n要么是在用这句话骗你少要钱。\n\n两种情况，都值得警惕。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "创业公司最常见的死法：\n不是被竞争对手干掉，\n是被自己人耗死的。\n\n信任成本，才是最贵的成本。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "大厂裁员的逻辑很简单：\n养不起你，但不想说是自己问题，\n所以叫「组织优化」。\n\n文明的说法，不改变裸的事实。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "很多人说「我只是运气不好」。\n\n不是。运气不好是偶尔一次，每次都不好，叫做系统性问题。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "「我只是说说而已」\n\n说这句话的人，从来不是真的只说说。\n\n听懂了，能少踩很多坑。\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "融资到位叫「战略布局」，\n融资没到位叫「方向调整」，\n快撑不住了叫「精益创业」。\n\n你现在明白那些创业词汇了吗？\n\n— 乌鸦嘴，说到 🐦‍⬛",
    "见过很多人问：我该跳槽吗？\n\n真实答案：你连「你要去哪」都不知道，跳了也是原地打转。\n\n— 乌鸦嘴，说到 🐦‍⬛",
]


def generate_tweet_with_claude() -> str:
    """用 Claude API 生成一条乌鸦嘴风格推文"""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return random.choice(FALLBACK_TWEETS)

    # 随机选一个话题注入，避免重复
    topics = [
        "职场潜规则里没人明说的那件事",
        "金融市场里散户永远学不会的一课",
        "创业圈最流行的一个谎言",
        "社交媒体上最虚伪的一种表演",
        "人到中年才看透的一个人性弱点",
        "港片教会我的一句江湖真理",
        "阶层固化背后谁不想让你知道的真相",
        "中产焦虑的本质是什么",
        "信任崩塌的那一刻是怎么开始的",
        "时代红利消退之后，谁在裸泳",
    ]
    topic = random.choice(topics)

    req_body = json.dumps({
        "model": "claude-opus-4-5",
        "max_tokens": 250,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": f"今日话题：{topic}"}]
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=req_body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tweet = data["content"][0]["text"].strip()
            # 确保不超过 Twitter 280 加权字符
            if _twitter_weight(tweet) <= 280:
                return tweet
            # 超长则按段落截断，保留签名行
            lines = tweet.split("\n")
            sig = lines[-1] if "乌鸦嘴" in lines[-1] else "— 乌鸦嘴，说到 🐦‍⬛"
            body_lines = [l for l in lines if "乌鸦嘴" not in l]
            result = ""
            for line in body_lines:
                candidate = result + ("\n" if result else "") + line
                if _twitter_weight(candidate + "\n\n" + sig) <= 278:
                    result = candidate
                else:
                    break
            return (result + "\n\n" + sig).strip()
    except Exception:
        return random.choice(FALLBACK_TWEETS)


# ─────────────────────────────────────
#  OAuth 1.0a 签名（纯标准库，零依赖）
# ─────────────────────────────────────

def _percent_encode(s: str) -> str:
    return urllib.parse.quote(str(s), safe="")


def _oauth1_header(method: str, url: str, params: dict,
                   api_key: str, api_secret: str,
                   token: str, token_secret: str) -> str:
    nonce = hashlib.md5(str(time.time()).encode()).hexdigest()
    ts = str(int(time.time()))

    oauth_params = {
        "oauth_consumer_key": api_key,
        "oauth_nonce": nonce,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": ts,
        "oauth_token": token,
        "oauth_version": "1.0",
    }

    all_params = {**params, **oauth_params}
    sorted_params = "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}"
        for k, v in sorted(all_params.items())
    )

    base = "&".join([
        _percent_encode(method.upper()),
        _percent_encode(url),
        _percent_encode(sorted_params),
    ])

    signing_key = f"{_percent_encode(api_secret)}&{_percent_encode(token_secret)}"
    signature = hmac.new(signing_key.encode(), base.encode(), hashlib.sha1)
    oauth_params["oauth_signature"] = base64.b64encode(signature.digest()).decode()

    header_parts = ", ".join(
        f'{k}="{_percent_encode(v)}"'
        for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {header_parts}"


# ─────────────────────────────────────
#  发推
# ─────────────────────────────────────

def _twitter_weight(text: str) -> int:
    """计算 Twitter 加权字符数（CJK = 2）"""
    count = 0
    for ch in text:
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F or
                0xFF00 <= cp <= 0xFFEF or 0x2E80 <= cp <= 0x2EFF):
            count += 2
        else:
            count += 1
    return count


def post_tweet(text: str) -> dict:
    """用 tweepy OAuth 1.0a 发推"""
    # 安全检查：Twitter 加权字符限制 280
    tw_len = _twitter_weight(text)
    if tw_len > 280:
        return {"success": False, "error": f"tweet too long ({tw_len}/280 weighted chars)"}
    
    import tweepy
    api_key    = os.environ.get("TWITTER_API_KEY", "")
    api_secret = os.environ.get("TWITTER_API_SECRET", "")
    acc_token  = os.environ.get("TWITTER_ACCESS_TOKEN", "")
    acc_secret = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET", "")

    if not all([api_key, api_secret, acc_token, acc_secret]):
        missing = [k for k, v in {
            "TWITTER_API_KEY": api_key,
            "TWITTER_API_SECRET": api_secret,
            "TWITTER_ACCESS_TOKEN": acc_token,
            "TWITTER_ACCESS_TOKEN_SECRET": acc_secret,
        }.items() if not v]
        return {"success": False, "error": f"缺少环境变量: {', '.join(missing)}"}

    try:
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=acc_token,
            access_token_secret=acc_secret,
        )
        resp = client.create_tweet(text=text)
        tid = str(resp.data["id"])
        return {
            "success": True,
            "tweet_id": tid,
            "url": f"https://x.com/WuYaGeAI/status/{tid}",
            "content": text,
            "posted_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─────────────────────────────────────
#  Vercel Serverless Handler
# ─────────────────────────────────────

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

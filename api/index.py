"""
WuYa Smart Agent 3.0
乌鸦嘴预言家 · Prophecy Engine
我说的不算，但我说的都准
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import json
import os
import random
from datetime import datetime
import tweepy
import anthropic

app = FastAPI(
    title="WuYa Smart Agent 3.0 — 乌鸦嘴预言家",
    description="凶相预警 · 预言引擎 · 乌鸦嘴指数",
    version="3.0.1"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ════════════════════════════════════════════════════
#  Twitter API Client — 真实发推
# ════════════════════════════════════════════════════
def get_twitter_client():
    """Initialize real Twitter API v2 client from env vars"""
    api_key            = os.environ.get("TWITTER_API_KEY")
    api_secret         = os.environ.get("TWITTER_API_SECRET")
    access_token       = os.environ.get("TWITTER_ACCESS_TOKEN")
    access_token_secret= os.environ.get("TWITTER_ACCESS_TOKEN_SECRET")
    bearer_token       = os.environ.get("TWITTER_BEARER_TOKEN")

    missing = [k for k,v in {
        "TWITTER_API_KEY": api_key,
        "TWITTER_API_SECRET": api_secret,
        "TWITTER_ACCESS_TOKEN": access_token,
        "TWITTER_ACCESS_TOKEN_SECRET": access_token_secret,
    }.items() if not v]

    if missing:
        return None, f"Missing env vars: {', '.join(missing)}"

    try:
        client = tweepy.Client(
            bearer_token=bearer_token,
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_token_secret,
            wait_on_rate_limit=True
        )
        return client, None
    except Exception as e:
        return None, str(e)


def post_tweet_now(text: str) -> dict:
    """Actually post a tweet, return result dict"""
    client, err = get_twitter_client()
    if err:
        return {"success": False, "error": err}
    try:
        response = client.create_tweet(text=text)
        tweet_id = response.data["id"]
        return {
            "success": True,
            "tweet_id": tweet_id,
            "url": f"https://x.com/wuyageai/status/{tweet_id}",
            "content": text,
            "posted_at": datetime.utcnow().isoformat() + "Z",
        }
    except tweepy.errors.Forbidden as e:
        return {"success": False, "error": f"403 Forbidden — 检查 App 权限是否开启 Read+Write: {e}"}
    except tweepy.errors.TweepyException as e:
        return {"success": False, "error": str(e)}


# ════════════════════════════════════════════════════
#  In-memory tweet history (resets on cold start)
# ════════════════════════════════════════════════════
TWEET_HISTORY: List[dict] = []

# ════════════════════════════════════════════════════
#  预言库 Prophecy Vault
# ════════════════════════════════════════════════════
VAULT = [
    {
        "id": "p_001",
        "subject": "某AI独角兽",
        "category": "industry",
        "alert_level": 4,
        "content": "融资烧光、估值腰斩，这局早看出来了。",
        "created_at": "2025-03-01T10:00:00Z",
        "status": "fulfilled",
        "result": "估值从200亿跌至80亿，裁员40%",
        "fulfilled_at": "2025-04-15T00:00:00Z",
        "crow_score": 5,
    },
    {
        "id": "p_002",
        "subject": "某meme加密货币",
        "category": "market",
        "alert_level": 5,
        "content": "庄家出货信号明显，散户接盘在即。凶相。",
        "created_at": "2025-03-20T09:00:00Z",
        "status": "fulfilled",
        "result": "72小时内暴跌63%",
        "fulfilled_at": "2025-03-23T00:00:00Z",
        "crow_score": 5,
    },
    {
        "id": "p_003",
        "subject": "某顶流明星",
        "category": "celebrity",
        "alert_level": 3,
        "content": "人设太满，撑不住的。迟早塌。",
        "created_at": "2025-04-10T08:00:00Z",
        "status": "pending",
        "result": None,
        "fulfilled_at": None,
        "crow_score": None,
    },
    {
        "id": "p_004",
        "subject": "某新能源车企",
        "category": "industry",
        "alert_level": 4,
        "content": "现金流有问题，供应链出现裂缝。这局不好打。",
        "created_at": "2025-04-20T11:00:00Z",
        "status": "pending",
        "result": None,
        "fulfilled_at": None,
        "crow_score": None,
    },
]

MEME_TRIGGERS = ["崩盘", "暴跌", "腰斩", "跑路", "塌房", "翻车", "暴雷", "破产", "崩了", "完了"]

# ════════════════════════════════════════════════════
#  推文模板 Tweet Templates
# ════════════════════════════════════════════════════
TWEET_TEMPLATES = {
    "alert": [
        "⚠️ 凶相预警\n\n{subject}——{detail}\n\n这局不好打。\n乌鸦嘴指数 {level}/5\n\n@wuyageai",
        "🐦 乌鸦嘴盯着一个东西：{subject}\n\n{detail}\n\n凶相已现。\n乌鸦嘴指数 {level}/5 @wuyageai",
        "嗅到味了。\n\n{subject}，{detail}\n\n自求多福吧。\n\n乌鸦嘴指数 {level}/5 @wuyageai",
    ],
    "fulfilled": [
        "（叼着牙签）\n\n早说了{subject}会{prediction}。\n\n今天：{result}\n\n#乌鸦嘴又准了 @wuyageai",
        "🎯 预言兑现\n\n{subject}，说过了。\n\n结果：{result}\n\n#乌鸦嘴从不撒谎 @wuyageai",
        "不是我说的早，是你们不信。\n\n{subject}：{result}\n\n@wuyageai #乌鸦嘴又准了",
    ],
    "sarcasm": [
        "哟，{subject}{event}了。\n\n意外吗？（一点都不）\n\n@wuyageai",
        "所以……{subject}，{event}，震惊了吧？\n\n（毫不震惊.jpg）\n\n@wuyageai",
        "{subject}出事了。\n\n没什么好说的。\n\n@wuyageai",
    ],
    "meme": [
        "（掀桌）\n\n说过了！这不就来了？🀄\n\n#乌鸦嘴从不撒谎",
        "（叼着牙签）\n\n……早。说。了。\n\n@wuyageai",
        "🐦\n\n早说了。\n\n（离开现场）",
        "我不是在诅咒，我是在预警。\n\n结果都一样。\n\n@wuyageai",
    ],
}


# ════════════════════════════════════════════════════
#  Pydantic Models
# ════════════════════════════════════════════════════
class TweetPostRequest(BaseModel):
    content: str                   # 直接发这条推文

class AutoGenerateRequest(BaseModel):
    mode: str = "alert"            # alert | fulfilled | sarcasm | meme
    subject: str = "某对象"
    detail: str = ""
    level: int = 4
    prediction: str = ""
    result: str = ""
    event: str = "翻车"
    use_ai: bool = False           # True = 用 Claude 生成；False = 用模板

class ProphecyCreate(BaseModel):
    subject: str
    category: str
    alert_level: int
    content: str

class ProphecyHit(BaseModel):
    id: str
    result: str
    crow_score: int


# ════════════════════════════════════════════════════
#  核心 API
# ════════════════════════════════════════════════════

@app.get("/api/health")
async def health():
    client, err = get_twitter_client()
    twitter_ok = client is not None
    return {
        "status": "ok",
        "version": "3.0.1",
        "twitter_connected": twitter_ok,
        "twitter_error": err if not twitter_ok else None,
        "anthropic_key": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "vault_count": len(VAULT),
        "history_count": len(TWEET_HISTORY),
        "ts": datetime.utcnow().isoformat() + "Z",
    }


# ─── 直接发推 ───────────────────────────────────────
@app.post("/api/tweets/post")
async def post_tweet(req: TweetPostRequest):
    """真实发推到 X/Twitter"""
    if not req.content.strip():
        raise HTTPException(400, "content is required")
    if len(req.content) > 280:
        raise HTTPException(400, f"Tweet too long: {len(req.content)} chars (max 280)")

    result = post_tweet_now(req.content)

    if result["success"]:
        # 记录历史
        TWEET_HISTORY.insert(0, {
            **result,
            "mode": "manual",
            "likes": 0, "retweets": 0, "replies": 0,
        })
        if len(TWEET_HISTORY) > 50:
            TWEET_HISTORY.pop()

    return result


# ─── 生成 + 发推（一键） ───────────────────────────
@app.post("/api/auto/generate-and-post")
async def auto_generate_and_post(req: AutoGenerateRequest):
    """
    生成推文内容，然后自动发布到 X。
    use_ai=True 时调用 Claude 生成；否则使用模板。
    """
    # 1. 生成内容
    if req.use_ai and os.environ.get("ANTHROPIC_API_KEY"):
        content = await _ai_generate(req)
    else:
        content = _template_generate(req)

    if not content:
        raise HTTPException(500, "Failed to generate content")

    # 确保不超 280 字符
    if len(content) > 280:
        content = content[:277] + "..."

    # 2. 发推
    result = post_tweet_now(content)

    if result["success"]:
        TWEET_HISTORY.insert(0, {
            **result,
            "mode": req.mode,
            "likes": 0, "retweets": 0, "replies": 0,
        })

    return {**result, "generated_content": content}


def _template_generate(req: AutoGenerateRequest) -> str:
    templates = TWEET_TEMPLATES.get(req.mode, TWEET_TEMPLATES["alert"])
    tpl = random.choice(templates)
    return (tpl
        .replace("{subject}", req.subject)
        .replace("{detail}", req.detail or "信号不对")
        .replace("{level}", str(req.level))
        .replace("{prediction}", req.prediction or "出事")
        .replace("{result}", req.result or "果然出事")
        .replace("{event}", req.event or "翻车")
    )


async def _ai_generate(req: AutoGenerateRequest) -> str:
    try:
        ai = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        mode_desc = {
            "alert":     "凶相预警——提前预警某对象即将出问题",
            "fulfilled": "预言应验——宣布之前的预言成真，叼着牙签冷静说一声",
            "sarcasm":   "反讽点评——某事翻车后用冷嘲热讽点评",
            "meme":      "表情包——掀桌或叼牙签表情，非常简短有力",
        }.get(req.mode, "凶相预警")

        prompt = f"""你是「乌鸦嘴预言家」，一个专门预警负面事件的AI账号，口头禅是「我说的不算，但我说的都准」。
        
任务：为以下场景生成一条 X（Twitter）推文。
模式：{mode_desc}
对象：{req.subject}
细节：{req.detail or '信号不对劲'}
乌鸦嘴指数：{req.level}/5

要求：
- 字数严格控制在 180 字以内（含标点和换行）
- 语气冷静、毒舌、带一点宿命感
- 必须结尾加 @wuyageai 或 #乌鸦嘴又准了
- 只输出推文正文，不要解释，不要引号

推文："""

        msg = ai.messages.create(
            model="claude-opus-4-5",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text.strip()
    except Exception as e:
        # fallback to template
        return _template_generate(req)


# ─── 队列（静态示例） ──────────────────────────────
@app.get("/api/tweets/queue")
async def get_queue():
    return {
        "queue": [
            {
                "id": "tw_a01", "mode": "alert", "category": "industry",
                "content": "⚠️ 凶相预警\n\n某大厂——裁员信号已持续3个月。\n\n这局不好打。\n乌鸦嘴指数 4/5\n\n@wuyageai",
            },
            {
                "id": "tw_a02", "mode": "fulfilled", "category": "market",
                "content": "（叼着牙签）\n\n之前说某币会崩。\n\n今天：-63%\n\n#乌鸦嘴又准了 @wuyageai",
            },
            {
                "id": "tw_a03", "mode": "sarcasm", "category": "celebrity",
                "content": "哟，某明星塌房了。\n\n意外吗？（一点都不）\n\n@wuyageai",
            },
            {
                "id": "tw_a04", "mode": "meme", "category": "market",
                "content": "（掀桌）\n\n说过了！这不就来了？🀄\n\n#乌鸦嘴从不撒谎",
            },
        ]
    }


# ─── 推文历史（真实已发） ──────────────────────────
@app.get("/api/tweets/history")
async def get_history(limit: int = 20):
    return {"tweets": TWEET_HISTORY[:limit]}


# ─── 预言库 CRUD ───────────────────────────────────
@app.get("/api/prophecy/list")
async def list_prophecies():
    return {"prophecies": VAULT, "total": len(VAULT)}

@app.post("/api/prophecy/create")
async def create_prophecy(p: ProphecyCreate):
    new_p = {
        "id": f"p_{len(VAULT)+1:03d}",
        "subject": p.subject,
        "category": p.category,
        "alert_level": p.alert_level,
        "content": p.content,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "status": "pending",
        "result": None,
        "fulfilled_at": None,
        "crow_score": None,
    }
    VAULT.append(new_p)
    return {"success": True, "prophecy": new_p}

@app.post("/api/prophecy/hit")
async def mark_hit(h: ProphecyHit):
    for p in VAULT:
        if p["id"] == h.id:
            p["status"] = "fulfilled"
            p["result"] = h.result
            p["crow_score"] = h.crow_score
            p["fulfilled_at"] = datetime.utcnow().isoformat() + "Z"
            return {"success": True, "prophecy": p}
    raise HTTPException(404, f"Prophecy {h.id} not found")


# ─── 内容生成（纯预览，不发推） ───────────────────
@app.post("/api/content/generate")
async def generate_content(req: AutoGenerateRequest):
    """只生成内容预览，不发推"""
    if req.use_ai and os.environ.get("ANTHROPIC_API_KEY"):
        content = await _ai_generate(req)
    else:
        content = _template_generate(req)
    meme_triggered = any(w in content for w in MEME_TRIGGERS)
    return {
        "content": content,
        "mode": req.mode,
        "char_count": len(content),
        "ready_to_post": True,
        "meme_triggered": meme_triggered,
        "meme_suggestion": "（掀桌）\n\n说过了！这不就来了？🀄\n\n#乌鸦嘴从不撒谎" if meme_triggered else None,
    }


# ─── Agent 状态 ────────────────────────────────────
@app.get("/api/agent/status")
async def agent_status():
    client, err = get_twitter_client()
    fulfilled = [p for p in VAULT if p["status"] == "fulfilled"]
    accuracy = round(len(fulfilled)/len(VAULT)*100, 1) if VAULT else 0
    return {
        "version": "3.0.1",
        "name": "乌鸦嘴预言家",
        "slogan": "我说的不算，但我说的都准",
        "twitter_connected": client is not None,
        "twitter_error": err if client is None else None,
        "prophecy_accuracy": accuracy,
        "vault_count": len(VAULT),
        "fulfilled_count": len(fulfilled),
        "tweet_count": len(TWEET_HISTORY),
        "auto_tweet": True,
        "tweet_interval_min": 45,
        "reply_interval_min": 10,
        "meme_triggers": MEME_TRIGGERS,
        "crow_index_target": 80.0,
    }

@app.post("/api/agent/trigger")
async def trigger_task(task: dict):
    """触发自动任务：生成 + 发推"""
    task_type = task.get("type", "alert")
    subject   = task.get("subject", "某对象")
    detail    = task.get("detail", "信号不对")
    level     = task.get("level", 4)
    auto_post = task.get("auto_post", False)

    req = AutoGenerateRequest(
        mode=task_type, subject=subject,
        detail=detail, level=level,
        use_ai=task.get("use_ai", False)
    )

    if auto_post:
        return await auto_generate_and_post(req)
    else:
        content = _template_generate(req)
        return {
            "success": True,
            "task_id": f"task_{datetime.utcnow().timestamp():.0f}",
            "type": task_type,
            "generated_content": content,
            "posted": False,
            "message": "内容已生成，未发布（auto_post=false）",
        }


@app.post("/api/webhook/twitter")
async def twitter_webhook(request: Request):
    data = await request.json()
    print(f"[WEBHOOK 3.0] {json.dumps(data, indent=2)}")
    return {"received": True}


# Vercel handler
from mangum import Mangum
handler = Mangum(app)

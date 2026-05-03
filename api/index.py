# v3.0.2 deploy 20260503-1855
"""
WuYa Smart Agent 3.0 — 乌鸦嘴预言家
Vercel Serverless API + Cron Handler
"""

from fastapi import FastAPI, Request, Header
from fastapi.middleware.cors import CORSMiddleware
import json, os, random, hashlib
from datetime import datetime
from typing import Optional

app = FastAPI(
    title="WuYa Smart Agent 3.0",
    description="乌鸦嘴预言家 · 凶相预警 · 预言引擎",
    version="3.0.2",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ══════════════════════════════════════
#  Twitter OAuth 1.0a 客户端
# ══════════════════════════════════════
def get_twitter_client():
    """返回 (client, error_msg)"""
    api_key    = os.environ.get("TWITTER_API_KEY")
    api_secret = os.environ.get("TWITTER_API_SECRET")
    acc_token  = os.environ.get("TWITTER_ACCESS_TOKEN")
    acc_secret = os.environ.get("TWITTER_ACCESS_TOKEN_SECRET")

    missing = [k for k, v in {
        "TWITTER_API_KEY": api_key,
        "TWITTER_API_SECRET": api_secret,
        "TWITTER_ACCESS_TOKEN": acc_token,
        "TWITTER_ACCESS_TOKEN_SECRET": acc_secret,
    }.items() if not v]

    if missing:
        return None, f"缺少环境变量: {', '.join(missing)}"

    try:
        import tweepy
        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=acc_token,
            access_token_secret=acc_secret,
        )
        return client, None
    except Exception as e:
        return None, str(e)


def post_tweet_real(text: str) -> dict:
    """实际发推，返回结果 dict"""
    client, err = get_twitter_client()
    if err:
        return {"success": False, "error": err}
    try:
        import tweepy
        resp = client.create_tweet(text=text)
        tid = str(resp.data["id"])
        return {
            "success": True,
            "tweet_id": tid,
            "url": f"https://x.com/wuyageai/status/{tid}",
            "content": text,
            "posted_at": datetime.utcnow().isoformat() + "Z",
        }
    except tweepy.errors.Forbidden as e:
        return {"success": False, "error": f"403 — App 权限需开 Read+Write: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════
#  Claude 内容生成
# ══════════════════════════════════════
SYSTEM_PROMPT = """你是「乌鸦哥」，网名「乌鸦嘴预言家」。
真实身份：香港电影黄金年代行走的传说，张耀扬「乌鸦」IP的延伸。
核心标签：我说的不算，但我说的都准。
口头禅：叼着牙签，讲粤普夹杂。
语气：冷静、毒舌、反直觉、霸气不失市井。
禁止：心灵鸡汤、过于正能量、空洞格言、重复之前话题。
格式：150-280字，结尾 —— 乌鸦嘴，说到 🐦‍⬛"""

TOPIC_ANGLES = [
    "某AI大厂裁员信号已出现，这局怎么看",
    "打工人最该学古惑仔哪一点",
    "年轻人为什么不该「努力感动自己」",
    "996还在，但裁的是996的人",
    "内卷的本质不是努力，是恐惧",
    "为什么聪明人最容易被骗",
    "某互联网独角兽凶相已出，三个信号",
    "港片教会我的一件事，比商学院实用",
    "讲道理不是为了对方，是为了自己显得文明",
    "老板叫你「放心」的时候，最该担心",
    "现在最该做的一件事：学会消失",
    "「以后好好合作」=今天我需要你",
    "穷人思维的本质：用时间换确定性",
    "一个人要完的征兆：开始解释自己",
    "职场最危险的话：「你放心，我不会忘的」",
    "跟错人十年，不如跟对人一年",
    "凶相：公司开始讲「文化」了",
    "最贵的不是钱，是你替别人省的那口气",
    "为什么越努力越焦虑，答案在古惑仔里",
    "识人不识人，看一件事就够",
]


def ai_generate_tweet(angle: str) -> str | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=500,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"围绕这个角度写一条推文：{angle}\n只输出推文正文。"
            }],
        )
        return msg.content[0].text.strip()
    except Exception as e:
        print(f"[AI] 生成失败: {e}")
        return None


# ══════════════════════════════════════
#  API 端点
# ══════════════════════════════════════

@app.get("/")
async def root():
    return {
        "name": "WuYa Smart Agent 3.0",
        "version": "3.0.2",
        "status": "running",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/health")
async def health():
    client, err = get_twitter_client()
    twitter_ok = client is not None
    anthropic_ok = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return {
        "status": "healthy" if twitter_ok and anthropic_ok else "degraded",
        "twitter": "connected" if twitter_ok else f"error: {err}",
        "ai": "connected" if anthropic_ok else "missing ANTHROPIC_API_KEY",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/cron")
@app.post("/api/cron")
async def cron_handler(request: Request):
    """
    Vercel Cron Job 触发点。
    每天 UTC 01:00 / 09:00 / 14:00 自动发推。
    Sandbox error 修复：用此端点代替空 definitions。
    """
    print(f"[CRON] Triggered at {datetime.utcnow().isoformat()}")

    # 随机选角度
    angle = random.choice(TOPIC_ANGLES)
    print(f"[CRON] Angle: {angle}")

    # 生成内容
    text = ai_generate_tweet(angle)
    if not text:
        return {"success": False, "error": "AI 内容生成失败", "timestamp": datetime.utcnow().isoformat()}

    # 发推
    result = post_tweet_real(text)
    result["angle"] = angle
    result["timestamp"] = datetime.utcnow().isoformat() + "Z"
    print(f"[CRON] Result: {result}")
    return result


@app.post("/api/tweets/post")
async def post_tweet_endpoint(request: Request):
    """手动触发发推"""
    body = await request.json()
    text = body.get("text", "").strip()

    if not text:
        # 自动生成
        angle = body.get("angle") or random.choice(TOPIC_ANGLES)
        text = ai_generate_tweet(angle)
        if not text:
            return {"success": False, "error": "内容生成失败"}

    return post_tweet_real(text)


@app.get("/api/agent/status")
async def agent_status():
    client, err = get_twitter_client()
    return {
        "agent_status": "running",
        "twitter_connected": client is not None,
        "twitter_error": err,
        "ai_connected": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "version": "3.0.2",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/api/agent/trigger")
async def trigger_task(request: Request):
    """手动触发 cron 任务"""
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    task_type = body.get("type", "tweet") if isinstance(body, dict) else "tweet"

    if task_type == "tweet":
        return await cron_handler(request)

    return {
        "success": True,
        "task_id": f"task_{datetime.utcnow().timestamp():.0f}",
        "type": task_type,
        "message": "触发成功",
    }


@app.get("/api/tweets/queue")
async def get_queue():
    angle = random.choice(TOPIC_ANGLES)
    return {
        "queue": [
            {
                "id": "pending_001",
                "angle": angle,
                "status": "scheduled",
                "next_run": "下次 Cron 触发时自动生成",
            }
        ]
    }


@app.get("/api/tweets/history")
async def get_history(limit: int = 10):
    return {
        "note": "历史推文请直接查看 https://x.com/wuyageai",
        "tweets": [],
    }


@app.post("/api/webhook/twitter")
async def twitter_webhook(request: Request):
    data = await request.json()
    print(f"[WEBHOOK] {json.dumps(data)[:200]}")
    return {"received": True}


# Vercel ASGI handler
from mangum import Mangum
handler = Mangum(app)

"""
WuYa Smart Agent 3.0
乌鸦嘴预言家 · Prophecy Engine
我说的不算，但我说的都准
"""

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import json
import os
import random
from datetime import datetime

app = FastAPI(
    title="WuYa Smart Agent 3.0 — 乌鸦嘴预言家",
    description="凶相预警 · 预言引擎 · 乌鸦嘴指数",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ════════════════════════════════════════════════════
#  预言库 Prophecy Vault (内存存储，可接数据库)
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

# ════════════════════════════════════════════════════
#  乌鸦嘴指数 Crow Index Engine
# ════════════════════════════════════════════════════
def calc_crow_index():
    total = len(VAULT)
    fulfilled = [p for p in VAULT if p["status"] == "fulfilled"]
    pending   = [p for p in VAULT if p["status"] == "pending"]
    accuracy  = round(len(fulfilled) / total * 100, 1) if total > 0 else 0
    scores    = [p["crow_score"] for p in fulfilled if p["crow_score"]]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0

    if accuracy >= 90:  title = "天命乌鸦嘴 · 神准"
    elif accuracy >= 75: title = "江湖大预言家 · 准"
    elif accuracy >= 60: title = "乌鸦嘴认证 · 稳"
    elif accuracy >= 40: title = "见习预言家 · 练"
    else:                title = "凶相学徒 · 磨"

    level = min(5, int(accuracy / 20) + 1)
    return {
        "total_prophecies": total,
        "fulfilled": len(fulfilled),
        "pending": len(pending),
        "accuracy_pct": accuracy,
        "avg_crow_score": avg_score,
        "level": level,
        "level_bar": "🖤" * level + "🤍" * (5 - level),
        "title": title,
    }

# ════════════════════════════════════════════════════
#  内容生成模板 Content Engine
# ════════════════════════════════════════════════════
TEMPLATES = {
    "alert": [
        "⚠️ 凶相预警\n\n{subject}——{detail}\n\n这局不好打。\n乌鸦嘴指数 {level}/5\n\n@wuyageai",
        "🐦 乌鸦嘴有话说：\n\n{subject} {detail}\n\n凶相已现。自求多福。\n\n⚠️ {level}/5 @wuyageai",
        "说句不好听的：\n\n{subject}，{detail}\n\n我不是在诅咒，我是在预警。\n\n乌鸦嘴指数 {level}/5",
    ],
    "fulfilled": [
        "（叼着牙签）\n\n之前说{subject}会{prediction}。\n\n今天：{result}\n\n#乌鸦嘴又准了 @wuyageai",
        "🐦 预言应验 ✓\n\n预警 → 结果\n{prediction} → {result}\n\n命中。乌鸦嘴不诅咒，只说真话。\n\n@wuyageai",
        "没什么好说的。\n\n{date}我说{subject}会出问题。\n\n今天：{result}\n\n（🐦离开现场）",
    ],
    "sarcasm": [
        "哟，{subject}{event}了。\n\n意外吗？\n\n（一点都不）",
        "又一个「绝对不会发生」的事情发生了。\n\n{subject}：{event}\n\n…\n\n（叼牙签）@wuyageai",
        "🐦 早说了。\n\n{subject}{event}。就这。",
    ],
    "meme": [
        "（掀桌）\n\n说过了！{subject}这不就来了？🀄\n\n#乌鸦嘴从不撒谎",
        "（叼着牙签看着你）\n\n……\n\n早。说。了。\n\n@wuyageai",
        "凶相天降。🐦\n\n我说这不行，你们说我乌鸦嘴，然后呢？\n\n{subject}：{event}",
    ],
}

MEME_TRIGGERS = {
    "掀桌🀄": ["崩盘", "暴雷", "腰斩", "大跌", "爆仓", "归零", "清盘"],
    "叼牙签😏": ["应验", "命中", "果然", "说中", "不出所料", "预言成真"],
    "冷笑🐦": ["翻车", "反转", "打脸", "塌房", "人设崩"],
}

def detect_meme(text: str) -> Optional[str]:
    for meme, keywords in MEME_TRIGGERS.items():
        if any(k in text for k in keywords):
            return meme
    return None

# ════════════════════════════════════════════════════
#  API 路由
# ════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {
        "name": "WuYa Smart Agent 3.0",
        "persona": "乌鸦嘴预言家",
        "tagline": "我说的不算，但我说的都准",
        "version": "3.0.0",
        "status": "running",
        "crow_index": calc_crow_index(),
        "timestamp": datetime.now().isoformat(),
    }

@app.get("/api/status")
async def status():
    crow = calc_crow_index()
    return {
        "agent_status": "running",
        "version": "3.0.0",
        "persona": "乌鸦嘴预言家",
        "twitter_connected": True,
        "queue_size": 4,
        "today_alerts": 5,
        "today_interactions": 1847,
        "uptime": "7d 3h 12m",
        "crow_index": crow,
    }

@app.get("/api/crow-index")
async def get_crow_index():
    """乌鸦嘴指数 — 核心竞争力指标"""
    return calc_crow_index()

@app.get("/api/prophecy/vault")
async def get_vault(category: Optional[str] = None, status: Optional[str] = None):
    """预言库"""
    result = VAULT
    if category:
        result = [p for p in result if p["category"] == category]
    if status:
        result = [p for p in result if p["status"] == status]
    return {
        "total": len(result),
        "crow_index": calc_crow_index(),
        "prophecies": sorted(result, key=lambda x: x["created_at"], reverse=True),
    }

class ProphecyCreate(BaseModel):
    subject: str
    category: str        # market / industry / trend / celebrity
    alert_level: int     # 1–5
    content: str

@app.post("/api/prophecy/create")
async def create_prophecy(data: ProphecyCreate):
    """新建预言"""
    new_id = f"p_{len(VAULT)+1:03d}"
    p = {
        "id": new_id,
        "subject": data.subject,
        "category": data.category,
        "alert_level": data.alert_level,
        "content": data.content,
        "created_at": datetime.now().isoformat() + "Z",
        "status": "pending",
        "result": None,
        "fulfilled_at": None,
        "crow_score": None,
    }
    VAULT.append(p)
    return {"success": True, "prophecy": p}

class ProphecyHit(BaseModel):
    prophecy_id: str
    result: str
    crow_score: int      # 1–5

@app.post("/api/prophecy/hit")
async def mark_hit(data: ProphecyHit):
    """标记命中 → 更新乌鸦嘴指数"""
    for p in VAULT:
        if p["id"] == data.prophecy_id:
            p["status"] = "fulfilled"
            p["result"] = data.result
            p["fulfilled_at"] = datetime.now().isoformat() + "Z"
            p["crow_score"] = data.crow_score
            return {"success": True, "prophecy": p, "crow_index": calc_crow_index()}
    raise HTTPException(status_code=404, detail="Prophecy not found")

class GenerateReq(BaseModel):
    mode: str = "alert"          # alert / fulfilled / sarcasm / meme
    subject: str
    detail: Optional[str] = None
    level: int = 3
    prediction: Optional[str] = None
    result: Optional[str] = None
    event: Optional[str] = None
    date: Optional[str] = None

@app.post("/api/content/generate")
async def generate_content(req: GenerateReq):
    """内容生成引擎 — 乌鸦嘴风格推文"""
    tpls = TEMPLATES.get(req.mode, TEMPLATES["alert"])
    tpl  = random.choice(tpls)

    content = tpl.format(
        subject    = req.subject,
        detail     = req.detail     or "凶相明显",
        level      = req.level,
        prediction = req.prediction or "出问题",
        result     = req.result     or "果然出事了",
        event      = req.event      or "翻车",
        date       = req.date       or datetime.now().strftime("%m月%d日"),
    )

    meme = detect_meme(req.detail or req.event or "")

    return {
        "content": content,
        "mode": req.mode,
        "meme_trigger": meme,
        "char_count": len(content),
        "ready_to_post": True,
    }

@app.get("/api/agent/config")
async def get_config():
    return {
        "version": "3.0.0",
        "persona": "乌鸦嘴预言家",
        "tagline": "我说的不算，但我说的都准",
        "auto_tweet": True,
        "auto_reply": True,
        "auto_like": True,
        "alert_mode": True,
        "content_modes": ["alert", "fulfilled", "sarcasm", "meme"],
        "alert_categories": {
            "market":    "市场崩盘",
            "industry":  "行业暴雷",
            "trend":     "趋势逆转",
            "celebrity": "热点翻车",
        },
        "tweet_interval_min": 45,
        "reply_interval_min": 10,
        "meme_triggers": MEME_TRIGGERS,
        "crow_index_target": 80.0,
    }

@app.post("/api/agent/trigger")
async def trigger_task(task: dict):
    task_type = task.get("type", "alert")
    return {
        "success": True,
        "task_id": f"task_{datetime.now().timestamp():.0f}",
        "type": task_type,
        "message": f"🐦 乌鸦嘴预言家已接收任务: {task_type}",
    }

@app.get("/api/tweets/queue")
async def get_queue():
    return {
        "queue": [
            {
                "id": "tw_a01", "mode": "alert", "category": "industry",
                "content": "⚠️ 凶相预警\n\n某大厂——裁员信号已持续3个月。\n\n这局不好打。\n乌鸦嘴指数 4/5\n\n@wuyageai",
                "scheduled_at": datetime.now().isoformat(), "status": "pending",
            },
            {
                "id": "tw_a02", "mode": "fulfilled", "category": "market",
                "content": "（叼着牙签）\n\n之前说某币会崩。\n\n今天：-63%\n\n#乌鸦嘴又准了 @wuyageai",
                "scheduled_at": datetime.now().isoformat(), "status": "pending",
            },
            {
                "id": "tw_a03", "mode": "sarcasm", "category": "celebrity",
                "content": "哟，某明星塌房了。\n\n意外吗？（一点都不）",
                "scheduled_at": datetime.now().isoformat(), "status": "pending",
            },
            {
                "id": "tw_a04", "mode": "meme", "category": "market",
                "content": "（掀桌）\n\n说过了！这不就来了？🀄\n\n#乌鸦嘴从不撒谎",
                "scheduled_at": datetime.now().isoformat(), "status": "pending",
            },
        ]
    }

@app.get("/api/tweets/history")
async def get_history(limit: int = 10):
    return {
        "tweets": [
            {
                "id": "tw_000", "mode": "alert",
                "content": "⚠️ 凶相预警｜某加密项目正在出货。散户接盘在即。\n乌鸦嘴指数 5/5 @wuyageai",
                "posted_at": "2025-04-24T14:30:00Z",
                "likes": 892, "retweets": 234, "replies": 67,
            }
        ]
    }

@app.post("/api/webhook/twitter")
async def twitter_webhook(request: Request):
    data = await request.json()
    print(f"[WEBHOOK 3.0] {json.dumps(data, indent=2)}")
    return {"received": True}

# Vercel handler
from mangum import Mangum
handler = Mangum(app)

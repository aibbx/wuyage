from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
import json
import os
from datetime import datetime

app = FastAPI(title="WuYa Smart Agent 2.0 API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "name": "WuYa Smart Agent 2.0",
        "version": "2.0.0",
        "status": "running",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/status")
async def status():
    return {
        "agent_status": "running",
        "twitter_connected": True,
        "queue_size": 5,
        "today_tweets": 12,
        "today_interactions": 847,
        "uptime": "3d 12h 45m"
    }

@app.post("/api/webhook/twitter")
async def twitter_webhook(request: Request):
    """接收 Twitter webhook 事件"""
    data = await request.json()
    print(f"[WEBHOOK] Twitter event: {json.dumps(data, indent=2)}")
    return {"received": True}

@app.post("/api/agent/trigger")
async def trigger_task(task: dict):
    """手动触发 Agent 任务"""
    task_type = task.get("type", "tweet")
    print(f"[TRIGGER] Task: {task_type}")
    return {
        "success": True,
        "task_id": f"task_{datetime.now().timestamp()}",
        "type": task_type
    }

@app.get("/api/agent/config")
async def get_config():
    """获取 Agent 配置"""
    return {
        "auto_tweet": True,
        "auto_reply": True,
        "auto_like": True,
        "tweet_interval_min": 30,
        "reply_interval_min": 15,
        "personality": "乌鸦哥 - 霸气江湖风格"
    }

@app.get("/api/tweets/queue")
async def get_queue():
    """获取待发送队列"""
    return {
        "queue": [
            {
                "id": "tw_001",
                "content": "兄弟们！今天研究了下最新的 AI 模型...",
                "scheduled_at": "2024-01-15T16:00:00Z",
                "status": "pending"
            },
            {
                "id": "tw_002",
                "content": "刚刚看到个有趣的观点：未来不会用 AI 的人...",
                "scheduled_at": "2024-01-15T19:00:00Z",
                "status": "pending"
            }
        ]
    }

@app.get("/api/tweets/history")
async def get_history(limit: int = 10):
    """获取发送历史"""
    return {
        "tweets": [
            {
                "id": "tw_000",
                "content": "粉丝们！乌鸦哥有话说...",
                "posted_at": "2024-01-15T14:30:00Z",
                "likes": 45,
                "retweets": 12,
                "replies": 8
            }
        ]
    }

# Vercel handler
from mangum import Mangum
handler = Mangum(app)
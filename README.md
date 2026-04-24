# 🐦‍⬛ 乌鸦哥 WuYa Smart Agent 2.0

WuYa Smart Agent 2.0 是一个 AI 驱动的社交媒体智能代理系统。

## 🏗️ 架构

```
wuyage.ai
├── / → 官网首页 (website/)
├── /dashboard → 控制台 (dashboard/)
└── /api/* → API 接口 (api/)
```

## 🚀 部署

### 1. 安装 Vercel CLI
```bash
npm i -g vercel
```

### 2. 登录 Vercel
```bash
vercel login
```

### 3. 部署
```bash
vercel --prod
```

## 🔧 环境变量

在 Vercel Dashboard → Settings → Environment Variables 中设置：

- `ANTHROPIC_API_KEY` - Claude API Key
- `TWITTER_BEARER_TOKEN` - Twitter API Bearer Token
- `TWITTER_API_KEY` - Twitter API Key
- `TWITTER_API_SECRET` - Twitter API Secret

## 📁 目录结构

```
.
├── api/
│   └── index.py          # FastAPI 后端
├── website/
│   └── index.html        # 官网首页
├── dashboard/
│   └── index.html        # 控制台
├── vercel.json           # Vercel 配置
└── requirements.txt      # Python 依赖
```
# -*- coding: utf-8 -*-
"""
主应用文件 - 使用Flask Blueprint整合所有API服务
整合了：
- 每日AI简报 API (daily-report)
- KPI 概览接口 (data-cards) 
- 新闻 API (news)
- 地图模块 API (databoard-map)
- 数据模块 API (databoard-data)
"""

import os
import sys
import json
from flask import Flask
from flask_cors import CORS

# 确保可以导入项目根目录下的 infra 包
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def _load_env_file(path: str) -> list[str]:
    if not os.path.isfile(path):
        return []
    loaded_keys = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded_keys.append(key)
    return loaded_keys


def _load_env() -> None:
    base_dir = os.path.dirname(__file__)
    root_dir = os.path.abspath(os.path.join(base_dir, ".."))
    env_paths = [
        os.path.join(base_dir, ".env"),
        os.path.join(root_dir, ".env"),
    ]
    for path in env_paths:
        loaded = _load_env_file(path)
        if os.path.isfile(path):
            if loaded:
                print(f"[INFO] loaded env file: {path} ({len(loaded)} keys)")
            else:
                print(f"[INFO] env file present but no new keys loaded: {path}")


_load_env()

if os.getenv("TAVILY_API_KEY"):
    print("[INFO] TAVILY_API_KEY detected")
else:
    print("[WARN] TAVILY_API_KEY not set")

# 导入各个Blueprint
from backend_api.daily_report_bp import daily_report_bp
from backend_api.data_cards_bp import data_cards_bp
from backend_api.news_bp import news_bp
from backend_api.databoard_map_bp import databoard_map_bp
from backend_api.databoard_data_bp import databoard_data_bp
from backend_api.agent_report_bp import agent_report_bp, get_agent_initial_report
from backend_api.agent_chat_bp import agent_chat_bp
from backend_api.user_bp import user_bp

# 创建Flask应用
app = Flask(__name__)

# 配置 JSON 编码，支持中文显示
app.config['JSON_AS_ASCII'] = False
app.config['JSONIFY_PRETTYPRINT_REGULAR'] = True

# 自定义 JSON 编码器，确保中文字符正确显示
class CustomJSONEncoder(json.JSONEncoder):
    def __init__(self, **kwargs):
        kwargs['ensure_ascii'] = False
        super(CustomJSONEncoder, self).__init__(**kwargs)

app.json_encoder = CustomJSONEncoder

# 配置 CORS 解决跨域问题
default_allowed_origins = [
    'http://localhost:9528',
    'http://127.0.0.1:9528',
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://116.62.34.152:7002',
    'https://116.62.34.152',
]
allowed_origins_env = os.getenv("ALLOWED_ORIGINS")
if allowed_origins_env:
    allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]
    if not allowed_origins:
        allowed_origins = default_allowed_origins
else:
    allowed_origins = default_allowed_origins
# 支持本地和线上 HTTPS 访问
CORS(
    app,
    origins=allowed_origins,
    methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    allow_headers=['Content-Type', 'Authorization', 'X-Requested-With', 'X-Token'],
    supports_credentials=True
)

# 注册Blueprint
app.register_blueprint(daily_report_bp, url_prefix='/api/dashboard')
app.register_blueprint(data_cards_bp, url_prefix='/api/dashboard')
app.register_blueprint(news_bp, url_prefix='/api/dashboard')
app.register_blueprint(databoard_map_bp, url_prefix='/api/databoard/map')
app.register_blueprint(databoard_data_bp, url_prefix='/api/databoard/data')
app.register_blueprint(user_bp, url_prefix='/api')
app.register_blueprint(agent_report_bp, url_prefix='/api/agent')
app.register_blueprint(agent_chat_bp, url_prefix='/api/agent')

# 兼容旧路径：/agent/initial-report
@app.route("/agent/initial-report", methods=["GET"])
def agent_initial_report_alias():
    return get_agent_initial_report()

# 健康检查接口
@app.route("/healthz", methods=["GET"])
def healthz():
    return {"ok": True, "service": "unified-api"}

@app.route("/", methods=["GET"])
def index():
    return {
        "message": "统一API服务",
        "services": [
            "每日AI简报: /api/dashboard/daily-report",
            "KPI概览: /api/dashboard/data-cards", 
            "新闻服务: /api/dashboard/news",
            "地图模块: /api/databoard/map",
            "数据模块: /api/databoard/data",
            "用户认证: /api/user/login, /api/user/info, /api/user/logout",
            "智能体聊天: /api/agent/chat, /api/agent/chat/stream"
        ]
    }

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Unified API Service")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "5001")), help="Port to run the Flask server")
    args = parser.parse_args()
    port = args.port

    print(f"✅ 启动统一API服务：http://127.0.0.1:{port}")
    print(f"📊 每日AI简报: http://127.0.0.1:{port}/api/dashboard/daily-report")
    print(f"📈 KPI概览: http://127.0.0.1:{port}/api/dashboard/data-cards")
    print(f"📰 新闻服务: http://127.0.0.1:{port}/api/dashboard/news")
    print(f"🗺️ 地图模块: http://127.0.0.1:{port}/api/databoard/map")
    print(f"📊 数据模块: http://127.0.0.1:{port}/api/databoard/data")
    print(f"👤 用户认证: http://127.0.0.1:{port}/api/user/login")
    print(f"💬 智能体聊天: http://127.0.0.1:{port}/api/agent/chat")

    app.run(host="0.0.0.0", port=port, debug=True)

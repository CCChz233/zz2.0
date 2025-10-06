# -*- coding: utf-8 -*-
"""
主应用文件 - 使用Flask Blueprint整合所有API服务
整合了：
- 每日AI简报 API (daily-report)
- KPI 概览接口 (data-cards) 
- 新闻 API (news)
"""

import os
import json
from flask import Flask
from flask_cors import CORS

# 导入各个Blueprint
from backend_api.daily_report_bp import daily_report_bp
from backend_api.data_cards_bp import data_cards_bp
from backend_api.news_bp import news_bp
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
CORS(app, 
     origins=['http://localhost:9528', 'http://127.0.0.1:9528', 'http://localhost:3000', 'http://127.0.0.1:3000'],
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization', 'X-Requested-With', 'X-Token'],
     supports_credentials=True)

# 注册Blueprint
app.register_blueprint(daily_report_bp, url_prefix='/api/dashboard')
app.register_blueprint(data_cards_bp, url_prefix='/api/dashboard')
app.register_blueprint(news_bp, url_prefix='/api/dashboard')
app.register_blueprint(user_bp, url_prefix='/api')

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
            "用户认证: /api/user/login, /api/user/info, /api/user/logout"
        ]
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"✅ 启动统一API服务：http://127.0.0.1:{port}")
    print(f"📊 每日AI简报: http://127.0.0.1:{port}/api/dashboard/daily-report")
    print(f"📈 KPI概览: http://127.0.0.1:{port}/api/dashboard/data-cards")
    print(f"📰 新闻服务: http://127.0.0.1:{port}/api/dashboard/news")
    print(f"👤 用户认证: http://127.0.0.1:{port}/api/user/login")
    app.run(host="0.0.0.0", port=port, debug=True)

# -*- coding: utf-8 -*-
"""
Flask 后端：用户认证 API Blueprint
依赖:
    pip install flask flask_cors
"""

import json
from flask import Blueprint, request, jsonify, make_response

# ====== 初始化 ======
user_bp = Blueprint('user', __name__)

# ====== 用户认证相关 ======
# 模拟用户数据
tokens = {
    "admin": {
        "token": "admin-token"
    },
    "editor": {
        "token": "editor-token"
    }
}

users = {
    "admin-token": {
        "roles": ["admin"],
        "introduction": "I am a super administrator",
        "avatar": "https://wpimg.wallstcn.com/f778738c-e4f8-4870-b634-56703b4acafe.gif",
        "name": "Super Admin"
    },
    "editor-token": {
        "roles": ["editor"],
        "introduction": "I am an editor",
        "avatar": "https://wpimg.wallstcn.com/f778738c-e4f8-4870-b634-56703b4acafe.gif",
        "name": "Normal Editor"
    }
}

@user_bp.route("/user/login", methods=["POST"])
def user_login():
    """用户登录接口"""
    data = request.get_json()
    username = data.get("username") if data else None
    
    if not username:
        error_data = {
            "code": 400,
            "message": "Username is required"
        }
        response = make_response(
            json.dumps(error_data, ensure_ascii=False, indent=2)
        )
        response.status_code = 400
        response.mimetype = 'application/json; charset=utf-8'
        return response
    
    # 查找用户token
    token_info = tokens.get(username)
    
    # 模拟错误：用户不存在
    if not token_info:
        error_data = {
            "code": 60204,
            "message": "Account and password are incorrect."
        }
        response = make_response(
            json.dumps(error_data, ensure_ascii=False, indent=2)
        )
        response.status_code = 200
        response.mimetype = 'application/json; charset=utf-8'
        return response
    
    # 登录成功，返回token
    success_data = {
        "code": 20000,
        "data": token_info
    }
    response = make_response(
        json.dumps(success_data, ensure_ascii=False, indent=2)
    )
    response.status_code = 200
    response.mimetype = 'application/json; charset=utf-8'
    return response

@user_bp.route("/user/info", methods=["GET"])
def get_user_info():
    """获取用户信息接口"""
    token = request.args.get("token")
    
    if not token:
        error_data = {
            "code": 400,
            "message": "Token is required"
        }
        response = make_response(
            json.dumps(error_data, ensure_ascii=False, indent=2)
        )
        response.status_code = 400
        response.mimetype = 'application/json; charset=utf-8'
        return response
    
    # 查找用户信息
    user_info = users.get(token)
    
    # 模拟错误：token无效
    if not user_info:
        error_data = {
            "code": 50008,
            "message": "Login failed, unable to get user details."
        }
        response = make_response(
            json.dumps(error_data, ensure_ascii=False, indent=2)
        )
        response.status_code = 200
        response.mimetype = 'application/json; charset=utf-8'
        return response
    
    # 返回用户信息
    success_data = {
        "code": 20000,
        "data": user_info
    }
    response = make_response(
        json.dumps(success_data, ensure_ascii=False, indent=2)
    )
    response.status_code = 200
    response.mimetype = 'application/json; charset=utf-8'
    return response

@user_bp.route("/user/logout", methods=["POST"])
def user_logout():
    """用户登出接口"""
    success_data = {
        "code": 20000,
        "data": "success"
    }
    response = make_response(
        json.dumps(success_data, ensure_ascii=False, indent=2)
    )
    response.status_code = 200
    response.mimetype = 'application/json; charset=utf-8'
    return response

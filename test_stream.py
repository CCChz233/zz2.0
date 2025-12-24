#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试统一 LLM 流式传输（基于 infra.llm.chat）
"""

import json
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from infra.llm import chat


def test_qwen_stream():
    """测试统一大模型流式传输"""
    messages = [
        {"role": "user", "content": "请用一句话介绍你自己，然后数数从1到10"}
    ]

    print("🚀 开始测试统一 LLM 流式传输...")
    print("-" * 50)

    try:
        response = chat(messages, stream=True)
        print("✅ 连接成功，开始接收流式数据...\n")

        chunk_count = 0
        full_content = ""
        
        for line in response.iter_lines():
            if not line:
                continue
            
            line_str = line.decode("utf-8")
            
            # 跳过空行和注释
            if not line_str.strip() or line_str.startswith(':'):
                continue
            
            # 移除 "data: " 前缀
            if line_str.startswith("data: "):
                line_str = line_str[6:]
            
            # 检查结束标记
            if line_str.strip() == "[DONE]":
                print("\n✅ 流式传输完成")
                break
            
            try:
                chunk_data = json.loads(line_str)
                chunk_count += 1
                
                # 尝试多种格式解析
                content = ""
                
                # OpenAI兼容格式
                if "choices" in chunk_data and len(chunk_data["choices"]) > 0:
                    delta = chunk_data["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                
                # DashScope格式
                elif "output" in chunk_data:
                    output = chunk_data["output"]
                    if "choices" in output and len(output["choices"]) > 0:
                        choice = output["choices"][0]
                        if "delta" in choice:
                            content = choice["delta"].get("content", "")
                        elif "message" in choice:
                            content = choice["message"].get("content", "")
                        elif "text" in choice:
                            content = choice.get("text", "")
                    elif "text" in output:
                        content = output.get("text", "")
                
                # 直接文本格式
                elif "text" in chunk_data:
                    content = chunk_data.get("text", "")
                
                if content:
                    full_content += content
                    # 实时打印，模拟流式效果
                    print(content, end='', flush=True)
                else:
                    # 打印原始数据用于调试
                    if chunk_count <= 3:
                        print(f"\n[调试] Chunk {chunk_count} 原始数据: {json.dumps(chunk_data, ensure_ascii=False)[:100]}")
                    
            except json.JSONDecodeError as e:
                print(f"\n⚠️ JSON解析失败: {e}")
                print(f"原始行: {line_str[:100]}")
            except Exception as e:
                print(f"\n⚠️ 处理出错: {e}")
        
        print(f"\n\n📊 统计信息:")
        print(f"  - 接收chunk数量: {chunk_count}")
        print(f"  - 总内容长度: {len(full_content)}")
        print(f"  - 完整内容: {full_content[:200]}...")
        
        if chunk_count > 1:
            print("✅ 流式传输正常工作！")
        else:
            print("⚠️ 警告：只收到1个chunk，可能不是流式传输")
            
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_qwen_stream()

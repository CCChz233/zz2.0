from typing import Dict, List

SUMMARY_LIMIT = 500


def _truncate(text: str, limit: int = SUMMARY_LIMIT) -> str:
    text = (text or "").strip()
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def build_evidence_block(items: List[Dict]) -> str:
    """Format retrieval results into an evidence string for prompting."""
    if not items:
        return "未检索到相关事件。若证据不足，请直接说明“当前事件库未查到足够信息”，不要编造。"

    lines: List[str] = ["以下为检索到的相关事件，请仅基于这些信息回答："]
    for idx, item in enumerate(items, start=1):
        title = item.get("title") or "未提供标题"
        url = item.get("url") or ""
        summary = _truncate(item.get("summary", ""))
        similarity = item.get("similarity")
        sim_text = f"{float(similarity):.3f}" if similarity is not None else "未知"
        published_at = item.get("published_at") or "时间未知"
        source = item.get("source") or "来源未知"

        header = f"{idx}. {title}（时间：{published_at}，来源：{source}，相似度：{sim_text}）"
        if url:
            header += f" | 链接：{url}"
        lines.append(header)
        if summary:
            lines.append(f"   摘要：{summary}")

    return "\n".join(lines)


def build_messages_with_evidence(user_question: str, items: List[Dict]) -> List[Dict[str, str]]:
    """
    构造包含证据块的消息列表，供 LLM 使用。
    返回形如：
    [
      {"role":"system","content":"系统提示+证据块"},
      {"role":"user","content": user_question}
    ]
    """
    evidence_block = build_evidence_block(items)
    system_content = (
        "你是面向事实的助手。仅根据提供的证据回答，禁止编造。"
        "若证据不足，请直接说明“当前事件库未查到足够信息”。"
        "回答保持简洁、分点，必要时引用事件标题或时间并附上链接。\n\n"
        f"【证据】\n{evidence_block}"
    )
    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_question},
    ]


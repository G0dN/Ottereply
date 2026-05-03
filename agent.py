import requests
from loguru import logger
from config import settings
from utils import sanitize_reply


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    url = f"{settings.LLM_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.8,
        "max_tokens": 300,
    }

    logger.info("LLM request to {} model={}", url, settings.LLM_MODEL)
    r = requests.post(url, json=payload, headers=headers, timeout=30)

    if not r.ok:
        logger.error(
            "LLM HTTP {}: {}",
            r.status_code,
            r.text[:500],
        )
        r.raise_for_status()

    try:
        data = r.json()
    except ValueError:
        logger.error("LLM response not JSON: {!r}", r.text[:500])
        raise

    if "choices" not in data:
        logger.error("LLM response missing 'choices': {}", data)
        raise ValueError(f"Unexpected LLM response: {data}")

    content = data["choices"][0]["message"]["content"]
    logger.info("LLM returned {} chars", len(content))
    return content.strip()


def generate_reply(
    source_subject: str = "", source_message: str = "", context: str = ""
) -> str:
    user_prompt = _build_reply_prompt(source_subject, source_message, context)
    try:
        reply = _call_llm(settings.LLM_SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        logger.warning("LLM call failed, using fallback: {}", e)
        reply = _fallback_reply(source_subject, source_message)
    return sanitize_reply(reply)


def generate_followup_reply(
    source_author: str = "", source_subject: str = "", context: str = ""
) -> str:
    user_prompt = _build_followup_prompt(source_author, context)
    try:
        reply = _call_llm(settings.LLM_SYSTEM_PROMPT, user_prompt)
    except Exception as e:
        logger.warning("LLM call failed, using fallback: {}", e)
        reply = _fallback_followup(source_author)
    return sanitize_reply(reply)


def _build_reply_prompt(subject: str, first_post: str, context: str) -> str:
    parts = [f"帖子标题：{subject}"]
    if context:
        parts.append(f"已有讨论：\n{context}")
    else:
        parts.append(f"帖子内容：{first_post}")
    parts.append("请针对以上内容写一个简短回复（2-4句话）。")
    return "\n\n".join(parts)


def _build_followup_prompt(author: str, context: str) -> str:
    parts = []
    if context:
        parts.append(f"已有讨论：\n{context}")
    parts.append(
        f"上一楼是 {author} 引用了你的发言并给出了回复。"
        f"请针对 {author} 的最新回复写一个简短回应（2-4句话）。"
    )
    return "\n\n".join(parts)


def _fallback_reply(subject: str, first_post: str) -> str:
    source_content = first_post or subject or ""
    if source_content:
        return (
            "收到，我来帮你看一下。\n\n"
            "请补充一下具体报错截图、环境版本和复现步骤。\n\n"
            "如果方便，也请说明你的 Discuz 版本和插件列表。"
        )
    return "收到，请问有什么可以帮你的？请详细描述你的问题。"


def _fallback_followup(author: str) -> str:
    return f"to {author}: 收到你的回复，请补充更多细节如报错截图和环境版本。"

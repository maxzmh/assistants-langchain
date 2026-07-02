"""
media 服务：从文本抽取图片 URL、把文本 + 图片装成多模态 content。

约定：本模块纯函数、无 IO、无副作用。上传文件由 router 层预先读成 bytes。
"""
import base64
import re
from typing import List, Optional, Tuple, Union

# 从消息文本里抽取图片 URL：http(s) 结尾为常见图片扩展名，或明显的图床/静态托管路径。
# 只识别 URL 边界很清晰的场景，避免把普通文字里的链接误当图片。
_IMAGE_URL_RE = re.compile(
    r"https?://[^\s<>\"'，,、]+?\.(?:jpg|jpeg|png|webp|gif|bmp)(?:\?[^\s<>\"'，,、]*)?",
    re.IGNORECASE,
)


def extract_image_urls(text: str) -> Tuple[str, List[str]]:
    """从用户文本里抽出图片 URL 列表，返回 (剥离 URL 后的文本, 去重后的 URL 列表)。"""
    urls = _IMAGE_URL_RE.findall(text or "")
    if not urls:
        return text, []
    cleaned = _IMAGE_URL_RE.sub("", text).strip()
    seen: set = set()
    uniq: List[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return cleaned, uniq


def build_content(
    text: str,
    image_bytes: Optional[bytes],
    image_mime: Optional[str],
    urls: List[str],
    original_message: str = "",
) -> Union[str, List[dict]]:
    """组装 LangChain HumanMessage 的 content：

    - 无图片 → 返回原始字符串（等价于 message 本身）。
    - 有图片 → 返回 [{'type':'text',...}, {'type':'image_url',...}, ...]。
      如果 text 为空（用户只上传了图片），给一个默认提示。
    """
    parts: List[dict] = []
    if image_bytes is not None:
        mime = image_mime or "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    for url in urls:
        parts.append({"type": "image_url", "image_url": {"url": url}})

    if not parts:
        # 无图片：直接把原始消息作为字符串给模型（保持与旧行为一致）
        return original_message or text

    text_prompt = text or (original_message.strip() if original_message else "") or "请描述并分析这张图片。"
    return [{"type": "text", "text": text_prompt}] + parts

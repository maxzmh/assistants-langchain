"""
media 服务：从文本抽取图片 URL、把文本 + 图片装成多模态 content。

约定：本模块纯函数、无 IO、无副作用。上传文件由 router 层预先读成 bytes。

图片 URL 识别策略（分两步）：
  A) 结构化语法优先——Markdown ![alt](url) 与 HTML <img src="url">，命中即视为图片。
  B) 剩下的裸 URL 按启发式判别：
     * 后缀是常见图片扩展名（jpg/jpeg/png/webp/gif/bmp/svg/avif/heic/heif/tiff）
     * 或主机匹配常见图床/CDN 白名单（Imgur / 微博 sinaimg / 微信 mmbiz.qpic /
       QQ qlogo / B 站 hdslb / 阿里云 OSS 且 URL 含 x-oss-process=image /
       Cloudinary /image/upload/ / Discord CDN / Twitter pbs 等）

抽出的 URL 会在原始文本中被剥离，避免"URL 文本"跟"图片本身"重复喂给模型。
"""
import base64
import re
from typing import List, Optional, Tuple, Union
from urllib.parse import urlparse

# URL 边界字符：遇到空白、尖括号、引号、中英文逗号顿号即视为结束
_URL_TOKEN = r"https?://[^\s<>\"'，,、]+"

# 1) Markdown 图片：![alt](url)
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\((" + _URL_TOKEN + r")\)")

# 2) HTML <img src="...">
_HTML_IMG_RE = re.compile(
    r"<img\b[^>]*?\bsrc\s*=\s*['\"](" + _URL_TOKEN + r")['\"][^>]*>",
    re.IGNORECASE,
)

# 3) 兜底：文本中任意裸 URL
_ANY_URL_RE = re.compile(_URL_TOKEN)

# 图片扩展名
_IMAGE_EXT_RE = re.compile(
    r"\.(?:jpg|jpeg|png|webp|gif|bmp|svg|avif|heic|heif|tiff)(?:$|[?#])",
    re.IGNORECASE,
)

# 图床/CDN 主机白名单：主机名精确匹配或以下列后缀结尾即视为图片链接。
_IMAGE_HOST_SUFFIXES = (
    "imgur.com",
    "sinaimg.cn",
    "qpic.cn",       # 覆盖 mmbiz.qpic.cn 等
    "qlogo.cn",
    "hdslb.com",     # B 站
    "cdn.discordapp.com",
    "pbs.twimg.com",
)

# 需要额外看路径/查询参数才能判定的主机
def _looks_like_image_url(url: str) -> bool:
    if _IMAGE_EXT_RE.search(url):
        return True
    try:
        p = urlparse(url)
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    if any(host == suf or host.endswith("." + suf) for suf in _IMAGE_HOST_SUFFIXES):
        return True
    # 阿里云 OSS：主机是 *.aliyuncs.com 且带 x-oss-process=image
    if host.endswith("aliyuncs.com") and "x-oss-process=image" in (p.query or ""):
        return True
    # Cloudinary：路径含 /image/upload/
    if host.endswith("cloudinary.com") and "/image/upload/" in (p.path or ""):
        return True
    return False


def extract_image_urls(text: str) -> Tuple[str, List[str]]:
    """从用户文本里抽出图片 URL 列表，返回 (剥离图片指代后的文本, 去重后的 URL 列表)。

    识别顺序：Markdown 图片 → HTML <img> → 启发式裸 URL。
    """
    if not text:
        return text, []

    urls: List[str] = []
    seen: set = set()

    def _push(url: str) -> None:
        if url and url not in seen:
            seen.add(url)
            urls.append(url)

    # A) 结构化语法：命中即算，剥离整段语法
    def _consume_structured(pat: re.Pattern, s: str) -> str:
        def _sub(m: re.Match) -> str:
            _push(m.group(1))
            return ""
        return pat.sub(_sub, s)

    cleaned = _consume_structured(_MD_IMAGE_RE, text)
    cleaned = _consume_structured(_HTML_IMG_RE, cleaned)

    # B) 剩下的裸 URL：命中启发式规则的才算图片，同时把 URL 从文本里剥掉
    def _maybe_image(m: re.Match) -> str:
        url = m.group(0)
        if _looks_like_image_url(url):
            _push(url)
            return ""
        return url  # 非图片 URL 原样保留

    cleaned = _ANY_URL_RE.sub(_maybe_image, cleaned)

    # 收拢多余空白
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    return cleaned, urls


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

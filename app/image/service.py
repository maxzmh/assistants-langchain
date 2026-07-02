"""
文生图服务：调火山方舟 Seedream，下载到本地，返回可回显的相对 URL。

火山方舟兼容 OpenAI `images.generations` 协议，直接复用 `openai.AsyncOpenAI`
指向 `ARK_BASE_URL` 即可。返回的 URL 由火山托管、有效期一般 24h，所以本函数
**立刻把 bytes 拉回来落盘**，前端拿到的一直是本地 `/api/image/file/xxx.png`，
不受上游 URL 过期影响。

对外只有 `generate(prompt, size, style)` 一个函数；HTTP 层薄封装在 router 里。
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from openai import AsyncOpenAI

from app.config import ARK_IMAGE_MODEL, GENERATED_DIR

# —— 风格 prompt 前缀 ——
# 火山图像 API 没有独立的 style 参数（不像 DALL·E 有 vivid / natural），
# 用固定短语拼进 prompt 实现风格化。'natural' = 不拼任何前缀，保持原意。
_STYLE_PROMPTS: dict[str, str] = {
    "natural": "",
    "general": "高质量, 细节丰富, ",
    "anime": "动漫风格, 精美插画, 二次元, ",
    "photo": "写实摄影, 单反相机, 电影级光影, ",
    "watercolor": "水彩画风格, 手绘, 柔和色彩, ",
}

# 允许的画布尺寸白名单：跟前端下拉框对齐。
# Seedream 4.x 要求总像素 >= 3,686,400（约 1920x1920），选项都得高于这个阈值：
#   2048x2048 = 4.19M  (方形 1:1)
#   2560x1440 = 3.69M  (横屏 16:9)
#   1440x2560 = 3.69M  (竖屏 9:16)
#   2400x1600 = 3.84M  (横屏 3:2)
#   1600x2400 = 3.84M  (竖屏 2:3)
# 未来换早期模型再放开小尺寸。任何不在此表的值都会被兜底为默认。
_DEFAULT_SIZE = "2048x2048"
_ALLOWED_SIZES: set[str] = {
    "2048x2048",
    "2560x1440",
    "1440x2560",
    "2400x1600",
    "1600x2400",
}

# openai 客户端单例：与 ChatOpenAI 走同一份 API key / base_url。
# ARK_API_KEY 缺失时 AsyncOpenAI 会在实际调用时报错，不必启动时校验。
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.getenv("ARK_API_KEY"),
            base_url=os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        )
    return _client


@dataclass
class ImageResult:
    """给 router 返回：本地 URL + 落盘绝对路径 + 实际发给模型的 prompt（含风格前缀）。"""
    url: str
    path: Path
    prompt: str


async def generate(prompt: str, size: str = _DEFAULT_SIZE, style: str = "natural") -> ImageResult:
    """文生图：调火山方舟 → 下载 → 落 `static/generated/<uuid>.png`。

    Args:
        prompt: 用户提示词；不含风格前缀，函数内部按 `style` 拼接。
        size: 画布尺寸，必须在白名单里；非法值兜底为 `_DEFAULT_SIZE`。
        style: 风格 key，见 `_STYLE_PROMPTS`；非法值 = natural。

    Returns:
        ImageResult(url, path, prompt) —— `url` 是相对路径 `/api/image/file/xxx.png`，
        可直接放进 message.content 的 `image_url` 段。
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt 不能为空")

    if size not in _ALLOWED_SIZES:
        size = _DEFAULT_SIZE
    prefix = _STYLE_PROMPTS.get(style, "")
    final_prompt = prefix + prompt

    client = _get_client()
    resp = await client.images.generate(
        model=ARK_IMAGE_MODEL,
        prompt=final_prompt,
        size=size,
        response_format="url",  # 火山方舟仅支持 URL；b64_json 不支持
    )
    remote_url = resp.data[0].url
    if not remote_url:
        raise RuntimeError("图像服务未返回 URL")

    # 立刻下载 —— 上游 URL 24h 过期，只有存本地才能长期回显
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.get(remote_url)
        r.raise_for_status()
        payload = r.content

    # 扩展名从 Content-Type 兜底推：多数情况是 image/png
    ct = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(ct, "png")
    name = f"{uuid.uuid4().hex}.{ext}"
    dest = GENERATED_DIR / name
    dest.write_bytes(payload)

    return ImageResult(
        url=f"/api/image/file/{name}",
        path=dest,
        prompt=final_prompt,
    )

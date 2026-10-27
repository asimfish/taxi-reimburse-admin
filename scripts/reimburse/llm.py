"""OpenAI 兼容的对话接口（默认 DeepSeek），只用标准库。

api_key 来源（按顺序）：环境变量 REIMBURSE_LLM_KEY / DEEPSEEK_API_KEY，
或 $REIMBURSE_SECRETS（默认 ~/.config/taxi-reimburse/secrets.json）里的 "llm_api_key"。
"""
import base64
import io
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

SECRETS = Path(os.environ.get("REIMBURSE_SECRETS", Path.home() / ".config" / "taxi-reimburse" / "secrets.json"))


class LLMError(Exception):
    pass


def read_secrets():
    try:
        return json.loads(SECRETS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_secrets(data):
    SECRETS.parent.mkdir(parents=True, exist_ok=True)
    tmp = SECRETS.with_name(SECRETS.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SECRETS)
    os.chmod(SECRETS, 0o600)


def api_key():
    return os.environ.get("REIMBURSE_LLM_KEY") or os.environ.get("DEEPSEEK_API_KEY") or read_secrets().get("llm_api_key", "")


def available(cfg):
    return bool(cfg["llm"].get("enabled") and api_key())


def chat(cfg, messages, model=None, json_mode=True, max_tokens=16000, retries=2):
    key = api_key()
    if not key:
        raise LLMError("未配置模型 API key")
    llm = cfg["llm"]
    body = {"model": model or llm["model"], "messages": messages, "max_tokens": max_tokens, "temperature": 0}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(
        llm["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    # 默认直连，避免服务器上失效的系统代理
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(llm.get("proxies") or {}))
    last = None
    for attempt in range(retries + 1):
        try:
            with opener.open(req, timeout=llm.get("timeout", 300)) as resp:
                data = json.loads(resp.read())
            content = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage", {})
            return (parse_json(content) if json_mode else content), usage
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            last = LLMError(f"模型接口返回 {e.code}：{detail}")
            if e.code in (400, 401, 403):
                break
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError) as e:
            last = LLMError(f"模型接口调用失败：{e}")
        time.sleep(2 * (attempt + 1))
    raise last


def parse_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("模型没有返回 JSON")
    return json.loads(text[start:end + 1])


def image_part(path, max_side=1600):
    from PIL import Image, ImageOps

    if Path(path).suffix.lower() in (".heic", ".heif"):
        from pillow_heif import register_heif_opener

        register_heif_opener()
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if max(img.size) > max_side:
        k = max_side / max(img.size)
        img = img.resize((round(img.width * k), round(img.height * k)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()}}

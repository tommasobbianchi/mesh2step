"""DeepSeek vision, called directly (OpenAI-compatible API) instead of through `opencode run`.

`opencode run -f <image>` stalls at "init" on nativedev (2026-09-14: text prompts answer, image prompts hang
past 280 s from any directory), so the image question goes straight to the API with the credential opencode
already stores. Model choice measured on the Bracket_40 hole close-ups: deepseek-v4-flash-vision-exp named
both countersinks (43 s); deepseek-flash (V4.1 Flash) called one of them counterbored (14 s).

usage: python3 vlm_api.py "<question>" <image> [model]      prints the model's reply
"""
import base64
import json
import mimetypes
import os
import sys
import urllib.request

URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash-vision-exp"


def ask(question: str, image_path: str, model: str = DEFAULT_MODEL, timeout: float = 180.0) -> str:
    key = json.load(open(os.path.expanduser("~/.local/share/opencode/auth.json")))["deepseek"]["key"]
    mime = mimetypes.guess_type(image_path)[0] or "image/png"
    data = base64.b64encode(open(image_path, "rb").read()).decode()
    body = json.dumps({"model": model, "temperature": 0.1, "messages": [{"role": "user", "content": [
        {"type": "text", "text": question},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}]}]}).encode()
    req = urllib.request.Request(URL, body, {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))["choices"][0]["message"]["content"]


if __name__ == "__main__":
    print(ask(sys.argv[1], sys.argv[2], *(sys.argv[3:4] or [])))

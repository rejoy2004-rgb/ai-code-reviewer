# test_openrouter.py

import httpx
from app.config.settings import settings

headers = {
    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
}

payload = {
    "model": settings.OPENROUTER_MODEL,
    "messages": [
        {
            "role": "user",
            "content": "Say hello"
        }
    ]
}

response = httpx.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers=headers,
    json=payload,
    timeout=60
)

print(response.status_code)
print(response.text)
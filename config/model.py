import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


AGNES_API_KEY = os.getenv("AGNES_API_KEY")
AGNES_BASE_URL = os.getenv(
    "AGNES_BASE_URL",
    "https://apihub.agnes-ai.com/v1",
)
AGNES_MODEL = os.getenv(
    "AGNES_MODEL",
    "agnes-2.5-flash",
)


if not AGNES_API_KEY:
    raise RuntimeError(
        "AGNES_API_KEY is not configured."
    )


client = OpenAI(
    api_key=AGNES_API_KEY,
    base_url=AGNES_BASE_URL,
)


def ask_ai(
    prompt: str,
    system_prompt: str | None = None,
) -> str:
    messages = []

    if system_prompt:
        messages.append(
            {
                "role": "system",
                "content": system_prompt,
            }
        )

    messages.append(
        {
            "role": "user",
            "content": prompt,
        }
    )

    response = client.chat.completions.create(
        model=AGNES_MODEL,
        messages=messages,
    )

    return response.choices[0].message.content or ""
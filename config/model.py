import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


AGNES_BASE_URL = os.getenv(
    "AGNES_BASE_URL",
    "https://apihub.agnes-ai.com/v1",
)
AGNES_MODEL = os.getenv(
    "AGNES_MODEL",
    "agnes-2.5-flash",
)


_client = None


def get_client():
    """Return the shared OpenAI-compatible client, constructing it lazily.

    Importing this module must remain side-effect free: ``AGNES_API_KEY``
    validation and client construction happen on first use instead of at
    import time, so the agent import chain stays usable in key-less
    environments (tests, docs builds, tooling).
    """
    global _client
    if _client is None:
        api_key = os.getenv("AGNES_API_KEY")
        if not api_key:
            raise RuntimeError(
                "AGNES_API_KEY is not configured."
            )
        _client = OpenAI(
            api_key=api_key,
            base_url=os.getenv("AGNES_BASE_URL", AGNES_BASE_URL),
        )
    return _client


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

    response = get_client().chat.completions.create(
        model=AGNES_MODEL,
        messages=messages,
    )

    return response.choices[0].message.content or ""

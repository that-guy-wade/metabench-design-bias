"""OpenAI client loader: reads OPENAI_API_KEY from the managed env file without printing it."""
import openai

def client():
    key = None
    for line in open("/path/to/model-keys.env"):
        if line.startswith("OPENAI_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
    assert key, "OPENAI_API_KEY missing"
    return openai.OpenAI(api_key=key, timeout=600, max_retries=4)

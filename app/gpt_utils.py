import os
import requests
import json


def ask_gpt(text, context, bot_name):
    """
    Send a request to OpenAI's Chat Completions API

    Args:
        text (str): The user's query
        context (str): The context from bot documents
        bot_name (str): The name of the bot

    Returns:
        str: The response from GPT
    """
    api_key = os.environ.get("OPENAI_API_KEY")

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    data = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "system",
                "content": f"You are an assistant for the bot named {bot_name}. Use the following context to inform your responses, but focus primarily on answering the user's query.",
            },
            {
                "role": "user",
                "content": f"Here is some context information: {context}",
            },
            {
                "role": "assistant",
                "content": "I've reviewed this information and am ready to help with your question.",
            },
            {
                "role": "user",
                "content": text,
            },
        ],
    }

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers=headers,
        data=json.dumps(data),
    )

    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        raise Exception(f"Error from OpenAI API: {response.text}")

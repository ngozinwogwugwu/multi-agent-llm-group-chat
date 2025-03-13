import os
import requests
import json
from app.models import Message


def ask_gpt(text, context, bot_name, bot_id=None, channel=None):
    """
    Send a request to OpenAI's Chat Completions API

    Args:
        text (str): The user's query
        context (str): The context from bot documents
        bot_name (str): The name of the bot
        bot_id (int, optional): The database ID of the bot
        channel (str, optional): The Slack channel ID

    Returns:
        str: The response from GPT
    """
    api_key = os.environ.get("OPENAI_API_KEY")

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    # Get past 10 messages from this bot in the channel if bot_id and channel are provided
    conversation_history = ""
    if bot_id and channel:
        past_messages = (
            Message.query.filter_by(bot_id=bot_id, channel=channel)
            .order_by(Message.created_at.desc())
            .limit(10)
            .all()
        )

        if past_messages:
            conversation_history = "Recent conversation history:\n"
            # Reverse to get chronological order
            for msg in reversed(past_messages):
                conversation_history += (
                    f"{'Bot' if msg.is_bot else 'User'}: {msg.text}\n"
                )

    # Combine document context with conversation history
    full_context = (
        f"{context}\n\n{conversation_history}" if conversation_history else context
    )

    data = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "system",
                "content": f"You are an assistant for the bot named {bot_name}. Use the following context to inform your responses, but focus primarily on answering the user's query.",
            },
            {
                "role": "user",
                "content": f"Here is some context information: {full_context}",
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

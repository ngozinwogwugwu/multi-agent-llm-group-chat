import os
import requests
import json
from app.models import Message, User
from slack_sdk.errors import SlackApiError


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


def process_bot_responses(text, channel_id, user_message, db, slack_client, logger):
    """
    Process responses from all bots for a given user message

    Args:
        text (str): The user's message text
        channel_id (str): The Slack channel ID
        user_message (Message): The saved user message object
        db: The database session
        slack_client: The Slack client
        logger: The logger instance
    """
    from app.models import SlackBot, Message
    import json

    # Get all bots
    all_bots = SlackBot.query.all()
    logger.info(f"Found {len(all_bots)} bots")

    # Create a dictionary of bot contexts
    bot_contexts = {}
    bot_names = {}
    for bot in all_bots:
        documents = bot.documents
        context = " ".join([doc.content for doc in documents])
        bot_contexts[bot.id] = context
        bot_names[bot.id] = bot.name

    # Create a prompt to determine which bot should respond
    bot_descriptions = "\n".join(
        [
            f"- Bot {bot.id} ({bot.name}): {bot_contexts[bot.id][:200]}..."
            for bot in all_bots
        ]
    )

    api_key = os.environ.get("OPENAI_API_KEY")
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    router_prompt = {
        "model": "gpt-4o",
        "messages": [
            {
                "role": "system",
                "content": f"""You are a router that determines which specialized bot should respond to a user query.
                You have access to the following bots:
                {bot_descriptions}
                
                Analyze the user's query and determine which single bot is best suited to respond.
                Even if multiple bots could potentially answer, you must select the single most appropriate bot.
                
                Return a JSON object with the following fields:
                - bot_id: The ID of the bot that should respond (integer)
                - bot_name: The name of the bot that should respond (string)
                - response: The response to the user's query (string)
                - confidence: Confidence level (0-1) that this bot is the right one to answer (number)
                """,
            },
            {"role": "user", "content": text},
        ],
        "response_format": {"type": "json_object"},
    }

    try:
        # Call OpenAI to determine which bot should respond
        logger.info("Calling OpenAI API to determine which bot should respond")
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            data=json.dumps(router_prompt),
        )

        if response.status_code != 200:
            logger.error(f"Error from OpenAI API: {response.text}")
            return

        router_response = response.json()["choices"][0]["message"]["content"]
        router_data = json.loads(router_response)

        logger.info(f"Router response: {router_data}")

        # Get the selected bot's information
        bot_id = router_data["bot_id"]
        bot_name = router_data["bot_name"]
        bot_response = router_data["response"]
        confidence = router_data["confidence"]

        logger.info(
            f"Selected bot: {bot_name} (ID: {bot_id}) with confidence: {confidence}"
        )

        # Format and send the response
        formatted_response = f"*{bot_name}*: {bot_response}"

        slack_response = slack_client.chat_postMessage(
            channel=channel_id,
            text=formatted_response,
            # thread_ts=user_message.timestamp,  # Uncomment to make it a thread reply
        )

        # Store the bot's response in the database
        bot_message = Message(
            channel=channel_id,
            text=bot_response,
            timestamp=slack_response.get("ts"),
            bot_id=bot_id,
            is_bot=True,
        )
        db.session.add(bot_message)
        db.session.commit()
        logger.info(f"Bot response saved with ID: {bot_message.id}")

    except Exception as e:
        logger.error(
            f"Error in router process: {str(e)}",
            exc_info=True,
        )


def get_or_create_user(user_id, slack_client, db, logger):
    """
    Get an existing user or create a new one if they don't exist

    Args:
        user_id (str): The Slack user ID
        slack_client: The Slack client
        db: The database session
        logger: The logger instance

    Returns:
        User: The user object
    """
    # Check if user exists
    user = User.query.filter_by(slack_user_id=user_id).first()

    # If user doesn't exist, create a new user record
    if not user:
        logger.info(f"User {user_id} not found in database, creating new user record")
        try:
            # Fetch user info from Slack API
            user_info = slack_client.users_info(user=user_id)
            username = user_info["user"]["name"]
            email = user_info["user"]["profile"].get("email")

            logger.info(f"Creating user with username: {username}, email: {email}")
            user = User(slack_user_id=user_id, username=username, email=email)
            db.session.add(user)
            db.session.commit()
        except SlackApiError as e:
            logger.error(f"Error fetching user info: {e}")
            username = f"user_{user_id}"
            user = User(slack_user_id=user_id, username=username)
            db.session.add(user)
            db.session.commit()

    return user


def check_duplicate_message(channel_id, ts, client_msg_id, logger):
    """
    Check if a message is a duplicate based on client_msg_id or timestamp

    Args:
        channel_id (str): The Slack channel ID
        ts (str): The message timestamp
        client_msg_id (str): The client message ID
        logger: The logger instance

    Returns:
        bool: True if duplicate, False otherwise
    """
    # Check if this is a duplicate message using client_msg_id (most reliable)
    if client_msg_id:
        existing_message = Message.query.filter_by(client_msg_id=client_msg_id).first()

        if existing_message:
            logger.info(
                f"Duplicate message detected with client_msg_id {client_msg_id}, skipping processing"
            )
            return True
    # Fallback to timestamp-based deduplication if client_msg_id is not available
    else:
        existing_message = Message.query.filter_by(
            channel=channel_id, timestamp=ts, is_bot=False
        ).first()

        if existing_message:
            logger.info(
                f"Duplicate message detected with timestamp {ts}, skipping processing"
            )
            return True

    return False

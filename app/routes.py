from flask import (
    Blueprint,
    jsonify,
    request,
    render_template,
    redirect,
    url_for,
    Response,
)
from slack_sdk.errors import SlackApiError
import openai  # Correct import for the OpenAI SDK
from app import db, slack_client
from app.models import User, SlackBot, Message, Document
import os
from app.gpt_utils import ask_gpt
from slack_sdk.signature import SignatureVerifier
import logging
import json
import re
from threading import Thread

main_bp = Blueprint("main", __name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Initialize OpenAI API key
openai.api_key = os.environ["OPENAI_API_KEY"]

# Initialize the signature verifier
signature_verifier = SignatureVerifier(os.environ["SLACK_SIGNING_SECRET"])

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@main_bp.route("/")
def home():
    return "Slack Flask App is running!"


@main_bp.route("/health")
def health():
    return jsonify({"status": "healthy"}), 200


@main_bp.route("/send-message", methods=["POST"])
def send_message():
    data = request.get_json()
    channel = data.get("channel", "#all-the-circuit-board")
    text = data.get("text", "Hello World from Flask App! 👋")

    try:
        # Send message to Slack
        response = slack_client.chat_postMessage(
            channel=channel,
            text=text,
        )

        # Store message in database
        message = Message(channel=channel, text=text, timestamp=response["ts"])
        db.session.add(message)
        db.session.commit()

        return jsonify(
            {"status": "success", "message_id": message.id, "slack_ts": response["ts"]}
        )

    except SlackApiError as e:
        return jsonify({"error": e.response["error"]}), 400


@main_bp.route("/slack/events", methods=["POST"])
def slack_events():
    logger.info("Received request to /slack/events endpoint")

    # Get the JSON data from the request
    data = request.get_json()

    # Handle challenge requests immediately
    if "challenge" in data:
        logger.info("Received challenge request from Slack")
        return jsonify({"challenge": data["challenge"]})

    # Start a background thread to process the event
    # This allows us to return a 200 response immediately
    def process_event_async(event_data):
        try:
            # Process the event
            process_slack_event(event_data)
        except Exception as e:
            logger.error(f"Error processing event: {str(e)}", exc_info=True)

    # Start the background processing
    Thread(target=process_event_async, args=(data,)).start()

    # Return 200 OK immediately
    return "", 200


# Extract the event processing logic into a separate function
def process_slack_event(data):
    # Log the raw request data
    logger.info(f"Processing event data: {json.dumps(data, indent=2)}")

    # Process the event
    if "event" in data:
        event = data["event"]
        logger.info(f"Processing event: {json.dumps(event, indent=2)}")

        # Add debug logging for the condition
        logger.info(
            f"Event type: {event.get('type')}, bot_id present: {bool(event.get('bot_id'))}"
        )

        # Check if it's a message event or app_mention event and not from a bot (to avoid loops)
        if (
            event.get("type") == "message" or event.get("type") == "app_mention"
        ) and not event.get("bot_id"):
            # Extract message details
            channel_id = event.get("channel")
            user_id = event.get("user")
            text = event.get("text", "")
            ts = event.get("ts")
            client_msg_id = event.get("client_msg_id")

            # Check if this is a duplicate message using client_msg_id (most reliable)
            if client_msg_id:
                existing_message = Message.query.filter_by(
                    client_msg_id=client_msg_id
                ).first()

                if existing_message:
                    logger.info(
                        f"Duplicate message detected with client_msg_id {client_msg_id}, skipping processing"
                    )
                    return
            # Fallback to timestamp-based deduplication if client_msg_id is not available
            else:
                existing_message = Message.query.filter_by(
                    channel=channel_id, timestamp=ts, is_bot=False
                ).first()

                if existing_message:
                    logger.info(
                        f"Duplicate message detected with timestamp {ts}, skipping processing"
                    )
                    return

            logger.info(
                f"Received message from user {user_id} in channel {channel_id}: {text}"
            )

            # Store the message in the database
            user = User.query.filter_by(slack_user_id=user_id).first()

            # If user doesn't exist, create a new user record
            if not user:
                logger.info(
                    f"User {user_id} not found in database, creating new user record"
                )
                # You might want to fetch user info from Slack API
                try:
                    user_info = slack_client.users_info(user=user_id)
                    username = user_info["user"]["name"]
                    email = user_info["user"]["profile"].get("email")

                    logger.info(
                        f"Creating user with username: {username}, email: {email}"
                    )
                    user = User(slack_user_id=user_id, username=username, email=email)
                    db.session.add(user)
                    db.session.commit()
                except SlackApiError as e:
                    logger.error(f"Error fetching user info: {e}")
                    username = f"user_{user_id}"
                    user = User(slack_user_id=user_id, username=username)
                    db.session.add(user)
                    db.session.commit()

            # Create and save the message with client_msg_id
            message = Message(
                channel=channel_id,
                text=text,
                timestamp=ts,
                user_id=user.id,
                is_bot=False,
                client_msg_id=client_msg_id,  # Store the client_msg_id
            )
            db.session.add(message)
            db.session.commit()
            logger.info(f"Message saved with ID: {message.id}")

            # For app_mention events, extract the mentioned bot directly from the event
            if event.get("type") == "app_mention":
                # Get the bot's user ID from the message
                mentioned_bot_id = None
                # Try to extract the bot ID from the text (format: <@BOT_ID>)
                match = re.search(r"<@([A-Z0-9]+)>", text)
                if match:
                    mentioned_bot_id = match.group(1)
                    logger.info(f"Bot mentioned with ID: {mentioned_bot_id}")

                    # Find the bot in the database
                    bot = SlackBot.query.filter_by(bot_id=mentioned_bot_id).first()
                    if bot:
                        logger.info(f"Found bot in database: {bot.name}")
                        mentioned_bots = [bot]
                    else:
                        logger.warning(
                            f"Bot with ID {mentioned_bot_id} not found in database"
                        )
                        mentioned_bots = []
                else:
                    logger.warning("Could not extract bot ID from app_mention text")
                    mentioned_bots = []
            else:
                # For regular messages, check if any bot was mentioned by name
                bots = SlackBot.query.all()
                mentioned_bots = [
                    bot for bot in bots if bot.name.lower() in text.lower()
                ]

            if mentioned_bots:
                logger.info(
                    f"Bots mentioned in message: {[bot.name for bot in mentioned_bots]}"
                )

                # Process each mentioned bot
                for bot in mentioned_bots:
                    logger.info(f"Processing response for bot: {bot.name}")
                    # Get the bot's documents for context
                    documents = bot.documents
                    context = " ".join([doc.content for doc in documents])
                    logger.info(f"Context length: {len(context)} characters")

                    try:
                        # Generate a response using OpenAI
                        logger.info(f"Calling OpenAI API for bot {bot.name}")
                        response = ask_gpt(text, context, bot.name)
                        logger.info(
                            f"Received response from OpenAI: {response[:100]}..."
                        )

                        # Send the response back to Slack
                        logger.info(f"Sending response to Slack channel {channel_id}")
                        slack_response = slack_client.chat_postMessage(
                            channel=channel_id,
                            text=response,
                            thread_ts=ts,  # This will make it a thread reply
                        )
                        logger.info(
                            f"Response sent to Slack, ts: {slack_response.get('ts')}"
                        )

                        # Store the bot's response in the database
                        bot_message = Message(
                            channel=channel_id,
                            text=response,
                            timestamp=slack_response.get("ts"),
                            bot_id=bot.id,
                            is_bot=True,
                        )
                        db.session.add(bot_message)
                        db.session.commit()
                        logger.info(f"Bot response saved with ID: {bot_message.id}")

                    except Exception as e:
                        logger.error(
                            f"Error generating or sending response: {str(e)}",
                            exc_info=True,
                        )
            else:
                logger.info("No bots were mentioned in the message")
        else:
            logger.info(
                "Ignoring event: not a user message/app_mention or sent by a bot"
            )
    else:
        logger.info("No event data in the request")

    logger.info("Finished processing request")


# Dashboard
@admin_bp.route("/")
def dashboard():
    users = User.query.all()
    bots = SlackBot.query.all()
    messages = Message.query.order_by(Message.created_at.desc()).limit(10).all()
    documents = Document.query.order_by(Document.created_at.desc()).limit(10).all()
    return render_template(
        "admin/dashboard.html",
        users=users,
        bots=bots,
        messages=messages,
        documents=documents,
    )


# Users CRUD
@admin_bp.route("/users")
def list_users():
    users = User.query.all()
    return render_template("admin/users/list.html", users=users)


@admin_bp.route("/users/<int:id>", methods=["GET", "POST"])
def edit_user(id):
    user = User.query.get_or_404(id)
    if request.method == "POST":
        user.username = request.form["username"]
        user.email = request.form["email"]
        db.session.commit()
        return redirect(url_for("admin.list_users"))
    return render_template("admin/users/edit.html", user=user)


@admin_bp.route("/users/<int:id>/delete", methods=["POST"])
def delete_user(id):
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()
    return redirect(url_for("admin.list_users"))


# SlackBots CRUD
@admin_bp.route("/bots")
def list_bots():
    bots = SlackBot.query.all()
    return render_template("admin/bots/list.html", bots=bots)


@admin_bp.route("/bots/<int:id>", methods=["GET", "POST"])
def edit_bot(id):
    bot = SlackBot.query.get_or_404(id)
    if request.method == "POST":
        bot.name = request.form["name"]
        db.session.commit()
        return redirect(url_for("admin.list_bots"))
    return render_template("admin/bots/edit.html", bot=bot)


@admin_bp.route("/bots/<int:id>/delete", methods=["POST"])
def delete_bot(id):
    bot = SlackBot.query.get_or_404(id)
    db.session.delete(bot)
    db.session.commit()
    return redirect(url_for("admin.list_bots"))


@admin_bp.route("/bots/new", methods=["GET", "POST"])
def new_bot():
    if request.method == "POST":
        bot = SlackBot(bot_id=request.form["bot_id"], name=request.form["name"])
        db.session.add(bot)
        db.session.commit()
        return redirect(url_for("admin.list_bots"))
    return render_template("admin/bots/new.html")


# Messages CRUD
@admin_bp.route("/messages")
def list_messages():
    messages = Message.query.order_by(Message.created_at.desc()).all()
    return render_template("admin/messages/list.html", messages=messages)


@admin_bp.route("/messages/<int:id>", methods=["GET", "POST"])
def edit_message(id):
    message = Message.query.get_or_404(id)
    if request.method == "POST":
        message.text = request.form["text"]
        message.channel = request.form["channel"]
        db.session.commit()
        return redirect(url_for("admin.list_messages"))
    return render_template("admin/messages/edit.html", message=message)


@admin_bp.route("/messages/<int:id>/delete", methods=["POST"])
def delete_message(id):
    message = Message.query.get_or_404(id)
    db.session.delete(message)
    db.session.commit()
    return redirect(url_for("admin.list_messages"))


# Documents CRUD
@admin_bp.route("/documents")
def list_documents():
    documents = Document.query.order_by(Document.created_at.desc()).all()
    return render_template("admin/documents/list.html", documents=documents)


@admin_bp.route("/documents/new", methods=["GET", "POST"])
def new_document():
    if request.method == "POST":
        document = Document(
            title=request.form["title"],
            content=request.form["content"],
            bot_id=request.form["bot_id"],
        )
        db.session.add(document)
        db.session.commit()
        return redirect(url_for("admin.list_documents"))

    bots = SlackBot.query.all()
    return render_template("admin/documents/new.html", bots=bots)


@admin_bp.route("/documents/<int:id>", methods=["GET", "POST"])
def edit_document(id):
    document = Document.query.get_or_404(id)
    if request.method == "POST":
        document.title = request.form["title"]
        document.content = request.form["content"]
        document.bot_id = request.form["bot_id"]
        db.session.commit()
        return redirect(url_for("admin.list_documents"))

    bots = SlackBot.query.all()
    return render_template("admin/documents/edit.html", document=document, bots=bots)


@admin_bp.route("/documents/<int:id>/delete", methods=["POST"])
def delete_document(id):
    document = Document.query.get_or_404(id)
    db.session.delete(document)
    db.session.commit()
    return redirect(url_for("admin.list_documents"))


@admin_bp.route("/ask_openai/<int:id>", methods=["POST"])
def ask_openai(id):
    # Retrieve the bot and its documents
    bot = SlackBot.query.get_or_404(id)
    documents = bot.documents

    # Prepare the context from the documents
    context = " ".join([doc.content for doc in documents])

    # Call OpenAI API using our new function
    try:
        openai_response = ask_gpt(context, bot.name)

        # Send the result to Slack
        slack_client.chat_postMessage(
            channel="#all-the-circuit-board",
            text=f"OpenAI response for bot {bot.name}: {openai_response}",
        )
        return f"OpenAI response sent to Slack for bot {bot.name}."
    except Exception as e:
        return f"Error: {str(e)}"

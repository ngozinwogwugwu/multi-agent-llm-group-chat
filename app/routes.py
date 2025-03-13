from flask import Blueprint, jsonify, request
from slack_sdk.errors import SlackApiError
from app import db, slack_client
from app.models import Message

main_bp = Blueprint("main", __name__)


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

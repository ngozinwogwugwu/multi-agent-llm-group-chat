from flask import Blueprint, jsonify, request, render_template, redirect, url_for
from slack_sdk.errors import SlackApiError
import openai  # Correct import for the OpenAI SDK
from app import db, slack_client
from app.models import User, SlackBot, Message, Document
import os
from app.gpt_utils import ask_gpt

main_bp = Blueprint("main", __name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

# Initialize OpenAI API key
openai.api_key = os.environ["OPENAI_API_KEY"]


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

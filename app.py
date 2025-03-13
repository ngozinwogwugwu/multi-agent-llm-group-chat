import os
from flask import Flask
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

# Initialize Slack client
slack_client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])


@app.route("/")
def home():
    return "Slack Flask App is running!"


@app.route("/send-hello-world")
def send_hello_world():
    try:
        # Send message to a specific channel
        response = slack_client.chat_postMessage(
            channel="#all-the-circuit-board",  #
            text="Hello World from Flask App! 👋",
        )
        return f"Message sent: {response['ts']}"
    except SlackApiError as e:
        return f"Error sending message: {e.response['error']}"


if __name__ == "__main__":
    # Post a message when the app starts
    try:
        slack_client.chat_postMessage(
            channel="#all-the-circuit-board",  #
            text="Hello World! The Flask app has started! 🚀",
        )
        print("Startup message sent to Slack")
    except SlackApiError as e:
        print(f"Error sending startup message: {e.response['error']}")

    # Run the Flask app
    app.run(debug=True)

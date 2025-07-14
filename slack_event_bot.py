from flask import Flask
from slackeventsapi import SlackEventAdapter
import os

# Replace this with your Slack Signing Secret from your app settings
SLACK_SIGNING_SECRET = "YOUR_SLACK_SIGNING_SECRET"

# Initialize Flask app
app = Flask(__name__)

# Initialize Slack Event Adapter
slack_events_adapter = SlackEventAdapter(SLACK_SIGNING_SECRET, "/slack/events", app)

# Example: Listen for 'message' events
@slack_events_adapter.on("message")
def handle_message(event_data):
    message = event_data["event"]
    print(f"Message received: {message.get('text')}")

# Example: Listen for 'reaction_added' events
@slack_events_adapter.on("reaction_added")
def handle_reaction(event_data):
    reaction = event_data["event"]
    print(f"Reaction added: {reaction.get('reaction')}")

# Error handling
@slack_events_adapter.on("error")
def handle_error(error):
    print(f"Error: {error}")

# Start the Flask server
if __name__ == "__main__":
    app.run(port=3000)
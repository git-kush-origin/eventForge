from flask import Flask, request, jsonify
import os

# Get the Slack Signing Secret from an environment variable
SLACK_SIGNING_SECRET = os.getenv('SLACK_SIGNING_SECRET')

if not SLACK_SIGNING_SECRET:
    raise ValueError("SLACK_SIGNING_SECRET environment variable is not set!")

app = Flask(__name__)

@app.route('/slack/events', methods=['POST'])
def slack_events():
    # Handle Slack's URL verification challenge
    data = request.get_json()
    if 'challenge' in data:
        return jsonify({'challenge': data['challenge']})

    # Handle other Slack events (e.g., messages, reactions)
    print(f"Event received: {data}")
    return '', 200

if __name__ == '__main__':
    app.run(port=3000)
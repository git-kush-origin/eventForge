from flask import Flask, request, jsonify
import os

# Get the Slack Signing Secret from an environment variable
SLACK_SIGNING_SECRET = os.getenv('SLACK_SIGNING_SECRET')

if not SLACK_SIGNING_SECRET:
    raise ValueError("SLACK_SIGNING_SECRET environment variable is not set!")

# Get the PORT environment variable (default to 3000 if not set)
PORT = int(os.getenv('PORT', 3000))

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
    # Bind to 0.0.0.0 to make the app accessible externally
    app.run(host='0.0.0.0', port=PORT)
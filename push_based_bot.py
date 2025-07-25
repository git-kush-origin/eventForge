"""
Push-based Slack Bot for Thread Analysis

This script initializes a push-based Slack bot that listens for messages in real-time
and analyzes threads where the user is mentioned using LLM.

Required Environment Variables:
- SLACK_BOT_TOKEN: Slack bot token for API access
- SLACK_APP_TOKEN: App token for Socket Mode
- SLACK_USER_ID: ID of the user to track mentions for
- GEMINI_API_KEY: API key for Gemini LLM
"""

import logging
import argparse
from dotenv import load_dotenv
from slack.slack_client_factory import SlackClientFactory
from llm.thread_analyzer import ThreadAnalyzer

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def main():
    """Initialize and start the push-based Slack bot with LLM analysis"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Real-time Slack thread analysis')
    parser.add_argument('--show-thread', action='store_true', help='Show full thread details including replies')
    args = parser.parse_args()

    # Initialize components
    client = SlackClientFactory.create_client("push")
    formatter = SlackClientFactory.create_formatter(logger)
    analyzer = ThreadAnalyzer()  # LLM-based thread analyzer

    # Store components in client for event handler access
    client.formatter = formatter
    client.analyzer = analyzer
    client.show_thread = args.show_thread

    # Start the bot
    client.start()

if __name__ == "__main__":
    main()

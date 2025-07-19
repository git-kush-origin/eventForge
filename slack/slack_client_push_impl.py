from .slack_client import ISlackClient
import os
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from typing import List, Dict, Optional
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

class SlackPushClient(ISlackClient):
    """Push-based implementation of Slack client using Bolt"""
    
    def __init__(self, user_id: str = None):
        """
        Initialize the push-based client
        
        Args:
            user_id: The Slack user ID to monitor events for
        """
        self.user_id = user_id
        self.app = None
        self.handler = None
        self.logger = logging.getLogger(__name__)
        self.initialize()
    
    def initialize(self):
        """Initialize the Bolt app and set up event handlers"""
        load_dotenv()
        
        # Initialize the Slack app with security credentials
        self.app = App(
            token=os.environ["SLACK_BOT_TOKEN"],
            signing_secret=os.environ["SLACK_SIGNING_SECRET"]
        )
        
        # Set up event handlers
        self._setup_event_handlers()
        
        # If no user_id provided, get it from environment
        if not self.user_id:
            self.user_id = os.environ.get("SLACK_USER_ID")
            if self.user_id:
                self.logger.info(f"Using user ID from environment: {self.user_id}")
            else:
                self.logger.error("No user ID provided or found in environment")
    
    def _setup_event_handlers(self):
        """Set up event handlers for the Bolt app"""
        @self.app.event("message")
        def handle_message_events(body, logger):
            """Handle incoming message events"""
            event = body.get("event", {})
            if self.is_user_mentioned(event):
                self.logger.info(f"User mentioned in message: {event.get('text', '')}")
    
    def start(self):
        """Start the Socket Mode handler"""
        if not self.app:
            self.logger.error("App not initialized")
            return
            
        try:
            app_token = os.environ["SLACK_APP_TOKEN"]
            self.handler = SocketModeHandler(self.app, app_token)
            self.handler.start()
        except Exception as e:
            self.logger.error(f"Error starting Socket Mode handler: {e}")
    
    def stop(self):
        """Stop the Socket Mode handler"""
        if self.handler:
            self.handler.close()
    
    def get_user_channels(self) -> List[Dict]:
        """Get channels accessible to the user"""
        # For push client, this is not typically needed
        # but implemented for interface compatibility
        return []
    
    def fetch_channel_messages(self, channel_id: str, oldest_ts: str, channel_name: str = "unknown") -> List[Dict]:
        """Fetch messages from a channel"""
        # For push client, this is not typically needed
        # but implemented for interface compatibility
        return []
    
    def fetch_thread_replies(self, channel_id: str, thread_ts: str) -> List[Dict]:
        """Fetch replies in a thread"""
        # For push client, this is not typically needed
        # but implemented for interface compatibility
        return []
    
    def is_user_mentioned(self, message: Dict) -> bool:
        """Check if the user is mentioned in a message"""
        text = message.get("text", "")
        return self.user_id and f"<@{self.user_id}>" in text
    
    def get_timestamp_n_hours_ago(self, hours: int) -> str:
        """Get timestamp from n hours ago"""
        # For push client, this is not typically needed
        # but implemented for interface compatibility
        time_n_hours_ago = datetime.now() - timedelta(hours=hours)
        return f"{time_n_hours_ago.timestamp():.0f}" 
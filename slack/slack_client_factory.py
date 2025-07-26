from typing import Optional
from .slack_client import ISlackClient
from .slack_client_pull_impl import SlackPullClient
from .slack_client_push_impl import SlackClientPushImpl
from .message_formatter import IMessageFormatter, DefaultMessageFormatter

class SlackClientFactory:
    """Factory to create appropriate Slack client and formatter"""
    
    @staticmethod
    def create_client(client_type: str, user_id: str = None) -> ISlackClient:
        """
        Create a Slack client of the specified type
        
        Args:
            client_type: Type of client ("pull" or "push")
            user_id: Optional user ID to track
            
        Returns:
            ISlackClient: Appropriate Slack client implementation
        """
        if client_type == "pull":
            return SlackPullClient(user_id)
        elif client_type == "push":
            return SlackClientPushImpl(user_id)
        else:
            raise ValueError(f"Invalid client type: {client_type}. Must be 'pull' or 'push'")

    @staticmethod
    def create_formatter(logger=None) -> IMessageFormatter:
        """
        Create a message formatter
        
        Args:
            logger: Optional logger instance
            
        Returns:
            IMessageFormatter: Default message formatter implementation
        """
        return DefaultMessageFormatter(logger) 
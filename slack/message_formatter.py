from abc import ABC, abstractmethod
import logging
from datetime import datetime
import re
import json
from typing import Dict, List
from .slack_client import ISlackClient

class IMessageFormatter(ABC):
    """Interface for formatting Slack messages and related data"""
    
    @abstractmethod
    def format_timestamp(self, ts: str) -> str:
        """Convert Slack timestamp to readable format"""
        pass

    @abstractmethod
    def format_reactions(self, reactions: list, client: ISlackClient) -> str:
        """Format reactions into a readable string"""
        pass

    @abstractmethod
    def format_message(self, msg: dict, client: ISlackClient, indent: str = "") -> str:
        """Format a single message with timestamp, user, text, and reactions"""
        pass

    @abstractmethod
    def format_thread_metadata(self, metadata) -> str:
        """Format thread metadata into a readable string"""
        pass

    @abstractmethod
    def format_thread_analysis(self, analysis) -> str:
        """Format thread analysis into a readable string"""
        pass

    @abstractmethod
    def log_thread_stats(self, logger, metadata) -> None:
        """Log thread statistics in a formatted way"""
        pass

class DefaultMessageFormatter(IMessageFormatter):
    """Default implementation of message formatter"""
    
    def __init__(self, logger=None):
        """Initialize the formatter with optional logger"""
        self.logger = logger or logging.getLogger(__name__)

    def format_timestamp(self, ts: str) -> str:
        """Convert Slack timestamp to readable format"""
        try:
            dt = datetime.fromtimestamp(float(ts))
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError) as e:
            self.logger.error(f"Error formatting timestamp {ts}: {e}")
            return "Unknown time"

    def format_reactions(self, reactions: list, client: ISlackClient) -> str:
        """Format reactions into a readable string"""
        if not reactions:
            return ""
        reaction_strs = []
        for reaction in reactions:
            count = reaction.get('count', 0)
            users = reaction.get('users', [])
            user_str = ", ".join(f"<@{user_id}>" for user_id in users)
            reaction_strs.append(f":{reaction['name']}: ({count} - {user_str})")
        return " ".join(reaction_strs)

    def format_message(self, msg: dict, client: ISlackClient, indent: str = "") -> str:
        """Format a single message with timestamp, user, text, and reactions"""
        msg_time = self.format_timestamp(msg.get('ts', '0'))
        text = msg.get('text', 'No text').strip()
        user_id = msg.get('user', 'Unknown')
        
        # Format the basic message
        formatted_msg = f"{indent}[{msg_time}] <@{user_id}>: {text}"
        
        # Add reactions if they exist and weren't part of the main text
        reactions = msg.get('reactions', [])
        if reactions and not text.startswith("Reacted with"):
            # Use the same indentation level as the message for reactions
            formatted_msg += f"\n{indent}└─ Reactions: {self.format_reactions(reactions, client)}"
        
        return formatted_msg

    def format_thread_metadata(self, metadata) -> str:
        """Format thread metadata into a readable string"""
        metadata_dict = {
            "messages": metadata.message_count,
            "participants": metadata.unique_participants,
            "activity": {
                "last_hour": f"{metadata.hourly_frequency:.1f}/hr",
                "last_4_hours": f"{metadata.four_hour_frequency:.1f}/hr",
                "last_24_hours": f"{metadata.daily_frequency:.1f}/hr"
            },
            "last_reply": f"{metadata.time_since_last_reply:.1f} hours ago",
            "mentions": {
                "direct": metadata.direct_mentions,
                "group": metadata.group_mentions
            },
            "reactions": metadata.reaction_count
        }
        return json.dumps(metadata_dict, indent=2)

    def format_thread_analysis(self, analysis) -> str:
        """Format thread analysis into a readable string"""
        return (
            f"Thread Analysis:\n"
            f"  Summary: {analysis.summary}\n"
            f"  Key Points:\n    • " + "\n    • ".join(analysis.key_points) + "\n"
            f"  Action Items:\n    • " + "\n    • ".join(analysis.action_items) + "\n"
            f"  Participants:\n    • " + "\n    • ".join(analysis.participants) + "\n"
            f"  Sentiment: {analysis.sentiment}\n"
            + (f"  Next Steps: {analysis.next_steps}\n" if analysis.next_steps else "")
        )

    def log_thread_stats(self, logger, metadata) -> None:
        """Log thread statistics in a formatted way"""
        logger.info("\nThread Stats:")
        logger.info(f"• Total Messages: {metadata.message_count}")
        logger.info(f"• Participants: {metadata.unique_participants}")
        logger.info(f"• Direct mentions: {metadata.direct_mentions}")
        logger.info(f"• Group mentions: {metadata.group_mentions}")
        logger.info(f"• Message Frequency:")
        logger.info(f"  - Last hour: {metadata.hourly_frequency} messages")
        logger.info(f"  - Last 4 hours: {metadata.four_hour_frequency} messages")
        logger.info(f"  - Last 24 hours: {metadata.daily_frequency} messages")
        logger.info(f"• Reactions: {metadata.reaction_count}")
        logger.info(f"• Time Since Last Reply: {metadata.time_since_last_reply:.1f} hours") 
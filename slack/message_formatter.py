"""
Message Formatter Module

This module provides formatting functionality for Slack messages and threads.
It is designed to be independent of Slack client implementations, focusing on:
1. Message content formatting
2. Thread statistics presentation
3. User mention handling
4. Reaction formatting

The module contains:
- IMessageFormatter: Interface for message formatting operations
- DefaultMessageFormatter: Default implementation with standard formatting

For detailed documentation, see docs/message_formatter.md
"""

from abc import ABC, abstractmethod
from typing import Dict, List
from .slack_client import ISlackClient, ThreadMetadata
import logging
from llm.thread_analyzer import ThreadAnalysis

class IMessageFormatter(ABC):
    """
    Interface for message formatting operations
    
    This interface defines the contract for formatting various Slack
    message components. It is designed to be:
    1. Independent of Slack client implementations
    2. Easily extensible for different formatting needs
    3. Testable through interface mocking
    """
    
    @abstractmethod
    def format_message(self, message: Dict, client: ISlackClient, prefix: str = "") -> str:
        """Format a single message for display"""
        pass
    
    @abstractmethod
    def format_thread_metadata(self, metadata: ThreadMetadata) -> str:
        """Format thread metadata for display"""
        pass
        
    @abstractmethod
    def format_thread_analysis(self, analysis: ThreadAnalysis) -> str:
        """Format LLM thread analysis for display"""
        pass

class DefaultMessageFormatter(IMessageFormatter):
    """
    Default implementation of message formatter
    
    This class provides standard formatting for:
    1. Message content with mentions and links
    2. Thread metadata with activity metrics
    3. Reactions with counts
    """
    
    def __init__(self, logger: logging.Logger = None):
        """Initialize formatter with optional logger"""
        self.logger = logger or logging.getLogger(__name__)
    
    def format_message(self, message: Dict, client: ISlackClient, prefix: str = "") -> str:
        """Format message content with mentions and formatting"""
        try:
            text = message.get('text', '')
            # Handle user mentions
            if 'user_profile' in message:
                text = text.replace(f"<@{message['user_profile']['id']}>",
                                  f"@{message['user_profile']['name']}")
            
            # Handle channel mentions
            if 'channel_id' in message:
                text = text.replace(f"<#{message['channel_id']}>",
                                  f"#{message.get('channel_name', 'unknown')}")
                
            return f"{prefix}{text.strip()}"
        except Exception as e:
            self.logger.error(f"Error formatting message content: {e}")
            return message.get('text', '')
    
    def format_thread_metadata(self, metadata: ThreadMetadata) -> str:
        """
        Format thread metadata for display
        
        Simply displays the pre-calculated metadata values in a structured format.
        No calculations are performed here - all values are already computed
        by the client implementation.
        
        Args:
            metadata: Pre-calculated thread metadata
            
        Returns:
            str: Formatted metadata string
        """
        try:
            lines = [
                "Thread Stats:",
                f"• Channel Status:",
                f"  - Membership: {'Member' if metadata.is_channel_member else 'Non-Member'}",
                f"• Basic Metrics:",
                f"  - Messages: {metadata.message_count}",
                f"  - Participants: {metadata.unique_participants}",
                f"  - Reactions: {metadata.reaction_count}",
                f"• Activity Scores:",
                f"  - Volume: {metadata.activity_volume_score:.2f}",
                f"  - Recency: {metadata.recency_score:.2f}",
                f"  - Participation: {metadata.participation_score:.2f}",
                f"• Mention Metrics:",
                f"  - Direct: {metadata.direct_mentions} (score: {metadata.direct_mention_score:.2f})",
                f"  - Group: {metadata.group_mentions} (score: {metadata.group_mention_score:.2f})",
                f"• Time Since Last Reply: {metadata.time_since_last_reply:.1f} hours"
            ]
            return "\n".join(lines)
        except Exception as e:
            self.logger.error(f"Error formatting thread metadata: {e}")
            return "Error formatting metadata"
            
    def format_thread_analysis(self, analysis: ThreadAnalysis) -> str:
        """Format LLM thread analysis for display"""
        try:
            lines = []
            
            # Status
            lines.append(f"Status: {analysis.action_status}")
            
            # Key points
            lines.append("\nSummary:")
            for point in analysis.key_points:
                lines.append(f"• {point}")
            
            # Action items
            if analysis.my_action or analysis.others_action:
                if analysis.my_action:
                    lines.append("\nAction Required From You:")
                    lines.append(f"→ {str(analysis.my_action)}")
                if analysis.others_action:
                    lines.append("\nAction Required From Others:")
                    lines.append(f"→ {str(analysis.others_action)}")
            
            return "\n".join(lines)
        except Exception as e:
            self.logger.error(f"Error formatting thread analysis: {e}")
            return "Error formatting analysis" 
from abc import ABC, abstractmethod
import os
from slack_sdk.web import WebClient
from slack_sdk.errors import SlackApiError
from slack_bolt import App
from typing import List, Dict, Optional, Set
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass

@dataclass
class UserGroupMembership:
    """Information about a user's group memberships"""
    channel_ids: Set[str]         # Channels user is member of
    usergroup_ids: Set[str]       # IDs of groups user belongs to
    usergroup_handles: Set[str]   # Handles of groups user belongs to (e.g. "engineering-team")

@dataclass
class ThreadMetadata:
    """Metadata about a thread's activity and importance"""
    message_count: int                  # Total messages in thread
    unique_participants: int            # Number of unique participants
    direct_mentions: int               # Number of times user was directly mentioned
    group_mentions: int                # Number of times user's groups were mentioned
    reaction_count: int                # Total number of reactions
    last_reply_ts: float              # Timestamp of last reply
    hourly_frequency: float           # Messages per 1-hour window
    four_hour_frequency: float        # Messages per 4-hour window
    daily_frequency: float            # Messages per 24-hour window
    time_since_last_reply: float      # Hours since last reply

class ISlackClient(ABC):
    """Interface defining all Slack operations"""
    
    @abstractmethod
    def initialize(self):
        """Initialize the client with necessary setup"""
        pass
    
    @abstractmethod
    def get_user_channels(self) -> List[Dict]:
        """Get channels accessible to the user"""
        pass
    
    @abstractmethod
    def fetch_channel_messages(self, channel_id: str, oldest_ts: str, channel_name: str = "unknown") -> List[Dict]:
        """Fetch messages from a channel"""
        pass
    
    @abstractmethod
    def fetch_thread_replies(self, channel_id: str, thread_ts: str) -> List[Dict]:
        """Fetch replies in a thread"""
        pass
    
    @abstractmethod
    def is_user_mentioned(self, message: Dict) -> bool:
        """Check if user is mentioned in a message"""
        pass
    
    @abstractmethod
    def get_timestamp_n_hours_ago(self, hours: int) -> str:
        """Get timestamp from n hours ago"""
        pass

    @abstractmethod
    def get_thread_metadata(self, thread_messages: List[Dict]) -> ThreadMetadata:
        """
        Analyze a thread and return its metadata
        
        Args:
            thread_messages: List of messages in the thread
            
        Returns:
            ThreadMetadata: Analysis of the thread's activity
        """
        pass

    @abstractmethod
    def fetch_user_group_memberships(self) -> UserGroupMembership:
        """
        Fetch and cache user's group memberships
        
        Returns:
            UserGroupMembership: User's channel and group memberships
        """
        pass

    @abstractmethod
    def is_user_in_group_mention(self, message: Dict, channel_id: str) -> bool:
        """
        Check if message contains a group mention that includes the user
        
        Args:
            message: The message to check
            channel_id: The channel the message is in
            
        Returns:
            bool: True if user is included in any group mentions
        """
        pass 
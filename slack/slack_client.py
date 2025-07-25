"""
Slack Client Interface Module

This module defines the core interfaces for Slack operations and data structures.
It provides a consistent contract that all implementations must follow, enabling:
1. Multiple client implementations (pull/push-based)
2. Easy testing through interface mocking
3. Consistent behavior across the application

The module contains:
- UserGroupMembership: Data class for user's group memberships
- ThreadMetadata: Data class for thread statistics and metrics
- ISlackClient: Core interface for Slack operations

Implementation Differences:

Pull-Based Client (SlackPullClient):
- Uses single WebClient with user token
- Actively fetches messages from channels
- Caches channel and group memberships
- Efficient for batch processing
- Rate-limited but has broader access
- Advantages:
  • Full access to public channels without joining
  • Simpler token management
  • Better for historical data analysis
- Disadvantages:
  • Not real-time
  • Higher API usage
  • Rate limits can slow processing

Push-Based Client (SlackPushClient):
- Uses two Bolt apps (bot + user tokens)
- Receives real-time events via Socket Mode
- Checks memberships on-demand
- Efficient for real-time monitoring
- Hybrid token approach for full access
- Advantages:
  • Real-time event processing
  • Lower API usage
  • No rate limits for events
- Disadvantages:
  • More complex token management
  • Requires Socket Mode setup
  • Bot needs channel membership for some features

Key Technical Differences:
1. Token Usage:
   - Pull: Single user token
   - Push: Bot token for events, user token for data access

2. Channel Access:
   - Pull: Uses cached channel memberships
   - Push: Checks membership in real-time

3. Event Handling:
   - Pull: Periodic polling with rate limits
   - Push: Real-time via Socket Mode

4. Group Management:
   - Pull: Caches group memberships
   - Push: Hybrid approach (cache + real-time checks)

5. Thread Analysis:
   - Pull: Batch processing with cached data
   - Push: Real-time processing with fresh data

For detailed documentation, see docs/slack_client.md
"""

from abc import ABC, abstractmethod
import os
from slack_sdk.web import WebClient
from slack_sdk.errors import SlackApiError
from slack_bolt import App
from typing import List, Dict, Optional, Set
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
import math

# Maximum expected message count for activity score normalization
MAX_EXPECTED_MESSAGES = 200

# Maximum expected participant count for participation score normalization
MAX_EXPECTED_PARTICIPANTS = 30

# Maximum expected mention counts for mention score normalization
MAX_DIRECT_MENTIONS = 5
MAX_GROUP_MENTIONS = 15

# Maximum expected reactions per message for density score
MAX_REACTIONS_PER_MESSAGE = 5

# Expected message velocity (messages per hour) for engagement score
EXPECTED_MSG_VELOCITY = 10

# Expected thread depth (replies in chain) for engagement score
EXPECTED_THREAD_DEPTH = 5

# Time window for frequency score (in hours)
FREQUENCY_WINDOW_HOURS = 1
BURST_THRESHOLD = 5  # Messages in window to consider a "burst"

# Decay factor for recency score (in minutes)
# With -0.04, score will be:
# - 1.0 for current messages
# - ~0.30 after 30 minutes
# - ~0.09 after 1 hour
# - ~0.008 after 2 hours
# - Nearly 0 after 4 hours
RECENCY_DECAY_FACTOR = -0.04

def calculate_recency_score(minutes_since_last_msg: float) -> float:
    """Calculate recency score using exponential decay"""
    return math.exp(RECENCY_DECAY_FACTOR * minutes_since_last_msg)

@dataclass
class UserGroupMembership:
    """
    Information about a user's group memberships
    
    This class tracks:
    1. Which channels the user belongs to
    2. Which user groups they're part of (by ID)
    3. The handles/names of their groups
    
    Used for:
    - Determining message relevance
    - Filtering channel access
    - Group mention detection
    """
    channel_ids: Set[str]         # Channels user is member of
    usergroup_ids: Set[str]       # IDs of groups user belongs to
    usergroup_handles: Set[str]   # Handles of groups user belongs to (e.g. "engineering-team")

@dataclass
class ThreadMetadata:
    """
    Metadata about a thread's activity and importance
    
    This class tracks various metrics about a thread:
    1. Basic Counts:
       - Message and participant counts
       - Mention counts (direct/group)
       - Reaction counts
       
    2. Activity & Engagement Metrics:
       - Activity volume (normalized message count)
       - Participation (unique participants)
       - Reaction density (reactions per message)
       - Engagement (interaction quality/velocity)
       
    3. Temporal Metrics:
       - Recency (time since last message)
       - Frequency (message rate over time)
       
    4. User Context:
       - Direct mention score
       - Group mention score
       - Channel membership
    
    Used for:
    - Thread prioritization
    - Activity monitoring
    - User engagement tracking
    """
    # Basic Counts
    message_count: int                  # Total messages in thread
    unique_participants: int            # Number of unique participants
    direct_mentions: int                # Number of times user was directly mentioned
    group_mentions: int                 # Number of times user's groups were mentioned
    reaction_count: int                 # Total number of reactions
    
    # Timing Information
    last_reply_ts: float               # Timestamp of last reply
    time_since_last_reply: float       # Hours since last reply
    
    # User Context
    is_channel_member: bool            # Whether the user is a member of the channel
    
    # Activity & Engagement Scores (0-1)
    activity_volume_score: float       # Normalized log scale of message count
    participation_score: float         # Normalized unique participant count
    reaction_density_score: float      # Reactions per message (normalized)
    engagement_score: float            # Combined measure of interaction quality:
                                      # - Message velocity (msgs/hour)
                                      # - Reply chain depth
                                      # Higher score = more active discussion
    
    # Temporal Scores (0-1)
    recency_score: float              # Exponential decay based on last message
    frequency_score: float            # Rate of messages over time:
                                     # - Detects "bursts" of activity
                                     # - High score = many messages in short time
                                     # - Helps identify active discussions
    
    # Mention Scores (0-1)
    direct_mention_score: float       # Normalized direct mention count
    group_mention_score: float        # Normalized group mention count
    
    #TODO: add more scores
    #user-explcit-signals
        #muted,starred groups
    #VIP participants

class ISlackClient(ABC):
    """
    Interface defining all Slack operations
    
    This interface provides a consistent contract for Slack operations,
    allowing for different implementations (pull vs push) while maintaining
    consistent behavior.
    
    Key Responsibilities:
    1. Channel management and access
    2. Message fetching and filtering
    3. Thread tracking and analysis
    4. User mention detection
    5. Activity metrics calculation
    
    Implementation Notes:
    - All methods should handle rate limiting
    - Methods should use appropriate error handling
    - Implementations should be thread-safe
    - Cache data where appropriate
    """
    
    @abstractmethod
    def initialize(self):
        """
        Initialize the client with necessary setup
        
        Should handle:
        1. Environment variable loading
        2. API client setup
        3. User authentication
        4. Initial data caching
        
        Raises:
            ValueError: If required environment variables are missing
            SlackApiError: If Slack API initialization fails
        """
        pass
    
    @abstractmethod
    def get_user_channels(self) -> List[Dict]:
        """
        Get channels accessible to the user
        
        Returns:
            List[Dict]: List of channel information dictionaries
                Each dict contains:
                - id: Channel ID
                - name: Channel name
                - is_private: Whether channel is private
                - is_member: Whether user is a member
        """
        pass
    
    @abstractmethod
    def fetch_channel_messages(self, channel_id: str, oldest_ts: str, channel_name: str = "unknown") -> List[Dict]:
        """
        Fetch messages from a channel
        
        Args:
            channel_id: The Slack channel ID
            oldest_ts: Timestamp to fetch messages after
            channel_name: Optional channel name for logging
            
        Returns:
            List[Dict]: List of message dictionaries from the channel
            
        Note:
            Implementations should handle pagination and rate limiting
        """
        pass
    
    @abstractmethod
    def fetch_thread_replies(self, channel_id: str, thread_ts: str) -> List[Dict]:
        """
        Fetch replies in a thread
        
        Args:
            channel_id: The channel containing the thread
            thread_ts: Timestamp of the parent message
            
        Returns:
            List[Dict]: List of reply messages in the thread
            
        Note:
            Should return messages in chronological order
        """
        pass
    
    @abstractmethod
    def is_user_mentioned(self, message: Dict) -> bool:
        """
        Check if user is mentioned in a message
        
        Should check for:
        1. Direct mentions (@user)
        2. Group mentions (@group)
        3. Channel-wide mentions (@here, @channel)
        
        Args:
            message: Slack message dictionary
            
        Returns:
            bool: True if user is mentioned
        """
        pass
    
    @abstractmethod
    def get_timestamp_n_hours_ago(self, hours: int) -> str:
        """
        Get timestamp from n hours ago
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            str: Slack timestamp format (epoch seconds)
        """
        pass

    @abstractmethod
    def get_thread_metadata(self, thread_messages: List[Dict]) -> ThreadMetadata:
        """
        Analyze a thread and return its metadata
        
        Calculates:
        1. Message and participant counts
        2. Mention frequencies
        3. Activity rates
        4. Timing information
        
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
        
        Retrieves:
        1. Channel memberships
        2. User group memberships
        3. Group handles/names
        
        Returns:
            UserGroupMembership: User's channel and group memberships
            
        Note:
            Implementations should cache this data appropriately
        """
        pass 
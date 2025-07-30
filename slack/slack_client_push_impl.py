"""
Push-based Slack Client Implementation

This module implements a push-based approach to Slack interaction where:
1. Events are received in real-time via Socket Mode using bot token
2. Thread fetching and data access uses user token for broader permissions in Socket mode
3. Messages are processed as they arrive
4. Callbacks are used to notify the main application
5. Tracks important threads for continuous monitoring
"""

import os
import math
from datetime import datetime, timedelta
from typing import List, Dict, Set, Optional
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError
import logging
from collections import defaultdict
from slack_sdk import WebClient
from .slack_client import (
    ISlackClient, ThreadMetadata, UserGroupMembership,
    MAX_EXPECTED_MESSAGES, MAX_EXPECTED_PARTICIPANTS,
    MAX_DIRECT_MENTIONS, MAX_GROUP_MENTIONS,
    MAX_REACTIONS_PER_MESSAGE, EXPECTED_MSG_VELOCITY,
    EXPECTED_THREAD_DEPTH, FREQUENCY_WINDOW_HOURS,
    BURST_THRESHOLD,
    calculate_recency_score
)
from .message_formatter import DefaultMessageFormatter
import re
import time

class SlackClientPushImpl(ISlackClient):
    """
    Push-based implementation of Slack client using Bolt and Socket Mode.
    
    This implementation:
    1. Uses Socket Mode for real-time event reception
    2. Maintains two separate apps:
       - bot_app: For event handling (needs SLACK_BOT_TOKEN)
       - user_app: For thread fetching and data access (needs SLACK_USER_TOKEN)
    3. Provides callback mechanism for event notification
    4. Tracks user's group memberships for mention detection
    5. Maintains list of important threads for monitoring
    """
    
    def __init__(self, user_id: str = None):
        """Initialize the push-based client"""
        self.user_id = user_id
        self.bot_app = None  # Bolt app with bot token for Socket Mode events
        self.user_app = None  # Bolt app with user token for data access
        self.handler = None   # Socket Mode handler
        self.logger = logging.getLogger(__name__)
        self._group_membership = None  # Cache of user's group memberships
        self.message_callbacks = []    # List of callback functions for events
        
        # Track important threads
        self.tracked_threads = {}  # Dict[str, Dict] - key: channel_id:thread_ts
        self.initialize()

    def add_thread_to_tracking(self, channel_id: str, thread_ts: str, reason: str = ""):
        """Add a thread to the tracking list
        
        Args:
            channel_id: Channel ID where thread exists
            thread_ts: Thread timestamp
            reason: Why this thread is being tracked (for logging)
        """
        thread_key = f"{channel_id}:{thread_ts}"
        if thread_key not in self.tracked_threads:
            self.tracked_threads[thread_key] = {
                'channel_id': channel_id,
                'thread_ts': thread_ts,
                'first_tracked_at': time.time(),
                'reason': reason
            }
            self.logger.info(f"Started tracking thread {thread_key} - {reason}")

    def is_thread_tracked(self, channel_id: str, thread_ts: str) -> bool:
        """Check if a thread is being tracked
        
        Args:
            channel_id: Channel ID
            thread_ts: Thread timestamp
            
        Returns:
            bool: True if thread is being tracked
        """
        thread_key = f"{channel_id}:{thread_ts}"
        return thread_key in self.tracked_threads

    def is_user_involved(self, message: Dict) -> bool:
        """Check if user is involved in the message/thread"""
        # Check if user is mentioned
        if self.is_user_mentioned(message):
            # Add thread to tracking if it's not already tracked
            thread_ts = message.get('thread_ts') or message.get('ts')
            self.add_thread_to_tracking(
                message.get('channel'),
                thread_ts,
                "User mentioned in thread"
            )
            return True
            
        # Check if user is the message author
        if message.get('user') == self.user_id:
            # Track threads started by user
            thread_ts = message.get('thread_ts') or message.get('ts')
            self.add_thread_to_tracking(
                message.get('channel'),
                thread_ts,
                "User is thread author"
            )
            return True
            
        # If it's a thread, check if user has replied or if thread is tracked
        thread_ts = message.get('thread_ts')
        if thread_ts:
            # First check if thread is already tracked
            if self.is_thread_tracked(message.get('channel'), thread_ts):
                return True
                
            try:
                # Get all replies in thread
                replies = self.user_app.client.conversations_replies(
                    channel=message.get('channel'),
                    ts=thread_ts
                )
                if replies and replies.get('messages'):
                    # Check if user has replied in thread
                    has_replied = any(reply.get('user') == self.user_id 
                                    for reply in replies.get('messages', []))
                    if has_replied:
                        self.add_thread_to_tracking(
                            message.get('channel'),
                            thread_ts,
                            "User has replied in thread"
                        )
                        return True
            except Exception as e:
                self.logger.debug(f"Error checking thread replies: {e}")
                
        return False
    
    def register_message_callback(self, callback):
        """
        Register a callback function for message events.
        
        The callback will be triggered for messages where:
        1. User is directly mentioned (@user)
        2. User's groups are mentioned (@group)
        3. Global mentions (@here/@channel) in user's channels
        4. User is the message author
        5. User has replied in the thread
        
        Args:
            callback: Function(channel_id, message_event) to be called
                     when relevant messages are received
        """
        self.message_callbacks.append(callback)
        
    def _notify_message_callbacks(self, channel_id, message_event):
        """
        Notify all registered callbacks about a new message.
        
        This is called by the event handler when a relevant message
        (containing user/group mention or user involvement) is received.
        
        Args:
            channel_id: ID of the channel where message was posted
            message_event: Full Slack message event data
        """
        for callback in self.message_callbacks:
            try:
                callback(channel_id, message_event)
            except Exception as e:
                self.logger.debug(f"Error in message callback: {e}")

    def initialize(self):
        """
        Initialize the client components.
        
        This method:
        1. Creates both Bolt apps (bot and user)
           - bot_app: For Socket Mode events (SLACK_BOT_TOKEN)
           - user_app: For thread fetching and data access (SLACK_USER_TOKEN)
        2. Gets user ID from environment if not provided
        3. Fetches and caches user's group memberships
        4. Sets up event handlers for Socket Mode
        """
        # Initialize the Bolt apps with respective tokens
        self.logger.info("🔄 Initializing Bolt apps...")
        
        # Bot app for Socket Mode events
        self.bot_app = App(token=os.environ["SLACK_BOT_TOKEN"])
        self.logger.info("✅ Bot app initialized")
        
        # User app for data access (threads, user info, etc.)
        self.user_app = App(token=os.environ["SLACK_USER_TOKEN"])
        self.logger.info("✅ User app initialized")
        
        # Get user ID from environment if not provided
        if not self.user_id:
            self.user_id = os.environ.get("SLACK_USER_ID")
            if self.user_id:
                self.logger.info(f"👤 Using user ID from environment: {self.user_id}")
            else:
                self.logger.error("❌ No user ID provided or found in environment")
                return

        # Cache user's group memberships for mention detection
        self.logger.info("🔄 Fetching user group memberships...")
        self._group_membership = self.fetch_user_group_memberships()
        self.logger.info(f"✅ Found {len(self._group_membership.usergroup_handles)} groups")
        
        # Set up Socket Mode event handlers
        self._setup_event_handlers()
        
    def _setup_event_handlers(self):
        """
        Set up event handlers for Socket Mode.
        
        This sets up handlers for:
        1. Message events (new messages, replies)
        2. Mention detection (user, group, global)
        3. User involvement (author, replies)
        4. Callback notification
        """
        @self.bot_app.event("message")
        def handle_message_events(event, client):
            """Handle incoming real-time message events"""
            try:
                # Filter for actual message events
                if "type" not in event or event["type"] != "message":
                    return
                    
                channel_id = event.get("channel")
                if not channel_id:
                    return
                    
                # Check if this is a message in a tracked thread
                thread_ts = event.get('thread_ts')
                if thread_ts and self.is_thread_tracked(channel_id, thread_ts):
                    self._notify_message_callbacks(channel_id, event)
                    return

                # Process messages where user is involved
                if self.is_user_involved(event):
                    # Notify registered callbacks
                    self._notify_message_callbacks(channel_id, event)
                    
            except Exception as e:
                self.logger.error(f"Error handling message event: {e}")
    
    def start(self):
        """
        Start the Socket Mode handler.
        
        This:
        1. Creates SocketModeHandler with bot app
        2. Starts listening for real-time events
        3. Keeps running until stopped or interrupted
        """
        if not self.bot_app:
            self.logger.error("❌ Bot app not initialized")
            return
            
        try:
            self.logger.info("🔌 Starting Socket Mode handler...")
            app_token = os.environ["SLACK_APP_TOKEN"]
            self.handler = SocketModeHandler(self.bot_app, app_token)
            self.handler.start()
            self.logger.info("✅ Socket Mode handler started successfully")
        except Exception as e:
            self.logger.error(f"❌ Error starting Socket Mode handler: {e}")
    
    def stop(self):
        """
        Stop the Socket Mode handler.
        
        This cleanly shuts down the event listener.
        """
        if self.handler:
            self.logger.info("🛑 Stopping Socket Mode handler...")
            self.handler.close()
            self.logger.info("✅ Socket Mode handler stopped")
    
    def get_user_channels(self) -> List[Dict]:
        """Get channels accessible to the user using user app"""
        try:
            result = self.user_app.client.users_conversations(
                user=self.user_id,
                types="public_channel,private_channel"
            )
            return result.get('channels', [])
        except Exception as e:
            self.logger.error(f"Error fetching user channels: {e}")
            return []
    
    def fetch_channel_messages(self, channel_id: str, oldest_ts: str, channel_name: str = "unknown") -> List[Dict]:
        """Fetch messages from a channel using user app"""
        try:
            result = self.user_app.client.conversations_history(
                channel=channel_id,
                oldest=oldest_ts
            )
            return result.get('messages', [])
        except Exception as e:
            self.logger.error(f"Error fetching channel messages: {e}")
            return []
    
    def fetch_thread_replies(self, channel_id: str, thread_ts: str) -> List[Dict]:
        """
        Fetch all replies in a thread using Bolt app with user token.
        
        Uses user token to access thread data, which allows:
        1. Access to threads in any public channel
        2. Access to threads in private channels where user is member
        3. Full thread history without limitations
        4. No rate limiting unlike Web API
        
        Args:
            channel_id: Channel containing the thread
            thread_ts: Timestamp of the parent message
            
        Returns:
            List of messages in the thread, including the parent
        """
        try:
            result = self.user_app.client.conversations_replies(
                channel=channel_id,
                ts=thread_ts
            )
            return result.get('messages', [])
        except Exception as e:
            self.logger.error(f"Error fetching thread replies: {e}")
            return []
    
    def is_user_mentioned(self, message: Dict) -> bool:
        """
        Check if user is mentioned in a message.
        
        For global mentions (@here, @channel), only consider them if user is a member of the channel.
        For direct/group mentions, consider them regardless of channel membership.
        """
        if not self.user_id:
            return False
            
        text = message.get('text', '')
        channel_id = message.get('channel', '')
        
        # Direct mention - always consider
        if f"<@{self.user_id}>" in text:
            return True
            
        # Group mentions - always consider
        if self._group_membership and self._group_membership.usergroup_ids:
            for group_id in self._group_membership.usergroup_ids:
                if f"<!subteam^{group_id}>" in text:
                    return True
        
        # Global mentions (@here, @channel) - only if user is channel member
        if ("<!channel>" in text or "<!here>" in text):
            try:
                # Check if user is member of the channel
                response = self.user_app.client.conversations_members(
                    channel=channel_id,
                    limit=1000  # Adjust based on channel size
                )
                members = response.get('members', [])
                return self.user_id in members
            except Exception as e:
                self.logger.debug(f"Error checking channel membership: {e}")
                return False
                    
        return False
    
    def get_timestamp_n_hours_ago(self, hours: int) -> str:
        """Get timestamp from n hours ago"""
        time_n_hours_ago = datetime.now() - timedelta(hours=hours)
        return str(time_n_hours_ago.timestamp())
    
    def fetch_user_group_memberships(self) -> UserGroupMembership:
        """Fetch user's group memberships using user app"""
        try:
            result = self.user_app.client.usergroups_list(include_users=True)
            if not result:
                return UserGroupMembership(set(), set(), set())

            usergroup_ids = set()
            usergroup_handles = set()
            
            for group in result.get("usergroups", []):
                group_id = group["id"]
                users = group.get("users", [])
                
                if self.user_id in users:
                    usergroup_ids.add(group_id)
                    usergroup_handles.add(group["handle"])
                    self.logger.debug(f"User is member of group: {group['handle']}")

            return UserGroupMembership(
                channel_ids=set(),  # We don't need channel IDs for this implementation
                usergroup_ids=usergroup_ids,
                usergroup_handles=usergroup_handles
            )

        except Exception as e:
            self.logger.error(f"Error fetching user groups: {e}")
            return UserGroupMembership(set(), set(), set())

    def is_user_in_group_mention(self, message: Dict, channel_id: str) -> bool:
        """Check if message contains a group mention that includes the user"""
        if not self._group_membership:
            return False

        text = message.get("text", "")
        
        # Check for @channel, @here, @everyone mentions
        if channel_id in self._group_membership.channel_ids:
            if "<!channel>" in text or "<!everyone>" in text:
                return True
            if "<!here>" in text:
                return True
                
        # Check for user group mentions
        # Format: <!subteam^TEAM_ID|team-name>
        group_mentions = re.findall(r'<!subteam\^([A-Z0-9]+)(?:\|[^>]+)?>', text)
        return any(group_id in self._group_membership.usergroup_ids 
                  for group_id in group_mentions)

    def is_channel_member(self, channel_id: str) -> bool:
        """Check if user is a member of the given channel"""
        try:
            response = self.user_app.client.conversations_members(
                channel=channel_id,
                limit=1000  # Adjust based on channel size
            )
            members = response.get('members', [])
            return self.user_id in members
        except Exception as e:
            self.logger.debug(f"Error checking channel membership: {e}")
            return False

    def get_thread_metadata(self, thread_messages: List[Dict]) -> ThreadMetadata:
        """
        Calculate comprehensive metadata and importance scores for a thread.
        
        This method analyzes various aspects of thread activity and engagement:
        
        1. Basic Metrics:
           - Message count: Total messages in thread
           - Unique participants: Number of distinct users
           - Reaction count: Total reactions across all messages
        
        2. Activity & Engagement Scores:
           - Activity Volume Score: Logarithmic scaling of message count
             * Uses log scale to prevent long threads from dominating
             * Normalized to [0,1] using max_expected_messages
             * Logarithmic ensures diminishing returns for very long threads
           
           - Engagement Score: Combines velocity and depth
             * Velocity: Messages per hour vs expected velocity
             * Depth: Maximum reply chain length vs expected depth
             * Weighted 60% velocity, 40% depth to prioritize active discussions
        
        3. Temporal Scores:
           - Recency Score: Exponential decay based on time since last reply
             * Fresh threads (< 1 hour) score near 1.0
             * Score drops exponentially as thread ages
             * Helps prioritize active/recent discussions
           
           - Frequency Score: Recent message burst detection
             * Looks for message clusters in recent window
             * High score (1.0) for burst of messages
             * Medium score (0.5) for steady activity
             * Helps identify suddenly active threads
        
        4. Participation Metrics:
           - Participation Score: Linear scaling of unique participants
             * Normalized against max_expected_participants
             * Higher score for more diverse participation
             * Helps identify broadly engaging discussions
        
        5. Mention Analysis:
           - Direct/Group Mention Scores: Normalized mention counts
             * Separate tracking for direct (@user) and group (@team) mentions
             * Each normalized against their respective maximums
             * Helps identify threads requiring attention
        
        6. Reaction Analysis:
           - Reaction Density Score: Reactions per message
             * Normalized against max_reactions_per_message
             * Indicates thread's emotional/social engagement
             * High scores suggest valuable/popular content
        
        Args:
            thread_messages: List of messages in the thread
            
        Returns:
            ThreadMetadata with all calculated metrics and scores
        """
        if not thread_messages:
            return ThreadMetadata(
                message_count=0,
                unique_participants=0,
                direct_mentions=0,
                group_mentions=0,
                reaction_count=0,
                last_reply_ts=0.0,
                time_since_last_reply=0.0,
                activity_volume_score=0.0,
                recency_score=0.0,
                participation_score=0.0,
                direct_mention_score=0.0,
                group_mention_score=0.0,
                reaction_density_score=0.0,
                engagement_score=0.0,
                frequency_score=0.0,
                is_channel_member=False
            )
            
        # Get channel ID from first message
        channel_id = thread_messages[0].get('channel', '')
        
        # Basic counts
        message_count = len(thread_messages)
        participants = {msg.get('user') for msg in thread_messages if msg.get('user')}
        unique_participant_count = len(participants)
        reaction_count = sum(
            len(msg.get('reactions', [])) for msg in thread_messages
        )
        
        # Activity Volume Score
        # Why logarithmic?
        # - Prevents very long threads from completely dominating
        # - 10 vs 5 messages is more significant than 105 vs 100
        # - log(n+1) ensures score starts at 0 for empty threads
        activity_volume_score = min(1.0, math.log(message_count + 1) / math.log(MAX_EXPECTED_MESSAGES + 1))
        
        # Participation Score
        # Linear scaling works here because:
        # - Each unique participant is equally valuable
        # - More participants generally means broader engagement
        # - Upper limit prevents massive threads from dominating
        participation_score = min(1.0, unique_participant_count / MAX_EXPECTED_PARTICIPANTS)
        
        # Reaction Density Score
        # Per-message normalization because:
        # - Controls for thread length
        # - High density = high engagement per message
        # - Better indicator than raw reaction count
        avg_reactions_per_msg = reaction_count / message_count if message_count > 0 else 0
        reaction_density_score = min(1.0, avg_reactions_per_msg / MAX_REACTIONS_PER_MESSAGE)
        
        # Engagement Score Components
        timestamps = [float(msg['ts']) for msg in thread_messages]
        timestamps.sort()
        
        # 1. Message Velocity
        # Messages per hour shows how actively thread is being used
        thread_duration_hours = (max(timestamps) - min(timestamps)) / 3600 if len(timestamps) > 1 else 1
        msgs_per_hour = message_count / thread_duration_hours if thread_duration_hours > 0 else 0
        velocity_score = min(1.0, msgs_per_hour / EXPECTED_MSG_VELOCITY)
        
        # 2. Thread Depth
        # Reply chain length shows how deep discussions go
        reply_chains = defaultdict(list)
        for msg in thread_messages:
            parent_ts = msg.get('thread_ts') or msg.get('ts')
            reply_chains[parent_ts].append(msg)
        max_chain_depth = max(len(chain) for chain in reply_chains.values())
        depth_score = min(1.0, max_chain_depth / EXPECTED_THREAD_DEPTH)
        
        # Combined Engagement Score
        # Weights velocity higher because:
        # - Active threads need more immediate attention
        # - Deep threads might be important but less urgent
        engagement_score = (0.6 * velocity_score) + (0.4 * depth_score)
        
        # Frequency Score (Burst Detection)
        # Why use a sliding window?
        # - Identifies sudden bursts of activity
        # - Recent bursts might need immediate attention
        # - Gradual activity gets proportional score
        now = time.time()
        recent_window = now - (FREQUENCY_WINDOW_HOURS * 3600)
        recent_msgs = sum(1 for ts in timestamps if ts > recent_window)
        is_burst = recent_msgs >= BURST_THRESHOLD
        frequency_score = min(1.0, recent_msgs / BURST_THRESHOLD) if is_burst else (0.5 * recent_msgs / BURST_THRESHOLD)
        
        # Mention Analysis
        # Direct mentions are personal and usually need attention
        direct_mentions = sum(
            1 for msg in thread_messages
            if f"<@{self.user_id}>" in msg.get('text', '')
        )
        
        # Group mentions might need attention based on context
        memberships = self.fetch_user_group_memberships()
        group_mentions = sum(
            1 for msg in thread_messages
            if any(f"<!subteam^{gid}>" in msg.get('text', '')
                  for gid in memberships.usergroup_ids)
        )
        
        # Normalize mention counts
        direct_mention_score = min(1.0, direct_mentions / MAX_DIRECT_MENTIONS)
        group_mention_score = min(1.0, group_mentions / MAX_GROUP_MENTIONS)
        
        # Timing calculations for recency
        latest_ts = max(timestamps)
        now = time.time()
        hours_since_last = (now - latest_ts) / 3600
        minutes_since_reply = hours_since_last * 60
        
        # Recency Score
        # Why exponential decay?
        # - Recent messages are much more important
        # - Importance drops quickly in first few hours
        # - Long-dead threads should score near zero
        recency_score = calculate_recency_score(minutes_since_reply)
        
        # Channel membership affects global mention relevance
        is_member = channel_id in self._group_membership.channel_ids if self._group_membership else False
        
        return ThreadMetadata(
            message_count=message_count,
            unique_participants=unique_participant_count,
            direct_mentions=direct_mentions,
            group_mentions=group_mentions,
            reaction_count=reaction_count,
            last_reply_ts=latest_ts,
            time_since_last_reply=hours_since_last,
            activity_volume_score=activity_volume_score,
            recency_score=recency_score,
            participation_score=participation_score,
            direct_mention_score=direct_mention_score,
            group_mention_score=group_mention_score,
            reaction_density_score=reaction_density_score,
            engagement_score=engagement_score,
            frequency_score=frequency_score,
            is_channel_member=is_member
        ) 
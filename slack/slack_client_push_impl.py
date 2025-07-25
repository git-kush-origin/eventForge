"""
Push-Based Slack Client Implementation

This module implements a push-based approach to Slack interaction where:
1. Events are received via Socket Mode using bot token
2. Thread fetching is done using user token
3. Messages are processed in real-time
4. State is maintained for active threads

Key features:
- Real-time event processing with bot token
- Thread fetching with user token for full access
- Efficient state management
- Thread activity tracking
- User mention detection

For detailed documentation, see docs/slack_client_push.md
"""

import os
import math
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk.errors import SlackApiError
import logging
from .slack_client import (
    ISlackClient, ThreadMetadata, UserGroupMembership,
    MAX_EXPECTED_MESSAGES, MAX_EXPECTED_PARTICIPANTS,
    MAX_DIRECT_MENTIONS, MAX_GROUP_MENTIONS,
    MAX_REACTIONS_PER_MESSAGE, EXPECTED_MSG_VELOCITY,
    EXPECTED_THREAD_DEPTH, FREQUENCY_WINDOW_HOURS,
    BURST_THRESHOLD,
    calculate_recency_score
)
from llm.thread_analyzer import ThreadAnalyzer
from .message_formatter import DefaultMessageFormatter
from collections import defaultdict

class SlackPushClient(ISlackClient):
    """Push-based implementation of Slack client using Bolt"""
    
    def __init__(self, user_id: str = None):
        """
        Initialize the push-based client
        
        Args:
            user_id: The Slack user ID to monitor events for
        """
        self.user_id = user_id
        self.bot_app = None  # Bolt app with bot token for events
        self.user_app = None  # Bolt app with user token for thread fetching
        self.handler = None
        self.logger = logging.getLogger(__name__)
        self._group_membership = None
        self.analyzer = ThreadAnalyzer()  # LLM-based thread analyzer
        self.initialize()
    
    def initialize(self):
        """Initialize both Bolt apps and set up event handlers"""
        # Initialize the Bolt apps with respective tokens
        self.logger.info("🔄 Initializing Bolt apps...")
        
        # Bot app for events
        self.bot_app = App(token=os.environ["SLACK_BOT_TOKEN"])
        self.logger.info("✅ Bot app initialized")
        
        # User app for thread fetching
        self.user_app = App(token=os.environ["SLACK_USER_TOKEN"])
        self.logger.info("✅ User app initialized")
        
        # If no user_id provided, get it from environment
        if not self.user_id:
            self.user_id = os.environ.get("SLACK_USER_ID")
            if self.user_id:
                self.logger.info(f"👤 Using user ID from environment: {self.user_id}")
            else:
                self.logger.error("❌ No user ID provided or found in environment")
                return

        # Initialize group membership
        self.logger.info("🔄 Fetching user group memberships...")
        self._group_membership = self.fetch_user_group_memberships()
        self.logger.info(f"✅ Found {len(self._group_membership.usergroup_handles)} groups")
        
        # Set up event handlers
        self._setup_event_handlers()
        
    def _setup_event_handlers(self):
        """Set up event handlers for the bot app"""
        @self.bot_app.event("message")
        def handle_message_events(event, client):
            """Handle incoming message events"""
            try:
                # Check if message mentions user or their groups
                if self.is_user_mentioned(event):
                    thread_ts = event.get('thread_ts') or event.get('ts')
                    channel = event.get('channel')
                    
                    # Fetch complete thread using user app
                    thread_messages = self.fetch_thread_replies(channel, thread_ts)
                    
                    # Calculate thread metadata
                    metadata = self.get_thread_metadata(thread_messages)
                    
                    # Get LLM analysis
                    analysis = self.analyzer.analyze_thread(thread_messages)
                    
                    # Create formatter
                    formatter = DefaultMessageFormatter(self.logger)
                    
                    # Print thread header
                    self.logger.info(f"\n{'='*50}")
                    self.logger.info(f"Thread in <#{channel}> {'(Member)' if metadata.is_channel_member else '(Non-Member)'}")
                    
                    # Print all messages in thread
                    self.logger.info("\nMessages:")
                    for msg in thread_messages:
                        # Get user info for the message
                        try:
                            user_info = self.user_app.client.users_info(user=msg.get('user'))['user']
                            user_name = user_info.get('real_name', user_info.get('name', 'Unknown'))
                        except Exception:
                            user_name = 'Unknown'
                        
                        # Format timestamp
                        ts = float(msg.get('ts', 0))
                        dt = datetime.fromtimestamp(ts)
                        time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Format message text
                        text = msg.get('text', '')
                        
                        # Print message with user and timestamp
                        self.logger.info(f"[{time_str}] {user_name}: {text}")
                        
                        # Print reactions if any
                        if msg.get('reactions'):
                            reaction_str = ' | '.join(
                                f":{reaction['name']}: x{reaction['count']}"
                                for reaction in msg['reactions']
                            )
                            self.logger.info(f"Reactions: {reaction_str}")
                    
                    # Print LLM analysis using formatter
                    self.logger.info(formatter.format_thread_analysis(analysis))
                    
                    # Print thread stats using formatter
                    self.logger.info(formatter.format_thread_metadata(metadata))
                    
                    self.logger.info(f"{'='*50}\n")
                    
            except Exception as e:
                self.logger.error(f"Error handling message event: {e}")
    
    def start(self):
        """Start the Socket Mode handler for bot app"""
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
        """Stop the Socket Mode handler"""
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
        """Fetch replies in a thread using user app"""
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

    def get_thread_metadata(self, messages: List[Dict]) -> ThreadMetadata:
        """Calculate metadata for a thread"""
        if not messages:
            return ThreadMetadata(
                message_count=0,
                unique_participants=0,
                reaction_count=0,
                direct_mentions=0,
                group_mentions=0,
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
        channel_id = messages[0].get('channel', '')
        
        # Basic counts
        message_count = len(messages)
        unique_participants = len({msg.get('user') for msg in messages if msg.get('user')})
        reaction_count = sum(
            len(msg.get('reactions', [])) for msg in messages
        )
        
        # Calculate reaction density score
        avg_reactions_per_msg = reaction_count / message_count if message_count > 0 else 0
        reaction_density_score = min(1.0, avg_reactions_per_msg / MAX_REACTIONS_PER_MESSAGE)
        
        # Calculate engagement score
        timestamps = [float(msg.get('ts', 0)) for msg in messages]
        timestamps.sort()
        
        # Message velocity component
        thread_duration_hours = (max(timestamps) - min(timestamps)) / 3600 if len(timestamps) > 1 else 1
        msgs_per_hour = message_count / thread_duration_hours if thread_duration_hours > 0 else 0
        velocity_score = min(1.0, msgs_per_hour / EXPECTED_MSG_VELOCITY)
        
        # Thread depth component
        reply_chains = defaultdict(list)
        for msg in messages:
            parent_ts = msg.get('thread_ts') or msg.get('ts')
            reply_chains[parent_ts].append(msg)
        max_chain_depth = max(len(chain) for chain in reply_chains.values())
        depth_score = min(1.0, max_chain_depth / EXPECTED_THREAD_DEPTH)
        
        # Combined engagement score
        engagement_score = (0.6 * velocity_score) + (0.4 * depth_score)
        
        # Calculate frequency score
        now = datetime.now().timestamp()
        recent_window = now - (FREQUENCY_WINDOW_HOURS * 3600)
        recent_msgs = sum(1 for ts in timestamps if ts > recent_window)
        is_burst = recent_msgs >= BURST_THRESHOLD
        frequency_score = min(1.0, recent_msgs / BURST_THRESHOLD) if is_burst else (0.5 * recent_msgs / BURST_THRESHOLD)
        
        # Calculate mention counts
        direct_mentions = 0
        group_mentions = 0
        for msg in messages:
            text = msg.get('text', '')
            if f"<@{self.user_id}>" in text:
                direct_mentions += 1
            if self._group_membership and self._group_membership.usergroup_ids:
                for group_id in self._group_membership.usergroup_ids:
                    if f"<!subteam^{group_id}>" in text:
                        group_mentions += 1
                        break

        # Calculate time since last reply
        latest_ts = max(timestamps)
        hours_since_last = (now - latest_ts) / 3600
        
        # Calculate scores
        activity_score = min(1.0, math.log(message_count + 1) / math.log(MAX_EXPECTED_MESSAGES + 1))
        recency_score = calculate_recency_score(hours_since_last * 60)  # Convert hours to minutes
        participation_score = min(1.0, unique_participants / MAX_EXPECTED_PARTICIPANTS)
        direct_mention_score = min(1.0, direct_mentions / MAX_DIRECT_MENTIONS)
        group_mention_score = min(1.0, group_mentions / MAX_GROUP_MENTIONS)
        
        # Check channel membership
        is_member = self.is_channel_member(channel_id)

        return ThreadMetadata(
            message_count=message_count,
            unique_participants=unique_participants,
            reaction_count=reaction_count,
            direct_mentions=direct_mentions,
            group_mentions=group_mentions,
            last_reply_ts=latest_ts,
            time_since_last_reply=hours_since_last,
            activity_volume_score=activity_score,
            recency_score=recency_score,
            participation_score=participation_score,
            direct_mention_score=direct_mention_score,
            group_mention_score=group_mention_score,
            reaction_density_score=reaction_density_score,
            engagement_score=engagement_score,
            frequency_score=frequency_score,
            is_channel_member=is_member
        ) 
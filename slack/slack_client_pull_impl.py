from .slack_client import ISlackClient, ThreadMetadata, UserGroupMembership
import os
from slack_sdk.web import WebClient
from slack_sdk.errors import SlackApiError
from typing import List, Dict, Optional, Set
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time
import re

class SlackPullClient(ISlackClient):
    """Pull-based implementation of Slack client using WebClient"""
    
    def __init__(self, user_id: str = None):
        """
        Initialize the pull-based client
        
        Args:
            user_id: The Slack user ID to fetch activities for
        """
        self.user_id = user_id
        self.client = None
        self.logger = logging.getLogger(__name__)
        self._group_membership = None
        self.initialize()
    
    def initialize(self):
        """Initialize the WebClient and get user ID if not provided"""
        load_dotenv()
        self.client = WebClient(token=os.environ["SLACK_USER_TOKEN"])
        
        if not self.user_id:
            try:
                auth_response = self.client.auth_test()
                self.user_id = auth_response["user_id"]
                self.logger.info(f"Using authenticated user's ID: {self.user_id}")
            except SlackApiError as e:
                self.logger.error(f"Error getting user ID: {e}")
                self.user_id = None

        # Initialize group membership
        self.logger.info("Fetching user group memberships...")
        self._group_membership = self.fetch_user_group_memberships()
        self.logger.info(f"Found {len(self._group_membership.usergroup_handles)} groups user belongs to")
    
    def make_slack_api_call(self, method: str, **kwargs) -> Optional[Dict]:
        """Make a Slack API call with rate limiting and error handling"""
        try:
            response = getattr(self.client, method)(**kwargs)
            return response
        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                delay = int(e.response.headers.get("Retry-After", 1))
                self.logger.warning(f"Rate limited. Waiting {delay} seconds...")
                time.sleep(delay)
                return self.make_slack_api_call(method, **kwargs)
            else:
                self.logger.error(f"Error making Slack API call to {method}: {e}")
                return None
    
    def get_user_channels(self) -> List[Dict]:
        """Get whitelisted channels that the user is a member of"""
        target_channel_id = "C088XPUGDFZ"  # TODO: Make configurable
        
        # Get whitelisted channels
        all_channels = self.list_accessible_channels()
        
        if not all_channels:
            self.logger.error("\n❌ No accessible channels found")
            return []
        
        # Try to find our target channel
        target_channel = next((
            channel for channel in all_channels 
            if channel["id"] == target_channel_id
        ), None)
        
        if target_channel:
            channels = [{"id": target_channel["id"], "name": target_channel["name"]}]
            self.logger.info(f"\n✅ Using channel: {channels[0]['name']} ({channels[0]['id']})")
            return channels
        else:
            self.logger.error(f"\n❌ Could not access channel {target_channel_id}")
            return []
    
    def list_accessible_channels(self) -> List[Dict]:
        """List whitelisted channels accessible to the user"""
        WHITELISTED_CHANNELS = ["C088XPUGDFZ"]  # TODO: Make configurable
        
        try:
            self.logger.info("\n📋 Checking whitelisted channels...")
            
            channels = []
            for channel_id in WHITELISTED_CHANNELS:
                try:
                    result = self.make_slack_api_call(
                        "conversations_info",
                        channel=channel_id
                    )
                    
                    if result and "channel" in result:
                        channel = result["channel"]
                        if channel.get("is_member", False):
                            channels.append(channel)
                            channel_type = "🔒 Private" if channel.get('is_private', False) else "🌐 Public"
                            
                            self.logger.info(
                                f"\n• {channel['name']}"
                                f"\n  ID: {channel['id']}"
                                f"\n  Type: {channel_type}"
                            )
                        else:
                            self.logger.warning(f"\n⚠️ Not a member of channel: {channel_id}")
                    else:
                        self.logger.warning(f"\n⚠️ Could not fetch info for channel: {channel_id}")
                        
                except SlackApiError as e:
                    self.logger.error(f"\n❌ Error fetching channel {channel_id}: {str(e)}")
                    continue
            
            if not channels:
                self.logger.warning("\n⚠️ No accessible channels found from the whitelist")
                return []
                
            self.logger.info(f"\n✅ Successfully checked {len(WHITELISTED_CHANNELS)} whitelisted channels")
            return channels
            
        except Exception as e:
            self.logger.error(f"\n❌ Unexpected error: {str(e)}")
            return []
    
    def fetch_channel_messages(self, channel_id: str, oldest_ts: str, channel_name: str = "unknown") -> List[Dict]:
        """Fetch messages from a specific channel after the given timestamp"""
        messages = []
        try:
            cursor = None
            self.logger.info(f"\nStarting to fetch messages from #{channel_name}")
            self.logger.info(f"Looking for messages after timestamp: {oldest_ts}")
            
            while True:
                result = self.make_slack_api_call(
                    "conversations_history",
                    channel=channel_id,
                    oldest=oldest_ts,
                    limit=200,
                    cursor=cursor,
                    types=["public_channel", "private_channel"]
                )
                
                if not result:
                    self.logger.error(f"No result from conversations_history API for #{channel_name}")
                    break
                
                if "messages" in result:
                    batch_messages = result["messages"]
                    messages.extend(batch_messages)
                    self.logger.info(f"\nFound {len(batch_messages)} messages in this batch (Total so far: {len(messages)})")
                    
                    cursor = result.get("response_metadata", {}).get("next_cursor")
                    if not cursor:
                        break
                    
                    time.sleep(0.5)  # Rate limiting
                else:
                    self.logger.warning(f"No messages found in API response for #{channel_name}")
                    break
            
            self.logger.info(f"\nTotal messages found in #{channel_name}: {len(messages)}")
            return messages
            
        except SlackApiError as e:
            self.logger.error(f"Error fetching messages from #{channel_name}: {e}")
            return []
    
    def fetch_thread_replies(self, channel_id: str, thread_ts: str) -> List[Dict]:
        """Fetch all replies in a thread"""
        try:
            result = self.make_slack_api_call(
                "conversations_replies",
                channel=channel_id,
                ts=thread_ts
            )
            return result["messages"] if result else []
        except SlackApiError as e:
            self.logger.error(f"Error fetching thread replies: {e}")
            return []
    
    def fetch_user_group_memberships(self) -> UserGroupMembership:
        """Fetch user's group memberships"""
        try:
            # Get all user groups in workspace with their members
            self.logger.info("Fetching all user groups with members...")
            result = self.make_slack_api_call(
                "usergroups_list",
                include_users=True  # Get members in single API call
            )
            
            if not result:
                self.logger.error("Failed to fetch user groups")
                return UserGroupMembership(set(), set(), set())

            usergroup_ids = set()
            usergroup_handles = set()
            
            # Check membership in each group
            total_groups = len(result.get("usergroups", []))
            self.logger.info(f"Checking membership in {total_groups} groups...")
            
            for group in result.get("usergroups", []):
                group_id = group["id"]
                users = group.get("users", [])  # Members are included in response
                
                if self.user_id in users:
                    usergroup_ids.add(group_id)
                    usergroup_handles.add(group["handle"])
                    self.logger.info(f"User is member of group: {group['handle']}")

            # Get user's channel memberships
            channels = self.get_user_channels()
            channel_ids = {channel["id"] for channel in channels}

            membership = UserGroupMembership(
                channel_ids=channel_ids,
                usergroup_ids=usergroup_ids,
                usergroup_handles=usergroup_handles
            )
            
            self.logger.info(f"Group membership initialized: {len(usergroup_handles)} groups")
            return membership

        except SlackApiError as e:
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

    def is_user_mentioned(self, message: Dict) -> bool:
        """Check if user is mentioned in the message"""
        # Check direct mentions
        text = message.get("text", "")
        direct_mention = f"<@{self.user_id}>" in text
        
        # Check group mentions
        group_mention = self.is_user_in_group_mention(
            message, 
            message.get("channel", "")
        )
        
        return direct_mention or group_mention
    
    def get_timestamp_n_hours_ago(self, hours: int) -> str:
        """Get a Slack timestamp from n hours ago"""
        time_n_hours_ago = datetime.now() - timedelta(hours=hours)
        timestamp = f"{time_n_hours_ago.timestamp():.0f}"
        self.logger.info(f"Looking for messages after: {time_n_hours_ago} (timestamp: {timestamp})")
        return timestamp 

    def get_thread_metadata(self, thread_messages: List[Dict]) -> ThreadMetadata:
        """Analyze a thread and return its metadata"""
        now = time.time()
        
        # Sort messages by timestamp
        sorted_messages = sorted(thread_messages, key=lambda x: float(x.get('ts', 0)))
        
        # Basic counts
        message_count = len(thread_messages)
        participants = {msg.get('user') for msg in thread_messages if msg.get('user')}
        unique_participants = len(participants)
        
        # Direct and group mentions
        direct_mentions = 0
        group_mentions = 0
        for msg in thread_messages:
            text = msg.get('text', '')
            if f"<@{self.user_id}>" in text:
                direct_mentions += 1
            if self.is_user_in_group_mention(msg, msg.get('channel', '')):
                group_mentions += 1
        
        # Reactions
        reaction_count = sum(
            len(msg.get('reactions', [])) 
            for msg in thread_messages
        )
        
        # Last reply timestamp
        last_reply_ts = float(sorted_messages[-1].get('ts', 0))
        time_since_last_reply = (now - last_reply_ts) / 3600  # Convert to hours
        
        # Message frequencies
        hour_ago = now - 3600
        four_hours_ago = now - (3600 * 4)
        day_ago = now - (3600 * 24)
        
        hourly_messages = sum(1 for msg in thread_messages 
                            if float(msg.get('ts', 0)) > hour_ago)
        four_hour_messages = sum(1 for msg in thread_messages 
                               if float(msg.get('ts', 0)) > four_hours_ago)
        daily_messages = sum(1 for msg in thread_messages 
                           if float(msg.get('ts', 0)) > day_ago)
        
        return ThreadMetadata(
            message_count=message_count,
            unique_participants=unique_participants,
            direct_mentions=direct_mentions,
            group_mentions=group_mentions,
            reaction_count=reaction_count,
            last_reply_ts=last_reply_ts,
            hourly_frequency=hourly_messages,
            four_hour_frequency=four_hour_messages / 4,  # Per hour over 4 hours
            daily_frequency=daily_messages / 24,  # Per hour over 24 hours
            time_since_last_reply=time_since_last_reply
        ) 
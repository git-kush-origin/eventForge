from typing import List, Dict, Optional
from dataclasses import dataclass
import google.generativeai as genai
import os
from dotenv import load_dotenv
import logging
from datetime import datetime
import json

@dataclass
class ActionItem:
    """Represents an action item with the actor and requestor"""
    action: str  # The action to be performed
    requested_by: List[str] = None  # List of users who requested/expect this action

    def __str__(self) -> str:
        if self.requested_by and len(self.requested_by) > 0:
            requestors = ", ".join(self.requested_by)
            return f"{self.action} (requested by: {requestors})"
        return self.action

@dataclass
class ThreadAnalysis:
    """Analysis results for a Slack thread"""
    key_points: List[str]      # Main points from the discussion
    my_action: Optional[ActionItem] = None  # Action required from our user
    others_action: Optional[ActionItem] = None  # Action required from other users
    action_status: str = "No action required"  # Quick status about pending actions

    def to_json(self, indent: int = 2) -> str:
        """Convert analysis to formatted JSON string"""
        return json.dumps({
            "key_points": self.key_points,
            "my_action": self.my_action.__dict__ if self.my_action else None,
            "others_action": self.others_action.__dict__ if self.others_action else None,
            "action_status": self.action_status
        }, indent=indent)

class ThreadAnalyzer:
    """
    Analyzes Slack threads using LLMs to provide insights and summaries.
    Uses Grab's Gemini endpoint for analysis.
    """
    
    def __init__(self):
        """Initialize the analyzer with Gemini configuration"""
        # Load environment variables
        load_dotenv()
        self.logger = logging.getLogger(__name__)
        
        # Check for required environment variables
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables. Please add it to your .env file.")
            
        self.logger.info("Initializing Gemini client...")
        
        # Initialize Gemini client
        genai.configure(
            api_key=api_key,
            transport="rest",
            client_options={"api_endpoint": "https://public-api.grabgpt.managed.catwalk-k8s.stg-myteksi.com/google"}
        )
        
        # Get the model
        self.model = genai.GenerativeModel('gemini-2.5-flash')
        self.logger.info("Gemini client initialized successfully")
        
        # Get user ID and group from environment
        self.user_id = os.getenv("SLACK_USER_ID")
        self.user_group = os.getenv("SLACK_USER_GROUP")
    
    def _format_thread_for_llm(self, thread_messages: List[Dict]) -> str:
        """Format thread messages into a string suitable for LLM input"""
        formatted_messages = []
        for msg in thread_messages:
            timestamp = datetime.fromtimestamp(float(msg.get('ts', 0)))
            time_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            user = f"<@{msg.get('user', 'Unknown')}>"
            text = msg.get('text', 'No text')
            
            formatted_messages.append(f"[{time_str}] {user}: {text}")
        
        return "\n".join(formatted_messages)
    
    def analyze_thread(self, thread_messages: List[Dict]) -> ThreadAnalysis:
        """Analyze a thread and provide key points and expectations"""
        # Format thread for LLM
        thread_text = self._format_thread_for_llm(thread_messages)
        
        # Prepare context about user/group
        user_context = f"USER_ID: {self.user_id}" if self.user_id else ""
        group_context = f"GROUP_ID: {self.user_group}" if self.user_group else ""
        identity_context = " and ".join(filter(None, [user_context, group_context]))
        
        # Prepare prompt
        prompt = f"""
        Analyze this Slack thread and identify:
        1. List 3-5 key points starting with •
        2. Identify actions required from {identity_context} specifically, including who requested/expects these actions
        3. Identify actions required from other users, including who requested/expects these actions
        4. Provide a one-line status about whether {identity_context} needs to take any action

        Format your response exactly as follows:
        [Key Points]
        • point 1
        • point 2
        • point 3

        [My Actions]
        • action: <action description>
        • requested_by: <@user1>, <@user2>

        [Others Actions]
        • action: <action description>
        • requested_by: <@user1>, <@user2>

        [Status]
        • "Action required: <brief description>" OR "No action required" OR "Waiting on others: <brief description>"

        Thread:
        {thread_text}
        """
        
        try:
            # Call Gemini API
            response = self.model.generate_content(prompt)
            
            # Extract sections
            points = []
            my_action = None
            others_action = None
            status = "No action required"  # Default status
            current_section = None
            current_action = None
            current_requestors = None
            
            for line in response.text.split('\n'):
                line = line.strip()
                if line.startswith('[Key Points]'):
                    current_section = 'points'
                elif line.startswith('[My Actions]'):
                    current_section = 'my_actions'
                    current_action = None
                    current_requestors = None
                elif line.startswith('[Others Actions]'):
                    current_section = 'others_actions'
                    current_action = None
                    current_requestors = None
                elif line.startswith('[Status]'):
                    current_section = 'status'
                elif line.startswith('•'):
                    line = line.lstrip('•').strip()
                    if current_section == 'points':
                        points.append(line)
                    elif current_section in ['my_actions', 'others_actions']:
                        if line.startswith('action:'):
                            current_action = line[7:].strip()
                        elif line.startswith('requested_by:'):
                            current_requestors = [u.strip() for u in line[13:].strip().split(',')]
                            # Create ActionItem when we have both action and requestors
                            if current_action:
                                action_item = ActionItem(current_action, current_requestors)
                                if current_section == 'my_actions':
                                    my_action = action_item
                                else:
                                    others_action = action_item
                    elif current_section == 'status':
                        status = line.strip('"')  # Remove quotes
            
            return ThreadAnalysis(
                key_points=points,
                my_action=my_action,
                others_action=others_action,
                action_status=status
            )
            
        except Exception as e:
            self.logger.error(f"Error analyzing thread: {e}")
            return ThreadAnalysis(
                key_points=["Error analyzing thread"],
                my_action=None,
                others_action=None,
                action_status="Error analyzing thread"
            ) 
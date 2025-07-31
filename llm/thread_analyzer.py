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

    # Content-based scores (0-1)
    urgency_score: float = 0.0       # How time-sensitive/urgent the thread is
    topic_score: float = 0.0         # How important the topic/subject matter is
    question_score: float = 0.0      # How many direct questions need answers
    action_score: float = 0.0        # How much action/work is required

    def to_json(self, indent: int = 2) -> str:
        """Convert analysis to formatted JSON string"""
        return json.dumps({
            "key_points": self.key_points,
            "my_action": self.my_action.__dict__ if self.my_action else None,
            "others_action": self.others_action.__dict__ if self.others_action else None,
            "action_status": self.action_status,
            "content_scores": {
                "urgency": self.urgency_score,
                "topic": self.topic_score,
                "question": self.question_score,
                "action": self.action_score
            }
        }, indent=indent)

class ThreadAnalyzer:
    """Analyzes Slack threads using LLMs to provide insights and summaries"""
    
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
        """Analyze a thread and provide key points, expectations, and scores"""
        # Format thread for LLM
        thread_text = self._format_thread_for_llm(thread_messages)
        
        # Prepare context about user/group
        user_context = f"<@{self.user_id}>" if self.user_id else ""
        group_context = f"<@{self.user_group}>" if self.user_group else ""
        identity_context = " and ".join(filter(None, [user_context, group_context]))
        
        # Prepare prompt
        prompt = f"""
        Analyze this Slack thread and provide:
        1. List 3-5 key points starting with •
        2. Identify actions required from {identity_context} specifically, including who requested/expects these actions
        3. Identify actions required from other users, including who requested/expects these actions
        4. Provide a one-line status about whether {identity_context} needs to take any action

        IMPORTANT: Always maintain Slack's user mention format (<@U123...>) in your responses. Do not convert user IDs to any other format.

        5. Calculate the following scores (0.0 to 1.0):
           - Urgency Score: How time-sensitive is the thread?
             • 1.0: Immediate action needed (e.g., "urgent", "ASAP", "blocking", "production issue")
             • 0.7: Soon but not immediate (e.g., "by tomorrow", "this week")
             • 0.4: Normal timing (e.g., "when you can", "next sprint")
             • 0.1: No time pressure
           
           - Topic Score: How important is the subject matter?
             • 1.0: Critical (e.g., production, security, customer impact)
             • 0.7: Important (e.g., features, bugs, planning)
             • 0.4: Normal (e.g., updates, discussions)
             • 0.1: Low priority (e.g., minor issues, FYI)
           
           - Question Score: How many direct questions need answers?
             • 1.0: Multiple urgent questions
             • 0.7: Several questions
             • 0.4: One or two questions
             • 0.0: No questions
           
           - Action Score: How much action/work is required?
             • 1.0: Major work required
             • 0.7: Significant tasks
             • 0.4: Minor tasks
             • 0.0: No action needed

        Format your response exactly as follows:
        [Key Points]
        • point 1 (with user mentions like <@U123ABC>)
        • point 2
        • point 3

        [My Actions]
        • action: <action description with user mentions like <@U123ABC>>
        • requested_by: <@U123ABC>, <@U456DEF>

        [Others Actions]
        • action: <action description with user mentions like <@U123ABC>>
        • requested_by: <@U123ABC>, <@U456DEF>

        [Status]
        • "Action required: <brief description>" OR "No action required" OR "Waiting on others: <brief description>"

        [Scores]
        • urgency: <0.0-1.0>
        • topic: <0.0-1.0>
        • question: <0.0-1.0>
        • action: <0.0-1.0>

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
            scores = {
                'urgency': 0.0,
                'topic': 0.0,
                'question': 0.0,
                'action': 0.0
            }
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
                elif line.startswith('[Scores]'):
                    current_section = 'scores'
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
                    elif current_section == 'scores':
                        if ':' in line:
                            score_type, value = line.split(':', 1)
                            score_type = score_type.strip()
                            try:
                                value = float(value.strip())
                                if 0 <= value <= 1:
                                    scores[score_type] = value
                            except (ValueError, KeyError):
                                pass
            
            return ThreadAnalysis(
                key_points=points,
                my_action=my_action,
                others_action=others_action,
                action_status=status,
                urgency_score=scores['urgency'],
                topic_score=scores['topic'],
                question_score=scores['question'],
                action_score=scores['action']
            )
            
        except Exception as e:
            self.logger.error(f"Error analyzing thread: {e}")
            return ThreadAnalysis(
                key_points=["Error analyzing thread"],
                my_action=None,
                others_action=None,
                action_status="Error analyzing thread",
                urgency_score=0.0,
                topic_score=0.0,
                question_score=0.0,
                action_score=0.0
            ) 
"""
Web UI for Thread Priority Queue

This module provides a web interface to view the priority queue of Slack threads.
It uses Flask for the backend and updates the view periodically.
"""

from flask import Flask, render_template, jsonify
from datetime import datetime
import threading
import time
from thread_priority_queue import ThreadPriorityQueue
from typing import Optional, Dict, Any
import os
import webbrowser

# Create Flask app with correct template directory
template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates'))
app = Flask(__name__, template_folder=template_dir)

# Global reference to the priority queue
priority_queue: Optional[ThreadPriorityQueue] = None

def format_timestamp(ts: float) -> str:
    """Format Unix timestamp to readable datetime"""
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

def get_slack_message_link(channel_id: str, message_ts: str, thread_ts: Optional[str] = None) -> str:
    """Generate a Slack message link using archives format
    
    Args:
        channel_id: The Slack channel ID
        message_ts: The message timestamp
        thread_ts: Optional thread timestamp for thread context
        
    Returns:
        Slack archive URL for the message
    """
    # Convert timestamp to Slack's p-number format (remove dots and pad)
    p_ts = message_ts.replace('.', '')
    
    # Base URL
    base_url = f"https://grab.slack.com/archives/{channel_id}/p{p_ts}"
    
    # Add thread context if available
    if thread_ts:
        base_url += f"?thread_ts={thread_ts}&cid={channel_id}"
        
    return base_url

def format_llm_analysis(thread_info: Any) -> Dict[str, Any]:
    """Format LLM analysis data for the UI
    
    Args:
        thread_info: ThreadInfo object containing messages and analysis
        
    Returns:
        Formatted analysis data
    """
    if not hasattr(thread_info, 'analysis') or not thread_info.analysis:
        return {
            'key_points': [],
            'my_action': None,
            'others_action': None,
            'action_status': "No analysis available",
            'scores': {
                'urgency': 0.0,
                'topic': 0.0,
                'question': 0.0,
                'action': 0.0
            }
        }
    
    analysis = thread_info.analysis
    return {
        'key_points': analysis.key_points,
        'my_action': {
            'action': analysis.my_action.action,
            'requested_by': analysis.my_action.requested_by
        } if analysis.my_action else None,
        'others_action': {
            'action': analysis.others_action.action,
            'requested_by': analysis.others_action.requested_by
        } if analysis.others_action else None,
        'action_status': analysis.action_status,
        'scores': {
            'urgency': analysis.urgency_score,
            'topic': analysis.topic_score,
            'question': analysis.question_score,
            'action': analysis.action_score
        }
    }

@app.route('/')
def index():
    """Render the main page"""
    return render_template('index.html')

@app.route('/api/threads')
def get_threads():
    """API endpoint to get current threads"""
    if not priority_queue:
        return jsonify([])
        
    threads = priority_queue.get_top_threads()
    thread_data = []
    
    for thread in threads:
        # Get first and last message timestamps
        first_msg_ts = thread.messages[0]['ts']
        last_msg_ts = thread.messages[-1]['ts']
        
        # Format thread data
        thread_data.append({
            'channel_id': thread.channel_id,
            'thread_ts': thread.thread_ts,
            'importance_score': thread.importance.final_score,
            'activity_score': thread.importance.activity_score,
            'content_score': thread.importance.content_score,
            'user_score': thread.importance.user_score,
            'temporal_score': thread.importance.temporal_score,
            'message_count': len(thread.messages),
            'first_message': {
                'text': thread.messages[0].get('text', ''),
                'timestamp': format_timestamp(float(first_msg_ts)),
                'link': get_slack_message_link(thread.channel_id, first_msg_ts, thread.thread_ts)
            },
            'last_message': {
                'text': thread.messages[-1].get('text', ''),
                'timestamp': format_timestamp(float(last_msg_ts)),
                'link': get_slack_message_link(thread.channel_id, last_msg_ts, thread.thread_ts)
            },
            'thread_link': get_slack_message_link(thread.channel_id, thread.thread_ts),
            'last_updated': format_timestamp(thread.last_updated),
            'analysis': format_llm_analysis(thread)
        })
    
    return jsonify(thread_data)

def set_priority_queue(queue: ThreadPriorityQueue):
    """Set the global priority queue reference"""
    global priority_queue
    priority_queue = queue

def open_browser(port: int):
    """Open the web browser after a short delay"""
    time.sleep(1.5)  # Wait for Flask to start
    webbrowser.open(f'http://127.0.0.1:{port}')

def run_web_ui(host: str = '127.0.0.1', port: int = 5000):
    """Run the Flask web server and open browser"""
    # Start browser in a separate thread
    browser_thread = threading.Thread(
        target=open_browser,
        args=(port,)
    )
    browser_thread.daemon = True
    browser_thread.start()
    
    # Disable Flask access logging
    import logging
    log = logging.getLogger('werkzeug')
    log.disabled = True
    
    # Run Flask app
    app.run(host=host, port=port, debug=False) 
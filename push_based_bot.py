"""
Push-based Slack bot using Socket Mode and callbacks.
Listens for messages that mention the user or their groups.

Required Environment Variables:
- SLACK_BOT_TOKEN: Slack bot token for Socket Mode
- SLACK_APP_TOKEN: App token for Socket Mode
- SLACK_USER_TOKEN: User token for thread access
- SLACK_USER_ID: ID of the user to track mentions for
- GEMINI_API_KEY: API key for Gemini LLM
"""
import os
import logging
import time
from dotenv import load_dotenv
from slack.slack_client_push_impl import SlackClientPushImpl
from slack.message_formatter import DefaultMessageFormatter
from llm.thread_analyzer import ThreadAnalyzer
from importance_calculator import ImportanceCalculator
from thread_priority_queue import ThreadPriorityQueue
from thread_state_manager import ThreadStateManager
from ui.web_ui import run_web_ui, set_priority_queue
from datetime import datetime
import threading
from dataclasses import dataclass
from dacite import from_dict
import re

#TODO: move caching to a separate file
class UserNameCache:
    def __init__(self, client, cache_ttl=3600):  # TTL in seconds
        self.client = client
        self.cache = {}
        self.cache_ttl = cache_ttl
        self.last_update = {}
    
    def get_user_name(self, user_id):
        current_time = time.time()
        # Check if we have a cached value that hasn't expired
        if user_id in self.cache:
            if current_time - self.last_update[user_id] < self.cache_ttl:
                return self.cache[user_id]
        try:
            # Fetch from Slack API using the user_app client
            user_info = self.client.user_app.client.users_info(user=user_id)
            user_name = user_info["user"]["profile"]["display_name"]
            if not user_name:
                user_name = user_info["user"]["real_name"]
            # Update cache
            self.cache[user_id] = user_name
            self.last_update[user_id] = current_time
            return user_name
        except Exception as e:
            print(f"Error fetching user info for {user_id}: {e}")
            return f"<@{user_id}>"  # Return original format on error

def format_message_with_names_cached(message_text, user_cache):
    # Match the entire mention pattern including any special characters
    user_mentions = re.findall(r'<@[A-Z0-9]+>', message_text)
    formatted_text = message_text
    for mention in user_mentions:
        # Extract user ID by removing <@ and >
        user_id = mention[2:-1]
        user_name = user_cache.get_user_name(user_id)
        formatted_text = formatted_text.replace(mention, f'@{user_name}')
    return formatted_text

# Load environment variables
load_dotenv()

def process_thread_analysis(
    channel_id: str,
    thread_ts: str,
    messages: list,
    client,
    logger,
    analyzer,
    calculator,
    priority_queue
) -> None:
    """Process a thread with LLM analysis and importance calculation."""
    try:
        # Calculate thread metadata
        metadata = client.get_thread_metadata(messages)
        
        # Get LLM analysis
        logger.info("\nStarting LLM analysis...")
        analysis = analyzer.analyze_thread(messages)
        logger.info("LLM analysis completed")
        
        # Format user mentions in analysis results
        user_cache = UserNameCache(client)
        if analysis.key_points:
            analysis.key_points = [format_message_with_names_cached(point, user_cache)
                                 for point in analysis.key_points]
        
        # Format my_action if it exists
        if analysis.my_action:
            analysis.my_action.action = format_message_with_names_cached(
                analysis.my_action.action, user_cache
            )
            if analysis.my_action.requested_by:
                analysis.my_action.requested_by = [
                    format_message_with_names_cached(name, user_cache)
                    for name in analysis.my_action.requested_by
                ]
        
        # Format others_action if it exists
        if analysis.others_action:
            analysis.others_action.action = format_message_with_names_cached(
                analysis.others_action.action, user_cache
            )
            if analysis.others_action.requested_by:
                analysis.others_action.requested_by = [
                    format_message_with_names_cached(name, user_cache)
                    for name in analysis.others_action.requested_by
                ]
        
        # Calculate importance score
        importance = calculator.calculate_importance(metadata, analysis)
        
        # Add/update thread in priority queue
        priority_queue.add_or_update_thread(
            channel_id=channel_id,
            thread_ts=thread_ts,
            importance=importance,
            messages=messages,
            analysis=analysis
        )
        
        # Log analysis results
        logger.info(f"\nProcessed thread in <#{channel_id}>:")
        logger.info(f"• Score: {importance.final_score:.2f}")
        logger.info(f"• Messages: {len(messages)}")
        if analysis:
            logger.info(f"• Key Points: {len(analysis.key_points)}")
            
        return importance, analysis
        
    except Exception as e:
        logger.error(f"Error processing thread analysis: {str(e)}")
        return None, None

def review_threads(
    state_manager: ThreadStateManager,
    client,
    logger,
    analyzer,
    calculator,
    priority_queue
) -> None:
    """Worker function to periodically review threads."""
    logger.info("🔄 Starting thread review worker")
    
    while True:
        try:
            # Get threads needing review
            threads = state_manager.get_threads_for_review()
            logger.info(f"\nChecking for threads to review...")
            
            if threads:
                logger.info(f"\n📊 Reviewing {len(threads)} threads")
                
                for channel_id, thread_ts, state in threads:
                    # Fetch updated history if needed
                    if state_manager.should_fetch_history(channel_id, thread_ts):
                        messages = client.fetch_thread_replies(channel_id, thread_ts)
                        state = state_manager.update_thread_state(
                            channel_id=channel_id,
                            thread_ts=thread_ts,
                            messages=messages
                        )
                    
                    # Process thread
                    importance, analysis = process_thread_analysis(
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        messages=state.messages,
                        client=client,
                        logger=logger,
                        analyzer=analyzer,
                        calculator=calculator,
                        priority_queue=priority_queue
                    )
                    
                    # Mark as processed
                    state_manager.mark_thread_processed(
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        analysis=analysis,
                        importance_score=importance.final_score if importance else None
                    )
                
                # Show current top 5 threads
                logger.info("\n📈 Top 5 Important Threads:")
                for idx, thread in enumerate(priority_queue.get_top_threads(5), 1):
                    logger.info(f"{idx}. Channel: <#{thread.channel_id}> | Score: {thread.importance.final_score:.2f}")
            
            # Sleep until next review cycle
            threading.Event().wait(30)
            
        except Exception as e:
            logger.error(f"Error in review worker: {str(e)}")
            threading.Event().wait(30)  # Still sleep on error

def handle_message(channel_id, message, client, logger, formatter, analyzer, calculator, priority_queue, state_manager):
    """Callback function to handle messages that mention the user or their groups."""
    try:
        # Get thread timestamp - if it's a reply, use the parent thread's ts
        thread_ts = message.get('thread_ts') or message.get('ts')
        
        # Update state manager with the new message
        state = state_manager.update_thread_state(
            channel_id=channel_id,
            thread_ts=thread_ts,
            new_message=message
        )
        
        # If we need to fetch history, do it now
        if state_manager.should_fetch_history(channel_id, thread_ts):
            thread_messages = client.fetch_thread_replies(channel_id, thread_ts)
            state = state_manager.update_thread_state(
                channel_id=channel_id,
                thread_ts=thread_ts,
                messages=thread_messages
            )
        
        # Print thread header for logging
        logger.info(f"\n{'='*50}")
        logger.info(f"Thread in <#{channel_id}>")
        logger.info(f"{'='*50}\n")
        
        # Print the new message
        try:
            user_info = client.user_app.client.users_info(user=message.get('user'))['user']
            user_name = user_info.get('real_name', user_info.get('name', 'Unknown'))
            
            # Format timestamp
            ts = float(message.get('ts', 0))
            dt = datetime.fromtimestamp(ts)
            time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            
            logger.info(f"[{time_str}] {user_name}:")
            logger.info(formatter.format_message(message, client))
            
            # Print reactions if any
            if message.get('reactions'):
                reaction_str = ' | '.join(
                    f":{reaction['name']}: x{reaction['count']}"
                    for reaction in message['reactions']
                )
                logger.info(f"Reactions: {reaction_str}")
        except Exception as e:
            # Fallback to basic formatting if user info fails
            logger.info(formatter.format_message(message, client))
        
        logger.info(f"\n{'='*50}")
        
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")

def main():
    # Set up logging with clean format for readability
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )
    logger = logging.getLogger(__name__)
    
    # Initialize components
    client = SlackClientPushImpl()
    client.initialize()
    formatter = DefaultMessageFormatter(logger)
    analyzer = ThreadAnalyzer()  # Initialize LLM analyzer
    calculator = ImportanceCalculator()  # Initialize importance calculator
    priority_queue = ThreadPriorityQueue()  # Initialize priority queue
    state_manager = ThreadStateManager()  # Initialize state manager
    
    # Set up web UI
    set_priority_queue(priority_queue)  # Share queue with web UI
    web_thread = threading.Thread(
        target=run_web_ui,
        kwargs={'host': '127.0.0.1', 'port': 5000}
    )
    web_thread.daemon = True
    web_thread.start()
    logger.info("🌐 Web UI available at http://127.0.0.1:5000")
    
    # Start thread review worker
    review_thread = threading.Thread(
        target=review_threads,
        args=(state_manager, client, logger, analyzer, calculator, priority_queue)
    )
    review_thread.daemon = True
    review_thread.start()
    logger.info("🔄 Thread review worker started")
    
    # Register our message handler
    def callback(channel_id, message):
        handle_message(
            channel_id, message, client, logger, formatter,
            analyzer, calculator, priority_queue, state_manager
        )
    
    client.register_message_callback(callback)
    
    logger.info("🚀 Starting bot... Press Ctrl+C to exit")
    
    try:
        # Start listening for events
        client.start()
    finally:
        # Clean shutdown
        state_manager.stop()

if __name__ == "__main__":
    main()

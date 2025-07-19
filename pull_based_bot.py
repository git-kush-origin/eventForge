"""
Pull-based Slack Bot for Thread Analysis

This script fetches and analyzes Slack threads where the user is mentioned.
It uses LLM-based analysis to provide summaries, identify action items,
and track thread statistics.

Key Features:
- Fetches messages from specified Slack channels
- Groups messages into threads
- Analyzes threads using LLM
- Identifies actions required from user and others
- Provides thread statistics and metadata
- Optional detailed thread view with all replies

Required Environment Variables:
- SLACK_USER_TOKEN: Slack user token for API access
- SLACK_USER_ID: ID of the user to track mentions for
- SLACK_USER_GROUP: (Optional) User's group ID
- GEMINI_API_KEY: API key for Gemini LLM
"""

import logging
import argparse
from slack.slack_client_factory import SlackClientFactory
from llm.thread_analyzer import ThreadAnalyzer

def should_show_thread(thread_messages: list, client) -> bool:
    """
    Determine if a thread should be shown based on user mentions
    
    This function checks if any message in the thread contains:
    - Direct mention of the user (@user)
    - Group mention that includes the user (@group)
    - Any other form of mention tracked by the client
    
    Args:
        thread_messages: List of messages in the thread
        client: ISlackClient instance that implements mention checking
        
    Returns:
        bool: True if thread contains at least one message mentioning the user
    """
    for msg in thread_messages:
        if client.is_user_mentioned(msg):
            return True
    return False

def main():
    """
    Main entry point for the pull-based Slack bot.
    
    Flow:
    1. Initialize logging and parse arguments
    2. Set up Slack client, formatter, and analyzer
    3. Fetch messages from channels
    4. Group messages into threads
    5. Analyze relevant threads
    6. Display results with formatting
    """
    # Set up logging with a clean format for readability
    logging.basicConfig(
        level=logging.INFO,
        format='%(message)s'
    )
    logger = logging.getLogger(__name__)

    # Parse command line arguments for customization
    parser = argparse.ArgumentParser(description='Fetch and analyze recent Slack messages')
    parser.add_argument('--hours', type=int, default=1, help='Hours of history to fetch')
    parser.add_argument('--show-thread', action='store_true', help='Show full thread details including replies')
    args = parser.parse_args()

    # Initialize all components using the factory pattern
    # This ensures consistent creation and proper dependency injection
    client = SlackClientFactory.create_client("pull")  # Pull-based client for fetching messages
    formatter = SlackClientFactory.create_formatter(logger)  # Formatter for consistent output
    analyzer = ThreadAnalyzer()  # LLM-based thread analyzer
    
    # Get timestamp for message history
    # Default to 48 hours to ensure we don't miss any important threads
    oldest_ts = client.get_timestamp_n_hours_ago(48)
    
    # Get channels configured for monitoring
    # The client implementation handles channel whitelisting
    channels = client.get_user_channels()
    
    # Process each channel sequentially
    for channel in channels:
        channel_id = channel["id"]
        channel_name = channel["name"]
        
        # Fetch all messages from the channel within our time window
        messages = client.fetch_channel_messages(channel_id, oldest_ts, channel_name)
        
        if not messages:
            continue
            
        # Group messages by their thread
        # This ensures we have complete context for analysis
        threads = {}
        for msg in messages:
            # thread_ts identifies the parent message
            # if not a thread reply, use the message's own ts
            thread_ts = msg.get('thread_ts') or msg.get('ts')
            
            # If this is a new thread we haven't seen before
            if thread_ts not in threads:
                threads[thread_ts] = []
                # For threaded messages, fetch the complete thread
                if msg.get('thread_ts'):
                    thread_messages = client.fetch_thread_replies(channel_id, thread_ts)
                    threads[thread_ts].extend(thread_messages)
                else:
                    # For standalone messages, just add them as-is
                    threads[thread_ts].append(msg)
            
        # Filter to only threads with user mentions
        # This reduces noise and focuses on relevant conversations
        relevant_threads = {
            ts: msgs for ts, msgs in threads.items()
            if should_show_thread(msgs, client)
        }
        
        # Display messages only if we found relevant threads
        if relevant_threads:
            # Print channel header
            logger.info(f"\n{'='*50}")
            logger.info(f"Messages from #{channel_name}")
            logger.info(f"{'='*50}\n")
            
            # Sort threads by timestamp for chronological display
            sorted_threads = sorted(relevant_threads.items(), key=lambda x: float(x[0]))
            
            # Process each thread
            for thread_ts, thread_messages in sorted_threads:
                # Sort messages within thread chronologically
                thread_messages.sort(key=lambda x: float(x.get('ts', '0')))
                
                # Get thread analysis and metadata
                metadata = client.get_thread_metadata(thread_messages)
                analysis = analyzer.analyze_thread(thread_messages)
                
                # Display thread information in sections:
                
                # 1. Original message that started the thread
                parent_msg = thread_messages[0]
                logger.info(formatter.format_message(parent_msg, client))
                
                # 2. Current status of the thread
                logger.info(f"\nStatus: {analysis.action_status}")
                
                # 3. Key points identified by LLM
                logger.info("\nSummary:")
                for point in analysis.key_points:
                    logger.info(f"• {point}")
                
                # 4. Thread statistics and metadata
                formatter.log_thread_stats(logger, metadata)
                
                # 5. Required actions section
                if analysis.my_action or analysis.others_action:
                    if analysis.my_action:
                        logger.info("\nAction Required From You:")
                        logger.info(f"→ {str(analysis.my_action)}")
                    if analysis.others_action:
                        logger.info("\nAction Required From Others:")
                        logger.info(f"→ {str(analysis.others_action)}")
                
                # 6. Optional: Full thread replies if requested
                if len(thread_messages) > 1 and args.show_thread:
                    logger.info("\nReplies:")
                    # Skip the parent message as it's already shown
                    for i, reply in enumerate(thread_messages[1:], 1):
                        # Use tree-like formatting for visual thread structure
                        prefix = "    └─" if i == len(thread_messages[1:]) else "    ├─"
                        reply_text = formatter.format_message(reply, client, prefix)
                        logger.info(reply_text)
                
                # Add separator between threads
                logger.info(f"\n{'='*50}")

if __name__ == "__main__":
    main() 
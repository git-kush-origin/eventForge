"""
Thread State Manager

This module manages thread states and optimizes thread processing by:
1. Maintaining thread history and state
2. Managing message batching
3. Optimizing API calls
4. Handling high-frequency threads efficiently
5. Periodic batch processing of threads
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Set
import time
import logging
import threading
from llm.thread_analyzer import ThreadAnalysis

@dataclass
class ThreadAnalysisState:
    """State of thread analysis"""
    last_analysis: Optional[ThreadAnalysis]
    analysis_version: int
    last_processed_ts: str
    importance_score: float

@dataclass
class ThreadState:
    """State information for a thread"""
    thread_id: str              # thread_ts
    channel_id: str            # Slack channel ID
    messages: List[Dict]       # All known messages
    last_fetch_time: float     # Last time thread history was fetched
    last_analysis_time: float  # Last time thread was analyzed
    last_message_time: float   # Timestamp of most recent message
    needs_history_fetch: bool  # Whether thread history needs to be fetched
    is_parent_message_seen: bool  # Whether we've seen the parent message
    analysis_state: Optional[ThreadAnalysisState] = None

class ThreadStateManager:
    """
    Manages thread states and optimizes processing.
    
    Features:
    - Thread state caching
    - Smart API usage
    - Periodic batch processing
    - Message truncation
    - Worker-based processing
    """
    
    def __init__(
        self,
        review_interval: float = 30.0,
    ):
        """
        Initialize the thread state manager.
        
        Args:
            review_interval: Seconds between batch processing reviews
            fetch_cooldown: Minimum seconds between thread history fetches
        """
        self.thread_states: Dict[str, ThreadState] = {}
        self.review_interval = review_interval
        self.logger = logging.getLogger(__name__)
        
        # Track threads with new messages
        self.threads_with_updates: Set[str] = set()
        self._lock = threading.Lock()

    def get_thread_key(self, channel_id: str, thread_ts: str) -> str:
        """Generate unique key for thread"""
        return f"{channel_id}:{thread_ts}"

    def should_fetch_history(self, channel_id: str, thread_ts: str) -> bool:
        """
        Determine if thread history should be fetched.
        
        Returns True if:
        1. Thread is not in state
        2. Thread needs history fetch flag is set
        3. Parent message hasn't been seen
        
        Note: Cooldown check removed as batching is handled by review cycle
        """
        thread_key = self.get_thread_key(channel_id, thread_ts)
        state = self.thread_states.get(thread_key)
        
        if not state:
            return True
            
        return state.needs_history_fetch or not state.is_parent_message_seen

    def update_thread_state(
        self,
        channel_id: str,
        thread_ts: str,
        messages: Optional[List[Dict]] = None,
        new_message: Optional[Dict] = None
    ) -> ThreadState:
        """
        Update thread state with new messages or a single new message.
        
        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            messages: Optional complete message history
            new_message: Optional single new message
            
        Returns:
            Updated ThreadState
        """
        thread_key = self.get_thread_key(channel_id, thread_ts)
        current_time = time.time()
        
        with self._lock:
            # Get or create thread state
            state = self.thread_states.get(thread_key)
            if not state:
                state = ThreadState(
                    thread_id=thread_ts,
                    channel_id=channel_id,
                    messages=[],
                    last_fetch_time=0,
                    last_analysis_time=0,
                    last_message_time=current_time,
                    needs_history_fetch=True,
                    is_parent_message_seen=False
                )
                self.thread_states[thread_key] = state
            
            # Update with complete message history if provided
            if messages:
                # Sort messages by timestamp
                sorted_messages = sorted(messages, key=lambda x: float(x['ts']))
                
                # Check if we have the parent message
                if sorted_messages and sorted_messages[0]['ts'] == thread_ts:
                    state.is_parent_message_seen = True
                
                # Update state
                state.messages = sorted_messages
                state.last_fetch_time = current_time
                state.needs_history_fetch = False
                
                # Update last message time
                if sorted_messages:
                    state.last_message_time = float(sorted_messages[-1]['ts'])
                    
                    # Add to threads_with_updates if we have messages
                    # This ensures the thread gets reviewed for prioritization
                    self.threads_with_updates.add(thread_key)
                
                self.logger.info(
                    f"Updated thread {thread_key} state:"
                    f"\n• Messages: {len(state.messages)}"
                    f"\n• Parent Seen: {state.is_parent_message_seen}"
                    f"\n• Last Message: {state.last_message_time}"
                )
            
            # Add new message if provided
            if new_message:
                new_ts = float(new_message['ts'])
                
                # Check if this is the parent message
                if new_message['ts'] == thread_ts:
                    state.is_parent_message_seen = True
                
                # Add to messages if newer than what we have
                if not state.messages or new_ts > float(state.messages[-1]['ts']):
                    state.messages.append(new_message)
                    state.messages.sort(key=lambda x: float(x['ts']))
                    state.last_message_time = new_ts
                    
                    # Mark thread for review
                    self.threads_with_updates.add(thread_key)
                    
                    self.logger.debug(
                        f"Added new message to {thread_key}"
                        f"\n• Messages: {len(state.messages)}"
                        f"\n• Last Message Time: {state.last_message_time}"
                    )
            
            return state

    def get_threads_for_review(self) -> List[Tuple[str, str, ThreadState]]:
        """
        Get threads that have received updates in the review interval.
        
        Returns:
            List of (channel_id, thread_ts, state) tuples
        """
        current_time = time.time()
        review_threads = []
        
        with self._lock:
            # Get all threads with updates
            for thread_key in list(self.threads_with_updates):
                state = self.thread_states[thread_key]
                
                # Check if thread had updates in review interval
                time_since_message = current_time - state.last_message_time
                if time_since_message <= self.review_interval:
                    channel_id, thread_ts = thread_key.split(':')
                    review_threads.append((channel_id, thread_ts, state))
                else:
                    # Remove from updates set if too old
                    self.threads_with_updates.remove(thread_key)
        
        return review_threads

    def mark_thread_processed(
        self,
        channel_id: str,
        thread_ts: str,
        analysis: Optional[ThreadAnalysis] = None,
        importance_score: Optional[float] = None
    ) -> None:
        """Mark a thread as processed and update its analysis state"""
        thread_key = self.get_thread_key(channel_id, thread_ts)
        
        with self._lock:
            if thread_key in self.threads_with_updates:
                self.threads_with_updates.remove(thread_key)
            
            state = self.thread_states.get(thread_key)
            if state:
                state.last_analysis_time = time.time()
                
                if analysis is not None and importance_score is not None:
                    if not state.analysis_state:
                        state.analysis_state = ThreadAnalysisState(
                            last_analysis=analysis,
                            analysis_version=1,
                            last_processed_ts=thread_ts,
                            importance_score=importance_score
                        )
                    else:
                        state.analysis_state.last_analysis = analysis
                        state.analysis_state.analysis_version += 1
                        state.analysis_state.last_processed_ts = thread_ts
                        state.analysis_state.importance_score = importance_score

    def stop(self) -> None:
        """Stop the worker thread"""
        pass  # No longer needed as worker is removed

    def get_thread_state(
        self,
        channel_id: str,
        thread_ts: str
    ) -> Optional[ThreadState]:
        """Get current state of a thread"""
        thread_key = self.get_thread_key(channel_id, thread_ts)
        return self.thread_states.get(thread_key) 
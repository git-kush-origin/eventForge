"""
Thread Priority Queue Module

This module maintains a priority queue of threads based on their importance scores.
Key features:
1. Maintains max 20 most important threads
2. Updates existing threads if they're analyzed again
3. Uses heap queue for efficient priority management
4. Thread uniqueness based on channel_id + thread_ts
"""

from typing import Dict, List, NamedTuple, Optional
from dataclasses import dataclass
import heapq
import time
import logging
from importance_calculator import ImportanceFactors
from llm.thread_analyzer import ThreadAnalysis

@dataclass
class ThreadInfo:
    """Information about a thread in the queue"""
    channel_id: str
    thread_ts: str
    importance: ImportanceFactors
    messages: List[Dict]
    last_updated: float  # timestamp of last update
    analysis: Optional[ThreadAnalysis] = None  # LLM analysis results

    def get_thread_key(self) -> str:
        """Get unique key for the thread"""
        return f"{self.channel_id}:{self.thread_ts}"

class PrioritizedThread:
    """Wrapper class for thread info with priority queue support"""
    def __init__(self, thread_info: ThreadInfo):
        self.thread_info = thread_info
        # Negative score because heapq is a min heap and we want max scores
        self.priority = -thread_info.importance.final_score
        self.timestamp = time.time()  # Used as tiebreaker

    def __lt__(self, other):
        # First compare by priority (importance score)
        if self.priority != other.priority:
            return self.priority < other.priority
        # If priorities are equal, newer threads come first
        return self.timestamp > other.timestamp

class ThreadPriorityQueue:
    """Maintains a priority queue of threads based on importance scores"""
    
    def __init__(self, max_size: int = 20):
        """Initialize the priority queue
        
        Args:
            max_size: Maximum number of threads to maintain (default: 20)
        """
        self.max_size = max_size
        self.queue: List[PrioritizedThread] = []  # Heap queue
        self.thread_map: Dict[str, PrioritizedThread] = {}  # For O(1) lookups
        self.logger = logging.getLogger(__name__)
    
    def add_or_update_thread(
        self,
        channel_id: str,
        thread_ts: str,
        importance: ImportanceFactors,
        messages: List[Dict],
        analysis: Optional[ThreadAnalysis] = None
    ) -> None:
        """Add a new thread or update existing one in the queue
        
        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
            importance: Calculated importance factors
            messages: List of messages in the thread
            analysis: Optional LLM analysis results
        """
        thread_info = ThreadInfo(
            channel_id=channel_id,
            thread_ts=thread_ts,
            importance=importance,
            messages=messages,
            last_updated=time.time(),
            analysis=analysis
        )
        
        thread_key = thread_info.get_thread_key()
        new_thread = PrioritizedThread(thread_info)
        
        # If thread exists, remove it and its old priority
        if thread_key in self.thread_map:
            old_thread = self.thread_map[thread_key]
            old_score = -old_thread.priority  # Convert back to positive score
            self.logger.info(
                f"\nUpdating existing thread in <#{channel_id}>"
                f"\n• Old Score: {old_score:.2f}"
                f"\n• New Score: {importance.final_score:.2f}"
                f"\n• Score Change: {importance.final_score - old_score:+.2f}"
            )
            self._remove_thread(thread_key)
        else:
            self.logger.info(
                f"\nAdding new thread from <#{channel_id}>"
                f"\n• Initial Score: {importance.final_score:.2f}"
            )
        
        # Add new/updated thread
        heapq.heappush(self.queue, new_thread)
        self.thread_map[thread_key] = new_thread
        
        # If we're over capacity, remove lowest priority thread
        if len(self.queue) > self.max_size:
            removed = heapq.heappop(self.queue)
            removed_key = removed.thread_info.get_thread_key()
            removed_score = -removed.priority
            self.logger.info(
                f"\nRemoving lowest priority thread from <#{removed.thread_info.channel_id}>"
                f"\n• Score: {removed_score:.2f}"
                f"\n• Reason: Queue over capacity (max: {self.max_size})"
            )
            del self.thread_map[removed_key]
    
    def get_top_threads(self, n: Optional[int] = None) -> List[ThreadInfo]:
        """Get top N threads by importance score
        
        Args:
            n: Number of threads to return. If None, returns all threads.
        
        Returns:
            List of ThreadInfo objects sorted by importance (highest first)
        """
        if n is None:
            n = len(self.queue)
        
        # Create a copy of the queue for sorting
        temp_queue = self.queue.copy()
        result = []
        
        # Pop top N items
        for _ in range(min(n, len(temp_queue))):
            thread = heapq.heappop(temp_queue)
            result.append(thread.thread_info)
        
        return result
    
    def _remove_thread(self, thread_key: str) -> None:
        """Remove a thread from the queue by its key
        
        Args:
            thread_key: Unique thread identifier (channel_id:thread_ts)
        """
        if thread_key not in self.thread_map:
            return
            
        # Find and remove from queue
        thread_to_remove = self.thread_map[thread_key]
        self.queue = [t for t in self.queue if t != thread_to_remove]
        heapq.heapify(self.queue)  # Restore heap property
        
        # Remove from map
        del self.thread_map[thread_key]
    
    def get_thread(self, channel_id: str, thread_ts: str) -> Optional[ThreadInfo]:
        """Get a specific thread by its identifiers
        
        Args:
            channel_id: Slack channel ID
            thread_ts: Thread timestamp
        
        Returns:
            ThreadInfo if found, None otherwise
        """
        thread_key = f"{channel_id}:{thread_ts}"
        if thread_key in self.thread_map:
            return self.thread_map[thread_key].thread_info
        return None
    
    def __len__(self) -> int:
        """Get number of threads in queue"""
        return len(self.queue) 
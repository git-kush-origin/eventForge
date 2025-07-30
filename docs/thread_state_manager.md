# Thread State Manager

## Why Thread State Manager?

The Thread State Manager addresses several critical challenges in real-time Slack thread processing:

### 1. Real-time Processing Challenges
Without a state manager, real-time thread processing faces these issues:
- Every new slack event is independent of its predecesors even when belonging to an existing thread. This would require us to trigger immediate API calls to fetch slack history for the entire thread.
- Each event would require separate LLM analysis
- Thread context is fetched repeatedly
- High costs for API and LLM usage
- Performance degradation in high-traffic channels

### 2. Cost & Resource Optimization
The state manager provides significant savings:
```mermaid
graph LR
    A[Without TSM] --> B[10 messages]
    B --> C[10 API calls]
    C --> D[10 LLM analyses]
    D --> E[$10 cost*]
    
    F[With TSM] --> G[10 messages]
    G --> H[1 API call]
    H --> I[1 LLM analysis]
    I --> J[$1 cost*]
    
    style E fill:#ffcccc
    style J fill:#ccffcc
    
    %% *Hypothetical costs for illustration
```

### 3. Smart Caching Benefits
- **API Efficiency**: Reduces Slack API calls by up to 90%
- **LLM Cost Reduction**: Batches messages for single analysis
- **Memory Optimization**: Deduplicates messages and maintains clean state
- **Context Preservation**: Maintains thread history and parent messages

### 4. Real-world Impact
Example scenarios showing TSM benefits:

1. **High-frequency Thread**
   - Without TSM: 100 API calls, 100 analyses per hour
   - With TSM: ~12 API calls, ~2 analyses per hour
   - Result: 88% reduction in API usage, 98% reduction in LLM costs

2. **Multiple Active Threads**
   - Without TSM: Each thread processed independently
   - With TSM: Batch processing across threads
   - Result: Linear scaling with thread count

3. **Long-running Threads**
   - Without TSM: Context lost between updates
   - With TSM: Persistent thread state
   - Result: Better analysis quality and context awareness

This document provides a detailed explanation of the ThreadStateManager component, which optimizes thread processing and state management in the Slack bot.

## Core Data Structures

```mermaid
classDiagram
    class ThreadState {
        +str thread_id
        +str channel_id
        +List[Dict] messages
        +float last_fetch_time
        +float last_analysis_time
        +float last_message_time
        +bool needs_history_fetch
        +bool is_parent_message_seen
        +AnalysisState analysis_state
    }

    class AnalysisState {
        +ThreadAnalysis last_analysis
        +int analysis_version
        +str last_processed_ts
        +float importance_score
    }

    class ThreadStateManager {
        -Dict[str, ThreadState] thread_states
        -Set[str] threads_with_updates
        -float review_interval
        -float fetch_cooldown
        -Lock _lock
        -Thread _worker_thread
        +update_thread_state()
        +should_fetch_history()
        +get_threads_for_review()
        +mark_thread_processed()
    }

    ThreadStateManager --> ThreadState : manages
    ThreadState --> AnalysisState : has
```

## How It Works: A Real-world Flow

### 1. Message Reception Flow
```mermaid
sequenceDiagram
    participant Bot as Push Based Bot
    participant TSM as Thread State Manager
    participant Slack as Slack API

    Bot->>TSM: New message received
    TSM->>TSM: update_thread_state()
    Note over TSM: Creates/updates thread state<br>Adds to threads_with_updates
    
    TSM->>TSM: should_fetch_history()?
    alt Needs History
        Bot->>Slack: Fetch thread history
        Slack-->>Bot: Complete thread history
        Bot->>TSM: update_thread_state(messages=history)
        Note over TSM: Updates state with full history<br>Marks thread for review
    end
```

1. **New Message Arrives**
   - Bot receives Slack event
   - Calls `update_thread_state` with new message
   - ThreadStateManager either:
     - Creates new thread state, or
     - Updates existing thread state
   - Thread is marked for review in `threads_with_updates`

2. **History Check**
   - Bot checks `should_fetch_history`
   - Returns true if:
     - Thread is new
     - Parent message missing
     - History fetch needed
   - If true, bot:
     - Fetches complete thread history
     - Updates state with full history

### 2. Review and Analysis Flow
```mermaid
sequenceDiagram
    participant Bot as Review Worker
    participant TSM as Thread State Manager
    participant LLM as Thread Analyzer
    participant PQ as Priority Queue

    loop Every 30 seconds
        Bot->>TSM: get_threads_for_review()
        TSM-->>Bot: List of threads needing review
        
        loop Each Thread
            Bot->>LLM: Analyze thread
            LLM-->>Bot: Analysis results
            Bot->>PQ: Update priority
            Bot->>TSM: mark_thread_processed()
            Note over TSM: Removes from threads_with_updates<br>Updates analysis state
        end
    end
```

1. **Review Cycle** (<a href='../push_based_bot.py'>review_threads in push_based_bot.py</a>)
   - Every 30 seconds, bot's review worker:
     - Calls <a href='../thread_state_manager.py'>get_threads_for_review</a> to get pending threads
     - Gets threads from `threads_with_updates` set
     - Only returns threads updated within review interval

2. **Thread Processing** (<a href='../push_based_bot.py'>process_thread_analysis in push_based_bot.py</a>)
   - For each thread:
     - Performs LLM analysis
     - Calculates importance
     - Updates priority queue
     - Calls <a href='../thread_state_manager.py'>mark_thread_processed</a>

3. **State Updates** 
   - `mark_thread_processed`:
     - Removes thread from `threads_with_updates`
     - Updates analysis state
     - Increments analysis version
     - Records importance score

### 3. State Management Details

1. **Thread State Lifecycle**
   - New Message: Creates initial state, marks for history fetch
   - History Fetch: Updates with complete thread history
   - Analysis: Adds analysis results and importance score

2. **Update Types**
   - Single Message: Adds to existing thread state
   - Full History: Updates entire thread history
   - Analysis: Updates thread importance and version

## Key Benefits

1. **API Efficiency**
   - Reduces API calls by batching requests
   - Example: 10 messages → 1 API call instead of 10

2. **LLM Cost Reduction**
   - Batches messages for single analysis
   - Example: 5 messages → 1 analysis instead of 5

3. **Memory Optimization**
   - Maintains single copy of thread history
   - Prevents duplicate messages
   - Cleans up old thread states

## Simple Integration Example

```python
# Initialize
state_manager = ThreadStateManager(review_interval=30.0)

# When new message arrives
def on_message(message):
    # Update state and check if history needed
    if state_manager.should_fetch_history(message.channel, message.thread_ts):
        history = fetch_thread_history()
        state_manager.update_thread_state(messages=history)
    else:
        state_manager.update_thread_state(new_message=message)

# Review cycle (runs every 30s)
def review():
    for thread in state_manager.get_threads_for_review():
        analyze_and_prioritize(thread)
        state_manager.mark_thread_processed(thread)
``` 
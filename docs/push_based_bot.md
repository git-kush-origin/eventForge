# Push-Based Slack Bot Documentation

This document outlines the functionality of the push-based Slack bot that analyzes slack threads in real-time using Socket Mode which uses Slack's Boult format.

## Problem Statement

A busy user on slack can attes how annoying and overwheling it gets to constantly recieve slack message alerts all day long and the timeless efforts it takes to go through these upcoming stream of events, manually seeking prioritisation of one over the other. This project aims to automate the prioritisation of these threads on behalf of the user, allocating an importance score to each of the slack thread based on content, activitiy and temporal importance of thread, employing LLM in the background.

## Overview

The bot listens for real-time Slack events and analyzes threads where:
- The user is mentioned
- The user has replied
- The user is the thread owner

Providing:
- Periodic thread analysis (every 30 seconds)
- Thread importance scoring
- Priority-based thread queue
- Real-time web UI visualization

## Package Documentation
- [Slack Package](../slack/docs/slack_client.md): Core messaging and formatting functionality
- [LLM Package](../llm/docs/thread_analyzer.md): Thread analysis and action identification


## Architecture

### 1. Component Architecture
This diagram shows the system's main components and their relationships:

```mermaid
graph TB
    subgraph Slack["Slack Workspace"]
        SM["Socket Mode Events Listener<br/><a href='../push_based_bot.py'>push_based_bot.py (120-125)</a>"]
        Thread1[Thread #1]
        Thread2[Thread #2] -->|New Messages incoming| SM
        Thread3[Thread #3]
    end

    subgraph StateLayer["State Management"]
        TSM["Thread State Manager<br/><a href='../thread_state_manager.py'>thread_state_manager.py (45-60)</a>
        (maintains the slack thread states locally
        for optimised cost effective results)"]
        TS["Maintain Thread's State<br/><a href='../thread_state_manager.py'>thread_state_manager.py (80-95)</a>"]
        TU["Update Threads with new messages<br/><a href='../thread_state_manager.py'>thread_state_manager.py (100-115)</a>"]
    end

    subgraph ProcessingLayer["Processing Layer"]
        RW["Review Worker<br/><a href='../push_based_bot.py'>push_based_bot.py (150-165)</a>
        (Batch threads eligible for
        LLM analysis and process)"]
        LLM["LLM Analyzer<br/><a href='../llm/thread_analyzer.py'>thread_analyzer.py (30-45)</a>"]
        IC["Importance Calculator<br/><a href='../importance_calculator.py'>importance_calculator.py (25-40)</a>"]
    end

    subgraph Storage["Storage & UI"]
        PQ["Priority Queue<br/><a href='../thread_priority_queue.py'>thread_priority_queue.py (20-35)</a>"]
        WebUI["Web Interface<br/><a href='../ui/web_ui.py'>web_ui.py (15-30)</a>"]
    end

    SM --> TSM
    Thread1 & Thread2 & Thread3 --> SM
    
    TSM --> TS
    TSM --> TU
    
    TU --> RW
    TS --> RW
    
    RW --> LLM
    LLM --> IC
    IC --> PQ
    PQ --> WebUI

    style TSM fill:#E6F3FF,stroke:#333,stroke-width:4px
    style RW fill:#FFF0E6,stroke:#333,stroke-width:4px
```

### 2. Message Processing Flow
This sequence diagram shows how messages flow through the system, from reception to analysis:

```mermaid
sequenceDiagram
    participant S as Slack
    participant TSM as ThreadStateManager
    participant RW as ReviewWorker
    participant LLM as LLM Analyzer
    participant IC as ImportanceCalc
    participant PQ as PriorityQueue
    participant UI as WebUI

    Note over S,UI: Message Reception Flow
    S->>TSM: New Message
    TSM->>TSM: Update State
    alt Needs History
        TSM->>S: Fetch Thread
        S-->>TSM: Thread History
        TSM->>TSM: Update State
    end
    TSM->>TSM: Mark for Review

    Note over S,UI: Review Cycle (Every 30s)
    RW->>TSM: Get Review Threads
    TSM-->>RW: Threads List
    loop Each Thread
        alt Needs History
            RW->>S: Fetch Updated History
            S-->>RW: Thread History
            RW->>TSM: Update State
        end
        RW->>LLM: Analyze Thread
        LLM-->>IC: Analysis Results
        IC->>PQ: Update Queue
        RW->>TSM: Mark Processed
    end
    PQ->>UI: Refresh View
```

### 3. Detailed Processing Steps
This diagram breaks down the specific steps in each processing phase:

```mermaid
graph TD
    A[Start] --> B[Initialize Components];
    B --> C[Start Socket Mode];
    C --> D[Start Thread Review Worker];
    D --> E[Start Web UI];
    
    subgraph EventFlow[Event Processing]
        F[Receive Message] --> G[Update Thread State];
        G --> H{Need History?};
        H -- Yes --> I[Fetch Thread History];
        H -- No --> J[Log Message];
    end
    
    subgraph ReviewFlow[Review Processing]
        K[Every 30s] --> L[ThreadStateManager];
        L --> M[Get Threads for Review];
        M --> N{For Each Thread};
        N --> O{Need History?};
        O -- Yes --> P[Fetch Updated History];
        P --> Q[Update Thread State];
        O -- No --> R[Get Current State];
        Q --> S[Process with LLM];
        R --> S;
        S --> T[Update Priority Queue];
        T --> U[Mark Thread Processed];
        U --> N;
    end
    
    subgraph WebUI[Web Interface]
        V[Priority Queue] --> W[Display Threads];
        W --> X[Show Analysis];
        X --> Y[Expandable Details];
    end

    style L fill:#f9f,stroke:#333,stroke-width:2px
```

Each diagram provides a different perspective:
1. **Message Processing Flow**: Shows the temporal sequence of operations and interactions between components
2. **Component Architecture**: Illustrates the system's structure and component relationships
3. **Detailed Processing Steps**: Breaks down the specific steps within each processing phase

## The Need for Thread State Management

### Problem Statement

Without dedicated state management, the bot faces several challenges in real-time thread processing:

1. **Redundant API Calls**
   - Every new message triggers a full thread history fetch
   - No tracking of what's already been fetched
   - Unnecessary load on Slack API
   - Example: In a high-activity thread with 10 messages/minute, that's 10 redundant API calls fetching the same history

2. **Inefficient LLM Usage**
   - Each message triggers immediate LLM analysis
   - No batching of messages for analysis
   - Higher costs due to frequent LLM API calls
   - Example: A burst of 5 messages in 10 seconds triggers 5 separate LLM analyses instead of one batch analysis

3. **Memory and Processing Overhead**
   - No message deduplication
   - Repeated processing of unchanged threads
   - Growing memory usage with duplicate message storage
   - Example: A thread with 100 messages gets stored multiple times, once per update

### Basic vs Optimized Approach

```mermaid
graph LR
    subgraph Basic["Without State Management"]
        direction LR
        M1[Message 1] --> F1[Fetch History]
        F1 --> A1[Analyze]
        A1 --> Q1[Update Queue]
        M2[Message 2] --> F2[Fetch History]
        F2 --> A2[Analyze]
        A2 --> Q2[Update Queue]
        M3[Message 3] --> F3[Fetch History]
        F3 --> A3[Analyze]
        A3 --> Q3[Update Queue]
    end

    subgraph Optimized["With State Management"]
        direction LR
        N1[Message 1] & N2[Message 2] & N3[Message 3] --> S[Update State]
        S --> B{Review Cycle<br/>30s}
        B --> F[Single Fetch]
        F --> A[Batch Analysis]
        A --> Q[Update Queue]
    end

    style Basic fill:#FFE6E6,stroke:#333,stroke-width:2px,color:#000
    style Optimized fill:#E6F3FF,stroke:#333,stroke-width:2px,color:#000
    linkStyle default stroke:#000,stroke-width:2px
    classDef default fill:#fff,stroke:#333,stroke-width:2px,color:#000
```

The comparison highlights key differences:

1. **Without State Management**
   - Each message triggers independent processing
   - Redundant API calls and analysis
   - Higher costs and resource usage
   - No message batching

2. **With State Management**
   - Messages update local state
   - Batch processing every 30 seconds
   - Single API call for updates
   - One analysis for multiple messages
   - Efficient resource utilization

For detailed implementation of the ThreadStateManager, including data structures, operations, and integration guide, see [Thread State Manager Documentation](thread_state_manager.md).

## Components Used

The bot uses several components:
- `ThreadStateManager`: State and processing management
- `SlackClientPushImpl`: Slack communication
- `ThreadAnalyzer`: LLM-based analysis
- `ImportanceCalculator`: Score calculation
- `ThreadPriorityQueue`: Thread prioritization
- `WebUI`: Real-time visualization

## Usage

Run the bot with:
```bash
python push_based_bot.py
```

The bot will:
1. Initialize all components
2. Start the review worker
3. Launch the web UI
4. Begin processing events

## Environment Variables
Required environment variables:
- `SLACK_BOT_TOKEN`: Bot token for event handling
- `SLACK_USER_TOKEN`: User token for data access
- `SLACK_APP_TOKEN`: App token for Socket Mode
- `SLACK_USER_ID`: ID of the user to track mentions for
- `GEMINI_API_KEY`: API key for Gemini LLM

## Key Differences from Pull-Based Bot

1. **Event Handling**:
   - Push: Real-time via Socket Mode with state management
   - Pull: Periodic polling

2. **Processing Model**:
   - Push: State-based with periodic reviews
   - Pull: Direct processing on poll

3. **Thread Tracking**:
   - Push: Comprehensive (mentions, replies, owned threads)
   - Pull: Mention-based only

4. **Analysis Timing**:
   - Push: Periodic batch processing
   - Pull: Immediate on poll

5. **UI Integration**:
   - Push: Real-time web interface
   - Pull: Console output only 
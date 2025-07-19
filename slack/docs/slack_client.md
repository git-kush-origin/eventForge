# Slack Package Documentation

This package provides a modular interface for interacting with Slack, handling message formatting, and managing client implementations.

## Architecture Overview

```mermaid
classDiagram
    %% Core Interfaces
    class ISlackClient["ISlackClient<br/><a href='../slack_client.py'>slack_client.py (31-86)</a>"] {
        <<interface>>
        +initialize()
        +get_user_channels()
        +fetch_channel_messages()
        +fetch_thread_replies()
        +is_user_mentioned()
        +get_thread_metadata()
    }
    
    class IMessageFormatter["IMessageFormatter<br/><a href='../message_formatter.py'>message_formatter.py (8-105)</a>"] {
        <<interface>>
        +format_message()
        +format_reactions()
        +format_thread_metadata()
        +log_thread_stats()
    }

    %% Implementations
    class SlackPullClient["SlackPullClient<br/><a href='../slack_client_pull_impl.py'>slack_client_pull_impl.py (12-332)</a>"] {
        +initialize()
        +fetch_channel_messages()
        +fetch_thread_replies()
    }

    class SlackPushClient["SlackPushClient<br/><a href='../slack_client_push_impl.py'>slack_client_push_impl.py (12-102)</a>"] {
        +initialize()
        +handle_message_events()
        +start()
    }

    class DefaultMessageFormatter["DefaultMessageFormatter<br/><a href='../message_formatter.py'>message_formatter.py (108-130)</a>"] {
        +format_message()
        +format_reactions()
        +log_thread_stats()
    }

    %% Factory
    class SlackClientFactory["SlackClientFactory<br/><a href='../slack_client_factory.py'>slack_client_factory.py (5-40)</a>"] {
        +create_client()
        +create_formatter()
    }

    %% Relationships
    ISlackClient <|.. SlackPullClient : implements
    ISlackClient <|.. SlackPushClient : implements
    IMessageFormatter <|.. DefaultMessageFormatter : implements
    SlackClientFactory ..> SlackPullClient : creates
    SlackClientFactory ..> SlackPushClient : creates
    SlackClientFactory ..> DefaultMessageFormatter : creates
```

## Package Components

### Core Interfaces

#### [`ISlackClient`](../slack_client.py)
Interface defining all Slack operations. See [interface documentation](slack_client.md) for details.

#### [`IMessageFormatter`](../message_formatter.py)
Interface for message formatting operations. See [formatter documentation](message_formatter.md) for details.

### Implementations

#### [`SlackPullClient`](../slack_client_pull_impl.py)
Pull-based implementation using Slack's Web API. See [pull client documentation](slack_client_pull_impl.md) for details.

#### [`SlackPushClient`](../slack_client_push_impl.py)
Push-based implementation using Slack's Socket Mode. See [push client documentation](slack_client_push_impl.md) for details.

#### [`DefaultMessageFormatter`](../message_formatter.py)
Default implementation of message formatting. See [formatter documentation](message_formatter.md) for details.

### Factory

#### [`SlackClientFactory`](../slack_client_factory.py)
Factory for creating appropriate client and formatter instances. See [factory documentation](slack_client_factory.md) for details.

## Usage

The package is designed to be used through the factory pattern:

```python
from slack.slack_client_factory import SlackClientFactory

# Create a pull-based client
client = SlackClientFactory.create_client("pull")

# Create a formatter
formatter = SlackClientFactory.create_formatter(logger)
```

## Environment Variables
- `SLACK_USER_TOKEN`: Slack user token for API access
- `SLACK_BOT_TOKEN`: Slack bot token (for push-based client)
- `SLACK_SIGNING_SECRET`: Slack signing secret (for push-based client)
- `SLACK_APP_TOKEN`: Slack app-level token (for Socket Mode)
- `SLACK_USER_ID`: ID of the user to track mentions for 
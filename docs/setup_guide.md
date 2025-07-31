# Slack Analyzer Setup Guide

## Two Implementation Options

### 1. Pull-Based Setup (Simpler, No App Required)
This approach polls channels periodically instead of using real-time events.

#### Requirements:
- Only needs `SLACK_USER_TOKEN`
- No Slack app creation needed
- Can reuse existing configuration

#### Steps:
1. Get your User Token:
   - Go to the existing Slack app page
   - Under "OAuth & Permissions", get your User Token (`xoxp-` prefix)
2. Create `.env` file:
```
SLACK_USER_TOKEN=xoxp-your-user-token
GEMINI_API_KEY=your-gemini-api-key
GEMINI_API_ENDPOINT=your-gemini-endpoint
```
3. Run with pull-based implementation:
```python
python pull_based_bot.py
```

### 2. Push-Based Setup (Real-time Events, Requires App)
This approach uses Socket Mode for real-time event streaming.

#### Requirements:
- Needs own Slack app with Socket Mode
- Requires three tokens:
  - Bot Token (`SLACK_BOT_TOKEN`)
  - App Token (`SLACK_APP_TOKEN`)
  - User Token (`SLACK_USER_TOKEN`)

#### Steps:

1. **Create Slack App**
   - Go to [Slack API](https://api.slack.com/apps)
   - Click "Create New App" → "From scratch"
   - Name it and select workspace

2. **Configure Bot Permissions**
   Add these OAuth scopes:
   - `channels:history`
   - `channels:read`
   - `groups:history`
   - `groups:read`
   - `users:read`
   - `users:read.email`
   - `team:read`
   - `chat:write`
   - `im:history`
   - `im:read`
   - `reactions:read`

3. **Configure User Token Scopes**
   Add these scopes:
   - `channels:history`
   - `channels:read`
   - `groups:history`
   - `groups:read`
   - `users:read`
   - `team:read`

4. **Enable Socket Mode**
   - Go to "Socket Mode" in settings
   - Enable it
   - Get App Token (`xapp-` prefix)

5. **Install App**
   - Go to "Install App"
   - Click "Install to Workspace"
   - Get Bot Token (`xoxb-` prefix)
   - Get User Token (`xoxp-` prefix)

6. **Configure Environment**
   Create `.env` file:
```
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
SLACK_USER_TOKEN=xoxp-your-user-token
SLACK_USER_ID=your-user-id
GEMINI_API_KEY=your-gemini-api-key
GEMINI_API_ENDPOINT=your-gemini-endpoint
```

7. **Run Bot**
```python
python push_based_bot.py
```

## Choosing Between Pull and Push

### Pull-Based (Simple Setup)
✅ Advantages:
- Easier to set up
- No app creation needed
- Can share configuration
- Works with just user token

❌ Disadvantages:
- Not real-time
- Higher API usage
- Rate limits apply
- Periodic polling only

### Push-Based (Real-time)
✅ Advantages:
- Real-time events
- More efficient
- Better for immediate responses
- Lower API usage

❌ Disadvantages:
- Requires app creation
- More complex setup
- Each user needs own app
- More tokens to manage

## Security Notes
- Never share your tokens
- Don't commit `.env` file
- Rotate tokens periodically
- Keep app tokens secure

## Troubleshooting
- For permission errors, check OAuth scopes
- For Socket Mode issues, verify app token
- For access issues, check channel memberships
- For rate limits, consider using pull-based approach

## Support
- Check application logs for errors
- Verify all environment variables
- Ensure proper workspace permissions
- Contact Slack admin for access issues
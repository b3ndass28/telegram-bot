# Referens Bot

## Render Environment Variables

Set these in Render → Environment:

```text
BOT_TOKEN=your_bot_token_from_BotFather
CHAT_ID=-100xxxxxxxxxx
```

Do not put the token inside the code.

## Required Telegram setup

1. Create a Telegram bot through BotFather.
2. Create a Telegram group.
3. Enable Topics in the group.
4. Add the bot as admin.
5. Give the bot permission to Manage Topics.
6. Run `/id` to get the group Chat ID.
7. Put BOT_TOKEN and CHAT_ID into Render Environment Variables.

## Instagram cookies

For Instagram downloads/screenshots, add `cookies.txt` to the project root.

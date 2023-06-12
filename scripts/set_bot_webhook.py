from telegram import Bot

def set_bot_webhook(lambda_url, bot_token):
    community_id = bot_token
    bot = Bot(token=bot_token)
    webhook_url = f"{lambda_url}?community_id={community_id}"
    success = bot.setWebhook(url=webhook_url)
    if success:
        print(f"Webhook set successfully for {bot.username}.")
    else:
        print(f"Failed to set webhook for {bot.username}.")


if __name__ == "__main__":
    # read url and token from program arguments
    import sys
    if len(sys.argv) < 3:
        print("Usage: python set_bot_webhook.py <lambda_url> <bot_token>")
        exit(1)
        
    lambda_url = sys.argv[1]
    token = sys.argv[2]
    set_bot_webhook(lambda_url, token)
import os
import logging
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from supabase import create_client, Client
import sys

def get_env_variable(var_name, prompt_text, is_secret=False):
    value = os.getenv(var_name)
    if not value:
        if is_secret:
            import getpass
            value = getpass.getpass(f"{prompt_text}: ")
        else:
            value = input(f"{prompt_text}: ")
        if not value:
            logging.error(f"Required configuration '{var_name}' was not provided. Exiting.")
            sys.exit(1)
    return value

def run_bot():
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    slack_bot_token = get_env_variable("SLACK_BOT_TOKEN", "Enter Slack Bot Token (xoxb-)", is_secret=True)
    slack_app_token = get_env_variable("SLACK_APP_TOKEN", "Enter Slack App Token (xapp-)", is_secret=True)
    supabase_url = get_env_variable("SUPABASE_URL", "Enter Supabase Project URL")
    supabase_service_key = get_env_variable("SUPABASE_SERVICE_KEY", "Enter Supabase Service Role Key", is_secret=True)
    target_slack_user_id = get_env_variable("TARGET_SLACK_USER_ID", "Enter Target Slack User ID (e.g., UXXXXXXXXXX)")
    supabase_table_name = os.getenv("SUPABASE_TABLE_NAME")
    if not supabase_table_name:
        supabase_table_name = input("Enter Supabase Table Name (default: slack_messages_for_sensay): ") or "slack_messages_for_sensay"

    logger.info("Initializing Deshi Knowledge Collector Bot...")

    try:
        slack_app = App(token=slack_bot_token)
        supabase_client: Client = create_client(supabase_url, supabase_service_key)

        logger.info(f"Supabase client initialized for URL: {supabase_url}")
        logger.info(f"Monitoring messages from Slack User ID: {target_slack_user_id}")
        logger.info(f"Storing messages in Supabase table: {supabase_table_name}")

        @slack_app.event("message")
        def handle_message_events(event, say):
            event_user_id = event.get("user")
            message_text = event.get("text")
            channel_id = event.get("channel")
            message_ts = event.get("ts")

            if event.get("subtype") is None and event_user_id == target_slack_user_id and message_text:
                logger.info(f"Received message from target user ({event_user_id}) in channel ({channel_id}): '{message_text[:70]}...'")
                try:
                    data_to_insert = {
                        "slack_user_id": event_user_id,
                        "slack_channel_id": channel_id,
                        "message_content": message_text,
                        "slack_message_ts": message_ts
                    }
                    response = supabase_client.table(supabase_table_name).insert(data_to_insert).execute()
                    if response.data:
                        logger.info(f"Message successfully stored in Supabase. ID: {response.data[0]['id']}")
                    else:
                        logger.warning(f"Supabase insert did not return data: {response.error if response.error else 'No error info'}")
                        if response.error and "violates unique constraint" in str(response.error.message).lower():
                             logger.warning(f"Duplicate message (slack_message_ts: {message_ts}) not inserted.")
                        elif response.error:
                             logger.error(f"Failed to store message in Supabase: {response.error}")
                except Exception as e_db:
                    logger.error(f"Error storing message in Supabase: {e_db}", exc_info=True)

        socket_handler = SocketModeHandler(slack_app, slack_app_token)
        logger.info("Connecting to Slack via Socket Mode...")
        socket_handler.start()

    except Exception as e_main:
        logger.critical(f"A critical error occurred: {e_main}", exc_info=True)
    finally:
        logger.info("Bot has shut down or encountered a critical error.")

if __name__ == "__main__":
    run_bot()

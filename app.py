import streamlit as st
import os
import logging
import threading
import time
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from supabase import create_client, Client
import io
import sys

# --- Initial Configuration ---
load_dotenv() # Load .env file if present, UI will override
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Streamlit Log Capture ---
# This class will capture stdout and stderr to be displayed in Streamlit
class StreamlitLogHandler(io.StringIO):
    def __init__(self):
        super().__init__()
        self.buffer = [] # Store log messages

    def write(self, message):
        # Add message to internal buffer
        self.buffer.append(message)
        # Also write to actual stdout/stderr for console logging
        sys.__stdout__.write(message) # Or sys.__stderr__

    def get_logs(self):
        return "".join(self.buffer)

    def clear_logs(self):
        self.buffer = []
        self.truncate(0)
        self.seek(0)

# --- Bot Logic (Encapsulated in a function) ---
def start_slack_bot_listener(config, stop_event, log_capture_buffer):
    slack_bot_token = config["SLACK_BOT_TOKEN"]
    slack_app_token = config["SLACK_APP_TOKEN"]
    supabase_url = config["SUPABASE_URL"]
    supabase_service_key = config["SUPABASE_SERVICE_KEY"]
    target_slack_user_id = config["TARGET_SLACK_USER_ID"]
    supabase_table_name = config.get("SUPABASE_TABLE_NAME", "slack_messages_for_sensay")

    # Redirect stdout and stderr for this thread
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = log_capture_buffer
    sys.stderr = log_capture_buffer

    logger.info("Bot thread started. Initializing Slack and Supabase clients...")
    log_capture_buffer.write("Bot thread started. Initializing Slack and Supabase clients...\n")

    try:
        bot_app = App(token=slack_bot_token)
        supabase: Client = create_client(supabase_url, supabase_service_key)

        logger.info(f"Supabase client initialized for URL: {supabase_url}")
        logger.info(f"Monitoring messages from Slack User ID: {target_slack_user_id}")
        logger.info(f"Storing messages in Supabase table: {supabase_table_name}")
        log_capture_buffer.write(f"Supabase client initialized for URL: {supabase_url}\n")
        log_capture_buffer.write(f"Monitoring messages from Slack User ID: {target_slack_user_id}\n")
        log_capture_buffer.write(f"Storing messages in Supabase table: {supabase_table_name}\n")


        @bot_app.event("message")
        def handle_message_events(event, say):
            event_user_id = event.get("user")
            message_text = event.get("text")
            channel_id = event.get("channel")
            message_ts = event.get("ts")

            if event.get("subtype") is None and event_user_id == target_slack_user_id and message_text:
                log_msg = f"Received message from target user ({event_user_id}) in channel ({channel_id}): '{message_text[:50]}...'"
                logger.info(log_msg)
                log_capture_buffer.write(log_msg + "\n")

                try:
                    data_to_insert = {
                        "slack_user_id": event_user_id,
                        "slack_channel_id": channel_id,
                        "message_content": message_text,
                        "slack_message_ts": message_ts
                    }
                    response = supabase.table(supabase_table_name).insert(data_to_insert).execute()

                    if response.data:
                        log_msg = f"Message successfully stored in Supabase. ID: {response.data[0]['id']}"
                        logger.info(log_msg)
                        log_capture_buffer.write(log_msg + "\n")
                    else:
                        err_msg = f"Supabase insert did not return data: {response.error if response.error else 'No error info'}"
                        logger.warning(err_msg)
                        log_capture_buffer.write(f"WARNING: {err_msg}\n")
                        if response.error and "violates unique constraint" in str(response.error.message).lower():
                            logger.warning(f"Duplicate message (slack_message_ts: {message_ts}) not inserted.")
                            log_capture_buffer.write(f"WARNING: Duplicate message (slack_message_ts: {message_ts}) not inserted.\n")

                except Exception as e:
                    err_msg = f"Error storing message in Supabase: {e}"
                    logger.error(err_msg)
                    log_capture_buffer.write(f"ERROR: {err_msg}\n")

        logger.info("Starting SocketModeHandler...")
        log_capture_buffer.write("Starting SocketModeHandler...\n")
        handler = SocketModeHandler(bot_app, slack_app_token)
        
        # Start the handler. This is blocking.
        # The thread will keep running this until the handler stops or an error occurs.
        # The stop_event is not directly used by handler.start() here.
        handler.start() 

    except Exception as e:
        err_msg = f"Critical error in bot thread: {e}"
        logger.error(err_msg, exc_info=True)
        log_capture_buffer.write(f"CRITICAL ERROR: {err_msg}\n")
    finally:
        logger.info("Bot thread attempting to clean up and exit.")
        log_capture_buffer.write("Bot thread attempting to clean up and exit.\n")
        sys.stdout = original_stdout # Restore original stdout
        sys.stderr = original_stderr # Restore original stderr


# --- Streamlit UI ---
st.set_page_config(page_title="Deshi Knowledge Collector", layout="wide")
st.title("🚀 Deshi Knowledge Collector Bot")
st.caption("Collects Slack messages from a designated user and stores them in Supabase.")

# Initialize session state variables
if 'env_vars_confirmed' not in st.session_state:
    st.session_state.env_vars_confirmed = False
if 'bot_started' not in st.session_state:
    st.session_state.bot_started = False
if 'bot_thread' not in st.session_state:
    st.session_state.bot_thread = None
if 'stop_event' not in st.session_state:
    # stop_event is used to signal the thread, though SocketModeHandler().start() doesn't use it directly for stopping
    st.session_state.stop_event = threading.Event() 
if 'streamlit_log_handler' not in st.session_state:
    st.session_state.streamlit_log_handler = StreamlitLogHandler()


# --- Configuration Input Area ---
if not st.session_state.env_vars_confirmed:
    st.subheader("Step 1: Configure Environment Variables")
    with st.form("env_var_form"):
        st.markdown("These values will be used to run the Slack bot. They are stored in session state and not persisted beyond your browser session unless you use a .env file as a fallback.")
        
        slack_bot_token = st.text_input("Slack Bot Token (xoxb-)", value=os.getenv("SLACK_BOT_TOKEN", ""), type="password")
        slack_app_token = st.text_input("Slack App Token (xapp-)", value=os.getenv("SLACK_APP_TOKEN", ""), type="password")
        supabase_url = st.text_input("Supabase Project URL", value=os.getenv("SUPABASE_URL", ""))
        supabase_service_key = st.text_input("Supabase Service Role Key", value=os.getenv("SUPABASE_SERVICE_KEY", ""), type="password")
        target_slack_user_id = st.text_input("Target Slack User ID (e.g., UXXXXXXXXXX)", value=os.getenv("TARGET_SLACK_USER_ID", ""))
        supabase_table_name = st.text_input("Supabase Table Name", value=os.getenv("SUPABASE_TABLE_NAME", "slack_messages_for_sensay"))

        submitted = st.form_submit_button("Save Configuration")

        if submitted:
            missing = []
            if not slack_bot_token: missing.append("Slack Bot Token")
            if not slack_app_token: missing.append("Slack App Token")
            if not supabase_url: missing.append("Supabase URL")
            if not supabase_service_key: missing.append("Supabase Service Key")
            if not target_slack_user_id: missing.append("Target Slack User ID")
            # supabase_table_name can use default, so not strictly critical if empty initially

            critical_missing = [field for field in missing] # All fields are considered critical for now

            if critical_missing:
                 st.error(f"Please fill in all required fields: {', '.join(critical_missing)}")
            else:
                st.session_state.config = {
                    "SLACK_BOT_TOKEN": slack_bot_token,
                    "SLACK_APP_TOKEN": slack_app_token,
                    "SUPABASE_URL": supabase_url,
                    "SUPABASE_SERVICE_KEY": supabase_service_key,
                    "TARGET_SLACK_USER_ID": target_slack_user_id,
                    "SUPABASE_TABLE_NAME": supabase_table_name or "slack_messages_for_sensay"
                }
                st.session_state.env_vars_confirmed = True
                st.success("Configuration saved! You can now start the bot.")
                st.rerun() # Rerun to show the next section
else:
    st.subheader("Step 2: Manage Bot")
    st.success("Configuration is set.")
    
    col1, col2 = st.columns(2)
    with col1:
        st.write("Current Configuration (Secrets are masked):")
        config_display = {}
        if 'config' in st.session_state:
            config_display = {
                "SLACK_BOT_TOKEN": f"{st.session_state.config.get('SLACK_BOT_TOKEN', '')[:5]}..." if st.session_state.config.get('SLACK_BOT_TOKEN') else "Not Set",
                "SLACK_APP_TOKEN": f"{st.session_state.config.get('SLACK_APP_TOKEN', '')[:5]}..." if st.session_state.config.get('SLACK_APP_TOKEN') else "Not Set",
                "SUPABASE_URL": st.session_state.config.get('SUPABASE_URL', 'Not Set'),
                "SUPABASE_SERVICE_KEY": f"{st.session_state.config.get('SUPABASE_SERVICE_KEY', '')[:5]}..." if st.session_state.config.get('SUPABASE_SERVICE_KEY') else "Not Set",
                "TARGET_SLACK_USER_ID": st.session_state.config.get('TARGET_SLACK_USER_ID', 'Not Set'),
                "SUPABASE_TABLE_NAME": st.session_state.config.get('SUPABASE_TABLE_NAME', 'Not Set')
            }
        st.json(config_display)

    with col2:
        if not st.session_state.bot_started:
            if st.button("Start Bot Listener", key="start_bot"):
                if st.session_state.bot_thread is None or not st.session_state.bot_thread.is_alive():
                    st.session_state.streamlit_log_handler.clear_logs() # Clear previous logs
                    st.session_state.stop_event.clear() # Ensure stop event is clear before starting
                    st.session_state.bot_thread = threading.Thread(
                        target=start_slack_bot_listener,
                        args=(st.session_state.config, st.session_state.stop_event, st.session_state.streamlit_log_handler),
                        daemon=True 
                    )
                    st.session_state.bot_thread.start()
                    st.session_state.bot_started = True
                    st.info("Bot listener thread started. Check logs below.")
                    st.rerun() # Rerun to update log display loop
                else:
                    st.warning("Bot thread seems to be already running.")
        else:
            st.success("Bot listener is active (in a background thread).")
            if st.button("Reset Configuration (Stops UI indication, thread may continue)", key="stop_bot"):
                if st.session_state.stop_event:
                    st.session_state.stop_event.set() # Signal thread (though it might not be checked by the handler)
                
                # Give the thread a moment to potentially react if it were designed to
                # time.sleep(0.1) 

                st.session_state.bot_started = False
                st.session_state.env_vars_confirmed = False
                # Don't nullify bot_thread immediately if you want to check its status later
                # st.session_state.bot_thread = None 
                st.session_state.streamlit_log_handler.write("UI Stop requested. Resetting configuration.\n")
                st.warning("UI indication stopped. Bot thread may continue running in the background until the Streamlit app is fully closed.")
                st.rerun()

    st.subheader("Bot Logs")
    log_placeholder = st.empty()

    log_display_label = "Logs"
    log_display_content = "Bot not started or no logs yet."
    show_rerun_trigger_for_logs = False

    if st.session_state.bot_started:
        log_display_label = "Logs (Bot Active)"
        log_display_content = st.session_state.streamlit_log_handler.get_logs()
        
        if st.session_state.bot_thread and st.session_state.bot_thread.is_alive():
            show_rerun_trigger_for_logs = True
        elif st.session_state.bot_thread and not st.session_state.bot_thread.is_alive():
            st.warning("Bot thread appears to have stopped unexpectedly. Displaying last known logs.")
    
    elif 'streamlit_log_handler' in st.session_state and st.session_state.streamlit_log_handler.get_logs():
        log_display_label = "Logs (Bot Inactive)"
        log_display_content = st.session_state.streamlit_log_handler.get_logs()

    log_placeholder.text_area(
        log_display_label,
        value=log_display_content,
        height=300,
        key="bot_log_text_area_main_display",
        disabled=True
    )

    if show_rerun_trigger_for_logs:
        try:
            time.sleep(2) 
            st.rerun()
        except Exception as e:
            logger.warning(f"Exception during st.rerun for log update: {e}")


st.markdown("---")
st.markdown("Built with [Streamlit](https://streamlit.io), [Slack Bolt](https://slack.dev/bolt-python), and [Supabase](https://supabase.io).")

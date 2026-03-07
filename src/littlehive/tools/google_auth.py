import os
from littlehive.agent.logger_setup import logger
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from littlehive.agent.paths import TOKEN_PATH, CREDENTIALS_PATH

# Centralized scopes for the Ultimate EA
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/tasks",
]


def get_credentials():
    """Handles OAuth 2.0 authentication for all Google services."""
    creds = None
    # The file token.json stores the user's access and refresh tokens
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                # If refresh fails (e.g. scopes changed), force re-auth
                creds = None

        if not creds:
            if not os.path.exists(CREDENTIALS_PATH):
                logger.warning(f"WARNING: {CREDENTIALS_PATH} not found.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            # Fixed port to match Authorized redirect URIs in Google Cloud
            # We MUST use prompt='consent' to force Google to give us a new refresh_token
            creds = flow.run_local_server(port=53941, prompt="consent")

        # Save the credentials for the next run
        with open(TOKEN_PATH, "w") as token:
            token.write(creds.to_json())

    return creds

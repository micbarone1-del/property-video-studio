import smtplib
import imaplib
import email
import os
import pandas as pd
from email.message import EmailMessage
from dotenv import load_dotenv

import mimetypes
# Updated Google imports for OAuth 2.0 Flow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Load credentials from .env file
load_dotenv()
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")

PROCESSED_LOG_FILE = "processed_emails.txt"

def load_processed_ids():
    """Loads the list of processed email IDs from a file."""
    if not os.path.exists(PROCESSED_LOG_FILE):
        return set()
    with open(PROCESSED_LOG_FILE, 'r') as f:
        return set(line.strip() for line in f if line.strip())

def save_processed_id(message_id):
    """Appends a new processed email ID to the file."""
    if not message_id:
        return
    with open(PROCESSED_LOG_FILE, 'a') as f:
        f.write(f"{message_id}\n")

# --- INTEGRATED PROCESSOR FUNCTIONS ---

def excel_reading(archive_path):
    """
    Transforms Excel rows into a list of dictionaries (scenes).
    """
    if not os.path.exists(archive_path):
        print(f" Error: The file {archive_path} does not exist!")
        return []

    try:
        # Read the Excel file using Pandas
        df = pd.read_excel(archive_path)
        # Cleanup: remove rows that are completely empty
        df = df.dropna(how='all')
        # Convert to a list of dictionaries
        scenes = df.to_dict(orient='records')
        
        print(f" Success! {len(scenes)} scenes processed from spreadsheet.")
        return scenes
    except Exception as e:
        print(f"Error processing Excel: {e}")
        return []

# --- COMMUNICATION FUNCTIONS ---

def upload_to_drive(file_path):
    """
    Uploads a file to Google Drive and makes it publicly accessible via link.
    Uses OAuth2 to upload as the user, avoiding Service Account quota limits.
    Assumes an OAuth Client ID key named 'client_secret.json' is present.
    """
    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    creds = None
    
    # The file token.json stores the user's access and refresh tokens.
    # It is created automatically when the authorization flow completes for the first time.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists('client_secret.json'):
                print("ERROR: 'client_secret.json' not found. Please download your OAuth Client ID from Google Cloud Console.")
                return None
            
            # This triggers the browser popup for authentication
            flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0)
            
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('drive', 'v3', credentials=creds)

        file_metadata = {'name': os.path.basename(file_path)}
        
        # Add the target folder if specified in the environment variables
        if DRIVE_FOLDER_ID:
            file_metadata['parents'] = [DRIVE_FOLDER_ID]
        else:
            print("WARNING: DRIVE_FOLDER_ID not found in .env. Uploading to root directory.")
        
        ctype, encoding = mimetypes.guess_type(file_path)
        if ctype is None:
            ctype = 'application/octet-stream'

        media = MediaFileUpload(file_path, mimetype=ctype, resumable=True)

        print(f"Uploading {file_path} to Google Drive...")
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()

        # Make the file accessible to anyone with the link
        service.permissions().create(
            fileId=file.get('id'),
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()

        link = file.get('webViewLink')
        print(f"Upload successful. Link: {link}")
        return link

    except Exception as e:
        print(f"Error uploading to Google Drive: {e}")
        return None

def send_custom_email(recipient_address, subject, message_body, attachment_path=None):
    """
    Sends an email using SMTP. If attachment_path is provided, uploads the file 
    to Google Drive and appends the link to the message body.
    
    Args:
        recipient_address (str): The email address of the recipient.
        subject (str): The subject of the email.
        message_body (str): The body text of the email.
        attachment_path (str, optional): The file path of the attachment. Defaults to None.
        
    Returns:
        bool: True if email sent successfully, False otherwise.
    """
    if not EMAIL_USER or not EMAIL_PASS:
        print("Error: EMAIL_USER or EMAIL_PASS environment variables not set.")
        return False

    # Handle Attachment via Drive Upload
    if attachment_path and os.path.exists(attachment_path):
        print("Processing file for Drive upload...")
        drive_link = upload_to_drive(attachment_path)
        if drive_link:
            message_body += f"\n\nHere is the link to download your video:\n{drive_link}"
        else:
            message_body += f"\n\n(Note: We tried to upload your video to Google Drive but encountered an error. Please contact support.)"
    elif attachment_path:
        print(f"Warning: Attachment path '{attachment_path}' does not exist. Sending email without the link.")

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = EMAIL_USER
    msg['To'] = recipient_address
    msg.set_content(message_body)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
        print(f"Message sent to {recipient_address}")
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def download_and_process_latest_spreadsheet():
    """
    Scans the inbox for emails with spreadsheets, downloads the most recent one
    that hasn't been processed yet, and returns the sender's email.
    """
    host = 'imap.gmail.com'
    if not os.path.exists('downloads'):
        os.makedirs('downloads')

    processed_ids = load_processed_ids()

    try:
        mail = imaplib.IMAP4_SSL(host, 993)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")
        
        # Search for all emails
        status, messages = mail.search(None, 'ALL')
        mail_ids = messages[0].split()
        
        if not mail_ids:
            # print("📭 No messages found in inbox.") # Optional: reduce log spam
            return None

        # Analyze the most recent 5 emails in reverse order
        for num in reversed(mail_ids[-2:]): 
            # Fetch headers first to check Message-ID without downloading attachments
            status, header_data = mail.fetch(num, '(BODY.PEEK[HEADER])')
            
            msg_header = email.message_from_bytes(header_data[0][1])
            message_id = msg_header.get("Message-ID", "").strip()
            
            if message_id in processed_ids:
                # print(f"Skipping already processed email: {message_id}")
                continue

            # If not processed, fetch the full body
            status, data = mail.fetch(num, '(BODY.PEEK[])')
            for response_part in data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    for part in msg.walk():
                        if part.get_content_maintype() == 'multipart': continue
                        if part.get('Content-Disposition') is None: continue
                        
                        filename = part.get_filename()
                        if filename and filename.lower().endswith(('.xlsx', '.xls')):
                            filepath = os.path.join('downloads', filename)
                            
                            print(f" Spreadsheet found: {filename}")
                            with open(filepath, 'wb') as f:
                                f.write(part.get_payload(decode=True))

                            sender = msg.get("From")
                            
                            # Mark as processed immediately
                            save_processed_id(message_id)
                            
                            # Log out before processing the data
                            mail.close()
                            mail.logout()
                            
                            # Return sender to trigger workflow
                            return sender

        mail.close()
        mail.logout()
        # print(" No new spreadsheets found in recent emails.")
        return None

    except Exception as e:
        print(f"Critical error in workflow: {e}")
        return None

# --- INTEGRATED WORKFLOW TEST ---
if __name__ == "__main__":
    print(" Starting Integrated Workflow (Download + Processing)...")
    
    # This single command now handles the entire initial flow
    spreadsheet_data = download_and_process_latest_spreadsheet()
    
    if spreadsheet_data:
        print("\n--- DATA RECEIVED ---")
        for scene in spreadsheet_data:
            print(scene)
    else:
        print("\n No scenes were loaded.")
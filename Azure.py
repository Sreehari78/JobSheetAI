from typing import Optional
from langchain_openai import AzureChatOpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import asyncio
import logging
from telethon import TelegramClient, events
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from datetime import datetime, timezone
import ast

# -------- Configure Logging -------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("app.log", encoding="utf-8"),  # Log to a file with UTF-8 encoding
        logging.StreamHandler(),  # Stream logs to console
    ],
)

# -------- Load Environment Variables -------- #
load_dotenv()

# Telegram API Configuration
API_ID = os.getenv("TELEGRAM_API_ID")
API_HASH = os.getenv("TELEGRAM_API_HASH")
PHONE_NUM = os.getenv("TELEGRAM_PHONE")
CHANNELS = ["https://t.me/dot_aware", "https://t.me/OceanOfJobs", "https://t.me/blah1bla"]

# Google Sheets Configuration
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")

# Azure OpenAI API Configuration
AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_API_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

# -------- Initialize Azure OpenAI Client -------- #
client = AzureChatOpenAI(
    azure_deployment=AZURE_DEPLOYMENT_NAME,
    api_version=AZURE_API_VERSION,
    temperature=0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
)

# Collect all `.json` credential files in the current directory
CREDENTIALS_FILES = ["sheets/sreehari-credentials.json"]  # We will create this file dynamically in GitHub Actions

# -------- Add Structured Output Schema with Pydantic -------- #
class JobDetails(BaseModel):
    """Schema for structured job details extracted by the model."""
    company_name: str = Field(description="The name of the company.")
    job_role: str = Field(description="The specific job role or position.")
    ctc: Optional[str] = Field(description="The Cost to Company or salary information (e.g., 10-15 LPA).")
    years_of_experience: Optional[str] = Field(description="The required years of experience for the job.")
    passout_year: Optional[str] = Field(description="The passout year of the candidate.")
    application_link: Optional[str] = Field(description="The URL or link to apply for the job.")

# Enhance Azure OpenAI client with structured output
structured_client = client.with_structured_output(JobDetails)

# -------- Azure OpenAI Function -------- #
def extract_job_details(message: str) -> JobDetails:
    """
    Extract job details using the structured Azure OpenAI LLM.
    """
    prompt = [
        {
            "role": "system",
            "content": """
            Extract the following details from the message if it's a job posting:
            - Company Name
            - Job Role
            - CTC (Cost to Company / Salary)
            - Years of Experience
            - Passout Year
            - Application Link
            Return the details as a JSON object with exact keys: company_name, job_role, ctc, years_of_experience, passout_year, application_link.
            If any information is missing, leave it as an empty string. 
            """
        },
        {"role": "user", "content": message},
    ]
    try:
        # Send structured request to Azure OpenAI
        response = structured_client.invoke(prompt)  # Automatically parse into JobDetails structure
        logging.info(f"Structured Job Details: {response}")
        return response
    except Exception as e:
        logging.error(f"Error in Azure OpenAI response: {e}")
        # Return default empty job details in case of errors
        return JobDetails(
            company_name="",
            job_role="",
            ctc="",
            application_link=""
        )

# -------- Google Sheets Helper Functions -------- #
def connect_to_google_sheet(credentials_file: str):
    """Connect to Google Sheets API and return the sheet instance."""
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_file, scope)
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).sheet1
        logging.info(f"Connected to Google Sheets using credentials: {credentials_file}")
        return sheet
    except Exception as e:
        logging.error(f"Failed to connect to Google Sheets with {credentials_file}: {e}")
        raise e

def append_to_google_sheets(sheets, data: JobDetails):
    """Append extracted job details to all provided Google Sheets."""
    for sheet in sheets:
        try:
            sheet.append_row(
                [
                    data.company_name,
                    data.job_role,
                    data.ctc,
                    data.years_of_experience,
                    data.passout_year,
                    data.application_link,
                ]
            )
            logging.info(f"Appended data to Google Sheet: {sheet.title}")
        except Exception as e:
            logging.error(f"Failed to append data to Google Sheet: {sheet.title}: {e}")

# -------- Message Processing -------- #
def process_message(message_text: str, sheets):
    """Process the message: extract details and append them to Google Sheets."""
    logging.info(f"Processing message: {message_text}")
    job_details = extract_job_details(message_text)
    if any([job_details.company_name, job_details.job_role, job_details.ctc, job_details.application_link]):
        logging.info(f"Extracted job details: {job_details}")
        append_to_google_sheets(sheets, job_details)
    else:
        logging.info("No job details found in message.")

# -------- Telegram Event Handlers -------- #
async def handle_new_message(event, sheets):
    """Handle new message event and process the message."""
    message_text = event.raw_text
    logging.info(f"New message received: {message_text}")
    process_message(message_text, sheets)

# -------- Telegram Bot Workflow -------- #
async def main():
    """
    Main function to:
    - Fetch all messages delivered today from each channel
    - Listen for new messages
    - Append data to multiple Google Sheets
    """
    # Initialize Telegram client
    client_telegram = TelegramClient("Session", API_ID, API_HASH)

    # Start Telegram client
    await client_telegram.start()
    logging.info("Connected to Telegram!")

    # Connect to all Google Sheets
    sheets = []
    for credentials_file in CREDENTIALS_FILES:
        try:
            sheet = connect_to_google_sheet(credentials_file)
            sheets.append(sheet)
        except Exception as e:
            logging.error(f"Skipping Google Sheet for {credentials_file} due to errors.")

    if not sheets:
        logging.error("No Google Sheets available. Exiting.")
        return
    logging.info(f"Connected to {len(sheets)} Google Sheets.")

    # Get current day boundaries
    now = datetime.now(timezone.utc)  # Updated code
    start_of_day = datetime(now.year, now.month, now.day)
    logging.info(f"Fetching messages delivered since: {start_of_day}")

    # Get channel entities
    channel_entities = []
    for channel in CHANNELS:
        try:
            entity = await client_telegram.get_entity(channel.strip())
            channel_entities.append(entity)
            logging.info(f"Added channel: {entity.title}")
        except Exception as e:
            logging.error(f"Failed to get entity for {channel}: {e}")

    # Fetch and process today's messages
    for entity in channel_entities:
        try:
            async for msg in client_telegram.iter_messages(
                entity,
                offset_date=start_of_day,
                reverse=True,
            ):
                if msg.message:
                    process_message(msg.message, sheets)
        except Exception as e:
            logging.error(f"Error fetching messages from {entity.title}: {e}")

    # Listen for new messages
    @client_telegram.on(events.NewMessage(chats=channel_entities))
    async def new_message_listener(event):
        await handle_new_message(event, sheets)

    logging.info("Listening for new messages...")
    await client_telegram.run_until_disconnected()

# -------- Run the Program -------- #
if __name__ == "__main__":
    try:
        asyncio.run(main())
        print(f"Credentials files: {type(CREDENTIALS_FILES)}")

    except KeyboardInterrupt:
        logging.info("Program terminated by user.")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")

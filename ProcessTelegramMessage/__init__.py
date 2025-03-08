import os
import logging
import json

from azure.storage.blob import BlobServiceClient
from oauth2client.service_account import ServiceAccountCredentials
import azure.functions as func
import gspread

def load_credentials_from_blob():
    """
    Load the credentials.json file from Azure Blob Storage and parse it.
    """
    try:
        # Read the connection string from environment variables
        storage_connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not storage_connection_string:
            raise ValueError("AZURE_STORAGE_CONNECTION_STRING is not set in application settings.")

        # Define the container and blob name
        container_name = "secrets"  # Change if you used a different container name
        blob_name = "credentials.json"

        # Connect to Blob Storage
        blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(blob_name)

        # Download the blob content as bytes and parse it
        logging.info("Downloading credentials.json from Blob Storage...")
        credentials_blob = blob_client.download_blob().readall()
        credentials_data = json.loads(credentials_blob)  # Convert bytes to dictionary
        return credentials_data

    except Exception as e:
        logging.error(f"Error loading credentials from Blob Storage: {e}")
        raise e


def connect_to_google_sheet():
    """
    Connect to Google Sheets using the credentials loaded from Blob Storage.
    """
    try:
        # Load credentials dynamically from Blob Storage
        credentials_data = load_credentials_from_blob()

        # Define the required Google Sheets scopes
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]

        # Authenticate with Google Sheets API
        creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_data, scope)
        client = gspread.authorize(creds)
        sheet = client.open(os.getenv("GOOGLE_SHEET_NAME")).sheet1  # Modify if necessary
        return sheet

    except Exception as e:
        logging.error(f"Error connecting to Google Sheets: {e}")
        raise e


def main(req: func.HttpRequest) -> func.HttpResponse:
    """
    Azure Function entry point to process the HTTP request and work with Google Sheets.
    """
    logging.info("Processing HTTP request to extract job details.")
    try:
        # Extract the message from the HTTP request
        message = req.params.get("message")
        if not message:
            return func.HttpResponse("Missing 'message' parameter.", status_code=400)

        # Mocked: Your logic to process the message (e.g., parse job details)
        job_details = {
            "company_name": "Sample Company",
            "job_role": "Software Engineer",
            "ctc": "10-15 LPA",
            "application_link": "http://apply.samplecompany.com"
        }

        # Connect to Google Sheets and append the job details
        sheet = connect_to_google_sheet()
        sheet.append_row([job_details["company_name"], job_details["job_role"], job_details["ctc"], job_details["application_link"]])

        logging.info(f"Job details appended to Google Sheets: {job_details}")
        return func.HttpResponse(f"Job details appended: {json.dumps(job_details)}", status_code=200)

    except Exception as e:
        logging.error(f"Error occurred: {e}")
        return func.HttpResponse(f"Error: {str(e)}", status_code=500)
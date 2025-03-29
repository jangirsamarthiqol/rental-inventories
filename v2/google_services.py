import streamlit as st
import gspread
from google.oauth2.service_account import Credentials as GSpreadCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from config import (
    GSPREAD_PROJECT_ID,
    GSPREAD_PRIVATE_KEY_ID,
    GSPREAD_PRIVATE_KEY,
    GSPREAD_CLIENT_EMAIL,
    GSPREAD_CLIENT_ID,
    GOOGLE_SHEET_ID,
    SHEET_NAME,
    GOOGLE_DRIVE_PROJECT_ID,
    GOOGLE_DRIVE_PRIVATE_KEY_ID,
    GOOGLE_DRIVE_PRIVATE_KEY,
    GOOGLE_DRIVE_CLIENT_EMAIL,
    GOOGLE_DRIVE_CLIENT_ID,
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# --- Google Sheets Setup ---
gspread_sa_info = {
    "type": "service_account",
    "project_id": GSPREAD_PROJECT_ID,
    "private_key_id": GSPREAD_PRIVATE_KEY_ID,
    "private_key": GSPREAD_PRIVATE_KEY,
    "client_email": GSPREAD_CLIENT_EMAIL,
    "client_id": GSPREAD_CLIENT_ID,
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{GSPREAD_CLIENT_EMAIL}",
}
gs_creds = GSpreadCredentials.from_service_account_info(gspread_sa_info, scopes=SCOPES)
gc = gspread.authorize(gs_creds)
sheet = gc.open_by_key(GOOGLE_SHEET_ID).worksheet(SHEET_NAME)

def ensure_sheet_headers():
    expected_header = [
        "Property Id", "Property Name", "Property Type", "Plot Size", "SBUA",
        "Rent Per Month in Lakhs", "Maintenance Charges", "Security Deposit", "Configuration",
        "Facing", "Furnishing Status", "Micromarket", "Area", "Available From", "Floor Number",
        "Lease Period", "Lock-in Period", "Amenities", "Extra details", "Restrictions",
        "Veg/Non Veg", "Pet friendly", "Drive Link", "mapLocation", "Coordinates",
        "Date of inventory added", "Date of Status Last Checked", "Agent Id", "Agent Number", "Agent Name", "Exact Floor"
    ]
    current_header = sheet.row_values(1)
    if current_header != expected_header:
        header_range = "A1:AE1"  # Adjust range as needed
        sheet.update(header_range, [expected_header])

def append_to_google_sheet(row: list):
    try:
        # Append the new row to the next available row at the bottom
        sheet.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        st.error(f"Sheet error: {e}")





# --- Google Drive Setup ---
from google.oauth2.service_account import Credentials as DriveCredentials

drive_sa_info = {
    "type": "service_account",
    "project_id": GOOGLE_DRIVE_PROJECT_ID,
    "private_key_id": GOOGLE_DRIVE_PRIVATE_KEY_ID,
    "private_key": GOOGLE_DRIVE_PRIVATE_KEY,
    "client_email": GOOGLE_DRIVE_CLIENT_EMAIL,
    "client_id": GOOGLE_DRIVE_CLIENT_ID,
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{GOOGLE_DRIVE_CLIENT_EMAIL}",
}
drive_creds = GSpreadCredentials.from_service_account_info(drive_sa_info, scopes=SCOPES)
drive_service = build("drive", "v3", credentials=drive_creds)

def create_drive_folder(folder_name: str, parent_id: str) -> str:
    query = f"'{parent_id}' in parents and name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    files = drive_service.files().list(q=query, fields="files(id)").execute().get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    try:
        folder = drive_service.files().create(body=meta, fields="id").execute()
        return folder.get("id")
    except Exception as e:
        st.error(f"Drive folder error ({folder_name}): {e}")
        return ""

def upload_media_to_drive(file_obj, filename: str, parent_folder_id: str):
    file_obj.seek(0)
    meta = {"name": filename, "parents": [parent_folder_id]}
    media = MediaIoBaseUpload(file_obj, mimetype="application/octet-stream", resumable=True)
    try:
        res = drive_service.files().create(body=meta, media_body=media, fields="id").execute()
        file_id = res.get("id")
        drive_service.permissions().create(
            fileId=file_id, body={"type": "anyone", "role": "reader"}
        ).execute()
        return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"
    except Exception as e:
        st.error(f"Drive upload error ({filename}): {e}")
        return None

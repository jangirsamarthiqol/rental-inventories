import os
from dotenv import load_dotenv

load_dotenv()

# Firebase Configuration
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIREBASE_PRIVATE_KEY_ID = os.getenv("FIREBASE_PRIVATE_KEY_ID")
FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY").replace('\\n', '\n')
FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL")
FIREBASE_CLIENT_ID = os.getenv("FIREBASE_CLIENT_ID")
FIREBASE_STORAGE_BUCKET = os.getenv("FIREBASE_STORAGE_BUCKET")  # e.g., your-bucket.appspot.com

# Google Sheets Configuration (Hardcoded for now)
GOOGLE_SHEET_ID = "14rr4IiEfMVQ_GlzZ-90EkeVNuo4uk_HjjGf8104a3JI"
SHEET_NAME = "Rental Inventories"

# Google Sheets Credentials
GSPREAD_PROJECT_ID = os.getenv("GSPREAD_PROJECT_ID")
GSPREAD_PRIVATE_KEY_ID = os.getenv("GSPREAD_PRIVATE_KEY_ID")
GSPREAD_PRIVATE_KEY = os.getenv("GSPREAD_PRIVATE_KEY").replace('\\n', '\n')
GSPREAD_CLIENT_EMAIL = os.getenv("GSPREAD_CLIENT_EMAIL")
GSPREAD_CLIENT_ID = os.getenv("GSPREAD_CLIENT_ID")

# Google Drive Credentials
GOOGLE_DRIVE_PROJECT_ID = os.getenv("GOOGLE_DRIVE_PROJECT_ID")
GOOGLE_DRIVE_PRIVATE_KEY_ID = os.getenv("GOOGLE_DRIVE_PRIVATE_KEY_ID")
GOOGLE_DRIVE_PRIVATE_KEY = os.getenv("GOOGLE_DRIVE_PRIVATE_KEY").replace('\\n', '\n')
GOOGLE_DRIVE_CLIENT_EMAIL = os.getenv("GOOGLE_DRIVE_CLIENT_EMAIL")
GOOGLE_DRIVE_CLIENT_ID = os.getenv("GOOGLE_DRIVE_CLIENT_ID")

# Other Configurations
PARENT_FOLDER_ID = os.getenv("PARENT_FOLDER_ID")  # The parent folder ID in Drive

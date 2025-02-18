import os
import datetime
from io import BytesIO
import streamlit as st
from dotenv import load_dotenv

# Firebase Admin & Firestore
import firebase_admin
from firebase_admin import credentials, firestore, storage

# Google Sheets and Drive
import gspread
from google.oauth2.service_account import Credentials as GSpreadCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

# Google Cloud Storage (for Firebase Storage)
from google.cloud import storage as gcs

# Import area data
from area_data import areasData, all_micromarkets, find_area

# -------------------------------------
# Load Environment Variables
# -------------------------------------
load_dotenv()

# --- Firebase Credentials ---
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIREBASE_PRIVATE_KEY_ID = os.getenv("FIREBASE_PRIVATE_KEY_ID")
FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY").replace('\\n', '\n')
FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL")
FIREBASE_CLIENT_ID = os.getenv("FIREBASE_CLIENT_ID")
FIREBASE_STORAGE_BUCKET = os.getenv("FIREBASE_STORAGE_BUCKET")  # e.g., acn-resale-inventories-dde03.appspot.com

# --- Google Sheets Credentials ---
GSPREAD_PROJECT_ID = os.getenv("GSPREAD_PROJECT_ID")
GSPREAD_PRIVATE_KEY_ID = os.getenv("GSPREAD_PRIVATE_KEY_ID")
GSPREAD_PRIVATE_KEY = os.getenv("GSPREAD_PRIVATE_KEY").replace('\\n', '\n')
GSPREAD_CLIENT_EMAIL = os.getenv("GSPREAD_CLIENT_EMAIL")
GSPREAD_CLIENT_ID = os.getenv("GSPREAD_CLIENT_ID")
GSPREAD_SHEET_ID = os.getenv("GSPREAD_SHEET_ID")

# --- Google Drive Credentials ---
GOOGLE_DRIVE_PROJECT_ID = os.getenv("GOOGLE_DRIVE_PROJECT_ID")
GOOGLE_DRIVE_PRIVATE_KEY_ID = os.getenv("GOOGLE_DRIVE_PRIVATE_KEY_ID")
GOOGLE_DRIVE_PRIVATE_KEY = os.getenv("GOOGLE_DRIVE_PRIVATE_KEY").replace('\\n', '\n')
GOOGLE_DRIVE_CLIENT_EMAIL = os.getenv("GOOGLE_DRIVE_CLIENT_EMAIL")
GOOGLE_DRIVE_CLIENT_ID = os.getenv("GOOGLE_DRIVE_CLIENT_ID")

# --- Other Configurations ---
PARENT_FOLDER_ID = os.getenv("PARENT_FOLDER_ID")  # Only the folder ID

# -------------------------------------
# Construct Service Account Dictionaries
# -------------------------------------
firebase_sa_info = {
    "type": "service_account",
    "project_id": FIREBASE_PROJECT_ID,
    "private_key_id": FIREBASE_PRIVATE_KEY_ID,
    "private_key": FIREBASE_PRIVATE_KEY,
    "client_email": FIREBASE_CLIENT_EMAIL,
    "client_id": FIREBASE_CLIENT_ID,
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{FIREBASE_CLIENT_EMAIL}"
}

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
    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{GSPREAD_CLIENT_EMAIL}"
}

google_drive_sa_info = {
    "type": "service_account",
    "project_id": GOOGLE_DRIVE_PROJECT_ID,
    "private_key_id": GOOGLE_DRIVE_PRIVATE_KEY_ID,
    "private_key": GOOGLE_DRIVE_PRIVATE_KEY,
    "client_email": GOOGLE_DRIVE_CLIENT_EMAIL,
    "client_id": GOOGLE_DRIVE_CLIENT_ID,
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{GOOGLE_DRIVE_CLIENT_EMAIL}"
}

# -------------------------------------
# Setup Firebase Admin, Firestore, and Storage
# -------------------------------------
if not firebase_admin._apps:
    cred = credentials.Certificate(firebase_sa_info)
    firebase_admin.initialize_app(cred, {"storageBucket": FIREBASE_STORAGE_BUCKET})

db = firestore.client()
bucket = storage.bucket()
gcs_client = gcs.Client.from_service_account_info(firebase_sa_info)

# -------------------------------------
# Setup Google Sheets
# -------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
gs_creds = GSpreadCredentials.from_service_account_info(gspread_sa_info, scopes=SCOPES)
gc = gspread.authorize(gs_creds)
sheet = gc.open_by_key(GSPREAD_SHEET_ID).worksheet("Rental Inventories")

def ensure_sheet_headers():
    header = [
        "Property Id", "Property Name", "Property Type", "Plot Size", "SBUA",
        "Rent Per Month in Lakhs", "Maintenance Charges", "Security Deposit", "Configuration",
        "Facing", "Furnishing Status", "Micromarket", "Area", "Available From", "Floor Number",
        "Lease Period", "Lock-in Period", "Amenities", "Extra details", "Restrictions",
        "Veg/Non Veg", "Pet friendly", "Drive Link", "mapLocation", "Coordinates",
        "Date of inventory added", "Date of Status Last Checked","Agent Id", "Agent Number", "Agent Name", "Exact Floor"
    ]
    if sheet.row_values(1) != header:
        sheet.clear()
        sheet.append_row(header, value_input_option="USER_ENTERED")

ensure_sheet_headers()

# -------------------------------------
# Setup Google Drive API
# -------------------------------------
drive_creds = GSpreadCredentials.from_service_account_info(google_drive_sa_info, scopes=SCOPES)
drive_service = build("drive", "v3", credentials=drive_creds)

def parse_coordinates(coord_str: str):
    try:
        parts = coord_str.split(",")
        if len(parts) != 2:
            return None
        return {"lat": float(parts[0].strip()), "lng": float(parts[1].strip())}
    except:
        return None

def standardize_phone_number(num: str) -> str:
    num = num.strip().replace(" ", "")
    if not num.startswith("+91"):
        if num.startswith("91"):
            num = "+" + num
        else:
            num = "+91" + num
    return num

def fetch_agent_details(agent_number: str):
    agent_number = standardize_phone_number(agent_number)
    docs = db.collection("agents").where("phonenumber", "==", agent_number).limit(1).stream()
    for doc in docs:
        data = doc.to_dict()
        return data.get("cpId"), data.get("name")
    return None, None

def generate_property_id():
    docs = list(db.collection("rental-inventories").stream())
    return f"RN{len(docs)+1:03d}"

def upload_media_to_firebase(property_id: str, file_obj: BytesIO, folder: str, filename: str) -> str:
    path = f"rental-media-files/{property_id}/{folder}/{filename}"
    blob = bucket.blob(path)
    try:
        blob.upload_from_file(file_obj, content_type="application/octet-stream")
        blob.make_public()
        return blob.public_url
    except Exception as e:
        st.error(f"Firebase error ({filename}): {e}")
        return ""

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

def upload_media_to_drive(file_obj: BytesIO, filename: str, parent_folder_id: str):
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

def append_to_google_sheet(row: list):
    try:
        sheet.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        st.error(f"Sheet error: {e}")

def compute_floor_range(exact_floor):
    try:
        floor = float(exact_floor)
    except:
        return "NA"
    if floor == 0:
        return "Ground Floor"
    elif floor <= 5:
        return "Lower Floor (1-5)"
    elif floor <= 10:
        return "Middle Floor (6-10)"
    elif floor <= 20:
        return "Higher Floor (10+)"
    else:
        return "Higher Floor (20+)"

def strip_plus91(num: str) -> str:
    num = num.strip()
    if num.startswith("+91"):
        return num[3:]
    return num

# -------------------------------------
# Clear Form Callback
# -------------------------------------
def clear_form_callback():
    keys_to_clear = [
        "agent_number", "property_type", "property_name", "plot_size", "SBUA",
        "rent_per_month", "maintenance_charges", "security_deposit", "configuration",
        "facing", "furnishing_status", "micromarket", "available_from", "exact_floor",
        "floor_range", "lease_period", "lock_in_period", "amenities", "extra_details",
        "restrictions", "veg_non_veg", "pet_friendly", "mapLocation", "coordinates"
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            st.session_state[key] = ""
    try:
        st.experimental_rerun()
    except Exception as e:
        st.info("Form cleared! Please refresh the page manually.")

# -------------------------------------
# Streamlit App Layout
# -------------------------------------
st.title("Rental Inventory Entry")

st.header("Agent Details")
agent_number = st.text_input("Agent Number (Phone Number)")
if st.button("Fetch Agent Details"):
    a_id, a_name = fetch_agent_details(agent_number)
    if a_id:
        st.success(f"Agent Found: {a_name} (ID: {a_id})")
    else:
        st.error("Agent not found.")

# Place property type outside the form for dynamic behavior
if "property_type" not in st.session_state:
    st.session_state.property_type = ""
st.session_state.property_type = st.selectbox("Property Type", ["", "Apartment", "Studio", "Duplex", "Triplex", "Villa", "Office Space", "Retail Space", "Commercial Property"])

with st.form(key="rental_form"):
    st.header("Property Details")
    property_name = st.text_input("Property Name")
    property_type = st.session_state.property_type
    st.write("Selected property type:", property_type)
    plot_size = st.text_input("Plot Size")
    SBUA = st.text_input("SBUA")
    rent_per_month = st.text_input("Rent Per Month in Lakhs")
    maintenance_charges = st.selectbox("Maintenance Charges", ["", "Included", "Not included"])
    security_deposit = st.text_input("Security Deposit")
    
    if property_type.strip().lower() in ["apartment", "duplex", "triplex", "villa"]:
        configuration = st.selectbox("Configuration", ["", "1 BHK", "2 BHK", "2.5 BHK", "3 BHK", "3.5 BHK", "4 BHK", "4.5 BHK", "5 BHK", "5.5 BHK", "6 BHK", "6.5 BHK", "7 BHK", "7.5 BHK", "8 BHK", "8.5 BHK", "9 BHK", "9.5 BHK", "10 BHK"])
    elif property_type.strip().lower() == "studio":
        configuration = "Studio"
        st.info("Configuration auto-set as 'Studio'")
    else:
        configuration = st.text_input("Configuration")
        
    facing = st.selectbox("Facing", ["", "East", "North", "West", "South", "North-East", "North-West", "South-East", "South-West"])
    furnishing_status = st.selectbox("Furnishing Status", ["", "Fully Furnished", "Semi Furnished", "Warm Shell", "Bare Shell", "Plug & Play"])
    
    micromarket_selected = st.multiselect("Select Micromarket", options=all_micromarkets, help="Search and select one micromarket")
    micromarket = micromarket_selected[0] if micromarket_selected else ""
    area = find_area(micromarket) if micromarket else ""
    
    ready_to_move = st.checkbox("Ready to Move")
    if ready_to_move:
        available_from_val = "Ready-to-move"
    else:
        available_from_date = st.date_input("Available From", datetime.date.today())
        available_from_val = available_from_date.strftime("%Y-%m-%d")
    
    exact_floor = st.text_input("Exact Floor (numeric, optional)")
    if exact_floor.strip():
        computed_floor_range = compute_floor_range(exact_floor)
        st.write("Computed Floor Range:", computed_floor_range)
        floor_range = computed_floor_range
    else:
        floor_range = st.selectbox("Floor Range", ["", "NA", "Ground Floor", "Lower Floor (1-5)", "Middle Floor (6-10)", "Higher Floor (10+)", "Higher Floor (20+)", "Top Floor"])
    
    lease_period = st.text_input("Lease Period")
    lock_in_period = st.text_input("Lock-in Period")
    amenities = st.text_input("Amenities")
    extra_details = st.text_area("Extra details")
    restrictions = st.text_area("Restrictions")
    veg_non_veg = st.selectbox("Veg/Non Veg", ["", "Veg Only", "Both"])
    pet_friendly = st.text_input("Pet friendly")
    mapLocation = st.text_input("mapLocation")
    coordinates = st.text_input("Coordinates (lat, lng)")
    
    st.header("Media Uploads")
    photos_files = st.file_uploader("Upload Photos", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
    videos_files = st.file_uploader("Upload Videos", type=["mp4", "mov", "avi"], accept_multiple_files=True)
    documents_files = st.file_uploader("Upload Documents", type=["pdf", "doc", "docx"], accept_multiple_files=True)
    
    st.header("Manual Agent Override (if needed)")
    agent_id_manual = st.text_input("Agent ID (if not auto‑filled)", value="")
    agent_name_manual = st.text_input("Agent Name (if not auto‑filled)", value="")
    
    submitted = st.form_submit_button("Submit Inventory")
    
if submitted:
    property_id = generate_property_id()
    st.write("Generated Property ID:", property_id)
    
    prop_drive_folder_id = create_drive_folder(property_id, PARENT_FOLDER_ID)
    drive_main_link = f"https://drive.google.com/drive/folders/{prop_drive_folder_id}" if prop_drive_folder_id else ""
    st.write("Drive Property Folder Link:", drive_main_link)
    
    if agent_id_manual.strip() and agent_name_manual.strip():
        agent_id_final = agent_id_manual.strip()
        agent_name_final = agent_name_manual.strip()
    else:
        agent_id_final, agent_name_final = fetch_agent_details(agent_number)
        agent_id_final = agent_id_final or ""
        agent_name_final = agent_name_final or ""
    
    now = datetime.datetime.now()
    timestamp = int(now.timestamp())
    geoloc = parse_coordinates(coordinates)
    
    photos_urls, videos_urls, documents_urls, drive_file_links = [], [], [], []
    
    for photo in photos_files:
        filename = photo.name
        file_bytes = BytesIO(photo.read())
        fb_url = upload_media_to_firebase(property_id, file_bytes, "photos", filename)
        if fb_url:
            photos_urls.append(fb_url)
        file_bytes.seek(0)
        dlink = upload_media_to_drive(file_bytes, filename, prop_drive_folder_id)
        if dlink:
            drive_file_links.append(dlink)
    
    for video in videos_files:
        filename = video.name
        file_bytes = BytesIO(video.read())
        fb_url = upload_media_to_firebase(property_id, file_bytes, "videos", filename)
        if fb_url:
            videos_urls.append(fb_url)
        file_bytes.seek(0)
        dlink = upload_media_to_drive(file_bytes, filename, prop_drive_folder_id)
        if dlink:
            drive_file_links.append(dlink)
    
    for doc in documents_files:
        filename = doc.name
        file_bytes = BytesIO(doc.read())
        fb_url = upload_media_to_firebase(property_id, file_bytes, "documents", filename)
        if fb_url:
            documents_urls.append(fb_url)
        file_bytes.seek(0)
        dlink = upload_media_to_drive(file_bytes, filename, prop_drive_folder_id)
        if dlink:
            drive_file_links.append(dlink)
    
    property_data = {
        "propertyId": property_id,
        "propertyName": property_name,
        "propertyType": property_type,
        "plotSize": plot_size,
        "SBUA": SBUA,
        "rentPerMonthInLakhs": rent_per_month,
        "maintenanceCharges": maintenance_charges,
        "securityDeposit": security_deposit,
        "configuration": configuration,
        "facing": facing,
        "furnishingStatus": furnishing_status,
        "micromarket": micromarket,
        "area": area,
        "availableFrom": available_from_val,
        "floorNumber": floor_range,
        "exactFloor": exact_floor,
        "leasePeriod": lease_period,
        "lockInPeriod": lock_in_period,
        "amenities": amenities,
        "extraDetails": extra_details,
        "restrictions": restrictions,
        "vegNonVeg": veg_non_veg,
        "petFriendly": pet_friendly,
        "mapLocation": mapLocation,
        "coordinates": coordinates,
        "_geoloc": geoloc,
        "dateOfInventoryAdded": timestamp,
        "dateOfStatusLastChecked": timestamp,
        "agentId": agent_id_final,
        "agentNumber": standardize_phone_number(agent_number),
        "agentName": agent_name_final,
        "driveLink": drive_main_link,
        "photos": photos_urls,
        "videos": videos_urls,
        "documents": documents_urls,
        "driveFileLinks": drive_file_links
    }
    
    try:
        db.collection("rental-inventories").document(property_id).set(property_data)
        st.success("Property saved to Firebase!")
    except Exception as e:
        st.error(f"Error saving to Firebase: {e}")
    
    sheet_agent_number = standardize_phone_number(agent_number)[3:]
    sheet_row = [
        property_id,
        agent_id_final,
        property_name,
        property_type,
        plot_size,
        SBUA,
        rent_per_month,
        maintenance_charges,
        security_deposit,
        configuration,
        facing,
        furnishing_status,
        micromarket,
        area,
        available_from_val,
        floor_range,
        lease_period,
        lock_in_period,
        amenities,
        extra_details,
        restrictions,
        veg_non_veg,
        pet_friendly,
        drive_main_link,
        mapLocation,
        coordinates,
        now.strftime("%Y-%m-%d %H:%M:%S"),
        now.strftime("%Y-%m-%d %H:%M:%S"),
        agent_id_final,
        sheet_agent_number,
        agent_name_final,
        exact_floor
    ]
    
    try:
        append_to_google_sheet(sheet_row)
        st.success("Property details appended to Google Sheet!")
        st.success("Submission Successful!")
    except Exception as e:
        st.error(f"Error appending to Google Sheet: {e}")

# # Clear button to reset the form (this clears session state and refreshes the app)
# if st.button("Clear Form", key="clear_btn"):
#     clear_form_callback()

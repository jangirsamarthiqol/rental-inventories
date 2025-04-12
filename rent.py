import os
import datetime
import logging
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, storage
from google.cloud import storage as gcs
import gspread
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from dotenv import load_dotenv

# Set page configuration first
st.set_page_config(page_title="Rental Inventory", page_icon="📦")

# Import area data (assumed to be available)
from area_data import areasData, all_micromarkets, find_area

# -------------------------------------
# CONFIGURATION & ENVIRONMENT
# -------------------------------------
load_dotenv()

# --- Firebase Credentials ---
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY").replace('\\n', '\n')
FIREBASE_PRIVATE_KEY_ID = os.getenv("FIREBASE_PRIVATE_KEY_ID")  # if needed
FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL")
FIREBASE_CLIENT_ID = os.getenv("FIREBASE_CLIENT_ID")
FIREBASE_STORAGE_BUCKET = os.getenv("FIREBASE_STORAGE_BUCKET")

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
    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{FIREBASE_CLIENT_EMAIL}",
}

# --- Google Sheets Credentials ---
GSPREAD_PROJECT_ID = os.getenv("GSPREAD_PROJECT_ID")
GSPREAD_PRIVATE_KEY_ID = os.getenv("GSPREAD_PRIVATE_KEY_ID")
GSPREAD_PRIVATE_KEY = os.getenv("GSPREAD_PRIVATE_KEY").replace('\\n', '\n')
GSPREAD_CLIENT_EMAIL = os.getenv("GSPREAD_CLIENT_EMAIL")
GSPREAD_CLIENT_ID = os.getenv("GSPREAD_CLIENT_ID")
GSPREAD_SHEET_ID = os.getenv("GSPREAD_SHEET_ID")  # set this in your .env

# --- Google Drive Credentials ---
GOOGLE_DRIVE_PROJECT_ID = os.getenv("GOOGLE_DRIVE_PROJECT_ID")
GOOGLE_DRIVE_PRIVATE_KEY_ID = os.getenv("GOOGLE_DRIVE_PRIVATE_KEY_ID")
GOOGLE_DRIVE_PRIVATE_KEY = os.getenv("GOOGLE_DRIVE_PRIVATE_KEY").replace('\\n', '\n')
GOOGLE_DRIVE_CLIENT_EMAIL = os.getenv("GOOGLE_DRIVE_CLIENT_EMAIL")
GOOGLE_DRIVE_CLIENT_ID = os.getenv("GOOGLE_DRIVE_CLIENT_ID")

# --- Other Configurations ---
PARENT_FOLDER_ID = os.getenv("PARENT_FOLDER_ID")  # Parent folder ID in Google Drive

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------------
# CACHED INITIALIZATIONS (using st.cache_resource)
# -------------------------------------
@st.cache_resource
def init_firebase():
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate(firebase_sa_info)
            firebase_admin.initialize_app(cred, {"storageBucket": FIREBASE_STORAGE_BUCKET})
            logger.info("Firebase initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing Firebase: {e}")
            raise
    db_inst = firestore.client()
    bucket_inst = storage.bucket()
    gcs_client_inst = gcs.Client.from_service_account_info(firebase_sa_info)
    return db_inst, bucket_inst, gcs_client_inst

db, bucket, gcs_client = init_firebase()

@st.cache_resource
def init_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    gs_creds = ServiceAccountCredentials.from_service_account_info({
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
    }, scopes=scopes)
    client = gspread.authorize(gs_creds)
    return client

gc = init_gspread_client()
sheet = gc.open_by_key(GSPREAD_SHEET_ID).worksheet("Rental Inventories")

def ensure_sheet_headers():
    # Updated header list with "Inventory Status" inserted after "Floor Number"
    expected_header = [
        "Property Id", "Property Name", "Property Type", "Plot Size", "SBUA",
        "Rent Per Month in Lakhs", "Commission Type", "Maintenance Charges", "Security Deposit", "Configuration",
        "Facing", "Furnishing Status", "Micromarket", "Area", "Available From", "Floor Number",
        "Inventory Status",  # New header column (no input required)
        "Lease Period", "Lock-in Period", "Amenities", "Extra details", "Restrictions",
        "Veg/Non Veg", "Pet friendly", "Drive Link", "mapLocation", "Coordinates",
        "Date of inventory added", "Date of Status Last Checked", "Agent Id", "Agent Number", "Agent Name", "Exact Floor"
    ]
    current_header = sheet.row_values(1)
    if current_header != expected_header:
        header_range = "A1:AG1"
        sheet.update(header_range, [expected_header])

ensure_sheet_headers()

def append_to_google_sheet(row: list):
    try:
        sheet.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        st.error(f"Sheet error: {e}")

@st.cache_resource
def init_drive_service():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    drive_creds = ServiceAccountCredentials.from_service_account_info({
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
    }, scopes=scopes)
    service = build("drive", "v3", credentials=drive_creds)
    return service

drive_service = init_drive_service()

# -------------------------------------
# HELPER FUNCTIONS
# -------------------------------------
def parse_coordinates(coord_str: str):
    try:
        parts = coord_str.split(",")
        if len(parts) != 2:
            return None
        return {"lat": float(parts[0].strip()), "lng": float(parts[1].strip())}
    except Exception:
        return None

def standardize_phone_number(num: str) -> str:
    num = num.strip().replace(" ", "")
    if not num.startswith("+91"):
        if num.startswith("91"):
            num = "+" + num
        else:
            num = "+91" + num
    return num

def strip_plus91(num: str) -> str:
    num = num.strip()
    return num[3:] if num.startswith("+91") else num

def fetch_agent_details(agent_number: str):
    agent_number = standardize_phone_number(agent_number)
    docs = db.collection("agents").where("phonenumber", "==", agent_number).limit(1).stream()
    for doc in docs:
        data = doc.to_dict()
        return data.get("cpId"), data.get("name")
    return None, None

def generate_property_id():
    docs = list(db.collection("rental-inventories").stream())
    max_id = 0
    for doc in docs:
        pid = doc.get("propertyId")
        if pid and pid.startswith("RN"):
            try:
                num = int(pid.replace("RN", ""))
                max_id = max(max_id, num)
            except Exception:
                pass
    return f"RN{max_id + 1:03d}"

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
    query = (
        f"'{parent_id}' in parents and name='{folder_name}' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    try:
        files = drive_service.files().list(q=query, fields="files(id)").execute().get("files", [])
    except Exception as e:
        st.error(f"Error querying drive folders: {e}")
        return ""
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

# --- Parallel file uploads using ThreadPoolExecutor ---
def upload_single_file(file, property_id, folder, drive_folder_id):
    filename = file.name
    file_bytes = BytesIO(file.read())
    fb_url = upload_media_to_firebase(property_id, file_bytes, folder, filename)
    dlink = None
    if drive_folder_id:
        file_bytes.seek(0)
        dlink = upload_media_to_drive(file_bytes, filename, drive_folder_id)
    return fb_url, dlink

def process_files_concurrent(files, property_id, folder, drive_folder_id):
    firebase_urls = []
    drive_links = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(upload_single_file, file, property_id, folder, drive_folder_id) for file in files]
        for future in futures:
            fb_url, dlink = future.result()
            if fb_url:
                firebase_urls.append(fb_url)
            if dlink:
                drive_links.append(dlink)
    return firebase_urls, drive_links

def compute_floor_range(exact_floor):
    try:
        floor = float(exact_floor)
    except Exception:
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

def clear_form_callback():
    keys_to_clear = [
        "agent_number", "property_type", "property_name", "plot_size", "SBUA",
        "rent_per_month", "commission_type", "maintenance_charges", "security_deposit", "configuration",
        "facing", "furnishing_status", "micromarket", "available_from", "exact_floor",
        "floor_range", "lease_period", "lock_in_period", "amenities", "extra_details",
        "restrictions", "veg_non_veg", "pet_friendly", "mapLocation", "coordinates"
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    st.experimental_rerun()

# -------------------------------------
# STREAMLIT APPLICATION (Inventory Submission UI)
# -------------------------------------
def main():
    st.title("Rental Inventory Entry")
    
    # --- Agent Details ---
    st.header("Agent Details")
    agent_number = st.text_input("Agent Number (Phone Number)", key="agent_number").strip()
    if st.button("Fetch Agent Details", key="fetch_agent_details"):
        a_id, a_name = fetch_agent_details(agent_number)
        if a_id:
            st.success(f"Agent Found: {a_name} (ID: {a_id})")
        else:
            st.error("Agent not found.")
    
    # Initialize session_state for property_type if not already set
    if "property_type" not in st.session_state:
        st.session_state["property_type"] = ""
    
    # Capture property type (do not modify session_state after widget creation)
    property_type = st.selectbox("Property Type", 
        ["", "Apartment", "Studio", "Duplex", "Triplex", "Villa", "Office Space", "Retail Space", "Commercial Property", "Villament","Plot"],
        key="property_type")
    
    with st.form(key="rental_form"):
        st.header("Property Details")
        property_name = st.text_input("Property Name", key="property_name").strip().replace("'", "")
        st.write("Selected property type:", property_type)
        plot_size = st.text_input("Plot Size", key="plot_size").strip().replace("'", "")
        SBUA = st.text_input("SBUA", key="SBUA").strip().replace("'", "")
        rent_per_month = st.text_input("Rent Per Month in Lakhs", key="rent_per_month").strip().replace("'", "")
        # Commission Type Dropdown with options
        commission_type = st.selectbox("Commission Type", ["NA","Side by Side", "Commission Sharing"], key="commission_type")
        maintenance_charges = st.selectbox("Maintenance Charges", ["", "Included", "Not included"], key="maintenance_charges")
        security_deposit = st.text_input("Security Deposit", key="security_deposit").strip().replace("'", "")
        
        # Configuration based on property type
        if property_type.strip().lower() in ["apartment", "duplex", "triplex", "villa"]:
            configuration = st.selectbox("Configuration", 
                                         ["", "1 BHK", "2 BHK", "2.5 BHK", "3 BHK", "3.5 BHK", "4 BHK", 
                                          "4.5 BHK", "5 BHK", "5.5 BHK", "6 BHK", "6.5 BHK", "7 BHK", 
                                          "7.5 BHK", "8 BHK", "8.5 BHK", "9 BHK", "9.5 BHK", "10 BHK"], 
                                         key="configuration")
        elif property_type.strip().lower() == "studio":
            configuration = "Studio"
            st.info("Configuration auto-set as 'Studio'")
        else:
            configuration = st.text_input("Configuration", key="configuration").strip().replace("'", "")
            
        facing = st.selectbox("Facing", ["", "East", "North", "West", "South", "North-East", "North-West", "South-East", "South-West"], key="facing")
        furnishing_status = st.selectbox("Furnishing Status", 
                                         ["", "Fully Furnished", "Semi Furnished", "Warm Shell", "Bare Shell", "Plug & Play"], 
                                         key="furnishing_status")
        
        micromarket_selected = st.multiselect("Select Micromarket", options=all_micromarkets, help="Search and select one micromarket", key="micromarket")
        micromarket = micromarket_selected[0] if micromarket_selected else ""
        area = find_area(micromarket) if micromarket else ""
        
        ready_to_move = st.checkbox("Ready to Move", key="ready_to_move")
        if ready_to_move:
            available_from_val = "Ready-to-move"
        else:
            available_from_date = st.date_input("Available From", datetime.date.today(), key="available_from")
            available_from_val = available_from_date.strftime("%Y-%m-%d")
        
        exact_floor = st.text_input("Exact Floor (numeric, optional)", key="exact_floor").strip().replace("'", "")
        if exact_floor:
            computed_floor_range = compute_floor_range(exact_floor)
            st.write("Computed Floor Range:", computed_floor_range)
            floor_range = computed_floor_range
        else:
            floor_range = st.selectbox("Floor Range", ["", "NA", "Ground Floor", "Lower Floor (1-5)", "Middle Floor (6-10)", "Higher Floor (10+)", "Higher Floor (20+)", "Top Floor"], key="floor_range")
        
        lease_period = st.text_input("Lease Period", key="lease_period").strip().replace("'", "")
        lock_in_period = st.text_input("Lock-in Period", key="lock_in_period").strip().replace("'", "")
        amenities = st.text_input("Amenities", key="amenities").strip().replace("'", "")
        extra_details = st.text_area("Extra details", key="extra_details").strip().replace("'", "")
        restrictions = st.text_area("Restrictions", key="restrictions").strip().replace("'", "")
        veg_non_veg = st.selectbox("Veg/Non Veg", ["", "Veg Only", "Both"], key="veg_non_veg")
        pet_friendly = st.text_input("Pet friendly", key="pet_friendly").strip().replace("'", "")
        mapLocation = st.text_input("mapLocation", key="mapLocation").strip().replace("'", "")
        coordinates = st.text_input("Coordinates (lat, lng)", key="coordinates").strip().replace("'", "")
        
        st.header("Media Uploads")
        photos_files = st.file_uploader("Upload Photos", type=["jpg", "jpeg", "png"], accept_multiple_files=True, key="photos_files")
        videos_files = st.file_uploader("Upload Videos", type=["mp4", "mov", "avi"], accept_multiple_files=True, key="videos_files")
        documents_files = st.file_uploader("Upload Documents", type=["pdf", "doc", "docx"], accept_multiple_files=True, key="documents_files")
        
        submitted = st.form_submit_button("Submit Inventory")
    
    # Prevent accidental form submission with Enter key
    st.markdown(
        """
        <script>
        document.addEventListener("DOMContentLoaded", function() {
            const inputs = window.parent.document.querySelectorAll('form input');
            inputs.forEach(function(input) {
                input.addEventListener('keydown', function(e) {
                    if (e.key === "Enter") {
                        e.preventDefault();
                    }
                });
            });
        });
        </script>
        """,
        unsafe_allow_html=True
    )
    
    if submitted:
        # -------------------------
        # INVENTORY SUBMISSION DETAILS
        # -------------------------
        property_id = generate_property_id()
        st.write("Generated Property ID:", property_id)
        
        # Create dedicated Drive folder for this property
        prop_drive_folder_id = create_drive_folder(property_id, PARENT_FOLDER_ID)
        drive_main_link = f"https://drive.google.com/drive/folders/{prop_drive_folder_id}" if prop_drive_folder_id else ""
        st.write("Drive Property Folder Link:", drive_main_link)
        
        # Fetch agent details
        agent_id_final, agent_name_final = fetch_agent_details(agent_number)
        agent_id_final = agent_id_final or ""
        agent_name_final = agent_name_final or ""
        
        now = datetime.datetime.now()
        timestamp = int(now.timestamp())
        geoloc = parse_coordinates(coordinates)
        
        # Process media uploads concurrently
        photos_urls, photos_drive_links = process_files_concurrent(photos_files, property_id, "photos", prop_drive_folder_id)
        videos_urls, videos_drive_links = process_files_concurrent(videos_files, property_id, "videos", prop_drive_folder_id)
        documents_urls, documents_drive_links = process_files_concurrent(documents_files, property_id, "documents", prop_drive_folder_id)
        drive_file_links = photos_drive_links + videos_drive_links + documents_drive_links
        
        # Prepare property data dictionary
        property_data = {
            "propertyId": property_id,
            "propertyName": property_name,
            "propertyType": property_type,
            "plotSize": plot_size,
            "SBUA": SBUA,
            "rentPerMonthInLakhs": rent_per_month,
            "commissionType": commission_type,  # New field added
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
        
        # Prepare row for Google Sheets
        sheet_agent_number = strip_plus91(agent_number)
        sheet_row = [
            property_id,
            property_name,
            property_type,
            plot_size,
            SBUA,
            rent_per_month,
            commission_type,  # New field inserted here
            maintenance_charges,
            security_deposit,
            configuration,
            facing,
            furnishing_status,
            micromarket,
            area,
            available_from_val,
            floor_range,
            "",  # Blank for Inventory Status column
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
            now.strftime("%Y-%m-%d"),
            now.strftime("%Y-%m-%d"),
            agent_id_final,
            sheet_agent_number,
            agent_name_final,
            exact_floor
        ]
        
        try:
            db.collection("rental-inventories").document(property_id).set(property_data)
            st.success("Property saved to Firebase!")
        except Exception as e:
            st.error(f"Error saving data to Firebase: {e}")
        
        try:
            append_to_google_sheet(sheet_row)
            st.success("Property details appended to Google Sheet!")
            st.success("Submission Successful!")
        except Exception as e:
            st.error(f"Error appending data to Google Sheet: {e}")

if __name__ == "__main__":
    main()

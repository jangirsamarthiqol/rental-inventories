import os
import datetime
import logging
from io import BytesIO

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, storage
from google.cloud import storage as gcs
import gspread
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from dotenv import load_dotenv

# --------------------
# CONFIGURATION & ENVIRONMENT
# --------------------
load_dotenv()

# Firebase Configuration
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY").replace('\\n', '\n')
FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL")
FIREBASE_STORAGE_BUCKET = os.getenv("FIREBASE_STORAGE_BUCKET")

# Google Sheets Configuration
GOOGLE_SHEET_ID = "14rr4IiEfMVQ_GlzZ-90EkeVNuo4uk_HjjGf8104a3JI"
SHEET_NAME = "Rental Inventories"
GSPREAD_PROJECT_ID = os.getenv("GSPREAD_PROJECT_ID")
GSPREAD_PRIVATE_KEY_ID = os.getenv("GSPREAD_PRIVATE_KEY_ID")
GSPREAD_PRIVATE_KEY = os.getenv("GSPREAD_PRIVATE_KEY").replace('\\n', '\n')
GSPREAD_CLIENT_EMAIL = os.getenv("GSPREAD_CLIENT_EMAIL")
GSPREAD_CLIENT_ID = os.getenv("GSPREAD_CLIENT_ID")

# Google Drive Configuration
GOOGLE_DRIVE_PROJECT_ID = os.getenv("GOOGLE_DRIVE_PROJECT_ID")
GOOGLE_DRIVE_PRIVATE_KEY_ID = os.getenv("GOOGLE_DRIVE_PRIVATE_KEY_ID")
GOOGLE_DRIVE_PRIVATE_KEY = os.getenv("GOOGLE_DRIVE_PRIVATE_KEY").replace('\\n', '\n')
GOOGLE_DRIVE_CLIENT_EMAIL = os.getenv("GOOGLE_DRIVE_CLIENT_EMAIL")
GOOGLE_DRIVE_CLIENT_ID = os.getenv("GOOGLE_DRIVE_CLIENT_ID")
PARENT_FOLDER_ID = os.getenv("PARENT_FOLDER_ID")

# Logging Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --------------------
# FIREBASE INITIALIZATION
# --------------------
firebase_sa_info = {
    "type": "service_account",
    "project_id": FIREBASE_PROJECT_ID,
    "private_key": FIREBASE_PRIVATE_KEY,
    "client_email": FIREBASE_CLIENT_EMAIL,
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": f"https://www.googleapis.com/robot/v1/metadata/x509/{FIREBASE_CLIENT_EMAIL}",
}

def initialize_firebase():
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate(firebase_sa_info)
            firebase_admin.initialize_app(cred, {"storageBucket": FIREBASE_STORAGE_BUCKET})
            logger.info("Firebase initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing Firebase: {e}")
            raise

initialize_firebase()

def get_firestore_client():
    return firestore.client()

def get_storage_bucket():
    return storage.bucket()

def get_gcs_client():
    return gcs.Client.from_service_account_info(firebase_sa_info)

db = get_firestore_client()
bucket = get_storage_bucket()
gcs_client = get_gcs_client()

# --------------------
# GOOGLE SHEETS & DRIVE SERVICES
# --------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Google Sheets Setup via gspread
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
gs_creds = ServiceAccountCredentials.from_service_account_info(gspread_sa_info, scopes=SCOPES)
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
        sheet.update(range_name="A1:AE1", values=[expected_header])

def append_to_google_sheet(row: list):
    try:
        # Get all current data
        all_data = sheet.get_all_values()
        # Determine next row index
        next_row_index = len(all_data) + 1
        # Insert the row at the determined index
        sheet.insert_row(row, index=next_row_index, value_input_option="USER_ENTERED")
    except Exception as e:
        st.error(f"Sheet error: {e}")


# --------------------
# UTILITY FUNCTIONS
# --------------------
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
        num = "+91" + num if not num.startswith("91") else "+" + num
    return num

def strip_plus91(num: str) -> str:
    return num.strip()[3:] if num.strip().startswith("+91") else num.strip()

def fetch_agent_details(agent_number: str):
    agent_number = standardize_phone_number(agent_number)
    docs = db.collection("agents").where(field_path="phonenumber", op_string="==", value=agent_number).limit(1).stream()
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

def upload_media_to_firebase(property_id: str, file_obj, folder: str, filename: str) -> str:
    path = f"rental-media-files/{property_id}/{folder}/{filename}"
    blob = bucket.blob(path)
    try:
        blob.upload_from_file(file_obj, content_type="application/octet-stream")
        blob.make_public()
        return blob.public_url
    except Exception as e:
        st.error(f"Firebase error ({filename}): {e}")
        return ""

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
        "property_type", "property_name", "plot_size", "SBUA",
        "rent_per_month", "maintenance_charges", "security_deposit", "configuration",
        "facing", "furnishing_status", "micromarket", "available_from", "exact_floor",
        "floor_range", "lease_period", "lock_in_period", "amenities", "extra_details",
        "restrictions", "veg_non_veg", "pet_friendly", "mapLocation", "coordinates"
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            st.session_state[key] = ""
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.info("Form cleared! Please refresh the page manually.")

def process_files(files, property_id, folder, drive_folder_id):
    """
    Uploads a list of files to Firebase and Google Drive.
    Returns two lists: one for Firebase URLs and one for Drive links.
    """
    firebase_urls = []
    drive_links = []
    for file in files:
        filename = file.name
        file_bytes = BytesIO(file.read())
        fb_url = upload_media_to_firebase(property_id, file_bytes, folder, filename)
        if fb_url:
            firebase_urls.append(fb_url)
        if drive_folder_id:
            file_bytes.seek(0)
            dlink = upload_media_to_drive(file_bytes, filename, drive_folder_id)
            if dlink:
                drive_links.append(dlink)
    return firebase_urls, drive_links

# --------------------
# STREAMLIT APPLICATION
# --------------------
def main():
    # Set Streamlit page config and favicon
    st.set_page_config(page_title="Rental Inventory", page_icon="./logo.jpg")
    st.markdown(f'<link rel="icon" type="image/jpeg" href="./logo.jpg">', unsafe_allow_html=True)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
    
    # Import area data (ensure area_data.py is in the same directory)
    from area_data import areasData, all_micromarkets, find_area

    ensure_sheet_headers()
    
    st.title("Rental Inventory Entry")
    
    # --- Agent Details ---
    st.header("Agent Details")
    agent_number_input = st.text_input("Agent Number (Phone Number)", key="agent_number").strip()
    
    if st.button("Fetch Agent Details", key="fetch_agent_details"):
        a_id, a_name = fetch_agent_details(agent_number_input)
        if a_id:
            st.success(f"Agent Found: {a_name} (ID: {a_id})")
        else:
            st.error("Agent not found.")
    
    if "property_type" not in st.session_state:
        st.session_state["property_type"] = ""
    
    property_type = st.selectbox(
        "Property Type",
        ["", "Apartment", "Studio", "Duplex", "Triplex", "Villa", "Office Space", "Retail Space", "Commercial Property", "Villament"],
        key="property_type"
    )
    
    with st.form(key="rental_form"):
        st.header("Property Details")
        property_name = st.text_input("Property Name", key="property_name").strip().replace("'", "")
        st.write("Selected property type:", property_type)
        plot_size = st.text_input("Plot Size", key="plot_size").strip().replace("'", "")
        SBUA = st.text_input("SBUA", key="SBUA").strip().replace("'", "")
        rent_per_month = st.text_input("Rent Per Month in Lakhs", key="rent_per_month").strip().replace("'", "")
        maintenance_charges = st.selectbox("Maintenance Charges", ["", "Included", "Not included"], key="maintenance_charges")
        security_deposit = st.text_input("Security Deposit", key="security_deposit").strip().replace("'", "")
        
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
        
        ready_to_move = st.checkbox("Ready to Move", value=False, key="ready_to_move")
        if ready_to_move:
            available_from_val = "Ready-to-move"
        else:
            available_from_date = st.date_input("Available From", datetime.date.today(), key="available_from")
            available_from_val = available_from_date.strftime("%d/%b/%Y").strip().replace("'", "")
        
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
        micromarket_selected = st.multiselect("Select Micromarket", options=all_micromarkets, help="Search and select one micromarket", key="micromarket")
        micromarket = micromarket_selected[0] if micromarket_selected else ""
        area = find_area(micromarket) if micromarket else ""
        
        st.header("Media Uploads")
        photos_files = st.file_uploader("Upload Photos", type=["jpg", "jpeg", "png"], accept_multiple_files=True, key="photos_files")
        videos_files = st.file_uploader("Upload Videos", type=["mp4", "mov", "avi"], accept_multiple_files=True, key="videos_files")
        documents_files = st.file_uploader("Upload Documents", type=["pdf", "doc", "docx"], accept_multiple_files=True, key="documents_files")
        
        submitted = st.form_submit_button("Submit Inventory")
    
    # Prevent accidental form submission on Enter key press
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
        property_id = generate_property_id()
        st.write("Generated Property ID:", property_id)
        
        # Handle media uploads if any files are provided
        has_media = bool(photos_files or videos_files or documents_files)
        if has_media:
            drive_folder_id = create_drive_folder(property_id, PARENT_FOLDER_ID)
            drive_main_link = f"https://drive.google.com/drive/folders/{drive_folder_id}" if drive_folder_id else ""
            st.write("Drive Property Folder Link:", drive_main_link)
        else:
            drive_folder_id = None
            drive_main_link = ""
            st.info("No media files uploaded; skipping Google Drive uploads.")
        
        agent_id_final, agent_name_final = fetch_agent_details(agent_number_input)
        agent_id_final = agent_id_final or ""
        agent_name_final = agent_name_final or ""
        
        now = datetime.datetime.now()
        timestamp = int(now.timestamp())
        geoloc = parse_coordinates(coordinates)
        
        photos_urls, photos_drive_links = process_files(photos_files, property_id, "photos", drive_folder_id)
        videos_urls, videos_drive_links = process_files(videos_files, property_id, "videos", drive_folder_id)
        documents_urls, documents_drive_links = process_files(documents_files, property_id, "documents", drive_folder_id)
        drive_file_links = photos_drive_links + videos_drive_links + documents_drive_links
        
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
            "agentNumber": standardize_phone_number(agent_number_input),
            "agentName": agent_name_final,
            "driveLink": drive_main_link,
            "photos": photos_urls,
            "videos": videos_urls,
            "documents": documents_urls,
            "driveFileLinks": drive_file_links
        }
        
        def sanitize(val):
            if isinstance(val, str):
                new_val = val.strip().replace("'", "")
                try:
                    if '.' in new_val:
                        return float(new_val)
                    elif new_val.isdigit():
                        return int(new_val)
                except Exception:
                    pass
                return new_val
            return val
        
        sheet_agent_number = standardize_phone_number(agent_number_input)[3:]
        sheet_row = [
            property_id,
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
            now.strftime("%Y-%m-%d"),
            now.strftime("%Y-%m-%d"),
            agent_id_final,
            sheet_agent_number,
            agent_name_final,
            exact_floor
        ]
        sheet_row = [sanitize(item) for item in sheet_row]
        
        try:
            append_to_google_sheet(sheet_row)
            db.collection("rental-inventories").document(property_id).set(property_data)
            st.success("Property saved to Firebase!")
            st.success("Property details appended to Google Sheet!")
            st.success("Submission Successful!")
            # Optionally, clear the form after submission:
            # clear_form_callback()
        except Exception as e:
            st.error(f"Error saving data: {e}")

if __name__ == "__main__":
    main()

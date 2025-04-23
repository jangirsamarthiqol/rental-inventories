import os
import datetime
import logging
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Tuple, Optional
import time

import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, storage
from google.cloud import storage as gcs
import gspread
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from dotenv import load_dotenv

# Set page configuration with wider layout and custom theme
st.set_page_config(
    page_title="Rental Inventory System", 
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS for better UI
st.markdown("""
<style>
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    h1, h2, h3 {
        color: #2c3e50;
    }
    .stButton>button {
        background-color: #3498db;
        color: white;
        border-radius: 4px;
        padding: 0.5rem 1rem;
        font-weight: bold;
    }
    .stButton>button:hover {
        background-color: #2980b9;
    }
    .success-message {
        background-color: #d4edda;
        color: #155724;
        padding: 1rem;
        border-radius: 4px;
        margin-bottom: 1rem;
    }
    .warning-message {
        background-color: #fff3cd;
        color: #856404;
        padding: 1rem;
        border-radius: 4px;
        margin-bottom: 1rem;
    }
    .error-message {
        background-color: #f8d7da;
        color: #721c24;
        padding: 1rem;
        border-radius: 4px;
        margin-bottom: 1rem;
    }
    .form-section {
        background-color: #f8f9fa;
        padding: 1.5rem;
        border-radius: 8px;
        margin-bottom: 1.5rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    /* Progress bar styling */
    .stProgress > div > div > div > div {
        background-color: #3498db;
    }
</style>
""", unsafe_allow_html=True)

# Import area data (assumed to be available)
from area_data import areasData, all_micromarkets, find_area

# -------------------------------------
# CONFIGURATION & ENVIRONMENT
# -------------------------------------
load_dotenv()

# --- Firebase Credentials ---
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY").replace('\\n', '\n')
FIREBASE_PRIVATE_KEY_ID = os.getenv("FIREBASE_PRIVATE_KEY_ID")
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
GSPREAD_SHEET_ID = os.getenv("GSPREAD_SHEET_ID")

# --- Google Drive Credentials ---
GOOGLE_DRIVE_PROJECT_ID = os.getenv("GOOGLE_DRIVE_PROJECT_ID")
GOOGLE_DRIVE_PRIVATE_KEY_ID = os.getenv("GOOGLE_DRIVE_PRIVATE_KEY_ID")
GOOGLE_DRIVE_PRIVATE_KEY = os.getenv("GOOGLE_DRIVE_PRIVATE_KEY").replace('\\n', '\n')
GOOGLE_DRIVE_CLIENT_EMAIL = os.getenv("GOOGLE_DRIVE_CLIENT_EMAIL")
GOOGLE_DRIVE_CLIENT_ID = os.getenv("GOOGLE_DRIVE_CLIENT_ID")

# --- Other Configurations ---
PARENT_FOLDER_ID = os.getenv("PARENT_FOLDER_ID")

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------------------------
# CACHED INITIALIZATIONS
# -------------------------------------
@st.cache_resource(ttl=3600)  # Cache for 1 hour
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

# Instead of initializing on import, initialize when needed
db = None
bucket = None
gcs_client = None

@st.cache_resource(ttl=3600)  # Cache for 1 hour
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

# Lazy loading for Google Sheets
gc = None
sheet = None

@st.cache_resource(ttl=3600)  # Cache for 1 hour
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

# Lazy loading for Drive
drive_service = None

def ensure_sheet_headers():
    # Cached function to avoid checking headers on every run
    if 'headers_verified' in st.session_state and st.session_state['headers_verified']:
        return

    expected_header = [
        "Property Id", "Property Name", "Property Type", "Plot Size", "SBUA",
        "Rent Per Month in Lakhs", "Commission Type", "Maintenance Charges", "Security Deposit", "Configuration",
        "Facing", "Furnishing Status", "Micromarket", "Area", "Available From", "Floor Number",
        "Inventory Status",
        "Lease Period", "Lock-in Period", "Amenities", "Extra details", "Restrictions",
        "Veg/Non Veg", "Pet friendly", "Drive Link", "mapLocation", "Coordinates",
        "Date of inventory added", "Date of Status Last Checked", "Agent Id", "Agent Number", "Agent Name", "Exact Floor"
    ]
    current_header = sheet.row_values(1)
    if current_header != expected_header:
        header_range = "A1:AG1"
        sheet.update(values=[expected_header], range_name=header_range)
    
    # Mark headers as verified to avoid rechecking
    st.session_state['headers_verified'] = True

@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_next_row_index():
    values = sheet.get_all_values()
    return len(values) + 1

def append_to_google_sheet(row: list):
    try:
        next_row = get_next_row_index()
        cell_range = f"A{next_row}:AG{next_row}"
        sheet.update(values=[row], range_name=cell_range, value_input_option="USER_ENTERED")
        logger.info(f"Row added at position {next_row}")
        return True
    except Exception as e:
        st.error(f"Sheet error: {e}")
        logger.error(f"Sheet error: {e}")
        return False

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

@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_agent_details(agent_number: str):
    global db
    if db is None:
        db, bucket, gcs_client = init_firebase()
        
    agent_number = standardize_phone_number(agent_number)
    # Use filter() instead of where() to avoid deprecation warning
    query = db.collection("agents").where(filter=firestore.FieldFilter("phonenumber", "==", agent_number)).limit(1)
    docs = query.stream()
    for doc in docs:
        data = doc.to_dict()
        return data.get("cpId"), data.get("name")
    return None, None

@st.cache_data(ttl=300)  # Cache for 5 minutes
def generate_property_id():
    global db
    if db is None:
        db, bucket, gcs_client = init_firebase()
        
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
    global bucket
    if bucket is None:
        _, bucket, _ = init_firebase()
        
    path = f"rental-media-files/{property_id}/{folder}/{filename}"
    blob = bucket.blob(path)
    try:
        blob.upload_from_file(file_obj, content_type="application/octet-stream")
        blob.make_public()
        return blob.public_url
    except Exception as e:
        logger.error(f"Firebase error ({filename}): {e}")
        return ""

@st.cache_data(ttl=600)  # Cache for 10 minutes
def create_drive_folder(folder_name: str, parent_id: str) -> str:
    global drive_service
    if drive_service is None:
        drive_service = init_drive_service()
        
    query = (
        f"'{parent_id}' in parents and name='{folder_name}' and "
        "mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    try:
        files = drive_service.files().list(q=query, fields="files(id)").execute().get("files", [])
    except Exception as e:
        logger.error(f"Error querying drive folders: {e}")
        return ""
    if files:
        return files[0]["id"]
    meta = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    try:
        folder = drive_service.files().create(body=meta, fields="id").execute()
        return folder.get("id")
    except Exception as e:
        logger.error(f"Drive folder error ({folder_name}): {e}")
        return ""

def upload_media_to_drive(file_obj: BytesIO, filename: str, parent_folder_id: str):
    global drive_service
    if drive_service is None:
        drive_service = init_drive_service()
        
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
        logger.error(f"Drive upload error ({filename}): {e}")
        return None

# Optimized file upload with progress tracking
def upload_single_file(file, property_id, folder, drive_folder_id, progress_callback=None):
    filename = file.name
    file_bytes = BytesIO(file.read())
    fb_url = upload_media_to_firebase(property_id, file_bytes, folder, filename)
    dlink = None
    if drive_folder_id:
        file_bytes.seek(0)
        dlink = upload_media_to_drive(file_bytes, filename, drive_folder_id)
    if progress_callback:
        progress_callback()
    return fb_url, dlink

def process_files_concurrent(files, property_id, folder, drive_folder_id, progress_placeholder=None):
    if not files:
        return [], []
    
    firebase_urls = []
    drive_links = []
    file_count = len(files)
    
    # Create a progress bar if a placeholder is provided
    # progress_bar = None
    # if progress_placeholder:
    #     progress_bar = progress_placeholder.progress(0, text=f"Uploading {file_count} files...")
    
    # # Track progress
    # completed = 0
    
    # def update_progress():
    #     nonlocal completed
    #     completed += 1
    #     if progress_bar:
    #         progress_bar.progress(completed / file_count, text=f"Uploaded {completed}/{file_count} files")
    
    # Determine optimal number of workers based on file count
    max_workers = min(4, file_count)  # Max 4 workers, but no more than needed
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(upload_single_file, file, property_id, folder, drive_folder_id) 
            for file in files
        ]
        for future in futures:
            fb_url, dlink = future.result()
            if fb_url:
                firebase_urls.append(fb_url)
            if dlink:
                drive_links.append(dlink)
    
    # Complete the progress bar
    # if progress_bar:
    #     progress_bar.progress(1.0, text="File upload complete!")
    #     time.sleep(0.5)  # Give users a moment to see the completion
    
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
        "restrictions", "veg_non_veg", "pet_friendly", "mapLocation", "coordinates",
        "photos_files", "videos_files", "documents_files", "ready_to_move"
    ]
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    st.rerun()

# -------------------------------------
# STREAMLIT APPLICATION (Inventory Submission UI)
# -------------------------------------
def main():
    # Initialize services only when needed (lazy loading)
    global db, bucket, gcs_client, gc, sheet, drive_service
    st.title("🏠 Rental Inventory System")
    
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🔄 Clear Form", use_container_width=True):
            clear_form_callback()
    
    # Layout with tabs for better organization
    # tab1, tab2 = st.tabs(["📝 Submit New Inventory",""])
    
# with tab1:
    # Initialize needed services for this tab
    if db is None:
        db, bucket, gcs_client = init_firebase()
    if gc is None:
        gc = init_gspread_client()
        sheet = gc.open_by_key(GSPREAD_SHEET_ID).worksheet("Rental Inventories")
        ensure_sheet_headers()
    
    # Create a multi-column layout
    col1, col2 = st.columns(2)
    
    with col1:
        # st.markdown("<div class='form-section'>", unsafe_allow_html=True)
        st.subheader("Agent Details")
        agent_number = st.text_input("Agent Number (Phone Number)", key="agent_number", placeholder="+91XXXXXXXXXX").strip()
        
        agent_id_final = ""
        agent_name_final = ""
        
        if st.button("🔍 Fetch Agent", key="fetch_agent_details"):
            with st.spinner("Looking up agent..."):
                a_id, a_name = fetch_agent_details(agent_number)
                if a_id:
                    st.markdown(f"<div class='success-message'>Agent Found: {a_name} (ID: {a_id})</div>", unsafe_allow_html=True)
                    agent_id_final = a_id
                    agent_name_final = a_name
                else:
                    st.markdown("<div class='error-message'>Agent not found.</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        
        # st.markdown("<div class='form-section'>", unsafe_allow_html=True)
        st.subheader("Property Type & Location")
        
        # Initialize session_state for property_type if not already set
        if "property_type" not in st.session_state:
            st.session_state["property_type"] = ""
        
        property_type = st.selectbox("Property Type", 
            ["", "Apartment", "Studio", "Duplex", "Triplex", "Villa", "Office Space", "Retail Space", "Commercial Property", "Villament", "Plot"],
            key="property_type")
        
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    # with col2:
        # st.markdown("<div class='form-section'>", unsafe_allow_html=True)
        st.subheader("Basic Property Details")
        property_name = st.text_input("Property Name", key="property_name", placeholder="Enter property name").strip().replace("'", "")
        
        # Layout for property dimensions
        dim_col1, dim_col2 = st.columns(2)
        with dim_col1:
            plot_size = st.text_input("Plot Size", key="plot_size", placeholder="e.g., 2400 sq.ft").strip().replace("'", "")
        with dim_col2:
            SBUA = st.text_input("SBUA", key="SBUA", placeholder="e.g., 1800 sq.ft").strip().replace("'", "")
        
        # Layout for financial details
        fin_col1, fin_col2, fin_col3 = st.columns(3)
        with fin_col1:
            rent_per_month = st.text_input("Rent Per Month (Lakhs)", key="rent_per_month", placeholder="e.g., 1.5").strip().replace("'", "")
        with fin_col2:
            commission_type = st.selectbox("Commission Type", ["NA", "Side by Side", "Single Side Commission Split"], key="commission_type")
        with fin_col3:
            security_deposit = st.text_input("Security Deposit", key="security_deposit", placeholder="e.g., 3 months rent").strip().replace("'", "")
            
        maintenance_charges = st.selectbox("Maintenance Charges", ["", "Included", "Not included"], key="maintenance_charges")
        st.markdown("</div>", unsafe_allow_html=True)
        
        # st.markdown("<div class='form-section'>", unsafe_allow_html=True)
        st.subheader("Property Configuration")
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
            configuration = st.text_input("Configuration", key="configuration", placeholder="Enter configuration details").strip().replace("'", "")
            
        # Layout for property features
        feat_col1, feat_col2 = st.columns(2)
        with feat_col1:
            facing = st.selectbox("Facing", 
                                ["", "East", "North", "West", "South", 
                                    "North-East", "North-West", "South-East", "South-West"], 
                                key="facing")
        with feat_col2:
            furnishing_status = st.selectbox("Furnishing Status", 
                                            ["", "Fully Furnished", "Semi Furnished", "Warm Shell", 
                                            "Bare Shell", "Plug & Play"], 
                                            key="furnishing_status")
        
        st.markdown("</div>", unsafe_allow_html=True)
    
    # Create expanded sections for additional details
    # with st.expander("📅 Availability & Lease Details", expanded=False):
        # st.markdown("<div class='form-section'>", unsafe_allow_html=True)
        avail_col1, avail_col2 = st.columns(2)
        
        with avail_col1:
            st.markdown("<div style='margin-top: 44px;'>", unsafe_allow_html=True)
            ready_to_move = st.checkbox("Ready to Move", key="ready_to_move")
            if ready_to_move:
                available_from_val = "Ready-to-move"
                st.info("Property is available immediately")
            else:
                available_from_date = st.date_input("Available From", datetime.date.today(), key="available_from")
                available_from_val = available_from_date.strftime("%Y-%m-%d")
        
        with avail_col2:
            exact_floor = st.text_input("Exact Floor (numeric)", key="exact_floor", placeholder="e.g., 5").strip().replace("'", "")
            if exact_floor:
                computed_floor_range = compute_floor_range(exact_floor)
                st.info(f"Floor Range: {computed_floor_range}")
                floor_range = computed_floor_range
            else:
                floor_range = st.selectbox("Floor Range", 
                                       ["", "NA", "Ground Floor", "Lower Floor (1-5)", 
                                        "Middle Floor (6-10)", "Higher Floor (10+)", 
                                        "Higher Floor (20+)", "Top Floor"], 
                                       key="floor_range")
        
        lease_col1, lease_col2 = st.columns(2)
        with lease_col1:
            lease_period = st.text_input("Lease Period", key="lease_period", placeholder="e.g., 11 months").strip().replace("'", "")
        with lease_col2:
            lock_in_period = st.text_input("Lock-in Period", key="lock_in_period", placeholder="e.g., 6 months").strip().replace("'", "")
        st.markdown("</div>", unsafe_allow_html=True)
    
    # with st.expander("🏠 Property Features & Restrictions", expanded=False):
        # st.markdown("<div class='form-section'>", unsafe_allow_html=True)
        amenities = st.text_input("Amenities", key="amenities", placeholder="e.g., Swimming pool, Gym, Club house").strip().replace("'", "")
        extra_details = st.text_area("Extra details", key="extra_details", placeholder="Any additional information about the property").strip().replace("'", "")
        restrictions = st.text_area("Restrictions", key="restrictions", placeholder="Any restrictions for tenants").strip().replace("'", "")
        
        rest_col1, rest_col2 = st.columns(2)
        with rest_col1:
            veg_non_veg = st.selectbox("Veg/Non Veg", ["", "Veg Only", "Both"], key="veg_non_veg")
        with rest_col2:
            pet_friendly = st.selectbox("Pet friendly", ["", "Yes", "No", "Conditional"], key="pet_friendly")
        
        # Property location details
        micromarket_selected = st.multiselect("Select Micromarket", options=all_micromarkets, 
                                            help="Search and select one micromarket", key="micromarket")
        micromarket = micromarket_selected[0] if micromarket_selected else ""
        area = find_area(micromarket) if micromarket else ""
        
        if area:
            st.info(f"Selected Area: {area}")
            
        mapLocation = st.text_input("Map Location", key="mapLocation", placeholder="e.g., Koramangala 6th Block").strip().replace("'", "")
        coordinates = st.text_input("Coordinates (lat, lng)", key="coordinates", placeholder="12.9716, 77.5946").strip().replace("'", "")
        st.markdown("</div>", unsafe_allow_html=True)
    
    # with st.expander("📸 Media Uploads", expanded=False):
        # st.markdown("<div class='form-section'>", unsafe_allow_html=True)
        photos_files = st.file_uploader("Upload Photos", 
                                    type=["jpg", "jpeg", "png"], 
                                    accept_multiple_files=True, 
                                    key="photos_files",
                                    help="Upload property photos (JPG, PNG)")
        
        if photos_files:
            st.success(f"{len(photos_files)} photos selected")
            
        videos_files = st.file_uploader("Upload Videos", 
                                    type=["mp4", "mov", "avi"], 
                                    accept_multiple_files=True, 
                                    key="videos_files",
                                    help="Upload property videos (MP4, MOV, AVI)")
        
        if videos_files:
            st.success(f"{len(videos_files)} videos selected")
            
        documents_files = st.file_uploader("Upload Documents", 
                                        type=["pdf", "doc", "docx"], 
                                        accept_multiple_files=True, 
                                        key="documents_files",
                                        help="Upload property documents (PDF, DOC, DOCX)")
        
        if documents_files:
            st.success(f"{len(documents_files)} documents selected")
        st.markdown("</div>", unsafe_allow_html=True)
    
    # Add a submit button with a clear visual style
    # st.markdown("<div class='form-section'>", unsafe_allow_html=True)
    submit_col1, submit_col2 = st.columns([1, 1])
    # if st.button():
    #     if not property_name:
    #         st.error("Property Name is required!")
    #         return
    with submit_col1:
        submit_button = st.button("📝 SUBMIT INVENTORY", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)
    
    # Process form submission
    if submit_button:
        # Create a container for submission progress
        if not property_type:
            st.error("Property Type is required!")
            return
        if not rent_per_month:
            st.error("Rent Per Month is required!")
            return
        submission_container = st.empty()
        with submission_container.container():
            # Validate required fields
            required_fields = {
                "Property Name": property_name,
                "Property Type": property_type,
                "Agent Number": agent_number,
                "Micromarket": micromarket
            }
            
            missing_fields = [field for field, value in required_fields.items() if not value]
            
            if missing_fields:
                st.markdown(f"<div class='error-message'>Please fill in the following required fields: {', '.join(missing_fields)}</div>", unsafe_allow_html=True)
            else:
                # Create progress tracking
                # progress_bar = st.progress(0, text="Starting submission process...")
                
                # Step 1: Initialize property ID (10%)
                # progress_bar.progress(0.1, text="Generating property ID...")
                property_id = generate_property_id()
                st.info(f"Property ID: {property_id}")
                time.sleep(0.5)  # Small delay for UI feedback
                
                # Step 2: Create Drive folder (20%)
                # progress_bar.progress(0.2, text="Creating Drive folder...")
                if drive_service is None:
                    drive_service = init_drive_service()
                if  photos_files or videos_files or documents_files:
                    prop_drive_folder_id = create_drive_folder(property_id, PARENT_FOLDER_ID)
                    drive_main_link = f"https://drive.google.com/drive/folders/{prop_drive_folder_id}" if prop_drive_folder_id else ""
                    if drive_main_link:
                        st.info(f"Drive Folder: [Open Folder]({drive_main_link})")
                else:
                    prop_drive_folder_id = ""
                    drive_main_link = ""
                # progress_bar.progress(0.3, text="Drive folder created")
                
                # Step 3: Fetch agent details if not already fetched (40%)
                # progress_bar.progress(0.4, text="Verifying agent details...")
                if not agent_id_final or not agent_name_final:
                    agent_id_final, agent_name_final = fetch_agent_details(agent_number)
                    agent_id_final = agent_id_final or ""
                    agent_name_final = agent_name_final or ""
                
                # Step 4: Prepare basic data (50%)
                # progress_bar.progress(0.5, text="Preparing property data...")
                now = datetime.datetime.now()
                timestamp = int(now.timestamp())
                geoloc = parse_coordinates(coordinates)
                
                # Step 5: Upload media files (60-80%)
                # progress_bar.progress(0.6, text="Uploading media files...")
                
                # Create a placeholder for the file upload progress
                upload_progress = st.empty()
                
                # Process media uploads concurrently with separate progress tracking
                photos_urls, photos_drive_links = process_files_concurrent(
                        photos_files, property_id, "photos", prop_drive_folder_id, upload_progress
                    )
                videos_urls, videos_drive_links = process_files_concurrent(
                        videos_files, property_id, "videos", prop_drive_folder_id, upload_progress
                    )
                documents_urls, documents_drive_links = process_files_concurrent(
                        documents_files, property_id, "documents", prop_drive_folder_id, upload_progress
                    )
                drive_file_links = photos_drive_links + videos_drive_links + documents_drive_links
                
                # Step 6: Prepare property data dictionary (90%)
                # progress_bar.progress(0.9, text="Saving property data...")
                
                # Prepare property data dictionary
                property_data = {
                    "propertyId": property_id,
                    "propertyName": property_name,
                    "propertyType": property_type,
                    "plotSize": plot_size,
                    "SBUA": SBUA,
                    "rentPerMonthInLakhs": rent_per_month,
                    "commissionType": commission_type,
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
                    "driveFileLinks": drive_file_links,
                    "inventoryStatus": "Available"  # Default status for new listings
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
                    commission_type,
                    maintenance_charges,
                    security_deposit,
                    configuration,
                    facing,
                    furnishing_status,
                    micromarket,
                    area,
                    available_from_val,
                    floor_range,
                    "Available",  # Default for Inventory Status column
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
                
                # Step 7: Save to Firebase and Google Sheets (100%)
                firebase_success = False
                sheet_success = False
                
                try:
                    db.collection("rental-inventories").document(property_id).set(property_data)
                    firebase_success = True
                except Exception as e:
                    st.error(f"Error saving data to Firebase: {e}")
                    logger.error(f"Firebase error: {e}")
                
                try:
                    sheet_success = append_to_google_sheet(sheet_row)
                except Exception as e:
                    st.error(f"Error appending data to Google Sheet: {e}")
                    logger.error(f"Sheet error: {e}")
                
                # Final progress update
                # progress_bar.progress(1.0, text="Submission complete!")
                
                # Show success or error message
                if firebase_success and sheet_success:
                    st.markdown("""
                    <div class='success-message'>
                        <h3>✅ Submission Successful!</h3>
                        <p>Property has been added to both Firebase and Google Sheets.</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Show property summary
                    with st.expander("View Property Summary", expanded=True):
                        summary_col1, summary_col2 = st.columns(2)
                        with summary_col1:
                            st.write("**Property ID:**", property_id)
                            st.write("**Property Name:**", property_name)
                            st.write("**Property Type:**", property_type)
                            st.write("**Location:**", micromarket)
                            st.write("**Configuration:**", configuration)
                        with summary_col2:
                            st.write("**Rent:**", f"₹{rent_per_month} Lakhs/month")
                            st.write("**Agent:**", agent_name_final)
                            st.write("**Floor:**", floor_range)
                            st.write("**Availability:**", available_from_val)
                            if drive_main_link:
                                st.write("**Drive Link:**", f"[Open Folder]({drive_main_link})")
                    
                    # Add a button to add another property
                    if st.button("Add Another Property"):
                        clear_form_callback()
                else:
                    # Show appropriate error message
                    error_message = []
                    if not firebase_success:
                        error_message.append("Firebase database")
                    if not sheet_success:
                        error_message.append("Google Sheets")
                        
                    st.markdown(f"""
                    <div class='error-message'>
                        <h3>⚠️ Partial Submission</h3>
                        <p>There was an issue saving to {' and '.join(error_message)}.</p>
                        <p>Please check the logs or contact support for assistance.</p>
                    </div>
                    """, unsafe_allow_html=True)
    


if __name__ == "__main__":
    main()
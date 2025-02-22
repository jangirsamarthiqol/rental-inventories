import streamlit as st
import datetime
from io import BytesIO

from firebase_services import db
from google_services import (
    ensure_sheet_headers,
    append_to_google_sheet,
    create_drive_folder,
    upload_media_to_drive,
)
from utils import (
    parse_coordinates,
    standardize_phone_number,
    strip_plus91,
    fetch_agent_details,
    generate_property_id,
    upload_media_to_firebase,
    compute_floor_range,
    clear_form_callback,
)
from area_data import areasData, all_micromarkets, find_area  # Ensure area_data.py is available

# Ensure sheet headers are set
ensure_sheet_headers()

st.title("Rental Inventory Entry")

st.header("Agent Details")
# Agent Number field is kept outside the form so it remains persistent.
agent_number = st.text_input("Agent Number (Phone Number)", key="agent_number")

if st.button("Fetch Agent Details", key="fetch_agent_details"):
    a_id, a_name = fetch_agent_details(agent_number)
    if a_id:
        st.success(f"Agent Found: {a_name} (ID: {a_id})")
    else:
        st.error("Agent not found.")

# Initialize session state for property_type if not present.
if "property_type" not in st.session_state:
    st.session_state["property_type"] = ""

# Use the selectbox without reassigning the session state key.
property_type = st.selectbox(
    "Property Type",
    ["", "Apartment", "Studio", "Duplex", "Triplex", "Villa", "Office Space", "Retail Space", "Commercial Property", "Villament"],
    key="property_type"
)

with st.form(key="rental_form"):
    st.header("Property Details")
    property_name = st.text_input("Property Name", key="property_name")
    st.write("Selected property type:", property_type)
    plot_size = st.text_input("Plot Size", key="plot_size")
    SBUA = st.text_input("SBUA", key="SBUA")
    rent_per_month = st.text_input("Rent Per Month in Lakhs", key="rent_per_month")
    maintenance_charges = st.selectbox("Maintenance Charges", ["", "Included", "Not included"], key="maintenance_charges")
    security_deposit = st.text_input("Security Deposit", key="security_deposit")
    
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
        configuration = st.text_input("Configuration", key="configuration")
        
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
    
    exact_floor = st.text_input("Exact Floor (numeric, optional)", key="exact_floor")
    if exact_floor.strip():
        computed_floor_range = compute_floor_range(exact_floor)
        st.write("Computed Floor Range:", computed_floor_range)
        floor_range = computed_floor_range
    else:
        floor_range = st.selectbox("Floor Range", ["", "NA", "Ground Floor", "Lower Floor (1-5)", "Middle Floor (6-10)", "Higher Floor (10+)", "Higher Floor (20+)", "Top Floor"], key="floor_range")
    
    lease_period = st.text_input("Lease Period", key="lease_period")
    lock_in_period = st.text_input("Lock-in Period", key="lock_in_period")
    amenities = st.text_input("Amenities", key="amenities")
    extra_details = st.text_area("Extra details", key="extra_details")
    restrictions = st.text_area("Restrictions", key="restrictions")
    veg_non_veg = st.selectbox("Veg/Non Veg", ["", "Veg Only", "Both"], key="veg_non_veg")
    pet_friendly = st.text_input("Pet friendly", key="pet_friendly")
    mapLocation = st.text_input("mapLocation", key="mapLocation")
    coordinates = st.text_input("Coordinates (lat, lng)", key="coordinates")
    
    st.header("Media Uploads")
    photos_files = st.file_uploader("Upload Photos", type=["jpg", "jpeg", "png"], accept_multiple_files=True, key="photos_files")
    videos_files = st.file_uploader("Upload Videos", type=["mp4", "mov", "avi"], accept_multiple_files=True, key="videos_files")
    documents_files = st.file_uploader("Upload Documents", type=["pdf", "doc", "docx"], accept_multiple_files=True, key="documents_files")
    
    # Removed key from form_submit_button since it causes error.
    submitted = st.form_submit_button("Submit Inventory")

# Add a separate Clear Form button to allow manual clearing of the form (agent number remains)
# if st.button("Clear Form", key="clear_form"):
#     clear_form_callback()

# Prevent form submission on Enter key press
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
    
    # Check if there are any media files uploaded
    has_media = bool(photos_files or videos_files or documents_files)
    
    if has_media:
        from config import PARENT_FOLDER_ID
        prop_drive_folder_id = create_drive_folder(property_id, PARENT_FOLDER_ID)
        drive_main_link = f"https://drive.google.com/drive/folders/{prop_drive_folder_id}" if prop_drive_folder_id else ""
        st.write("Drive Property Folder Link:", drive_main_link)
    else:
        prop_drive_folder_id = None
        drive_main_link = ""
        st.info("No media files uploaded; skipping Google Drive uploads.")
    
    agent_id_final, agent_name_final = fetch_agent_details(agent_number)
    agent_id_final = agent_id_final or ""
    agent_name_final = agent_name_final or ""
    
    now = datetime.datetime.now()
    timestamp = int(now.timestamp())
    geoloc = parse_coordinates(coordinates)
    
    photos_urls, videos_urls, documents_urls, drive_file_links = [], [], [], []
    
    # Process Photo uploads
    for photo in photos_files:
        filename = photo.name
        file_bytes = BytesIO(photo.read())
        fb_url = upload_media_to_firebase(property_id, file_bytes, "photos", filename)
        if fb_url:
            photos_urls.append(fb_url)
        if prop_drive_folder_id:
            file_bytes.seek(0)
            dlink = upload_media_to_drive(file_bytes, filename, prop_drive_folder_id)
            if dlink:
                drive_file_links.append(dlink)
    
    # Process Video uploads
    for video in videos_files:
        filename = video.name
        file_bytes = BytesIO(video.read())
        fb_url = upload_media_to_firebase(property_id, file_bytes, "videos", filename)
        if fb_url:
            videos_urls.append(fb_url)
        if prop_drive_folder_id:
            file_bytes.seek(0)
            dlink = upload_media_to_drive(file_bytes, filename, prop_drive_folder_id)
            if dlink:
                drive_file_links.append(dlink)
    
    # Process Document uploads
    for doc in documents_files:
        filename = doc.name
        file_bytes = BytesIO(doc.read())
        fb_url = upload_media_to_firebase(property_id, file_bytes, "documents", filename)
        if fb_url:
            documents_urls.append(fb_url)
        if prop_drive_folder_id:
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
        # Automatically clear form fields (except agent number) after a successful submission.
        # clear_form_callback()
    except Exception as e:
        st.error(f"Error appending to Google Sheet: {e}")

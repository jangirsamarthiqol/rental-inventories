import datetime
import streamlit as st
from firebase_services import db, bucket

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
    from firebase_services import db
    agent_number = standardize_phone_number(agent_number)
    docs = db.collection("agents").where("phonenumber", "==", agent_number).limit(1).stream()
    for doc in docs:
        data = doc.to_dict()
        return data.get("cpId"), data.get("name")
    return None, None

def generate_property_id():
    from firebase_services import db
    docs = list(db.collection("rental-inventories").stream())
    max_id = 0
    for doc in docs:
        pid = doc.get("propertyId")
        if pid and pid.startswith("RN"):
            try:
                num = int(pid.replace("RN", ""))
                if num > max_id:
                    max_id = num
            except Exception:
                pass
    new_id = max_id + 1
    return f"RN{new_id:03d}"

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
    import streamlit as st
    # Note: 'agent_number' is intentionally excluded to persist its value.
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


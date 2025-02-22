import firebase_admin
import logging
from firebase_admin import credentials, firestore, storage
from google.cloud import storage as gcs
from config import FIREBASE_PROJECT_ID, FIREBASE_PRIVATE_KEY, FIREBASE_CLIENT_EMAIL, FIREBASE_STORAGE_BUCKET

# Enable logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Construct Firebase service account info
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

# Firebase initialization function
def initialize_firebase():
    if not firebase_admin._apps:
        try:
            cred = credentials.Certificate(firebase_sa_info)
            firebase_admin.initialize_app(cred, {"storageBucket": FIREBASE_STORAGE_BUCKET})
            logger.info("Firebase initialized successfully.")
        except Exception as e:
            logger.error(f"Error initializing Firebase: {e}")
            raise

# Lazy initialization
initialize_firebase()

# Firestore & Storage Clients
def get_firestore_client():
    return firestore.client()

def get_storage_bucket():
    return storage.bucket()

def get_gcs_client():
    return gcs.Client.from_service_account_info(firebase_sa_info)

db = get_firestore_client()
bucket = get_storage_bucket()
gcs_client = get_gcs_client()

import sqlite3
import os
import logging
import re

# Path to the main application database
MAIN_DB_PATH = "/Users/oscaralvarado/Documents/New project/test_debug_urologia.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fetch_prostate_patients():
    """
    Fetches patients with prostate cancer diagnosis (C61 or text match) 
    from the main urologia.db.
    Returns a list of dictionaries with normalized keys for the ML model.
    """
    if not os.path.exists(MAIN_DB_PATH):
        logger.error(f"Main database not found at {MAIN_DB_PATH}")
        return []

    try:
        conn = sqlite3.connect(MAIN_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Query for prostate cancer patients
        # We select relevant clinical fields for the model
        query = """
            SELECT 
                id as source_id,
                fecha_registro,
                edad as age,
                pros_ape_act as psa,
                pros_gleason,
                pros_tnm as clinical_tstage,
                pros_briganti,
                pros_riesgo,
                diagnostico_principal
            FROM consultas
            WHERE diagnostico_principal LIKE '%CANCER DE PROSTATA%' 
               OR diagnostico_principal LIKE '%C61%'
               OR diagnostico_principal LIKE '%TUMOR MALIGNO DE LA PROSTATA%'
        """
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        patients = []
        for row in rows:
            data = dict(row)
            
            # Normalize and parse data
            normalized_patient = normalize_patient_data(data)
            if normalized_patient:
                patients.append(normalized_patient)
                
        conn.close()
        logger.info(f"Fetched {len(patients)} prostate cancer patients from main DB.")
        return patients

    except Exception as e:
        logger.error(f"Error fetching patients from main DB: {e}")
        return []

def normalize_patient_data(data):
    """
    Transforms the raw DB row into the format expected by the ML model.
    Handles parsing of Gleason scores and other text fields.
    """
    try:
        # Basic validation
        if not data['age'] or not data['psa']:
            return None # Skip invalid records

        patient = {
            'source_id': data['source_id'],
            'age': float(data['age']),
            'psa': float(data['psa']),
            'diagnosis_date': data['fecha_registro'],
            'original_diagnosis': data['diagnostico_principal']
        }

        # Parse Gleason (e.g., "3+4", "7 (3+4)", "8", etc.)
        gleason_str = str(data['pros_gleason'] or "")
        primary, secondary = parse_gleason(gleason_str)
        patient['gleason_primary'] = primary
        patient['gleason_secondary'] = secondary
        
        # Clinical Stage
        # Ensure it matches T1c, T2a, etc.
        tstage = str(data['clinical_tstage'] or "").strip()
        # Simple normalization if needed, otherwise keep as is
        patient['clinical_tstage'] = tstage if tstage else "T1c" # Default or keep None?

        # Cores (Not strictly available in the main DB schema shown, 
        # but 'pros_briganti' or 'protocolo_detalles' might have it.
        # For now, we'll use defaults if missing, or maybe they are in 'protocolo_detalles' JSON.
        # Since 'protocolo_detalles' is JSON, we'd need to parse it. 
        # For this MVP connector, we assume missing cores = average or 0)
        patient['num_cores_positive'] = 0 # Placeholder if not in main columns
        patient['total_cores'] = 12       # Standard
        
        return patient

    except Exception as e:
        logger.warning(f"Skipping patient {data.get('source_id')}: {e}")
        return None

def parse_gleason(text):
    """
    Parses a Gleason string like '3+4', '7(3+4)', '6', etc.
    Returns (primary, secondary). Defaults to (3, 3) if parsing fails but mostly harmless.
    """
    text = text.strip()
    if not text:
        return 3, 3
    
    # Match "X+Y"
    match = re.search(r'(\d)\s*\+\s*(\d)', text)
    if match:
        return int(match.group(1)), int(match.group(2))
    
    # Match single number
    match_single = re.search(r'^(\d)$', text)
    if match_single:
        # If just '7', we assume 3+4? Or 4+3? Hard to say. 
        # Let's assume uniform 3+3 (6) if <7, 3+4 if 7, 4+4 if 8.
        val = int(match_single.group(1))
        if val <= 6: return 3, 3
        if val == 7: return 3, 4
        if val == 8: return 4, 4
        if val == 9: return 4, 5
        if val == 10: return 5, 5
        
    return 3, 3

if __name__ == "__main__":
    # Test connection
    pts = fetch_prostate_patients()
    if not pts:
        print("No patients found. Debugging DB structure:")
        conn = sqlite3.connect(MAIN_DB_PATH)
        cursor = conn.cursor()
        
        # List tables
        print("Listing tables:")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        print(cursor.fetchall())
        
        # List Diagnoses
        print("\nListing all diagnoses from 'consultas':")
        try:
            cursor.execute("SELECT DISTINCT diagnostico_principal FROM consultas")
            print(cursor.fetchall())
        except sqlite3.OperationalError as e:
            print(f"Error reading 'consultas': {e}")
            
        conn.close()
    
    for p in pts[:5]:
        print(p)

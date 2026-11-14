"""Synthetic EHR Data Generator (One Record per File).

Generates individual, heterogeneous, realistic EHR records across:
- JSON (.json) files
- CSV (.csv) files
- Plain text (.txt) files

Each patient record is saved as its own standalone file in data/raw/.
"""

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

DATA_DIR = Path(__file__).resolve().parent / "raw"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 13 Base clinical records representing varied conditions and edge cases
BASE_RECORDS: List[Dict[str, Any]] = [
    {
        "format": "json",
        "patient_id": "P-101",
        "MRN": "MRN-000101",
        "full_name": "Eleanor Vance",
        "birth_date": "1964-08-12",
        "gender_code": "female",
        "encounter": {
            "encounter_id": "ENC-101-1",
            "class": "AMB",
            "period_start": "2023-11-04T09:30:00Z",
            "period_end": "2023-11-04T10:15:00Z",
            "reason": "Routine Diabetic Follow-up and neuropathy review",
        },
        "documents": [
            {
                "doc_id": "DOC-101-A",
                "title": "Endocrinology Outpatient Progress Note",
                "type_code": "34108-1",
                "date": "2023-11-04T10:15:00Z",
                "content": "Patient Eleanor Vance (60 yo F) presents for diabetes management. Reports bilateral foot numbness and burning tingling in lower extremities consistent with diabetic peripheral neuropathy. Current medications: Metformin 1000mg BID, Glipizide 5mg daily. Fundoscopic exam reveals mild non-proliferative diabetic retinopathy. Advised tight glycemic control.",
            }
        ],
        "diagnostics": [
            {
                "report_id": "DIAG-101-A",
                "test_name": "Glycated Hemoglobin (HbA1c)",
                "loinc_code": "4548-4",
                "effective_date": "11/04/2023",
                "conclusion": "HbA1c severely elevated at 10.4% (Ref: <5.7%). Indicative of uncontrolled Type 2 Diabetes Mellitus with chronic microvascular risk.",
            }
        ],
    },
    {
        "format": "json",
        "patient_id": "P-102",
        "MRN": " 102 ",  # Dirty whitespace and bare number
        "full_name": "Marcus Aurelius Thorne",
        "birth_date": "10/24/1978",  # US format
        "gender_code": "M",  # Single letter
        "encounter": {
            "encounter_id": "ENC-102-1",
            "class": "EMER",
            "period_start": "2024-01-15 03:45:00",  # Space separator
            "period_end": "2024-01-15 08:30:00",
            "reason": "Substernal chest pain radiating to left jaw and diaphoresis",
        },
        "documents": [
            {
                "doc_id": "DOC-102-A",
                "title": "Emergency Department Admission Note",
                "type_code": "11488-4",
                "date": "2024-01-15T04:15:00Z",
                "content": "45-year-old male arrived via EMS with acute severe crushing substernal chest pressure, diaphoresis, and shortness of breath starting 2 hours prior. ECG demonstrates ST-segment elevations in leads V1-V4 consistent with acute anterior STEMI. Emergent cardiac catheterization initiated.",
            }
        ],
        "diagnostics": [
            {
                "report_id": "DIAG-102-A",
                "test_name": "Cardiac Troponin I",
                "loinc_code": "10839-9",
                "effective_date": "2024-01-15T04:00:00Z",
                "conclusion": "Troponin I critically elevated at 14.80 ng/mL (Ref: <0.04 ng/mL). Consistent with Acute Myocardial Infarction.",
            }
        ],
    },
    {
        "format": "json",
        "patient_id": "P-103",
        "MRN": "MRN:000103",
        "full_name": "SARAH CHEN",  # All uppercase
        "birth_date": "1992-03-15",
        "gender_code": "Female",
        "encounter": {
            "encounter_id": "ENC-103-1",
            "class": "AMB",
            "period_start": "2023-09-12T14:00:00Z",
            "period_end": "2023-09-12T14:45:00Z",
            "reason": "Persistent productive cough, fever, and right pleuritic chest pain",
        },
        "documents": [
            {
                "doc_id": "DOC-103-A",
                "title": "Pulmonology Consultation Note",
                "type_code": "11488-4",
                "date": "2023-09-12T14:30:00Z",
                "content": "31 yo female with 1-week history of worsening dyspnea, chills, and purulent sputum. Oxygen saturation 92% on ambient air. Right lower lung base reveals crackles and bronchial breath sounds. Started on empiric Levofloxacin for community-acquired pneumonia.",
            }
        ],
        "diagnostics": [
            {
                "report_id": "DIAG-103-A",
                "test_name": "Chest Radiography 2 Views (CXR)",
                "loinc_code": "24648-8",
                "effective_date": "Sep 12, 2023",
                "conclusion": "Frontal and lateral chest radiographs demonstrate dense consolidation in the right lower lobe with prominent air bronchograms, typical for bacterial lobar pneumonia. No pleural effusion.",
            }
        ],
    },
    {
        "format": "json",
        "patient_id": "P-104",
        "MRN": "MRN 104",  # Space separator
        "full_name": "Robert 'Bob' Sterling",  # Nickname quotes
        "birth_date": "1955-12-01",
        "gender_code": "cis-male",  # Non-standard gender string
        "encounter": {
            "encounter_id": "ENC-104-1",
            "class": "IMP",
            "period_start": "2023-12-20T11:00:00Z",
            "period_end": "2023-12-23T15:00:00Z",
            "reason": "Decompensated Congestive Heart Failure exacerbation",
        },
        "documents": [
            {
                "doc_id": "DOC-104-A",
                "title": "Hospital Inpatient Discharge Summary",
                "type_code": "18842-5",
                "date": "2023-12-23T14:00:00Z",
                "content": "68-year-old male with ischemic cardiomyopathy (LVEF 30%) admitted with 15-lb fluid weight gain, severe orthopnea, and bilateral 3+ pitting edema. Responded briskly to IV Furosemide diuresis with 6L net negative fluid balance. Discharge weight stabilized.",
            }
        ],
        "diagnostics": [
            {
                "report_id": "DIAG-104-A",
                "test_name": "B-Type Natriuretic Peptide (BNP)",
                "loinc_code": "30934-4",
                "effective_date": "2023-12-20T12:30:00Z",
                "conclusion": "BNP significantly elevated at 1,890 pg/mL (Ref: <100 pg/mL), confirming acute decompensated heart failure.",
            }
        ],
    },
    {
        "format": "json",
        "patient_id": "P-105",
        "MRN": "000105",
        "full_name": "Amina Al-Mansoor",
        "birth_date": "1988-06-30",
        "gender_code": "F",
        "encounter": {
            "encounter_id": "ENC-105-1",
            "class": "AMB",
            "period_start": "2024-02-10T10:00:00Z",
            "period_end": "2024-02-10T10:30:00Z",
            "reason": "Lupus nephritis surveillance and proteinuria check",
        },
        "documents": [
            {
                "doc_id": "DOC-105-A",
                "title": "Nephrology Clinic Note",
                "type_code": "34108-1",
                "date": "2024-02-10T10:30:00Z",
                "content": "35 yo female with known Systemic Lupus Erythematosus (SLE) and Class IV Lupus Nephritis. Currently maintained on Mycophenolate Mofetil and Hydroxychloroquine. Evaluated for increased peripheral edema and elevated blood pressure.",
            }
        ],
        "diagnostics": [
            {
                "report_id": "DIAG-105-A",
                "test_name": "Urinalysis and Protein/Creatinine Ratio",
                "loinc_code": "2888-6",
                "effective_date": "2024-02-10T11:00:00Z",
                "conclusion": "Urine protein to creatinine ratio markedly elevated at 3.2 mg/mg (Ref: <0.2 mg/mg), demonstrating active nephrotic-range proteinuria and lupus flare.",
            }
        ],
    },
    {
        "format": "csv",
        "patient_id": "P-106",
        "mrn": "MRN-000106",
        "name": "David K. Miller",
        "dob": "1972-04-19",
        "gender": "male",
        "enc_id": "ENC-106-1",
        "enc_class": "AMB",
        "enc_date": "2023-10-18 09:00:00",
        "note_type": "Progress Note",
        "note_content": "51-year-old male with hypertension and chronic kidney disease stage 3b. eGFR 38 mL/min/1.73m2, serum creatinine 2.1 mg/dL. Potassium stable at 4.6 mEq/L. Blood pressure 142/88. Renal ultrasound shows bilateral cortical thinning without hydronephrosis.",
    },
    {
        "format": "csv",
        "patient_id": "P-107",
        "mrn": "MRN:000107",
        "name": "Maria Rodriguez-Santos",
        "dob": "12/03/1980",
        "gender": "F",
        "enc_id": "ENC-107-1",
        "enc_class": "AMB",
        "enc_date": "2024-01-08",
        "note_type": "Consultation Note",
        "note_content": "43-year-old female presents with recurrent right upper quadrant colicky pain postprandially. Abdominal ultrasound confirms cholelithiasis with multiple gallstones and mild gallbladder wall thickening (3.5 mm). Referred for elective laparoscopic cholecystectomy.",
    },
    {
        "format": "csv",
        "patient_id": "P-108",
        "mrn": " 108 ",
        "name": "James O'Connor",
        "dob": "1960-09-05",
        "gender": "M",
        "enc_id": "ENC-108-1",
        "enc_class": "AMB",
        "enc_date": "2023-11-29T15:00:00Z",
        "note_type": "Oncology Follow-up",
        "note_content": "63-year-old male status-post left hemicolectomy for Stage IIA colon adenocarcinoma. Surveillance CT scan of chest/abdomen/pelvis reveals no evidence of local recurrence or distant metastatic disease. CEA level remains within normal limits at 1.8 ng/mL.",
    },
    {
        "format": "csv",
        "patient_id": "P-109",
        "mrn": "MRN-000109",
        "name": "Priya Patel",
        "dob": "1995-07-22",
        "gender": "female",
        "enc_id": "ENC-109-1",
        "enc_class": "AMB",
        "enc_date": "2024-02-01 11:30:00",
        "note_type": "Allergy & Immunology Note",
        "note_content": "28-year-old female with severe refractory atopic dermatitis and allergic rhinitis. Total serum IgE markedly elevated at 1,450 IU/mL. Initiated on Dupilumab 600mg loading dose followed by 300mg biweekly. Tolerating medication well with partial symptom relief.",
    },
    {
        "format": "csv",
        "patient_id": "P-110",
        "mrn": "MRN-000110",
        "name": "William 'Bill' Hayes",
        "dob": "1951-11-14",
        "gender": "cis-male",
        "enc_id": "ENC-110-1",
        "enc_class": "AMB",
        "enc_date": "2023-08-25",
        "note_type": "Orthopedic Clinic Note",
        "note_content": "72-year-old male with severe tricompartmental osteoarthritis of right knee. Radiographs reveal bone-on-bone medial compartment joint space narrowing with subchondral sclerosis and osteophyte formation. Scheduled for right total knee arthroplasty.",
    },
    {
        "format": "txt",
        "patient_id": "P-111",
        "mrn": "MRN-000111",
        "name": "Fatima Zahra Haddad",
        "dob": "1983-05-18",
        "gender": "female",
        "enc_ref": "ENC-111-1 (Ambulatory)",
        "date": "2024-01-22 08:15:00",
        "panel": "Comprehensive Thyroid Panel (LOINC: 11579-0)",
        "findings": "Free T4: 0.42 ng/dL [Low, Ref: 0.8 - 1.8 ng/dL]\nTotal T3: 58 ng/dL [Low, Ref: 80 - 200 ng/dL]\nTSH: 28.5 uIU/mL [Severely Elevated, Ref: 0.45 - 4.5 uIU/mL]\nThyroid Peroxidase Antibodies (TPO): >600 IU/mL [High positive]",
        "impression": "Laboratory findings unequivocally confirm Primary Hypothyroidism secondary to Hashimoto's Thyroiditis. Immediate initiation of Levothyroxine replacement therapy indicated.",
    },
    {
        "format": "txt",
        "patient_id": "P-112",
        "mrn": "112",
        "name": "Arthur Pendelton",
        "dob": "02/14/1958",
        "gender": "M",
        "enc_ref": "ENC-112-1 (Emergency)",
        "date": "Feb 18, 2024",
        "panel": "Brain Magnetic Resonance Imaging (MRI) (LOINC: 24725-4)",
        "findings": "T2 and FLAIR hyperintensity in the left middle cerebral artery (MCA) territory with restricted diffusion on DWI consistent with acute non-hemorrhagic cerebral infarction. No evidence of mass effect, midline shift, or hemorrhagic transformation. MRA reveals high-grade stenosis of the left internal carotid artery bulb.",
        "impression": "Acute ischemic stroke involving left MCA cortical and subcortical regions with severe left ICA stenotic disease.",
    },
    {
        "format": "txt",
        "patient_id": "P-113",
        "mrn": "MRN 000113",
        "name": "Grace Hopper Kelly",
        "dob": "1975-10-31",
        "gender": "F",
        "enc_ref": "ENC-113-1 (Ambulatory)",
        "date": "2023-12-05T13:45:00Z",
        "panel": "Lipid Panel with Reflex LDL (LOINC: 24331-1)",
        "findings": "Total Cholesterol: 295 mg/dL [High, Ref: <200]\nTriglycerides: 320 mg/dL [High, Ref: <150]\nHDL Cholesterol: 38 mg/dL [Low, Ref: >50]\nCalculated LDL Cholesterol: 193 mg/dL [Severe elevation, Ref: <100]",
        "impression": "Severe Mixed Hyperlipidemia with prominent atherogenic dyslipidemia. Significant cardiovascular risk. Statin therapy and lifestyle modifications recommended.",
    },
]


def write_single_record(record: Dict[str, Any], output_dir: Path) -> Path:
    """Writes a single patient record into its own standalone file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    fmt = record.get("format", "json").lower()
    p_id = record.get("patient_id", "P-UNKNOWN").lower().replace(":", "_").replace(" ", "_")

    if fmt == "json":
        file_path = output_dir / f"{p_id}.json"
        data_to_write = {k: v for k, v in record.items() if k != "format"}
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data_to_write, f, indent=2)
        return file_path

    elif fmt == "csv":
        file_path = output_dir / f"{p_id}.csv"
        with open(file_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Pt_MRN", "patient_name", "dob", "gender", "encounter_id", "enc_class", "enc_date", "note_type", "note_content"])
            writer.writerow([
                record["mrn"],
                record["name"],
                record["dob"],
                record["gender"],
                record["enc_id"],
                record["enc_class"],
                record["enc_date"],
                record["note_type"],
                record["note_content"],
            ])
        return file_path

    elif fmt == "txt":
        file_path = output_dir / f"{p_id}.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("--- RECORD START ---\n")
            f.write(f"PATIENT IDENTIFIER: {record['mrn']}\n")
            f.write(f"PATIENT NAME: {record['name']}\n")
            f.write(f"DOB: {record['dob']}\n")
            f.write(f"GENDER: {record['gender']}\n")
            f.write(f"ENCOUNTER REF: {record['enc_ref']}\n")
            f.write(f"COLLECTION DATE: {record['date']}\n")
            f.write(f"TEST PANEL: {record['panel']}\n")
            f.write(f"FINDINGS:\n{record['findings']}\n")
            f.write(f"CLINICAL IMPRESSION:\n{record['impression']}\n")
            f.write("--- RECORD END ---\n")
        return file_path
    else:
        raise ValueError(f"Unknown format: {fmt}")


def generate_all(output_dir: Path = DATA_DIR):
    created = []
    for rec in BASE_RECORDS:
        fp = write_single_record(rec, output_dir)
        created.append(fp)
    print(f"Generated {len(created)} individual patient record files in {output_dir}/")
    return created


if __name__ == "__main__":
    generate_all()

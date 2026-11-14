"""LLM-Powered Synthetic EHR Data Generator.

Generates dozens of realistic, heterogeneous mock clinical EHR records on the fly
using a local OpenAPI/OpenAI-compatible LLM server hosted via LM Studio (http://127.0.0.1:1234).

Uses lightweight, fast models (< 8B parameters), e.g.:
- llama-3.2-1b-instruct (default: ultra-fast and reliable instruction following)
- qwen3.5-0.8b
- google/gemma-3-1b

Outputs:
1. simulated_ehr_export.json (Simulated Epic EHR exports)
2. scanned_notes.csv (Consultation notes with realistic headers)
3. lab_results.txt (Unstructured pathology and diagnostic panels)
"""

import argparse
import csv
import json
import random
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"
DEFAULT_MODEL = "llama-3.2-1b-instruct"

# Diverse clinical archetypes for generation
CLINICAL_SPECIALTIES = [
    {
        "specialty": "Cardiology",
        "condition": "Acute Anterior STEMI with critical troponin elevation",
        "doc_type": "Emergency Department Admission Note",
        "loinc_code": "10839-9",
        "test_name": "Cardiac Troponin I",
        "keywords": ["chest pain", "diaphoresis", "ST elevation V1-V4", "catheterization"],
    },
    {
        "specialty": "Endocrinology",
        "condition": "Uncontrolled Type 2 Diabetes with peripheral neuropathy",
        "doc_type": "Endocrine Outpatient Progress Note",
        "loinc_code": "4548-4",
        "test_name": "Glycated Hemoglobin (HbA1c)",
        "keywords": ["HbA1c > 10%", "foot tingling", "metformin", "retinopathy"],
    },
    {
        "specialty": "Pulmonology",
        "condition": "Community-Acquired Lobar Pneumonia",
        "doc_type": "Pulmonology Consultation Note",
        "loinc_code": "24648-8",
        "test_name": "Chest Radiography (CXR 2-Views)",
        "keywords": ["dense consolidation", "purulent sputum", "pleuritic chest pain", "air bronchograms"],
    },
    {
        "specialty": "Nephrology",
        "condition": "Class IV Lupus Nephritis Flare with severe proteinuria",
        "doc_type": "Nephrology Clinic Note",
        "loinc_code": "2888-6",
        "test_name": "Urinalysis and Protein/Creatinine Ratio",
        "keywords": ["proteinuria 3.5 mg/mg", "edema", "hypertension", "hydroxychloroquine"],
    },
    {
        "specialty": "Neurology",
        "condition": "Acute Ischemic Stroke of Left MCA territory",
        "doc_type": "Neurology Inpatient Assessment",
        "loinc_code": "24725-4",
        "test_name": "Brain Magnetic Resonance Imaging (MRI DWI/FLAIR)",
        "keywords": ["restricted diffusion", "MCA infarction", "aphasia", "carotid stenosis"],
    },
    {
        "specialty": "Cardiology",
        "condition": "Acute Decompensated Congestive Heart Failure",
        "doc_type": "Inpatient Hospital Discharge Summary",
        "loinc_code": "30934-4",
        "test_name": "B-Type Natriuretic Peptide (BNP)",
        "keywords": ["BNP > 1500 pg/mL", "orthopnea", "3+ bilateral edema", "furosemide diuresis"],
    },
    {
        "specialty": "Gastroenterology",
        "condition": "Acute Cholecystitis with symptomatic cholelithiasis",
        "doc_type": "Gastroenterology Consultation Note",
        "loinc_code": "24331-1",
        "test_name": "Right Upper Quadrant Abdominal Ultrasound",
        "keywords": ["gallbladder wall thickening", "cholelithiasis", "Murphy's sign", "laparoscopic cholecystectomy"],
    },
    {
        "specialty": "Rheumatology",
        "condition": "Seropositive Rheumatoid Arthritis with erosive joint changes",
        "doc_type": "Rheumatology Progress Note",
        "loinc_code": "11579-0",
        "test_name": "Rheumatoid Factor and Anti-CCP Antibodies",
        "keywords": ["morning stiffness > 1 hour", "symmetric MCP joint swelling", "anti-CCP > 250 U/mL"],
    },
    {
        "specialty": "Hematology / Oncology",
        "condition": "Colorectal Adenocarcinoma Post-Resection Surveillance",
        "doc_type": "Oncology Surveillance Note",
        "loinc_code": "24323-8",
        "test_name": "Carcinoembryonic Antigen (CEA) and Surveillance CT",
        "keywords": ["status-post hemicolectomy", "CEA 1.6 ng/mL", "no local recurrence", "NED"],
    },
    {
        "specialty": "Allergy & Immunology",
        "condition": "Severe Refractory Atopic Dermatitis with extreme IgE elevation",
        "doc_type": "Allergy & Immunology Progress Note",
        "loinc_code": "24323-8",
        "test_name": "Total Serum Immunoglobulin E (IgE)",
        "keywords": ["total IgE > 1600 IU/mL", "severe pruritus", "dupilumab biologic therapy"],
    },
    {
        "specialty": "Orthopedics",
        "condition": "Severe Tricompartmental Osteoarthritis of Right Knee",
        "doc_type": "Orthopedic Surgery Clinic Note",
        "loinc_code": "24648-8",
        "test_name": "Standing Bilateral Knee Radiographs",
        "keywords": ["bone-on-bone medial narrowing", "subchondral sclerosis", "total knee arthroplasty candidate"],
    },
    {
        "specialty": "Endocrinology",
        "condition": "Primary Hypothyroidism secondary to Hashimoto's Thyroiditis",
        "doc_type": "Endocrinology Consultation Note",
        "loinc_code": "11579-0",
        "test_name": "Comprehensive Thyroid Panel with TPO Antibodies",
        "keywords": ["TSH 32 uIU/mL", "Free T4 0.35 ng/dL", "TPO > 600", "levothyroxine replacement"],
    },
]

FIRST_NAMES = [
    "Eleanor", "Marcus", "Sarah", "Robert", "Amina", "David", "Maria",
    "James", "Priya", "William", "Fatima", "Arthur", "Grace", "Liam",
    "Sophia", "Mateo", "Chloe", "Alexander", "Zara", "Benjamin"
]
LAST_NAMES = [
    "Vance", "Thorne", "Chen", "Sterling", "Al-Mansoor", "Miller",
    "Rodriguez-Santos", "O'Connor", "Patel", "Hayes", "Haddad", "Pendelton",
    "Kelly", "Dubois", "Nakamura", "Morales", "Kowalski", "Adeyemi", "Johansson"
]
GENDER_VARIANTS = ["female", "male", "F", "M", "cis-male", "cis female", "non-binary", "UNKNOWN"]
DATE_FORMATS = [
    "{y}-{m:02d}-{d:02d}",
    "{m:02d}/{d:02d}/{y}",
    "{y}.{m:02d}.{d:02d}",
]


class LLMSyntheticGenerator:
    """Generates synthetic patient cohorts using an OpenAPI-compatible LLM endpoint."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def verify_connection(self) -> bool:
        """Check if LM Studio server is running and discover models."""
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self.base_url}/models")
                if resp.status_code == 200:
                    models_data = resp.json().get("data", [])
                    model_ids = [m.get("id") for m in models_data]
                    print(f"Connected to LM Studio at {self.base_url}")
                    print(f"Available models: {model_ids}")
                    if self.model not in model_ids and model_ids:
                        # Auto-select the first available model under 8B
                        preferred = [m for m in model_ids if any(k in m for k in ["llama", "gemma", "qwen", "1b", "2b", "3b", "4b", "8b"])]
                        self.model = preferred[0] if preferred else model_ids[0]
                        print(f"Selected active model: {self.model}")
                    return True
        except Exception as e:
            print(f"Warning: Could not connect to LM Studio at {self.base_url}: {e}")
            print("Falling back to deterministic clinical templates if LLM is unreachable.")
        return False

    def generate_clinical_note_content(self, patient_name: str, age: int, gender: str, archetype: Dict[str, Any]) -> str:
        """Prompt local model to synthesize rich clinical note and diagnostic findings."""
        prompt = (
            f"Generate a realistic EHR clinical progress note for patient {patient_name}, "
            f"{age}yo {gender}, presenting with {archetype['condition']}. "
            f"Include symptoms ({', '.join(archetype['keywords'])}), physical exam findings, and management plan. "
            f"Output between 50 to 90 words of realistic medical prose."
        )

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": "You are an expert physician documenting in Epic EHR. Output concise clinical text only."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 160,
                    },
                )
                if resp.status_code == 200:
                    text = resp.json()["choices"][0]["message"]["content"]
                    # Clean out potential thought tags or code blocks
                    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
                    text = re.sub(r"```[\s\S]*?```", "", text).strip()
                    if len(text.split()) >= 20:
                        return text
        except Exception:
            pass

        # Robust programmatic fallback if LLM is unavailable or times out
        return (
            f"{age}-year-old {gender} presented for evaluation of {archetype['condition'].lower()}. "
            f"Documented clinical findings reveal prominent {archetype['keywords'][0]} and {archetype['keywords'][1]}. "
            f"Diagnostic evaluation confirms {archetype['test_name']} abnormalities consistent with active disease. "
            f"Initiated guideline-directed medical therapy with scheduled outpatient follow-up."
        )

    def generate_cohort(self, count: int = 12) -> List[Dict[str, Any]]:
        """Generate a cohort of diverse synthetic patient records."""
        records = []

        for i in range(count):
            p_id = f"P-{200 + i}"
            mrn_raw = random.choice([
                f"MRN-{200 + i:06d}",
                f" {200 + i} ",  # Dirty whitespace
                f"MRN {200 + i}",
                f"MRN:{200 + i:06d}",
            ])
            first = random.choice(FIRST_NAMES)
            last = random.choice(LAST_NAMES)
            full_name = f"{first} {last}"
            if random.random() < 0.2:
                full_name = full_name.upper()  # All caps edge case
            elif random.random() < 0.2:
                full_name = f"{first} '{first[:3]}' {last}"  # Nickname quotes edge case

            age = random.randint(25, 82)
            birth_year = 2024 - age
            b_month = random.randint(1, 12)
            b_day = random.randint(1, 28)
            fmt = random.choice(DATE_FORMATS)
            dob_str = fmt.format(y=birth_year, m=b_month, d=b_day)

            gender_str = random.choice(GENDER_VARIANTS)
            archetype = CLINICAL_SPECIALTIES[i % len(CLINICAL_SPECIALTIES)]

            enc_year = random.choice([2023, 2024])
            enc_month = random.randint(1, 12)
            enc_day = random.randint(1, 28)
            enc_date = f"{enc_year}-{enc_month:02d}-{enc_day:02d}"
            enc_id = f"ENC-{200 + i}-1"
            enc_class = random.choice(["AMB", "EMER", "IMP"])

            content = self.generate_clinical_note_content(first, age, gender_str, archetype)

            doc = {
                "doc_id": f"DOC-{200 + i}-A",
                "title": archetype["doc_type"],
                "type_code": "34108-1",
                "date": f"{enc_date}T10:00:00Z",
                "content": content,
                "mime_type": "text/plain",
            }

            diag = {
                "report_id": f"DIAG-{200 + i}-A",
                "test_name": archetype["test_name"],
                "loinc_code": archetype["loinc_code"],
                "effective_date": enc_date,
                "conclusion": f"{archetype['test_name']} abnormal findings: {archetype['condition']}. Key indicators: {', '.join(archetype['keywords'][:2])}.",
            }

            patient_record = {
                "patient_id": p_id,
                "MRN": mrn_raw,
                "full_name": full_name,
                "birth_date": dob_str,
                "gender_code": gender_str,
                "encounter": {
                    "encounter_id": enc_id,
                    "class": enc_class,
                    "period_start": f"{enc_date}T09:00:00Z",
                    "period_end": f"{enc_date}T10:30:00Z",
                    "reason": archetype["condition"],
                },
                "documents": [doc],
                "diagnostics": [diag],
                "specialty": archetype["specialty"],
            }
            records.append(patient_record)
            print(f"  [+] Generated Patient {i+1}/{count}: {full_name} ({p_id}) - {archetype['condition']}")

        return records

    def export_individual_records(self, records: List[Dict[str, Any]], output_dir: Path) -> List[Path]:
        """Export each generated record into its own standalone file, rotating across JSON, CSV, and TXT."""
        output_dir.mkdir(parents=True, exist_ok=True)
        created_files = []

        for idx, r in enumerate(records):
            p_id = r["patient_id"].lower().replace(":", "_").replace(" ", "_")
            fmt = ["json", "csv", "txt"][idx % 3]

            if fmt == "json":
                file_path = output_dir / f"{p_id}.json"
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(r, f, indent=2)
                created_files.append(file_path)

            elif fmt == "csv":
                file_path = output_dir / f"{p_id}.csv"
                enc = r["encounter"]
                doc = r["documents"][0]
                with open(file_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(["Pt_MRN", "patient_name", "dob", "gender", "encounter_id", "enc_class", "enc_date", "note_type", "note_content"])
                    writer.writerow([
                        r["MRN"],
                        r["full_name"],
                        r["birth_date"],
                        r["gender_code"],
                        enc["encounter_id"],
                        enc["class"],
                        enc["period_start"],
                        doc["title"],
                        doc["content"],
                    ])
                created_files.append(file_path)

            elif fmt == "txt":
                file_path = output_dir / f"{p_id}.txt"
                enc = r["encounter"]
                diag = r["diagnostics"][0]
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("--- RECORD START ---\n")
                    f.write(f"PATIENT IDENTIFIER: {r['MRN'].strip()}\n")
                    f.write(f"PATIENT NAME: {r['full_name']}\n")
                    f.write(f"DOB: {r['birth_date']}\n")
                    f.write(f"GENDER: {r['gender_code']}\n")
                    f.write(f"ENCOUNTER REF: {enc['encounter_id']} ({enc['class']})\n")
                    f.write(f"COLLECTION DATE: {diag['effective_date']}\n")
                    f.write(f"TEST PANEL: {diag['test_name']} (LOINC: {diag['loinc_code']})\n")
                    f.write(f"FINDINGS:\n{diag['conclusion']}\n")
                    f.write(f"CLINICAL IMPRESSION:\nConfirmed diagnosis of {enc['reason']}.\n")
                    f.write("--- RECORD END ---\n")
                created_files.append(file_path)

        json_count = sum(1 for p in created_files if p.suffix == ".json")
        csv_count = sum(1 for p in created_files if p.suffix == ".csv")
        txt_count = sum(1 for p in created_files if p.suffix == ".txt")
        print(f"Exported {len(created_files)} individual records to {output_dir}/ ({json_count} JSON, {csv_count} CSV, {txt_count} TXT)")
        return created_files

    def export_all_formats(self, records: List[Dict[str, Any]], output_dir: Path) -> List[Path]:
        """Backwards-compatible export that creates individual record files."""
        return self.export_individual_records(records, output_dir)


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic EHR cohorts using local OpenAPI-compatible LLM.")
    parser.add_argument("--count", type=int, default=100, help="Number of individual patient record files to generate (default: 100)")
    parser.add_argument("--base-url", type=str, default=DEFAULT_BASE_URL, help=f"LM Studio API base URL (default: {DEFAULT_BASE_URL})")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help=f"LLM model name (default: {DEFAULT_MODEL})")
    parser.add_argument("--output-dir", type=str, default="data/raw", help="Target directory for generated EHR files (default: data/raw)")
    args = parser.parse_args()

    generator = LLMSyntheticGenerator(base_url=args.base_url, model=args.model)
    generator.verify_connection()

    print(f"\nGenerating {args.count} individual synthetic EHR patient records using {generator.model}...")
    records = generator.generate_cohort(count=args.count)

    out_dir = Path(args.output_dir)
    generator.export_individual_records(records, output_dir=out_dir)
    print(f"\nSuccessfully generated {len(records)} individual records in {out_dir}/ ready for ingestion!\n")


if __name__ == "__main__":
    main()


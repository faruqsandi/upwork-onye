"""Prompt engineering templates for concise, strictly structured clinical summaries."""

CLINICAL_SUMMARIZER_SYSTEM_PROMPT = """You are an expert clinical informatics AI assistant.
Your task is to synthesize heterogeneous patient EHR records (clinical progress notes, lab reports, imaging studies) into a concise, high-yield structured summary for attending physicians.

CRITICAL INSTRUCTIONS:
1. WORD LIMIT: Your entire summary MUST be strictly UNDER 200 WORDS. Brevity and high signal-to-noise ratio are paramount.
2. CLINICAL ACCURACY: Rely strictly on documented findings. Never invent, hallucinate, or assume unstated diagnoses.
3. STRUCTURE: You must output a JSON object with the following exact keys:
   - "chief_concern": Single concise sentence stating the primary clinical reason for care.
   - "key_diagnoses": Array of active clinical conditions and chronic diseases mentioned.
   - "recent_media_and_labs": Array of recent imaging studies, pathology, or laboratory test results.
   - "flagged_anomalies": Array of abnormal, critical, or high-risk findings (e.g. critically elevated lab values, acute ischemic changes, acute exacerbations).
   - "full_summary_text": A cohesive narrative paragraph under 150 words synthesizing the patient's current clinical picture.
4. TONE: Objective, clinical, and precise.
"""

CLINICAL_FEW_SHOT_EXAMPLE = """
Example Input:
Patient: Eleanor Vance (60 yo F)
Encounter: Diabetic Follow-up and neuropathy review
Document: Patient reports bilateral foot numbness and burning tingling in lower extremities consistent with diabetic peripheral neuropathy. Metformin 1000mg BID. Fundoscopic exam reveals mild non-proliferative diabetic retinopathy.
Diagnostic: HbA1c severely elevated at 10.4% (Ref: <5.7%). Indicative of uncontrolled Type 2 Diabetes Mellitus.

Example Output:
{
  "chief_concern": "Uncontrolled Type 2 Diabetes Mellitus with worsening bilateral lower extremity neuropathy.",
  "key_diagnoses": ["Type 2 Diabetes Mellitus", "Diabetic Peripheral Neuropathy", "Mild Non-Proliferative Diabetic Retinopathy"],
  "recent_media_and_labs": ["Glycated Hemoglobin (HbA1c): 10.4% (severely elevated)", "Fundoscopic examination"],
  "flagged_anomalies": ["Critical glycemic elevation (HbA1c 10.4%) with progressive microvascular complications"],
  "full_summary_text": "60-year-old female presenting for diabetic management with progressive bilateral distal neuropathy and mild diabetic retinopathy. Glycemic control is severely decompensated with HbA1c 10.4% despite oral hypoglycemics. Urgent therapeutic intensification and podiatry/ophthalmology follow-up indicated."
}
"""


def build_user_prompt(patient_info: str, documents: list[str], diagnostics: list[str]) -> str:
    docs_block = "\n---\n".join(documents) if documents else "No progress notes available."
    diags_block = "\n---\n".join(diagnostics) if diagnostics else "No diagnostic reports available."

    return f"""PATIENT INFORMATION:
{patient_info}

CLINICAL NOTES & DOCUMENTS:
{docs_block}

DIAGNOSTIC & LAB REPORTS:
{diags_block}

Generate the structured JSON summary now conforming to all rules (strictly under 200 words total).
"""


"""Clinical summarization engine with Claude, OpenAI, and deterministic Mock providers."""

import base64
import json
import re
from abc import ABC, abstractmethod
from typing import List, Optional
import httpx
from fhir.resources.bundle import Bundle

from src.config import settings
from src.ingestion.models import CanonicalPatient
from .cache import SummaryCache
from .models import DEFAULT_DISCLAIMER, ClinicalSummary
from .prompts import (
    CLINICAL_FEW_SHOT_EXAMPLE,
    CLINICAL_SUMMARIZER_SYSTEM_PROMPT,
    build_user_prompt,
)


class BaseLLMClient(ABC):
    """Abstract interface for LLM summarization clients."""

    @abstractmethod
    def summarize(
        self,
        patient_id: str,
        patient_info: str,
        documents: List[str],
        diagnostics: List[str],
    ) -> ClinicalSummary:
        pass


class MockLLMClient(BaseLLMClient):
    """Deterministic, offline clinical intelligence provider.

    Ensures zero external API dependency and 100% reproducible test runs.
    """

    def summarize(
        self,
        patient_id: str,
        patient_info: str,
        documents: List[str],
        diagnostics: List[str],
    ) -> ClinicalSummary:
        combined_text = "\n".join(documents + diagnostics)

        # 1. Chief concern extraction
        chief_concern = "Evaluation and ongoing clinical management."
        if "chest pain" in combined_text.lower() or "stemi" in combined_text.lower():
            chief_concern = "Acute chest pressure with acute anterior ST-segment elevation myocardial infarction."
        elif "diabetes" in combined_text.lower() or "hba1c" in combined_text.lower():
            chief_concern = "Uncontrolled Type 2 Diabetes Mellitus with peripheral neuropathic symptoms."
        elif "pneumonia" in combined_text.lower() or "cough" in combined_text.lower():
            chief_concern = "Community-acquired lobar pneumonia with fever and productive cough."
        elif "heart failure" in combined_text.lower() or "bnp" in combined_text.lower():
            chief_concern = "Decompensated congestive heart failure with fluid overload."
        elif "lupus" in combined_text.lower() or "proteinuria" in combined_text.lower():
            chief_concern = "Active Class IV Lupus Nephritis flare with severe proteinuria."
        elif "thyroid" in combined_text.lower() or "tsh" in combined_text.lower():
            chief_concern = "Primary hypothyroidism secondary to Hashimoto's thyroiditis."
        elif "stroke" in combined_text.lower() or "mca" in combined_text.lower():
            chief_concern = "Acute ischemic left MCA cerebral infarction with carotid stenosis."

        # 2. Key diagnoses extraction
        key_diagnoses = []
        diag_candidates = [
            ("Type 2 Diabetes Mellitus", ["diabetes", "hba1c", "metformin"]),
            ("Diabetic Peripheral Neuropathy", ["neuropathy", "tingling", "numbness"]),
            ("Acute Anterior STEMI", ["stemi", "troponin", "st-segment", "infarction"]),
            ("Community-Acquired Pneumonia", ["pneumonia", "consolidation", "air bronchograms"]),
            ("Ischemic Cardiomyopathy / CHF", ["heart failure", "cardiomyopathy", "bnp"]),
            ("Systemic Lupus Erythematosus / Nephritis", ["lupus", "nephritis", "proteinuria"]),
            ("Hypertension & Stage 3b CKD", ["hypertension", "kidney disease", "ckd", "egfr"]),
            ("Symptomatic Cholelithiasis", ["cholelithiasis", "gallstones"]),
            ("Primary Hypothyroidism", ["hypothyroidism", "hashimoto", "tsh"]),
            ("Acute Ischemic Stroke", ["stroke", "infarction", "mca", "diffusion"]),
            ("Severe Hyperlipidemia", ["hyperlipidemia", "cholesterol", "ldl"]),
        ]
        for name, keywords in diag_candidates:
            if any(k in combined_text.lower() for k in keywords):
                key_diagnoses.append(name)
        if not key_diagnoses:
            key_diagnoses = ["Clinical evaluation documented"]

        # 3. Recent media and labs extraction
        recent_media = []
        for d in diagnostics:
            # take first 100 characters or key test lines
            first_line = d.strip().split("\n")[0]
            recent_media.append(first_line[:120])
        if not recent_media:
            recent_media = ["No recent diagnostic lab or imaging studies on file."]

        # 4. Flagged anomalies extraction
        anomalies = []
        anomaly_patterns = [
            (r"(HbA1c severely elevated[^\.\n]*)", "Critical HbA1c elevation"),
            (r"(Troponin I critically elevated[^\.\n]*)", "Critically elevated Troponin I (STEMI)"),
            (r"(BNP significantly elevated[^\.\n]*)", "Significantly elevated BNP (acute decompensation)"),
            (r"(dense consolidation[^\.\n]*)", "Lobar consolidation on chest radiography"),
            (r"(TSH:\s*[\d\.]+\s*uIU/mL[^\.\n]*)", "Severely elevated TSH with low Free T4"),
            (r"(acute non-hemorrhagic cerebral infarction[^\.\n]*)", "Acute ischemic stroke on brain MRI"),
            (r"(protein to creatinine ratio markedly elevated[^\.\n]*)", "Nephrotic-range proteinuria flare"),
            (r"(Calculated LDL[^\.\n]*)", "Marked LDL cholesterol elevation"),
        ]
        for pat, desc in anomaly_patterns:
            m = re.search(pat, combined_text, re.IGNORECASE)
            if m:
                anomalies.append(f"{desc}: {m.group(1).strip()}")
        if not anomalies:
            anomalies.append("No critical anomalies flagged in current record.")

        # 5. Full summary narrative (<150 words)
        diagnoses_str = ", ".join(key_diagnoses[:3])
        anomalies_str = "; ".join(anomalies[:2])
        full_text = (
            f"Patient {patient_id} presents with {chief_concern.lower()} "
            f"Active clinical profile includes {diagnoses_str}. "
            f"Recent diagnostic evaluations demonstrate key findings: {anomalies_str}. "
            f"Ongoing therapeutic monitoring and clinical correlation are advised."
        )

        words = full_text.split()
        if len(words) > 180:
            full_text = " ".join(words[:180]) + "..."
            words = full_text.split()

        return ClinicalSummary(
            patient_id=patient_id,
            chief_concern=chief_concern,
            key_diagnoses=key_diagnoses,
            recent_media_and_labs=recent_media,
            flagged_anomalies=anomalies,
            full_summary_text=full_text,
            word_count=len(words),
            confidence_score=0.96,
            disclaimer=DEFAULT_DISCLAIMER,
            cached=False,
        )


class AnthropicLLMClient(BaseLLMClient):
    """Anthropic Claude API client."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def summarize(
        self,
        patient_id: str,
        patient_info: str,
        documents: List[str],
        diagnostics: List[str],
    ) -> ClinicalSummary:
        prompt = build_user_prompt(patient_info, documents, diagnostics)
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 1024,
            "system": CLINICAL_SUMMARIZER_SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": CLINICAL_FEW_SHOT_EXAMPLE},
                {"role": "user", "content": prompt},
            ],
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
            resp.raise_for_status()
            res_json = resp.json()
            content_text = res_json["content"][0]["text"]

            # Parse JSON from response
            json_match = re.search(r"\{.*\}", content_text, re.DOTALL)
            parsed = json.loads(json_match.group(0)) if json_match else {}

            full_text = parsed.get("full_summary_text", content_text)
            words = full_text.split()

            return ClinicalSummary(
                patient_id=patient_id,
                chief_concern=parsed.get("chief_concern", "Clinical evaluation"),
                key_diagnoses=parsed.get("key_diagnoses", []),
                recent_media_and_labs=parsed.get("recent_media_and_labs", []),
                flagged_anomalies=parsed.get("flagged_anomalies", []),
                full_summary_text=full_text,
                word_count=len(words),
                confidence_score=0.95,
                disclaimer=DEFAULT_DISCLAIMER,
                cached=False,
            )


class OpenAILLMClient(BaseLLMClient):
    """OpenAI API client."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def summarize(
        self,
        patient_id: str,
        patient_info: str,
        documents: List[str],
        diagnostics: List[str],
    ) -> ClinicalSummary:
        prompt = build_user_prompt(patient_info, documents, diagnostics)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": "gpt-4o-mini",
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": CLINICAL_SUMMARIZER_SYSTEM_PROMPT},
                {"role": "user", "content": CLINICAL_FEW_SHOT_EXAMPLE},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 800,
        }
        with httpx.Client(timeout=30.0) as client:
            resp = client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=body)
            resp.raise_for_status()
            res_json = resp.json()
            content_text = res_json["choices"][0]["message"]["content"]
            parsed = json.loads(content_text)

            full_text = parsed.get("full_summary_text", content_text)
            words = full_text.split()

            return ClinicalSummary(
                patient_id=patient_id,
                chief_concern=parsed.get("chief_concern", "Clinical evaluation"),
                key_diagnoses=parsed.get("key_diagnoses", []),
                recent_media_and_labs=parsed.get("recent_media_and_labs", []),
                flagged_anomalies=parsed.get("flagged_anomalies", []),
                full_summary_text=full_text,
                word_count=len(words),
                confidence_score=0.95,
                disclaimer=DEFAULT_DISCLAIMER,
                cached=False,
            )


class ClinicalSummarizer:
    """Orchestrates summary generation with prompt constraints, caching, and fallback providers."""

    def __init__(
        self,
        cache: Optional[SummaryCache] = None,
        llm_client: Optional[BaseLLMClient] = None,
    ):
        self.cache = cache or SummaryCache()

        if llm_client:
            self.client = llm_client
        elif settings.LLM_PROVIDER == "anthropic" and settings.ANTHROPIC_API_KEY:
            self.client = AnthropicLLMClient(settings.ANTHROPIC_API_KEY)
        elif settings.LLM_PROVIDER == "openai" and settings.OPENAI_API_KEY:
            self.client = OpenAILLMClient(settings.OPENAI_API_KEY)
        else:
            self.client = MockLLMClient()

    def summarize_patient(self, patient: CanonicalPatient) -> ClinicalSummary:
        """Summarize patient from CanonicalPatient model."""
        patient_info = f"Patient ID: {patient.patient_id}, MRN: {patient.mrn}, Name: {patient.full_name}, DOB: {patient.birth_date}, Gender: {patient.gender.value}"
        doc_texts = [f"{d.title} ({d.date}):\n{d.content}" for d in patient.documents]
        diag_texts = [f"{dg.test_name} ({dg.effective_date}):\n{dg.conclusion}" for dg in patient.diagnostics]

        content_for_hash = patient_info + "\n" + "\n".join(doc_texts + diag_texts)
        rec_hash = self.cache.compute_record_hash(content_for_hash)

        # Check Cache Hit
        cached = self.cache.get(patient.patient_id, rec_hash)
        if cached:
            return cached

        # Cache Miss: Call LLM
        summary = self.client.summarize(patient.patient_id, patient_info, doc_texts, diag_texts)
        # Enforce <200 words constraint
        if summary.word_count >= 200:
            words = summary.full_summary_text.split()[:190]
            summary.full_summary_text = " ".join(words) + "..."
            summary.word_count = len(words)

        self.cache.set(patient.patient_id, rec_hash, summary)
        return summary

    def summarize_bundle(self, bundle: Bundle, patient_id: str) -> ClinicalSummary:
        """Extract documents and diagnostic reports from a FHIR Bundle and summarize."""
        patient_info = f"Patient ID: {patient_id}"
        doc_texts = []
        diag_texts = []

        if bundle.entry:
            for entry in bundle.entry:
                res = entry.resource
                if not res:
                    continue
                res_type = getattr(res, "get_resource_type", lambda: getattr(res, "__resource_type__", ""))()
                if res_type == "Patient":
                    name = res.name[0].text if res.name else "Unknown"
                    patient_info = f"Patient: {name} (ID: {res.id}, Gender: {res.gender}, DOB: {res.birthDate})"
                elif res_type == "DocumentReference":
                    title = "Document"
                    content = ""
                    if res.content and res.content[0].attachment:
                        att = res.content[0].attachment
                        title = att.title or title
                        if att.data:
                            try:
                                content = base64.b64decode(att.data).decode("utf-8")
                            except Exception:
                                content = str(att.data)
                    doc_texts.append(f"{title}:\n{content}")
                elif res_type == "DiagnosticReport":
                    title = res.code.coding[0].display if res.code and res.code.coding else "Lab Report"
                    diag_texts.append(f"{title}:\n{res.conclusion or ''}")

        content_for_hash = patient_info + "\n" + "\n".join(doc_texts + diag_texts)
        rec_hash = self.cache.compute_record_hash(content_for_hash)

        cached = self.cache.get(patient_id, rec_hash)
        if cached:
            return cached

        summary = self.client.summarize(patient_id, patient_info, doc_texts, diag_texts)
        if summary.word_count >= 200:
            words = summary.full_summary_text.split()[:190]
            summary.full_summary_text = " ".join(words) + "..."
            summary.word_count = len(words)

        self.cache.set(patient_id, rec_hash, summary)
        return summary

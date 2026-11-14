/**
 * Clinician Dashboard Frontend Controller
 * Vanilla JS + Tailwind CSS for sub-second semantic search & patient intelligence
 */

let debounceTimer = null;
let currentPatientId = null;
let currentPatientData = null;
let currentBundleJSON = null;
let isAnonymized = false;
let lastSearchResults = [];
let lastSearchQuery = "";

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
  const searchInput = document.getElementById("search-input");

  // Real-time debounced search on input
  searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      executeSearch();
    }, 300);
  });

  // Enter key immediate execution
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      clearTimeout(debounceTimer);
      executeSearch();
    }
  });

  // Global keyboard shortcuts
  document.addEventListener("keydown", (e) => {
    // Press '/' to focus search bar
    if (e.key === "/" && document.activeElement !== searchInput) {
      e.preventDefault();
      searchInput.focus();
    }
    // Press 'Escape' to close drawer
    if (e.key === "Escape") {
      closeDrawer();
    }
  });

  // Setup drag and drop on drop-zone
  const dropZone = document.getElementById("drop-zone");
  if (dropZone) {
    ["dragenter", "dragover"].forEach((eventName) => {
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add("drag-active");
      });
    });

    ["dragleave", "drop"].forEach((eventName) => {
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove("drag-active");
      });
    });

    dropZone.addEventListener("drop", (e) => {
      const dt = e.dataTransfer;
      if (dt && dt.files && dt.files.length > 0) {
        uploadFiles(dt.files);
      }
    });
  }

  // Default query on first load to immediately showcase capabilities
  setQuery("uncontrolled diabetes with elevated HbA1c and peripheral neuropathy");
});

function toggleAnonymization() {
  const checkbox = document.getElementById("toggle-anonymize");
  if (checkbox) {
    checkbox.checked = !checkbox.checked;
    handleAnonymizationChange({ target: checkbox });
  }
}

function handleAnonymizationChange(event) {
  isAnonymized = event.target.checked;
  const label = document.getElementById("anonymize-label");
  const container = document.getElementById("anonymize-container");
  if (isAnonymized) {
    if (label) label.innerText = "PHI Masked";
    if (container) container.classList.add("bg-indigo-50", "border-indigo-400");
    showToast("Patient data presentation anonymized (HIPAA Safe Harbor).");
  } else {
    if (label) label.innerText = "Anonymize PHI";
    if (container) container.classList.remove("bg-indigo-50", "border-indigo-400");
    showToast("Original patient identifiers restored in presentation.");
  }

  // Re-render search results
  if (lastSearchResults.length > 0) {
    renderSearchResults(lastSearchResults, lastSearchQuery);
  }

  // Re-render drawer if open
  if (currentPatientId && currentPatientData) {
    renderDrawer(currentPatientData);
  }
}

function anonymizeName(name, patientId) {
  if (!isAnonymized) return name;
  return `Patient [${patientId}] (De-identified)`;
}

function anonymizeMRN(mrn) {
  if (!isAnonymized) return mrn;
  return "MRN:******";
}

function anonymizeDOB(dob) {
  if (!isAnonymized) return dob;
  if (!dob || dob.length < 4) return "XXXX-XX-XX";
  const year = dob.substring(0, 4);
  return `${year}-XX-XX`;
}

function anonymizeText(text, patientName, mrn) {
  if (!isAnonymized || !text) return text || "";
  let res = text;
  if (mrn) {
    const cleanMrn = mrn.replace(/^MRN:/i, "");
    res = res.replaceAll(mrn, "MRN:******").replaceAll(cleanMrn, "******");
  }
  if (patientName && patientName !== "Unknown") {
    const parts = patientName.split(/\s+/).filter((p) => p.length > 2);
    for (const p of parts) {
      const regex = new RegExp(`\\b${escapeRegex(p)}\\b`, "gi");
      res = res.replace(regex, "[PATIENT]");
    }
  }
  return res;
}

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlightQuery(text, query) {
  if (!text) return "";
  const escaped = escapeHtml(text);
  if (!query) return escaped;

  const stopWords = new Set([
    "with", "and", "or", "in", "the", "a", "an", "to", "for",
    "of", "on", "at", "by", "is", "was", "are", "from", "patient", "patients"
  ]);

  const terms = query
    .trim()
    .split(/\s+/)
    .map((t) => t.replace(/[^\w\s-]/g, "").trim())
    .filter((t) => t.length >= 2 && !stopWords.has(t.toLowerCase()));

  if (terms.length === 0) return escaped;

  const regex = new RegExp(`\\b(${terms.map(escapeRegex).join("|")})`, "gi");
  return escaped.replace(regex, '<mark class="bg-amber-200 text-amber-900 rounded px-1 py-0.5 font-medium">$1</mark>');
}

function showIngestionProgress(title = "Processing clinical records...") {
  const panel = document.getElementById("ingestion-stats-panel");
  const progressBar = document.getElementById("ingestion-progress-bar");
  const progressText = document.getElementById("progress-text");
  if (panel) panel.classList.remove("hidden");
  if (progressBar) progressBar.classList.remove("hidden");
  if (progressText) progressText.innerText = title;
}

function renderIngestionStats(stats) {
  const panel = document.getElementById("ingestion-stats-panel");
  const progressBar = document.getElementById("ingestion-progress-bar");
  if (panel) panel.classList.remove("hidden");
  if (progressBar) progressBar.classList.add("hidden");

  document.getElementById("stat-total").innerText = stats.total_ingested ?? 0;
  document.getElementById("stat-successful").innerText = stats.successful ?? 0;
  document.getElementById("stat-failed").innerText = stats.failed ?? 0;
  document.getElementById("stat-duplicates").innerText = stats.skipped_duplicates ?? 0;

  document.getElementById("stats-message").innerText = stats.message || "Ingestion complete.";
  document.getElementById("stats-indices").innerText = `Bundles: ${stats.bundles_stored ?? 0} · Vectors: ${stats.vectors_indexed ?? 0}`;

  const failuresBox = document.getElementById("failures-box");
  const failuresList = document.getElementById("failures-list");
  if (stats.failed > 0 && stats.failures && stats.failures.length > 0) {
    failuresBox.classList.remove("hidden");
    failuresList.innerHTML = stats.failures.map((f) => `<p class="font-mono">• ${escapeHtml(f)}</p>`).join("");
  } else {
    failuresBox.classList.add("hidden");
  }
}

function dismissStatsPanel() {
  const panel = document.getElementById("ingestion-stats-panel");
  if (panel) panel.classList.add("hidden");
}

function handleFileInput(event) {
  const files = event.target.files;
  if (files && files.length > 0) {
    uploadFiles(files);
  }
}

async function uploadFiles(fileList) {
  const formData = new FormData();
  let count = 0;
  for (let i = 0; i < fileList.length; i++) {
    const file = fileList[i];
    const ext = file.name.split(".").pop().toLowerCase();
    if (["json", "csv", "txt"].includes(ext)) {
      formData.append("files", file);
      count++;
    }
  }

  if (count === 0) {
    showToast("Please select valid EHR files (.json, .csv, .txt).");
    return;
  }

  const uploadStatus = document.getElementById("upload-status");
  if (uploadStatus) {
    uploadStatus.innerText = `Uploading ${count} file(s)...`;
    uploadStatus.classList.remove("hidden");
  }

  showIngestionProgress(`Uploading & parsing ${count} file(s)...`);
  showToast(`Uploading ${count} clinical file(s) for ingestion...`);

  try {
    const resp = await fetch("/upload", {
      method: "POST",
      body: formData,
    });

    if (!resp.ok) {
      throw new Error(`Upload failed with HTTP ${resp.status}`);
    }

    const res = await resp.json();
    renderIngestionStats(res);
    showToast(`Ingestion complete! ${res.successful} successful, ${res.failed} failed, ${res.skipped_duplicates} duplicate(s) skipped.`);
    executeSearch();
  } catch (err) {
    showToast(`Upload error: ${err.message}`);
  } finally {
    if (uploadStatus) {
      uploadStatus.classList.add("hidden");
    }
    const input = document.getElementById("file-upload-input");
    if (input) input.value = "";
  }
}

function setQuery(text) {
  const input = document.getElementById("search-input");
  input.value = text;
  input.focus();
  executeSearch();
}

function resetFilters() {
  document.getElementById("filter-resource-type").value = "";
  document.getElementById("filter-date-from").value = "";
  document.getElementById("filter-date-to").value = "";
  executeSearch();
  showToast("Filters reset to default.");
}

async function executeSearch() {
  const query = document.getElementById("search-input").value.trim();
  const resourceType = document.getElementById("filter-resource-type").value;
  const dateFrom = document.getElementById("filter-date-from").value;
  const dateTo = document.getElementById("filter-date-to").value;

  const initialState = document.getElementById("initial-state");
  const loading = document.getElementById("loading-skeletons");
  const resultsList = document.getElementById("results-list");
  const matchSummary = document.getElementById("match-summary");
  const latencyBadge = document.getElementById("latency-badge");

  lastSearchQuery = query;

  if (!query) {
    lastSearchResults = [];
    if (initialState) initialState.classList.remove("hidden");
    resultsList.innerHTML = "";
    matchSummary.innerText = "Ready for query. Press Enter or click Search.";
    latencyBadge.classList.add("hidden");
    return;
  }

  // Show loading state
  if (initialState) initialState.classList.add("hidden");
  loading.classList.remove("hidden");
  resultsList.innerHTML = "";
  matchSummary.innerText = "Searching clinical vector database...";
  latencyBadge.classList.add("hidden");

  try {
    const payload = {
      query: query,
      resource_type: resourceType || null,
      date_from: dateFrom || null,
      date_to: dateTo || null,
      top_k: 5,
    };

    const resp = await fetch("/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      throw new Error(`Server returned HTTP ${resp.status}`);
    }

    const data = await resp.json();
    loading.classList.add("hidden");

    // Latency badge
    latencyBadge.innerText = `${data.execution_time_ms} ms`;
    latencyBadge.classList.remove("hidden");

    lastSearchResults = data.results || [];

    if (lastSearchResults.length === 0) {
      matchSummary.innerText = "No clinical matches found for the current query and filters.";
      resultsList.innerHTML = `
        <div class="text-center py-10 bg-white rounded-xl border border-slate-200 p-6">
          <p class="text-sm font-semibold text-slate-700">No records matched your criteria.</p>
          <p class="text-xs text-slate-500 mt-1">Try broadening your search terms or clearing the resource type and date filters.</p>
        </div>
      `;
      return;
    }

    matchSummary.innerText = `Top ${lastSearchResults.length} ranked matches across EHR records`;
    renderSearchResults(lastSearchResults, query);
  } catch (err) {
    loading.classList.add("hidden");
    matchSummary.innerText = "Search query failed.";
    resultsList.innerHTML = `
      <div class="bg-rose-50 border border-rose-200 text-rose-800 p-4 rounded-xl text-xs">
        <p class="font-bold">Error executing search request:</p>
        <p class="mt-1">${escapeHtml(err.message)}</p>
      </div>
    `;
  }
}

function renderSearchResults(results, query) {
  const resultsList = document.getElementById("results-list");
  if (!resultsList) return;

  resultsList.innerHTML = results
    .map((item) => {
      const isDiag = item.resource_type === "DiagnosticReport";
      const badgeColor = isDiag ? "bg-purple-100 text-purple-800" : "bg-indigo-100 text-indigo-800";
      const scorePercent = Math.round(item.relevance_score * 100);

      const displayName = anonymizeName(item.patient_name, item.patient_id);
      const displayMRN = anonymizeMRN(item.mrn);
      const displayTitle = highlightQuery(item.title, query);
      const rawSummary = anonymizeText(item.summary_snippet, item.patient_name, item.mrn);
      const displaySummary = highlightQuery(rawSummary, query);
      const rawExcerpt = anonymizeText(item.document_excerpt, item.patient_name, item.mrn);
      const displayExcerpt = highlightQuery(rawExcerpt, query);

      return `
      <article
        tabindex="0"
        onkeydown="if(event.key==='Enter') openPatientDrawer('${item.patient_id}')"
        class="result-card bg-white rounded-xl border border-slate-200 p-5 shadow-sm hover:border-indigo-300 hover:shadow-md cursor-pointer transition-all space-y-3"
        onclick="openPatientDrawer('${item.patient_id}')"
        aria-label="Result for ${escapeHtml(displayName)}"
      >
        <div class="flex items-start justify-between gap-4">
          <div>
            <div class="flex items-center space-x-2">
              <span class="text-sm font-bold text-slate-900 patient-card-name">${escapeHtml(displayName)}</span>
              <span class="px-2 py-0.5 rounded text-[10px] font-mono font-semibold bg-slate-100 text-slate-700 patient-card-mrn">${escapeHtml(displayMRN)}</span>
              <span class="px-2 py-0.5 rounded text-[10px] font-semibold ${badgeColor}">${escapeHtml(item.resource_type)}</span>
            </div>
            <p class="text-xs text-slate-500 mt-0.5">Record Date: <span class="font-medium text-slate-700">${escapeHtml(item.record_date)}</span> · Record ID: ${escapeHtml(item.record_id)}</p>
          </div>
          
          <!-- Relevance Score Pill -->
          <div class="flex flex-col items-end flex-shrink-0">
            <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${scorePercent >= 80 ? 'bg-emerald-100 text-emerald-800' : 'bg-blue-100 text-blue-800'}">
              ${scorePercent}% Match
            </span>
            <div class="w-16 bg-slate-100 rounded-full h-1.5 mt-1 overflow-hidden">
              <div class="h-1.5 rounded-full ${scorePercent >= 80 ? 'bg-emerald-500' : 'bg-blue-500'}" style="width: ${scorePercent}%"></div>
            </div>
          </div>
        </div>

        <!-- Title and Summary -->
        <div>
          <h4 class="text-xs font-bold text-slate-800">${displayTitle}</h4>
          <p class="text-xs text-slate-600 mt-1 leading-relaxed bg-slate-50/80 p-2 rounded border border-slate-100">
            <span class="font-semibold text-indigo-700">Clinical Summary:</span> ${displaySummary}
          </p>
        </div>

        <!-- Excerpt -->
        <p class="text-xs text-slate-500 line-clamp-2 italic">
          "${displayExcerpt}"
        </p>

        <div class="flex items-center justify-between pt-1 border-t border-slate-100 text-[11px]">
          <span class="text-slate-400">Click card or press Enter to inspect full patient file</span>
          <span class="text-indigo-600 font-semibold flex items-center hover:text-indigo-800">
            View Patient Record &rarr;
          </span>
        </div>
      </article>
    `;
    })
    .join("");
}

async function openPatientDrawer(patientId) {
  currentPatientId = patientId;
  const drawer = document.getElementById("patient-drawer");
  drawer.classList.remove("hidden");

  // Reset fields
  document.getElementById("drawer-patient-name").innerText = "Loading...";
  document.getElementById("drawer-mrn-badge").innerText = "";
  document.getElementById("drawer-demographics").innerText = "";
  document.getElementById("drawer-chief-concern").innerText = "Loading clinical summary...";
  document.getElementById("drawer-diagnoses-list").innerHTML = "";
  document.getElementById("drawer-anomalies-list").innerHTML = "";
  document.getElementById("drawer-full-narrative").innerText = "";
  document.getElementById("drawer-disclaimer").innerText = "";
  document.getElementById("drawer-records-list").innerHTML = "";
  document.getElementById("drawer-audit-table").innerHTML = "";
  document.getElementById("raw-fhir-container").classList.add("hidden");

  try {
    const resp = await fetch(`/patients/${encodeURIComponent(patientId)}`);
    if (!resp.ok) throw new Error("Failed to load patient dossier");
    const p = await resp.json();
    currentPatientData = p;

    renderDrawer(p);

    // Prefetch raw FHIR Bundle JSON
    const fhirResp = await fetch(`/bundles/${encodeURIComponent(patientId)}`);
    if (fhirResp.ok) {
      const fhirData = await fhirResp.json();
      currentBundleJSON = typeof fhirData === "string" ? JSON.stringify(JSON.parse(fhirData), null, 2) : JSON.stringify(fhirData, null, 2);
      renderRawFHIR();
    }
  } catch (err) {
    showToast(`Error loading dossier: ${err.message}`);
  }
}

function renderDrawer(p) {
  const query = lastSearchQuery;
  const displayName = anonymizeName(p.name, p.patient_id);
  const displayMRN = anonymizeMRN(p.mrn);
  const displayDOB = anonymizeDOB(p.birth_date);

  // Demographics
  document.getElementById("drawer-patient-name").innerText = displayName;
  document.getElementById("drawer-mrn-badge").innerText = displayMRN;
  document.getElementById("drawer-demographics").innerText = `DOB: ${displayDOB} · Gender: ${p.gender} · ID: ${p.patient_id}`;

  // Structured Summary
  const s = p.summary;
  const chief = anonymizeText(s.chief_concern, p.name, p.mrn);
  document.getElementById("drawer-chief-concern").innerHTML = highlightQuery(chief, query);
  document.getElementById("drawer-confidence-badge").innerText = `Confidence: ${Math.round(s.confidence_score * 100)}%`;

  const narrative = anonymizeText(s.full_summary_text, p.name, p.mrn);
  document.getElementById("drawer-full-narrative").innerHTML = highlightQuery(narrative, query);
  document.getElementById("drawer-disclaimer").innerText = s.disclaimer;

  // Active Diagnoses Pills
  const diagList = document.getElementById("drawer-diagnoses-list");
  diagList.innerHTML = (s.key_diagnoses || [])
    .map((d) => `<span class="px-2 py-0.5 rounded text-[11px] font-semibold bg-indigo-100 text-indigo-800">${highlightQuery(d, query)}</span>`)
    .join("");

  // Flagged Anomalies
  const anomBox = document.getElementById("drawer-anomalies-box");
  const anomList = document.getElementById("drawer-anomalies-list");
  if (s.flagged_anomalies && s.flagged_anomalies.length > 0) {
    anomBox.classList.remove("hidden");
    anomList.innerHTML = s.flagged_anomalies
      .map((a) => `<p class="mt-0.5">• ${highlightQuery(anonymizeText(a, p.name, p.mrn), query)}</p>`)
      .join("");
  } else {
    anomBox.classList.add("hidden");
  }

  // Linked Records
  const recordsList = document.getElementById("drawer-records-list");
  const allRecords = [
    ...(p.documents || []).map((doc) => ({
      type: "DocumentReference",
      title: doc.title,
      date: doc.date,
      content: doc.content,
    })),
    ...(p.diagnostics || []).map((dg) => ({
      type: "DiagnosticReport",
      title: dg.test_name,
      date: dg.effective_date,
      content: dg.conclusion,
    })),
  ];

  recordsList.innerHTML = allRecords
    .map((r) => {
      const isDiag = r.type === "DiagnosticReport";
      const maskedContent = anonymizeText(r.content, p.name, p.mrn);
      return `
      <div class="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs space-y-1">
        <div class="flex items-center justify-between">
          <span class="font-bold text-slate-800">${highlightQuery(r.title, query)}</span>
          <span class="px-1.5 py-0.5 rounded text-[10px] font-semibold ${isDiag ? 'bg-purple-100 text-purple-800' : 'bg-indigo-100 text-indigo-800'}">${escapeHtml(r.type)}</span>
        </div>
        <p class="text-[11px] text-slate-500">Date: ${escapeHtml(r.date)}</p>
        <p class="text-slate-700 whitespace-pre-line mt-1 bg-white p-2 rounded border border-slate-100">${highlightQuery(maskedContent, query)}</p>
      </div>
    `;
    })
    .join("");

  // Ingestion Audit Trail Table
  const auditTable = document.getElementById("drawer-audit-table");
  if (p.audit_log && p.audit_log.length > 0) {
    auditTable.innerHTML = p.audit_log
      .map(
        (entry) => `
      <tr class="hover:bg-slate-50">
        <td class="px-3 py-2 font-mono font-semibold text-indigo-600">${escapeHtml(entry.field_name)}</td>
        <td class="px-3 py-2 text-rose-600 font-mono">${escapeHtml(isAnonymized && entry.field_name === "patient_name" ? "********" : String(entry.original_value))}</td>
        <td class="px-3 py-2 text-emerald-600 font-mono">${escapeHtml(isAnonymized && entry.field_name === "patient_name" ? "********" : String(entry.cleaned_value))}</td>
        <td class="px-3 py-2 text-slate-500">${escapeHtml(entry.transformation_rule)}</td>
      </tr>
    `
      )
      .join("");
  } else {
    auditTable.innerHTML = `<tr><td colspan="4" class="px-3 py-2 text-center text-slate-400">No modifications required; record already clean.</td></tr>`;
  }

  renderRawFHIR();
}

function renderRawFHIR() {
  if (!currentBundleJSON) return;
  const rawContainer = document.getElementById("raw-fhir-json");
  if (!rawContainer) return;

  if (!isAnonymized || !currentPatientData) {
    rawContainer.innerText = currentBundleJSON;
    return;
  }

  // De-identify raw FHIR JSON for presentation
  try {
    const bundleObj = JSON.parse(currentBundleJSON);
    if (bundleObj.entry) {
      for (const ent of bundleObj.entry) {
        const res = ent.resource;
        if (res && res.resourceType === "Patient") {
          res.name = [{ family: "DE-IDENTIFIED", given: ["PATIENT"] }];
          res.identifier = [{ system: "http://hospital.smarthealth.org/mrn", value: "MRN:******" }];
          if (res.birthDate && res.birthDate.length >= 4) {
            res.birthDate = `${res.birthDate.substring(0, 4)}-XX-XX`;
          }
        }
      }
    }
    rawContainer.innerText = JSON.stringify(bundleObj, null, 2);
  } catch {
    rawContainer.innerText = currentBundleJSON;
  }
}

function closeDrawer() {
  document.getElementById("patient-drawer").classList.add("hidden");
  currentPatientId = null;
  currentPatientData = null;
  currentBundleJSON = null;
}

function toggleRawFHIR() {
  const container = document.getElementById("raw-fhir-container");
  container.classList.toggle("hidden");
}

function copyFHIRJSON() {
  if (!currentBundleJSON) return;
  const text = document.getElementById("raw-fhir-json").innerText;
  navigator.clipboard.writeText(text).then(() => {
    showToast(isAnonymized ? "Anonymized FHIR R4 Bundle copied to clipboard!" : "FHIR R4 Bundle copied to clipboard!");
  });
}

async function triggerIngest() {
  const btn = document.getElementById("btn-reingest");
  const spinner = document.getElementById("ingest-spinner");
  const icon = document.getElementById("ingest-icon");

  spinner.classList.remove("hidden");
  icon.classList.add("hidden");
  btn.disabled = true;

  showIngestionProgress("Scanning directory & rebuilding FHIR indexes...");

  try {
    const resp = await fetch("/ingest", { method: "POST" });
    if (!resp.ok) {
      throw new Error(`Ingest failed with HTTP ${resp.status}`);
    }
    const res = await resp.json();
    renderIngestionStats(res);
    showToast(`Ingestion complete! ${res.successful} successful, ${res.failed} failed, ${res.skipped_duplicates} duplicate(s) skipped.`);
    executeSearch();
  } catch (err) {
    showToast(`Ingestion error: ${err.message}`);
  } finally {
    spinner.classList.add("hidden");
    icon.classList.remove("hidden");
    btn.disabled = false;
  }
}

function showToast(message) {
  const toast = document.getElementById("toast");
  const msg = document.getElementById("toast-message");
  msg.innerText = message;
  toast.classList.remove("translate-y-20", "opacity-0", "pointer-events-none");
  setTimeout(() => {
    toast.classList.add("translate-y-20", "opacity-0", "pointer-events-none");
  }, 3500);
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}



/* ═══════════════════════════════════════════════════════════
   Compliance Vision — Local UI v2
   Dashboard-first SPA with pipeline progress & live monitoring
   ═══════════════════════════════════════════════════════════ */
(function () {

"use strict";

/* ─── State ──────────────────────────────────────────────── */
const state = {
    cameraOn: false,
    monitoring: false,
    stream: null,
    recorder: null,
    ws: null,
    chunks: [],
    clipNum: 0,
    sessionStart: null,
    timerInterval: null,
    totalIncidents: 0,
    clipsAnalyzed: 0,
    lastStatus: "---",
    history: [],
    config: {},
    pipeline: "idle", // idle | recording | converting | uploading | analyzing | complete | error
    rawJsonVisible: false,
};

/* ─── DOM refs ───────────────────────────────────────────── */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const el = {
    // header
    connBadge:       $("#connectionBadge"),
    connDot:         $("#connectionBadge .conn-dot"),
    connText:        $("#connectionBadge .conn-text"),
    // stats
    complianceStatus:$("#complianceStatus"),
    totalIncidents:  $("#totalIncidents"),
    clipsAnalyzed:   $("#clipsAnalyzed"),
    sessionTime:     $("#sessionTime"),
    // video
    videoWrapper:    $("#videoWrapper"),
    webcamVideo:     $("#webcamVideo"),
    captureCanvas:   $("#captureCanvas"),
    videoOverlay:    $("#videoOverlay"),
    videoPlaceholder:$("#videoPlaceholder"),
    recBadge:        $("#recBadge"),
    clipBadge:       $("#clipBadge"),
    // controls
    btnCamera:       $("#btnCamera"),
    btnMonitor:      $("#btnMonitor"),
    btnCapture:      $("#btnCapture"),
    btnUploadVideo:  $("#btnUploadVideo"),
    fileInput:       $("#fileInput"),
    // pipeline
    pipelineSteps:   $("#pipelineSteps"),
    // result
    resultEmpty:     $("#resultEmpty"),
    resultContent:   $("#resultContent"),
    resultBadge:     $("#resultBadge"),
    resultPeople:    $("#resultPeople"),
    resultTs:        $("#resultTs"),
    resultDetails:   $("#resultDetails"),
    btnRawToggle:    $("#btnRawToggle"),
    rawJson:         $("#rawJson"),
    // history
    historyList:     $("#historyList"),
    btnClearHistory: $("#btnClearHistory"),
    // settings
    sparkIp:         $("#sparkIp"),
    proxyPort:       $("#proxyPort"),
    endpointPath:    $("#endpointPath"),
    modelId:         $("#modelId"),
    maxTokens:       $("#maxTokens"),
    temperature:     $("#temperature"),
    clipDuration:    $("#clipDuration"),
    fps:             $("#fps"),
    autoAnalyze:     $("#autoAnalyze"),
    promptText:      $("#promptText"),
    btnSaveAll:      $("#btnSaveAll"),
    btnResetAll:     $("#btnResetAll"),
    btnTestConn:     $("#btnTestConn"),
    // toast
    toastContainer:  $("#toastContainer"),
};

/* ─── Prompt Templates ───────────────────────────────────── */
const TEMPLATES = {
    badge: `You are a security camera AI for TreeHacks 2026 hackathon at Stanford University.

THE OFFICIAL TREEHACKS BADGE:
- A Christmas tree / pine tree shaped green PCB (printed circuit board)
- Has "TREE HACKS" and "2026" text in white
- Has a rocket ship, stars, and planet graphics
- Has a QR code, LEDs, and USB-C connectors
- Worn around neck or held in hand

JOB: For each person in the video, determine if they have a TreeHacks badge or not.

RESPOND IN THIS EXACT JSON FORMAT:
{
  "people_count": <number>,
  "people": [
    {
      "person": "Person 1",
      "facing_camera": true or false,
      "badge_visible": true or false,
      "description": "brief appearance description"
    }
  ]
}

RULES:
- If a person is NOT facing the camera, set facing_camera to false and badge_visible to false.
- Only set badge_visible to true if you can clearly see the TreeHacks PCB badge.
- If no people are visible, return: {"people_count": 0, "people": []}
- Return ONLY the JSON, no other text.`,

    safety: `You are a safety compliance AI monitoring a workplace. Analyze the video feed for PPE (Personal Protective Equipment) compliance.

Check for: hard hats, safety vests, safety glasses, gloves, steel-toe boots, ear protection.

RESPOND IN THIS EXACT JSON FORMAT:
{
  "people_count": <number>,
  "people": [
    {
      "person": "Person 1",
      "ppe_items": ["hard hat", "safety vest"],
      "missing_items": ["safety glasses"],
      "compliant": false,
      "description": "brief description"
    }
  ]
}
Return ONLY the JSON, no other text.`,

    crowd: `You are a crowd monitoring AI. Analyze the video for crowd density and behavior.

RESPOND IN THIS EXACT JSON FORMAT:
{
  "people_count": <number>,
  "density": "low" | "medium" | "high" | "overcrowded",
  "concerns": ["list any safety concerns"],
  "description": "brief scene description"
}
Return ONLY the JSON, no other text.`,

    general: `Analyze this video feed and describe what you see in detail.

RESPOND IN THIS EXACT JSON FORMAT:
{
  "scene_description": "detailed description of the scene",
  "objects": ["list of notable objects"],
  "people_count": <number>,
  "activity": "description of any activity",
  "concerns": ["list any concerns or notable observations"]
}
Return ONLY the JSON, no other text.`,
};

/* ─── Toast Notifications ────────────────────────────────── */
function toast(msg, type = "info", duration = 3500) {
    const icons = { success: "✓", error: "✕", info: "ℹ" };
    const t = document.createElement("div");
    t.className = `toast ${type}`;
    t.innerHTML = `<span class="toast-icon">${icons[type] || icons.info}</span>${msg}`;
    el.toastContainer.appendChild(t);
    setTimeout(() => {
        t.style.animation = "slideOut 0.25s ease";
        setTimeout(() => t.remove(), 250);
    }, duration);
}

/* ─── SPA Navigation ─────────────────────────────────────── */
$$(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
        const page = btn.dataset.page;
        $$(".nav-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        $$(".page").forEach((p) => p.classList.remove("active"));
        $(`#page-${page}`).classList.add("active");
    });
});

/* ─── Connection Check ───────────────────────────────────── */
async function checkConnection() {
    el.connDot.className = "conn-dot check";
    el.connText.textContent = "Checking...";
    try {
        const r = await fetch("/api/connection");
        const data = await r.json();
        if (data.connected) {
            el.connDot.className = "conn-dot ok";
            el.connText.textContent = "Connected";
        } else {
            el.connDot.className = "conn-dot fail";
            el.connText.textContent = "Offline";
        }
        return data.connected;
    } catch {
        el.connDot.className = "conn-dot fail";
        el.connText.textContent = "Error";
        return false;
    }
}

/* ─── Config Management ──────────────────────────────────── */
async function loadConfig() {
    try {
        const r = await fetch("/api/config");
        state.config = await r.json();
        populateSettings(state.config);
    } catch (e) {
        console.error("Failed to load config", e);
    }
}

function populateSettings(c) {
    el.sparkIp.value = c.spark_ip || "";
    el.proxyPort.value = c.proxy_port || "";
    el.endpointPath.value = c.endpoint_path || "";
    el.modelId.value = c.model_id || "";
    el.maxTokens.value = c.max_tokens || 2048;
    el.temperature.value = c.temperature || 0.6;
    el.clipDuration.value = c.clip_duration || 3;
    el.fps.value = c.fps || 4;
    el.autoAnalyze.checked = c.auto_analyze !== false;
    el.promptText.value = c.prompt || "";
}

function gatherSettings() {
    return {
        spark_ip: el.sparkIp.value.trim(),
        proxy_port: parseInt(el.proxyPort.value) || 8001,
        endpoint_path: el.endpointPath.value.trim(),
        model_id: el.modelId.value.trim(),
        max_tokens: parseInt(el.maxTokens.value) || 2048,
        temperature: parseFloat(el.temperature.value) || 0.6,
        clip_duration: parseInt(el.clipDuration.value) || 3,
        fps: parseInt(el.fps.value) || 4,
        auto_analyze: el.autoAnalyze.checked,
        prompt: el.promptText.value,
    };
}

async function saveSettings() {
    const body = gatherSettings();
    try {
        const r = await fetch("/api/config", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        const data = await r.json();
        state.config = data.config;
        toast("Settings saved", "success");
    } catch (e) {
        toast("Failed to save settings", "error");
    }
}

async function resetSettings() {
    try {
        const r = await fetch("/api/config/reset", { method: "POST" });
        const data = await r.json();
        state.config = data.config;
        populateSettings(data.config);
        toast("Defaults restored", "success");
    } catch (e) {
        toast("Failed to reset settings", "error");
    }
}

/* ─── Session Timer ──────────────────────────────────────── */
function startTimer() {
    state.sessionStart = Date.now();
    state.timerInterval = setInterval(updateTimer, 1000);
}

function stopTimer() {
    clearInterval(state.timerInterval);
    state.timerInterval = null;
}

function updateTimer() {
    if (!state.sessionStart) return;
    const elapsed = Math.floor((Date.now() - state.sessionStart) / 1000);
    const m = String(Math.floor(elapsed / 60)).padStart(2, "0");
    const s = String(elapsed % 60).padStart(2, "0");
    el.sessionTime.textContent = `${m}:${s}`;
}

/* ─── Pipeline Step Management ───────────────────────────── */
function setPipeline(step) {
    state.pipeline = step;
    const steps = ["recording", "converting", "uploading", "analyzing", "complete"];
    const stepIndex = steps.indexOf(step);

    $$(".p-step").forEach((el) => {
        const s = el.dataset.step;
        const i = steps.indexOf(s);
        el.classList.remove("idle", "active", "done", "error");
        if (step === "idle" || step === "error") {
            el.classList.add("idle");
        } else if (i < stepIndex) {
            el.classList.add("done");
        } else if (i === stepIndex) {
            el.classList.add("active");
        } else {
            el.classList.add("idle");
        }
    });

    // If complete, mark all done
    if (step === "complete") {
        $$(".p-step").forEach((el) => {
            el.classList.remove("idle", "active");
            el.classList.add("done");
        });
    }
}

/* ─── Stats Update ───────────────────────────────────────── */
function updateStats() {
    el.complianceStatus.textContent = state.lastStatus;
    el.totalIncidents.textContent = state.totalIncidents;
    el.clipsAnalyzed.textContent = state.clipsAnalyzed;
}

/* ─── Camera ─────────────────────────────────────────────── */
async function startCamera() {
    try {
        state.stream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "environment" },
            audio: false,
        });
        el.webcamVideo.srcObject = state.stream;
        el.webcamVideo.classList.add("active");
        el.videoPlaceholder.classList.add("hidden");
        el.videoOverlay.classList.add("active");
        state.cameraOn = true;
        el.btnCamera.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="1" y1="1" x2="23" y2="23"/><path d="M21 21H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h3m3-3h6l2 3h4a2 2 0 0 1 2 2v9.34m-7.72-2.06a4 4 0 1 1-5.56-5.56"/></svg> Stop Camera`;
        el.btnMonitor.disabled = false;
        el.btnCapture.disabled = false;
        toast("Camera started", "success");
    } catch (e) {
        toast("Camera access denied: " + e.message, "error");
    }
}

function stopCamera() {
    if (state.monitoring) stopMonitoring();
    if (state.stream) {
        state.stream.getTracks().forEach((t) => t.stop());
        state.stream = null;
    }
    el.webcamVideo.classList.remove("active");
    el.webcamVideo.srcObject = null;
    el.videoPlaceholder.classList.remove("hidden");
    el.videoOverlay.classList.remove("active");
    state.cameraOn = false;
    el.btnCamera.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg> Start Camera`;
    el.btnMonitor.disabled = true;
    el.btnCapture.disabled = true;
}

/* ─── Recording / Capture ────────────────────────────────── */
function captureClip() {
    if (!state.cameraOn || !state.stream) return;
    const duration = (state.config.clip_duration || 3) * 1000;

    state.clipNum++;
    el.clipBadge.textContent = `Clip #${state.clipNum}`;
    el.recBadge.classList.add("on");
    setPipeline("recording");

    state.chunks = [];
    const mimeType = MediaRecorder.isTypeSupported("video/webm;codecs=vp9") ? "video/webm;codecs=vp9" : "video/webm";
    state.recorder = new MediaRecorder(state.stream, { mimeType });
    state.recorder.ondataavailable = (e) => { if (e.data.size > 0) state.chunks.push(e.data); };
    state.recorder.onstop = () => handleClipReady();
    state.recorder.start();

    setTimeout(() => {
        if (state.recorder && state.recorder.state === "recording") {
            state.recorder.stop();
        }
    }, duration);
}

async function handleClipReady() {
    el.recBadge.classList.remove("on");
    setPipeline("converting");

    const blob = new Blob(state.chunks, { type: "video/webm" });
    const reader = new FileReader();
    reader.onloadend = async () => {
        const b64 = reader.result.split(",")[1];
        await sendForAnalysis(b64);
    };
    reader.readAsDataURL(blob);
}

/* ─── Analysis ───────────────────────────────────────────── */
async function sendForAnalysis(videoB64) {
    setPipeline("uploading");

    try {
        setPipeline("analyzing");

        const r = await fetch("/api/analyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video_base64: videoB64 }),
        });

        if (!r.ok) {
            const err = await r.json().catch(() => ({ detail: r.statusText }));
            throw new Error(err.detail || "Analysis failed");
        }

        const report = await r.json();
        setPipeline("complete");
        handleReport(report);

        // Auto-continue?
        if (state.monitoring && state.config.auto_analyze !== false) {
            setTimeout(() => {
                if (state.monitoring) {
                    setPipeline("idle");
                    captureClip();
                }
            }, 1500);
        } else {
            setTimeout(() => setPipeline("idle"), 3000);
        }
    } catch (e) {
        setPipeline("idle");
        toast("Analysis error: " + e.message, "error");
        // Auto-retry if monitoring
        if (state.monitoring) {
            setTimeout(() => {
                if (state.monitoring) captureClip();
            }, 3000);
        }
    }
}

/* ─── Handle Analysis Report ─────────────────────────────── */
function handleReport(report) {
    state.clipsAnalyzed++;

    // Try to parse the model's content from the raw DGX response
    let parsed = null;
    try {
        if (report.raw && report.raw.choices && report.raw.choices[0]) {
            const content = report.raw.choices[0].message.content;
            // Try to extract JSON from the content
            const jsonMatch = content.match(/\{[\s\S]*\}/);
            if (jsonMatch) {
                parsed = JSON.parse(jsonMatch[0]);
            }
        }
    } catch (e) {
        console.warn("Could not parse model response as JSON:", e);
    }

    // Determine compliance
    let compliant = true;
    let incidentCount = 0;

    if (parsed) {
        if (parsed.people && Array.isArray(parsed.people)) {
            parsed.people.forEach((p) => {
                if (p.badge_visible === false && p.facing_camera === true) {
                    compliant = false;
                    incidentCount++;
                }
                if (p.compliant === false) {
                    compliant = false;
                    incidentCount++;
                }
            });
        }
        // For violation-based responses
        if (report.violation_count > 0) {
            compliant = false;
            incidentCount = Math.max(incidentCount, report.violation_count);
        }
    }

    // Update stats
    state.totalIncidents += incidentCount;
    state.lastStatus = compliant ? "Compliant" : "Violation";
    updateStats();

    // Stat card color feedback
    const statusEl = el.complianceStatus;
    statusEl.style.color = compliant ? "var(--green)" : "var(--red)";

    // Show result
    el.resultEmpty.style.display = "none";
    el.resultContent.style.display = "block";
    el.resultBadge.textContent = compliant ? "COMPLIANT" : "VIOLATION";
    el.resultBadge.className = `result-badge ${compliant ? "ok" : "bad"}`;
    el.resultTs.textContent = report.timestamp || new Date().toLocaleTimeString();

    // Populate details
    let detailsHTML = "";

    if (parsed && parsed.people && Array.isArray(parsed.people)) {
        el.resultPeople.textContent = `${parsed.people_count || parsed.people.length} person(s) detected`;
        parsed.people.forEach((p) => {
            const icon = p.facing_camera ? "👤" : "🔄";
            let badgeClass = "na", badgeText = "N/A";
            if (p.facing_camera && p.badge_visible === true) { badgeClass = "yes"; badgeText = "Badge ✓"; }
            else if (p.facing_camera && p.badge_visible === false) { badgeClass = "no"; badgeText = "No Badge"; }
            else if (p.compliant === true) { badgeClass = "yes"; badgeText = "Compliant"; }
            else if (p.compliant === false) { badgeClass = "no"; badgeText = "Non-Compliant"; }

            detailsHTML += `
                <div class="person-row">
                    <span class="person-icon">${icon}</span>
                    <div class="person-info">
                        <div class="person-name">${p.person || "Person"}</div>
                        <div class="person-desc">${p.description || ""}</div>
                    </div>
                    <span class="person-badge ${badgeClass}">${badgeText}</span>
                </div>`;
        });
    } else if (parsed) {
        el.resultPeople.textContent = `${parsed.people_count || 0} person(s)`;
        if (parsed.scene_description) {
            detailsHTML += `<p style="font-size:12px;color:var(--text-2);margin-bottom:8px">${parsed.scene_description}</p>`;
        }
        if (parsed.concerns && parsed.concerns.length) {
            parsed.concerns.forEach((c) => {
                detailsHTML += `
                    <div class="violation-row">
                        <div class="violation-rule">${c}</div>
                    </div>`;
            });
        }
    } else {
        // Raw text fallback
        el.resultPeople.textContent = "";
        let rawText = "";
        try {
            rawText = report.raw?.choices?.[0]?.message?.content || JSON.stringify(report.raw, null, 2);
        } catch { rawText = JSON.stringify(report, null, 2); }
        detailsHTML = `<pre class="raw-json" style="display:block;max-height:250px">${escapeHtml(rawText)}</pre>`;
    }

    el.resultDetails.innerHTML = detailsHTML;

    // Raw JSON
    el.rawJson.textContent = JSON.stringify(report.raw || report, null, 2);

    // Add to history
    addHistoryItem(report, compliant, parsed);

    toast(compliant ? "Compliant ✓" : `${incidentCount} violation(s) detected`, compliant ? "success" : "error");
}

/* ─── History ────────────────────────────────────────────── */
function addHistoryItem(report, compliant, parsed) {
    const item = { report, compliant, parsed, time: new Date().toLocaleTimeString() };
    state.history.unshift(item);
    if (state.history.length > 50) state.history.pop();
    renderHistory();
}

function renderHistory() {
    if (state.history.length === 0) {
        el.historyList.innerHTML = `<div class="empty-hint"><span class="muted">Results appear here during monitoring</span></div>`;
        return;
    }
    el.historyList.innerHTML = state.history.map((h, i) => {
        const people = h.parsed?.people_count || h.parsed?.people?.length || "?";
        return `
        <div class="h-item" data-idx="${i}">
            <div>
                <span class="h-badge ${h.compliant ? "ok" : "bad"}">${h.compliant ? "OK" : "ALERT"}</span>
                <span class="h-info">${people} person(s)</span>
            </div>
            <span class="h-time">${h.time}</span>
        </div>`;
    }).join("");

    // Click to view
    $$(".h-item").forEach((item) => {
        item.addEventListener("click", () => {
            const idx = parseInt(item.dataset.idx);
            const h = state.history[idx];
            if (h) handleReport(h.report);
        });
    });
}

/* ─── Monitoring ─────────────────────────────────────────── */
function startMonitoring() {
    state.monitoring = true;
    startTimer();
    el.btnMonitor.classList.add("monitoring");
    el.btnMonitor.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="6" width="12" height="12"/></svg> Stop Monitoring`;
    toast("Monitoring started", "info");
    captureClip();
}

function stopMonitoring() {
    state.monitoring = false;
    stopTimer();
    if (state.recorder && state.recorder.state === "recording") {
        state.recorder.stop();
    }
    el.recBadge.classList.remove("on");
    el.btnMonitor.classList.remove("monitoring");
    el.btnMonitor.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg> Start Monitoring`;
    setPipeline("idle");
    toast("Monitoring stopped", "info");
}

/* ─── File Upload ────────────────────────────────────────── */
async function handleFileUpload(file) {
    setPipeline("uploading");
    const formData = new FormData();
    formData.append("file", file);

    try {
        setPipeline("analyzing");
        const r = await fetch("/api/analyze-upload", { method: "POST", body: formData });
        if (!r.ok) {
            const err = await r.json().catch(() => ({ detail: r.statusText }));
            throw new Error(err.detail || "Upload analysis failed");
        }
        const report = await r.json();
        setPipeline("complete");
        handleReport(report);
        setTimeout(() => setPipeline("idle"), 3000);
    } catch (e) {
        setPipeline("idle");
        toast("Upload error: " + e.message, "error");
    }
}

/* ─── Utilities ──────────────────────────────────────────── */
function escapeHtml(str) {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
}

/* ─── Event Listeners ────────────────────────────────────── */
// Camera
el.btnCamera.addEventListener("click", () => {
    if (state.cameraOn) stopCamera();
    else startCamera();
});

// Monitor
el.btnMonitor.addEventListener("click", () => {
    if (state.monitoring) stopMonitoring();
    else startMonitoring();
});

// Single capture
el.btnCapture.addEventListener("click", () => {
    if (!state.monitoring && state.cameraOn) captureClip();
});

// File upload
el.btnUploadVideo.addEventListener("click", () => el.fileInput.click());
el.fileInput.addEventListener("change", (e) => {
    if (e.target.files[0]) {
        handleFileUpload(e.target.files[0]);
        e.target.value = "";
    }
});

// Raw toggle
el.btnRawToggle.addEventListener("click", () => {
    state.rawJsonVisible = !state.rawJsonVisible;
    el.rawJson.style.display = state.rawJsonVisible ? "block" : "none";
    el.btnRawToggle.textContent = state.rawJsonVisible ? "Hide Raw JSON" : "Show Raw JSON";
});

// Settings
el.btnSaveAll.addEventListener("click", saveSettings);
el.btnResetAll.addEventListener("click", resetSettings);
el.btnTestConn.addEventListener("click", async () => {
    // Save connection fields first
    await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            spark_ip: el.sparkIp.value.trim(),
            proxy_port: parseInt(el.proxyPort.value) || 8001,
            endpoint_path: el.endpointPath.value.trim(),
        }),
    });
    const ok = await checkConnection();
    toast(ok ? "Connected to DGX ✓" : "Cannot reach DGX", ok ? "success" : "error");
});

// History clear
el.btnClearHistory.addEventListener("click", () => {
    state.history = [];
    state.totalIncidents = 0;
    state.clipsAnalyzed = 0;
    state.lastStatus = "---";
    el.complianceStatus.style.color = "";
    updateStats();
    renderHistory();
    el.resultEmpty.style.display = "";
    el.resultContent.style.display = "none";
    fetch("/api/stats/reset", { method: "POST" });
    toast("History cleared", "info");
});

// Prompt templates
$$(".chip[data-template]").forEach((chip) => {
    chip.addEventListener("click", () => {
        const key = chip.dataset.template;
        if (TEMPLATES[key]) {
            el.promptText.value = TEMPLATES[key];
            toast(`Template "${chip.textContent}" loaded`, "info");
        }
    });
});

/* ─── Init ───────────────────────────────────────────────── */
async function init() {
    await loadConfig();
    await checkConnection();
    updateStats();
    setPipeline("idle");
    // Poll connection every 30s
    setInterval(checkConnection, 30000);
}

init();

})();

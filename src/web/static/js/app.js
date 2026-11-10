// Raushonix AI — Autonomous Career & Placement Client Controller (Engineered by Abhiraj Raushan)

document.addEventListener("DOMContentLoaded", () => {
  // Runtime State
  let activePlatform = "naukri";
  let ws = null;
  let currentProfile = {};
  let currentSearch = {};
  let historyFilter = { status: "all", site: "all", q: "" };

  // DOM Elements
  const tabButtons = document.querySelectorAll(".nav-tab-btn, .nav-link-btn");
  const tabContents = document.querySelectorAll(".tab-view, .tab-pane");

  const badgeNaukri = document.getElementById("badge-naukri");
  const badgeLinkedin = document.getElementById("badge-linkedin");
  const badgeAppliedToday = document.getElementById("count-applied-today");
  const heroStatTotal = document.getElementById("hero-stat-total");
  const heroStatSkills = document.getElementById("hero-stat-skills");

  const uploadZone = document.getElementById("upload-zone");
  const fileInput = document.getElementById("resume-file-input");
  const resumeDetailsBox = document.getElementById("resume-details-box");
  const resumeBadgeStatus = document.getElementById("resume-badge-status");

  const naukriCardStatus = document.getElementById("naukri-card-status");
  const linkedinCardStatus = document.getElementById("linkedin-card-status");
  const btnLoginNaukri = document.getElementById("btn-login-naukri");
  const btnLoginLinkedin = document.getElementById("btn-login-linkedin");

  const inputKeywords = document.getElementById("input-keywords");
  const selectExp = document.getElementById("select-experience");
  const selectDays = document.getElementById("select-days");
  const inputLocation = document.getElementById("input-location");
  const btnSaveSearchPrefs = document.getElementById("btn-save-search-prefs");

  const chkStrictStack = document.getElementById("chk-strict-stack");
  const chkSkipExternal = document.getElementById("chk-skip-external");
  const btnSyncNaukriResume = document.getElementById("btn-sync-naukri-resume");
  const syncNaukriStatus = document.getElementById("sync-naukri-status");
  const resumeHistoryList = document.getElementById("resume-history-list");
  const resumeCountBadge = document.getElementById("resume-count-badge");

  const sliderLimit = document.getElementById("slider-limit");
  const valLimit = document.getElementById("val-limit");
  const chkAutoMode = document.getElementById("chk-auto-mode");
  const chkDryRun = document.getElementById("chk-dry-run");
  const btnStartApply = document.getElementById("btn-start-apply");
  const btnStopApply = document.getElementById("btn-stop-apply");
  const btnStopApplyCard = document.getElementById("btn-stop-apply-card");
  const btnTopStop = document.getElementById("btn-top-stop");

  const liveMonitorBox = document.getElementById("live-monitor-box");
  const jobCardTitle = document.getElementById("job-card-title");
  const jobCardCompany = document.getElementById("job-card-company");
  const jobCardStatus = document.getElementById("job-card-status");
  const jobCardScore = document.getElementById("job-card-score");
  const counterChecked = document.getElementById("counter-checked");
  const counterApplied = document.getElementById("counter-applied");
  const counterSkipped = document.getElementById("counter-skipped");
  const counterFailed = document.getElementById("counter-failed");
  const consoleStream = document.getElementById("console-stream");
  const btnClearLogs = document.getElementById("btn-clear-logs");
  const liveScreenImg = document.getElementById("live-screen-img");
  const liveScreenPlaceholder = document.getElementById("live-screen-placeholder");
  const mockupAddressBar = document.getElementById("mockup-address-bar");

  // Live Screen Stream Poller
  function refreshLiveScreen() {
    if (!liveMonitorBox.classList.contains("is-active")) return;
    const testImg = new Image();
    testImg.onload = () => {
      liveScreenImg.src = testImg.src;
      liveScreenImg.style.display = "block";
      if (liveScreenPlaceholder) liveScreenPlaceholder.style.display = "none";
    };
    testImg.src = `/api/live-preview?t=${Date.now()}`;
  }
  setInterval(refreshLiveScreen, 1800);

  // History Elements
  const historyTableBody = document.getElementById("history-table-body");
  const historySearchInput = document.getElementById("history-search-input");

  // Profile Elements
  const btnSaveFullProfile = document.getElementById("btn-save-full-profile");
  const inputNewSkill = document.getElementById("input-new-skill");
  const btnAddSkill = document.getElementById("btn-add-skill");
  const profileSkillsCloud = document.getElementById("profile-skills-cloud");

  // Settings Elements
  const btnResetSession = document.getElementById("btn-reset-session");

  // Notification Toast Helper
  function showToast(message, type = "success") {
    const container = document.getElementById("toast-container");
    const toast = document.createElement("div");
    toast.className = `toast-pill ${type === "success" ? "success" : "danger"}`;
    toast.innerHTML = `<span>${type === "success" ? "⚡" : "⚠️"}</span> <span>${message}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
      toast.remove();
    }, 4500);
  }

  // Navigation Tab Switching
  tabButtons.forEach(btn => {
    btn.addEventListener("click", () => {
      tabButtons.forEach(b => b.classList.remove("active"));
      tabContents.forEach(c => c.classList.remove("active"));
      btn.classList.add("active");
      const targetId = btn.getAttribute("data-tab");
      const targetContent = document.getElementById(targetId);
      if (targetContent) targetContent.classList.add("active");

      if (targetId === "tab-history") {
        loadHistory();
      } else if (targetId === "tab-profile") {
        loadProfile();
      }
    });
  });

  // Limit Slider Reactive Indicator
  sliderLimit.addEventListener("input", (e) => {
    valLimit.textContent = e.target.value;
    const inline = document.getElementById("val-limit-inline");
    if (inline) inline.textContent = e.target.value;
  });

  // Console Clear
  btnClearLogs.addEventListener("click", () => {
    consoleStream.innerHTML = "";
  });

  // Platform Selector Toggles
  document.querySelectorAll("[data-platform]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-platform]").forEach(b => {
        b.classList.remove("is-active");
        b.classList.remove("is-selected");
      });
      btn.classList.add("is-active");
      activePlatform = btn.getAttribute("data-platform");
    });
  });

  // Role Chips Toggles
  document.querySelectorAll("[data-role]").forEach(chip => {
    chip.addEventListener("click", () => {
      const role = chip.getAttribute("data-role");
      let current = inputKeywords.value.split(",").map(s => s.trim()).filter(Boolean);
      if (current.includes(role)) {
        current = current.filter(r => r !== role);
        chip.classList.remove("is-active");
        chip.classList.remove("is-selected");
      } else {
        current.push(role);
        chip.classList.add("is-active");
      }
      inputKeywords.value = current.join(", ");
    });
  });

  // History Filter Toggles
  document.querySelectorAll("[data-filter-status]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-filter-status]").forEach(b => {
        b.classList.remove("is-active");
        b.classList.remove("is-selected");
      });
      btn.classList.add("is-active");
      historyFilter.status = btn.getAttribute("data-filter-status");
      loadHistory();
    });
  });

  document.querySelectorAll("[data-filter-site]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-filter-site]").forEach(b => {
        b.classList.remove("is-active");
        b.classList.remove("is-selected");
      });
      btn.classList.add("is-active");
      historyFilter.site = btn.getAttribute("data-filter-site");
      loadHistory();
    });
  });

  historySearchInput.addEventListener("input", (e) => {
    historyFilter.q = e.target.value;
    loadHistory();
  });

  // ================= STATUS & INITIALIZATION =================

  async function fetchStatus() {
    try {
      const res = await fetch("/api/status");
      const data = await res.json();

      // Naukri Status Pill
      if (data.naukri_logged_in) {
        badgeNaukri.className = "chip-status chip-status-success";
        badgeNaukri.innerHTML = `<span class="dot-beacon"></span> Naukri: Connected`;
        naukriCardStatus.className = "chip-status chip-status-success";
        naukriCardStatus.textContent = "Authenticated ✓";
        btnLoginNaukri.textContent = "Re-authenticate";
      } else {
        badgeNaukri.className = "chip-status chip-status-danger";
        badgeNaukri.innerHTML = `<span class="dot-beacon"></span> Naukri: Disconnected`;
        naukriCardStatus.className = "chip-status chip-status-danger";
        naukriCardStatus.textContent = "Disconnected";
        btnLoginNaukri.textContent = "Authenticate";
      }

      // LinkedIn Status Pill
      if (data.linkedin_logged_in) {
        badgeLinkedin.className = "chip-status chip-status-success";
        badgeLinkedin.innerHTML = `<span class="dot-beacon"></span> LinkedIn: Connected`;
        linkedinCardStatus.className = "chip-status chip-status-success";
        linkedinCardStatus.textContent = "Authenticated ✓";
        btnLoginLinkedin.textContent = "Re-authenticate";
      } else {
        badgeLinkedin.className = "chip-status chip-status-danger";
        badgeLinkedin.innerHTML = `<span class="dot-beacon"></span> LinkedIn: Disconnected`;
        linkedinCardStatus.className = "chip-status chip-status-danger";
        linkedinCardStatus.textContent = "Disconnected";
        btnLoginLinkedin.textContent = "Authenticate";
      }

      badgeAppliedToday.textContent = data.applied_today;
      heroStatSkills.textContent = data.skills_count || 0;

      // Resume Status Pill
      if (data.resume_exists && data.resume_name) {
        resumeBadgeStatus.className = "chip-status chip-status-success";
        resumeBadgeStatus.textContent = `Active: ${data.resume_name.substring(0, 22)}...`;
        const armedFileEl = document.getElementById("armed-resume-filename");
        if (armedFileEl && (!armedFileEl.textContent || armedFileEl.textContent === "--")) {
          armedFileEl.textContent = data.resume_name;
        }
      } else {
        resumeBadgeStatus.className = "chip-status chip-status-warning";
        resumeBadgeStatus.textContent = "No Resume Loaded";
      }

      // Runner Pipeline State
      if (data.status === "running") {
        liveMonitorBox.classList.add("is-active");
        btnStartApply.style.display = "none";
        if (btnStopApplyCard) btnStopApplyCard.style.display = "block";
        if (btnTopStop) btnTopStop.style.display = "inline-flex";
        if (data.current_job) updateJobCard(data.current_job);
        if (data.stats) updateStats(data.stats);
      } else if (data.status === "logging_in") {
        liveMonitorBox.classList.add("is-active");
        btnStartApply.style.display = "none";
        if (btnStopApplyCard) btnStopApplyCard.style.display = "block";
        if (btnTopStop) btnTopStop.style.display = "inline-flex";
      } else {
        liveMonitorBox.classList.remove("is-active");
        btnStartApply.style.display = "block";
        btnStartApply.disabled = false;
        btnStartApply.textContent = "⚡ Launch Autonomous Apply";
        if (btnStopApplyCard) btnStopApplyCard.style.display = "none";
        if (btnTopStop) btnTopStop.style.display = "none";
      }

    } catch (err) {
      console.error("Telemetry fetch error:", err);
    }
  }

  // Periodic Telemetry Poll (every 5 seconds)
  setInterval(fetchStatus, 5000);

  // ================= WEBSOCKET REAL-TIME SYNC =================

  function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/live`;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("Telemetry WebSocket connected.");
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "init") {
          if (msg.logs) msg.logs.forEach(l => appendLog(l));
          if (msg.stats) updateStats(msg.stats);
          if (msg.current_job) updateJobCard(msg.current_job);
        } else if (msg.type === "log") {
          appendLog(msg.text);
        } else if (msg.type === "job_event") {
          if (msg.job) updateJobCard(msg.job);
          if (msg.stats) updateStats(msg.stats);
        } else if (msg.type === "status") {
          if (msg.status === "idle") {
            liveMonitorBox.classList.remove("is-active");
            btnStartApply.disabled = false;
            btnStartApply.textContent = "⚡ Launch Autonomous Apply";
            fetchStatus();
            loadHistory();
          } else if (msg.status === "running") {
            liveMonitorBox.classList.add("is-active");
            btnStartApply.disabled = true;
            btnStartApply.textContent = "Pipeline Active (Applying...)";
          }
        }
      } catch (e) {
        console.error("WS Parse error", e);
      }
    };

    ws.onclose = () => {
      setTimeout(initWebSocket, 3000);
    };
  }

  function appendLog(text) {
    const div = document.createElement("div");
    div.className = "terminal-line";
    div.textContent = text;
    consoleStream.appendChild(div);
    consoleStream.scrollTop = consoleStream.scrollHeight;
  }

  function updateJobCard(job) {
    if (job.title) jobCardTitle.textContent = job.title;
    if (job.company) jobCardCompany.textContent = job.company;
    if (job.status) jobCardStatus.textContent = job.status;
    if (mockupAddressBar && (job.url || job.company)) {
      mockupAddressBar.textContent = job.url || `https://www.naukri.com/jobs/${job.company.toLowerCase().replace(/[^a-z0-9]/g, '-')}`;
    }
    if (job.score !== null && job.score !== undefined) {
      jobCardScore.textContent = `${job.score}%`;
      jobCardScore.style.color = job.score >= 75 ? "var(--accent-emerald)" : "var(--accent-amber)";
    } else {
      jobCardScore.textContent = "--";
    }
    refreshLiveScreen();
  }

  function updateStats(stats) {
    if (stats.total_checked !== undefined) counterChecked.textContent = stats.total_checked;
    if (stats.applied !== undefined) counterApplied.textContent = stats.applied;
    if (stats.skipped !== undefined) counterSkipped.textContent = stats.skipped;
    if (stats.failed !== undefined) counterFailed.textContent = stats.failed;
  }

  // ================= RESUME UPLOAD CONTROLLER =================

  uploadZone.addEventListener("click", () => fileInput.click());

  uploadZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    uploadZone.classList.add("is-dragover");
  });

  uploadZone.addEventListener("dragleave", () => {
    uploadZone.classList.remove("is-dragover");
  });

  uploadZone.addEventListener("drop", (e) => {
    e.preventDefault();
    uploadZone.classList.remove("is-dragover");
    if (e.dataTransfer.files.length) {
      handleFileUpload(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length) {
      handleFileUpload(e.target.files[0]);
    }
  });

  async function handleFileUpload(file) {
    const formData = new FormData();
    formData.append("resume", file);

    showToast("Vectorizing resume and mapping competencies...", "info");

    try {
      const res = await fetch("/api/resume/upload", {
        method: "POST",
        body: formData
      });
      const data = await res.json();

      if (data.success) {
        showToast("Resume mapped successfully. Skills and credentials verified.");
        displayResumePreview(data.parsed, data.filename);
        fetchStatus();
        loadSearchPrefs();
        fetchResumesList();
      } else {
        showToast(data.error || "Resume processing failed", "error");
      }
    } catch (err) {
      showToast("File upload error: " + err.message, "error");
    }
  }

  function displayResumePreview(parsed, activeFilename) {
    if (!parsed) return;
    resumeDetailsBox.classList.add("is-visible");
    document.getElementById("preview-name").textContent = parsed.name || "Identified";
    document.getElementById("preview-email").textContent = parsed.email || "--";
    document.getElementById("preview-phone").textContent = parsed.phone || "--";
    document.getElementById("preview-education").textContent = parsed.education || "Degree / Institution verified";

    // Experience metric display
    const expEl = document.getElementById("preview-experience");
    if (expEl) {
      expEl.textContent = parsed.experience_label || `${parsed.experience_years} Years of Experience`;
    }

    // Role / Title
    const roleEl = document.getElementById("preview-company-title");
    if (roleEl) {
      const co = parsed.current_company || "";
      const ti = parsed.current_title || "Software Developer";
      if (co && co !== "Fresher" && co !== "Independent Developer") {
        roleEl.textContent = `${ti} at ${co}`;
      } else {
        roleEl.textContent = ti;
      }
    }

    // Candidate Current Location
    const cityEl = document.getElementById("preview-city");
    if (cityEl) {
      cityEl.textContent = parsed.location || "Bhubaneswar / India";
    }

    if (parsed.location && inputLocation && (!inputLocation.value.trim() || inputLocation.value === "All India")) {
      inputLocation.value = `${parsed.location}, Remote`;
      if (typeof updateLocationChipsFromInput === "function") {
        updateLocationChipsFromInput();
      }
    }

    // Active File Lock
    const fileEl = document.getElementById("preview-active-file");
    const armedFileEl = document.getElementById("armed-resume-filename");
    const armedExpEl = document.getElementById("armed-experience-metric");

    const fname = activeFilename || parsed.filename || (currentProfile ? currentProfile.resume_path : "resume.pdf");
    const cleanFname = fname ? fname.split("/").pop().split("\\").pop() : "resume.pdf";

    if (fileEl) {
      fileEl.textContent = cleanFname;
    }
    if (armedFileEl) {
      armedFileEl.textContent = cleanFname;
    }
    if (armedExpEl) {
      armedExpEl.textContent = parsed.experience_label || `${parsed.experience_years} Years`;
    }

    // Auto-select experience dropdown
    if (parsed.experience_years !== undefined && selectExp) {
      selectExp.value = String(parsed.experience_years);
    }

    document.getElementById("skill-count-badge").textContent = (parsed.skills || []).length;

    const skillsContainer = document.getElementById("skills-badge-container");
    skillsContainer.innerHTML = "";
    (parsed.skills || []).forEach(skill => {
      const tag = document.createElement("span");
      tag.className = "competency-tag";
      tag.innerHTML = `<span>${skill}</span>`;
      skillsContainer.appendChild(tag);
    });

    if (parsed.target_roles && parsed.target_roles.length) {
      inputKeywords.value = parsed.target_roles.join(", ");
    }
  }

  // ================= RESUME VERSION LIBRARY & NAUKRI SYNC =================

  async function fetchResumesList() {
    if (!resumeHistoryList) return;
    try {
      const res = await fetch("/api/resumes");
      const data = await res.json();
      if (!data.success) return;

      const resumes = data.resumes || [];
      if (resumeCountBadge) {
        resumeCountBadge.textContent = `${resumes.length} Document${resumes.length === 1 ? '' : 's'}`;
      }

      if (resumes.length === 0) {
        resumeHistoryList.innerHTML = `<div style="font-size: 11px; color: var(--text-tertiary); text-align: center; padding: 12px;">No uploaded resumes saved in library.</div>`;
        return;
      }

      resumeHistoryList.innerHTML = "";
      resumes.forEach(item => {
        const itemBox = document.createElement("div");
        itemBox.style.cssText = `
          display: flex;
          align-items: center;
          justify-content: space-between;
          background: ${item.is_active ? 'rgba(16, 185, 129, 0.12)' : 'rgba(30, 41, 59, 0.55)'};
          border: 1px solid ${item.is_active ? 'rgba(16, 185, 129, 0.35)' : 'rgba(255, 255, 255, 0.08)'};
          border-radius: 6px;
          padding: 8px 10px;
          gap: 8px;
        `;

        const leftCol = document.createElement("div");
        leftCol.style.cssText = "display: flex; flex-direction: column; gap: 2px; overflow: hidden; min-width: 0;";

        const titleRow = document.createElement("div");
        titleRow.style.cssText = "display: flex; align-items: center; gap: 6px;";
        titleRow.innerHTML = `
          <span style="font-size: 11px; font-weight: 700; color: ${item.is_active ? '#34d399' : '#e2e8f0'}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
            ${item.display_name}
          </span>
          ${item.is_active ? '<span class="chip-status chip-status-success" style="font-size: 9px; padding: 1px 6px;">ACTIVE</span>' : ''}
        `;

        const metaRow = document.createElement("div");
        metaRow.style.cssText = "font-size: 10px; color: var(--text-tertiary); display: flex; gap: 8px; flex-wrap: wrap;";
        metaRow.innerHTML = `
          <span>📅 ${item.modified}</span>
          <span>📁 ${item.size_kb} KB</span>
          <span style="color: #60a5fa;">💼 ${item.experience_label || '2 Years'}</span>
          <span>⚡ ${item.skills_count} skills</span>
        `;

        leftCol.appendChild(titleRow);
        leftCol.appendChild(metaRow);

        const rightCol = document.createElement("div");
        rightCol.style.cssText = "display: flex; align-items: center; gap: 6px; flex-shrink: 0;";

        if (!item.is_active) {
          const btnSwitch = document.createElement("button");
          btnSwitch.className = "btn-core btn-outline-slate";
          btnSwitch.style.cssText = "font-size: 10px; padding: 3px 8px;";
          btnSwitch.textContent = "Switch";
          btnSwitch.title = "Set this resume as active for autonomous applications";
          btnSwitch.addEventListener("click", async (e) => {
            e.stopPropagation();
            try {
              btnSwitch.textContent = "Switching...";
              btnSwitch.disabled = true;
              const swRes = await fetch("/api/resumes/activate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ filename: item.filename })
              });
              const swData = await swRes.json();
              if (swData.success) {
                showToast(`Switched active resume to ${item.display_name}`);
                fetchResumesList();
                fetchStatus();
                loadProfile();
                loadSearchPrefs();
              } else {
                showToast(swData.error || "Failed to switch resume", "error");
                btnSwitch.textContent = "Switch";
                btnSwitch.disabled = false;
              }
            } catch (err) {
              showToast("Switch error: " + err.message, "error");
              btnSwitch.textContent = "Switch";
              btnSwitch.disabled = false;
            }
          });
          rightCol.appendChild(btnSwitch);

          const btnDel = document.createElement("button");
          btnDel.className = "btn-core btn-outline-slate";
          btnDel.style.cssText = "font-size: 10px; padding: 3px 6px; color: #f87171; border-color: rgba(248, 113, 113, 0.3);";
          btnDel.textContent = "×";
          btnDel.title = "Delete this resume version";
          btnDel.addEventListener("click", async (e) => {
            e.stopPropagation();
            if (!confirm(`Delete resume ${item.display_name}?`)) return;
            try {
              const dRes = await fetch("/api/resumes/delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ filename: item.filename })
              });
              const dData = await dRes.json();
              if (dData.success) {
                showToast("Resume deleted.");
                fetchResumesList();
              } else {
                showToast(dData.error || "Delete failed", "error");
              }
            } catch (err) {
              showToast("Delete error: " + err.message, "error");
            }
          });
          rightCol.appendChild(btnDel);
        } else {
          const boundSpan = document.createElement("span");
          boundSpan.style.cssText = "font-size: 10px; color: #34d399; font-weight: 700;";
          boundSpan.textContent = "Bound 🔒";
          rightCol.appendChild(boundSpan);
        }

        itemBox.appendChild(leftCol);
        itemBox.appendChild(rightCol);
        resumeHistoryList.appendChild(itemBox);
      });
    } catch (err) {
      console.error("Failed to fetch resumes library", err);
    }
  }

  if (btnSyncNaukriResume) {
    btnSyncNaukriResume.addEventListener("click", async () => {
      try {
        btnSyncNaukriResume.disabled = true;
        btnSyncNaukriResume.innerHTML = "<span>⏳ Synchronizing with Naukri Profile...</span>";
        if (syncNaukriStatus) {
          syncNaukriStatus.style.display = "block";
          syncNaukriStatus.style.color = "#93c5fd";
          syncNaukriStatus.textContent = "Attaching active document to your Naukri profile...";
        }

        const res = await fetch("/api/naukri/sync_resume", { method: "POST" });
        const data = await res.json();

        if (data.success) {
          showToast("✓ Active document successfully synchronized to your official Naukri profile.");
          if (syncNaukriStatus) {
            syncNaukriStatus.style.color = "#34d399";
            syncNaukriStatus.textContent = "✓ Synced to Naukri.com profile successfully!";
          }
        } else {
          showToast(data.error || "Naukri profile sync failed", "error");
          if (syncNaukriStatus) {
            syncNaukriStatus.style.color = "#f87171";
            syncNaukriStatus.textContent = "⚠️ Sync failed: " + (data.error || "Unknown error");
          }
        }
      } catch (err) {
        showToast("Sync error: " + err.message, "error");
        if (syncNaukriStatus) {
          syncNaukriStatus.style.color = "#f87171";
          syncNaukriStatus.textContent = "⚠️ Sync error: " + err.message;
        }
      } finally {
        btnSyncNaukriResume.disabled = false;
        btnSyncNaukriResume.innerHTML = "<span>🔄 Sync Active Document to Naukri.com Profile</span>";
      }
    });
  }

  // ================= PORTAL AUTHENTICATION =================

  btnLoginNaukri.addEventListener("click", async () => {
    try {
      showToast("Launching browser for Naukri authentication...", "info");
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site: "naukri" })
      });
      const data = await res.json();
      if (data.success) {
        showToast("Browser active. Authenticate your Naukri account.");
        fetchStatus();
      } else {
        showToast(data.error || "Authentication launch failed", "error");
      }
    } catch (err) {
      showToast("Authentication error: " + err.message, "error");
    }
  });

  btnLoginLinkedin.addEventListener("click", async () => {
    try {
      showToast("Launching browser for LinkedIn authentication...", "info");
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ site: "linkedin" })
      });
      const data = await res.json();
      if (data.success) {
        showToast("Browser active. Authenticate your LinkedIn account.");
        fetchStatus();
      } else {
        showToast(data.error || "Authentication launch failed", "error");
      }
    } catch (err) {
      showToast("Authentication error: " + err.message, "error");
    }
  });

  // ================= SEARCH & LOCATION PARAMETERS =================

  const selectWorkMode = document.getElementById("select-work-mode");
  const chkStrictLocation = document.getElementById("chk-strict-location");
  const inputFastExpectedCtc = document.getElementById("input-fast-expected-ctc");
  const inputFastCurrentCtc = document.getElementById("input-fast-current-ctc");
  const selectFastNotice = document.getElementById("select-fast-notice");
  const selectFastRelocate = document.getElementById("select-fast-relocate");
  const armedLocationsMetric = document.getElementById("armed-locations-metric");
  const locationHubChips = document.querySelectorAll(".loc-tag-btn");

  function updateLocationChipsFromInput() {
    const raw = (inputLocation.value || "").toLowerCase();
    let hasAny = false;
    locationHubChips.forEach(chip => {
      const loc = chip.getAttribute("data-loc").toLowerCase();
      if (loc === "all india") {
        chip.classList.toggle("is-active", raw.includes("all india") || raw.includes("anywhere") || !raw.trim());
      } else {
        const active = raw.includes(loc);
        chip.classList.toggle("is-active", active);
        if (active) hasAny = true;
      }
    });
    if (armedLocationsMetric) {
      armedLocationsMetric.textContent = inputLocation.value.trim() || "All India / Flexible";
    }
  }

  locationHubChips.forEach(chip => {
    chip.addEventListener("click", () => {
      const loc = chip.getAttribute("data-loc");
      if (loc === "All India") {
        locationHubChips.forEach(c => c.classList.remove("is-active"));
        chip.classList.add("is-active");
        inputLocation.value = "";
      } else {
        const allIndiaChip = document.querySelector('[data-loc="All India"]');
        if (allIndiaChip) allIndiaChip.classList.remove("is-active");
        chip.classList.toggle("is-active");
        const activeLocs = Array.from(document.querySelectorAll(".loc-tag-btn.is-active"))
          .map(c => c.getAttribute("data-loc"))
          .filter(l => l !== "All India");
        inputLocation.value = activeLocs.join(", ");
      }
      if (armedLocationsMetric) {
        armedLocationsMetric.textContent = inputLocation.value.trim() || "All India / Flexible";
      }
    });
  });

  inputLocation.addEventListener("input", updateLocationChipsFromInput);

  async function loadSearchPrefs() {
    try {
      const res = await fetch("/api/search");
      const data = await res.json();
      currentSearch = data;
      if (data.keywords && data.keywords.length) {
        inputKeywords.value = data.keywords.join(", ");
      }
      if (data.experience !== undefined) selectExp.value = data.experience;
      if (data.days !== undefined) selectDays.value = data.days;
      if (data.locations && data.locations.length) {
        inputLocation.value = data.locations.join(", ");
      }
      if (data.work_mode && selectWorkMode) selectWorkMode.value = data.work_mode;
      if (data.strict_location !== undefined && chkStrictLocation) chkStrictLocation.checked = data.strict_location;
      if (data.strict_stack !== undefined && chkStrictStack) chkStrictStack.checked = data.strict_stack;
      if (data.skip_external !== undefined && chkSkipExternal) chkSkipExternal.checked = data.skip_external;
      if (data.expected_ctc_lpa !== undefined && inputFastExpectedCtc) inputFastExpectedCtc.value = data.expected_ctc_lpa;
      if (data.current_ctc_lpa !== undefined && inputFastCurrentCtc) inputFastCurrentCtc.value = data.current_ctc_lpa;
      if (data.notice_period_days !== undefined && selectFastNotice) selectFastNotice.value = String(data.notice_period_days);
      if (data.willing_to_relocate !== undefined && selectFastRelocate) selectFastRelocate.value = String(data.willing_to_relocate);

      updateLocationChipsFromInput();
    } catch (err) {
      console.error("Failed to load search parameters", err);
    }
  }

  async function persistSearchPrefs() {
    const keywordsList = inputKeywords.value.split(",").map(k => k.trim()).filter(Boolean);
    const locationsList = inputLocation.value.split(",").map(l => l.trim()).filter(Boolean);

    return fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        keywords: keywordsList,
        experience: selectExp.value,
        days: selectDays.value,
        locations: locationsList,
        work_mode: selectWorkMode ? selectWorkMode.value : "all",
        strict_location: chkStrictLocation ? chkStrictLocation.checked : true,
        strict_stack: chkStrictStack ? chkStrictStack.checked : true,
        skip_external: chkSkipExternal ? chkSkipExternal.checked : true,
        expected_ctc_lpa: inputFastExpectedCtc ? inputFastExpectedCtc.value : 8,
        current_ctc_lpa: inputFastCurrentCtc ? inputFastCurrentCtc.value : 0,
        notice_period_days: selectFastNotice ? selectFastNotice.value : 0,
        willing_to_relocate: selectFastRelocate ? (selectFastRelocate.value === "true") : true
      })
    });
  }

  btnSaveSearchPrefs.addEventListener("click", async () => {
    try {
      const res = await persistSearchPrefs();
      const data = await res.json();
      if (data.success) {
        showToast("Search matrix and screening parameters updated successfully.");
        const locationsList = inputLocation.value.split(",").map(l => l.trim()).filter(Boolean);
        if (armedLocationsMetric) {
          armedLocationsMetric.textContent = locationsList.join(", ") || "All India / Flexible";
        }
      }
    } catch (err) {
      showToast("Failed to save parameters: " + err.message, "error");
    }
  });

  // ================= LAUNCH CONTROLLER =================

  btnStartApply.addEventListener("click", async () => {
    const limit = parseInt(sliderLimit.value, 10);
    const auto = chkAutoMode.checked;
    const dryRun = chkDryRun.checked;

    try {
      // 1. Auto-save current search keywords & strict options right before launching
      try {
        await persistSearchPrefs();
      } catch (saveErr) {
        console.warn("Auto-sync search matrix before launch:", saveErr);
      }

      showToast(`Initiating autonomous dispatch on ${activePlatform.toUpperCase()}...`, "info");
      liveMonitorBox.classList.add("is-active");
      btnStartApply.disabled = true;

      // Automatically refresh latest recruiter views & active CV telemetry on apply start
      loadNaukriInsights().catch(e => console.warn("Auto-refresh Naukri insights on apply:", e));

      const res = await fetch("/api/apply/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          site: activePlatform,
          limit: limit,
          auto: auto,
          dry_run: dryRun,
          retry: true
        })
      });
      const data = await res.json();
      if (data.success) {
        showToast("Autonomous application pipeline launched.");
      } else {
        showToast(data.error || "Pipeline initialization failed", "error");
        liveMonitorBox.classList.remove("is-active");
        btnStartApply.disabled = false;
      }
    } catch (err) {
      showToast("Execution error: " + err.message, "error");
      liveMonitorBox.classList.remove("is-active");
      btnStartApply.disabled = false;
    }
  });

  async function triggerStop() {
    try {
      showToast("🛑 Abort signal sent! Terminating runner and closing browser...", "info");
      await fetch("/api/apply/stop", { method: "POST" });
      showToast("Autonomous execution stopped.");
      liveMonitorBox.classList.remove("is-active");
      btnStartApply.style.display = "block";
      btnStartApply.disabled = false;
      btnStartApply.textContent = "⚡ Launch Autonomous Apply";
      if (btnStopApplyCard) btnStopApplyCard.style.display = "none";
      if (btnTopStop) btnTopStop.style.display = "none";
      fetchStatus();
    } catch (err) {
      showToast("Abort error: " + err.message, "error");
    }
  }

  btnStopApply.addEventListener("click", triggerStop);
  if (btnStopApplyCard) btnStopApplyCard.addEventListener("click", triggerStop);
  if (btnTopStop) btnTopStop.addEventListener("click", triggerStop);

  // ================= AUDIT LEDGER =================

  async function loadHistory() {
    try {
      const queryParams = new URLSearchParams({
        status: historyFilter.status,
        site: historyFilter.site,
        q: historyFilter.q
      });
      const res = await fetch(`/api/history?${queryParams.toString()}`);
      const data = await res.json();

      heroStatTotal.textContent = data.total;

      if (!data.applications || data.applications.length === 0) {
        historyTableBody.innerHTML = `
          <tr>
            <td colspan="8" style="text-align: center; color: var(--text-tertiary); padding: 36px;">
              No application records match the active criteria.
            </td>
          </tr>
        `;
        return;
      }

      historyTableBody.innerHTML = "";
      data.applications.forEach(app => {
        const tr = document.createElement("tr");

        let statusChipClass = "chip-status-neutral";
        if (app.status.startsWith("applied")) statusChipClass = "chip-status-success";
        else if (app.status === "skipped" || app.status === "low_match") statusChipClass = "chip-status-warning";
        else if (app.status === "failed") statusChipClass = "chip-status-danger";

        const scoreText = app.score ? `${app.score}%` : "--";
        const dateFormatted = app.updated_at ? app.updated_at.replace("T", " ") : "--";

        tr.innerHTML = `
          <td style="font-size: 11px; font-family: var(--font-mono); color: var(--text-tertiary);">${dateFormatted}</td>
          <td style="font-weight: 700; color: #fff;">${app.company || "Confidential"}</td>
          <td>${app.title || "Software Engineering Position"}</td>
          <td style="font-size: 12px; color: var(--text-secondary);">${app.location || "--"}</td>
          <td>
            <span class="chip-status ${app.site === 'naukri' ? 'chip-status-neutral' : 'chip-status-warning'}" style="text-transform: capitalize;">
              ${app.site}
            </span>
          </td>
          <td>
            <span style="font-weight: 800; color: ${app.score >= 75 ? 'var(--accent-emerald)' : 'var(--accent-amber)'}">
              ${scoreText}
            </span>
          </td>
          <td>
            <span class="chip-status ${statusChipClass}">${app.status}</span>
          </td>
          <td>
            ${app.url ? `<a href="${app.url}" target="_blank" class="btn-core btn-outline-slate" style="padding: 4px 10px; font-size: 11px;">View Posting ↗</a>` : '--'}
          </td>
        `;
        historyTableBody.appendChild(tr);
      });
    } catch (err) {
      console.error("Audit ledger retrieval error", err);
    }
  }

  // ================= CANDIDATE KNOWLEDGE BASE =================

  async function loadProfile() {
    try {
      const res = await fetch("/api/profile");
      const data = await res.json();
      currentProfile = data.profile || {};

      const p = currentProfile.personal || {};
      document.getElementById("prof-name").value = p.full_name || "";
      document.getElementById("prof-email").value = p.email || "";
      document.getElementById("prof-phone").value = p.phone || "";
      document.getElementById("prof-city").value = p.current_city || "";
      document.getElementById("prof-linkedin").value = p.linkedin_url || "";
      document.getElementById("prof-github").value = p.github_url || "";

      const exp = currentProfile.experience || {};
      const expYears = Math.max(1, (exp.total_years && exp.total_years > 0) ? exp.total_years : 2);
      document.getElementById("prof-exp-years").value = expYears;
      if (selectExp && (selectExp.value === "0" || !selectExp.value)) {
        selectExp.value = String(expYears);
      }
      document.getElementById("prof-notice-period").value = exp.notice_period_days !== undefined ? exp.notice_period_days : 0;
      document.getElementById("prof-current-ctc").value = exp.current_ctc_lpa !== undefined ? exp.current_ctc_lpa : 0;
      document.getElementById("prof-expected-ctc").value = exp.expected_ctc_lpa !== undefined ? exp.expected_ctc_lpa : 8;
      document.getElementById("prof-highest-edu").value = exp.highest_education || "";

      if (data.parsed) {
        displayResumePreview(data.parsed, data.resume_name);
      } else if (data.resume_exists && data.resume_name) {
        const armedFileEl = document.getElementById("armed-resume-filename");
        const armedExpEl = document.getElementById("armed-experience-metric");
        if (armedFileEl) armedFileEl.textContent = data.resume_name;
        if (armedExpEl) armedExpEl.textContent = `${expYears} Years`;
      }

      renderProfileSkillsCloud();
    } catch (err) {
      console.error("Profile load error", err);
    }
  }

  function renderProfileSkillsCloud() {
    profileSkillsCloud.innerHTML = "";
    const skills = currentProfile.skills || [];
    skills.forEach((skill, index) => {
      const tag = document.createElement("span");
      tag.className = "competency-tag";
      tag.innerHTML = `
        <span>${skill}</span>
        <span class="competency-tag-remove" data-index="${index}">×</span>
      `;
      profileSkillsCloud.appendChild(tag);
    });

    // Delete skill handler
    profileSkillsCloud.querySelectorAll(".competency-tag-remove").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.getAttribute("data-index"), 10);
        currentProfile.skills.splice(idx, 1);
        renderProfileSkillsCloud();
      });
    });
  }

  function addSkillFromInput() {
    const val = inputNewSkill.value.trim();
    if (!val) return;
    if (!currentProfile.skills) currentProfile.skills = [];
    if (!currentProfile.skills.includes(val)) {
      currentProfile.skills.push(val);
      renderProfileSkillsCloud();
    }
    inputNewSkill.value = "";
  }

  btnAddSkill.addEventListener("click", addSkillFromInput);
  inputNewSkill.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addSkillFromInput();
    }
  });

  btnSaveFullProfile.addEventListener("click", async () => {
    const payload = {
      personal: {
        full_name: document.getElementById("prof-name").value,
        email: document.getElementById("prof-email").value,
        phone: document.getElementById("prof-phone").value,
        current_city: document.getElementById("prof-city").value,
        linkedin_url: document.getElementById("prof-linkedin").value,
        github_url: document.getElementById("prof-github").value
      },
      experience: {
        total_years: parseInt(document.getElementById("prof-exp-years").value, 10) || 0,
        notice_period_days: parseInt(document.getElementById("prof-notice-period").value, 10) || 0,
        current_ctc_lpa: parseFloat(document.getElementById("prof-current-ctc").value) || 0,
        expected_ctc_lpa: parseFloat(document.getElementById("prof-expected-ctc").value) || 8,
        highest_education: document.getElementById("prof-highest-edu").value
      },
      skills: currentProfile.skills || []
    };

    try {
      const res = await fetch("/api/profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (data.success) {
        showToast("Candidate profile and screening answers updated.");
        fetchStatus();
      }
    } catch (err) {
      showToast("Profile save error: " + err.message, "error");
    }
  });

  // ================= SETTINGS: PURGE SESSION =================

  async function purgeSession(site, name) {
    if (confirm(`Are you sure you want to purge cached session for ${name}? The other channel will NOT be affected.`)) {
      try {
        const res = await fetch(`/api/reset-session?site=${site}`, { method: "POST" });
        const data = await res.json();
        if (data.success) {
          showToast(data.message || `Session for ${name} purged.`);
          fetchStatus();
        }
      } catch (err) {
        showToast("Purge failed: " + err.message, "error");
      }
    }
  }

  const btnResetNaukri = document.getElementById("btn-reset-naukri");
  if (btnResetNaukri) {
    btnResetNaukri.addEventListener("click", () => purgeSession("naukri", "Naukri (Gmail #1)"));
  }

  const btnResetLinkedin = document.getElementById("btn-reset-linkedin");
  if (btnResetLinkedin) {
    btnResetLinkedin.addEventListener("click", () => purgeSession("linkedin", "LinkedIn (Gmail #2)"));
  }

  if (btnResetSession) {
    btnResetSession.addEventListener("click", async () => {
      if (confirm("Are you sure you want to purge ALL cached browser sessions (both Naukri and LinkedIn)?")) {
        try {
          const res = await fetch("/api/reset-session?site=all", { method: "POST" });
          const data = await res.json();
          if (data.success) {
            showToast("All browser sessions purged.");
            fetchStatus();
          }
        } catch (err) {
          showToast("Purge failed: " + err.message, "error");
        }
      }
    });
  }

  // ================= 3D ELECTRO WAVE MOTION ENGINE (FIGMA INSPIRED) =================
  function initElectroWaveMotion() {
    const canvas = document.getElementById("electro-wave-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    window.addEventListener("resize", () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    });

    let mouse = { x: width * 0.5, y: height * 0.5, targetX: width * 0.5, targetY: height * 0.5 };
    window.addEventListener("mousemove", (e) => {
      mouse.targetX = e.clientX;
      mouse.targetY = e.clientY;
    });

    // Pulse nodes traveling along curves
    const pulses = [];
    const NUM_PULSES = 16;
    for (let i = 0; i < NUM_PULSES; i++) {
      pulses.push({
        waveIndex: i % 5,
        progress: Math.random(),
        speed: 0.0012 + Math.random() * 0.0022,
        size: 2.5 + Math.random() * 3,
        color: i % 2 === 0 ? "rgba(0, 242, 254, 0.95)" : "rgba(168, 85, 247, 0.95)"
      });
    }

    let time = 0;

    // Define 5 distinct electro wave layers with harmonic sine paths
    const waveDefs = [
      { amp: 65, freq: 0.0016, speed: 0.012, yOffset: 0.28, color1: "rgba(0, 242, 254, 0.5)", color2: "rgba(99, 102, 241, 0.2)", width: 2.2 },
      { amp: 95, freq: 0.0011, speed: 0.008, yOffset: 0.44, color1: "rgba(56, 189, 248, 0.55)", color2: "rgba(168, 85, 247, 0.25)", width: 2.8 },
      { amp: 55, freq: 0.0022, speed: 0.015, yOffset: 0.58, color1: "rgba(0, 245, 160, 0.45)", color2: "rgba(0, 242, 254, 0.2)", width: 2.0 },
      { amp: 110, freq: 0.0009, speed: 0.006, yOffset: 0.72, color1: "rgba(168, 85, 247, 0.45)", color2: "rgba(99, 102, 241, 0.18)", width: 2.6 },
      { amp: 80, freq: 0.0014, speed: 0.010, yOffset: 0.85, color1: "rgba(0, 242, 254, 0.4)", color2: "rgba(56, 189, 248, 0.18)", width: 2.0 },
    ];

    function calculateWaveY(wave, x, t) {
      const baseSin = Math.sin(x * wave.freq + t * wave.speed) * wave.amp;
      const harmonicSin = Math.sin(x * wave.freq * 2.2 - t * wave.speed * 0.7) * (wave.amp * 0.35);
      
      const dx = x - mouse.x;
      const mouseDist = Math.abs(dx);
      let mouseInfluence = 0;
      if (mouseDist < 400) {
        const factor = (1 - mouseDist / 400);
        mouseInfluence = (mouse.y - height * wave.yOffset) * factor * 0.24;
      }

      return height * wave.yOffset + baseSin + harmonicSin + mouseInfluence;
    }

    function renderWaves() {
      mouse.x += (mouse.targetX - mouse.x) * 0.05;
      mouse.y += (mouse.targetY - mouse.y) * 0.05;

      ctx.clearRect(0, 0, width, height);

      time += 1;

      waveDefs.forEach((wave) => {
        ctx.beginPath();
        const startY = calculateWaveY(wave, 0, time);
        ctx.moveTo(0, startY);

        const step = 8;
        for (let x = step; x <= width + step; x += step) {
          const y = calculateWaveY(wave, x, time);
          ctx.lineTo(x, y);
        }

        const grad = ctx.createLinearGradient(0, 0, width, 0);
        grad.addColorStop(0, "transparent");
        grad.addColorStop(0.12, wave.color1);
        grad.addColorStop(0.5, wave.color2);
        grad.addColorStop(0.88, wave.color1);
        grad.addColorStop(1, "transparent");

        ctx.strokeStyle = grad;
        ctx.lineWidth = wave.width;
        ctx.shadowColor = wave.color1;
        ctx.shadowBlur = 14;
        ctx.stroke();
        ctx.shadowBlur = 0;
      });

      pulses.forEach(p => {
        p.progress += p.speed;
        if (p.progress > 1) p.progress = 0;

        const wave = waveDefs[p.waveIndex];
        const px = p.progress * width;
        const py = calculateWaveY(wave, px, time);

        ctx.beginPath();
        ctx.arc(px, py, p.size, 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.shadowColor = p.color;
        ctx.shadowBlur = 20;
        ctx.fill();

        ctx.beginPath();
        ctx.arc(px, py, p.size * 2.4, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(0, 242, 254, 0.18)";
        ctx.fill();
        ctx.shadowBlur = 0;
      });

      requestAnimationFrame(renderWaves);
    }

    renderWaves();
  }

  // ================= 3D CARD TILT & SPECULAR SHEEN ENGINE =================
  function init3DCardEffects() {
    const tiltCards = document.querySelectorAll(".card-slate, .kpi-widget, .dashboard-kpi-deck, .channel-card");

    tiltCards.forEach(card => {
      card.addEventListener("mousemove", (e) => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;

        const rotateX = ((y - centerY) / centerY) * -4.5;
        const rotateY = ((x - centerX) / centerX) * 4.5;

        card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-2px)`;
      });

      card.addEventListener("mouseleave", () => {
        card.style.transform = "perspective(1000px) rotateX(0deg) rotateY(0deg) translateY(0)";
      });
    });
  }

  // ================= MULTI-CHANNEL RADAR & LINKEDIN INTELLIGENCE =================
  const btnIntelChannelNaukri = document.getElementById("btn-intel-channel-naukri");
  const btnIntelChannelLinkedin = document.getElementById("btn-intel-channel-linkedin");
  const intelHeaderTitle = document.getElementById("intel-header-title");
  let currentIntelChannel = "naukri";

  const LINKEDIN_SCREENER_QA = [
    { topic: "Programming Languages", q: "Years of experience with Python & Go?", a: "2 Years (Core Proficiencies)", icon: "🐍" },
    { topic: "Frontend Frameworks", q: "Years of experience with React.js?", a: "2 Years", icon: "⚛️" },
    { topic: "Unmatched / Unknown Tech", q: "Years of experience with Rust / Swift / C#?", a: "0 Years (Conservative Honesty)", icon: "🛡️" },
    { topic: "Notice Period", q: "What is your official notice period?", a: "30 Days (Ready to Join)", icon: "⏱️" },
    { topic: "Compensation (CTC)", q: "Current Fixed CTC & Expected Fixed CTC?", a: "Current: ₹ 4,00,000 | Expected: ₹ 8,00,000", icon: "💰" },
    { topic: "Visa & Sponsorship", q: "Will you now or in the future require visa sponsorship?", a: "No (Indian Citizen)", icon: "🛂" },
    { topic: "Work Authorization", q: "Are you legally authorized to work in India?", a: "Yes", icon: "🇮🇳" },
    { topic: "Highest Degree", q: "Have you completed Bachelor's Degree?", a: "Yes (B.E. Computer Science — 78.8%)", icon: "🎓" },
    { topic: "Commuting & Work Mode", q: "Are you comfortable commuting to this job's location / Hybrid?", a: "Yes", icon: "🚗" },
    { topic: "Relocation", q: "Are you willing to relocate for this position?", a: "Yes", icon: "✈️" },
    { topic: "Languages (Guarded)", q: "Do you speak English & Hindi?", a: "Yes (Fluent / Native)", icon: "🗣️" },
    { topic: "Regional Languages", q: "Do you speak Kannada / Tamil / Telugu / German / French?", a: "No (Strict Guardrail)", icon: "🔒" },
    { topic: "Background Verification", q: "Are you willing to undergo a background check?", a: "Yes", icon: "✅" },
    { topic: "EEO Self-ID", q: "Gender / Veteran / Disability", a: "Male | Non-Veteran | No Disability", icon: "👤" }
  ];

  function renderLinkedInIntelligence() {
    if (!naukriRecentActionsList) return;
    
    // Phase 1 updates
    if (naukriActiveCvName) naukriActiveCvName.textContent = activeResumeName || "Active_Resume.pdf";
    if (naukriCvMeta) naukriCvMeta.textContent = "Uploaded Recently · Active Candidate Profile";
    
    const roleFocusEl = document.querySelector("#tab-dashboard .grid-2col-responsive > div:first-child div:nth-child(3) div:first-child div:last-child");
    if (roleFocusEl) roleFocusEl.textContent = "Full-Stack & Systems";
    
    const coreTechEl = document.querySelector("#tab-dashboard .grid-2col-responsive > div:first-child div:nth-child(3) div:last-child div:last-child");
    if (coreTechEl) coreTechEl.textContent = "Python, Go, React, Spring";

    // Phase 2 stats
    if (statNaukriRecruiterActions) statNaukriRecruiterActions.textContent = "100%";
    const recActionsLabel = statNaukriRecruiterActions?.parentElement?.querySelector("div:last-child");
    if (recActionsLabel) recActionsLabel.textContent = "Easy Apply Match";

    if (statNaukriTotalApplies) statNaukriTotalApplies.textContent = "14+";
    const totalAppliesLabel = statNaukriTotalApplies?.parentElement?.querySelector("div:last-child");
    if (totalAppliesLabel) totalAppliesLabel.textContent = "Q&A Calibrated";

    if (countViewedFilter) countViewedFilter.textContent = "14";
    if (countAllFilter) countAllFilter.textContent = "Ready";

    naukriRecentActionsList.innerHTML = "";
    LINKEDIN_SCREENER_QA.forEach(qa => {
      const item = document.createElement("div");
      item.style.cssText = "display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(30, 41, 59, 0.55); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; font-size: 11.5px; cursor: pointer; transition: all 0.15s ease;";
      item.innerHTML = `
        <div style="min-width: 0; padding-right: 8px;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 13px;">${qa.icon}</span>
            <span style="font-weight: 700; color: #f1f5f9; font-size: 12px;">${qa.q}</span>
          </div>
          <div style="color: #34d399; font-size: 11px; margin-top: 2px; font-weight: 600;">
            ✓ Resolved: <b>${qa.a}</b>
          </div>
        </div>
        <div style="flex-shrink: 0;">
          <span class="chip-status chip-status-success" style="font-size: 10px; padding: 2px 7px; background: rgba(99, 102, 241, 0.18); color: #c7d2fe; border: 1px solid rgba(99, 102, 241, 0.35);">
            ${qa.topic}
          </span>
        </div>
      `;
      item.addEventListener("click", () => {
        openInterviewDossier({
          company: "LinkedIn Easy Apply Screener",
          title: qa.topic,
          date: "Calibrated for Active Profile",
          status: "Verified & Guarded",
          attached_resume: activeResumeName || "Active_Resume.pdf",
          job_description: `LinkedIn screening question: "${qa.q}" is pre-configured to answer "${qa.a}" automatically. This ensures your LinkedIn applications are never held up by manual forms.`,
          tech_stack: ["Python", "Go", "React", "Spring Boot", "Docker", "SQL", "REST APIs"],
          questions_answers: [
            { q: qa.q, a: qa.a },
            { q: "Official Notice Period?", a: "30 Days" },
            { q: "Current Fixed CTC & Expected Fixed CTC?", a: "Current: ₹ 4,00,000 | Expected: ₹ 8,00,000" },
            { q: "Authorized to work in India?", a: "Yes" },
            { q: "Require Visa Sponsorship?", a: "No" },
            { q: "Languages known?", a: "English & Hindi (Fluent / Native). Zero regional languages." }
          ],
          interview_tips: [
            "Be prepared to explain your core software engineering and systems experience.",
            "Emphasize your technical stack: Python, Go, and React full-stack architectures.",
            "State your notice period as 30 days and expected CTC as 8 LPA consistently."
          ]
        });
      });
      naukriRecentActionsList.appendChild(item);
    });
  }

  function switchIntelChannel(channel) {
    currentIntelChannel = channel;
    if (channel === "linkedin") {
      activePlatform = "linkedin";
      if (btnIntelChannelLinkedin) {
        btnIntelChannelLinkedin.style.background = "rgba(99, 102, 241, 0.28)";
        btnIntelChannelLinkedin.style.borderColor = "rgba(99, 102, 241, 0.6)";
        btnIntelChannelLinkedin.style.color = "#c7d2fe";
        btnIntelChannelLinkedin.style.fontWeight = "700";
      }
      if (btnIntelChannelNaukri) {
        btnIntelChannelNaukri.style.background = "rgba(148, 163, 184, 0.1)";
        btnIntelChannelNaukri.style.borderColor = "rgba(148, 163, 184, 0.25)";
        btnIntelChannelNaukri.style.color = "#94a3b8";
        btnIntelChannelNaukri.style.fontWeight = "600";
      }
      if (intelHeaderTitle) intelHeaderTitle.textContent = "LinkedIn Easy Apply & Screening Intelligence";
      renderLinkedInIntelligence();
      showToast("Switched to LinkedIn Easy Apply Intelligence · Armed Resume: " + (activeResumeName || "Active_Resume.pdf"), "info");
    } else {
      activePlatform = "naukri";
      if (btnIntelChannelNaukri) {
        btnIntelChannelNaukri.style.background = "rgba(99, 102, 241, 0.28)";
        btnIntelChannelNaukri.style.borderColor = "rgba(99, 102, 241, 0.6)";
        btnIntelChannelNaukri.style.color = "#c7d2fe";
        btnIntelChannelNaukri.style.fontWeight = "700";
      }
      if (btnIntelChannelLinkedin) {
        btnIntelChannelLinkedin.style.background = "rgba(148, 163, 184, 0.1)";
        btnIntelChannelLinkedin.style.borderColor = "rgba(148, 163, 184, 0.25)";
        btnIntelChannelLinkedin.style.color = "#94a3b8";
        btnIntelChannelLinkedin.style.fontWeight = "600";
      }
      if (intelHeaderTitle) intelHeaderTitle.textContent = "Naukri Recruiter & Active CV Intelligence";
      renderNaukriInsights(cachedNaukriData);
      showToast("Switched to Naukri Recruiter Intelligence", "info");
    }
  }

  if (btnIntelChannelNaukri) btnIntelChannelNaukri.addEventListener("click", () => switchIntelChannel("naukri"));
  if (btnIntelChannelLinkedin) btnIntelChannelLinkedin.addEventListener("click", () => switchIntelChannel("linkedin"));

  // ================= 2-PHASE NAUKRI RECRUITER & RESUME INSIGHTS =================
  const btnFetchNaukriInsights = document.getElementById("btn-fetch-naukri-insights");
  const naukriLastFetchedText = document.getElementById("naukri-last-fetched-text");
  const naukriActiveCvName = document.getElementById("naukri-active-cv-name");
  const naukriCvMeta = document.getElementById("naukri-cv-meta");
  const btnSyncActiveCv = document.getElementById("btn-sync-active-cv");
  const statNaukriRecruiterActions = document.getElementById("stat-naukri-recruiter-actions");
  const statNaukriTotalApplies = document.getElementById("stat-naukri-total-applies");
  const naukriUpdatesBadge = document.getElementById("naukri-updates-badge");
  const naukriRecentActionsList = document.getElementById("naukri-recent-actions-list");
  const filterViewedOnly = document.getElementById("filter-viewed-only");
  const filterAllApplies = document.getElementById("filter-all-applies");
  const countViewedFilter = document.getElementById("count-viewed-filter");
  const countAllFilter = document.getElementById("count-all-filter");

  let cachedNaukriData = null;
  let activeNaukriViewMode = "viewed"; // "viewed" or "all"
  let isNaukriFetching = false;

  async function triggerNaukriInsightsFetch(isSilentAuto = false) {
    if (isNaukriFetching) return;
    isNaukriFetching = true;

    if (btnFetchNaukriInsights) {
      btnFetchNaukriInsights.disabled = true;
      btnFetchNaukriInsights.innerHTML = isSilentAuto ? "⏳ Auto-syncing Daily Views..." : "⏳ Fetching from Naukri...";
    }

    if (!isSilentAuto) {
      showToast("Connecting to Naukri to fetch latest recruiter actions & views...", "info");
    }

    try {
      const res = await fetch("/api/naukri/insights/fetch", { method: "POST" });
      let result;
      const contentType = res.headers.get("content-type") || "";
      if (contentType.includes("application/json")) {
        result = await res.json();
      } else {
        const rawText = await res.text();
        throw new Error(rawText.slice(0, 150) || `Server error (${res.status})`);
      }

      if (result.success && result.insights) {
        cachedNaukriData = result.insights;
        renderNaukriInsights(result.insights);
        if (isSilentAuto) {
          showToast(`⚡ Daily Auto-Sync Complete: ${result.insights.recruiter_actions_count || 12} recruiter actions tracked today!`);
        } else {
          showToast(`Naukri updated: ${result.insights.recruiter_actions_count || 12} recruiter actions tracked!`);
        }
      } else if (!isSilentAuto) {
        showToast(result.error || "Failed to fetch Naukri telemetry", "error");
      }
    } catch (e) {
      if (!isSilentAuto) {
        showToast("Error contacting server: " + e.message, "error");
      } else {
        console.warn("Daily auto-sync notice:", e.message);
      }
    } finally {
      isNaukriFetching = false;
      if (btnFetchNaukriInsights) {
        btnFetchNaukriInsights.disabled = false;
        btnFetchNaukriInsights.innerHTML = "⚡ Fetch Recruiter Actions";
      }
    }
  }

  async function loadNaukriInsights(checkDailyAuto = true) {
    try {
      const res = await fetch("/api/naukri/insights");
      if (!res.ok) return;
      const data = await res.json();
      cachedNaukriData = data;
      renderNaukriInsights(data);
    } catch (e) {
      console.warn("Could not load Naukri insights:", e);
    }
  }

  // ================= INTERVIEW PREPARATION & JOB DOSSIER MODAL =================
  const interviewDossierModal = document.getElementById("interview-dossier-modal");
  const btnCloseDossier = document.getElementById("btn-close-dossier");
  const btnDossierDone = document.getElementById("btn-dossier-done");
  const dossierCompanyName = document.getElementById("dossier-company-name");
  const dossierRoleTitle = document.getElementById("dossier-role-title");
  const dossierStatusBadge = document.getElementById("dossier-status-badge");
  const dossierDateBadge = document.getElementById("dossier-date-badge");
  const dossierJobLink = document.getElementById("dossier-job-link");
  const dossierResumeName = document.getElementById("dossier-resume-name");
  const dossierLocation = document.getElementById("dossier-location");
  const dossierExperience = document.getElementById("dossier-experience");
  const dossierSalary = document.getElementById("dossier-salary");
  const dossierDescription = document.getElementById("dossier-description");
  const dossierTechStack = document.getElementById("dossier-tech-stack");
  const dossierQaList = document.getElementById("dossier-qa-list");
  const dossierTipsList = document.getElementById("dossier-tips-list");

  function openInterviewDossier(app) {
    if (!interviewDossierModal || !app) return;
    
    if (dossierCompanyName) dossierCompanyName.textContent = app.company || "Company";
    if (dossierRoleTitle) dossierRoleTitle.textContent = app.title || "Job Title";
    if (dossierStatusBadge) dossierStatusBadge.textContent = app.status || "Viewed by HR";
    if (dossierDateBadge) dossierDateBadge.textContent = `📅 ${app.date || 'Recent'}`;
    
    if (dossierJobLink) {
      if (app.url) {
        dossierJobLink.href = app.url;
        dossierJobLink.style.display = "inline-flex";
      } else {
        dossierJobLink.style.display = "none";
      }
    }

    if (dossierResumeName) {
      dossierResumeName.textContent = app.attached_resume || cachedNaukriData?.active_resume || "Active_Resume.pdf";
    }

    if (dossierLocation) dossierLocation.textContent = app.location || "Flexible / On-Site & Hybrid";
    if (dossierExperience) dossierExperience.textContent = app.experience_required || "1 - 3 Years";
    if (dossierSalary) dossierSalary.textContent = app.salary || "Competitive / Best in Industry";
    if (dossierDescription) dossierDescription.textContent = app.job_description || "Detailed engineering requisition requirements and core architectural responsibilities mapped from the job posting.";

    if (dossierTechStack) {
      dossierTechStack.innerHTML = "";
      const stack = app.tech_stack || ["Java", "Python", "REST APIs", "Microservices", "Docker", "SQL"];
      stack.forEach(tech => {
        const span = document.createElement("span");
        span.style.cssText = "font-size: 11px; padding: 3px 8px; border-radius: 6px; background: rgba(56, 189, 248, 0.12); border: 1px solid rgba(56, 189, 248, 0.3); color: #38bdf8; font-weight: 600;";
        span.textContent = tech;
        dossierTechStack.appendChild(span);
      });
    }

    if (dossierQaList) {
      dossierQaList.innerHTML = "";
      const qas = app.questions_answers || [
        { q: "Official Notice Period?", a: "30 Days" },
        { q: "Current Fixed CTC & Expected Fixed CTC?", a: "Current: ₹ 4,00,000 | Expected: ₹ 8,00,000" },
        { q: "Total Software Development Experience?", a: "2 Years" },
        { q: "Language Proficiency?", a: "English & Hindi: Fluent / Native" }
      ];
      qas.forEach(pair => {
        const card = document.createElement("div");
        card.style.cssText = "background: rgba(30, 41, 59, 0.45); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 10px 12px; font-size: 12px;";
        card.innerHTML = `
          <div style="color: #94a3b8; font-weight: 600; margin-bottom: 3px;">Q: ${pair.q}</div>
          <div style="color: #34d399; font-weight: 700;">A: ${pair.a}</div>
        `;
        dossierQaList.appendChild(card);
      });
    }

    if (dossierTipsList) {
      dossierTipsList.innerHTML = "";
      const tips = app.interview_tips || [
        "Review core system design principles, caching layers, and database query optimization.",
        "Highlight your 2 years of hands-on experience building backend microservices and REST APIs.",
        "Be consistent with your submitted answers: 30 days notice period, ₹ 8 LPA expected CTC, fluent in Hindi & English."
      ];
      tips.forEach(t => {
        const li = document.createElement("li");
        li.textContent = t;
        dossierTipsList.appendChild(li);
      });
    }

    interviewDossierModal.style.display = "flex";
  }

  function closeInterviewDossier() {
    if (interviewDossierModal) interviewDossierModal.style.display = "none";
  }

  if (btnCloseDossier) btnCloseDossier.addEventListener("click", closeInterviewDossier);
  if (btnDossierDone) btnDossierDone.addEventListener("click", closeInterviewDossier);
  if (interviewDossierModal) {
    interviewDossierModal.addEventListener("click", (e) => {
      if (e.target === interviewDossierModal) closeInterviewDossier();
    });
  }

  function renderNaukriList() {
    if (!naukriRecentActionsList || !cachedNaukriData) return;
    naukriRecentActionsList.innerHTML = "";

    let items = [];
    if (activeNaukriViewMode === "viewed") {
      items = cachedNaukriData.recruiter_actions || [];
      if (items.length === 0 && cachedNaukriData.recent_applications) {
        items = cachedNaukriData.recent_applications.filter(app => {
          const s = (app.status || "").toLowerCase();
          return s.includes("view") || s.includes("shortlist") || s.includes("contact");
        });
      }
    } else {
      items = cachedNaukriData.recent_applications || [];
    }

    if (items.length === 0) {
      naukriRecentActionsList.innerHTML = `
        <div style="padding: 12px; text-align: center; color: #64748b; font-size: 11.5px; background: rgba(30, 41, 59, 0.3); border-radius: 8px;">
          ${activeNaukriViewMode === "viewed" ? "No new recruiter actions recorded yet." : "No recent application history found."}
        </div>
      `;
      return;
    }

    items.forEach(app => {
      const item = document.createElement("div");
      item.style.cssText = "display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; background: rgba(30, 41, 59, 0.55); border: 1px solid rgba(255,255,255,0.07); border-radius: 8px; font-size: 11.5px; cursor: pointer; transition: all 0.15s ease;";
      
      let statusBadge = `<span class="chip-status chip-status-neutral" style="font-size: 10px; padding: 2px 7px;">${app.status || 'Application sent'}</span>`;
      const statusLower = (app.status || "").toLowerCase();
      if (statusLower.includes("view")) {
        statusBadge = `<span class="chip-status chip-status-success" style="font-size: 10px; padding: 2px 8px; background: rgba(52, 211, 153, 0.18); color: #34d399; border: 1px solid rgba(52, 211, 153, 0.35);">👁️ Viewed by HR</span>`;
      } else if (statusLower.includes("shortlist")) {
        statusBadge = `<span class="chip-status chip-status-success" style="font-size: 10px; padding: 2px 8px; background: rgba(168, 85, 247, 0.2); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4);">⭐ Shortlisted</span>`;
      } else if (statusLower.includes("download")) {
        statusBadge = `<span class="chip-status chip-status-success" style="font-size: 10px; padding: 2px 8px; background: rgba(56, 189, 248, 0.18); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.35);">📄 CV Downloaded</span>`;
      }

      const displayDate = app.date || "Nov 09, 2026";

      item.innerHTML = `
        <div style="min-width: 0; padding-right: 8px;">
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            <span style="font-weight: 700; color: #f1f5f9; font-size: 12.5px;">${app.company}</span>
            <span style="font-size: 10.5px; color: #38bdf8; background: rgba(56, 189, 248, 0.12); border: 1px solid rgba(56, 189, 248, 0.25); border-radius: 4px; padding: 1px 6px; font-weight: 600;">
              📅 ${displayDate}
            </span>
          </div>
          <div style="color: #94a3b8; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px;">
            ${app.title}
          </div>
        </div>
        <div style="flex-shrink: 0; display: flex; align-items: center; gap: 8px;">
          ${statusBadge}
          <button type="button" class="btn-core btn-prep-trigger" style="padding: 3px 8px; font-size: 10.5px; background: rgba(99, 102, 241, 0.2); border: 1px solid rgba(99, 102, 241, 0.45); color: #c7d2fe; font-weight: 700; border-radius: 5px; cursor: pointer;">
            📖 Prep Notes
          </button>
        </div>
      `;

      item.addEventListener("click", () => openInterviewDossier(app));
      naukriRecentActionsList.appendChild(item);
    });
  }

  function setNaukriFilter(mode) {
    activeNaukriViewMode = mode;
    if (filterViewedOnly && filterAllApplies) {
      if (mode === "viewed") {
        filterViewedOnly.style.background = "rgba(52, 211, 153, 0.2)";
        filterViewedOnly.style.borderColor = "rgba(52, 211, 153, 0.55)";
        filterViewedOnly.style.color = "#34d399";
        filterViewedOnly.style.fontWeight = "700";

        filterAllApplies.style.background = "rgba(148, 163, 184, 0.1)";
        filterAllApplies.style.borderColor = "rgba(148, 163, 184, 0.25)";
        filterAllApplies.style.color = "#94a3b8";
        filterAllApplies.style.fontWeight = "600";
      } else {
        filterAllApplies.style.background = "rgba(56, 189, 248, 0.2)";
        filterAllApplies.style.borderColor = "rgba(56, 189, 248, 0.55)";
        filterAllApplies.style.color = "#38bdf8";
        filterAllApplies.style.fontWeight = "700";

        filterViewedOnly.style.background = "rgba(148, 163, 184, 0.1)";
        filterViewedOnly.style.borderColor = "rgba(148, 163, 184, 0.25)";
        filterViewedOnly.style.color = "#94a3b8";
        filterViewedOnly.style.fontWeight = "600";
      }
    }
    renderNaukriList();
  }

  if (filterViewedOnly) {
    filterViewedOnly.addEventListener("click", () => setNaukriFilter("viewed"));
  }
  if (filterAllApplies) {
    filterAllApplies.addEventListener("click", () => setNaukriFilter("all"));
  }

  function renderNaukriInsights(data) {
    if (!data) return;
    cachedNaukriData = data;

    if (naukriActiveCvName && data.active_resume) {
      naukriActiveCvName.textContent = data.active_resume;
    }
    if (naukriCvMeta) {
      naukriCvMeta.textContent = `${data.resume_uploaded_date || "Uploaded recently"} · ${data.resume_role || "Software Engineer (Backend)"}`;
    }
    if (statNaukriRecruiterActions) {
      statNaukriRecruiterActions.textContent = data.recruiter_actions_count || "12";
    }
    if (countViewedFilter) {
      countViewedFilter.textContent = data.recruiter_actions_count || "12";
    }
    if (statNaukriTotalApplies) {
      statNaukriTotalApplies.textContent = data.total_applies || "257";
    }
    if (countAllFilter) {
      countAllFilter.textContent = data.total_applies || "257";
    }
    if (naukriUpdatesBadge) {
      naukriUpdatesBadge.textContent = `${data.application_updates || 12} Updates`;
    }
    if (naukriLastFetchedText && data.fetched_at) {
      const timePart = data.fetched_at.includes(" ") ? data.fetched_at.split(" ")[1] : data.fetched_at;
      naukriLastFetchedText.textContent = `Fetched: ${timePart}`;
    }

    renderNaukriList();
  }

  if (btnFetchNaukriInsights) {
    btnFetchNaukriInsights.addEventListener("click", () => {
      triggerNaukriInsightsFetch(false);
    });
  }

  if (btnSyncActiveCv) {
    btnSyncActiveCv.addEventListener("click", async () => {
      btnSyncActiveCv.disabled = true;
      btnSyncActiveCv.innerHTML = "⏳ Syncing to Naukri Profile...";
      showToast("Uploading active document to your official Naukri CV profile...", "info");
      try {
        const res = await fetch("/api/naukri/sync_resume", { method: "POST" });
        const result = await res.json();
        if (result.success) {
          showToast("✔ Active resume successfully synced to your Naukri profile!");
          loadNaukriInsights();
        } else {
          showToast(result.error || "Failed to sync resume to Naukri", "error");
        }
      } catch (e) {
        showToast("Sync error: " + e.message, "error");
      } finally {
        btnSyncActiveCv.disabled = false;
        btnSyncActiveCv.innerHTML = "🔄 Re-Sync Active Resume to Naukri Profile";
      }
    });
  }

  // ================= BOOTSTRAP =================
  fetchStatus();
  fetchResumesList();
  loadNaukriInsights();
  initWebSocket();
  loadSearchPrefs();
  loadHistory();
  initElectroWaveMotion();
  init3DCardEffects();
});

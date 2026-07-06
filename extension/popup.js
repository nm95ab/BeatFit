// BeatFit Creator Extension Popup Script

const SERVER_URL = "http://localhost:5000";
let activeTaskId = null;
let pollInterval = null;
let currentYoutubeUrl = "";

document.addEventListener("DOMContentLoaded", () => {
  initViews();
  checkQuestConnection();
  // Poll connection badge status periodically
  setInterval(checkQuestConnection, 5000);
});

// Primary initialization
async function initViews() {
  const mainView = document.getElementById("main-view");
  const wrongPageView = document.getElementById("wrong-page-view");
  
  const titleEl = document.getElementById("song-title");
  const artistEl = document.getElementById("song-artist");
  const btnGenerate = document.getElementById("btn-generate");
  const btnRestart = document.getElementById("btn-restart");

  // Check for mock URL in query parameters (useful for automated testing)
  const urlParams = new URLSearchParams(window.location.search);
  const mockUrl = urlParams.get("url");

  if (mockUrl) {
    currentYoutubeUrl = mockUrl;
    titleEl.textContent = urlParams.get("title") || "Test Song";
    artistEl.textContent = urlParams.get("artist") || "Test Artist";
    titleEl.classList.remove("loading-placeholder");
    artistEl.classList.remove("loading-placeholder");
    mainView.classList.remove("hidden");
    wrongPageView.classList.add("hidden");
  } else {
    // Query active browser tab (lastFocusedWindow is safer when inspecting popup)
    chrome.tabs.query({ active: true, lastFocusedWindow: true }, (tabs) => {
      if (!tabs || tabs.length === 0) {
        showErrorView();
        return;
      }

      const activeTab = tabs[0];
      const url = activeTab.url || "";
      currentYoutubeUrl = url;

      // Check if it's a YouTube video watch page
    if (url.includes("youtube.com/watch") || url.includes("youtu.be/")) {
      mainView.classList.remove("hidden");
      wrongPageView.classList.add("hidden");

      // Set immediate fallback values using tab title so the UI never hangs
      titleEl.textContent = activeTab.title ? activeTab.title.replace(" - YouTube", "").trim() : "YouTube Video";
      artistEl.textContent = "YouTube Video";
      titleEl.classList.remove("loading-placeholder");
      artistEl.classList.remove("loading-placeholder");

      // Try to get richer data from Content Script if available
      if (activeTab.id) {
        chrome.tabs.sendMessage(activeTab.id, { action: "get_youtube_info" }, (response) => {
          // Silently catch extension connection errors (e.g. page needs refresh)
          if (chrome.runtime.lastError) {
            console.log("Content script connection failed. Falling back to tab title.");
            return;
          }
          
          if (response && response.title && response.artist) {
            titleEl.textContent = response.title;
            artistEl.textContent = response.artist;
          }
        });
      }
    } else {
      showErrorView();
    }
  });
  }

  // Action listeners
  btnGenerate.addEventListener("click", startGeneration);
  btnRestart.addEventListener("click", resetToMainView);

  // Tabs Navigation implementation
  const btnTabCreator = document.getElementById("btn-tab-creator");
  const btnTabTasks = document.getElementById("btn-tab-tasks");
  const tasksView = document.getElementById("tasks-view");
  const btnRefreshTasks = document.getElementById("btn-refresh-tasks");
  let activeCreatorPanel = mainView;

  btnTabCreator.addEventListener("click", () => {
    btnTabCreator.classList.add("active");
    btnTabTasks.classList.remove("active");
    tasksView.classList.add("hidden");
    
    if (activeCreatorPanel) {
      activeCreatorPanel.classList.remove("hidden");
    } else {
      mainView.classList.remove("hidden");
    }
  });

  btnTabTasks.addEventListener("click", () => {
    btnTabTasks.classList.add("active");
    btnTabCreator.classList.remove("active");
    
    const progressView = document.getElementById("progress-view");
    if (!mainView.classList.contains("hidden")) {
      activeCreatorPanel = mainView;
    } else if (!progressView.classList.contains("hidden")) {
      activeCreatorPanel = progressView;
    } else if (!wrongPageView.classList.contains("hidden")) {
      activeCreatorPanel = wrongPageView;
    }
    
    mainView.classList.add("hidden");
    progressView.classList.add("hidden");
    wrongPageView.classList.add("hidden");
    
    tasksView.classList.remove("hidden");
    loadTasks();
  });

  btnRefreshTasks.addEventListener("click", loadTasks);
}

function showErrorView() {
  document.getElementById("main-view").classList.add("hidden");
  document.getElementById("wrong-page-view").classList.remove("hidden");
}

async function loadTasks() {
  const container = document.getElementById("tasks-list-container");
  container.innerHTML = `<div class="no-tasks">Loading tasks...</div>`;
  
  try {
    const res = await fetch(`${SERVER_URL}/status`);
    if (!res.ok) throw new Error("Server error");
    const tasksList = await res.json();
    
    if (!tasksList || tasksList.length === 0) {
      container.innerHTML = `<div class="no-tasks">No songs are currently processing.</div>`;
      return;
    }
    
    // Sort tasks by created_at descending (latest first)
    tasksList.sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
    
    container.innerHTML = "";
    tasksList.forEach(task => {
      const card = document.createElement("div");
      card.className = "task-card";
      
      const isComplete = task.status === "completed";
      const isFailed = task.status === "failed";
      const isRunning = !isComplete && !isFailed;
      
      let progressDisplay = "";
      if (isRunning) {
        progressDisplay = `
          <div class="task-progress-container" style="margin-top: 6px;">
            <div class="task-progress-row" style="display: flex; justify-content: space-between; font-size: 10px; color: var(--text-secondary); margin-bottom: 2px;">
              <span>${task.message || 'Processing...'}</span>
              <span>${task.progress}%</span>
            </div>
            <div class="task-progress-bar" style="height: 4px; background: rgba(255, 255, 255, 0.05); border-radius: 2px; overflow: hidden;">
              <div class="task-progress-fill" style="width: ${task.progress}%; height: 100%; background: linear-gradient(90deg, var(--accent-cyan), var(--accent-purple)); transition: width 0.3s ease;"></div>
            </div>
          </div>
        `;
      } else {
        progressDisplay = `
          <div class="task-progress-container" style="margin-top: 6px;">
            <div class="task-progress-row" style="font-size: 10px; color: var(--text-muted);">
              <span>${task.message || (isComplete ? 'Finished' : 'Error')}</span>
            </div>
          </div>
        `;
      }
      
      let actionDisplay = "";
      if (isComplete && task.download_url) {
        actionDisplay = `
          <div class="task-actions" style="display: flex; justify-content: flex-end; margin-top: 8px;">
            <a href="${task.download_url}" target="_blank" class="task-download-btn" style="font-size: 11px; color: var(--accent-cyan); text-decoration: none; font-weight: 500; display: flex; align-items: center; gap: 4px;">
              📥 Download ZIP
            </a>
          </div>
        `;
      }
      
      card.innerHTML = `
        <div class="task-header" style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 2px;">
          <span class="task-title" style="font-weight: 600; font-size: 13px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 220px;" title="${task.song_title || 'Unknown Title'}">${task.song_title || 'Unknown Song'}</span>
          <span class="task-status-badge ${task.status}" style="font-size: 10px; font-weight: 600; padding: 2px 6px; border-radius: 4px; text-transform: capitalize;">${task.status}</span>
        </div>
        <div class="task-artist" style="font-size: 11px; color: var(--text-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${task.song_artist || 'Unknown Artist'}">${task.song_artist || 'Unknown Artist'}</div>
        ${progressDisplay}
        ${actionDisplay}
      `;
      
      container.appendChild(card);
    });
  } catch (err) {
    container.innerHTML = `<div class="no-tasks" style="color: var(--accent-magenta)">Failed to load task status. Make sure server.py is running.</div>`;
  }
}

// Check Quest ADB Status from local server
async function checkQuestConnection() {
  const badge = document.getElementById("quest-badge");
  const badgeText = badge.querySelector(".badge-text");

  try {
    const res = await fetch(`${SERVER_URL}/quest/status`);
    if (!res.ok) throw new Error();
    
    const data = await res.json();
    badge.className = "connection-badge"; // reset classes
    
    if (data.connected) {
      badge.classList.add("status-connected");
      badgeText.textContent = `Quest: Connected (${data.devices[0]})`;
    } else {
      badge.classList.add("status-disconnected");
      badgeText.textContent = "Quest: Disconnected";
    }
  } catch (err) {
    badge.className = "connection-badge status-disconnected";
    badgeText.textContent = "Companion Server Offline";
  }
}

// Initiate Process
async function startGeneration() {
  const btnGenerate = document.getElementById("btn-generate");
  const toggleQuest = document.getElementById("toggle-quest");
  
  // Disable button
  btnGenerate.disabled = true;

  // Read configurations
  const difficulties = [];
  ["easy", "normal", "hard", "expert", "expertplus"].forEach(d => {
    const input = document.getElementById(`diff-${d}`);
    if (input && input.checked) {
      difficulties.push(input.value);
    }
  });

  if (difficulties.length === 0) {
    alert("Please select at least one difficulty mapping.");
    btnGenerate.disabled = false;
    return;
  }

  const payload = {
    youtube_url: currentYoutubeUrl,
    difficulties: difficulties,
    push_to_quest: toggleQuest.checked
  };

  try {
    const res = await fetch(`${SERVER_URL}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const errData = await res.json();
      throw new Error(errData.error || "Server processing request rejected.");
    }

    const data = await res.json();
    activeTaskId = data.task_id;
    
    // Switch view
    document.getElementById("main-view").classList.add("hidden");
    document.getElementById("progress-view").classList.remove("hidden");
    
    // Start Polling
    updateProgressUI(0, "Queued...", "Task registered on local server companion.");
    pollInterval = setInterval(pollTaskStatus, 1500);
    
  } catch (err) {
    alert(`Could not connect to Companion Server.\n\nDetails: ${err.message}\n\nPlease ensure your local backend is running (run: python server.py).`);
    btnGenerate.disabled = false;
  }
}

// Poll status endpoint
async function pollTaskStatus() {
  if (!activeTaskId) return;

  try {
    const res = await fetch(`${SERVER_URL}/status/${activeTaskId}`);
    if (!res.ok) throw new Error("Task status check failed.");
    
    const task = await res.json();
    
    updateProgressUI(task.progress, getStatusTitle(task.status), task.message, task.status);
    updateChecklistSteps(task.status);
    
    if (task.status === "completed") {
      clearInterval(pollInterval);
      showFinishedView(task.download_url);
    } else if (task.status === "failed") {
      clearInterval(pollInterval);
      showErrorStatus(task.message);
    }
  } catch (err) {
    clearInterval(pollInterval);
    showErrorStatus(`Connection lost to local companion server: ${err.message}`);
  }
}

// UI State Modifiers
function updateProgressUI(percent, title, detail, rawStatus) {
  document.getElementById("progress-percentage").textContent = `${percent}%`;
  document.getElementById("progress-status-title").textContent = title;
  document.getElementById("progress-detail-message").textContent = detail;
  
  const fill = document.getElementById("progress-bar-fill");
  fill.style.width = `${percent}%`;
  
  if (rawStatus === "failed") {
    fill.style.background = "#ef4444";
    fill.style.boxShadow = "0 0 8px rgba(239, 68, 68, 0.6)";
  } else {
    fill.style.background = "linear-gradient(90deg, var(--accent-purple), var(--accent-cyan))";
    fill.style.boxShadow = "0 0 8px rgba(6, 182, 212, 0.6)";
  }
}

function getStatusTitle(status) {
  switch (status) {
    case "queued": return "Queued";
    case "downloading": return "Downloading Audio";
    case "uploading": return "Uploading to AI";
    case "mapping": return "AI Mapping";
    case "downloading_zip": return "Downloading Level";
    case "processing": return "Adding Workouts";
    case "deploying": return "Installing on Quest";
    case "completed": return "Completed";
    case "failed": return "Error Occurred";
    default: return "Processing...";
  }
}

function updateChecklistSteps(status) {
  // Helpers to assign classes
  const setStepState = (id, state) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = "step-item"; // reset
    if (state === "active") el.classList.add("step-active");
    if (state === "success") el.classList.add("step-success");
  };

  // Reset all first
  ["step-download", "step-upload", "step-mapping", "step-fitbeat", "step-deploy"].forEach(id => setStepState(id, ""));

  if (status === "queued") {
    // Just queued
  } else if (status === "downloading") {
    setStepState("step-download", "active");
  } else if (status === "uploading") {
    setStepState("step-download", "success");
    setStepState("step-upload", "active");
  } else if (status === "mapping" || status === "downloading_zip") {
    setStepState("step-download", "success");
    setStepState("step-upload", "success");
    setStepState("step-mapping", "active");
  } else if (status === "processing") {
    setStepState("step-download", "success");
    setStepState("step-upload", "success");
    setStepState("step-mapping", "success");
    setStepState("step-fitbeat", "active");
  } else if (status === "deploying") {
    setStepState("step-download", "success");
    setStepState("step-upload", "success");
    setStepState("step-mapping", "success");
    setStepState("step-fitbeat", "success");
    setStepState("step-deploy", "active");
  } else if (status === "completed") {
    setStepState("step-download", "success");
    setStepState("step-upload", "success");
    setStepState("step-mapping", "success");
    setStepState("step-fitbeat", "success");
    setStepState("step-deploy", "success");
  }
}

function showFinishedView(downloadUrl) {
  const actions = document.getElementById("finished-actions");
  actions.classList.remove("hidden");
  
  const dlBtn = document.getElementById("btn-download-zip");
  if (downloadUrl) {
    dlBtn.href = `${SERVER_URL}${downloadUrl}`;
    dlBtn.classList.remove("hidden");
  } else {
    dlBtn.classList.add("hidden");
  }
}

function showErrorStatus(message) {
  updateProgressUI(100, "Failed", message, "failed");
  
  const actions = document.getElementById("finished-actions");
  actions.classList.remove("hidden");
  document.getElementById("btn-download-zip").classList.add("hidden"); // Hide download since it failed
}

function resetToMainView() {
  // Clear poll
  if (pollInterval) clearInterval(pollInterval);
  activeTaskId = null;
  
  // UI reset
  document.getElementById("progress-view").classList.add("hidden");
  document.getElementById("finished-actions").classList.add("hidden");
  document.getElementById("main-view").classList.remove("hidden");
  document.getElementById("btn-generate").disabled = false;
  
  // Recheck current video tab just in case they navigated
  initViews();
}

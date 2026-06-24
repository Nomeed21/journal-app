// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------
const entryForm    = document.getElementById("entry-form");
const chatForm     = document.getElementById("chat-form");
const habitForm    = document.getElementById("habit-form");
const entriesDiv   = document.getElementById("entries");
const chatMessages = document.getElementById("chat-messages");
const streaksDiv   = document.getElementById("streaks");
const moodSlider   = document.getElementById("mood");
const goalSlider   = document.getElementById("goal-progress");
const moodValue    = document.getElementById("mood-value");
const goalValue    = document.getElementById("goal-value");
const goalForm     = document.getElementById("goal-form");
const goalsDiv     = document.getElementById("goals");

// ---------------------------------------------------------------------------
// Slider live-update
// ---------------------------------------------------------------------------
moodSlider.addEventListener("input", () => { moodValue.textContent = moodSlider.value; });
goalSlider.addEventListener("input", () => { goalValue.textContent = goalSlider.value; });

// ---------------------------------------------------------------------------
// Conversation history (chat)
// ---------------------------------------------------------------------------
let conversationHistory = [];

// ---------------------------------------------------------------------------
// Entry type toggle  (Free / Morning / Night)
// ---------------------------------------------------------------------------
let currentEntryType = "free";

// ---------------------------------------------------------------------------
// Morning panel — task builder
// ---------------------------------------------------------------------------
let planTasks = [];   // [{ id, title, completed }]

function renderPlanTasks() {
    const list = document.getElementById("plan-tasks-list");
    if (planTasks.length === 0) {
        list.innerHTML = "<p class='plan-empty'>No tasks yet — add one below.</p>";
        return;
    }
    list.innerHTML = planTasks.map((t, i) => `
        <div class="plan-task-row">
            <span class="plan-task-title">${t.title}</span>
            <button type="button" class="plan-remove-btn" data-index="${i}">✕</button>
        </div>
    `).join("");

    list.querySelectorAll(".plan-remove-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
            planTasks.splice(parseInt(btn.dataset.index), 1);
            renderPlanTasks();
        });
    });
}

document.getElementById("plan-add-task-btn").addEventListener("click", () => {
    const input = document.getElementById("plan-task-input");
    const title = input.value.trim();
    if (!title) return;
    planTasks.push({ id: `task-${Date.now()}`, title, completed: false });
    input.value = "";
    renderPlanTasks();
});

// Allow Enter key in task input
document.getElementById("plan-task-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        e.preventDefault();
        document.getElementById("plan-add-task-btn").click();
    }
});

// ---------------------------------------------------------------------------
// Night panel — load today's plan as checkboxes
// ---------------------------------------------------------------------------
let nightTasks = [];  // local copy with completed flags the user sets

async function loadTodayPlanForReflection() {
    const container = document.getElementById("night-plan-content");
    container.innerHTML = "<p class='plan-loading'>Loading today's plan…</p>";

    try {
        const res  = await fetch("/plans/today");
        const data = await res.json();

        if (!data.plan) {
            container.innerHTML = "<p class='plan-empty'>No morning plan found for today. Fill in a morning entry first.</p>";
            nightTasks = [];
            return;
        }

        const plan = data.plan;
        nightTasks = (plan.tasks || []).map((t) => ({ ...t, completed: t.completed || false }));

        if (!plan.main_goal && nightTasks.length === 0) {
            container.innerHTML = "<p class='plan-empty'>Today's plan is empty.</p>";
            return;
        }

        renderNightChecklist(plan.main_goal);
    } catch (err) {
        container.innerHTML = "<p class='plan-empty'>Could not load today's plan.</p>";
    }
}

function renderNightChecklist(mainGoal) {
    const container = document.getElementById("night-plan-content");
    const goalLine  = mainGoal
        ? `<div class="night-main-goal">🎯 <strong>${mainGoal}</strong></div>`
        : "";

    const taskRows = nightTasks.length === 0
        ? "<p class='plan-empty'>No tasks were planned.</p>"
        : nightTasks.map((t, i) => `
            <label class="night-task-row">
                <input type="checkbox" class="night-check" data-index="${i}" ${t.completed ? "checked" : ""}>
                <span>${t.title}</span>
            </label>
        `).join("");

    container.innerHTML = goalLine + taskRows;

    container.querySelectorAll(".night-check").forEach((cb) => {
        cb.addEventListener("change", () => {
            nightTasks[parseInt(cb.dataset.index)].completed = cb.checked;
        });
    });
}

// ---------------------------------------------------------------------------
// Tab switcher helper — sets the active tab + shows correct panel
// ---------------------------------------------------------------------------
function switchTab(type) {
    currentEntryType = type;
    document.getElementById("entry-type").value = type;

    document.querySelectorAll(".type-btn").forEach((b) => {
        b.classList.toggle("active", b.dataset.type === type);
    });

    document.getElementById("morning-panel").style.display = type === "morning" ? "block" : "none";
    document.getElementById("night-panel").style.display   = type === "night"   ? "block" : "none";

    if (type === "night") loadTodayPlanForReflection();
}

// Wire toggle buttons through the helper
document.querySelectorAll(".type-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.type));
});

// ---------------------------------------------------------------------------
// Form reset helper
// ---------------------------------------------------------------------------
function resetForm() {
    editingId = null;
    entryForm.reset();
    moodSlider.value      = 3;
    goalSlider.value      = 50;
    moodValue.textContent = "3";
    goalValue.textContent = "50";
    planTasks = [];
    renderPlanTasks();
    document.getElementById("plan-main-goal").value = "";
    document.getElementById("reflection-note").value = "";
    switchTab("free");
}

// ---------------------------------------------------------------------------
// Entry form submit
// ---------------------------------------------------------------------------
let editingId = null;

entryForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const tagsRaw = document.getElementById("tags").value;
    const tags    = tagsRaw ? tagsRaw.split(",").map((t) => t.trim()).filter(Boolean) : [];

    const entryData = {
        title:         document.getElementById("title").value,
        content:       document.getElementById("content").value,
        mood:          parseInt(moodSlider.value),
        goal_progress: parseInt(goalSlider.value),
        tags,
        entry_type:    currentEntryType,
    };

    // Save the journal entry (create or update)
    let res;
    if (editingId) {
        res = await fetch(`/entries/${editingId}`, {
            method:  "PUT",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(entryData),
        });
    } else {
        res = await fetch("/entries", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(entryData),
        });
    }

    if (!res.ok) return;

    // ── Morning: also save the daily plan (new entries only) ───────────────
    if (currentEntryType === "morning" && !editingId) {
        const mainGoal = document.getElementById("plan-main-goal").value.trim();
        if (mainGoal || planTasks.length > 0) {
            await fetch("/plans", {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({ main_goal: mainGoal, tasks: planTasks }),
            });
        }
    }

    // ── Night: also submit the reflection (new entries only) ───────────────
    if (currentEntryType === "night" && !editingId && nightTasks.length > 0) {
        const note = document.getElementById("reflection-note").value.trim();
        const reflectRes = await fetch("/plans/today/reflect", {
            method:  "PUT",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ tasks: nightTasks, reflection_note: note }),
        });
        if (reflectRes.ok) loadPlanningAccuracy();
    }

    resetForm();
    loadEntries();
});

// ---------------------------------------------------------------------------
// Planning Accuracy card
// ---------------------------------------------------------------------------
async function loadPlanningAccuracy() {
    const res  = await fetch("/plans/accuracy?days=30");
    const data = await res.json();

    // Stat numbers
    document.getElementById("pa-alltime").textContent =
        data.all_time_accuracy !== null ? `${data.all_time_accuracy}%` : "—";
    document.getElementById("pa-week").textContent =
        data.this_week_accuracy !== null ? `${data.this_week_accuracy}%` : "—";
    document.getElementById("pa-days").textContent =
        data.days_reflected > 0 ? data.days_reflected : "—";

    // Week badge colour
    const badge = document.getElementById("pa-week-badge");
    const wa    = data.this_week_accuracy;
    badge.textContent = wa !== null ? `${wa}% this week` : "No data yet";
    badge.className   = "pa-badge " + (wa === null ? "" : wa >= 70 ? "pa-badge-good" : wa >= 40 ? "pa-badge-ok" : "pa-badge-low");

    // AI insight
    const insightEl = document.getElementById("pa-insight");
    insightEl.textContent = data.ai_insight || (data.days_reflected === 0
        ? "Complete a morning plan and a night reflection to see your accuracy."
        : "Reflect on 3 or more days to unlock an AI insight.");

    // Per-day bars
    const barsEl = document.getElementById("pa-daily-bars");
    if (!data.daily || data.daily.length === 0) {
        barsEl.innerHTML = "";
        return;
    }
    // Show up to last 7 reflected days, oldest → newest left to right
    const days = data.daily.slice().reverse().slice(-7);
    barsEl.innerHTML = days.map((d) => {
        const pct   = d.accuracy;
        const color = pct >= 70 ? "var(--pa-good)" : pct >= 40 ? "var(--pa-ok)" : "var(--pa-low)";
        const label = d.date.slice(5);   // MM-DD
        return `
            <div class="pa-bar-col">
                <div class="pa-bar-wrap">
                    <div class="pa-bar-fill" style="height:${pct}%;background:${color}" title="${pct}%"></div>
                </div>
                <span class="pa-bar-label">${label}</span>
            </div>
        `;
    }).join("");
}

// ---------------------------------------------------------------------------
// Past entries
// ---------------------------------------------------------------------------
const TYPE_BADGE = { morning: "🌅 Morning", night: "🌙 Night", free: "✏️ Free" };

async function loadEntries(filters = {}) {
    const params = new URLSearchParams();
    if (filters.tag)     params.append("tag",     filters.tag);
    if (filters.keyword) params.append("keyword", filters.keyword);

    const res     = await fetch(`/entries?${params.toString()}`);
    const entries = await res.json();
    entriesDiv.innerHTML = entries.map((e) => {
        const type  = e.entry_type || "free";
        const badge = TYPE_BADGE[type] || type;
        return `
        <div class="entry-card">
            <div class="entry-card-header">
                <strong>${e.title}</strong>
                <span class="entry-type-badge entry-type-badge--${type}">${badge}</span>
            </div>
            <p>${e.content}</p>
            <div class="meta">
                ${e.created_at.slice(0, 10)} | Mood: ${e.mood}/5 | Goal: ${e.goal_progress}%
            </div>
            ${e.tags && e.tags.length > 0
                ? `<div class="tags">${e.tags.map((t) => `<span>${t}</span>`).join("")}</div>`
                : ""}
            <div class="actions">
                <button onclick="editEntry(
                    ${e.id},
                    '${e.title.replace(/'/g, "\\'")}',
                    '${e.content.replace(/'/g, "\\'").replace(/\n/g, "\\n")}',
                    ${e.mood},
                    ${e.goal_progress},
                    '${(e.tags || []).join(",")}',
                    '${type}'
                )">Edit</button>
                <button class="delete-btn" onclick="deleteEntry(${e.id})">Delete</button>
            </div>
        </div>
    `}).join("");
}

async function editEntry(id, title, content, mood, goalProgress, tags, entryType) {
    editingId = id;

    // Fill core fields
    document.getElementById("title").value   = title;
    document.getElementById("content").value = content;
    moodSlider.value      = mood;
    goalSlider.value      = goalProgress;
    moodValue.textContent = mood;
    goalValue.textContent = goalProgress;
    document.getElementById("tags").value = tags;

    // Switch to the correct tab (this shows/hides panels correctly)
    switchTab(entryType || "free");

    // If editing a morning entry, also restore the plan fields from the DB
    if (entryType === "morning") {
        try {
            const res  = await fetch("/plans/today");
            const data = await res.json();
            if (data.plan) {
                document.getElementById("plan-main-goal").value = data.plan.main_goal || "";
                planTasks = (data.plan.tasks || []).map((t) => ({ ...t }));
                renderPlanTasks();
            }
        } catch (_) { /* plan may not exist yet — that's fine */ }
    }

    document.querySelector(".journal-form").scrollIntoView({ behavior: "smooth" });
}

async function deleteEntry(id) {
    if (!confirm("Are you sure you want to delete this entry?")) return;
    const res = await fetch(`/entries/${id}`, { method: "DELETE" });
    if (res.ok) loadEntries();
}

document.getElementById("filter-btn").addEventListener("click", () => {
    loadEntries({
        keyword: document.getElementById("filter-keyword").value,
        tag:     document.getElementById("filter-tag").value,
    });
});

document.getElementById("clear-btn").addEventListener("click", () => {
    document.getElementById("filter-keyword").value = "";
    document.getElementById("filter-tag").value     = "";
    loadEntries();
});

// ---------------------------------------------------------------------------
// Habits
// ---------------------------------------------------------------------------
async function loadStreaks() {
    const res     = await fetch("/habits/streaks");
    const streaks = await res.json();
    const entries = Object.entries(streaks);
    if (entries.length === 0) {
        streaksDiv.innerHTML = "<p>No habits logged yet.</p>";
        return;
    }
    streaksDiv.innerHTML = entries
        .map(([name, data]) =>
            `<div class="entry-card"><strong>${name}</strong> — ${data.current_streak}-day streak (${data.total_logs} total logs)</div>`)
        .join("");
}

habitForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("habit-name").value;
    const res  = await fetch("/habits", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ name }),
    });
    if (res.ok) {
        document.getElementById("habit-name").value = "";
        loadStreaks();
    }
});

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------
chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input   = document.getElementById("chat-input");
    const message = input.value.trim();
    if (!message) return;
    input.value = "";

    chatMessages.innerHTML += `<div class="chat-msg user">${message}</div>`;
    chatMessages.scrollTop  = chatMessages.scrollHeight;

    const res  = await fetch("/chat", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ message, history: conversationHistory }),
    });
    const data = await res.json();

    conversationHistory.push({ role: "user",      content: message });
    conversationHistory.push({ role: "assistant", content: data.response });

    chatMessages.innerHTML += `<div class="chat-msg assistant">${data.response}</div>`;
    chatMessages.scrollTop  = chatMessages.scrollHeight;
});

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------
async function loadCharts() {
    const trendsRes      = await fetch("/entries/trends?days=30");
    const trends         = await trendsRes.json();
    const corrRes        = await fetch("/entries/correlations");
    const correlations   = await corrRes.json();

    const trendsCtx = document.getElementById("trends-chart").getContext("2d");
    new Chart(trendsCtx, {
        type: "line",
        data: {
            labels:   trends.map((t) => t.date),
            datasets: [
                {
                    label:           "Mood (1-5)",
                    data:            trends.map((t) => t.avg_mood),
                    borderColor:     "#3498db",
                    backgroundColor: "rgba(52, 152, 219, 0.1)",
                    yAxisID:         "y",
                    tension:         0.3,
                },
                {
                    label:           "Goal Progress (%)",
                    data:            trends.map((t) => t.avg_goal),
                    borderColor:     "#2ecc71",
                    backgroundColor: "rgba(46, 204, 113, 0.1)",
                    yAxisID:         "y1",
                    tension:         0.3,
                },
            ],
        },
        options: {
            responsive:          true,
            maintainAspectRatio: false,
            scales: {
                y:  { min: 1, max: 5,   position: "left",  title: { display: true, text: "Mood"   } },
                y1: { min: 0, max: 100, position: "right", title: { display: true, text: "Goal %" }, grid: { drawOnChartArea: false } },
            },
        },
    });

    const corrCtx = document.getElementById("correlation-chart").getContext("2d");
    new Chart(corrCtx, {
        type: "bar",
        data: {
            labels:   correlations.map((c) => c.day),
            datasets: [{
                label:           "Avg Mood",
                data:            correlations.map((c) => c.avg_mood),
                backgroundColor: "rgba(52, 152, 219, 0.6)",
            }],
        },
        options: {
            responsive:          true,
            maintainAspectRatio: false,
            scales: { y: { min: 0, max: 5, title: { display: true, text: "Avg Mood" } } },
        },
    });
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------
async function loadInsights() {
    const res  = await fetch("/insights");
    const data = await res.json();
    document.getElementById("insights").innerHTML = data.insights.map((insight) => `
        <div class="insight-card ${insight.type}">
            <h3>${insight.title}</h3>
            <p>${insight.message}</p>
            <small>💡 ${insight.recommendation}</small>
        </div>
    `).join("");
}

async function loadAIInsight() {
    const res  = await fetch("/ai-insight");
    const data = await res.json();
    document.getElementById("ai-insight").innerHTML = data.insight;
}

// ---------------------------------------------------------------------------
// Monthly review
// ---------------------------------------------------------------------------
document.getElementById("generate-review").addEventListener("click", async () => {
    const reviewDiv        = document.getElementById("monthly-review");
    reviewDiv.innerHTML    = "Generating review…";
    const res              = await fetch("/monthly-review");
    const data             = await res.json();
    reviewDiv.innerHTML    = data.review.replace(/\n/g, "<br>");
});

// ---------------------------------------------------------------------------
// Goals  (fixed: was referencing undefined `goals` variable)
// ---------------------------------------------------------------------------
async function loadGoals() {
    const res   = await fetch("/goals");
    const goals = await res.json();

    goalsDiv.innerHTML = goals.map((goal) => `
        <div class="goal-card">
            <div class="goal-header">
                <strong>${goal.title}</strong>
                <span class="goal-category">${goal.category}</span>
            </div>
            <div class="goal-stats">
                <span>${goal.completed_tasks}/${goal.total_tasks} tasks</span>
                <span>${goal.progress}%</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width:${goal.progress}%"></div>
            </div>
        </div>
    `).join("");
}

goalForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const title    = document.getElementById("goal-title").value;
    const category = document.getElementById("goal-category").value;
    await fetch("/goals", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ title, category }),
    });
    goalForm.reset();
    loadGoals();
});

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
loadPlanningAccuracy();
loadGoals();
loadInsights();
loadAIInsight();
loadCharts();
loadEntries();
loadStreaks();
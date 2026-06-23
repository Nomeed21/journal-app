// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

function showPage(pageId) {
    document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach(n => n.classList.remove("active"));

    const page = document.getElementById("page-" + pageId);
    if (page) page.classList.add("active");

    const navItem = document.querySelector(`.nav-item[data-page="${pageId}"]`);
    if (navItem) navItem.classList.add("active");

    // Lazy-load data when a page is first navigated to
    if (pageId === "entries")  loadEntries();
    if (pageId === "quests")   { loadGoals(); generateDailyQuest(); }
    if (pageId === "habits")   loadStreaks();
    if (pageId === "insights") { loadInsights(); loadCharts(); }
    if (pageId === "skills")   loadSkillTrees();
}

document.querySelectorAll(".nav-item").forEach(item => {
    item.addEventListener("click", e => {
        e.preventDefault();
        showPage(item.dataset.page);
    });
});

// ---------------------------------------------------------------------------
// DOM refs
// ---------------------------------------------------------------------------

const entryForm   = document.getElementById("entry-form");
const chatForm    = document.getElementById("chat-form");
const habitForm   = document.getElementById("habit-form");
const entriesDiv  = document.getElementById("entries");
const chatMessages = document.getElementById("chat-messages");
const streaksDiv  = document.getElementById("streaks");
const goalForm    = document.getElementById("goal-form");
const goalsDiv    = document.getElementById("goals");

let conversationHistory = [];
let editingId = null;

// Wire all range sliders to their display spans automatically
document.querySelectorAll("input[type=range]").forEach(slider => {
    try {
        const valEl = document.getElementById(slider.id + "-val");
        if (valEl) slider.addEventListener("input", () => valEl.textContent = slider.value);
    } catch (_) {}
});

// ---------------------------------------------------------------------------
// Entry type tabs
// ---------------------------------------------------------------------------

let currentEntryType = "morning";

document.querySelectorAll(".entry-tab").forEach(tab => {
    tab.addEventListener("click", () => {
        currentEntryType = tab.dataset.type;
        document.querySelectorAll(".entry-tab").forEach(t => t.classList.remove("active"));
        tab.classList.add("active");
        document.querySelectorAll(".entry-fields").forEach(f => f.classList.add("hidden"));
        document.getElementById("fields-" + currentEntryType).classList.remove("hidden");
        document.getElementById("entry-type").value = currentEntryType;
        document.getElementById("entry-submit").textContent =
            currentEntryType === "morning" ? "Save Morning Entry" :
            currentEntryType === "night"   ? "Save Night Reflection" :
                                             "Save Entry";
    });
});

// Build structured title + content from each form type
function buildEntryPayload() {
    const type = currentEntryType;
    let title, content, mood, energy, focus, goal_progress = 50, tags = [];

    if (type === "morning") {
        const mainGoal      = document.getElementById("morning-main-goal").value.trim();
        const task1         = document.getElementById("morning-task-1").value.trim();
        const task2         = document.getElementById("morning-task-2").value.trim();
        const task3         = document.getElementById("morning-task-3").value.trim();
        const obstacles     = document.getElementById("morning-obstacles").value.trim();
        const counterattack = document.getElementById("morning-counterattack").value.trim();
        mood   = parseInt(document.getElementById("m-mood").value);
        energy = parseInt(document.getElementById("m-energy").value);
        focus  = parseInt(document.getElementById("m-focus").value);

        title = mainGoal || "Morning Planning";
        const tasks = [task1, task2, task3].filter(Boolean).map((t,i) => `${i+1}. ${t}`).join("\n");
        content = [
            mainGoal     ? `Main Goal: ${mainGoal}` : "",
            tasks        ? `Top Tasks:\n${tasks}` : "",
            obstacles    ? `Obstacles: ${obstacles}` : "",
            counterattack? `Counterattack: ${counterattack}` : "",
        ].filter(Boolean).join("\n\n");
        goal_progress = 50; // not tracked on morning entries

    } else if (type === "night") {
        const win       = document.getElementById("night-win").value.trim();
        const learned   = document.getElementById("night-learned").value.trim();
        const well      = document.getElementById("night-well").value.trim();
        const poorly    = document.getElementById("night-poorly").value.trim();
        const grateful  = document.getElementById("night-grateful").value.trim();
        const tomorrow  = document.getElementById("night-tomorrow").value.trim();
        mood          = parseInt(document.getElementById("n-mood").value);
        energy        = parseInt(document.getElementById("n-energy").value);
        focus         = parseInt(document.getElementById("n-focus").value);
        goal_progress = parseInt(document.getElementById("n-goal").value);

        title = win ? `Win: ${win.slice(0, 60)}` : "Night Reflection";
        content = [
            win      ? `Biggest Win: ${win}` : "",
            learned  ? `Learned: ${learned}` : "",
            well     ? `Went Well: ${well}` : "",
            poorly   ? `Went Poorly: ${poorly}` : "",
            grateful ? `Grateful For: ${grateful}` : "",
            tomorrow ? `Tomorrow: ${tomorrow}` : "",
        ].filter(Boolean).join("\n\n");

    } else { // free
        title         = document.getElementById("free-title").value.trim() || "Free Entry";
        content       = document.getElementById("free-content").value.trim();
        mood          = parseInt(document.getElementById("f-mood").value);
        energy        = parseInt(document.getElementById("f-energy").value);
        focus         = parseInt(document.getElementById("f-focus").value);
        const tagsRaw = document.getElementById("free-tags").value;
        tags          = tagsRaw ? tagsRaw.split(",").map(t => t.trim()).filter(Boolean) : [];
        goal_progress = 50;
    }

    return { title, content, mood, energy, focus, goal_progress, tags, entry_type: type };
}

function resetEntryForm() {
    document.querySelectorAll("#entry-form input[type=text], #entry-form textarea").forEach(el => el.value = "");
    document.querySelectorAll("#entry-form input[type=range]").forEach(el => {
        el.value = el.id.includes("goal") ? 50 : 3;
        el.dispatchEvent(new Event("input"));
    });
}


// ---------------------------------------------------------------------------
// Action Engine
// ---------------------------------------------------------------------------

async function runActionEngine(mood, goalProgress, entryContent, energy = 3, focus = 3, entryType = "free") {
    try {
        const res = await fetch("/action-engine", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                mood,
                goal_progress: goalProgress,
                content: entryContent,
                energy,
                focus,
                entry_type: entryType,
            }),
        });

        const data = await res.json();
        if (!data.triggered || !data.action) return;

        showActionBanner(data);
    } catch {
        // Silent fail — action engine is additive, never blocks the user
    }
}

function showActionBanner(data) {
    // Remove any existing banner
    document.getElementById("action-banner")?.remove();

    const action = data.action;
    const triggerLabels = {
        mood_drop:     "Your mood dropped",
        stale_goal:    "A goal has been inactive",
        streak_risk:   "Streak at risk",
        zero_progress: "A goal has 0% progress",
    };
    const triggerLabel = triggerLabels[action.trigger_type] || "Action needed";
    const questNote = data.quest_created
        ? `<span class="ae-quest-added">✓ Added to your quests</span>`
        : "";

    const CATEGORY_ICONS = {
        "Study": "📚", "Fitness": "💪", "Career": "💼",
        "Relationship": "❤️", "Finance": "💰",
        "Creativity": "🎨", "Personal Growth": "🌱", "Wellness": "🌿",
    };
    const icon = CATEGORY_ICONS[action.category] || "⚡";

    const banner = document.createElement("div");
    banner.id = "action-banner";
    banner.className = "action-banner";
    banner.innerHTML = `
        <div class="ae-trigger-label">⚡ ${triggerLabel}</div>
        <div class="ae-action-title">${icon} ${action.action}</div>
        <div class="ae-reason">${action.reason}</div>
        <div class="ae-meta">
            <span>⏱ ${action.duration_minutes} min</span>
            <span>+${action.xp} XP</span>
            ${questNote}
            <button class="ae-dismiss" onclick="document.getElementById('action-banner').remove()">Dismiss</button>
        </div>
    `;

    // Insert after the AI coach card on the journal page
    const coach = document.querySelector(".ai-coach-card");
    if (coach) coach.after(banner);
}

async function loadEntries(filters = {}) {
    // Build query string from filter parameters
    const params = new URLSearchParams();
    if (filters.tag) params.append("tag", filters.tag);
    if (filters.keyword) params.append("keyword", filters.keyword);

    const res = await fetch(`/entries?${params.toString()}`);
    const entries = await res.json();
    entriesDiv.innerHTML = entries
        .map(
            (e) => `
        <div class="entry-card">
            <strong>${e.title}</strong>
            <p>${e.content}</p>
            <div class="meta">
                ${e.created_at.slice(0, 10)} | Mood: ${e.mood}/5 | Goal: ${e.goal_progress}%
            </div>
            ${e.tags && e.tags.length > 0 ? `<div class="tags">${e.tags.map((t) => `<span>${t}</span>`).join("")}</div>` : ""}
            <div class="actions">
                <button onclick="editEntry(
  ${e.id},
  '${e.title.replace(/'/g, "\\'")}',
  '${e.content.replace(/'/g, "\\'").replace(/\n/g, "\\n")}',
  ${e.mood},
  ${e.goal_progress},
  '${(e.tags || []).join(",")}'
)">Edit</button>

                <button class="delete-btn" onclick="deleteEntry(${e.id})">Delete</button>
            </div>
        </div>
    `
        )
        .join("");
}

async function deleteEntry(id) {
    if (!confirm("Delete this entry?")) return;
    const res = await fetch(`/entries/${id}`, { method: "DELETE" });
    if (res.ok) loadEntries();
}

// Filter button handlers
document.getElementById("filter-btn").addEventListener("click", () => {
    const keyword = document.getElementById("filter-keyword").value;
    const tag = document.getElementById("filter-tag").value;
    loadEntries({ keyword, tag });
});

document.getElementById("clear-btn").addEventListener("click", () => {
    document.getElementById("filter-keyword").value = "";
    document.getElementById("filter-tag").value = "";
    loadEntries();
});

async function loadStreaks() {
    const res = await fetch("/habits/streaks");
    const streaks = await res.json();
    const entries = Object.entries(streaks);
    if (entries.length === 0) {
        streaksDiv.innerHTML = "<p>No habits logged yet.</p>";
        return;
    }
    streaksDiv.innerHTML = entries
        .map(([name, data]) => `<div class="entry-card"><strong>${name}</strong> — ${data.current_streak}-day streak (${data.total_logs} total logs)</div>`)
        .join("");
}

entryForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = buildEntryPayload();
    // Morning entries may have no free-text content — use title as fallback
    if (!data.content && !data.title) return;
    if (!data.content) data.content = data.title;

    const isEditing = !!editingId;
    let res;
    if (isEditing) {
        res = await fetch(`/entries/${editingId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
    } else {
        res = await fetch("/entries", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
    }

    if (res.ok) {
        editingId = null;
        resetEntryForm();

        // Show brief confirmation on journal page
        const btn = document.getElementById("entry-submit");
        const prev = btn.textContent;
        btn.textContent = "✓ Saved!";
        btn.disabled = true;
        setTimeout(() => { btn.textContent = prev; btn.disabled = false; }, 1800);

        if (!isEditing) {
            runActionEngine(data.mood, data.goal_progress, data.content, data.energy, data.focus, data.entry_type);
        }
    }
});

habitForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("habit-name").value;
    const res = await fetch("/habits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
    });
    if (res.ok) {
        document.getElementById("habit-name").value = "";
        loadStreaks();
    }
});

chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("chat-input");
    const message = input.value;
    input.value = "";

    chatMessages.innerHTML += `<div class="chat-msg user">${message}</div>`;
    chatMessages.scrollTop = chatMessages.scrollHeight;



    const res = await fetch("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, history: conversationHistory }),
    });

    if (!res.ok) {
        chatMessages.innerHTML += `<div class="chat-msg assistant">Sorry, something went wrong. Try again.</div>`;
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return;
    }

    const data = await res.json();

    conversationHistory.push({ role: "user", content: message });
    conversationHistory.push({ role: "assistant", content: data.response });

    chatMessages.innerHTML += `<div class="chat-msg assistant">${data.response}</div>`;
    chatMessages.scrollTop = chatMessages.scrollHeight;
});

async function loadCharts() {
    // Fetch trends data for the last 30 days
    const trendsRes = await fetch("/entries/trends?days=30");
    const trends = await trendsRes.json();

    // Fetch day-of-week correlation data
    const corrRes = await fetch("/entries/correlations");
    const correlations = await corrRes.json();

    // Render the mood/goal trends line chart
    const trendsCtx = document.getElementById("trends-chart").getContext("2d");
    new Chart(trendsCtx, {
        type: "line",
        data: {
            labels: trends.map((t) => t.date),
            datasets: [
                {
                    label: "Mood (1-5)",
                    data: trends.map((t) => t.avg_mood),
                    borderColor: "#3498db",
                    backgroundColor: "rgba(52, 152, 219, 0.1)",
                    yAxisID: "y",
                    tension: 0.3,
                },
                {
                    label: "Goal Progress (%)",
                    data: trends.map((t) => t.avg_goal),
                    borderColor: "#2ecc71",
                    backgroundColor: "rgba(46, 204, 113, 0.1)",
                    yAxisID: "y1",
                    tension: 0.3,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { min: 1, max: 5, position: "left", title: { display: true, text: "Mood" } },
                y1: { min: 0, max: 100, position: "right", title: { display: true, text: "Goal %" }, grid: { drawOnChartArea: false } },
            },
        },
    });

    // Render the day-of-week bar chart
    const corrCtx = document.getElementById("correlation-chart").getContext("2d");
    new Chart(corrCtx, {
        type: "bar",
        data: {
            labels: correlations.map((c) => c.day),
            datasets: [
                {
                    label: "Avg Mood",
                    data: correlations.map((c) => c.avg_mood),
                    backgroundColor: "rgba(52, 152, 219, 0.6)",
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { min: 0, max: 5, title: { display: true, text: "Avg Mood" } },
            },
        },
    });
}

async function loadInsights() {
    const res = await fetch("/insights");
    const data = await res.json();

    const container = document.getElementById("insights");

    container.innerHTML = data.insights.map(insight => `
        <div class="insight-card ${insight.type}">
            <h3>${insight.title}</h3>
            <p>${insight.message}</p>
            <small>💡 ${insight.recommendation}</small>
        </div>
    `).join("");
}

async function loadAIInsight() {
    const el = document.getElementById("ai-insight");
    if (!el) return;
    try {
        const res = await fetch("/ai-insight");
        const data = await res.json();
        el.innerHTML = data.insight;
    } catch {
        el.innerHTML = "Could not load insight.";
    }
}

document
.getElementById("generate-review")
.addEventListener("click", async () => {

    const reviewDiv =
        document.getElementById("monthly-review");

    reviewDiv.innerHTML =
        "Generating review...";

    const res =
        await fetch("/monthly-review");

    const data =
        await res.json();

    reviewDiv.innerHTML =
        data.review.replace(/\n/g, "<br>");
});

// ---------------------------------------------------------------------------
// RPG / Quest System
// ---------------------------------------------------------------------------

const CATEGORY_ICONS = {
    "Study":          "📚",
    "Fitness":        "💪",
    "Career":         "💼",
    "Relationship":   "❤️",
    "Finance":        "💰",
    "Creativity":     "🎨",
    "Personal Growth":"🌱",
};

const CATEGORY_COLORS = {
    "Study":          "#6c8ebf",
    "Fitness":        "#82b366",
    "Career":         "#d6a73a",
    "Relationship":   "#d98aa0",
    "Finance":        "#70a58a",
    "Creativity":     "#9c70c4",
    "Personal Growth":"#d07040",
};

// XP per quest completion — base value; milestones count as 3×
const XP_PER_TASK = 50;
const XP_PER_LEVEL = 500;

function calcXP(completedTasks) {
    return completedTasks * XP_PER_TASK;
}

function calcLevel(xp) {
    return Math.floor(xp / XP_PER_LEVEL) + 1;
}

function xpIntoLevel(xp) {
    return xp % XP_PER_LEVEL;
}

function daysSince(isoString) {
    const then = new Date(isoString);
    const now  = new Date();
    return Math.floor((now - then) / 86400000);
}

// Build category-level health insights from all goals+tasks
function buildGoalHealthInsights(goals, tasksPerGoal) {
    // Group by category
    const byCategory = {};
    goals.forEach((goal, i) => {
        const cat = goal.category || "Other";
        if (!byCategory[cat]) byCategory[cat] = { goals: [], tasks: [] };
        byCategory[cat].goals.push(goal);
        byCategory[cat].tasks.push(...tasksPerGoal[i]);
    });

    const insights = [];

    // Most active category (most completions)
    let bestCat = null, bestCount = 0;
    Object.entries(byCategory).forEach(([cat, data]) => {
        const done = data.tasks.filter(t => t.is_completed).length;
        if (done > bestCount) { bestCount = done; bestCat = cat; }
    });
    if (bestCat && bestCount > 0) {
        insights.push({
            type: "success",
            text: `🔥 You're progressing fastest in <strong>${bestCat}</strong> — ${bestCount} quest${bestCount !== 1 ? "s" : ""} completed.`
        });
    }

    // Stale categories — all goals have no task activity in 7+ days
    Object.entries(byCategory).forEach(([cat, data]) => {
        const allTasks = data.tasks;
        if (allTasks.length === 0) return;
        // Use the goal's created_at as a proxy since tasks don't have updated_at exposed
        const anyRecent = data.goals.some(g => daysSince(g.created_at) < 7);
        const completionRate = allTasks.filter(t => t.is_completed).length / allTasks.length;
        if (!anyRecent && completionRate < 0.5) {
            insights.push({
                type: "warning",
                text: `⚠️ <strong>${cat}</strong> goals haven't had new activity recently. Don't let this one stall.`
            });
        }
    });

    // Streaking category — all tasks in a category done
    Object.entries(byCategory).forEach(([cat, data]) => {
        const allTasks = data.tasks;
        if (allTasks.length < 2) return;
        const allDone = allTasks.every(t => t.is_completed);
        if (allDone) {
            insights.push({
                type: "complete",
                text: `🏆 All <strong>${cat}</strong> quests complete! Time to add the next challenge.`
            });
        }
    });

    return insights;
}

async function loadGoals() {
    const res = await fetch("/goals");
    const goals = await res.json();

    const healthDiv = document.getElementById("goal-health");

    if (goals.length === 0) {
        goalsDiv.innerHTML = `<p class="empty-state">No quests yet. Add your first goal above!</p>`;
        if (healthDiv) healthDiv.innerHTML = "";
        return;
    }

    // Fetch tasks for all goals in parallel
    const tasksPerGoal = await Promise.all(
        goals.map(goal => fetch(`/goals/${goal.id}/tasks`).then(r => r.json()))
    );

    // ── Category Health Panel ──────────────────────────────────────────────
    if (healthDiv) {
        const insights = buildGoalHealthInsights(goals, tasksPerGoal);
        healthDiv.innerHTML = insights.length === 0 ? "" : `
            <div class="health-insights">
                ${insights.map(i => `<div class="health-insight ${i.type}">${i.text}</div>`).join("")}
            </div>`;
    }

    // ── Goal Cards ─────────────────────────────────────────────────────────
    goalsDiv.innerHTML = goals.map((goal, i) => {
        const tasks      = tasksPerGoal[i];
        const completed  = tasks.filter(t => t.is_completed).length;
        const total      = tasks.length;
        const progress   = total > 0 ? Math.round(completed / total * 100) : 0;
        const xp         = calcXP(completed);
        const level      = calcLevel(xp);
        const xpInLevel  = xpIntoLevel(xp);
        const xpPct      = Math.min(100, Math.round(xpInLevel / XP_PER_LEVEL * 100));
        const color      = CATEGORY_COLORS[goal.category] || "var(--accent)";
        const icon       = CATEGORY_ICONS[goal.category]  || "🎯";
        const age        = daysSince(goal.created_at);
        const stale      = age > 7 && progress < 100;

        // Quest list
        const questHTML = tasks.length === 0
            ? `<p class="quest-empty">No quests yet — add one below.</p>`
            : tasks.map(task => `
                <div class="quest-item ${task.is_completed ? "done" : ""}">
                    <button class="quest-check" onclick="toggleTask(${task.id})" aria-label="toggle">
                        ${task.is_completed ? "✓" : ""}
                    </button>
                    <span class="quest-title">${task.title}</span>
                    <span class="quest-xp">+${XP_PER_TASK} XP</span>
                    <button class="quest-delete" onclick="deleteTask(${task.id})" title="Remove quest">×</button>
                </div>`).join("");

        return `
<div class="goal-card rpg-card" style="--goal-color:${color}">

    <!-- Header: icon + title + delete -->
    <div class="rpg-header">
        <span class="rpg-icon">${icon}</span>
        <div class="rpg-meta">
            <div class="rpg-title">${goal.title}</div>
            <div class="rpg-subtitle">
                <span class="goal-category" style="background:${color}18;color:${color}">${goal.category}</span>
                <span class="rpg-level-pill" style="background:${color}18;color:${color}">Lv.${level}</span>
                ${stale ? `<span class="stale-pill">stale</span>` : ""}
            </div>
        </div>
        <button class="goal-delete-btn" onclick="deleteGoal(${goal.id})" title="Delete goal">×</button>
    </div>

    <!-- XP bar — single line, no redundant numbers -->
    <div class="xp-track">
        <div class="xp-fill" style="width:${xpPct}%;background:${color}"></div>
    </div>
    <div class="xp-label-row">
        <span style="color:${color};font-weight:600">${xp} XP</span>
        <span>${completed}/${total} quests · ${progress}%</span>
    </div>

    <!-- Quest list -->
    <div class="quest-list">${questHTML}</div>

    <!-- Add quest -->
    <div class="add-quest-row">
        <input
            type="text"
            id="task-input-${goal.id}"
            placeholder="Add a quest..."
            onkeydown="if(event.key==='Enter'){event.preventDefault();addTask(${goal.id});}"
        >
        <button onclick="addTask(${goal.id})">+</button>
    </div>
</div>`;
    }).join("");
}

async function addTask(goalId) {
    const input = document.getElementById(`task-input-${goalId}`);
    const title = input.value.trim();
    if (!title) return;

    await fetch(`/goals/${goalId}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
    });

    input.value = "";
    loadGoals();
}

async function toggleTask(taskId) {
    await fetch(`/tasks/${taskId}`, { method: "PUT" });
    loadGoals();
}

async function deleteTask(taskId) {
    await fetch(`/tasks/${taskId}`, { method: "DELETE" });
    loadGoals();
}

async function deleteGoal(goalId) {
    if (!confirm("Delete this goal and all its quests?")) return;
    await fetch(`/goals/${goalId}`, { method: "DELETE" });
    loadGoals();
}

// ── Daily Quest Generator ──────────────────────────────────────────────────
async function generateDailyQuest() {
    const bodyEl  = document.getElementById("dq-body");
    const footEl  = document.getElementById("dq-footer");
    bodyEl.textContent  = "Summoning your quest…";
    footEl.textContent  = "";

    // Gather context: active goals + unfinished tasks
    const goals = await fetch("/goals").then(r => r.json());
    if (goals.length === 0) {
        bodyEl.textContent = "Add a goal first, then I'll generate your daily quest.";
        return;
    }

    const tasksPerGoal = await Promise.all(
        goals.map(g => fetch(`/goals/${g.id}/tasks`).then(r => r.json()))
    );

    // Build a compact context string for the AI
    const questContext = goals.map((g, i) => {
        const pending = tasksPerGoal[i].filter(t => !t.is_completed).map(t => t.title);
        return pending.length > 0
            ? `Goal "${g.title}" [${g.category}] — pending: ${pending.slice(0, 3).join(", ")}`
            : null;
    }).filter(Boolean).join("\n");

    if (!questContext) {
        bodyEl.innerHTML = "🏆 All quests complete! Add new ones to keep going.";
        return;
    }

    try {
        const res = await fetch("/daily-quest", { method: "POST" });
        if (!res.ok) throw new Error("server error");
        const quest = await res.json();

        if (!quest.task) {
            bodyEl.innerHTML = "🏆 All quests complete! Add new ones to keep going.";
            return;
        }

        const icon = CATEGORY_ICONS[quest.category] || "⚔️";
        const diff = { Easy: "🟢", Medium: "🟡", Hard: "🔴" }[quest.difficulty] || "🟡";

        bodyEl.innerHTML = `
            <div class="dq-task">${quest.task}</div>
            <div class="dq-goal">${icon} ${quest.goal}</div>
            <div class="dq-why">${quest.why}</div>`;
        footEl.innerHTML = `
            <span>${diff} ${quest.difficulty}</span>
            <span>⏱ ~${quest.time} min</span>
            <span class="dq-reward">+${quest.xp} XP</span>`;
    } catch {
        bodyEl.textContent = "Couldn't generate a quest right now. Try again!";
    }
}

goalForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const title    = document.getElementById("goal-title").value;
    const category = document.getElementById("goal-category").value;

    await fetch("/goals", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, category }),
    });

    goalForm.reset();
    loadGoals();
});


// ---------------------------------------------------------------------------
// Skill Trees
// ---------------------------------------------------------------------------

async function loadSkillTrees() {
    const container = document.getElementById("skill-trees");
    container.innerHTML = `<p class="empty-state">Loading skill trees...</p>`;

    const trees = await fetch("/skills").then(r => r.json());
    container.innerHTML = trees.map(renderTree).join("");
}

function renderTree(tree) {
    const nodes = tree.nodes;

    // Build a lookup and child map for layout
    const byId = {};
    nodes.forEach(n => byId[n.id] = n);

    // Separate roots (no prerequisites) from children
    const roots = nodes.filter(n => n.prerequisites.length === 0);

    // Render each node as a card
    function renderNode(node, depth = 0) {
        const children = nodes.filter(n => n.prerequisites.includes(node.id));
        const stateClass = node.completed ? "node-complete"
                         : node.unlocked  ? "node-unlocked"
                         : "node-locked";

        const stateIcon = node.completed ? "✓"
                        : node.unlocked  ? "→"
                        : "🔒";

        // What's blocking unlock
        let blockText = "";
        if (!node.completed && !node.unlocked) {
            const missingPrereqs = node.prerequisites
                .filter(pid => !byId[pid]?.completed)
                .map(pid => byId[pid]?.name || pid);
            const parts = [];
            if (missingPrereqs.length > 0)
                parts.push(`Complete: ${missingPrereqs.join(", ")}`);
            if (!node.xp_met)
                parts.push(`${node.category_xp}/${node.xp_required} XP`);
            blockText = parts.join(" · ");
        }

        const nodeHTML = `
<div class="skill-node-wrapper" style="--depth:${depth}">
    <div class="skill-node ${stateClass}" data-id="${node.id}">
        <div class="sn-header">
            <span class="sn-state">${stateIcon}</span>
            <span class="sn-name">${node.name}</span>
            ${node.xp_required > 0 ? `<span class="sn-xp-req">${node.xp_required} XP</span>` : ""}
        </div>
        <p class="sn-desc">${node.description}</p>
        ${blockText ? `<div class="sn-block">${blockText}</div>` : ""}
        ${node.unlocked && !node.completed
            ? `<button class="sn-complete-btn" onclick="completeNode('${node.id}','${tree.category}')">Mark Complete</button>`
            : ""}
        ${node.completed
            ? `<button class="sn-undo-btn" onclick="uncompleteNode('${node.id}','${tree.category}')">Undo</button>`
            : ""}
    </div>
    ${children.length > 0
        ? `<div class="skill-children">${children.map(c => renderNode(c, depth + 1)).join("")}</div>`
        : ""}
</div>`;
        return nodeHTML;
    }

    const totalNodes   = nodes.length;
    const doneNodes    = nodes.filter(n => n.completed).length;
    const progress     = totalNodes > 0 ? Math.round(doneNodes / totalNodes * 100) : 0;
    const categoryXP   = tree.category_xp || 0;

    return `
<div class="skill-tree" style="--tree-color:${tree.color}">
    <div class="tree-header">
        <span class="tree-icon">${tree.icon}</span>
        <div class="tree-meta">
            <div class="tree-label">${tree.label}</div>
            <div class="tree-stats">${doneNodes}/${totalNodes} nodes · ${categoryXP} XP earned</div>
        </div>
        <div class="tree-progress-ring">
            <svg viewBox="0 0 36 36">
                <circle cx="18" cy="18" r="15" fill="none" stroke="var(--line)" stroke-width="3"/>
                <circle cx="18" cy="18" r="15" fill="none"
                    stroke="${tree.color}" stroke-width="3"
                    stroke-dasharray="${progress} ${100 - progress}"
                    stroke-linecap="round"
                    transform="rotate(-90 18 18)"/>
            </svg>
            <span>${progress}%</span>
        </div>
    </div>
    <div class="tree-nodes">
        ${roots.map(r => renderNode(r, 0)).join("")}
    </div>
</div>`;
}

async function completeNode(nodeId, category) {
    await fetch(`/skills/${nodeId}/complete?category=${encodeURIComponent(category)}`, {
        method: "POST",
    });
    loadSkillTrees();
}

async function uncompleteNode(nodeId, category) {
    await fetch(`/skills/${nodeId}/complete?category=${encodeURIComponent(category)}`, {
        method: "DELETE",
    });
    loadSkillTrees();
}

// Boot: show journal page and load only what's needed for it
showPage("journal");
loadAIInsight();
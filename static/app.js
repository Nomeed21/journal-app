document.addEventListener("DOMContentLoaded", () => {

// ---------------------------------------------------------------------------
// Page navigation
// ---------------------------------------------------------------------------
const pages    = document.querySelectorAll(".page");
const navItems = document.querySelectorAll(".nav-item");

function showPage(pageId) {
    pages.forEach(p => p.classList.remove("active"));
    navItems.forEach(n => n.classList.remove("active"));
    const page = document.getElementById("page-" + pageId);
    if (page) page.classList.add("active");
    const nav  = document.querySelector(`.nav-item[data-page="${pageId}"]`);
    if (nav)   nav.classList.add("active");
    if (pageId === "entries")  loadEntries();
    if (pageId === "quests")   { loadGoals(); generateDailyQuest(); }
    if (pageId === "skills")   loadSkills();
    if (pageId === "habits")   loadStreaks();
    if (pageId === "insights") { loadCharts(); loadInsights(); }
    if (pageId === "review")   {}
    if (pageId === "journal")  loadProactiveCoaching();
}

navItems.forEach(item =>
    item.addEventListener("click", e => { e.preventDefault(); showPage(item.dataset.page); })
);

// ---------------------------------------------------------------------------
// XP / Level HUD (shown in sidebar)
// ---------------------------------------------------------------------------
async function loadXPHUD() {
    try {
        const data = await (await fetch("/achievements")).json();
        const info = data.level_info;
        const el   = document.getElementById("xp-hud");
        if (!el) return;
        el.innerHTML = `
            <div class="xp-hud-level">Lv ${info.level}</div>
            <div class="xp-hud-bar-wrap">
                <div class="xp-hud-bar-fill" style="width:${Math.round(info.xp_in_level/5)}%"></div>
            </div>
            <div class="xp-hud-text">${info.xp_in_level} / 500 XP</div>`;
    } catch (_) {}
}

// ---------------------------------------------------------------------------
// Achievement toast
// ---------------------------------------------------------------------------
function showAchievementToast(achievements) {
    if (!achievements || achievements.length === 0) return;
    achievements.forEach((ach, i) => {
        setTimeout(() => {
            const toast = document.createElement("div");
            toast.className = "achievement-toast";
            toast.innerHTML = `🏆 <strong>${ach.name}</strong> unlocked! +${ach.xp} XP`;
            document.body.appendChild(toast);
            setTimeout(() => toast.classList.add("show"), 50);
            setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 400); }, 3500);
        }, i * 600);
    });
    loadXPHUD();
}

// XP flash when a quest is completed
function showXPFlash(xp, category) {
    const el = document.createElement("div");
    el.className = "xp-flash";
    el.textContent = `+${xp} XP (${category})`;
    document.body.appendChild(el);
    setTimeout(() => el.classList.add("show"), 50);
    setTimeout(() => { el.classList.remove("show"); setTimeout(() => el.remove(), 400); }, 2000);
    loadXPHUD();
}

// ---------------------------------------------------------------------------
// Entry tabs
// ---------------------------------------------------------------------------
let currentEntryType   = "morning";
let editingId          = null;
let conversationHistory = [];

const entryTabs = document.querySelectorAll(".entry-tab");
const submitBtn = document.getElementById("entry-submit");
const TAB_LABELS = { morning: "Save Morning Entry", night: "Save Night Reflection", free: "Save Entry" };

function switchEntryTab(type) {
    currentEntryType = type;
    document.getElementById("entry-type").value = type;
    entryTabs.forEach(t => t.classList.toggle("active", t.dataset.type === type));
    document.getElementById("fields-morning").classList.toggle("hidden", type !== "morning");
    document.getElementById("fields-night").classList.toggle("hidden",   type !== "night");
    document.getElementById("fields-free").classList.toggle("hidden",    type !== "free");
    submitBtn.textContent = editingId ? "Update Entry" : (TAB_LABELS[type] || "Save Entry");
    if (type === "night") loadNightChecklist();
}

entryTabs.forEach(tab => tab.addEventListener("click", () => switchEntryTab(tab.dataset.type)));

// Slider wiring
[["m-mood","m-mood-val"],["m-energy","m-energy-val"],["m-focus","m-focus-val"],
 ["n-mood","n-mood-val"],["n-goal","n-goal-val"],["n-energy","n-energy-val"],["n-focus","n-focus-val"],
 ["f-mood","f-mood-val"],["f-energy","f-energy-val"],["f-focus","f-focus-val"]
].forEach(([sid, vid]) => {
    const slider = document.getElementById(sid), val = document.getElementById(vid);
    if (slider && val) slider.addEventListener("input", () => val.textContent = slider.value);
});

// ---------------------------------------------------------------------------
// Night checklist
// ---------------------------------------------------------------------------
let nightTasks = [];

async function loadNightChecklist() {
    let el = document.getElementById("night-plan-checklist");
    if (!el) {
        el = document.createElement("div");
        el.id = "night-plan-checklist";
        el.className = "field-group";
        const fn = document.getElementById("fields-night");
        fn.insertBefore(el, fn.firstChild);
    }
    el.innerHTML = "<p class='plan-loading'>Loading today's plan…</p>";
    try {
        const data = await (await fetch("/plans/today")).json();
        if (!data.plan || (!data.plan.main_goal && !(data.plan.tasks || []).length)) {
            el.innerHTML = "<p class='plan-loading'>No morning plan found — fill in a Morning entry first.</p>";
            nightTasks = [];
            return;
        }
        nightTasks = (data.plan.tasks || []).map(t => ({ ...t, completed: t.completed || false }));
        const goalLine = data.plan.main_goal
            ? `<div class="night-main-goal">🎯 <strong>${data.plan.main_goal}</strong></div>` : "";
        const taskRows = nightTasks.map((t, i) => `
            <label class="night-task-row">
                <input type="checkbox" class="night-check" data-index="${i}" ${t.completed ? "checked" : ""}>
                <span>${t.title}</span>
            </label>`).join("");
        el.innerHTML = `<label class="field-label">Today's Plan — How Did It Go?</label>${goalLine}
            ${taskRows || "<p class='plan-loading'>No tasks were planned.</p>"}`;
        el.querySelectorAll(".night-check").forEach(cb =>
            cb.addEventListener("change", () => { nightTasks[+cb.dataset.index].completed = cb.checked; })
        );
    } catch (_) {
        el.innerHTML = "<p class='plan-loading'>Could not load today's plan.</p>";
    }
}

// ---------------------------------------------------------------------------
// Entry form submit
// ---------------------------------------------------------------------------
const entryForm = document.getElementById("entry-form");
const gv = id => { const e = document.getElementById(id); return e ? e.value : ""; };
const gi = (id, fallback=3) => { const v = parseInt(gv(id)); return isNaN(v) ? fallback : v; };

entryForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    let entryData;

    if (currentEntryType === "morning") {
        const tasks = [gv("morning-task-1"), gv("morning-task-2"), gv("morning-task-3")]
            .map(s => s.trim()).filter(Boolean)
            .map((title, i) => ({ id: `t${i}`, title, completed: false }));
        entryData = {
            title:         gv("morning-main-goal").trim() || "Morning Entry",
            content:       [gv("morning-main-goal"),
                            gv("morning-obstacles") ? `Obstacles: ${gv("morning-obstacles")}` : "",
                            gv("morning-counterattack") ? `Plan: ${gv("morning-counterattack")}` : ""]
                           .filter(Boolean).join("\n"),
            mood: gi("m-mood"), goal_progress: 0,
            energy: gi("m-energy"), focus: gi("m-focus"), tags: [], entry_type: "morning",
        };
        if (gv("morning-main-goal").trim() || tasks.length) {
            await fetch("/plans", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ main_goal: gv("morning-main-goal").trim(), tasks }),
            });
        }
    } else if (currentEntryType === "night") {
        const parts = [
            gv("night-win")      ? `Win: ${gv("night-win")}` : "",
            gv("night-learned")  ? `Learned: ${gv("night-learned")}` : "",
            gv("night-well")     ? `Went well: ${gv("night-well")}` : "",
            gv("night-poorly")   ? `Went poorly: ${gv("night-poorly")}` : "",
            gv("night-grateful") ? `Grateful for: ${gv("night-grateful")}` : "",
            gv("night-tomorrow") ? `Tomorrow: ${gv("night-tomorrow")}` : "",
        ].filter(Boolean);
        entryData = {
            title: gv("night-win").trim().slice(0, 60) || "Night Reflection",
            content: parts.join("\n"),
            mood: gi("n-mood"), goal_progress: gi("n-goal", 50),
            energy: gi("n-energy"), focus: gi("n-focus"), tags: [], entry_type: "night",
        };
        if (nightTasks.length) {
            await fetch("/plans/today/reflect", {
                method: "PUT", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ tasks: nightTasks, reflection_note: gv("night-win") }),
            });
        }
    } else {
        const tagsRaw = gv("free-tags");
        entryData = {
            title: gv("free-title").trim() || "Journal Entry",
            content: gv("free-content"),
            mood: gi("f-mood"), goal_progress: 0,
            energy: gi("f-energy"), focus: gi("f-focus"),
            tags: tagsRaw ? tagsRaw.split(",").map(t => t.trim()).filter(Boolean) : [],
            entry_type: "free",
        };
    }

    let res;
    if (editingId) {
        res = await fetch(`/entries/${editingId}`, {
            method: "PUT", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(entryData),
        });
    } else {
        res = await fetch("/entries", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify(entryData),
        });
    }
    if (!res.ok) return;
    const saved = await res.json();

    // Show achievement toasts from the entry creation response
    if (saved.new_achievements) showAchievementToast(saved.new_achievements);

    // Run action engine in background
    fetch("/action-engine", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            mood: entryData.mood, goal_progress: entryData.goal_progress,
            content: entryData.content, energy: entryData.energy || 3,
            focus: entryData.focus || 3, entry_type: currentEntryType,
        }),
    }).then(r => r.json()).then(data => {
        if (data.triggered && data.action) showActionBanner(data);
    }).catch(() => {});

    // Auto-generate quests from this entry (non-blocking)
    if (!editingId) {
        fetch("/journal/generate-quests", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content: entryData.content, mood: entryData.mood, entry_type: currentEntryType }),
        }).then(r => r.json()).then(data => {
            if (data.quests && data.quests.length) showQuestSuggestions(data.quests);
        }).catch(() => {});
    }

    resetEntryForm();
    loadAIInsight();
    loadXPHUD();
    loadProactiveCoaching();
});

// ---------------------------------------------------------------------------
// Action engine banner
// ---------------------------------------------------------------------------
function showActionBanner(data) {
    let banner = document.getElementById("action-banner");
    if (!banner) {
        banner = document.createElement("div");
        banner.id = "action-banner";
        banner.className = "action-banner";
        const form = document.getElementById("entry-form");
        form.parentNode.insertBefore(banner, form.nextSibling);
    }
    const a = data.action;
    banner.innerHTML = `
        <div class="action-banner-header">
            <span class="action-banner-label">⚡ Action Engine</span>
            <button class="action-banner-close" onclick="this.closest('.action-banner').remove()">✕</button>
        </div>
        <div class="action-banner-body"><strong>${a.action}</strong>
            <span style="font-size:.85rem;color:var(--ink-soft)"> — ${a.reason}</span></div>
        <div class="action-banner-footer">
            <span class="dq-chip">${a.category}</span>
            <span class="dq-chip">⏱ ${a.duration_minutes}m</span>
            <span class="dq-chip">+${a.xp} XP</span>
            ${data.quest_created ? '<span class="dq-chip dq-chip--success">✓ Added to Quests</span>' : ''}
        </div>`;
    banner.classList.add("show");
}

// ---------------------------------------------------------------------------
// Quest suggestions from journal
// ---------------------------------------------------------------------------
function showQuestSuggestions(quests) {
    let panel = document.getElementById("quest-suggestions");
    if (!panel) {
        panel = document.createElement("div");
        panel.id = "quest-suggestions";
        panel.className = "quest-suggestions";
        const form = document.getElementById("entry-form");
        form.parentNode.insertBefore(panel, form.nextSibling);
    }
    panel.innerHTML = `
        <div class="qs-header">
            <span class="qs-label">✦ Quests from your entry</span>
            <button class="action-banner-close" onclick="this.closest('.quest-suggestions').remove()">✕</button>
        </div>
        ${quests.map((q, i) => `
            <div class="qs-item">
                <div class="qs-title">${q.title}</div>
                <div class="qs-meta"><span class="dq-chip">${q.category}</span>
                    <span class="dq-chip">${q.difficulty}</span>
                    <span class="dq-chip">⏱ ${q.time_minutes}m</span>
                    <span style="font-size:.8rem;color:var(--ink-soft)">${q.reason}</span></div>
                <button class="qs-add-btn" onclick="addQuestFromSuggestion('${q.title.replace(/'/g,"\\'")}', '${q.category}', this)">
                    + Add Quest</button>
            </div>`).join("")}`;
    panel.classList.add("show");
}

window.addQuestFromSuggestion = async function(title, category, btn) {
    // Find or create a goal in that category
    const goalsRes  = await fetch("/goals");
    const goals     = await goalsRes.json();
    let goal        = goals.find(g => g.category === category);
    if (!goal) {
        const newGoal = await fetch("/goals", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: `${category} Goals`, category }),
        }).then(r => r.json());
        goal = newGoal.goal;
    }
    await fetch(`/goals/${goal.id}/tasks`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
    });
    btn.textContent = "✓ Added";
    btn.disabled    = true;
};

// ---------------------------------------------------------------------------
// Proactive coaching alert on Journal page
// ---------------------------------------------------------------------------
async function loadProactiveCoaching() {
    try {
        const data = await (await fetch("/coaching/proactive")).json();
        let el     = document.getElementById("proactive-coaching");
        if (!el) return;
        if (!data.needs_attention) {
            el.style.display = "none";
            return;
        }
        el.style.display = "";
        el.innerHTML = `
            <div class="proactive-label">🔔 Coach Alert</div>
            <div class="proactive-nudge">${data.nudge}</div>
            <div class="proactive-alerts">
                ${data.alerts.map(a => `<span class="proactive-chip">${a}</span>`).join("")}
            </div>`;
    } catch (_) {}
}

// ---------------------------------------------------------------------------
// Form reset
// ---------------------------------------------------------------------------
function resetEntryForm() {
    editingId = null;
    entryForm.reset();
    ["m-mood-val","m-energy-val","m-focus-val","n-mood-val","n-goal-val",
     "n-energy-val","n-focus-val","f-mood-val","f-energy-val","f-focus-val"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = id.includes("goal") ? "50" : "3";
    });
    nightTasks = [];
    switchEntryTab("morning");
}

// ---------------------------------------------------------------------------
// Entries page
// ---------------------------------------------------------------------------
const entriesDiv = document.getElementById("entries");
const TYPE_BADGE = { morning: "🌅 Morning", night: "🌙 Night", free: "📓 Free" };

async function loadEntries(filters = {}) {
    const params = new URLSearchParams();
    if (filters.tag)     params.append("tag",     filters.tag);
    if (filters.keyword) params.append("keyword", filters.keyword);
    const entries = await (await fetch(`/entries?${params}`)).json();
    entriesDiv.innerHTML = entries.map(e => {
        const type  = e.entry_type || "free";
        const badge = TYPE_BADGE[type] || type;
        return `<div class="entry-card">
            <div class="entry-card-header">
                <strong>${e.title}</strong>
                <span class="entry-type-badge entry-type-badge--${type}">${badge}</span>
            </div>
            <p>${e.content.replace(/\n/g, "<br>")}</p>
            <div class="meta">${e.created_at.slice(0,10)} | Mood: ${e.mood}/5 | Goal: ${e.goal_progress}%</div>
            ${e.tags && e.tags.length ? `<div class="tags">${e.tags.map(t => `<span>${t}</span>`).join("")}</div>` : ""}
            <div class="actions">
                <button onclick="window.editEntry(${e.id},'${e.title.replace(/'/g,"\\'")}',
                    '${e.content.replace(/'/g,"\\'").replace(/\n/g,"\\n")}',
                    ${e.mood},${e.goal_progress},'${(e.tags||[]).join(",")}','${type}')">Edit</button>
                <button class="delete-btn" onclick="window.deleteEntry(${e.id})">Delete</button>
            </div>
        </div>`;
    }).join("") || "<p style='color:var(--ink-faint);font-style:italic'>No entries yet.</p>";
}

window.editEntry = async function(id, title, content, mood, goalProgress, tags, entryType) {
    editingId = id;
    showPage("journal");
    switchEntryTab(entryType || "free");
    if (entryType === "morning") {
        document.getElementById("morning-main-goal").value = title || "";
        const lines   = content.split("\\n");
        const obsLine = lines.find(l => l.startsWith("Obstacles:"));
        const planLine= lines.find(l => l.startsWith("Plan:"));
        if (obsLine)  document.getElementById("morning-obstacles").value    = obsLine.replace("Obstacles: ","");
        if (planLine) document.getElementById("morning-counterattack").value = planLine.replace("Plan: ","");
        document.getElementById("m-mood").value = mood;
        document.getElementById("m-mood-val").textContent = mood;
    } else if (entryType === "night") {
        const lines   = content.split("\\n");
        const get     = (p) => (lines.find(l => l.startsWith(p)) || "").replace(p,"");
        document.getElementById("night-win").value       = get("Win: ");
        document.getElementById("night-learned").value   = get("Learned: ");
        document.getElementById("night-well").value      = get("Went well: ");
        document.getElementById("night-poorly").value    = get("Went poorly: ");
        document.getElementById("night-grateful").value  = get("Grateful for: ");
        document.getElementById("night-tomorrow").value  = get("Tomorrow: ");
        document.getElementById("n-mood").value          = mood;
        document.getElementById("n-mood-val").textContent = mood;
        document.getElementById("n-goal").value          = goalProgress;
        document.getElementById("n-goal-val").textContent = goalProgress;
    } else {
        document.getElementById("free-title").value   = title || "";
        document.getElementById("free-content").value = content.replace(/\\n/g,"\n");
        document.getElementById("free-tags").value    = tags || "";
        document.getElementById("f-mood").value       = mood;
        document.getElementById("f-mood-val").textContent = mood;
    }
    submitBtn.textContent = "Update Entry";
    document.getElementById("entry-form").scrollIntoView({ behavior: "smooth" });
};

window.deleteEntry = async function(id) {
    if (!confirm("Delete this entry?")) return;
    if ((await fetch(`/entries/${id}`, { method: "DELETE" })).ok) loadEntries();
};

document.getElementById("filter-btn").addEventListener("click", () =>
    loadEntries({ keyword: document.getElementById("filter-keyword").value,
                  tag:     document.getElementById("filter-tag").value }));
document.getElementById("clear-btn").addEventListener("click", () => {
    document.getElementById("filter-keyword").value = "";
    document.getElementById("filter-tag").value     = "";
    loadEntries();
});

// ---------------------------------------------------------------------------
// Habits
// ---------------------------------------------------------------------------
const streaksDiv = document.getElementById("streaks");
const habitForm  = document.getElementById("habit-form");

async function loadStreaks() {
    const streaks  = await (await fetch("/habits/streaks")).json();
    const entries  = Object.entries(streaks);
    // Also show predictive streak risk
    let riskData = {};
    try { riskData = await (await fetch("/analytics/predictive")).json(); } catch (_) {}
    const atRisk = riskData.streak_at_risk || [];
    streaksDiv.innerHTML = entries.length === 0
        ? "<p style='color:var(--ink-faint);font-style:italic'>No habits logged yet.</p>"
        : entries.map(([name, data]) => {
            const risk = atRisk.includes(name);
            return `<div class="entry-card ${risk ? 'streak-at-risk' : ''}">
                <strong>${name}</strong>
                ${risk ? '<span class="risk-badge">⚠️ At risk today!</span>' : ''}
                — ${data.current_streak}-day streak (${data.total_logs} total logs)
            </div>`;
        }).join("");
}

habitForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = document.getElementById("habit-name").value.trim();
    const data = await (await fetch("/habits", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
    })).json();
    if (data.new_achievements) showAchievementToast(data.new_achievements);
    habitForm.reset();
    loadStreaks();
    loadXPHUD();
});

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------
const chatMessages = document.getElementById("chat-messages");
const chatForm     = document.getElementById("chat-form");

chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input   = document.getElementById("chat-input");
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    chatMessages.innerHTML += `<div class="chat-msg user">${message}</div>`;
    chatMessages.scrollTop  = chatMessages.scrollHeight;
    const data = await (await fetch("/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, history: conversationHistory }),
    })).json();
    conversationHistory.push({ role: "user",      content: message });
    conversationHistory.push({ role: "assistant", content: data.response });
    chatMessages.innerHTML += `<div class="chat-msg assistant">${data.response}</div>`;
    chatMessages.scrollTop  = chatMessages.scrollHeight;
});

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------
async function loadCharts() {
    const [trendsRes, corrRes] = await Promise.all([
        fetch("/entries/trends?days=30"), fetch("/entries/correlations"),
    ]);
    const trends = await trendsRes.json(), correlations = await corrRes.json();

    new Chart(document.getElementById("trends-chart").getContext("2d"), {
        type: "line",
        data: {
            labels: trends.map(t => t.date),
            datasets: [
                { label: "Mood (1-5)",        data: trends.map(t => t.avg_mood), borderColor: "#d98aa0", backgroundColor: "rgba(217,138,160,0.1)", yAxisID: "y",  tension: 0.3 },
                { label: "Goal Progress (%)", data: trends.map(t => t.avg_goal), borderColor: "#b8617c", backgroundColor: "rgba(184,97,124,0.1)",   yAxisID: "y1", tension: 0.3 },
            ],
        },
        options: { responsive: true, maintainAspectRatio: false,
            scales: {
                y:  { min: 1, max: 5,   position: "left",  title: { display: true, text: "Mood" } },
                y1: { min: 0, max: 100, position: "right", title: { display: true, text: "Goal %" }, grid: { drawOnChartArea: false } },
            }},
    });

    new Chart(document.getElementById("correlation-chart").getContext("2d"), {
        type: "bar",
        data: {
            labels: correlations.map(c => c.day),
            datasets: [{ label: "Avg Mood", data: correlations.map(c => c.avg_mood), backgroundColor: "rgba(217,138,160,0.6)" }],
        },
        options: { responsive: true, maintainAspectRatio: false,
            scales: { y: { min: 0, max: 5, title: { display: true, text: "Avg Mood" } } }},
    });
}

// ---------------------------------------------------------------------------
// Insights
// ---------------------------------------------------------------------------
async function loadInsights() {
    const data = await (await fetch("/insights")).json();
    document.getElementById("insights").innerHTML = data.insights.map(i => `
        <div class="insight-card ${i.type}">
            <h3>${i.title}</h3><p>${i.message}</p>
            <small>💡 ${i.recommendation}</small>
        </div>`).join("");
}

async function loadAIInsight() {
    const data = await (await fetch("/ai-insight")).json();
    document.getElementById("ai-insight").textContent = data.insight;
}

// ---------------------------------------------------------------------------
// Monthly review
// ---------------------------------------------------------------------------
document.getElementById("generate-review").addEventListener("click", async () => {
    const el = document.getElementById("monthly-review");
    el.textContent = "Generating…";
    const data = await (await fetch("/monthly-review")).json();
    el.innerHTML = data.review.replace(/\n/g, "<br>");
});

// ---------------------------------------------------------------------------
// Goals & Quests
// ---------------------------------------------------------------------------
const goalsDiv = document.getElementById("goals");
const goalForm = document.getElementById("goal-form");

async function loadGoals() {
    const goals = await (await fetch("/goals")).json();
    goalsDiv.innerHTML = goals.map(g => {
        // Task list with toggle checkboxes
        const taskList = g.tasks && g.tasks.length
            ? `<div class="task-list">
                ${g.tasks.map(t => `
                    <label class="task-row ${t.is_completed ? 'task-done' : ''}">
                        <input type="checkbox" class="task-check"
                            onchange="toggleTask(${t.id}, this, ${g.id})"
                            ${t.is_completed ? 'checked' : ''}>
                        <span class="task-title">${t.title}</span>
                    </label>`).join("")}
               </div>`
            : `<p class="task-empty">No tasks yet — add one below.</p>`;

        // Inline add-task form
        const addTaskForm = `
            <div class="add-task-row">
                <input type="text" class="add-task-input" id="task-input-${g.id}"
                    placeholder="Add a task…" onkeydown="if(event.key==='Enter'){addTask(${g.id});event.preventDefault();}">
                <button class="add-task-btn" onclick="addTask(${g.id})">+ Add</button>
            </div>`;

        // Milestone list
        const msSection = g.milestones && g.milestones.length
            ? `<div class="ms-section">
                <div class="ms-label">🏁 Milestones (${g.milestones_done}/${g.milestones_total})</div>
                ${g.milestones.map(m => `
                    <label class="ms-item ${m.is_completed ? 'ms-done' : ''}">
                        <input type="checkbox" onchange="toggleMilestone(${m.id}, this)" ${m.is_completed ? 'checked' : ''}>
                        <span>${m.title}${m.target_date ? ` <em class="ms-date">by ${m.target_date}</em>` : ""}</span>
                    </label>`).join("")}
               </div>` : "";

        // Inline add-milestone form
        const addMsForm = `
            <div class="add-ms-row" id="ms-form-${g.id}" style="display:none">
                <input type="text" id="ms-title-${g.id}" placeholder="Milestone title…">
                <input type="date" id="ms-date-${g.id}">
                <button onclick="addMilestone(${g.id})">Add</button>
                <button class="btn-ghost" onclick="document.getElementById('ms-form-${g.id}').style.display='none'">Cancel</button>
            </div>`;

        return `<div class="goal-card" id="goal-${g.id}">
            <div class="goal-header">
                <div>
                    <strong class="goal-title">${g.title}</strong>
                    <span class="goal-category">${g.category}</span>
                </div>
                <span class="goal-level-badge">Lv ${g.level} · ${g.xp} XP</span>
            </div>
            <div class="goal-stats">
                <span>${g.completed_tasks}/${g.total_tasks} tasks complete</span>
                <span class="goal-pct">${g.progress}%</span>
            </div>
            <div class="progress-bar"><div class="progress-fill" style="width:${g.progress}%"></div></div>

            <div class="goal-section-label">Tasks</div>
            ${taskList}
            ${addTaskForm}

            ${msSection}
            ${addMsForm}

            <div class="goal-actions">
                <button class="btn-ghost goal-ms-btn" onclick="
                    const f=document.getElementById('ms-form-${g.id}');
                    f.style.display=f.style.display==='none'?'flex':'none'">
                    + Milestone
                </button>
                <button class="btn-ghost goal-delete-btn" onclick="deleteGoal(${g.id})">Delete goal</button>
            </div>
        </div>`;
    }).join("") || "<p class='empty-state'>No goals yet — add one above to get started.</p>";
}

goalForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    await fetch("/goals", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            title:    document.getElementById("goal-title").value,
            category: document.getElementById("goal-category").value,
        }),
    });
    goalForm.reset();
    loadGoals();
});

// Milestone toggle
window.toggleMilestone = async function(id, cb) {
    cb.disabled = true;
    const data = await (await fetch(`/milestones/${id}`, { method: "PUT" })).json();
    if (data.is_completed) showXPFlash(75, "Milestone");
    loadGoals();
    loadXPHUD();
};

// Inline add milestone
window.addMilestone = async function(goalId) {
    const title  = document.getElementById(`ms-title-${goalId}`).value.trim();
    if (!title) return;
    const target = document.getElementById(`ms-date-${goalId}`).value || null;
    await fetch(`/goals/${goalId}/milestones`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, target_date: target }),
    });
    loadGoals();
};

// Toggle task completion
window.toggleTask = async function(taskId, cb, goalId) {
    cb.disabled = true;
    const data = await (await fetch(`/tasks/${taskId}`, { method: "PUT" })).json();
    if (data.xp_earned) showXPFlash(data.xp_earned, data.category || "Goal");
    if (data.new_achievements) showAchievementToast(data.new_achievements);
    loadGoals();
    loadXPHUD();
};

// Add a new task to a goal
window.addTask = async function(goalId) {
    const input = document.getElementById(`task-input-${goalId}`);
    const title = input.value.trim();
    if (!title) return;
    await fetch(`/goals/${goalId}/tasks`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
    });
    loadGoals();
};

// Delete a goal
window.deleteGoal = async function(goalId) {
    if (!confirm("Delete this goal and all its tasks?")) return;
    await fetch(`/goals/${goalId}`, { method: "DELETE" });
    loadGoals();
};

// Daily quest
async function generateDailyQuest() {
    const body   = document.getElementById("dq-body");
    const footer = document.getElementById("dq-footer");
    body.textContent = "Generating your quest…";
    footer.textContent = "";
    try {
        const data = await (await fetch("/daily-quest", { method: "POST" })).json();
        if (!data.task) {
            body.textContent = data.message || "All quests complete!";
            return;
        }
        body.innerHTML = `<strong>${data.task}</strong><br>
            <span style="font-size:.88rem;opacity:.8">${data.why}</span>`;
        footer.innerHTML = `<span class="dq-chip">${data.category}</span>
            <span class="dq-chip">${data.difficulty}</span>
            <span class="dq-chip">⏱ ${data.time}m</span>
            <span class="dq-chip">+${data.xp} XP</span>`;
    } catch (_) { body.textContent = "Could not generate quest."; }
}
window.generateDailyQuest = generateDailyQuest;

// ---------------------------------------------------------------------------
// Skills
// ---------------------------------------------------------------------------
async function loadSkills() {
    const [trees, achievementsData] = await Promise.all([
        fetch("/skills").then(r => r.json()),
        fetch("/achievements").then(r => r.json()),
    ]);

    const container = document.getElementById("skill-trees");

    // Global level banner
    const info = achievementsData.level_info;
    container.innerHTML = `
        <div class="skill-level-banner">
            <div class="slb-level">Level ${info.level}</div>
            <div class="slb-xp-bar-wrap">
                <div class="slb-xp-bar-fill" style="width:${Math.round(info.xp_in_level/5)}%"></div>
            </div>
            <div class="slb-xp-text">${info.xp_in_level} / 500 XP · ${info.xp_to_next} to next level</div>
        </div>
        <div class="skill-explainer">
            <strong>How Skills work:</strong>
            Complete tasks in a category to earn XP → XP unlocks skill nodes → click
            <em>Check Mastery</em> on an unlocked node → answer the prompt honestly →
            pass to mark it Mastered and unlock the next tier.
            <span class="skill-legend">
                <span class="sleg sleg--unlocked">Unlocked</span>
                <span class="sleg sleg--completed">Mastered</span>
                <span class="sleg sleg--locked">Locked</span>
            </span>
        </div>`;

    trees.forEach(tree => {
        const treeEl = document.createElement("div");
        treeEl.className = "skill-tree";
        treeEl.innerHTML = `
            <div class="skill-tree-header">
                <span>${tree.icon} ${tree.label}</span>
                <div style="display:flex;align-items:center;gap:.5rem">
                    <span class="skill-xp">${tree.category_xp} XP</span>
                    <button class="skill-path-btn" onclick="showProgressionPath('${tree.category}')">Path →</button>
                </div>
            </div>
            <div class="skill-nodes">
                ${tree.nodes.map(node => `
                    <div class="skill-node ${node.completed ? "completed" : node.unlocked ? "unlocked" : "locked"}">
                        <div class="skill-node-name">${node.name}</div>
                        <div class="skill-node-desc">${node.description}</div>
                        ${node.leads_to && node.leads_to.length ? `<div class="skill-leads-to">→ Unlocks: ${node.leads_to.join(", ")}</div>` : ""}
                        ${node.unlocked && !node.completed
                            ? `<button class="skill-complete-btn" onclick="openMasteryCheck('${node.id}','${tree.category}','${node.name.replace(/'/g,"\\'")}')">
                                Check Mastery ✓</button>`
                            : node.completed
                            ? `<span class="skill-done">✓ Mastered</span>`
                            : (() => {
                                const needsXp = !node.xp_met ? `${node.xp_required} XP in ${tree.label}` : "";
                                const needsPrereqs = !node.prereqs_met && node.prerequisites && node.prerequisites.length
                                    ? `master: ${node.prerequisites.join(", ")}` : "";
                                const reqs = [needsXp, needsPrereqs].filter(Boolean).join(" · ");
                                return `<span class="skill-locked">🔒 Needs: ${reqs || "prerequisites"}</span>`;
                              })()
                        }
                    </div>`).join("")}
            </div>`;
        container.appendChild(treeEl);
    });

    // Achievements section
    const earned = achievementsData.earned || [];
    if (earned.length) {
        const achEl = document.createElement("div");
        achEl.className = "achievements-section";
        achEl.innerHTML = `
            <h3 style="font-family:var(--font-display);margin-bottom:.75rem">🏆 Achievements</h3>
            <div class="achievements-grid">
                ${earned.map(a => `<div class="achievement-badge">
                    <strong>${a.name}</strong>
                    <small>${a.earned_at.slice(0,10)}</small>
                </div>`).join("")}
            </div>`;
        container.appendChild(achEl);
    }
}

// Mastery check modal
window.openMasteryCheck = async function(nodeId, category, nodeName) {
    try {
        const checkData = await (await fetch(`/skills/${nodeId}/mastery-check?category=${encodeURIComponent(category)}`)).json();

        if (checkData.already_passed) {
            // Already passed — go straight to completion
            await completeSkillNode(nodeId, category);
            return;
        }

        // Build modal
        let modal = document.getElementById("mastery-modal");
        if (!modal) {
            modal = document.createElement("div");
            modal.id        = "mastery-modal";
            modal.className = "mastery-modal-overlay";
            document.body.appendChild(modal);
        }
        const typeLabel = { reflection: "📖 Reflection", quiz: "🧠 Quiz", challenge: "⚡ Challenge", proof: "📋 Proof of Learning" };
        modal.innerHTML = `
            <div class="mastery-modal-box">
                <div class="mastery-modal-header">
                    <div class="mastery-modal-title">${typeLabel[checkData.type] || "Mastery Check"}: ${nodeName}</div>
                    <button class="mastery-modal-close" onclick="document.getElementById('mastery-modal').style.display='none'">✕</button>
                </div>
                <div class="mastery-modal-prompt">${checkData.prompt}</div>
                <textarea id="mastery-response" class="mastery-response-input"
                    placeholder="Write your response here. Be specific and honest — vague answers won't pass." rows="6"></textarea>
                <div id="mastery-feedback" class="mastery-feedback hidden"></div>
                <div style="display:flex;gap:.5rem;margin-top:1rem">
                    <button class="mastery-submit-btn" onclick="submitMasteryCheck('${nodeId}','${category}','${nodeName.replace(/'/g,"\\'")}')">
                        Submit for Evaluation</button>
                    <button style="background:var(--paper);color:var(--ink-soft);border:1px solid var(--line)"
                        onclick="document.getElementById('mastery-modal').style.display='none'">Cancel</button>
                </div>
            </div>`;
        modal.style.display = "flex";
    } catch (_) {}
};

window.submitMasteryCheck = async function(nodeId, category, nodeName) {
    const response = document.getElementById("mastery-response").value.trim();
    if (!response) { alert("Please write a response first."); return; }
    const btn      = document.querySelector(".mastery-submit-btn");
    btn.textContent = "Evaluating…";
    btn.disabled    = true;
    try {
        const result = await (await fetch(
            `/skills/${nodeId}/mastery-check?category=${encodeURIComponent(category)}`,
            { method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ response }) }
        )).json();
        const fb = document.getElementById("mastery-feedback");
        fb.classList.remove("hidden");
        fb.className = `mastery-feedback ${result.passed ? "mastery-passed" : "mastery-failed"}`;
        fb.innerHTML = `
            <strong>${result.passed ? "✓ Passed!" : "✗ Not quite"}</strong> (Score: ${result.score}/100)
            <p>${result.feedback}</p>
            ${result.passed && result.what_was_good ? `<p>👍 ${result.what_was_good}</p>` : ""}
            ${!result.passed && result.what_to_improve ? `<p>💡 ${result.what_to_improve}</p>` : ""}`;
        if (result.passed) {
            const completeBtn = document.createElement("button");
            completeBtn.textContent = "✓ Mark as Mastered";
            completeBtn.className   = "mastery-submit-btn";
            completeBtn.style.marginTop = ".75rem";
            completeBtn.onclick = async () => {
                document.getElementById("mastery-modal").style.display = "none";
                await completeSkillNode(nodeId, category);
            };
            fb.appendChild(completeBtn);
        } else {
            btn.textContent = "Try Again";
            btn.disabled    = false;
        }
    } catch (_) {
        btn.textContent = "Submit for Evaluation";
        btn.disabled    = false;
    }
};

async function completeSkillNode(nodeId, category) {
    try {
        const data = await (await fetch(
            `/skills/${nodeId}/complete?category=${encodeURIComponent(category)}`,
            { method: "POST" }
        )).json();
        showXPFlash(data.xp_earned, category);
        if (data.new_achievements) showAchievementToast(data.new_achievements);
        if (data.newly_unlocked && data.newly_unlocked.length) {
            setTimeout(() => {
                const toast = document.createElement("div");
                toast.className = "achievement-toast achievement-toast--unlock";
                toast.innerHTML = `🔓 Unlocked: <strong>${data.newly_unlocked.join(", ")}</strong>`;
                document.body.appendChild(toast);
                setTimeout(() => toast.classList.add("show"), 50);
                setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 400); }, 4000);
            }, 800);
        }
        loadSkills();
        loadXPHUD();
    } catch (_) {}
}

// Progression path panel
window.showProgressionPath = async function(category) {
    try {
        const data = await (await fetch(`/progression/${encodeURIComponent(category)}`)).json();
        let panel  = document.getElementById("progression-panel");
        if (!panel) {
            panel = document.createElement("div");
            panel.id = "progression-panel";
            panel.className = "progression-panel";
            document.getElementById("skill-trees").prepend(panel);
        }
        const recommended = data.recommended;
        panel.innerHTML = `
            <div class="progression-header">
                <strong>${category} Path</strong>
                <button onclick="this.closest('.progression-panel').remove()" style="background:none;border:none;color:var(--ink-soft);cursor:pointer">✕</button>
            </div>
            <div class="progression-body">
                ${data.completed.length ? `<div class="prog-section"><div class="prog-label">✓ Mastered</div>
                    ${data.completed.map(n => `<span class="prog-chip prog-chip--done">${n.name}</span>`).join("")}</div>` : ""}
                ${data.in_progress.length ? `<div class="prog-section"><div class="prog-label">⚡ In Progress (Unlocked)</div>
                    ${data.in_progress.map(n => `<span class="prog-chip prog-chip--active">${n.name}</span>`).join("")}</div>` : ""}
                ${recommended ? `<div class="prog-section prog-recommended">
                    <div class="prog-label">★ Recommended Next</div>
                    <strong>${recommended.name}</strong> — ${recommended.description}
                    <button class="skill-path-btn" style="margin-top:.4rem" 
                        onclick="openMasteryCheck('${recommended.id}','${category}','${recommended.name.replace(/'/g,"\\'")}')">
                        Start Mastery Check</button>
                </div>` : ""}
                ${data.locked.length ? `<div class="prog-section"><div class="prog-label">🔒 Locked</div>
                    ${data.locked.map(n => `<span class="prog-chip prog-chip--locked" title="XP needed: ${n.unlocked_by?.xp_needed||0}">${n.name}</span>`).join("")}</div>` : ""}
            </div>`;
    } catch (_) {}
};

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
loadAIInsight();
loadXPHUD();
switchEntryTab("morning");
loadProactiveCoaching();

}); // end DOMContentLoaded
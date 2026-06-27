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
    if (pageId === "journal")  { loadProactiveCoaching(); loadTodayStatus(); }
    if (pageId === "domains")  loadDomains();
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

let todayDone = { morning: false, night: false, free: false };

async function loadTodayStatus() {
    try {
        const data = await (await fetch("/entries/today-status")).json();
        todayDone = { morning: data.morning, night: data.night, free: data.free };
        // Update tab badges
        entryTabs.forEach(tab => {
            const type = tab.dataset.type;
            const done = todayDone[type];
            tab.classList.toggle("entry-tab--done", done);
            // Update label: add checkmark if done
            const base = { morning: "🌅 Morning", night: "🌙 Night", free: "📓 Free" }[type];
            tab.textContent = done ? base + " ✓" : base;
        });
        // Refresh current tab state
        applyTabDoneState(currentEntryType);
    } catch (_) {}
}

function applyTabDoneState(type) {
    const done = !editingId && todayDone[type];
    submitBtn.disabled = done;
    submitBtn.textContent = editingId
        ? "Update Entry"
        : done
            ? `${type.charAt(0).toUpperCase()+type.slice(1)} entry already saved today`
            : (TAB_LABELS[type] || "Save Entry");

    // Show/hide the "edit today's entry" link
    let editLink = document.getElementById("edit-today-link");
    if (done && !editingId) {
        if (!editLink) {
            editLink = document.createElement("div");
            editLink.id = "edit-today-link";
            editLink.className = "edit-today-link";
            submitBtn.parentNode.insertBefore(editLink, submitBtn.nextSibling);
        }
        editLink.innerHTML = `<a href="#" id="edit-today-btn">Edit today's ${type} entry instead →</a>`;
        document.getElementById("edit-today-btn").addEventListener("click", async (e) => {
            e.preventDefault();
            const today = new Date().toISOString().slice(0,10);
            const entries = await (await fetch(`/entries?start_date=${today}T00:00:00Z`)).json();
            const match = entries.find(en => en.entry_type === type);
            if (match) window.editEntry(match.id, match.title, match.content, match.mood, (match.tags||[]).join(","), match.entry_type);
        });
    } else if (editLink) {
        editLink.remove();
    }
}

function switchEntryTab(type) {
    currentEntryType = type;
    document.getElementById("entry-type").value = type;
    entryTabs.forEach(t => t.classList.toggle("active", t.dataset.type === type));
    document.getElementById("fields-morning").classList.toggle("hidden", type !== "morning");
    document.getElementById("fields-night").classList.toggle("hidden",   type !== "night");
    document.getElementById("fields-free").classList.toggle("hidden",    type !== "free");
    if (type === "night") loadNightChecklist();
    applyTabDoneState(type);
}

entryTabs.forEach(tab => tab.addEventListener("click", () => switchEntryTab(tab.dataset.type)));

// Slider wiring
[["m-mood","m-mood-val"],["m-energy","m-energy-val"],["m-focus","m-focus-val"],
 ["n-mood","n-mood-val"],["n-energy","n-energy-val"],["n-focus","n-focus-val"],
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
        // Fetch plan and habits independently so one failure doesn't kill the other
        let data = { plan: null }, streaks = {};
        try {
            const planRes = await fetch("/plans/today");
            if (planRes.ok) data = await planRes.json();
        } catch (_) {}
        try {
            const streaksRes = await fetch("/habits/balance");
            if (streaksRes.ok) {
                const habData = await streaksRes.json();
                streaks = habData.streaks || {};
            }
        } catch (_) {}
        // Habit checklist
        const habitNames = Object.keys(streaks);
        let habitSection = "";
        if (habitNames.length) {
            habitSection = `
                <div class="ms-label" style="margin-top:.75rem">Today's Habits</div>
                ${habitNames.map(name => {
                    const s = streaks[name];
                    const cat = s.category || "Productivity";
                    return `<label class="night-task-row">
                        <input type="checkbox" class="night-habit-check" data-name="${name}" data-cat="${cat}">
                        <span>${name} <em style="font-size:.75rem;color:var(--ink-faint)">${s.current_streak}-day streak</em></span>
                    </label>`;
                }).join("")}`;
        }

        if (!data.plan || (!data.plan.main_goal && !(data.plan.tasks || []).length)) {
            el.innerHTML = `<p class='plan-loading'>No morning plan found.</p>${habitSection}`;
            nightTasks = [];
        } else {
            nightTasks = (data.plan.tasks || []).map(t => ({ ...t, completed: t.completed || false }));
            const goalLine = data.plan.main_goal
                ? `<div class="night-main-goal">🎯 <strong>${data.plan.main_goal}</strong></div>` : "";
            const taskRows = nightTasks.map((t, i) => `
                <label class="night-task-row">
                    <input type="checkbox" class="night-check" data-index="${i}" ${t.completed ? "checked" : ""}>
                    <span>${t.title}</span>
                </label>`).join("");
            el.innerHTML = `<label class="field-label">Today's Plan — How Did It Go?</label>${goalLine}
                ${taskRows || "<p class='plan-loading'>No tasks were planned.</p>"}
                ${habitSection}`;
        }
        el.querySelectorAll(".night-check").forEach(cb =>
            cb.addEventListener("change", () => { nightTasks[+cb.dataset.index].completed = cb.checked; })
        );
        // Quick-log habits from night reflection
        el.querySelectorAll(".night-habit-check").forEach(cb => {
            cb.addEventListener("change", async () => {
                if (cb.checked) {
                    await fetch("/habits", {
                        method: "POST", headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ name: cb.dataset.name, category: cb.dataset.cat, difficulty: "Normal" }),
                    });
                }
            });
        });
    } catch (_) {
        el.innerHTML = "<p class='plan-loading'>Error rendering night checklist. Check the console.</p>";
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
            mood: gi("m-mood"),
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
            mood: gi("n-mood"),
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
            mood: gi("f-mood"),
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

    // Guard: already written today — offer to edit instead
    if (saved.status === "already_exists") {
        const toast = document.createElement("div");
        toast.className = "achievement-toast show";
        toast.style.background = "#e65100";
        toast.innerHTML = `📝 ${saved.message}`;
        document.body.appendChild(toast);
        setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 400); }, 4000);
        loadTodayStatus();
        return;
    }

    // Show achievement toasts from the entry creation response
    if (saved.new_achievements) showAchievementToast(saved.new_achievements);

    // Run action engine in background
    fetch("/action-engine", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            mood: entryData.mood,
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
    loadTodayStatus();
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
    ["m-mood-val","m-energy-val","m-focus-val","n-mood-val",
     "n-energy-val","n-focus-val","f-mood-val","f-energy-val","f-focus-val"].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.textContent = "3";
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
            <div class="meta">${e.created_at.slice(0,10)} | Mood: ${e.mood}/5</div>
            ${e.tags && e.tags.length ? `<div class="tags">${e.tags.map(t => `<span>${t}</span>`).join("")}</div>` : ""}
            <div class="actions">
                <button onclick="window.editEntry(${e.id},'${e.title.replace(/'/g,"\\'")}',
                    '${e.content.replace(/'/g,"\\'").replace(/\n/g,"\\n")}',
                    ${e.mood},'${(e.tags||[]).join(",")}','${type}')">Edit</button>
                <button class="delete-btn" onclick="window.deleteEntry(${e.id})">Delete</button>
            </div>
        </div>`;
    }).join("") || "<p style='color:var(--ink-faint);font-style:italic'>No entries yet.</p>";
}

window.editEntry = async function(id, title, content, mood, tags, entryType) {
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


// ============================================================
// HABITS V2 — Core Gameplay System
// Full integration: Skill Trees · Domains · Quests · Bosses · AI
// ============================================================

// ── State ────────────────────────────────────────────────────
let allSkillNodes = [];
let currentHabits = {};

// ── Boot ─────────────────────────────────────────────────────
async function loadStreaks() {
    await Promise.all([
        _loadSkillNodes(),
        _loadHabitsData(),
    ]);
    _buildSkillNodePicker();
    _renderHabitsPage();
    _loadActiveSynergies();
    _loadHabitAIInsight();
}

async function _loadSkillNodes() {
    try {
        allSkillNodes = await (await fetch("/habits/skill-nodes")).json();
    } catch (_) { allSkillNodes = []; }
}

async function _loadHabitsData() {
    try {
        const res = await fetch("/habits/balance");
        if (!res.ok) return;
        const data = await res.json();
        currentHabits = data.streaks || {};
        _renderDomainBalance(data.balance || []);
    } catch (_) {}
    try {
        const heatRes = await fetch("/habits/heatmap?days=365");
        if (heatRes.ok) _renderHeatmap(await heatRes.json());
    } catch (_) {}
}

// ── Domain Balance ────────────────────────────────────────────
const DOMAIN_ICONS = {
    "Computer Science": "💻", "Health": "💪", "Music": "🎵",
    "Relationships": "❤️", "Personal Growth": "🌱", "Finance": "💰", "Creativity": "🎨"
};
const DOMAIN_COLORS = {
    "Computer Science": "#6c8ebf", "Health": "#82b366", "Music": "#9c70c4",
    "Relationships": "#d98aa0", "Personal Growth": "#d07040", "Finance": "#d6a73a", "Creativity": "#b8617c"
};

function _renderDomainBalance(balance) {
    const el = document.getElementById("hb-bars");
    if (!el || !balance.length) return;
    el.innerHTML = balance.map(b => {
        const color = b.rate >= 70 ? "#4caf50" : b.rate >= 40 ? "#f7a94b" : "#ef5350";
        const icon = DOMAIN_ICONS[b.category] || "◎";
        return `<div class="hv2-bal-col">
            <div class="hv2-bal-wrap">
                <div class="hv2-bal-fill" style="height:${b.rate}%;background:${color}"></div>
            </div>
            <div class="hv2-bal-icon" title="${b.category}: ${b.rate}%">${icon}</div>
            <div class="hv2-bal-pct">${b.rate}%</div>
        </div>`;
    }).join("");
}

// ── Active Synergies Banner ───────────────────────────────────
async function _loadActiveSynergies() {
    const el = document.getElementById("hv2-synergy-banner");
    if (!el) return;
    try {
        const today = new Date().toISOString().slice(0, 10);
        // Fetch from habits/balance which includes synergy data indirectly
        // We check each habit's active_synergies
        const synergies = [];
        Object.values(currentHabits).forEach(h => {
            (h.active_synergies || []).forEach(s => {
                if (!synergies.find(x => x.name === s.name)) synergies.push(s);
            });
        });
        if (!synergies.length) { el.style.display = "none"; return; }
        el.style.display = "flex";
        el.innerHTML = `
            <span class="hv2-syn-banner-label">⚗️ Active Synergies</span>
            ${synergies.map(s => `
                <span class="hv2-syn-active-pill">
                    ${s.name}
                    <span class="hv2-syn-bonus">${s.bonus_desc || ""}</span>
                </span>`).join("")}`;
    } catch (_) { if (el) el.style.display = "none"; }
}

// ── Heatmap ───────────────────────────────────────────────────
function _renderHeatmap(data) {
    const el = document.getElementById("habit-heatmap");
    if (!el) return;
    const countMap = {};
    data.forEach(d => { countMap[d.date] = d.count; });
    const today = new Date();
    const cols = [];
    for (let w = 51; w >= 0; w--) {
        const col = [];
        for (let d = 0; d < 7; d++) {
            const dt = new Date(today);
            dt.setDate(dt.getDate() - (w * 7 + d));
            const key = dt.toISOString().slice(0, 10);
            const cnt = countMap[key] || 0;
            const op = cnt === 0 ? 0.06 : Math.min(0.15 + cnt * 0.22, 1);
            col.push(`<div class="hv2-hm-cell" title="${key}: ${cnt} habit${cnt !== 1 ? 's' : ''}" style="background:rgba(217,138,160,${op})"></div>`);
        }
        cols.push(`<div class="hv2-hm-col">${col.join("")}</div>`);
    }
    el.innerHTML = cols.join("");
}

// ── Create Panel toggle ───────────────────────────────────────
window.toggleHabitCreatePanel = function() {
    const body = document.getElementById("hv2-create-body");
    const btn  = document.querySelector(".hv2-create-toggle");
    if (!body) return;
    const open = body.style.display === "none";
    body.style.display = open ? "" : "none";
    if (btn) btn.textContent = open ? "Collapse" : "Expand";
    if (open) _buildSkillNodePicker();
};

// ── Skill Node Picker ─────────────────────────────────────────
function _buildSkillNodePicker() {
    const select = document.getElementById("habit-skill-node");
    if (!select || !allSkillNodes.length) return;
    const byTree = {};
    allSkillNodes.forEach(n => {
        if (!byTree[n.tree]) byTree[n.tree] = [];
        byTree[n.tree].push(n);
    });
    select.innerHTML = `<option value="">— No Skill Node (general habit) —</option>` +
        Object.entries(byTree).map(([tree, nodes]) =>
            `<optgroup label="${nodes[0]?.icon || ''} ${tree} · ${nodes[0]?.domain || ''}">
                ${nodes.map(n =>
                    `<option value="${n.id}" data-tree="${tree}" data-domain="${n.domain}">${n.name}</option>`
                ).join("")}
            </optgroup>`
        ).join("");
    select.addEventListener("change", () => {
        const opt = select.options[select.selectedIndex];
        const preview = document.getElementById("habit-node-preview");
        if (preview) {
            preview.textContent = opt?.dataset?.domain
                ? `→ ${opt.dataset.tree} · ${opt.dataset.domain}`
                : "";
        }
    });
}

// ── Habit Form Submit ─────────────────────────────────────────
const habitForm = document.getElementById("habit-form");
if (habitForm) {
    habitForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const name   = document.getElementById("habit-name")?.value.trim();
        const nodeEl = document.getElementById("habit-skill-node");
        const nodeId = nodeEl?.value || "";
        const opt    = nodeEl?.options[nodeEl.selectedIndex];
        const tree   = opt?.dataset?.tree || "";
        if (!name) return;

        // Create profile if node selected
        if (nodeId && tree) {
            await fetch("/habits/profile", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, skill_node_id: nodeId, skill_tree: tree }),
            });
        }

        // Log immediately
        const res  = await fetch("/habits", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, skill_node_id: nodeId, skill_tree: tree }),
        });
        const data = await res.json();

        if (data.status === "already_logged") {
            _toast("✓ Already logged today", "#4caf50");
        } else {
            if (data.xp_earned) showXPFlash(data.xp_earned, data.domain || "Habits");
            if (data.new_achievements) showAchievementToast(data.new_achievements);
            if (data.xp_modifiers?.length) {
                _toast(data.xp_modifiers.map(m => m.label).join(" · "), "var(--accent)", 3000);
            }
            if (data.new_synergies?.length) {
                data.new_synergies.forEach((s, i) =>
                    setTimeout(() => _toast(`⚗️ ${s.name}: ${s.bonus}`, "#7c3aed", 4500), i * 700)
                );
            }
            if (data.evolution_ready) {
                _toast(`⬆️ ${data.evolution_ready.message}`, "#ff9800", 5000);
            }
            if (data.habit_quest) _showHabitQuestBanner(data.habit_quest, name);
        }

        habitForm.reset();
        const preview = document.getElementById("habit-node-preview");
        if (preview) preview.textContent = "";
        loadStreaks();
        loadXPHUD();
    });
}

// ── Main Render ───────────────────────────────────────────────
function _renderHabitsPage() {
    const el = document.getElementById("streaks");
    if (!el) return;

    const entries = Object.entries(currentHabits);
    if (!entries.length) {
        el.innerHTML = `<div class="hv2-empty">
            <strong style="display:block;margin-bottom:.5rem;font-size:1rem">No habits yet</strong>
            Create your first habit above and link it to a Skill Node — every completion
            will automatically progress your Skills, Domains, and generate Quests.
        </div>`;
        return;
    }

    // Sort: evolving first, then at-risk (no log today), then rest
    const pending  = entries.filter(([, h]) => h.pending_evolution);
    const atRisk   = entries.filter(([, h]) => !h.pending_evolution && !h.done_today && h.current_streak > 0);
    const doneTdy  = entries.filter(([, h]) => h.done_today);
    const fresh    = entries.filter(([, h]) => !h.pending_evolution && !h.done_today && h.current_streak === 0);

    let html = "";

    if (pending.length) {
        html += `<div class="hv2-section-label">⬆️ Ready to Evolve</div>`;
        html += pending.map(([n, h]) => _buildHabitCard(n, h)).join("");
    }
    if (atRisk.length) {
        html += `<div class="hv2-section-label">🔥 Streak at Risk — Log Today</div>`;
        html += atRisk.map(([n, h]) => _buildHabitCard(n, h)).join("");
    }
    if (fresh.length) {
        if (pending.length || atRisk.length) html += `<div class="hv2-section-label">New Habits</div>`;
        html += fresh.map(([n, h]) => _buildHabitCard(n, h)).join("");
    }
    if (doneTdy.length) {
        html += `<div class="hv2-section-label">✓ Completed Today</div>`;
        html += doneTdy.map(([n, h]) => _buildHabitCard(n, h)).join("");
    }

    el.innerHTML = html;
}

// ── Habit Card Builder ────────────────────────────────────────
function _buildHabitCard(name, h) {
    const streak      = h.current_streak || 0;
    const total       = h.total_logs || 0;
    const mastery     = h.mastery_label || "Beginner";
    const masteryLvl  = h.mastery_level || 1;
    const stage       = h.evolution_stage || 1;
    const stages      = h.evolution_stages || [];
    const stageDef    = stages[stage - 1] || {};
    const domain      = h.domain || h.category || "Personal Growth";
    const node        = h.skill_node_name || "—";
    const xp          = h.base_xp || h.xp_per_log || 10;
    const successRate = h.success_rate || 0;
    const doneToday   = h.done_today || false;
    const tokens      = h.recovery_tokens || { available: 0 };
    const synergies   = h.active_synergies || [];
    const pending     = h.pending_evolution || false;
    const progressEvo = h.progress_to_next_evo || 0;
    const nextEvo     = h.next_evo_at;
    const domColor    = DOMAIN_COLORS[domain] || "var(--accent)";

    // SVG mastery ring
    const RING_COLORS = ["#c9a8b0","#d98aa0","#b8617c","#8b2252","#4a0e2a","#1a0010"];
    const ringColor = RING_COLORS[Math.min(masteryLvl - 1, 5)];
    const R = 19, circ = 2 * Math.PI * R;
    const pct = (masteryLvl - 1) / 5;
    const dash = circ * pct;

    // Stage color
    const STAGE_COLORS = ["#9e9e9e","#4caf50","#2196f3","#ff9800","#f44336","#9c27b0"];
    const stageColor = STAGE_COLORS[Math.min(stage - 1, 5)];

    // Synergy pills
    const synHtml = synergies.map(s =>
        `<span class="hv2-syn-pill" title="${s.bonus_desc}">⚗️ ${s.name}</span>`
    ).join("");

    // Evolution content
    let evoHtml;
    if (pending) {
        const nextStage = stages[stage] || {};
        evoHtml = `<div class="hv2-evo-banner">
            <span class="hv2-evo-icon">⬆️</span>
            <div class="hv2-evo-text">
                <strong>Ready to evolve → Stage ${stage + 1}${nextStage.title ? ': ' + nextStage.title : ''}</strong>
                ${nextStage.description ? `<em>${nextStage.description}${nextStage.duration_minutes ? ' · ' + nextStage.duration_minutes + ' min' : ''}</em>` : ''}
            </div>
            <div class="hv2-evo-btns">
                <button class="hv2-evo-confirm" onclick="confirmEvolution('${_esc(name)}', true)">Evolve ▶</button>
                <button class="hv2-evo-decline" onclick="confirmEvolution('${_esc(name)}', false)">Later</button>
            </div>
        </div>`;
    } else if (nextEvo) {
        evoHtml = `<div class="hv2-evo-progress">
            <div class="hv2-evo-bar-wrap">
                <div class="hv2-evo-bar" style="width:${progressEvo}%"></div>
            </div>
            <span class="hv2-evo-label">Stage ${stage + 1} in ${nextEvo - total} log${nextEvo - total !== 1 ? 's' : ''}</span>
        </div>`;
    } else {
        evoHtml = `<span class="hv2-evo-maxed">⭐ Max Evolution Reached</span>`;
    }

    // Token controls
    const tokenHtml = tokens.available > 0 ? `
        <div class="hv2-token-row">
            <span class="hv2-token-count">🛡️ ${tokens.available} token${tokens.available !== 1 ? 's' : ''}</span>
            <div class="hv2-token-actions">
                <button class="hv2-token-btn" onclick="spendToken('${_esc(name)}','restore')" title="Restore a missed day">↩ Restore</button>
                <button class="hv2-token-btn" onclick="spendToken('${_esc(name)}','skip')" title="Skip today without breaking streak">⏭ Skip</button>
                <button class="hv2-token-btn" onclick="spendToken('${_esc(name)}','bonus_xp')" title="+50% XP on next log">⚡ Bonus XP</button>
                ${tokens.available >= 2 ? `<button class="hv2-token-btn" onclick="spendToken('${_esc(name)}','freeze')" title="Freeze streak 3 days">❄️ Freeze</button>` : ""}
                ${tokens.available >= 2 ? `<button class="hv2-token-btn" onclick="spendToken('${_esc(name)}','boss_reduce')" title="Reduce Weekly Boss difficulty">⚔️ Boss</button>` : ""}
                ${tokens.available >= 2 ? `<button class="hv2-token-btn" onclick="spendToken('${_esc(name)}','quest_recover')" title="Recover failed quest">♻️ Quest</button>` : ""}
            </div>
        </div>` : "";

    return `<div class="hv2-card ${pending ? 'hv2-card--evolving' : ''} ${doneToday ? 'hv2-card--done' : ''}"
            style="--hv2-domain-color:${domColor}">
        <div class="hv2-card-top">

            <!-- Mastery Ring -->
            <div class="hv2-ring-wrap" title="Mastery: ${mastery} (Level ${masteryLvl})">
                <svg width="46" height="46" viewBox="0 0 46 46">
                    <circle cx="23" cy="23" r="${R}" fill="none" stroke="var(--line-strong)" stroke-width="3.5"/>
                    <circle cx="23" cy="23" r="${R}" fill="none"
                        stroke="${ringColor}" stroke-width="3.5"
                        stroke-dasharray="${dash.toFixed(1)} ${(circ - dash).toFixed(1)}"
                        stroke-dashoffset="${(circ / 4).toFixed(1)}"
                        stroke-linecap="round"/>
                    <text x="23" y="27" text-anchor="middle" font-size="12" font-weight="700" fill="var(--ink)">${masteryLvl}</text>
                </svg>
            </div>

            <!-- Info -->
            <div class="hv2-info">
                <div class="hv2-name-row">
                    <span class="hv2-name">${name}</span>
                    ${doneToday ? '<span class="hv2-done-badge">✓ Done</span>' : ''}
                    ${streak >= 7 ? `<span class="hv2-done-badge" style="background:#fff8e1;color:#e65100;border-color:#ffe082">🔥 ${streak}d</span>` : ''}
                </div>
                <div class="hv2-tags">
                    ${node !== "—" ? `<span class="hv2-tag hv2-tag--node">🔗 ${node}</span>` : ''}
                    <span class="hv2-tag hv2-tag--domain" style="background:${domColor}18;color:${domColor};border-color:${domColor}40">${domain}</span>
                    <span class="hv2-tag hv2-tag--stage" style="background:${stageColor}18;color:${stageColor};border-color:${stageColor}40">
                        Stage ${stage}${stageDef.title ? ' · ' + stageDef.title : ''}
                    </span>
                    <span class="hv2-tag hv2-tag--mastery">${mastery}</span>
                </div>
                <div class="hv2-stats-row">
                    <span class="hv2-stat">🔥 ${streak}-day streak</span>
                    <span class="hv2-stat hv2-stat--faint">${total} total</span>
                    <span class="hv2-stat hv2-stat--faint">${successRate}% rate</span>
                    <span class="hv2-xp">+${xp} XP</span>
                </div>
                ${synHtml ? `<div class="hv2-synergies">${synHtml}</div>` : ""}
            </div>

            <!-- Actions -->
            <div class="hv2-actions">
                ${!doneToday
                    ? `<button class="hv2-log-btn" onclick="quickLogHabit('${_esc(name)}')">Log Today</button>`
                    : `<button class="hv2-log-btn hv2-log-btn--done" disabled>✓ Logged</button>`}
                <div class="hv2-icon-btns">
                    <button class="hv2-stats-btn" onclick="openStatsModal('${_esc(name)}')" title="Stats">📊</button>
                    <button class="hv2-stats-btn" onclick="openEditHabitModal('${_esc(name)}')" title="Edit">✏️</button>
                    <button class="hv2-stats-btn hv2-delete-btn" onclick="deleteHabit('${_esc(name)}')" title="Delete">🗑️</button>
                </div>
            </div>
        </div>

        <!-- Evolution -->
        <div class="hv2-evo-row">${evoHtml}</div>

        <!-- Tokens -->
        ${tokenHtml}
    </div>`;
}

// ── Log Habit ─────────────────────────────────────────────────
window.quickLogHabit = async function(name) {
    const h = currentHabits[name] || {};
    const res  = await fetch("/habits", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            name,
            skill_node_id: h.skill_node_id || "",
            skill_tree:    h.skill_tree    || "",
        }),
    });
    const data = await res.json();

    if (data.status === "already_logged") {
        _toast("✓ Already logged today", "#4caf50");
        return;
    }

    // XP flash with modifiers
    if (data.xp_earned) showXPFlash(data.xp_earned, data.domain || "Habits");
    if (data.new_achievements) showAchievementToast(data.new_achievements);

    if (data.xp_modifiers?.length) {
        const labels = data.xp_modifiers.map(m => m.label).join(" · ");
        _toast(`${labels}`, "var(--accent)", 3000);
    }

    if (data.new_synergies?.length) {
        data.new_synergies.forEach((s, i) =>
            setTimeout(() => _toast(`⚗️ ${s.name}: ${s.bonus}`, "#7c3aed", 4500), i * 800)
        );
    }

    if (data.evolution_ready) {
        _toast(`⬆️ ${data.evolution_ready.message}`, "#ff9800", 5000);
    }

    if (data.habit_quest) _showHabitQuestBanner(data.habit_quest, name);
    if (data.adaptation)  setTimeout(() => _toast(`✦ ${data.adaptation}`, "var(--ink)", 4000), 1200);

    loadStreaks();
    loadXPHUD();
};

// ── Quest Banner ──────────────────────────────────────────────
function _showHabitQuestBanner(quest, habitName) {
    let b = document.getElementById("habit-quest-banner");
    if (!b) {
        b = document.createElement("div");
        b.id = "habit-quest-banner";
        b.className = "hv2-quest-banner";
        const sec = document.getElementById("page-habits");
        const streaks = document.getElementById("streaks");
        sec.insertBefore(b, streaks);
    }
    b.innerHTML = `
        <div class="hv2-qb-label">⚔️ Quest generated from "${habitName}"</div>
        <div class="hv2-qb-title">${quest.title}</div>
        <div class="hv2-qb-meta">
            ${quest.description ? `<span>${quest.description}</span>` : ""}
            <span class="dq-chip">⏱ ${quest.duration_minutes}m</span>
            <span class="dq-chip">${quest.difficulty}</span>
        </div>
        <button class="btn-ghost btn-sm" onclick="this.closest('.hv2-quest-banner').style.display='none'">Dismiss</button>`;
    b.style.display = "block";
    b.classList.add("show");
}

// ── Evolution ─────────────────────────────────────────────────
window.confirmEvolution = async function(name, confirmed) {
    const data = await (await fetch(`/habits/${encodeURIComponent(name)}/evolve`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmed }),
    })).json();
    if (data.status === "evolved") {
        showXPFlash(data.xp_bonus, "Evolution");
        _toast(`⬆️ Evolved to Stage ${data.new_stage}! XP per log: ${data.new_base_xp}`, "#ff9800", 4500);
    } else {
        _toast("Evolution deferred. It'll wait for you.", "var(--ink-soft)");
    }
    loadStreaks();
};

// ── Recovery Tokens ───────────────────────────────────────────
window.spendToken = async function(name, type) {
    const DESCS = {
        restore:      "Restore yesterday's missed log — your streak will be protected.",
        skip:         "Skip today without breaking your streak.",
        bonus_xp:     "Activate +50% XP for your next log.",
        freeze:       "Freeze your streak for 3 days (vacation mode).",
        boss_reduce:  "Reduce next Weekly Boss difficulty. (costs 2 tokens)",
        quest_recover:"Recover your most recently failed quest. (costs 2 tokens)",
    };
    const COSTS = { restore: 1, skip: 1, bonus_xp: 1, reroll: 1, freeze: 2, boss_reduce: 2, quest_recover: 2 };
    const tokens = currentHabits[name]?.recovery_tokens?.available || 0;
    const cost = COSTS[type] || 1;
    if (tokens < cost) { _toast(`Need ${cost} token(s), you have ${tokens}.`, "#ef5350"); return; }
    if (!confirm(DESCS[type] || `Use a ${type} token?`)) return;

    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    const date = yesterday.toISOString().slice(0, 10);

    const res  = await fetch("/habits/recover", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, date, token_type: type }),
    });
    const data = await res.json();
    if (!res.ok) { _toast(data.detail || "Token use failed.", "#ef5350"); return; }
    _toast(data.effect?.message || `✓ ${type} token used.`, "#4caf50", 3000);
    loadStreaks();
};

// ── Stats Modal ───────────────────────────────────────────────
window.openStatsModal = async function(name) {
    const modal = document.getElementById("habit-stats-modal");
    const inner = document.getElementById("habit-stats-inner");
    if (!modal || !inner) return;

    modal.style.display = "flex";
    inner.innerHTML = `<p style="padding:2rem 1rem;color:var(--ink-soft);font-style:italic">Loading stats…</p>`;

    try {
        const data = await (await fetch(`/habits/stats/${encodeURIComponent(name)}`)).json();
        const stages     = data.evolution_stages || [];
        const milestones = data.milestones || [];
        const heatmap    = data.heatmap || [];
        const h = currentHabits[name] || {};
        const domColor = DOMAIN_COLORS[data.domain || "Personal Growth"] || "var(--accent)";

        // Mini heatmap for modal
        const heatCountMap = {};
        heatmap.forEach(d => { heatCountMap[d.date] = d.count; });
        const today = new Date();
        let miniHeatCols = [];
        for (let w = 25; w >= 0; w--) {
            let col = [];
            for (let d = 0; d < 7; d++) {
                const dt = new Date(today);
                dt.setDate(dt.getDate() - (w * 7 + d));
                const key = dt.toISOString().slice(0, 10);
                const cnt = heatCountMap[key] || 0;
                const op  = cnt === 0 ? 0.06 : 1;
                col.push(`<div style="width:9px;height:9px;border-radius:2px;background:rgba(217,138,160,${op})" title="${key}"></div>`);
            }
            miniHeatCols.push(`<div style="display:flex;flex-direction:column;gap:2px">${col.join("")}</div>`);
        }

        inner.innerHTML = `
            <div class="hv2-modal-header">
                <div>
                    <div class="hv2-modal-title">${name}</div>
                    <div class="hv2-tags" style="margin-top:.4rem;flex-wrap:wrap;display:flex;gap:.25rem">
                        ${data.skill_node_name && data.skill_node_name !== "—" ? `<span class="hv2-tag hv2-tag--node">🔗 ${data.skill_node_name}</span>` : ""}
                        <span class="hv2-tag" style="background:${domColor}18;color:${domColor};border:1px solid ${domColor}40;border-radius:999px;font-size:.68rem;font-weight:600;padding:.18rem .5rem">${data.domain || ""}</span>
                        <span class="hv2-tag hv2-tag--mastery">${data.mastery_label || ""} · Level ${data.mastery_level || 1}</span>
                    </div>
                </div>
                <button class="hv2-modal-close" onclick="document.getElementById('habit-stats-modal').style.display='none'">✕</button>
            </div>

            <div class="hv2-stat-grid">
                <div class="hv2-stat-box"><div class="hv2-stat-val">${data.current_streak}</div><div class="hv2-stat-key">Current Streak</div></div>
                <div class="hv2-stat-box"><div class="hv2-stat-val">${data.best_streak}</div><div class="hv2-stat-key">Best Streak</div></div>
                <div class="hv2-stat-box"><div class="hv2-stat-val">${data.total_logs}</div><div class="hv2-stat-key">Total Logs</div></div>
                <div class="hv2-stat-box"><div class="hv2-stat-val">${data.success_rate}%</div><div class="hv2-stat-key">Success Rate</div></div>
                <div class="hv2-stat-box"><div class="hv2-stat-val">${data.total_xp_earned || 0}</div><div class="hv2-stat-key">XP Earned</div></div>
                <div class="hv2-stat-box"><div class="hv2-stat-val">Stage ${data.evolution_stage}</div><div class="hv2-stat-key">Evolution</div></div>
                <div class="hv2-stat-box"><div class="hv2-stat-val">${data.recovery_tokens?.used || 0}</div><div class="hv2-stat-key">Tokens Used</div></div>
                <div class="hv2-stat-box"><div class="hv2-stat-val">${data.base_xp || 10}</div><div class="hv2-stat-key">XP / Log</div></div>
            </div>

            <!-- Mini heatmap -->
            <div class="hv2-sub-label">Last 6 Months</div>
            <div class="hv2-modal-heatmap">
                <div class="hv2-modal-heatmap-grid" style="display:flex;gap:2px;overflow-x:auto">
                    ${miniHeatCols.join("")}
                </div>
            </div>

            ${stages.length ? `
            <div class="hv2-sub-label">Evolution Path</div>
            <div class="hv2-stages">
                ${stages.map((s, i) => `
                    <div class="hv2-stage-row ${i < data.evolution_stage - 1 ? 'hv2-stage--done' : i === data.evolution_stage - 1 ? 'hv2-stage--current' : ''}">
                        <span class="hv2-stage-num">${s.stage}</span>
                        <div class="hv2-stage-body">
                            <div class="hv2-stage-title">${s.title}</div>
                            <div class="hv2-stage-desc">${s.description || ""}</div>
                        </div>
                        <span class="hv2-stage-dur">${s.duration_minutes ? '⏱ ' + s.duration_minutes + 'm' : ''}</span>
                    </div>`).join("")}
            </div>` : ""}

            ${milestones.length ? `
            <div class="hv2-sub-label">Completion Milestones</div>
            <div class="hv2-milestone-list">
                ${milestones.map(m => `
                    <div class="hv2-milestone ${m.reached ? 'hv2-milestone--done' : ''}">
                        <span>${m.reached ? '✅' : '○'}</span>
                        <span>${m.at} completions</span>
                        ${!m.reached ? `<span class="hv2-ms-remaining">${m.remaining} to go</span>` : '<span class="hv2-ms-remaining" style="color:#2e7d32">Reached!</span>'}
                    </div>`).join("")}
            </div>` : ""}`;
    } catch (err) {
        inner.innerHTML = `<p style="padding:1rem;color:var(--ink-soft)">Could not load stats. ${err.message}</p>`;
    }
};

// ── Edit Habit Modal ──────────────────────────────────────────
window.openEditHabitModal = function(name) {
    const modal = document.getElementById("habit-edit-modal");
    if (!modal) return;
    document.getElementById("edit-habit-original-name").value = name;
    document.getElementById("edit-habit-name").value = name;

    const select = document.getElementById("edit-habit-skill-node");
    if (select && allSkillNodes.length) {
        const byTree = {};
        allSkillNodes.forEach(n => {
            if (!byTree[n.tree]) byTree[n.tree] = [];
            byTree[n.tree].push(n);
        });
        select.innerHTML = `<option value="">— No Skill Node —</option>` +
            Object.entries(byTree).map(([tree, nodes]) =>
                `<optgroup label="${nodes[0]?.icon || ''} ${tree}">
                    ${nodes.map(n => `<option value="${n.id}" data-tree="${tree}" data-domain="${n.domain}">${n.name}</option>`).join("")}
                </optgroup>`
            ).join("");
        const h = currentHabits[name];
        if (h && h.skill_node_id) select.value = h.skill_node_id;
        const preview = document.getElementById("edit-habit-node-preview");
        const updatePreview = () => {
            const opt = select.options[select.selectedIndex];
            if (preview) preview.textContent = opt?.dataset?.domain ? `→ ${opt.dataset.tree} · ${opt.dataset.domain}` : "";
        };
        select.onchange = updatePreview;
        updatePreview();
    }

    modal.style.display = "flex";
    setTimeout(() => document.getElementById("edit-habit-name").focus(), 50);
};

window.saveHabitEdit = async function() {
    const originalName = document.getElementById("edit-habit-original-name").value;
    const newName = document.getElementById("edit-habit-name").value.trim();
    const nodeSelect = document.getElementById("edit-habit-skill-node");
    const nodeId = nodeSelect?.value || "";
    const opt = nodeSelect?.options[nodeSelect.selectedIndex];
    const tree = opt?.dataset?.tree || "";

    if (!newName) { _toast("Name cannot be empty.", "#ef5350"); return; }

    const btn = document.getElementById("edit-habit-save-btn");
    btn.textContent = "Saving…";
    btn.disabled = true;

    try {
        const res = await fetch(`/habits/${encodeURIComponent(originalName)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ new_name: newName, skill_node_id: nodeId, skill_tree: tree }),
        });
        const data = await res.json();
        if (!res.ok) { _toast(data.detail || "Update failed.", "#ef5350"); return; }
        _toast(`✓ Habit updated`, "#4caf50", 2500);
        document.getElementById("habit-edit-modal").style.display = "none";
        loadStreaks();
    } catch (e) {
        _toast("Update failed.", "#ef5350");
    } finally {
        btn.textContent = "Save Changes";
        btn.disabled = false;
    }
};

window.deleteHabit = async function(name) {
    if (!confirm(`Delete "${name}" and all its history?\n\nThis cannot be undone.`)) return;
    try {
        const res = await fetch(`/habits/${encodeURIComponent(name)}`, { method: "DELETE" });
        if (!res.ok) { _toast("Delete failed.", "#ef5350"); return; }
        _toast(`🗑️ "${name}" deleted`, "var(--ink)", 2500);
        loadStreaks();
        loadXPHUD();
    } catch (e) {
        _toast("Delete failed.", "#ef5350");
    }
};

// ── AI Insights ───────────────────────────────────────────────
async function _loadHabitAIInsight() {
    const el   = document.getElementById("habit-ai-insight");
    const card = document.getElementById("habit-ai-insight-card");
    const sigs = document.getElementById("hv2-adaptation-signals");
    if (!el || !card) return;

    const entries = Object.keys(currentHabits);
    if (entries.length < 1) { card.style.display = "none"; return; }
    card.style.display = "";

    try {
        const data = await (await fetch("/habits/ai-insights")).json();
        el.textContent = data.insight;

        // Show adaptation signals
        if (sigs && data.adaptation_signals?.length) {
            sigs.innerHTML = data.adaptation_signals.map(sig => {
                const isEvolve = sig.includes("thriving");
                return `<span class="hv2-adapt-chip ${isEvolve ? 'hv2-adapt-chip--evolve' : 'hv2-adapt-chip--simplify'}">${sig}</span>`;
            }).join("");
        }
    } catch (_) { card.style.display = "none"; }
}

// ── Utility ───────────────────────────────────────────────────
function _esc(s) { return s.replace(/'/g, "\\'").replace(/"/g, "&quot;"); }

function _toast(msg, color = "var(--ink)", duration = 2500) {
    const t = document.createElement("div");
    t.className = "achievement-toast";
    t.style.background = color;
    t.style.fontSize = ".88rem";
    t.innerHTML = msg;
    document.body.appendChild(t);
    setTimeout(() => t.classList.add("show"), 50);
    setTimeout(() => { t.classList.remove("show"); setTimeout(() => t.remove(), 400); }, duration);
}

// Expose
window._loadHabitAIInsight = _loadHabitAIInsight;

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
                { label: "Mood (1-5)",   data: trends.map(t => t.avg_mood),   borderColor: "#d98aa0", backgroundColor: "rgba(217,138,160,0.1)", tension: 0.3 },
                { label: "Energy (1-5)", data: trends.map(t => t.avg_energy), borderColor: "#b8617c", backgroundColor: "rgba(184,97,124,0.1)",   tension: 0.3 },
                { label: "Focus (1-5)",  data: trends.map(t => t.avg_focus),  borderColor: "#82b366", backgroundColor: "rgba(130,179,102,0.1)",   tension: 0.3 },
            ],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: { y: { min: 1, max: 5, title: { display: true, text: "Rating (1–5)" } } },
        },
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
// Goals V2 — Goal → Milestone → Quest → Task
// ---------------------------------------------------------------------------

const goalForm = document.getElementById("goal-form");

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

// ============================================================
// QUESTS PAGE V2 — Goal → Milestone → Quest → Task
// Progress rolls up automatically from the bottom up
// ============================================================

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let goalsData = [];

// ---------------------------------------------------------------------------
// Load & render the full goals tree
// ---------------------------------------------------------------------------
async function loadGoals() {
    const goalsDiv = document.getElementById("goals");
    if (!goalsDiv) return;
    goalsDiv.innerHTML = "<p class='empty-state' style='padding:1rem 0'>Loading quests…</p>";
    try {
        goalsData = await (await fetch("/goals")).json();
        renderGoals(goalsData);
    } catch (_) {
        goalsDiv.innerHTML = "<p class='empty-state'>Could not load goals.</p>";
    }
}

function renderGoals(goals) {
    const goalsDiv = document.getElementById("goals");
    if (!goals.length) {
        goalsDiv.innerHTML = "<p class='empty-state'>No goals yet — add one above to begin your journey.</p>";
        return;
    }
    goalsDiv.innerHTML = goals.map(g => buildGoalCard(g)).join("");
}

// ---------------------------------------------------------------------------
// Goal card builder
// ---------------------------------------------------------------------------
function buildGoalCard(g) {
    const basis    = g.progress_basis || "tasks";
    const basisLabel = { milestones: "milestones", quests: "quests", tasks: "tasks" }[basis];
    const pctColor = g.progress >= 80 ? "var(--pa-good)" : g.progress >= 40 ? "var(--pa-ok)" : "var(--accent)";

    // Body: milestones view, or bare quests, or legacy tasks
    let bodyHtml = "";

    if (g.milestones && g.milestones.length > 0) {
        bodyHtml = g.milestones.map(m => buildMilestoneSection(m, g.id)).join("");
        bodyHtml += buildAddMilestoneRow(g.id);
    } else if (g.quests && g.quests.length > 0) {
        bodyHtml = g.quests.map(q => buildQuestSection(q, g.id, null)).join("");
        bodyHtml += buildAddQuestRow(g.id, null);
        bodyHtml += buildAddMilestoneRow(g.id);
    } else if (g.legacy_tasks && g.legacy_tasks.length > 0) {
        // Legacy direct tasks
        bodyHtml = buildLegacyTaskList(g.legacy_tasks, g.id);
        bodyHtml += buildAddQuestRow(g.id, null);
        bodyHtml += buildAddMilestoneRow(g.id);
    } else {
        // Empty goal — show add options
        bodyHtml = `<p class="task-empty">No milestones or quests yet.</p>`;
        bodyHtml += buildAddQuestRow(g.id, null);
        bodyHtml += buildAddMilestoneRow(g.id);
    }

    return `<div class="goal-card" id="goal-${g.id}">
        <div class="goal-header">
            <div>
                <strong class="goal-title">${g.title}</strong>
                <span class="goal-category">${g.category}</span>
            </div>
            <div class="goal-header-right">
                <span class="goal-level-badge">Lv ${g.level} · ${g.xp} XP</span>
                <span class="goal-progress-pct" style="color:${pctColor}">${g.progress}%</span>
            </div>
        </div>
        <div class="goal-progress-row">
            <div class="progress-bar">
                <div class="progress-fill" style="width:${g.progress}%;background:${pctColor}"></div>
            </div>
            <span class="goal-basis-label">${g.completed_units || 0}/${g.total_units || 0} ${basisLabel}</span>
        </div>
        <div class="goal-body" id="goal-body-${g.id}">
            ${bodyHtml}
        </div>
        <div class="goal-actions">
            <button class="btn-ghost goal-delete-btn" onclick="deleteGoal(${g.id})">Delete goal</button>
        </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Milestone section
// ---------------------------------------------------------------------------
function buildMilestoneSection(m, goalId) {
    const pct = m.progress || 0;
    const pctColor = pct >= 80 ? "var(--pa-good)" : pct >= 40 ? "var(--pa-ok)" : "var(--accent)";
    const questsHtml = (m.quests || []).map(q => buildQuestSection(q, goalId, m.id)).join("");
    const addQuestHtml = buildAddQuestRow(goalId, m.id);

    return `<div class="ms-block" id="ms-block-${m.id}">
        <div class="ms-block-header">
            <div class="ms-block-icon ${m.is_completed ? 'ms-block-icon--done' : ''}">
                ${m.is_completed ? '🏁' : '◎'}
            </div>
            <div class="ms-block-title">${m.title}</div>
            ${m.target_date ? `<span class="ms-date">by ${m.target_date}</span>` : ""}
            <div class="ms-block-progress">
                <div class="ms-mini-bar"><div class="ms-mini-fill" style="width:${pct}%;background:${pctColor}"></div></div>
                <span class="ms-pct">${pct}%</span>
            </div>
            <button class="ms-delete-btn" onclick="deleteMilestone(${m.id})" title="Delete milestone">✕</button>
        </div>
        <div class="ms-block-body">
            ${questsHtml}
            ${addQuestHtml}
        </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Quest section
// ---------------------------------------------------------------------------
function buildQuestSection(q, goalId, milestoneId) {
    const pct = q.progress || 0;
    const pctColor = pct >= 80 ? "var(--pa-good)" : pct >= 40 ? "var(--pa-ok)" : "var(--accent)";
    const DIFF_COLORS = { Easy: "#4caf50", Normal: "#f7a94b", Hard: "#ff7043", Elite: "#9c27b0" };
    const diffColor = DIFF_COLORS[q.difficulty] || "#f7a94b";

    const tasksHtml = (q.tasks || []).map(t => buildTaskRow(t, q.id)).join("");
    const addTaskHtml = `
        <div class="add-task-row" id="add-task-row-${q.id}">
            <input type="text" class="add-task-input" id="task-input-${q.id}"
                placeholder="Add a task…"
                onkeydown="if(event.key==='Enter'){addQuestTask(${q.id});event.preventDefault();}">
            <button class="add-task-btn" onclick="addQuestTask(${q.id})">+ Add</button>
        </div>`;

    return `<div class="quest-block ${q.is_completed ? 'quest-block--done' : ''}" id="quest-block-${q.id}">
        <div class="quest-block-header">
            <span class="quest-dot" style="background:${q.is_completed ? '#4caf50' : diffColor}"></span>
            <span class="quest-title">${q.title}</span>
            ${q.description ? `<span class="quest-desc">${q.description}</span>` : ""}
            <div class="quest-badges">
                <span class="quest-badge" style="background:${diffColor}20;color:${diffColor}">${q.difficulty}</span>
                <span class="quest-badge">${q.completed_tasks}/${q.total_tasks} tasks</span>
            </div>
            <div class="quest-mini-bar-wrap">
                <div class="quest-mini-bar"><div class="quest-mini-fill" style="width:${pct}%;background:${pctColor}"></div></div>
            </div>
            <button class="quest-delete-btn" onclick="deleteQuest(${q.id})" title="Delete quest">✕</button>
        </div>
        <div class="quest-task-list">
            ${tasksHtml}
            ${addTaskHtml}
        </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Task row
// ---------------------------------------------------------------------------
function buildTaskRow(t, questId) {
    return `<label class="task-row ${t.is_completed ? 'task-done' : ''}" id="task-row-${t.id}">
        <input type="checkbox" class="task-check"
            onchange="toggleTask(${t.id}, this)"
            ${t.is_completed ? 'checked' : ''}>
        <span class="task-title">${t.title}</span>
        <button class="task-delete-btn" onclick="deleteTask(${t.id}, event)">✕</button>
    </label>`;
}

// ---------------------------------------------------------------------------
// Legacy task list (for old goals that have no quests/milestones)
// ---------------------------------------------------------------------------
function buildLegacyTaskList(tasks, goalId) {
    const rows = tasks.map(t => buildTaskRow(t, null)).join("");
    return `<div class="legacy-tasks-block">
        <div class="legacy-label">⚠ Legacy tasks (no quest assigned)</div>
        ${rows}
        <div class="add-task-row">
            <input type="text" class="add-task-input" id="task-input-legacy-${goalId}"
                placeholder="Add a task directly…"
                onkeydown="if(event.key==='Enter'){addLegacyTask(${goalId});event.preventDefault();}">
            <button class="add-task-btn" onclick="addLegacyTask(${goalId})">+ Add</button>
        </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Add rows (inline forms)
// ---------------------------------------------------------------------------
function buildAddMilestoneRow(goalId) {
    return `<div class="add-milestone-row" id="add-ms-row-${goalId}">
        <button class="btn-ghost btn-add-tier" onclick="toggleAddMilestone(${goalId})">+ Add Milestone</button>
        <div class="add-tier-form hidden" id="add-ms-form-${goalId}">
            <input type="text" id="ms-title-${goalId}" placeholder="Milestone name…"
                onkeydown="if(event.key==='Enter'){addMilestone(${goalId});event.preventDefault();}">
            <input type="date" id="ms-date-${goalId}">
            <button onclick="addMilestone(${goalId})">Add</button>
            <button class="btn-ghost" onclick="document.getElementById('add-ms-form-${goalId}').classList.add('hidden')">Cancel</button>
        </div>
    </div>`;
}

function buildAddQuestRow(goalId, milestoneId) {
    const key = milestoneId ? `ms-${milestoneId}` : `goal-${goalId}`;
    return `<div class="add-quest-row">
        <button class="btn-ghost btn-add-tier" onclick="toggleAddQuest('${key}', ${goalId}, ${milestoneId || 'null'})">
            ⚔️ Add Quest
        </button>
        <div class="add-tier-form hidden" id="add-quest-form-${key}">
            <input type="text" id="quest-title-${key}" placeholder="Quest title…"
                onkeydown="if(event.key==='Enter'){addQuest(${goalId}, ${milestoneId || 'null'}, '${key}');event.preventDefault();}">
            <select id="quest-diff-${key}" class="hlf-select" style="max-width:130px">
                <option value="Easy">🟢 Easy</option>
                <option value="Normal" selected>🟡 Normal</option>
                <option value="Hard">🟠 Hard</option>
                <option value="Elite">🔴 Elite</option>
            </select>
            <button onclick="addQuest(${goalId}, ${milestoneId || 'null'}, '${key}')">Add</button>
            <button class="btn-ghost" onclick="document.getElementById('add-quest-form-${key}').classList.add('hidden')">Cancel</button>
        </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Toggle helpers for inline forms
// ---------------------------------------------------------------------------
window.toggleAddMilestone = function(goalId) {
    const form = document.getElementById(`add-ms-form-${goalId}`);
    form.classList.toggle("hidden");
    if (!form.classList.contains("hidden")) document.getElementById(`ms-title-${goalId}`)?.focus();
};

window.toggleAddQuest = function(key, goalId, milestoneId) {
    const form = document.getElementById(`add-quest-form-${key}`);
    form.classList.toggle("hidden");
    if (!form.classList.contains("hidden")) document.getElementById(`quest-title-${key}`)?.focus();
};

// ---------------------------------------------------------------------------
// CRUD actions
// ---------------------------------------------------------------------------

window.addMilestone = async function(goalId) {
    const titleEl = document.getElementById(`ms-title-${goalId}`);
    const title   = titleEl?.value.trim();
    if (!title) return;
    const target = document.getElementById(`ms-date-${goalId}`)?.value || null;
    await fetch(`/goals/${goalId}/milestones`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, target_date: target }),
    });
    loadGoals();
};

window.deleteMilestone = async function(msId) {
    if (!confirm("Delete this milestone and all its quests?")) return;
    await fetch(`/milestones/${msId}`, { method: "DELETE" });
    loadGoals();
};

window.addQuest = async function(goalId, milestoneId, key) {
    const titleEl = document.getElementById(`quest-title-${key}`);
    const title   = titleEl?.value.trim();
    if (!title) return;
    const diff = document.getElementById(`quest-diff-${key}`)?.value || "Normal";
    await fetch(`/goals/${goalId}/quests`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, difficulty: diff, milestone_id: milestoneId }),
    });
    loadGoals();
};

window.deleteQuest = async function(questId) {
    if (!confirm("Delete this quest and all its tasks?")) return;
    await fetch(`/quests/${questId}`, { method: "DELETE" });
    loadGoals();
};

window.addQuestTask = async function(questId) {
    const input = document.getElementById(`task-input-${questId}`);
    const title = input?.value.trim();
    if (!title) return;
    await fetch(`/quests/${questId}/tasks`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
    });
    loadGoals();
};

window.addLegacyTask = async function(goalId) {
    const input = document.getElementById(`task-input-legacy-${goalId}`);
    const title = input?.value.trim();
    if (!title) return;
    await fetch(`/goals/${goalId}/tasks`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
    });
    loadGoals();
};

window.addTask = async function(goalId) {
    window.addLegacyTask(goalId);
};

window.toggleTask = async function(taskId, cb) {
    cb.disabled = true;
    try {
        const data = await (await fetch(`/tasks/${taskId}`, { method: "PUT" })).json();
        if (data.xp_earned) showXPFlash(data.xp_earned, data.category || "Goal");
        if (data.new_achievements) showAchievementToast(data.new_achievements);
        if (data.skill_completion?.skill_completed) showSkillCompleteModal(data.skill_completion);
        // Reload to reflect rollup
        loadGoals();
        loadXPHUD();
    } catch (_) {
        cb.disabled = false;
    }
};

window.deleteTask = async function(taskId, e) {
    e.preventDefault();
    e.stopPropagation();
    await fetch(`/tasks/${taskId}`, { method: "DELETE" });
    loadGoals();
};

window.deleteGoal = async function(goalId) {
    if (!confirm("Delete this goal and everything inside it?")) return;
    await fetch(`/goals/${goalId}`, { method: "DELETE" });
    loadGoals();
};

window.toggleMilestone = async function(id, cb) {
    // Not used in V2 (milestones complete automatically) — kept for compat
};

// ---------------------------------------------------------------------------
// Skills — Skill-Driven Quest System
// ---------------------------------------------------------------------------

const DIFF_ICONS = { Beginner: "🟢", Intermediate: "🟡", Advanced: "🔴" };

async function loadSkills() {
    const [trees, achData] = await Promise.all([
        fetch("/skills").then(r => r.json()),
        fetch("/achievements").then(r => r.json()),
    ]);

    const container = document.getElementById("skill-trees");
    const info = achData.level_info;

    container.innerHTML = `
        <div class="skill-level-banner">
            <div class="slb-level">Level ${info.level}</div>
            <div class="slb-xp-bar-wrap">
                <div class="slb-xp-bar-fill" style="width:${Math.round(info.xp_in_level / 5)}%"></div>
            </div>
            <div class="slb-xp-text">${info.xp_in_level} / 500 XP · ${info.xp_to_next} to next level</div>
        </div>
        <div class="skill-how-it-works">
            <strong>How it works:</strong>
            Click <em>Start Learning</em> on any available node → a goal with structured tasks is created →
            complete every task → the node is automatically mastered → XP is awarded → new nodes unlock.
        </div>`;

    trees.forEach(tree => {
        const treeEl = document.createElement("div");
        treeEl.className = "skt-tree";
        treeEl.innerHTML = `
            <div class="skt-tree-header">
                <span class="skt-tree-icon">${tree.icon}</span>
                <span class="skt-tree-name">${tree.label}</span>
                <span class="skt-tree-xp">${tree.category_xp} XP</span>
            </div>
            <div class="skt-nodes" id="nodes-${tree.category}"></div>`;
        container.appendChild(treeEl);

        const nodesEl = treeEl.querySelector(".skt-nodes");
        tree.nodes.forEach(node => {
            nodesEl.appendChild(buildNodeCard(node, tree));
        });
    });

    // Achievements
    const earned = achData.earned || [];
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

function buildNodeCard(node, tree) {
    const el = document.createElement("div");

    // Determine state
    let state;
    if (node.completed)                  state = "completed";
    else if (node.active_goal)           state = "active";
    else if (node.unlocked)              state = "available";
    else                                 state = "locked";

    el.className = `skt-node skt-node--${state}`;

    // Prerequisites display
    const prereqNames = (node.prerequisites || []).map(pid => {
        const found = tree.nodes.find(n => n.id === pid);
        return found ? found.name : pid;
    });

    // What this unlocks
    const unlocksNames = (node.leads_to || []).map(uid => {
        const found = tree.nodes.find(n => n.id === uid);
        return found ? found.name : uid;
    });

    // Progress bar for active node
    const ag = node.active_goal;
    const progressHtml = ag
        ? `<div class="skt-progress-wrap">
               <div class="skt-progress-bar">
                   <div class="skt-progress-fill" style="width:${ag.progress}%"></div>
               </div>
               <span class="skt-progress-label">${ag.completed_tasks}/${ag.total_tasks} tasks · ${ag.progress}%</span>
           </div>`
        : "";

    // CTA button
    let ctaHtml = "";
    if (state === "completed") {
        ctaHtml = `<div class="skt-done-badge">✓ Mastered</div>`;
    } else if (state === "active") {
        ctaHtml = `<button class="skt-btn skt-btn--active"
            onclick="showPage('quests')">View Tasks →</button>`;
    } else if (state === "available") {
        ctaHtml = `<button class="skt-btn skt-btn--start"
            onclick="startLearning('${node.id}','${tree.category}',this)">▶ Start Learning</button>`;
    } else {
        // Locked — show what's needed
        const needsXP = !node.xp_met ? `${node.xp_required} XP in ${tree.label}` : "";
        const needsNodes = !node.prereqs_met && prereqNames.length
            ? `Complete: ${prereqNames.join(", ")}` : "";
        const reqs = [needsXP, needsNodes].filter(Boolean).join(" · ");
        ctaHtml = `<div class="skt-locked-msg">🔒 ${reqs || "Complete prerequisites"}</div>`;
    }

    el.innerHTML = `
        <div class="skt-node-head">
            <div class="skt-node-state-dot skt-dot--${state}"></div>
            <div class="skt-node-title">${node.name}</div>
            <div class="skt-node-badges">
                <span class="skt-badge">${DIFF_ICONS[node.difficulty] || ""} ${node.difficulty || ""}</span>
                <span class="skt-badge">⏱ ~${node.estimated_hours || "?"}h</span>
                <span class="skt-badge skt-badge--xp">+${node.xp_reward || node.xp_required} XP</span>
            </div>
        </div>
        <div class="skt-node-desc">${node.description}</div>
        ${prereqNames.length ? `<div class="skt-node-meta">Requires: ${prereqNames.map(n => `<span class="skt-req">${n}</span>`).join("")}</div>` : ""}
        ${unlocksNames.length ? `<div class="skt-node-meta">Unlocks: ${unlocksNames.map(n => `<span class="skt-unlocks">${n}</span>`).join("")}</div>` : ""}
        ${progressHtml}
        <div class="skt-node-foot">${ctaHtml}</div>`;

    return el;
}

// Start Learning — creates goal + tasks then redirects to Quests
window.startLearning = async function(nodeId, category, btn) {
    btn.textContent = "Starting…";
    btn.disabled = true;
    try {
        const data = await (await fetch(
            `/skills/${nodeId}/start?category=${encodeURIComponent(category)}`,
            { method: "POST" }
        )).json();

        if (data.status === "already_active") {
            showPage("quests");
            return;
        }
        if (data.status === "started") {
            showXPFlash(0, "Quest Created!");
            // Show a brief toast then go to quests
            const toast = document.createElement("div");
            toast.className = "achievement-toast show";
            toast.innerHTML = `📚 <strong>Learning started!</strong> ${data.task_count} tasks added to Quests.`;
            document.body.appendChild(toast);
            setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 400); }, 3000);
            setTimeout(() => showPage("quests"), 600);
        }
    } catch (_) {
        btn.textContent = "▶ Start Learning";
        btn.disabled = false;
    }
};

// Skill complete celebration modal
function showSkillCompleteModal(sc) {
    let modal = document.getElementById("skill-complete-modal");
    if (!modal) {
        modal = document.createElement("div");
        modal.id = "skill-complete-modal";
        modal.className = "skill-complete-overlay";
        document.body.appendChild(modal);
    }
    modal.innerHTML = `
        <div class="skill-complete-box">
            <div class="skill-complete-star">⭐</div>
            <h2 class="skill-complete-title">Skill Mastered!</h2>
            <p class="skill-complete-name">${sc.node_name}</p>
            <div class="skill-complete-xp">+${sc.xp_earned} XP</div>
            ${sc.newly_unlocked && sc.newly_unlocked.length
                ? `<div class="skill-complete-unlocks">
                    🔓 Now unlocked: <strong>${sc.newly_unlocked.join(", ")}</strong>
                   </div>` : ""}
            <div style="display:flex;gap:.75rem;margin-top:1.25rem;justify-content:center">
                <button class="skt-btn skt-btn--start" onclick="
                    document.getElementById('skill-complete-modal').style.display='none';
                    showPage('skills');
                    loadSkills();">View Skill Tree</button>
                <button style="background:var(--paper);color:var(--ink-soft);border:1px solid var(--line);padding:.55rem 1rem;border-radius:10px;cursor:pointer"
                    onclick="document.getElementById('skill-complete-modal').style.display='none'">
                    Close</button>
            </div>
        </div>`;
    modal.style.display = "flex";
    // Also show XP flash
    showXPFlash(sc.xp_earned, sc.category);
}

// ---------------------------------------------------------------------------
// Life Domains — full page logic
// ---------------------------------------------------------------------------

async function loadDomains() {
    const container = document.getElementById("domain-cards");
    container.innerHTML = "<p class='empty-state'>Loading domains…</p>";
    try {
        const domains = await (await fetch("/domains")).json();
        if (!domains.length) { container.innerHTML = "<p class='empty-state'>No domain data yet.</p>"; return; }
        container.innerHTML = domains.map(d => buildDomainCard(d)).join("");
    } catch (_) {
        container.innerHTML = "<p class='empty-state'>Could not load domains.</p>";
    }
    loadActionEngine();
    loadCurrentBosses();
}

function buildDomainCard(d) {
    const pct      = Math.round(d.xp_in_level / 5);  // xp_in_level out of 500
    const habits   = (d.habits || []).slice(0, 4);
    const skills   = (d.skill_trees || []);
    const goals    = (d.goals || []).filter(g => g.progress < 100).slice(0, 3);
    const boss     = d.weekly_boss;

    const habitPills = habits.map(h =>
        `<span class="dom-pill ${h.done_today ? 'dom-pill--done' : ''}">${h.done_today ? '✓' : '○'} ${h.name} (${h.streak}🔥)</span>`
    ).join("") || `<span class="dom-pill dom-pill--empty">No habits linked</span>`;

    const skillBars = skills.map(s =>
        `<div class="dom-skill-row">
            <span class="dom-skill-name">${s.label}</span>
            <div class="dom-skill-bar"><div class="dom-skill-fill" style="width:${s.pct}%;background:${d.color}"></div></div>
            <span class="dom-skill-pct">${s.completed}/${s.total}</span>
         </div>`
    ).join("") || `<span style="font-size:.8rem;color:var(--ink-faint)">No skill trees</span>`;

    const goalList = goals.map(g =>
        `<div class="dom-goal-row">
            <span class="dom-goal-title">${g.title}</span>
            <div class="dom-goal-bar"><div class="dom-goal-fill" style="width:${g.progress}%;background:${d.color}"></div></div>
            <span class="dom-goal-pct">${g.progress}%</span>
         </div>`
    ).join("") || `<span style="font-size:.8rem;color:var(--ink-faint)">No active goals</span>`;

    const bossHtml = boss
        ? `<div class="dom-boss ${boss.completed ? 'dom-boss--done' : ''}">
               <span class="dom-boss-icon">${boss.completed ? '✅' : '⚔️'}</span>
               <span class="dom-boss-name">${boss.name}</span>
               ${!boss.completed ? `<button class="dom-boss-btn" onclick="defeatBoss(${boss.id}, this)">Defeat</button>` : '<span class="dom-boss-defeated">Defeated!</span>'}
           </div>`
        : `<span style="font-size:.8rem;color:var(--ink-faint)">No boss this week</span>`;

    return `<div class="domain-card" style="--dom-color:${d.color}">
        <div class="dom-header">
            <span class="dom-icon">${d.icon}</span>
            <div class="dom-title-block">
                <div class="dom-name">${d.name}</div>
                <div class="dom-desc">${d.description}</div>
            </div>
            <div class="dom-level-badge">Lv ${d.level}</div>
        </div>
        <div class="dom-xp-row">
            <div class="dom-xp-bar-wrap">
                <div class="dom-xp-bar-fill" style="width:${pct}%;background:${d.color}"></div>
            </div>
            <span class="dom-xp-text">${d.xp_in_level}/500 XP · ${d.xp_to_next} to next</span>
        </div>
        <div class="dom-progress-pct">${d.progress}% quest completion · ${d.active_goals} active goal${d.active_goals !== 1 ? 's' : ''}</div>

        <div class="dom-section-label">Habits</div>
        <div class="dom-pills">${habitPills}</div>

        <div class="dom-section-label">Skill Trees</div>
        ${skillBars}

        <div class="dom-section-label">Active Goals</div>
        ${goalList}

        <div class="dom-section-label">This Week's Boss</div>
        ${bossHtml}
    </div>`;
}

async function loadActionEngine() {
    const el = document.getElementById("aep-content");
    try {
        const data = await (await fetch("/action-engine")).json();
        if (!data.needs_attention) {
            el.innerHTML = `<div class="aep-ok">✦ ${data.summary}</div>`;
            return;
        }
        const primary = data.primary;
        el.innerHTML = `
            <div class="aep-primary">
                <div class="aep-severity aep-sev--${primary.severity}">${primary.severity.toUpperCase()}</div>
                <div class="aep-problem-title">${primary.title}</div>
                <div class="aep-action">→ ${primary.action}</div>
            </div>
            ${data.problems.length > 1 ? `<div class="aep-other-list">
                ${data.problems.slice(1).map(p =>
                    `<div class="aep-other-item"><span class="aep-sev--${p.severity} aep-severity">${p.severity.toUpperCase()}</span> ${p.title}</div>`
                ).join("")}
            </div>` : ""}`;
    } catch (_) {
        el.innerHTML = `<div class="aep-ok">Action Engine unavailable.</div>`;
    }
}

async function loadBottleneck() {
    const el = document.getElementById("bottleneck-content");
    el.innerHTML = "<span style='color:var(--ink-faint);font-style:italic'>Analyzing…</span>";
    try {
        const data = await (await fetch("/bottleneck")).json();
        if (!data.bottleneck) {
            el.innerHTML = `<p style="color:var(--ink-soft)">${data.message}</p>`;
            return;
        }
        const scores = (data.all_scores || []).slice(0, 4);
        el.innerHTML = `
            <div class="btn-primary-block">
                <div class="btn-bottleneck-name">${data.bottleneck}</div>
                <div class="btn-confidence">Confidence: ${data.confidence}%</div>
                ${data.ai_message ? `<div class="btn-ai-msg">${data.ai_message}</div>` : ""}
            </div>
            <div class="btn-evidence">
                <div class="btn-sub-label">Evidence</div>
                ${data.evidence.map(e => `<div class="btn-ev-item">• ${e}</div>`).join("")}
            </div>
            <div class="btn-recovery">
                <div class="btn-sub-label">Recovery Plan</div>
                ${(data.recovery_plan || []).map((r, i) =>
                    `<div class="btn-rec-item"><span class="btn-rec-num">${i + 1}</span>${r}</div>`
                ).join("")}
            </div>
            ${scores.length > 1 ? `<div class="btn-scores">
                ${scores.map(s =>
                    `<div class="btn-score-row">
                        <span class="btn-score-name">${s.name}</span>
                        <div class="btn-score-bar-wrap"><div class="btn-score-bar" style="width:${Math.min(s.score, 100)}%"></div></div>
                     </div>`
                ).join("")}
            </div>` : ""}`;
    } catch (_) {
        el.innerHTML = "<p style='color:var(--ink-soft)'>Could not run analysis.</p>";
    }
}
window.loadBottleneck = loadBottleneck;

// Weekly Boss Battles
async function loadCurrentBosses() {
    const el = document.getElementById("boss-battles");
    try {
        const data = await (await fetch("/bosses/current")).json();
        if (!data.bosses || !data.bosses.length) {
            el.innerHTML = `<div class="boss-empty">No boss battles this week yet. <button class="btn-ghost btn-sm" onclick="generateBosses()">Generate Now</button></div>`;
            return;
        }
        el.innerHTML = data.bosses.map(b => buildBossCard(b)).join("");
    } catch (_) {
        el.innerHTML = `<div class="boss-empty">Could not load boss battles.</div>`;
    }
}

function buildBossCard(b) {
    const req  = Array.isArray(b.requirements) ? b.requirements : [];
    const done = b.completed;
    return `<div class="boss-card ${done ? 'boss-card--done' : ''}">
        <div class="boss-card-header">
            <span class="boss-icon">${done ? '☠️' : '👹'}</span>
            <div class="boss-title-block">
                <div class="boss-name">${b.name}</div>
                <div class="boss-domain">${b.domain}</div>
            </div>
            <div class="boss-xp">+${b.xp_reward} XP</div>
        </div>
        <div class="boss-desc">${b.description || ''}</div>
        ${req.length ? `<div class="boss-reqs">
            ${req.map(r => `<div class="boss-req-item">☐ ${r.label}</div>`).join("")}
        </div>` : ""}
        <div class="boss-deadline">Deadline: ${b.deadline}</div>
        ${done
            ? `<div class="boss-defeated-badge">✅ Defeated!</div>`
            : `<button class="boss-defeat-btn" onclick="defeatBoss(${b.id}, this)">⚔️ Mark Defeated</button>`}
    </div>`;
}

window.generateBosses = async function() {
    const el = document.getElementById("boss-battles");
    el.innerHTML = "<p style='color:var(--ink-faint);font-style:italic'>Generating boss battles…</p>";
    try {
        const data = await (await fetch("/bosses/generate", { method: "POST" })).json();
        loadCurrentBosses();
        const toast = document.createElement("div");
        toast.className = "achievement-toast show";
        toast.innerHTML = `⚔️ ${data.bosses.length} Boss Battles generated for ${data.week_key}!`;
        document.body.appendChild(toast);
        setTimeout(() => { toast.classList.remove("show"); setTimeout(() => toast.remove(), 400); }, 3500);
    } catch (_) {
        el.innerHTML = "<p style='color:var(--ink-soft)'>Boss generation failed.</p>";
    }
};

window.defeatBoss = async function(bossId, btn) {
    btn.disabled = true;
    btn.textContent = "Processing…";
    try {
        const data = await (await fetch(`/bosses/${bossId}/complete`, { method: "POST" })).json();
        if (data.xp_earned) showXPFlash(data.xp_earned, data.domain);
        if (data.new_achievements) showAchievementToast(data.new_achievements);
        loadCurrentBosses();
        loadDomains();
        loadXPHUD();
    } catch (_) {
        btn.disabled = false;
        btn.textContent = "⚔️ Mark Defeated";
    }
};

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------
loadAIInsight();
loadXPHUD();
loadTodayStatus();
switchEntryTab("morning");
loadProactiveCoaching();

}); // end DOMContentLoaded
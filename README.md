# LiAInne — User Manual
**Your personal growth RPG and AI journal coach**

---

## Table of Contents

1. [What is LiAInne?](#1-what-is-liainne)
2. [The Big Picture — How Everything Connects](#2-the-big-picture)
3. [XP, Levels & Achievements](#3-xp-levels--achievements)
4. [Journal](#4-journal)
5. [Habits](#5-habits)
6. [Quests & Goals](#6-quests--goals)
7. [Skill Trees](#7-skill-trees)
8. [Life Domains](#8-life-domains)
9. [Insights & Monthly Review](#9-insights--monthly-review)
10. [LiAInne Chat (AI Coach)](#10-liainne-chat-ai-coach)
11. [Weekly Boss Battles](#11-weekly-boss-battles)
12. [Action Engine & Bottleneck Detector](#12-action-engine--bottleneck-detector)
13. [Quick-Start Guide (First 10 Minutes)](#13-quick-start-guide-first-10-minutes)
14. [FAQ](#14-faq)

---

## 1. What is LiAInne?

LiAInne is a self-improvement app built like an RPG. Instead of a plain to-do list or journal, everything you do — writing, completing tasks, building habits, learning skills — earns you **XP**, levels you up, and feeds into a web of interconnected systems.

The AI coach (also named LiAInne) reads your journal history and gives you personalised feedback, nudges, and recommendations in real time.

---

## 2. The Big Picture

Understanding how the systems feed into each other makes everything click:

```
Journal Entries
    │
    ├──▶ Mood/Energy/Focus trends → Insights & AI Coach
    └──▶ Quest suggestions (auto-generated from your writing)

Habits
    │
    ├──▶ Skill Node XP (linked habit → progresses a Skill Tree)
    ├──▶ Domain XP (rolls up to your Life Domain level)
    ├──▶ Synergy Bonuses (complete related habits on the same day)
    └──▶ Recovery Tokens (earned every 14-day streak segment)

Skill Trees
    │
    ├──▶ Unlock new nodes as XP grows
    ├──▶ "Start Learning" creates a Goal + Tasks automatically
    └──▶ Completing all tasks auto-completes the node → more XP

Goals → Milestones → Quests → Tasks
    │
    ├──▶ Each completed task → XP → Domain level → Skill unlock
    └──▶ Progress rolls up automatically (tasks → quests → milestones → goal)

Life Domains
    │
    └──▶ Aggregate view of all the above per life area
         (Computer Science, Health, Finance, Music, etc.)

Weekly Boss Battles
    └──▶ Weekly challenges tied to your active goals/habits → bonus XP
```

Every action you take feeds multiple systems simultaneously. You don't need to manage them manually — the app does the rollup for you.

---

## 3. XP, Levels & Achievements

### How XP works

| Action | XP Earned |
|---|---|
| Morning journal entry | 15 XP |
| Night journal entry | 20 XP |
| Free journal entry | 10 XP |
| Completing a task | 50 XP |
| Completing a habit | 10–30 XP (+ modifiers) |
| Completing a skill node | 50–400 XP (scales with difficulty) |
| Completing a milestone | 75 XP |
| Defeating a Weekly Boss | 100–400 XP |
| Earning an achievement | 50–500 XP |

### Level progression

Every **500 XP** = 1 level. Your current level and XP bar are always visible at the bottom of the left sidebar.

### XP Modifiers (Habits)

When you log a habit, bonus multipliers can stack on top of the base XP:

| Modifier | Bonus | Condition |
|---|---|---|
| ☀️ Morning | +25% | Logged before 10am UTC |
| ⚡ First Today | +15% | First habit logged that day |
| 🔥 Perfect Week | +50% | 7-day streak milestone |
| 📈 Domain Boost | +40% | Domain has < 10% of total XP |
| ⚗️ Synergy Active | +20% | A synergy was triggered today |
| 🛡️ XP Token | +50% | Bonus XP recovery token spent |

### Achievements

Achievements are unlocked automatically when you hit certain milestones (e.g. 7-day streak, Level 5, completing 5 quests). Each awards bonus XP. View them on the **Skills** page.

---

## 4. Journal

The Journal is the heart of LiAInne. You write here daily; the AI reads everything you write to power the coach, insights, and quest suggestions.

### Entry Types

There are three entry types, each with a different structure:

#### 🌅 Morning Entry
Fill in before you start your day:
- **Today's Main Goal** — the one thing that would make today a success
- **Top 3 Tasks** — concrete actions (these become your daily plan)
- **Potential Obstacles** — what might derail you
- **Counterattack Plan** — how you'll respond if obstacles appear
- **Mood / Energy / Focus sliders** (1–5)

> Your Morning tasks are saved as a **Daily Plan** and reappear in the Night entry as a checklist.

#### 🌙 Night Entry
A structured reflection at day's end:
- **Biggest Win** — what went well
- **What Did I Learn?** — any insight or lesson
- **Went Well / Went Poorly** — honest split review
- **Gratitude** — one or more things you're grateful for
- **Tomorrow's Priority** — one thing to carry forward
- **Mood / Energy / Focus sliders**

> The Night entry also shows a checklist of your Morning tasks and today's habits so you can tick them off as part of reflection.

#### 📓 Free Entry
Open-ended writing with a title, tags (comma-separated), and sliders. Use this for anything that doesn't fit the structured formats — brainstorming, venting, processing an experience.

### One entry per type per day

Each entry type can only be submitted once per day. If you've already saved a Morning entry, the tab will show a ✓ badge and the submit button is disabled. A link appears to **edit** today's entry instead.

### Auto-generated Quest Suggestions

After saving any entry, the AI reads your writing and suggests 1–3 concrete quests derived from what you wrote (things you mentioned wanting to do, goals you referenced, habits you missed). A panel appears below the form with **+ Add Quest** buttons to add them directly to your goals.

---

## 5. Habits

Habits are repeatable daily actions tracked with streaks, mastery levels, and evolution stages.

### Creating a Habit

1. Go to the **Habits** page
2. Type the habit name in the top form (e.g. "Morning run")
3. Optionally link it to a **Skill Node** — this makes every log contribute XP toward that skill
4. Click **Log Habit** — this both creates and logs it for today

### Linking to a Skill Node

This is the most powerful feature of habits. When you select a Skill Node from the dropdown:
- Every log contributes 50% of earned XP directly toward that skill node
- The habit card shows which node and domain it's feeding
- Synergies become available

### Habit Cards

Each habit has a card showing:
- **Mastery Ring** — visual SVG ring showing mastery level (1–6)
- **Current Streak** and **Best Streak**
- **Success Rate** — completions ÷ days since first log
- **Evolution Stage** and progress to the next stage
- **Domain** and linked **Skill Node**
- **Recovery Tokens** available

#### Card Sections (top to bottom):
- **Log Today** button — becomes "✓ Logged" once done
- **📊 Stats** — opens detailed stats modal with heatmap + evolution path
- **✏️ Edit** — rename the habit or relink it to a different skill node
- **🗑️ Delete** — permanently removes the habit and all its history

### Mastery Levels

| Level | Label | Total Logs Required |
|---|---|---|
| 1 | Beginner | 0 |
| 2 | Apprentice | 7 |
| 3 | Journeyman | 30 |
| 4 | Expert | 90 |
| 5 | Master | 180 |
| 6 | Legend | 365 |

### Evolution

At **7, 21, 60, 120, and 200** total completions, your habit is ready to **evolve** — it advances to the next stage (a harder, deeper version of the same habit, AI-generated at creation). When evolution is ready:
1. A banner appears on the card
2. Click **Evolve ▶** to confirm or **Later** to defer
3. Evolution increases the base XP per log by 40%

### Synergies

If you complete **two or more related habits on the same day**, a synergy bonus is triggered. Examples:

| Synergy | Keywords | Bonus |
|---|---|---|
| Mental Clarity | journal + meditate | +15% XP, focus insights |
| Recovery Boost | exercise + sleep | +20% XP, streak protection |
| Learning Momentum | read + code/study | +25% XP, skill XP doubled |
| Creative Flow | write + draw/music | +20% XP, creative domain boost |
| Warrior Protocol | exercise + cold/fast | +30% XP, boss difficulty reduced |

Active synergies are shown as purple ⚗️ pills on your habit cards and in the synergy banner at the top of the page.

### Recovery Tokens

Tokens are earned automatically — one token per 14-day streak segment. Use them to protect your progress:

| Token | Cost | Effect |
|---|---|---|
| ↩ Restore | 1 | Restore a missed day (protects streak) |
| ⏭ Skip | 1 | Skip today without breaking streak |
| ⚡ Bonus XP | 1 | +50% XP on your next log |
| ❄️ Freeze | 2 | Freeze streak for 3 days |
| ⚔️ Boss | 2 | Reduce next Weekly Boss difficulty |
| ♻️ Quest | 2 | Recover a failed quest |

### Life Balance Dashboard

The bar chart at the top of the Habits page shows your habit completion rate per **Life Domain** over the last 14 days. Aim for balanced bars — gaps indicate neglected areas.

### Activity Heatmap

A GitHub-style heatmap showing the last 365 days of all habit activity combined. Darker pink = more habits logged that day.

---

## 6. Quests & Goals

The Quests page organises your goals into a 4-tier hierarchy:

```
Goal  (e.g. "Learn to code")
 └── Milestone  (e.g. "Complete Python basics")
      └── Quest  (e.g. "Finish loops chapter")
           └── Task  (e.g. "Write 3 practice programs")
```

Progress rolls up automatically — completing tasks completes quests, completing quests completes milestones, and so on.

### Creating a Goal

Use the form at the top of the Quests page:
1. Enter a **title**
2. Choose a **category** (Study, Fitness, Finance, etc.)
3. Click **+ Add Goal**

### Adding Milestones

Inside a goal card, click **+ Add Milestone**. Give it a name and optionally a target date. Milestones are major checkpoints — each one represents a meaningful chunk of the goal.

### Adding Quests

Inside a goal (or inside a milestone), click **⚔️ Add Quest**. Quests have a title and a **difficulty** (Easy / Normal / Hard / Elite). Quests are the main unit of work.

### Adding Tasks

Inside a quest, use the **+ Add** row to add individual tasks. Press Enter or click Add. Tasks are the smallest actionable unit — each completed task earns **50 XP**.

### Checking Off Tasks

Click the checkbox next to any task to toggle it complete. XP is awarded immediately and a flash notification appears. When all tasks in a quest are done, the quest auto-completes. When all quests in a milestone are done, the milestone auto-completes.

### Today's Main Quest Banner

At the top of the Quests page, the AI picks the **single most impactful task** you should do today from all your active goals, based on your mood, streaks at risk, and goal progress. Click ↺ to regenerate.

### Skill-Linked Goals

If you start a Skill Node from the **Skills** page, a goal is automatically created with all the structured tasks for that node. Completing every task in that goal auto-completes the skill node and awards the XP reward.

---

## 7. Skill Trees

Skill Trees provide structured long-term learning paths across five areas:

| Tree | Focus |
|---|---|
| 📚 Study | Computer Science — Python, DSA, OOP, Web Dev, AI, Security |
| 💪 Fitness | Physical Mastery — Consistency, Strength, Cardio, Nutrition |
| 💰 Finance | Financial Intelligence — Budgeting, Investing, Debt, Income |
| 🎨 Creativity | Creative Mastery — Foundations, Craft, Voice, Projects |
| 🌱 Personal Growth | Self Mastery — Awareness, Habits, Mindset, Focus, Leadership |

### Node States

| State | Meaning |
|---|---|
| 🔒 Locked | Prerequisites not met or XP too low |
| Available (pink border) | Ready to start |
| Active (green border) | Learning in progress |
| ✓ Mastered (light green) | Fully completed |

### How to Progress Through a Tree

1. Find an **Available** node
2. Click **▶ Start Learning** — a Goal with structured tasks is created automatically and you're taken to the Quests page
3. Complete all the tasks in that goal
4. When the last task is checked, the node is automatically mastered and XP is awarded
5. New nodes unlock based on your XP and completed prerequisites

### XP Requirements

Each node requires a minimum amount of category XP before it can be started. Complete tasks, habits, and boss battles in the relevant category to accumulate XP and unlock deeper nodes.

### Mastery Checks (Advanced)

Some nodes have a **Mastery Check** — a short written challenge or reflection that the AI evaluates before the node can be manually completed. The AI scores your response and gives feedback. You need to pass the check to unlock the completion button.

---

## 8. Life Domains

The Domains page gives you a bird's-eye view of your life organised into 7 areas:

| Domain | What it tracks |
|---|---|
| 💻 Computer Science | Study skill tree, CS goals, learning habits |
| 💪 Health | Fitness skill tree, health goals, physical habits |
| 🎵 Music | Creativity skill tree, music goals |
| ❤️ Relationships | Social goals, relationship habits |
| 🌱 Personal Growth | Personal Growth skill tree, mindset goals |
| 💰 Finance | Finance skill tree, finance goals |
| 🎨 Creativity | Creativity skill tree, art/writing goals |

### Domain Card

Each domain card shows:
- **Level and XP bar** — total XP from all sources in that domain
- **Quest completion %** — across all goals in the domain
- **Habits** — linked habits with streak info and today's status
- **Skill Trees** — node completion progress bars
- **Active Goals** — top 3 in-progress goals
- **This Week's Boss** — the domain's weekly boss battle (if generated)

---

## 9. Insights & Monthly Review

### Insights Page

The Insights page shows automatically detected patterns from your journal data:

- **Trend charts** — mood, energy, and focus over the last 30 days
- **Day-of-week chart** — which days tend to have your best mood
- **Pattern cards** — colour-coded observations (green = positive, orange = warning)

Types of insights you'll see:
- Mood / Energy / Focus trend direction (improving, declining, flat)
- Your best day of the week
- Strongest current habit streak
- Fastest-progressing goal category
- Stalled categories (inactive for 7+ days with < 50% completion)
- Consistency score (% of days journalled in the last 2 weeks)
- Growth plateau detection (both mood and energy flat for 7+ entries)

### Monthly Review

Go to the **Review** page and click **Generate Review** to get a full AI-written monthly summary covering:
- **Wins** — what went well this month
- **Challenges** — what was hard
- **Patterns** — what the data reveals
- **Focus For Next Month** — specific recommended priorities

The review is generated fresh each time and draws on your actual entry content, achievement history, and goal progress.

---

## 10. LiAInne Chat (AI Coach)

The chat panel on the right side of every page is your always-available AI coach.

### What LiAInne knows

Every time you send a message, LiAInne automatically receives:
- Your mood, energy, and focus trends (overall and last 7 vs previous 7 days)
- All journal entries from the last 14 days (full text)
- Older entries as weekly averages
- All habit streaks and categories
- Active risk alerts (streaks at risk, stagnation, goal failure risk)
- Semantically relevant older entries (matched to your question)

### What to ask

LiAInne works best with specific, honest questions:

- *"Why do I keep losing momentum on my study goals?"*
- *"What pattern do you see in my mood this month?"*
- *"I'm feeling burnt out today — what should I do?"*
- *"What habit should I focus on building next?"*
- *"Review my last week and tell me what's going well"*

### What LiAInne won't do

LiAInne is a coach, not a therapist or doctor. If you're in crisis or experiencing a mental health emergency, please contact local emergency services or a crisis line.

---

## 11. Weekly Boss Battles

Boss Battles are weekly challenges that push you to make real progress across your domains.

### Generating Bosses

1. Go to the **Domains** page
2. Click **Generate This Week's Bosses**
3. The AI creates 3 boss battles tailored to your active goals and habits
4. Each boss belongs to a specific domain and has 3–5 specific requirements

### Defeating a Boss

Once you've completed all the requirements for a boss (in real life — the app doesn't auto-detect this), click **⚔️ Mark Defeated** on the boss card. You'll receive the XP reward immediately.

Bosses expire at the end of the week (Sunday). New ones generate the following week.

### Boss XP

Boss battles award between **100 and 400 XP**, making them one of the highest-value single actions in the app.

---

## 12. Action Engine & Bottleneck Detector

### Action Engine (Domains page)

The ⚡ Action Engine panel at the top of the Domains page continuously monitors your data for problems and surfaces the most urgent one with a specific action to take right now. It detects:

- **Stagnation** — mood and energy both flat for 7+ entries
- **Burnout Risk** — energy declining sharply
- **Streak at Risk** — habits logged yesterday but not today
- **Goal Failure Risk** — goals with < 20% progress after 14+ days
- **Skill Bottleneck** — an unlocked skill node that hasn't been started
- **Declining Consistency** — journal gap > 50% in the last 2 weeks

### Bottleneck Detector (Domains page)

Click **Analyze** in the "🔍 Why Am I Stuck?" card to get a deeper diagnosis. The detector:

1. Scores all potential bottlenecks (Low Energy, Low Mood, Poor Focus, Goal Stagnation, Habit Inconsistency)
2. Identifies the primary issue with a confidence score
3. Shows the evidence from your data
4. Gives a 4-step recovery plan
5. Generates a personal AI message from LiAInne

---

## 13. Quick-Start Guide (First 10 Minutes)

Follow these steps to get the most out of LiAInne from day one:

**Step 1 — Write your first Morning Entry**
Go to **Journal**, fill in your main goal for today, add 2–3 tasks, rate your mood/energy/focus, and save. This unlocks the AI coach and starts tracking your trends.

**Step 2 — Create one Goal**
Go to **Quests**, add a goal with a meaningful title and category (e.g. "Get fit" → Fitness). Add one milestone and two or three quests with tasks underneath.

**Step 3 — Start a Skill Tree node**
Go to **Skills**, pick a tree that matches your goal, and click **▶ Start Learning** on the first available node. A goal with structured tasks is created automatically — go to Quests to find it.

**Step 4 — Log your first Habit**
Go to **Habits**, type a habit you want to build (e.g. "Read for 20 minutes"), link it to a Skill Node from Step 3, and click **Log Habit**.

**Step 5 — Check your Domains**
Go to **Domains** and see how everything you just did has already registered across your life domains. Generate your first Weekly Boss.

**Step 6 — Ask LiAInne something**
Use the chat panel to ask about your goals, request a recommendation, or just check in. The more you journal, the smarter the responses get.

---

## 14. FAQ

**Q: Do I have to fill in every entry type every day?**
No. Any entry is better than none. The Night entry and Free entry are optional — even a 2-sentence Morning entry keeps your trends running.

**Q: Why is my Skill Node still locked even though I have XP?**
Nodes require XP in the *specific category* of that tree, not total XP. For example, the Python Basics node requires 100 XP in the Study category specifically. Complete tasks in Study goals or log Study-linked habits to accumulate it.

**Q: How do recovery tokens work exactly?**
You earn 1 token for every 14 consecutive days of logging a habit. They accumulate. Use them to restore missed days (which keeps your streak intact), skip days, or buy boosts.

**Q: Can I have the same habit linked to multiple skill nodes?**
No — each habit links to one skill node at a time. You can edit the habit to change which node it feeds.

**Q: What happens if I delete a goal that was created by a Skill Node?**
The goal and tasks are deleted, but the skill node returns to "Available" status — you can start it again and a new goal will be created.

**Q: The AI coach doesn't seem to know about something I wrote. Why?**
The coach has full access to the last 14 days of entries by text, and older entries by weekly averages. For very specific older events, it uses semantic search to find relevant entries. If something isn't surfacing, try referencing it directly in your chat message.

**Q: My XP doesn't seem to be going up. What's wrong?**
XP is awarded at the moment of action — task completions, habit logs, journal saves. Refresh the page if the sidebar level bar looks stale. Check the Achievements page to see your total XP.

**Q: How do Synergies expire?**
Synergies last 24 hours from when they were triggered. They appear as purple pills on habit cards and in the synergy banner — once expired they disappear automatically.

---

*LiAInne — built for people who take their growth seriously.*
# LiAInne — a journal at your own pace

FastAPI + Supabase + vanilla HTML/CSS/JavaScript.

## Start on Windows

Double-click **Start Journal.bat**. On the first run, it creates a separate Windows Python environment and installs the app dependencies (internet required). Install Python 3.10 to 3.13 from https://www.python.org/downloads/windows/ first if prompted. The browser opens automatically when the journal is ready. Keep the command window open while using the journal; close it or press Ctrl+C to stop the server. If port 8000 is already in use, close the other program using it and try again. To make the journal easier to find, right-click the batch file and create a desktop shortcut.

Your existing `.local-data/journal.sqlite3` and `.env` remain in this folder; keep them when moving the app. If `LIAINNE_JOURNAL_DB` in `.env` points to an old WSL path, update it to a Windows path or remove the setting to use the local default. The old Linux `venv` is not used on Windows.

For development or other platforms, start as before:

```sh
uvicorn main:app
```

Journaling and optional Game tools use SQLite by default. Run the app without Supabase credentials or an AI model.

## Everyday use

- **Today:** an optional note, initially unset mood, and at most one priority. Save a note or mood alone. Longer morning/night reflections are optional. Multiple notes per day are welcome.
- **Journal:** paginated historical entries, including old entry types.
- **Progress:** cumulative recorded moments and days, without a streak requirement. Gamification is an optional secondary destination.
- **Tasks:** explicitly create a task, bring an older task to today, postpone it to a chosen date, archive it, or restore it. The most recent move has an Undo button. Archived tasks retain their original records; completion is not changed by moving them. Existing quest/subtask completion remains in the optional Quest Board.
- Existing quests, books, skills, habits, domains, resume, routines and calendar remain in **Optional tools** (`/tools.html`). These legacy tools retain more detailed controls than the everyday screen.

A welcome-back message appears after **7 local calendar days** since the latest non-skipped journal entry. The calendar uses the existing UTC+8 convention. A new user sees no absence message. Dismissal is stored in the browser, keyed to the last recorded date. Nothing is generated to compensate for an absence.

Reflection saves append only journal data: no tasks, AI jobs, XP grants, or automatic achievement checks. Select text in the note and use **Turn selected note text into a task**, review the task title, then explicitly create it. A priority is saved as part of the reflection, not as a commitment on the task board.

## AI and storage

**Local AI is optional and off by default.** All automatic/legacy AI routes, providers, embeddings, and model downloads remain blocked. Saving and reading journal entries use SQLite independently of Ollama.

1. Install Ollama on the same computer as FastAPI. Use an already downloaded local model. This app never pulls models.
2. Set `OLLAMA_NO_CLOUD=1` **for the Ollama server**, then restart Ollama. For an interactive Linux/WSL service, launch `OLLAMA_NO_CLOUD=1 ollama serve`. For a system service, set the variable in that service’s environment. On Windows set the user environment variable, fully quit Ollama, and relaunch it. [Ollama local-only configuration](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features).
3. Start FastAPI with `uvicorn main:app`. Under **Settings → Local AI (Ollama)**, test the connection, enable the feature, and select `qwen3:4b` (fast) or `qwen3:8b` (better quality). Coding models are hidden unless explicitly revealed. If you already have these models, skip installation/download steps.
4. Open **Journal** or **Game → Entries**. Select text or use a whole entry, choose **Ask local AI**, write a question, and preview the exact messages. Only **Send** calls the model. **Stop** cancels generation. **Save as note** explicitly writes the answer as a separate entry. Enabling the feature does not authorize reading other entries or analyzing history.

FastAPI connects only to a loopback HTTP Ollama server. Defaults are `OLLAMA_BASE_URL=http://localhost:11434`, `OLLAMA_MODEL=qwen3:4b`, `LOCAL_AI_ENABLED=false`, `OLLAMA_NUM_CTX=4096`, `OLLAMA_TIMEOUT_SECONDS=120`, and `OLLAMA_KEEP_ALIVE=5m`. Settings choices override the initial enable/model defaults and persist with this local installation. The local AI permission is deliberately excluded from portable data backups. No API key, CORS adjustment, or public Ollama port is needed. If an older .env points at a network IP or a /v1 provider URL, replace it with the loopback URL above. With FastAPI in WSL, Ollama must be reachable from that environment’s loopback.

Status checks read installed-model metadata only. Preview never calls Ollama. A conservative UTF-8 byte budget reserves space for model formatting and a 512-token answer. The preview reports exactly how many passage characters were removed. Generation uses temperature 0.6 and disables Qwen thinking by default. Settings can show reasoning separately. Older Ollama versions that reject the thinking option are retried without it.

If you host FastAPI elsewhere, localhost points to that server. Using a laptop model from a hosted backend would require a separately secured setup, such as a private tunnel. This app implements only the same-computer configuration.

Run the app on the loopback interface (127.0.0.1). The single-user server has no login, and its API can read, export, and replace journal data. Keep it off shared networks and public hosts.

All app tables live in `.local-data/journal.sqlite3` on the machine running FastAPI. Set `LIAINNE_JOURNAL_DB` to choose another persistent file. It contains plaintext journal content. Fonts and charts are bundled so the interface can render offline.

**Settings → Export JSON** downloads all 31 tables and the current browser’s LiAInne preferences. **Import JSON** validates a Settings backup, saves a recovery copy in `backup/`, then replaces local records in one transaction. Browser persistence applies to preferences. SQLite lives outside browser storage.

### One-time Supabase migration

The export uses read-only requests, paginates in primary-key order, and includes schema metadata, exact counts, and any Storage files. Keep exports and reports with real database counts private.

```sh
# Node 20.12+ loads .env automatically. On Node 18, let Python load it:
venv/bin/python -c "from backend import bootstrap_env; import subprocess; subprocess.run(['node','scripts/export-supabase.mjs'],check=True)"
# Substitute the exact timestamped file printed by the export:
venv/bin/python -m scripts.import_supabase backup/supabase-export-TIMESTAMP.json
venv/bin/python -m scripts.import_supabase backup/supabase-export-TIMESTAMP.json --apply
```

Without `--apply`, the importer checks a disposable copy. Applying merges records by original primary key, refuses conflicting values, compares every imported row, and verifies foreign keys before commit. Keep the original export and recovery file private.

`LIAINNE_DATA_BACKEND=sqlite` is the default. To restore the **previous hybrid mode**, set it to `supabase` with valid Supabase credentials and restart. Optional tools then use Supabase, while journal entries continue using SQLite. The two databases do not synchronize.

## Progress and historical data

Imported entries, completed tasks, XP ledgers, achievements and saved skill completions retain their source IDs and values. Board reads no longer generate tasks, expire old daily/recovery quests, or reset repeating quests. Habit-recovery generation is disabled.

The optional live skill-mastery display now evaluates participation at the last recorded activity date, without the old daily inactivity subtraction. This can change the *displayed calculated percentage* relative to the old formula; no saved scores or historical ledger rows are rewritten. Old gamification mechanics otherwise remain available only in optional tools. This release does not add weekly-target configuration.

Task archive uses the existing unrestricted `section` text column (`archived`), and excludes archived tasks from the optional active board. Undo lasts until another move replaces it or the page reloads; Restore remains available afterward. There are no bulk changes.

SQLite preserves unset mood, energy, and focus values. No migrations, exports, seeds, or deletes are run automatically.

## Verification

```sh
venv/bin/python -m unittest discover -s tests -v
```

Tests use temporary SQLite files for entries and an in-memory stand-in for remote tools. They cover note-only/mood-only/repeated saves, validation, optional reflections, 14-day return, preserved tasks, reversible placement, startup without AI, blocked direct AI APIs/helpers, disabled background embedding, database failures and nullable trend ratings.

For a synthetic browser preview only:

```sh
venv/bin/python tests/preview_calm.py
# http://localhost:8765
```

This preview never connects to Supabase and is not persistent. Production Supabase integration is intentionally not exercised by these tests. Existing SQL is the compatibility reference; no real journal data should be seeded or cleared during verification.

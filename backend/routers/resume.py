"""Resume-skill API routes."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.db import supabase

router = APIRouter()
_services = {}


def configure(**services) -> None:
    """Supply shared cross-feature services from the application composition root."""
    _services.update(services)


# Resume Skills — a hard/soft skills list you can confidently put on a resume.
# Deliberately separate from the Skill Trees: a tree node like "Data
# Structures" isn't itself a resume line, and a resume also needs soft
# skills (discipline, follow-through) that no tree tracks at all. This is a
# simple standalone list with evidence text per skill, plus auto-suggestions
# pulled from things you've actually demonstrated elsewhere in the app —
# completed skill nodes (hard), and streaks/achievements/level (soft) — so
# the list stays grounded in real evidence instead of aspirational claims.
#
# Requires a `resume_skills` table: id, name, skill_type ('hard'|'soft'),
# category, evidence, confidence (1-5), source_type, source_id, created_at.
# ---------------------------------------------------------------------------

class ResumeSkillCreate(BaseModel):
    name: str
    skill_type: str          # "hard" | "soft"
    category: str = ""
    evidence: str = ""
    confidence: int = 3      # 1-5, how confidently you can claim this

class ResumeSkillUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    evidence: Optional[str] = None
    confidence: Optional[int] = None

def _clamp_confidence(v) -> int:
    try:    return max(1, min(5, int(v)))
    except: return 3

@router.get("/resume/skills")
def get_resume_skills():
    try:
        rows = (
            supabase.table("resume_skills")
            .select("*")
            .order("confidence", desc=True)
            .order("created_at", desc=True)
            .execute()
            .data
        )
    except Exception:
        rows = []
    return {
        "hard": [r for r in rows if r.get("skill_type") == "hard"],
        "soft": [r for r in rows if r.get("skill_type") == "soft"],
    }

@router.post("/resume/skills")
def create_resume_skill(s: ResumeSkillCreate):
    if s.skill_type not in ("hard", "soft"):
        raise HTTPException(400, "skill_type must be 'hard' or 'soft'")
    name = s.name.strip()
    if not name:
        raise HTTPException(400, "Name is required")
    row = supabase.table("resume_skills").insert({
        "name":        name,
        "skill_type":  s.skill_type,
        "category":    s.category.strip(),
        "evidence":    s.evidence.strip(),
        "confidence":  _clamp_confidence(s.confidence),
        "source_type": "manual",
        "source_id":   f"manual:{datetime.now(timezone.utc).isoformat()}",
        "created_at":  datetime.now(timezone.utc).isoformat(),
    }).execute()
    return {"status": "created", "skill": row.data[0]}

@router.put("/resume/skills/{skill_id}")
def update_resume_skill(skill_id: int, s: ResumeSkillUpdate):
    update = {k: v for k, v in s.dict().items() if v is not None}
    if "name" in update:
        update["name"] = update["name"].strip() or "Untitled Skill"
    if "confidence" in update:
        update["confidence"] = _clamp_confidence(update["confidence"])
    if not update:
        raise HTTPException(400, "Nothing to update")
    result = supabase.table("resume_skills").update(update).eq("id", skill_id).execute()
    if not result.data:
        raise HTTPException(404, "Skill not found")
    return {"status": "updated", "skill": result.data[0]}

@router.delete("/resume/skills/{skill_id}")
def delete_resume_skill(skill_id: int):
    result = supabase.table("resume_skills").delete().eq("id", skill_id).execute()
    if not result.data:
        raise HTTPException(404, "Skill not found")
    return {"status": "deleted"}

def _build_resume_suggestions() -> dict:
    """
    Suggests resume-worthy skills backed by concrete evidence already in the
    app, filtered against skills already added so the same suggestion
    doesn't keep reappearing once accepted (or manually added under the
    same name). Hard skills come from mastered skill-tree nodes; soft
    skills come from patterns (long streaks, achievement volume, level,
    quest follow-through) that are genuinely hard to fake.
    """
    try:
        existing_names = {
            (r.get("name") or "").strip().lower()
            for r in supabase.table("resume_skills").select("name").execute().data
        }
    except Exception:
        existing_names = set()

    hard = []
    try:
        completed = supabase.table("skill_progress").select("node_id, category").execute().data
        seen = set()
        for c in completed:
            tree = _services["skill_trees"].get(c.get("category"))
            if not tree:
                continue
            node = next((n for n in tree["nodes"] if n["id"] == c.get("node_id")), None)
            if not node:
                continue
            key = node["name"].lower()
            if key in existing_names or key in seen:
                continue
            seen.add(key)
            hard.append({
                "name":     node["name"],
                "category": tree.get("label", c["category"]),
                "evidence": f"Completed the '{node['name']}' skill node in {tree.get('label', c['category'])}, including its mastery check.",
                "source":   "skill_node",
            })
    except Exception as e:
        _services["logger"].exception("_build_resume_suggestions hard skills failed: %s", e)

    soft = []
    try:
        streaks    = _services["compute_streaks_raw"]()
        best_name, best_streak = max(
            ((n, v["current_streak"]) for n, v in streaks.items()),
            key=lambda x: x[1], default=(None, 0)
        )
        if best_streak >= 14 and "discipline" not in existing_names:
            soft.append({
                "name": "Discipline", "category": "Self-Management",
                "evidence": f"Sustained a {best_streak}-day streak on '{best_name}' without a manual log system to lean on.",
                "source": "habit_streak",
            })
        if best_streak >= 30 and "consistency" not in existing_names:
            soft.append({
                "name": "Consistency", "category": "Self-Management",
                "evidence": f"Maintained a {best_streak}-day streak on '{best_name}'.",
                "source": "habit_streak",
            })
    except Exception as e:
        _services["logger"].exception("_build_resume_suggestions streak check failed: %s", e)

    try:
        ach_count = len(supabase.table("achievements").select("id").execute().data)
        if ach_count >= 5 and "goal setting" not in existing_names:
            soft.append({
                "name": "Goal Setting", "category": "Self-Management",
                "evidence": f"Earned {ach_count} milestone achievements tracking self-directed personal goals.",
                "source": "achievements",
            })
    except Exception as e:
        _services["logger"].exception("_build_resume_suggestions achievements check failed: %s", e)

    try:
        level = _services["xp_to_level"](_services["get_total_xp"]())["level"]
        if level >= 10 and "self-directed learning" not in existing_names:
            soft.append({
                "name": "Self-Directed Learning", "category": "Self-Management",
                "evidence": f"Reached Level {level} in a self-managed, gamified personal-growth system spanning multiple skill domains.",
                "source": "level",
            })
    except Exception as e:
        _services["logger"].exception("_build_resume_suggestions level check failed: %s", e)

    try:
        rows  = supabase.table("board_quests").select("is_completed").execute().data
        total = len(rows)
        done  = sum(1 for r in rows if r.get("is_completed"))
        if total >= 20 and done / total >= 0.6 and "follow-through" not in existing_names:
            soft.append({
                "name": "Follow-Through", "category": "Self-Management",
                "evidence": f"Completed {done} of {total} self-assigned tasks and quests tracked to date.",
                "source": "quest_completion",
            })
    except Exception as e:
        _services["logger"].exception("_build_resume_suggestions quest completion check failed: %s", e)

    return {"hard": hard, "soft": soft}

@router.get("/resume/suggestions")
def get_resume_suggestions():
    return _build_resume_suggestions()


# cache-bust-2026-09-29-1
import io
import re
import zipfile
import hashlib
import secrets
import os
import json
import base64
from datetime import datetime, date

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import linregress
import streamlit as st
from supabase import create_client, Client
from ai_advisor import render_ai_advisor

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, HRFlowable, Image
)

st.set_page_config(
    page_title="Student Academic Management System",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
h1, h2, h3, h4, h5, h6 {
    line-height: 1.35 !important;
    padding-top: .20rem !important;
    padding-bottom: .30rem !important;
    margin-top: .45rem !important;
    margin-bottom: .65rem !important;
}
.welcome-title {
    line-height: 1.35 !important;
    padding: .55rem .25rem .75rem .25rem !important;
    margin: .20rem 0 .90rem 0 !important;
}
[data-testid="stAppViewContainer"] .main .block-container {
    padding-top: 2rem !important;
    padding-bottom: 2rem !important;
}
label, .stMarkdown, .stText, p {
    line-height: 1.45 !important;
}
.block-container {padding-top: 3rem; padding-bottom: 2rem;}
.app-title {font-size: 2rem; font-weight: 750; margin-bottom: 0;}
.app-subtitle {color:#6b7280; margin-top:2px; margin-bottom:18px;}
.section-title {font-size:1.15rem; font-weight:700; margin-top:12px;}
div[data-testid="stMetric"] {
    border: 1px solid rgba(128,128,128,0.35);
    border-radius: 12px;
    padding: 10px 14px;
    background: rgba(128,128,128,0.08);
}
div[data-testid="stMetric"] * {
    color: inherit !important;
}
div[data-testid="stMetricLabel"],
div[data-testid="stMetricValue"],
div[data-testid="stMetricDelta"] {
    color: inherit !important;
}
.school-banner {
    border-radius: 16px;
    padding: 1rem 1.2rem;
    margin-bottom: 1rem;
    border: 1px solid rgba(128,128,128,.22);
    background: linear-gradient(90deg, rgba(128,128,128,.10), rgba(128,128,128,.03));
}
.school-banner .school-name {
    font-size: 1.55rem;
    font-weight: 800;
    line-height: 1.3;
}
.school-banner .school-subtitle {
    font-size: .9rem;
    opacity: .72;
    margin-top: .15rem;
}
</style>
""", unsafe_allow_html=True)

DEFAULT_SCHOOL = "EXCELLENCE SECONDARY SCHOOL"
import re as _re_module

def detect_terms_from_columns(columns):
    """Scan columns and return a sorted list of unique terms like ['y1t1','y1t2','y2t3','y3t1',...]."""
    pattern = _re_module.compile(r"^(y\d+t\d+)")
    found = set()
    for col in columns:
        col_lower = str(col).lower().strip()
        match = pattern.match(col_lower)
        if match:
            found.add(match.group(1))
    # Sort: first by year, then by term
    def sort_key(t):
        m = _re_module.match(r"y(\d+)t(\d+)", t)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        return (0, 0)
    return sorted(found, key=sort_key)

TERMS = ["y1t1", "y1t2", "y1t3", "y2t1", "y2t2", "y2t3"]  # fallback default


# ============================================================
# SUPABASE CLIENT
# ============================================================

def get_supabase_client() -> Client:
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_KEY", "")
    if not url or not key:
        st.error(
            "⚠️ Supabase credentials are not configured. "
            "Please add SUPABASE_URL and SUPABASE_KEY to Streamlit Secrets."
        )
        st.stop()
    return create_client(url, key)


class _SupabaseProxy:
    """Routes every query to the logged-in school's client.
    Falls back to the default (global) client if no school is logged in."""

    def _client(self):
        c = st.session_state.get("school_client")
        if c is not None:
            return c
        if "_default_client" not in st.session_state:
            st.session_state["_default_client"] = get_supabase_client()
        return st.session_state["_default_client"]

    def table(self, *args, **kwargs):
        return self._client().table(*args, **kwargs)

    def auth(self, *args, **kwargs):
        return self._client().auth

    def storage(self, *args, **kwargs):
        return self._client().storage

    def rpc(self, *args, **kwargs):
        return self._client().rpc(*args, **kwargs)

    def postgrest(self):
        return self._client().postgrest


supabase = _SupabaseProxy()


# ============================================================
# PASSWORD HASHING
# ============================================================

def hash_password(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${hashed}"


def verify_password(password, stored):
    if not stored:
        return False
    if "$" not in stored:
        return stored == password
    salt, hashed = stored.split("$", 1)
    return hash_password(password, salt) == f"{salt}${hashed}"


# ============================================================
# USER / AUTH
# ============================================================

def ensure_demo_users():
    try:
        for uname, pwd, role in [("teacher", "teacher123", "teacher"),
                                  ("student", "student123", "student")]:
            existing = supabase.table("users").select("username").eq("username", uname).execute()
            if not existing.data:
                supabase.table("users").insert({
                    "username": uname,
                    "password": hash_password(pwd),
                    "role": role,
                    "student_name": ""
                }).execute()
    except Exception:
        pass


ensure_demo_users()


def authenticate_user(username, password, client=None):
    try:
        c = client or supabase
        result = c.table("users").select("*").eq("username", username.strip()).execute()
        if not result.data:
            return None
        user = result.data[0]
        if not verify_password(password, user.get("password", "")):
            return None
        if "$" not in (user.get("password") or ""):
            supabase.table("users").update({
                "password": hash_password(password)
            }).eq("username", user["username"]).execute()
        return user
    except Exception as e:
        st.error(f"Database error during login: {e}")
        return None


def get_parent_profile(username):
    try:
        result = supabase.table("parents").select("*").eq("username", username.strip()).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def get_student_profile(username):
    try:
        result = supabase.table("students").select("*").eq("username", username.strip()).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def create_or_update_parent(username, parent_name, password, child_names):
    hashed = hash_password(password)
    existing = supabase.table("users").select("username").eq("username", username).execute()
    if existing.data:
        supabase.table("users").update({
            "password": hashed, "role": "parent", "student_name": ""
        }).eq("username", username).execute()
    else:
        supabase.table("users").insert({
            "username": username, "password": hashed,
            "role": "parent", "student_name": ""
        }).execute()
    existing_p = supabase.table("parents").select("username").eq("username", username).execute()
    if existing_p.data:
        supabase.table("parents").update({
            "parent_name": parent_name, "child_names": child_names
        }).eq("username", username).execute()
    else:
        supabase.table("parents").insert({
            "username": username,
            "parent_name": parent_name,
            "child_names": child_names,
            "created_at": datetime.now().isoformat()
        }).execute()


def create_or_update_student(username, student_full_name, password):
    hashed = hash_password(password)
    existing = supabase.table("users").select("username").eq("username", username).execute()
    if existing.data:
        supabase.table("users").update({
            "password": hashed, "role": "student",
            "student_name": student_full_name
        }).eq("username", username).execute()
    else:
        supabase.table("users").insert({
            "username": username, "password": hashed,
            "role": "student", "student_name": student_full_name
        }).execute()
    existing_s = supabase.table("students").select("username").eq("username", username).execute()
    if existing_s.data:
        supabase.table("students").update({
            "student_full_name": student_full_name
        }).eq("username", username).execute()
    else:
        supabase.table("students").insert({
            "username": username,
            "student_full_name": student_full_name,
            "created_at": datetime.now().isoformat()
        }).execute()


def change_user_password(username, new_password):
    supabase.table("users").update({
        "password": hash_password(new_password)
    }).eq("username", username).execute()


# ============================================================
# BULK IMPORT HELPERS
# ============================================================

import random
import string as _string


def _slugify_name(full_name):
    """Turn 'Mr. Peter Kamau' into 'peter.kamau'."""
    name = str(full_name or "").strip()
    # Drop common titles
    for title in ["mr.", "mrs.", "ms.", "miss", "dr.", "prof.", "sir", "madam"]:
        if name.lower().startswith(title):
            name = name[len(title):].strip()
    # Keep only letters, spaces, dots
    cleaned = "".join(c if (c.isalnum() or c in " .-_") else "" for c in name)
    parts = [p for p in cleaned.replace("_", " ").replace("-", " ").split() if p]
    if not parts:
        return "user"
    return ".".join(p.lower() for p in parts)


def _generate_username(full_name, taken):
    """Generate a unique username. Appends a number if already taken."""
    base = _slugify_name(full_name)
    username = base
    counter = 1
    while username.lower() in {t.lower() for t in taken}:
        counter += 1
        username = f"{base}{counter}"
    taken.add(username)
    return username


def _generate_password():
    """8-character random password with letters and digits."""
    chars = _string.ascii_letters + _string.digits
    return "".join(random.choice(chars) for _ in range(8))


def _bulk_import_users(df, role, name_column, extra_columns=None):
    """
    Bulk-create user accounts from a DataFrame.

    df: pandas DataFrame with at least a name column
    role: 'teacher' | 'student' | 'parent' | 'clerk' | 'exams' | 'it_officer' | 'admin'
    name_column: column name that holds the person's full name
    extra_columns: dict mapping extra logic per role, e.g. {'stream': 'stream'}

    Returns dict: {'created': [...], 'skipped': [...], 'errors': [...]}
    """
    created = []
    skipped = []
    errors = []

    # Fetch existing usernames to avoid collisions
    try:
        existing_rows = supabase.table("users").select("username").execute().data or []
        taken = {r["username"] for r in existing_rows}
    except Exception as e:
        return {"created": [], "skipped": [], "errors": [f"Could not fetch existing users: {e}"]}

    for idx, row in df.iterrows():
        try:
            full_name = str(row.get(name_column, "")).strip()
            if not full_name or full_name.lower() == "nan":
                continue

            # Username: from Excel if provided, else generated
            username = str(row.get("username", "")).strip() if "username" in df.columns else ""
            if not username:
                username = _generate_username(full_name, taken)
            elif username.lower() in {t.lower() for t in taken}:
                skipped.append({"row": idx + 2, "name": full_name, "reason": f"username '{username}' already exists"})
                continue
            else:
                taken.add(username)

            # Password: from Excel if provided, else generated
            password = str(row.get("password", "")).strip() if "password" in df.columns else ""
            if not password:
                password = _generate_password()

            # Role-specific fields
            extra_payload = {}
            if role == "student":
                # student_name for students = full name
                extra_payload["student_name"] = full_name
            elif role == "parent":
                extra_payload["student_name"] = ""
                # Parent row may have a children column
                children = str(row.get("children", "")).strip() if "children" in df.columns else ""
                if children and children.lower() != "nan":
                    # Also write to parents table
                    try:
                        existing_p = supabase.table("parents").select("username").eq("username", username).execute()
                        if existing_p.data:
                            supabase.table("parents").update({
                                "parent_name": full_name,
                                "child_names": children,
                            }).eq("username", username).execute()
                        else:
                            supabase.table("parents").insert({
                                "username": username,
                                "parent_name": full_name,
                                "child_names": children,
                            }).execute()
                    except Exception:
                        pass
            else:
                extra_payload["student_name"] = full_name

            # Write user row
            try:
                hashed = hash_password(password)
                supabase.table("users").insert({
                    "username": username,
                    "password": hashed,
                    "role": role,
                    **extra_payload,
                }).execute()
                created.append({
                    "row": idx + 2,
                    "name": full_name,
                    "username": username,
                    "password": password,
                    "role": role,
                })
            except Exception as e:
                errors.append({"row": idx + 2, "name": full_name, "error": str(e)})

        except Exception as e:
            errors.append({"row": idx + 2, "name": str(row.get(name_column, "")), "error": str(e)})

    return {"created": created, "skipped": skipped, "errors": errors}


def _ensure_class_exists(class_name):
    """Create a class in tt_class_teacher if it doesn't exist."""
    try:
        existing = supabase.table("tt_class_teacher").select("id").eq("class_name", class_name).limit(1).execute()
        if existing.data:
            return True
        supabase.table("tt_class_teacher").insert({
            "class_name": class_name,
            "subject_name": "FREE",
            "teacher_id": None,
            "periods_per_week": 0,
        }).execute()
        return True
    except Exception as e:
        return str(e)


def _ensure_subject_exists(subject_name, periods_per_week=3):
    """Create a subject in tt_subjects if it doesn't exist."""
    try:
        existing = supabase.table("tt_subjects").select("id").eq("subject_name", subject_name).execute()
        if existing.data:
            return True
        supabase.table("tt_subjects").insert({
            "subject_name": subject_name,
            "periods_per_week": int(periods_per_week),
            "has_double": False,
            "double_count": 0,
            "requires_lab": False,
            "lab_type": None,
        }).execute()
        return True
    except Exception as e:
        return str(e)


def _assign_teacher_to_class(teacher_full_name, subject_name, class_name, periods_per_week=3):
    """Create/update a tt_class_teacher row linking teacher + subject + class."""
    try:
        t = supabase.table("tt_teachers").select("id").eq("full_name", teacher_full_name).execute()
        if not t.data:
            return f"Teacher {teacher_full_name} not found in tt_teachers"
        teacher_id = t.data[0]["id"]

        _ensure_subject_exists(subject_name, periods_per_week)

        existing = supabase.table("tt_class_teacher").select("id").eq("class_name", class_name).eq("subject_name", subject_name).execute()
        if existing.data:
            supabase.table("tt_class_teacher").update({
                "teacher_id": teacher_id,
                "periods_per_week": int(periods_per_week),
            }).eq("id", existing.data[0]["id"]).execute()
        else:
            supabase.table("tt_class_teacher").insert({
                "class_name": class_name,
                "subject_name": subject_name,
                "teacher_id": teacher_id,
                "periods_per_week": int(periods_per_week),
            }).execute()
        return True
    except Exception as e:
        return str(e)


def _bulk_import_subjects(df):
    """Import subjects into tt_subjects. Accepts multiple column name variants."""
    created = []
    errors = []

    # Normalize column names
    df.columns = [str(c).strip().lower() for c in df.columns]

    # Map the various column names you might use to canonical ones
    rename_map = {}
    for c in df.columns:
        if c in ["subject", "subjects", "subject name"]:
            rename_map[c] = "subject"
        elif c in ["periods per week", "period per week", "periods/week", "ppw"]:
            rename_map[c] = "periods per week"
        elif c in ["has double", "has double lesson", "double"]:
            rename_map[c] = "has double"
        elif c in ["requires lab", "required lab", "lab"]:
            rename_map[c] = "requires lab"
        elif c in ["lab type", "labtype", "lab name"]:
            rename_map[c] = "lab type"
    df = df.rename(columns=rename_map)

    for idx, row in df.iterrows():
        try:
            subject_name = str(row.get("subject", "")).strip()
            if not subject_name or subject_name.lower() == "nan":
                continue

            ppw = 3
            try:
                ppw = int(row.get("periods per week", 3))
            except Exception:
                pass

            has_double = str(row.get("has double", "no")).strip().lower() in ["yes", "true", "1", "y"]
            requires_lab = str(row.get("requires lab", "no")).strip().lower() in ["yes", "true", "1", "y"]
            lab_type = str(row.get("lab type", "")).strip()

            existing = supabase.table("tt_subjects").select("id").eq("subject_name", subject_name).execute()
            payload = {
                "subject_name": subject_name,
                "periods_per_week": ppw,
                "has_double": has_double,
                "double_count": 1 if has_double else 0,
                "requires_lab": requires_lab,
                "lab_type": lab_type or None,
            }
            if existing.data:
                supabase.table("tt_subjects").update(payload).eq("id", existing.data[0]["id"]).execute()
                created.append({"subject": subject_name, "action": "updated"})
            else:
                supabase.table("tt_subjects").insert(payload).execute()
                created.append({"subject": subject_name, "action": "created"})
        except Exception as e:
            errors.append({"row": idx + 2, "subject": str(row.get("subject", "")), "error": str(e)})

    return {"created": created, "errors": errors}


def _bulk_import_periods(df):
    """Import periods into tt_periods."""
    created = []
    errors = []

    for idx, row in df.iterrows():
        try:
            pno = int(row.get("period no", 0))
            if pno <= 0:
                continue
            start = str(row.get("start time", "")).strip()
            end = str(row.get("end time", "")).strip()
            existing = supabase.table("tt_periods").select("id").eq("period_no", pno).execute()
            payload = {
                "period_no": pno,
                "start_time": start,
                "end_time": end,
                "is_break": False,
                "break_label": None,
            }
            if existing.data:
                supabase.table("tt_periods").update(payload).eq("id", existing.data[0]["id"]).execute()
                created.append({"period": pno, "action": "updated"})
            else:
                supabase.table("tt_periods").insert(payload).execute()
                created.append({"period": pno, "action": "created"})
        except Exception as e:
            errors.append({"row": idx + 2, "period": str(row.get("period no", "")), "error": str(e)})

    return {"created": created, "errors": errors}


def _credentials_csv(created_rows):
    """Turn a list of created-user dicts into a CSV bytes object."""
    if not created_rows:
        return b""
    lines = ["Name,Username,Password,Role"]
    for r in created_rows:
        # Escape commas in names by wrapping in quotes
        name = str(r["name"]).replace('"', '""')
        lines.append(f'"{name}",{r["username"]},{r["password"]},{r["role"]}')
    return "\n".join(lines).encode("utf-8")
def create_or_update_teacher(username, full_name, password):
    hashed = hash_password(password)
    existing = supabase.table("users").select("username").eq("username", username).execute()
    if existing.data:
        supabase.table("users").update({
            "password": hashed, "role": "teacher",
            "student_name": full_name
        }).eq("username", username).execute()
    else:
        supabase.table("users").insert({
            "username": username, "password": hashed,
            "role": "teacher", "student_name": full_name
        }).execute()


def get_teachers():
    try:
        result = supabase.table("users").select("username,student_name").eq("role", "teacher").order("username").execute()
        return result.data or []
    except Exception:
        return []


def delete_teacher(username):
    try:
        supabase.table("users").delete().eq("username", username).eq("role", "teacher").execute()
    except Exception:
        pass


# ============================================================
# RESULTS STORE
# ============================================================

def save_results_store(raw_df):
    try:
        records = raw_df.fillna("").to_dict(orient="records")
        data_json = json.dumps(records, default=str)
        existing = supabase.table("results_store").select("id").eq("name", "current").execute()
        if existing.data:
            supabase.table("results_store").update({
                "data_json": data_json,
                "updated_at": datetime.now().isoformat()
            }).eq("name", "current").execute()
        else:
            supabase.table("results_store").insert({
                "name": "current",
                "data_json": data_json,
                "updated_at": datetime.now().isoformat()
            }).execute()
        return True
    except Exception as e:
        st.warning(f"Could not save results to cloud: {e}")
        return False


def load_results_store():
    try:
        result = supabase.table("results_store").select("data_json").eq("name", "current").execute()
        if not result.data:
            return None
        records = json.loads(result.data[0]["data_json"])
        return pd.DataFrame(records)
    except Exception:
        return None


# ============================================================
# LEARNING CENTRE
# ============================================================

def add_material(title, material_type, subject, target_stream, description,
                 deadline, file_name, file_path, external_link, uploaded_by):
    supabase.table("materials").insert({
        "title": title,
        "material_type": material_type,
        "subject": subject,
        "target_stream": target_stream,
        "description": description,
        "deadline": deadline,
        "file_name": file_name,
        "file_path": file_path,
        "external_link": external_link,
        "uploaded_by": uploaded_by,
        "created_at": datetime.now().isoformat()
    }).execute()


def get_materials():
    try:
        result = supabase.table("materials").select("*").order("id", desc=True).execute()
        return result.data
    except Exception:
        return []


def save_submission(material_id, student_name, uploaded_file, file_path):
    safe_file = re.sub(r"[^A-Za-z0-9._-]+", "_", uploaded_file.name)
    existing = supabase.table("submissions").select("id").eq("material_id", material_id).eq("student_name", student_name).execute()
    payload = {
        "material_id": material_id,
        "student_name": student_name,
        "file_name": safe_file,
        "file_path": file_path,
        "submitted_at": datetime.now().isoformat(),
        "status": "Submitted"
    }
    if existing.data:
        supabase.table("submissions").update({
            "file_name": safe_file,
            "file_path": file_path,
            "submitted_at": datetime.now().isoformat(),
            "status": "Resubmitted"
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase.table("submissions").insert(payload).execute()


def get_submissions(material_id=None, student_name=None):
    try:
        query = supabase.table("submissions").select("*")
        if material_id is not None:
            query = query.eq("material_id", material_id)
        if student_name:
            query = query.eq("student_name", student_name)
        result = query.order("id", desc=True).execute()
        rows = result.data or []
        for r in rows:
            mat = supabase.table("materials").select("title,subject").eq("id", r["material_id"]).execute()
            if mat.data:
                r["title"] = mat.data[0]["title"]
                r["subject"] = mat.data[0].get("subject", "")
        return rows
    except Exception:
        return []


def delete_material(material_id):
    try:
        supabase.table("submissions").delete().eq("material_id", material_id).execute()
        supabase.table("materials").delete().eq("id", material_id).execute()
    except Exception:
        pass


# ============================================================
# QUIZZES
# ============================================================

def add_quiz(title, subject, target_stream, description, deadline,
             duration_minutes, created_by, questions):
    result = supabase.table("quizzes").insert({
        "title": title,
        "subject": subject,
        "target_stream": target_stream,
        "description": description,
        "deadline": deadline,
        "duration_minutes": int(duration_minutes),
        "created_by": created_by,
        "created_at": datetime.now().isoformat(),
        "status": "Published"
    }).execute()
    quiz_id = result.data[0]["id"]
    for i, q in enumerate(questions, 1):
        supabase.table("quiz_questions").insert({
            "quiz_id": quiz_id,
            "question_no": i,
            "question_text": q["text"],
            "question_type": q["type"],
            "option_a": q.get("a", ""),
            "option_b": q.get("b", ""),
            "option_c": q.get("c", ""),
            "option_d": q.get("d", ""),
            "correct_answer": q.get("correct", ""),
            "points": float(q.get("points", 1))
        }).execute()
    return quiz_id


def get_quizzes():
    try:
        result = supabase.table("quizzes").select("*").order("id", desc=True).execute()
        return result.data
    except Exception:
        return []


def get_quiz_questions(quiz_id):
    try:
        result = supabase.table("quiz_questions").select("*").eq("quiz_id", quiz_id).order("question_no").execute()
        return result.data
    except Exception:
        return []


def get_attempts(quiz_id=None, student_name=None):
    try:
        query = supabase.table("quiz_attempts").select("*")
        if quiz_id is not None:
            query = query.eq("quiz_id", quiz_id)
        if student_name:
            query = query.eq("student_name", student_name)
        result = query.order("id", desc=True).execute()
        rows = result.data or []
        for r in rows:
            qz = supabase.table("quizzes").select("title,subject").eq("id", r["quiz_id"]).execute()
            if qz.data:
                r["title"] = qz.data[0]["title"]
                r["subject"] = qz.data[0].get("subject", "")
        return rows
    except Exception:
        return []


def save_quiz_attempt(quiz_id, student_name, answers, score, total_points, status):
    existing = supabase.table("quiz_attempts").select("id").eq("quiz_id", quiz_id).eq("student_name", student_name).execute()
    now = datetime.now().isoformat()
    payload = {
        "quiz_id": quiz_id,
        "student_name": student_name,
        "started_at": now,
        "submitted_at": now,
        "answers_json": json.dumps(answers),
        "score": float(score),
        "total_points": float(total_points),
        "status": status,
        "manual_marks_json": "{}"
    }
    if existing.data:
        supabase.table("quiz_attempts").update({
            "submitted_at": now,
            "answers_json": json.dumps(answers),
            "score": float(score),
            "total_points": float(total_points),
            "status": status,
            "manual_marks_json": "{}"
        }).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase.table("quiz_attempts").insert(payload).execute()


def update_quiz_feedback(attempt_id, feedback, status='Reviewed'):
    supabase.table("quiz_attempts").update({
        "teacher_feedback": feedback.strip(),
        "status": status
    }).eq("id", attempt_id).execute()


def save_manual_marks(attempt_id, manual_marks_dict):
    supabase.table("quiz_attempts").update({
        "manual_marks_json": json.dumps(manual_marks_dict)
    }).eq("id", attempt_id).execute()


def finalize_quiz_attempt(attempt_id, auto_score, manual_marks_dict, total_points):
    total_manual = sum(float(v) for v in manual_marks_dict.values())
    new_score = float(auto_score) + total_manual
    supabase.table("quiz_attempts").update({
        "score": new_score,
        "status": "Reviewed"
    }).eq("id", attempt_id).execute()
    return new_score


def delete_quiz(quiz_id):
    try:
        supabase.table("quiz_questions").delete().eq("quiz_id", quiz_id).execute()
        supabase.table("quiz_attempts").delete().eq("quiz_id", quiz_id).execute()
        supabase.table("quizzes").delete().eq("id", quiz_id).execute()
    except Exception:
        pass


def quiz_available_for_student(quiz, student_streams):
    if quiz.get("target_stream") == "All Streams" or not student_streams:
        return True
    return quiz.get("target_stream") in student_streams


def quiz_grade(score, total):
    pct = (score / total * 100) if total else 0
    return pct, grade(pct)


# ============================================================
# BACKUP
# ============================================================
def load_school_settings():
    """Load school branding/settings from Supabase and apply to session state."""
    try:
        result = supabase.table("school_settings").select("*").eq("id", 1).execute()
        if not result.data:
            return
        s = result.data[0]

        # Text fields — only apply if present (non-empty)
        if s.get("school_name"):
            st.session_state.school_name = s["school_name"]
        if s.get("school_address") is not None:
            st.session_state.school_address = s["school_address"] or ""
        if s.get("school_phone") is not None:
            st.session_state.school_phone = s["school_phone"] or ""
        if s.get("school_email") is not None:
            st.session_state.school_email = s["school_email"] or ""
        if s.get("academic_year"):
            st.session_state.academic_year = s["academic_year"]
        if s.get("current_term"):
            st.session_state.current_term = s["current_term"]
        if s.get("class_teacher_name"):
            st.session_state.class_teacher_name = s["class_teacher_name"]
        if s.get("principal_name"):
            st.session_state.principal_name = s["principal_name"]
        if s.get("principal_comment"):
            st.session_state.principal_comment = s["principal_comment"]

        # Images — base64 encoded
        if s.get("logo_base64"):
            try:
                st.session_state.school_logo = base64.b64decode(s["logo_base64"])
            except Exception:
                pass
        if s.get("teacher_signature_base64"):
            try:
                st.session_state.teacher_signature = base64.b64decode(s["teacher_signature_base64"])
            except Exception:
                pass
        if s.get("principal_signature_base64"):
            try:
                st.session_state.principal_signature = base64.b64decode(s["principal_signature_base64"])
            except Exception:
                pass
    except Exception:
        pass


def save_school_settings():
    """Write current session_state branding/settings into Supabase."""
    def _b64(data):
        if not data:
            return None
        try:
            return base64.b64encode(data).decode("utf-8")
        except Exception:
            return None

    payload = {
        "school_name": st.session_state.get("school_name", ""),
        "school_address": st.session_state.get("school_address", ""),
        "school_phone": st.session_state.get("school_phone", ""),
        "school_email": st.session_state.get("school_email", ""),
        "academic_year": st.session_state.get("academic_year", ""),
        "current_term": st.session_state.get("current_term", ""),
        "class_teacher_name": st.session_state.get("class_teacher_name", ""),
        "principal_name": st.session_state.get("principal_name", ""),
        "principal_comment": st.session_state.get("principal_comment", ""),
        "logo_base64": _b64(st.session_state.get("school_logo")),
        "teacher_signature_base64": _b64(st.session_state.get("teacher_signature")),
        "principal_signature_base64": _b64(st.session_state.get("principal_signature")),
        "updated_at": datetime.now().isoformat(),
    }
    try:
        supabase.table("school_settings").update(payload).eq("id", 1).execute()
    except Exception as e:
        st.warning(f"Could not save settings to cloud: {e}")
def get_fee_structure(stream=None, term=None):
    """Return fee structure rows, optionally filtered."""
    try:
        query = supabase.table("fee_structure").select("*")
        if stream:
            query = query.eq("stream", stream)
        if term:
            query = query.eq("term", term)
        result = query.order("stream").order("term").execute()
        return result.data or []
    except Exception:
        return []


def set_fee_structure(stream, term, amount, description, updated_by):
    """Create or update a fee structure entry."""
    existing = supabase.table("fee_structure").select("id").eq("stream", stream).eq("term", term).execute()
    payload = {
        "stream": stream,
        "term": term,
        "amount": float(amount),
        "description": description,
        "updated_by": updated_by,
        "updated_at": datetime.now().isoformat(),
    }
    if existing.data:
        supabase.table("fee_structure").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase.table("fee_structure").insert(payload).execute()
    log_fee_action(updated_by, "set_fee_structure", f"{stream} {term} = {amount}")


def delete_fee_structure(structure_id, username):
    """Remove a fee structure entry."""
    supabase.table("fee_structure").delete().eq("id", structure_id).execute()
    log_fee_action(username, "delete_fee_structure", f"id={structure_id}")


def record_fee_payment(student_name, stream, term, amount, payment_date,
                       payment_method, reference, recorded_by, notes=""):
    """Insert a new fee payment."""
    payload = {
        "student_name": student_name,
        "stream": stream,
        "term": term,
        "amount": float(amount),
        "payment_date": str(payment_date),
        "payment_method": payment_method,
        "reference": reference,
        "recorded_by": recorded_by,
        "notes": notes,
    }
    result = supabase.table("fee_payments").insert(payload).execute()
    log_fee_action(recorded_by, "record_payment",
                   f"{student_name} {term} = {amount} ({payment_method})")
    return result.data[0]["id"] if result.data else None


def get_fee_payments(student_name=None, term=None, include_voided=False):
    """Return fee payments, optionally filtered."""
    try:
        query = supabase.table("fee_payments").select("*")
        if student_name:
            query = query.eq("student_name", student_name)
        if term:
            query = query.eq("term", term)
        if not include_voided:
            query = query.eq("voided", False)
        result = query.order("payment_date", desc=True).order("id", desc=True).execute()
        return result.data or []
    except Exception:
        return []


def void_fee_payment(payment_id, username, reason):
    """Mark a payment as void (do not delete)."""
    supabase.table("fee_payments").update({
        "voided": True,
        "voided_by": username,
        "voided_reason": reason,
        "voided_at": datetime.now().isoformat(),
    }).eq("id", payment_id).execute()
    log_fee_action(username, "void_payment", f"id={payment_id} reason={reason}")


def get_current_term():
    """Return the current academic term (like 'y3t1')."""
    # Try to detect from the academic year + current_term setting
    year_str = str(st.session_state.get("academic_year", "2026"))
    term_setting = st.session_state.get("current_term", "Term 3")

    # Extract year number from academic_year: "2026" → 1, "2027" → 2, etc.
    # Default to year 1
    try:
        # Look at the Excel data terms — pick the latest one
        if st.session_state.get("data") is not None:
            terms = st.session_state.data["target_terms"]
            if terms:
                return terms[-1]  # latest term in the data
    except Exception:
        pass

    # Fallback: extract from current_term setting
    term_num = 1
    if "Term 2" in term_setting:
        term_num = 2
    elif "Term 3" in term_setting:
        term_num = 3

    # Assume year 1 by default (most common for first-time use)
    return f"y1t{term_num}"
def get_allocated_ledger(student_name, stream):
    """
    Return term-by-term breakdown with payments allocated to earliest unpaid terms.
    This is a DISPLAY-ONLY function — it doesn't modify any data.
    
    Example:
    - Expected: Y1T1=50k, Y1T2=50k, Y1T3=50k
    - Paid: 80k (recorded under any term)
    - Allocated: Y1T1=50k, Y1T2=30k, Y1T3=0
    - Balance: Y1T1=0, Y1T2=20k, Y1T3=50k
    """
    

    # Get all terms with expected amounts
    all_structure = get_fee_structure(stream=stream)
    expected_by_term = {}
    for s in all_structure:
        t = (s.get("term") or "").lower()
        expected_by_term[t] = expected_by_term.get(t, 0) + float(s["amount"])

    # Get all payments (all terms combined)
    all_payments = get_fee_payments(student_name=student_name, include_voided=False)
    total_paid = sum(float(p["amount"]) for p in all_payments)

    # Sort terms chronologically (y1t1 < y1t2 < y1t3 < y2t1 < ...)
    def term_sort_key(t):
        m = re.match(r"y(\d+)t(\d+)", t)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        return (99, 99)

    sorted_terms = sorted(expected_by_term.keys(), key=term_sort_key)

    # Allocate payments to earliest unpaid terms
    remaining = total_paid
    allocated_by_term = {}
    for term in sorted_terms:
        expected = expected_by_term[term]
        if remaining <= 0:
            allocated_by_term[term] = 0.0
        elif remaining >= expected:
            allocated_by_term[term] = expected
            remaining -= expected
        else:
            allocated_by_term[term] = remaining
            remaining = 0

    # Any remaining is a credit (over-payment beyond all terms)
    credit = remaining

    # Build result rows
    rows = []
    total_expected = 0
    total_allocated = 0
    for term in sorted_terms:
        expected = expected_by_term[term]
        allocated = allocated_by_term[term]
        balance = expected - allocated
        total_expected += expected
        total_allocated += allocated

        if expected == 0:
            status = "—"
        elif balance <= 0:
            status = "✅ Settled"
        elif allocated > 0:
            status = "⚠️ Partial"
        else:
            status = "❌ Not paid"

        rows.append({
            "term": term,
            "expected": expected,
            "allocated": allocated,
            "balance": balance,
            "status": status,
        })

    return {
        "rows": rows,
        "total_expected": total_expected,
        "total_paid": total_paid,
        "total_allocated": total_allocated,
        "total_balance": total_expected - total_paid,
        "credit": credit,
    }
def get_student_fee_ledger(student_name, stream, term=None):
    """Return expected fees, paid fees, and balance for a student."""
    # Expected: fee structure for their stream
    if term:
        structure = get_fee_structure(stream=stream, term=term)
    else:
        structure = get_fee_structure(stream=stream)

    total_expected = sum(float(s["amount"]) for s in structure)

    # Paid: all non-voided payments by this student (optionally for the term)
    payments = get_fee_payments(student_name=student_name, term=term)
    total_paid = sum(float(p["amount"]) for p in payments)

    balance = total_expected - total_paid

    return {
        "expected": total_expected,
        "paid": total_paid,
        "balance": balance,
        "payments": payments,
        "structure": structure,
    }


def get_fee_collection_summary(term=None):
    """Return collection stats for a term (or all terms if None)."""
    try:
        if term:
            payments = supabase.table("fee_payments").select("*").eq("term", term).eq("voided", False).execute().data or []
        else:
            payments = supabase.table("fee_payments").select("*").eq("voided", False).execute().data or []

        total_collected = sum(float(p["amount"]) for p in payments)
        payment_count = len(payments)

        # By method
        by_method = {}
        for p in payments:
            m = p.get("payment_method", "unknown")
            by_method[m] = by_method.get(m, 0) + float(p["amount"])

        return {
            "total_collected": total_collected,
            "payment_count": payment_count,
            "by_method": by_method,
            "payments": payments,
        }
    except Exception:
        return {"total_collected": 0, "payment_count": 0, "by_method": {}, "payments": []}


def log_fee_action(username, action, details=""):
    """Write to the fee audit log."""
    try:
        supabase.table("fee_audit_log").insert({
            "username": username,
            "action": action,
            "details": details,
        }).execute()
    except Exception:
        pass


def get_fee_audit_log(limit=100):
    """Return recent audit log entries."""
    try:
        result = supabase.table("fee_audit_log").select("*").order("id", desc=True).limit(limit).execute()
        return result.data or []
    except Exception:
        return []


def generate_defaulters_pdf(rows, threshold, term_label, school_name):
    """Generate a PDF listing students below a fee threshold."""
    buf = io.BytesIO()
    from reportlab.lib.pagesizes import A4
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30
    )
    styles = pdf_styles()

    info_style = ParagraphStyle("Info", parent=styles["cell"], fontSize=9, leading=11)
    header_cell = ParagraphStyle("HeaderCell", parent=styles["cell"],
                                 fontName="Helvetica-Bold", fontSize=9, leading=11,
                                 textColor=colors.white, alignment=1)
    cell_center = ParagraphStyle("CellCenter", parent=styles["cell"],
                                 fontSize=9, leading=11, alignment=1)

    story = []
    pdf_school_header(
        story, school_name, styles,
        f"FEE DEFAULT REPORT | Threshold: KSh {threshold:,.0f}"
    )
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#263238")))
    story.append(Spacer(1, 8))

    meta = Table([
        [Paragraph("Report Term:", info_style), Paragraph(term_label, info_style)],
        [Paragraph("Threshold:", info_style), Paragraph(f"KSh {threshold:,.0f} (students below are listed)", info_style)],
        [Paragraph("Total Students:", info_style), Paragraph(str(len(rows)), info_style)],
        [Paragraph("Generated:", info_style), Paragraph(datetime.now().strftime("%d %B %Y %H:%M"), info_style)],
        [Paragraph("Prepared by:", info_style), Paragraph(st.session_state.get("username", ""), info_style)],
    ], colWidths=[110, 380])
    meta.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d0d6")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf1f3")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta)
    story.append(Spacer(1, 12))

    # Table header
    headers = ["#", "Student", "Stream", "Expected (KSh)", "Paid (KSh)", "Balance (KSh)"]
    table_rows = [[Paragraph(h, header_cell) for h in headers]]

    for i, r in enumerate(rows, 1):
        table_rows.append([
            Paragraph(str(i), cell_center),
            Paragraph(str(r["student"]), info_style),
            Paragraph(str(r["stream"]), cell_center),
            Paragraph(f"{r['expected']:,.0f}", cell_center),
            Paragraph(f"{r['paid']:,.0f}", cell_center),
            Paragraph(f"{r['balance']:,.0f}", cell_center),
        ])

    t = Table(table_rows, colWidths=[30, 170, 60, 90, 80, 90], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#c0392b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d7dce0")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fdf2f2")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "This list shows students who have paid LESS than the threshold. "
        "Students who have paid the threshold or more are NOT included.",
        styles["meta"]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph("_____________________________", info_style))
    story.append(Paragraph("Principal / Deputy Signature & Date", styles["meta"]))

    doc.build(story)
    buf.seek(0)
    return buf
# ============================================================
# TIMETABLE HELPERS
# ============================================================

def tt_get_periods():
    """Return all periods sorted by period_no (breaks are negative)."""
    try:
        result = supabase.table("tt_periods").select("*").execute()
        rows = result.data or []
        teaching = [r for r in rows if not r.get("is_break")]
        breaks = [r for r in rows if r.get("is_break")]
        return sorted(teaching, key=lambda x: x["period_no"]), breaks
    except Exception:
        return [], []

def tt_create_period(period_no, start_time, end_time):
    """Insert a new period (teaching or break)."""
    existing = supabase.table("tt_periods").select("id").eq("period_no", period_no).execute()
    payload = {
        "period_no": int(period_no),
        "start_time": start_time.strip(),
        "end_time": end_time.strip(),
        "is_break": False,
        "break_label": None,
    }
    if existing.data:
        supabase.table("tt_periods").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase.table("tt_periods").insert(payload).execute()


def tt_create_break(break_label, start_time, end_time):
    """Insert a new break."""
    existing = supabase.table("tt_periods").select("period_no").lt("period_no", 0).execute()
    used = [p["period_no"] for p in (existing.data or [])]
    next_id = min(used + [0]) - 1 if used else -1
    supabase.table("tt_periods").insert({
        "period_no": next_id,
        "start_time": start_time.strip(),
        "end_time": end_time.strip(),
        "is_break": True,
        "break_label": break_label.strip(),
    }).execute()


def tt_update_period(period_id, start_time, end_time, break_label=None):
    """Update time on an existing period or break."""
    payload = {"start_time": start_time.strip(), "end_time": end_time.strip()}
    if break_label is not None:
        payload["break_label"] = break_label.strip()
    supabase.table("tt_periods").update(payload).eq("id", period_id).execute()


def tt_delete_period(period_id):
    """Delete a period or break."""
    supabase.table("tt_periods").delete().eq("id", period_id).execute()


def tt_get_all_periods():
    """Return ALL periods AND breaks, sorted for display."""
    try:
        result = supabase.table("tt_periods").select("*").execute()
        rows = result.data or []
        return rows
    except Exception:
        return []

def tt_create_or_update_subject(subject_name, periods_per_week, has_double, double_count, requires_lab, lab_type):
    """Insert or update a subject. Also auto-assigns (unassigned) rows for all classes."""
    existing = supabase.table("tt_subjects").select("id").eq("subject_name", subject_name.strip()).execute()
    payload = {
        "subject_name": subject_name.strip(),
        "periods_per_week": int(periods_per_week),
        "has_double": bool(has_double),
        "double_count": int(double_count) if has_double else 0,
        "requires_lab": bool(requires_lab),
        "lab_type": (lab_type or "").strip() if requires_lab else None,
    }
    is_new = not existing.data
    if existing.data:
        supabase.table("tt_subjects").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase.table("tt_subjects").insert(payload).execute()

    # Auto-create assignment rows for all existing classes
    all_classes = set()
    try:
        rows = supabase.table("tt_class_teacher").select("class_name").execute().data or []
        all_classes = set(r["class_name"] for r in rows)
    except Exception:
        all_classes = set()

    for cls in sorted(all_classes):
        try:
            existing_a = supabase.table("tt_class_teacher").select("id").eq("class_name", cls).eq("subject_name", subject_name.strip()).execute()
            if not existing_a.data:
                supabase.table("tt_class_teacher").insert({
                    "class_name": cls,
                    "subject_name": subject_name.strip(),
                    "teacher_id": None,
                    "periods_per_week": int(periods_per_week),
                }).execute()
            else:
                # Update periods_per_week to keep in sync
                supabase.table("tt_class_teacher").update({
                    "periods_per_week": int(periods_per_week),
                }).eq("id", existing_a.data[0]["id"]).execute()
        except Exception:
            pass

    return True



def tt_delete_subject(subject_id):
    """Delete a subject."""
    supabase.table("tt_subjects").delete().eq("id", subject_id).execute()


def tt_get_all_subjects():
    """Return all subjects sorted by name."""
    try:
        result = supabase.table("tt_subjects").select("*").order("subject_name").execute()
        return result.data or []
    except Exception:
        return []

def tt_create_class(class_name):
    """Create a new class and auto-add rows for every existing subject."""
    class_name = class_name.strip().upper()
    if not class_name:
        return False

    # Add assignment rows for every existing subject
    try:
        subjects = supabase.table("tt_subjects").select("subject_name,periods_per_week").execute().data or []
        for s in subjects:
            existing = supabase.table("tt_class_teacher").select("id").eq("class_name", class_name).eq("subject_name", s["subject_name"]).execute()
            if not existing.data:
                supabase.table("tt_class_teacher").insert({
                    "class_name": class_name,
                    "subject_name": s["subject_name"],
                    "teacher_id": None,
                    "periods_per_week": int(s["periods_per_week"] or 0),
                }).execute()
    except Exception:
        pass
    return True


def tt_delete_class(class_name):
    """Delete a class and all its assignment rows."""
    supabase.table("tt_class_teacher").delete().eq("class_name", class_name).execute()
    # Also delete any generated timetable slots for that class
    try:
        supabase.table("tt_generated").delete().eq("class_name", class_name).execute()
    except Exception:
        pass








def tt_get_subjects():
    """Return all subjects with their period rules."""
    try:
        result = supabase.table("tt_subjects").select("*").order("subject_name").execute()
        return result.data or []
    except Exception:
        return []


def tt_get_teachers():
    """Return all teachers."""
    try:
        result = supabase.table("tt_teachers").select("*").order("full_name").execute()
        return result.data or []
    except Exception:
        return []


def tt_create_or_update_teacher(full_name, subjects_taught, max_periods_per_day=6):
    """Create a teacher, or update if the name already exists."""
    existing = supabase.table("tt_teachers").select("id").eq("full_name", full_name.strip()).execute()
    payload = {
        "full_name": full_name.strip(),
        "subjects_taught": subjects_taught.strip(),
        "max_periods_per_day": int(max_periods_per_day),
    }
    if existing.data:
        supabase.table("tt_teachers").update(payload).eq("id", existing.data[0]["id"]).execute()
        return existing.data[0]["id"]
    else:
        result = supabase.table("tt_teachers").insert(payload).execute()
        return result.data[0]["id"] if result.data else None


def tt_delete_teacher(teacher_id):
    """Delete a teacher. Their class assignments revert to NULL."""
    try:
        supabase.table("tt_teachers").delete().eq("id", teacher_id).execute()
    except Exception:
        pass


def tt_get_class_teacher_assignments(class_name=None):
    """Return assignments. If class_name given, filter to that class."""
    try:
        query = supabase.table("tt_class_teacher").select("*")
        if class_name:
            query = query.eq("class_name", class_name)
        result = query.order("class_name").order("subject_name").execute()
        return result.data or []
    except Exception:
        return []


def tt_assign_teacher(class_name, subject_name, teacher_id, periods_per_week):
    """Set the teacher for a class+subject combination."""
    existing = supabase.table("tt_class_teacher").select("id").eq("class_name", class_name).eq("subject_name", subject_name).execute()
    payload = {
        "class_name": class_name,
        "subject_name": subject_name,
        "teacher_id": teacher_id,
        "periods_per_week": int(periods_per_week),
    }
    if existing.data:
        supabase.table("tt_class_teacher").update(payload).eq("id", existing.data[0]["id"]).execute()
    else:
        supabase.table("tt_class_teacher").insert(payload).execute()


def tt_get_all_classes():
    """Return sorted list of all class names."""
    try:
        result = supabase.table("tt_class_teacher").select("class_name").execute()
        rows = result.data or []
        return sorted(set(r["class_name"] for r in rows))
    except Exception:
        return []


def tt_count_generated():
    """How many rows exist in the generated timetable."""
    try:
        result = supabase.table("tt_generated").select("id").execute()
        return len(result.data or [])
    except Exception:
        return 0

def tt_generate_timetable(max_seconds=300):
    """
    Generate a complete timetable using Google OR-Tools.
    Writes results to the tt_generated table.
    Returns a dict with 'success', 'message', 'stats'.
    """
    from ortools.sat.python import cp_model

    # ---- Read inputs ----
    teachers = supabase.table("tt_teachers").select("*").execute().data or []
    subjects = supabase.table("tt_subjects").select("*").execute().data or []
    assignments = supabase.table("tt_class_teacher").select("*").execute().data or []
    periods, breaks = tt_get_periods()

    if not teachers or not subjects or not assignments:
        return {"success": False, "message": "Missing setup data — add teachers/subjects/assignments first."}

    days = st.session_state.get("teaching_days") or ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    period_nos = sorted([p["period_no"] for p in periods])
    all_classes = sorted(set(a["class_name"] for a in assignments))

    teacher_by_id = {t["id"]: t for t in teachers}
    subject_by_name = {s["subject_name"]: s for s in subjects}

    # Build a demand list: (class, subject, teacher_id, periods_per_week)
    demand = []
    for a in assignments:
        demand.append({
            "class": a["class_name"],
            "subject": a["subject_name"],
            "teacher_id": a["teacher_id"],
            "ppw": int(a["periods_per_week"] or 0),
        })

    # ---- Model ----
    model = cp_model.CpModel()
    x = {}  # x[class][subject][day_idx][period_idx] = BoolVar

    # One decision variable per (class, subject, day, period)
    for d in demand:
        c = d["class"]
        s = d["subject"]
        for di in range(len(days)):
            for pi in range(len(period_nos)):
                x[(c, s, di, pi)] = model.NewBoolVar(f"x_{c}_{s}_{di}_{pi}")

    # Constraint 1: each class has exactly one subject per (day, period)
    for c in all_classes:
        for di in range(len(days)):
            for pi in range(len(period_nos)):
                                model.Add(sum(x[(c, s, di, pi)] for s in subject_by_name.keys() if (c, s, di, pi) in x) <= 1)
    # Constraint 1b: each class's subjects must total its own weekly target
    # (the sum of its own subjects' periods_per_week)
    class_target = {}
    for d in demand:
        c = d["class"]
        class_target[c] = class_target.get(c, 0) + int(d["ppw"])

    max_slots = len(days) * len(period_nos)
    for c in all_classes:
        if class_target.get(c, 0) > max_slots:
            return {
                "success": False,
                "message": (
                    f"Class **{c}** needs {class_target[c]} periods/week but only "
                    f"{max_slots} slots are available "
                    f"({len(days)} days × {len(period_nos)} periods/day). "
                    f"Reduce its subjects or add more periods to the day."
                ),
                "stats": {},
            }
        class_vars = [x[(c, s, di, pi)]
                      for s in subject_by_name.keys()
                      for di in range(len(days))
                      for pi in range(len(period_nos))
                      if (c, s, di, pi) in x]
        model.Add(sum(class_vars) == class_target.get(c, 0))
    # Constraint 2: subject meets its weekly period count per class
    for d in demand:
        c = d["class"]
        s = d["subject"]
        ppw = d["ppw"]
        vars_for_subject = [x[(c, s, di, pi)] for di in range(len(days)) for pi in range(len(period_nos))]
        model.Add(sum(vars_for_subject) == ppw)

    # Constraint 3: no teacher in two places at the same (day, period)
    teacher_usage = {}  # (teacher_id, day, period) -> list of vars
    for d in demand:
        if d["teacher_id"] is None:
            continue
        c, s, tid = d["class"], d["subject"], d["teacher_id"]
        for di in range(len(days)):
            for pi in range(len(period_nos)):
                key = (tid, di, pi)
                teacher_usage.setdefault(key, []).append(x[(c, s, di, pi)])
    for key, vars_list in teacher_usage.items():
        if len(vars_list) > 1:
            model.Add(sum(vars_list) <= 1)

        # Constraint 4: Assembly — Mon P1 AND Fri P1 for all classes
    mon_idx = 0
    fri_idx = 4
    p1_idx = period_nos.index(min(period_nos))
    for d in demand:
        if d["subject"] == "Assembly":
            c = d["class"]
            model.Add(x[(c, "Assembly", mon_idx, p1_idx)] == 1)
            model.Add(x[(c, "Assembly", fri_idx, p1_idx)] == 1)
            # Assembly cannot be anywhere else
            for di in range(len(days)):
                for pi in range(len(period_nos)):
                    if not ((di == mon_idx and pi == p1_idx) or (di == fri_idx and pi == p1_idx)):
                        model.Add(x[(c, "Assembly", di, pi)] == 0)

    # Constraint 5: Doubles for Chemistry and Biology (2 consecutive periods)
    for d in demand:
        if d["subject"] in ["Chemistry", "Biology"] and subject_by_name.get(d["subject"], {}).get("has_double"):
            c, s = d["class"], d["subject"]
            # At least one consecutive pair must be on the same day
            double_options = []
            for di in range(len(days)):
                for pi in range(len(period_nos) - 1):
                    pair_var = model.NewBoolVar(f"pair_{c}_{s}_{di}_{pi}")
                    model.Add(pair_var <= x[(c, s, di, pi)])
                    model.Add(pair_var <= x[(c, s, di, pi + 1)])
                    double_options.append(pair_var)
            model.Add(sum(double_options) >= 1)

            # Constraint 6: No Free Study on Mon P1 or Fri P1 (only if Free Study exists)
    for c in all_classes:
        if (c, "Free Study", mon_idx, p1_idx) in x:
            model.Add(x[(c, "Free Study", mon_idx, p1_idx)] == 0)
        if (c, "Free Study", fri_idx, p1_idx) in x:
            model.Add(x[(c, "Free Study", fri_idx, p1_idx)] == 0)

    # ---- Solve ----
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds
    solver.parameters.num_search_workers = 4

    status = solver.Solve(model)
    status_name = solver.StatusName(status)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "success": False,
            "message": f"Solver could not find a solution (status: {status_name}). Try increasing max_seconds or relaxing constraints.",
            "stats": {"status": status_name},
        }

    # ---- Save result ----
    supabase.table("tt_generated").delete().neq("id", 0).execute()

    rows_to_insert = []
    for d in demand:
        c, s, tid = d["class"], d["subject"], d["teacher_id"]
        for di in range(len(days)):
            for pi in range(len(period_nos)):
                if solver.Value(x[(c, s, di, pi)]) == 1:
                    room = None
                    if s == "Chemistry":
                        room = "Chemistry Lab"
                    elif s == "Biology":
                        room = "Biology Lab"
                    elif s == "Computer":
                        room = "Computer Lab"
                    rows_to_insert.append({
                        "class_name": c,
                        "day_of_week": days[di],
                        "period_no": period_nos[pi],
                        "subject_name": s,
                        "teacher_id": tid,
                        "room": room,
                    })

    # Insert in chunks to avoid big requests
    chunk_size = 500
    for i in range(0, len(rows_to_insert), chunk_size):
        supabase.table("tt_generated").insert(rows_to_insert[i:i + chunk_size]).execute()

    return {
        "success": True,
        "message": f"Timetable generated — {len(rows_to_insert)} slots placed.",
        "stats": {
            "status": status_name,
            "slots": len(rows_to_insert),
            "wall_time": round(solver.WallTime(), 2),
        },
    }

def tt_get_generated(class_name=None, teacher_id=None, room=None):
    """Read the generated timetable with optional filters."""
    try:
        query = supabase.table("tt_generated").select("*")
        if class_name:
            query = query.eq("class_name", class_name)
        if teacher_id is not None:
            query = query.eq("teacher_id", teacher_id)
        if room:
            query = query.eq("room", room)
        result = query.execute()
        return result.data or []
    except Exception:
        return []


def tt_build_grid(rows, teacher_map):
    """Turn a list of timetable rows into a week grid DataFrame with break rows."""
    days = st.session_state.get("teaching_days") or ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    # Get periods + breaks with times
    periods, breaks = tt_get_periods()
    period_nos = sorted([p["period_no"] for p in periods])
    period_time = {p["period_no"]: f"{p.get('start_time','')} – {p.get('end_time','')}".strip(" –") for p in periods}
    break_list = sorted(breaks, key=lambda b: b.get("start_time") or "")

    # Build matrix
    matrix = {p: {d: "" for d in days} for p in period_nos}
    for r in rows:
        p = r.get("period_no")
        d = r.get("day_of_week")
        if p not in matrix or d not in matrix[p]:
            continue
        subj = r.get("subject_name") or ""
        tid = r.get("teacher_id")
        teacher_name = teacher_map.get(tid, "") if tid else ""
        room = r.get("room") or ""

        parts = [subj]
        if teacher_name:
            parts.append(teacher_name)
        if room:
            parts.append(f"[{room}]")
        matrix[p][d] = " · ".join(parts)

    # Build output rows: insert break rows
    out_rows = []
    break_by_after_period = {}
    for b in break_list:
        # Use label like "Morning Break" and start/end time
        label = b.get("break_label") or "Break"
        t = f"{b.get('start_time','')} – {b.get('end_time','')}".strip(" –")
        # Determine which period comes BEFORE this break
        # We figure this out by comparing times
        prev_period = None
        for p in periods:
            if p.get("end_time") == b.get("start_time"):
                prev_period = p["period_no"]
                break
        if prev_period is not None:
            break_by_after_period.setdefault(prev_period, []).append(f"{label}  ({t})")

    for p in period_nos:
        time_label = period_time[p] if period_time[p] else f"Period {p}"
        out_rows.append({
            "Time": time_label,
            **{d: matrix[p][d] for d in days},
            "_is_break": False,
        })
        # Insert any breaks that follow this period
        if p in break_by_after_period:
            for brk in break_by_after_period[p]:
                out_rows.append({
                    "Time": brk,
                    **{d: "" for d in days},
                    "_is_break": True,
                })

    df = pd.DataFrame(out_rows)
    return df


def tt_generate_pdf(rows, title, school_name, teacher_map):
    """Generate a PDF timetable with real times and break rows. Fits one page."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.platypus import Image as RLImage

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=8*mm,
        rightMargin=8*mm,
        topMargin=8*mm,
        bottomMargin=8*mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TTTitle", parent=styles["Title"],
                                 fontName="Helvetica-Bold", fontSize=14, leading=16, alignment=1)
    subtitle_style = ParagraphStyle("TTSubtitle", parent=styles["Normal"],
                                    fontSize=10, leading=12, alignment=1,
                                    textColor=colors.HexColor("#555555"))
    meta_style = ParagraphStyle("TTMeta", parent=styles["Normal"],
                                fontSize=7, leading=9, alignment=1,
                                textColor=colors.HexColor("#777777"))
    time_style = ParagraphStyle("TTTime", parent=styles["Normal"],
                                fontName="Helvetica-Bold", fontSize=8, leading=10,
                                alignment=1, textColor=colors.HexColor("#222222"))
    cell_subject = ParagraphStyle("CellSubject", parent=styles["Normal"],
                                  fontName="Helvetica-Bold", fontSize=7.5, leading=9, alignment=1)
    cell_teacher = ParagraphStyle("CellTeacher", parent=styles["Normal"],
                                  fontSize=6.5, leading=8, alignment=1,
                                  textColor=colors.HexColor("#333333"))
    cell_room = ParagraphStyle("CellRoom", parent=styles["Normal"],
                               fontSize=5.5, leading=7, alignment=1,
                               textColor=colors.HexColor("#006600"),
                               fontName="Helvetica-Oblique")
    cell_empty = ParagraphStyle("CellEmpty", parent=styles["Normal"],
                                fontSize=6.5, leading=8, alignment=1,
                                textColor=colors.HexColor("#999999"))
    break_style = ParagraphStyle("TTBreak", parent=styles["Normal"],
                                 fontName="Helvetica-Oblique", fontSize=7.5, leading=9,
                                 alignment=1, textColor=colors.HexColor("#444444"))

    story = []

    # Header with logo
    logo = st.session_state.get("school_logo")
    if logo:
        try:
            logo_img = RLImage(io.BytesIO(logo), width=14*mm, height=14*mm)
            header_table = Table([[logo_img, Paragraph(f"<b>{school_name}</b><br/>{title}", subtitle_style)]],
                                 colWidths=[18*mm, None])
            header_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "LEFT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(header_table)
        except Exception:
            story.append(Paragraph(f"<b>{school_name}</b>", title_style))
            story.append(Paragraph(title, subtitle_style))
    else:
        story.append(Paragraph(f"<b>{school_name}</b>", title_style))
        story.append(Paragraph(title, subtitle_style))

    story.append(Paragraph(
        f"Academic Year {st.session_state.get('academic_year', '')} · {st.session_state.get('current_term', '')}",
        meta_style
    ))
    story.append(Spacer(1, 3))

    # Get periods + breaks
    periods, breaks = tt_get_periods()
    period_nos = sorted([p["period_no"] for p in periods])
    period_time = {p["period_no"]: f"{p.get('start_time','')} – {p.get('end_time','')}".strip(" –") for p in periods}
    break_list = sorted(breaks, key=lambda b: b.get("start_time") or "")

    days = st.session_state.get("teaching_days") or ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    matrix = {p: {d: None for d in days} for p in period_nos}
    for r in rows:
        p = r.get("period_no")
        d = r.get("day_of_week")
        if p not in matrix or d not in matrix[p]:
            continue
        matrix[p][d] = r

    # Build break labels per preceding period
    break_by_after_period = {}
    for b in break_list:
        label = b.get("break_label") or "Break"
        t = f"{b.get('start_time','')} – {b.get('end_time','')}".strip(" –")
        prev_period = None
        for p in periods:
            if p.get("end_time") == b.get("start_time"):
                prev_period = p["period_no"]
                break
        if prev_period is not None:
            break_by_after_period.setdefault(prev_period, []).append(f"☕ {label} · {t}")

    # Header row
    header = [Paragraph("<b>Time</b>", cell_subject)]
    for d in days:
        header.append(Paragraph(f"<b>{d}</b>", cell_subject))
    table_data = [header]
    row_heights = [8*mm]
    style_rules = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#333333")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263238")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#f0f0f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
        ("RIGHTPADDING", (0, 0), (-1, -1), 1),
    ]

    for p in period_nos:
        time_label = period_time[p] if period_time[p] else f"P{p}"
        row = [Paragraph(time_label, time_style)]
        for d in days:
            r = matrix[p][d]
            if r is None:
                row.append(Paragraph("—", cell_empty))
                continue
            subj = r.get("subject_name") or ""
            cls = r.get("class_name") or ""
            tid = r.get("teacher_id")
            teacher_name = teacher_map.get(tid, "") if tid else ""
            room = r.get("room") or ""

            # Show class name only on TEACHER PDFs, not on CLASS PDFs
            is_class_pdf = "CLASS TIMETABLE" in title

            cell_parts = [Paragraph(subj, cell_subject)]
            if not is_class_pdf and cls:
                cell_parts.append(Paragraph(cls, cell_teacher))
            if teacher_name:
                cell_parts.append(Paragraph(teacher_name, cell_teacher))
            if room:
                cell_parts.append(Paragraph(f"[{room}]", cell_room))
            row.append(cell_parts)
        table_data.append(row)
        row_heights.append(14*mm)

        # Add break row if any
        if p in break_by_after_period:
            for brk in break_by_after_period[p]:
                break_row = [Paragraph(brk, break_style)]
                for _ in days:
                    break_row.append("")
                table_data.append(break_row)
                row_heights.append(6*mm)
                # Style break row (grey background)
                break_row_index = len(table_data) - 1
                style_rules.append(
                    ("BACKGROUND", (0, break_row_index), (-1, break_row_index), colors.HexColor("#eaeaea"))
                )
                style_rules.append(
                    ("SPAN", (0, break_row_index), (-1, break_row_index))
                )

    col_widths = [22*mm] + [(doc.width - 22*mm) / 5] * 5
    table = Table(table_data, colWidths=col_widths, rowHeights=row_heights)
    table.setStyle(TableStyle(style_rules))

    story.append(table)
    story.append(Spacer(1, 3))
    story.append(Paragraph(
        f"Generated on {datetime.now().strftime('%d %B %Y at %H:%M')} · Official Timetable · {school_name}",
        meta_style
    ))
    story.append(Paragraph(
        "<b>Generated by SAM System</b>",
        meta_style
    ))

    doc.build(story)
    buf.seek(0)
    return buf







  

def tt_teacher_load_report():
    """Calculate each teacher's weekly load from assignments."""
    try:
        teachers = supabase.table("tt_teachers").select("*").execute().data or []
        assignments = supabase.table("tt_class_teacher").select("*").execute().data or []

        teacher_by_id = {t["id"]: t for t in teachers}
        loads = {}

        for a in assignments:
            if a.get("teacher_id") is None:
                continue
            tid = a["teacher_id"]
            if tid not in loads:
                loads[tid] = {"subjects": {}, "total": 0, "classes": 0}
            subj = a["subject_name"]
            ppw = int(a["periods_per_week"] or 0)
            loads[tid]["subjects"][subj] = loads[tid]["subjects"].get(subj, 0) + ppw
            loads[tid]["total"] += ppw
            loads[tid]["classes"] += 1

        rows = []
        for tid, load in loads.items():
            t = teacher_by_id.get(tid, {})
            subject_summary = ", ".join(f"{s}({p})" for s, p in load["subjects"].items())
            max_pw = (t.get("max_periods_per_day") or 6) * 5
            status = "✅ OK" if load["total"] <= max_pw else "❌ OVERLOADED"
            rows.append({
                "Teacher": t.get("full_name", "?"),
                "Subjects Taught": t.get("subjects_taught", ""),
                "Classes": load["classes"],
                "Periods/Week": load["total"],
                "Max": max_pw,
                "Status": status,
                "Breakdown": subject_summary,
            })
        rows.sort(key=lambda r: -r["Periods/Week"])

        assigned_ids = set(loads.keys())
        for t in teachers:
            if t["id"] not in assigned_ids:
                rows.append({
                    "Teacher": t.get("full_name", "?"),
                    "Subjects Taught": t.get("subjects_taught", ""),
                    "Classes": 0,
                    "Periods/Week": 0,
                    "Max": (t.get("max_periods_per_day") or 6) * 5,
                    "Status": "⚠️ UNASSIGNED",
                    "Breakdown": "",
                })

        return rows
    except Exception as e:
        st.error(f"Error building load report: {e}")
        return []
        # ============================================================
# TIMETABLE ADVISOR HELPERS
# ============================================================

def tt_advisor_analyse(teachers, classes, assignments, subjects):
    """
    Analyse whether a timetable setup is feasible.

    Rules (Level 2 — flexible):
      - Periods/day comes from the DB (tt_periods, is_break=False).
      - Teaching days come from st.session_state.teaching_days.
      - A class is OK if its total subject periods <= days*periods_per_day.
      - Under-filling is a WARNING (empty slots), not a blocker.
      - Over-filling is a blocker.
      - Teacher overload is a blocker.
      - Unassigned non-exempt subjects are a blocker (only if teachers exist).
    """
    issues = []
    warnings = []
    notes = []

    teacher_by_id = {t.get("id"): t for t in teachers if t.get("id") is not None}

    # ---- Dynamic days/periods ----
    days = st.session_state.get("teaching_days") or [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"
    ]
    try:
        periods_rows = (
            supabase.table("tt_periods")
            .select("period_no")
            .eq("is_break", False)
            .execute()
            .data
            or []
        )
        num_periods = len(periods_rows)
    except Exception:
        num_periods = 8
    max_slots = len(days) * num_periods

    # ---- 1. Per-class totals ----
    class_totals = {}
    for a in assignments:
        cls = a.get("class_name")
        ppw = int(a.get("periods_per_week") or 0)
        class_totals[cls] = class_totals.get(cls, 0) + ppw

    for cls, total in class_totals.items():
        if total > max_slots:
            issues.append(
                f"**{cls}** has **{total} periods/week** — that exceeds the "
                f"**{max_slots}** slots available "
                f"({len(days)} days × {num_periods} periods/day)."
            )
        elif total < max_slots:
            warnings.append(
                f"**{cls}** has **{total} periods/week** — "
                f"**{max_slots - total}** slot(s) will be left empty."
            )

    # ---- 2. Teacher loads ----
    teacher_loads = {}
    teacher_subjects = {}
    teacher_classes = {}
    for a in assignments:
        tid = a.get("teacher_id")
        if tid is None:
            continue
        ppw = int(a.get("periods_per_week") or 0)
        teacher_loads[tid] = teacher_loads.get(tid, 0) + ppw
        teacher_subjects.setdefault(tid, set()).add(a.get("subject_name"))
        teacher_classes.setdefault(tid, set()).add(a.get("class_name"))

    for tid, load in teacher_loads.items():
        t = teacher_by_id.get(tid, {})
        max_pd = int(t.get("max_periods_per_day") or 6)
        max_pw = max_pd * len(days)
        name = t.get("full_name", "?")
        if load > max_pw:
            issues.append(
                f"**{name}** is overloaded: **{load} periods/week** "
                f"vs max **{max_pw}**."
            )
        elif load >= max_pw - 2:
            warnings.append(
                f"**{name}** is near capacity: **{load}/{max_pw}** periods/week."
            )

    # ---- 3. Unassigned teachers ----
    assigned_ids = set(teacher_loads.keys())
    for t in teachers:
        tid = t.get("id")
        if tid is not None and tid not in assigned_ids:
            warnings.append(f"**{t.get('full_name','?')}** has no classes assigned.")

    # ---- 4. Unassigned subjects (only if teachers exist at all) ----
    exempt = {"Free Study", "Assembly"}
    if teachers:
        unassigned_subjects = set()
        for a in assignments:
            if a.get("teacher_id") is None and a.get("subject_name") not in exempt:
                unassigned_subjects.add(a.get("subject_name"))
        if unassigned_subjects:
            issues.append(
                "Subjects without a teacher: **"
                + ", ".join(sorted(unassigned_subjects))
                + "**. Assign teachers to every subject "
                "(except Free Study & Assembly)."
            )

    # ---- 5. Aggregate capacity vs demand ----
    total_demand = sum(teacher_loads.values())
    total_capacity = sum(
        int(t.get("max_periods_per_day") or 6) * len(days) for t in teachers
    )
    if teachers and total_capacity < total_demand:
        issues.append(
            f"Total teacher capacity is **{total_capacity} periods/week** "
            f"but total demand is **{total_demand}**. "
            f"Add more teachers or reduce subjects."
        )

    notes.append(
        f"**{len(classes)} classes** × up to **{max_slots} slots/week** "
        f"= up to **{len(classes) * max_slots} slots/week** total."
    )
    notes.append(
        f"**{len(teachers)} teachers** provide **{total_capacity} periods/week** of capacity."
    )
    if total_demand:
        notes.append(f"**{total_demand} periods/week** currently assigned.")
    notes.append(
        f"Slot math: **{len(days)} days × {num_periods} periods/day = {max_slots} slots/week per class**."
    )

    ok = len(issues) == 0
    return {
        "ok": ok,
        "issues": issues,
        "warnings": warnings,
        "notes": notes,
        "stats": {
            "classes": len(classes),
            "teachers": len(teachers),
            "total_demand": total_demand,
            "total_capacity": total_capacity,
            "max_slots": max_slots,
            "required_per_class": max_slots,
            "num_periods": num_periods,
            "num_days": len(days),
            "class_totals": class_totals,
            "teacher_loads": {
                tid: {
                    "name": teacher_by_id.get(tid, {}).get("full_name", "?"),
                    "load": load,
                    "max": int(teacher_by_id.get(tid, {}).get("max_periods_per_day") or 6) * len(days),
                    "subjects": sorted(teacher_subjects.get(tid, [])),
                    "classes": sorted(teacher_classes.get(tid, [])),
                }
                for tid, load in teacher_loads.items()
            },
        },
    }

def tt_advisor_render_report(result):
    """Render the advisor analysis result in Streamlit."""
    if result.get("ok"):
        if result.get("warnings"):
            st.warning(
                f"⚠️ **This setup will generate, but with {len(result['warnings'])} warning(s).** "
                f"Review the warnings below."
            )
        else:
            st.success("✅ **This setup looks feasible!** You can proceed to generate.")
    else:
        st.error(
            f"❌ **This setup will NOT generate a timetable.** "
            f"Found **{len(result['issues'])}** blocking issue(s)."
        )

    if result.get("issues"):
        st.markdown("### 🚫 Blocking Issues")
        for issue in result["issues"]:
            st.markdown(f"- {issue}")

    if result.get("warnings"):
        st.markdown("### ⚠️ Warnings")
        for w in result["warnings"]:
            st.markdown(f"- {w}")

    if result.get("notes"):
        st.markdown("### 📝 Notes")
        for n in result["notes"]:
            st.markdown(f"- {n}")

    stats = result.get("stats", {})
    class_totals = stats.get("class_totals", {})
    max_slots = stats.get("max_slots", 40)

    if class_totals:
        st.markdown("### 📋 Periods per Class")
        rows = []
        for cls, total in sorted(class_totals.items()):
            empty = max(0, max_slots - total)
            if total > max_slots:
                status = f"❌ +{total - max_slots} over"
            elif empty > 0:
                status = f"⚠️ {empty} empty"
            else:
                status = "✅ Full"
            rows.append({
                "Class": cls,
                "Periods/Week": total,
                "Max Slots": max_slots,
                "Empty Slots": empty,
                "Status": status,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    teacher_loads = stats.get("teacher_loads", {})
    if teacher_loads:
        st.markdown("### 👨‍🏫 Teacher Load Summary")
        rows = []
        for tid, info in sorted(teacher_loads.items(), key=lambda x: -x[1]["load"]):
            if info["load"] > info["max"]:
                status = "❌ OVERLOADED"
            elif info["load"] >= info["max"] - 2:
                status = "⚠️ Near max"
            else:
                status = "✅ OK"
            rows.append({
                "Teacher": info["name"],
                "Periods/Week": info["load"],
                "Max": info["max"],
                "Classes": len(info["classes"]),
                "Subjects": ", ".join(info["subjects"]),
                "Status": status,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ---- Per-teacher load table ----
    teacher_loads = result.get("stats", {}).get("teacher_loads", {})
    if teacher_loads:
        st.markdown("### 👨‍🏫 Teacher Load Summary")
        rows = []
        for tid, info in sorted(teacher_loads.items(), key=lambda x: -x[1]["load"]):
            status = "✅ OK"
            if info["load"] > info["max"]:
                status = "❌ OVERLOADED"
            elif info["load"] >= info["max"] - 2:
                status = "⚠️ Near max"
            rows.append({
                "Teacher": info["name"],
                "Periods/Week": info["load"],
                "Max": info["max"],
                "Classes": len(info["classes"]),
                "Subjects": ", ".join(info["subjects"]),
                "Status": status,
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

def get_all_streams_from_data():
    """Return list of streams from the current Excel data."""
    if st.session_state.get("data") is None:
        return []
    df = st.session_state.data["df"]
    stream_col = st.session_state.data["stream_col"]
    return sorted(df[stream_col].astype(str).unique().tolist())

def generate_receipt_pdf(payment_row, school_name, balance_before, balance_after):
    """Generate a fee payment receipt PDF with small logo top, faint logo watermark, and motto."""
    buf = io.BytesIO()
    from reportlab.lib.pagesizes import A5
    from reportlab.lib.utils import ImageReader
    doc = SimpleDocTemplate(
        buf, pagesize=A5,
        leftMargin=25, rightMargin=25, topMargin=20, bottomMargin=20
    )
    styles = pdf_styles()

    page_w, page_h = A5  # 419 x 595 points

    # ==========================================================
    # Watermark: faint logo covering the middle of the receipt
    # ==========================================================
    def draw_watermark(canvas, doc):
        logo = st.session_state.get("school_logo")
        if not logo:
            return
        try:
            img = ImageReader(io.BytesIO(logo))
            iw, ih = img.getSize()
            # Cover ~70% of page width
            target_w = page_w * 0.72
            scale = target_w / iw
            target_h = ih * scale
            x = (page_w - target_w) / 2
            y = (page_h - target_h) / 2 + 20  # slightly higher, behind the data
            canvas.saveState()
            canvas.setFillAlpha(0.12)  # Light (12%)
            canvas.drawImage(img, x, y, width=target_w, height=target_h, mask='auto')
            canvas.restoreState()
        except Exception:
            pass

    story = []

    # ==========================================================
    # Header with SMALL logo at the top (uses pdf_school_header)
    # ==========================================================
    pdf_school_header(story, school_name, styles, "FEE PAYMENT RECEIPT")
    story.append(Spacer(1, 5))

    # ==========================================================
    # Motto #1 — under the header
    # ==========================================================
    motto = (st.session_state.get("school_motto") or "").strip()
    motto_style = ParagraphStyle(
        "Motto", parent=styles["cell"],
        fontName="Helvetica-Oblique", fontSize=9, leading=12, alignment=1,
        textColor=colors.HexColor("#444444")
    )
    if motto:
        motto_table = Table(
            [[Paragraph(f"“{motto}”", motto_style)]],
            colWidths=[380]
        )
        motto_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f9fa")),
            ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d0d6")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.append(motto_table)
        story.append(Spacer(1, 6))

    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#263238")))
    story.append(Spacer(1, 6))

    # ==========================================================
    # Receipt number + date
    # ==========================================================
    receipt_no = f"RCP-{int(payment_row.get('id', 0)):06d}"
    pay_date = str(payment_row.get("payment_date", ""))

    info_style = ParagraphStyle("Info", parent=styles["cell"], fontSize=9, leading=11)
    header_style = ParagraphStyle("HeaderX", parent=styles["cell"], fontName="Helvetica-Bold", fontSize=9, leading=11)
    big_number = ParagraphStyle("BigNum", parent=styles["cell"], fontName="Helvetica-Bold", fontSize=12, leading=15, alignment=1)

    top = Table([
        [Paragraph("Receipt No:", header_style), Paragraph(receipt_no, info_style),
         Paragraph("Date:", header_style), Paragraph(pay_date, info_style)]
    ], colWidths=[70, 130, 45, 135])
    top.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf1f3")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#edf1f3")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d0d6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(top)
    story.append(Spacer(1, 6))

    # ==========================================================
    # Student + Payment details
    # ==========================================================
    details = [
        [Paragraph("Student", header_style), Paragraph(str(payment_row.get("student_name", "")), info_style)],
        [Paragraph("Stream", header_style), Paragraph(str(payment_row.get("stream", "")), info_style)],
        [Paragraph("Term", header_style), Paragraph((payment_row.get("term") or "").upper(), info_style)],
        [Paragraph("Method", header_style), Paragraph(str(payment_row.get("payment_method", "")), info_style)],
        [Paragraph("Reference", header_style), Paragraph(str(payment_row.get("reference", "")) or "—", info_style)],
    ]
    details_table = Table(details, colWidths=[75, 305])
    details_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f7f9fa")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d0d6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 8))

    # ==========================================================
    # Amount breakdown
    # ==========================================================
    amount = float(payment_row.get("amount", 0))
    amount_table = Table([
        [Paragraph("Previous Balance", header_style), Paragraph(f"KSh {balance_before:,.0f}", info_style)],
        [Paragraph("Amount Paid Now", header_style), Paragraph(f"KSh {amount:,.0f}", info_style)],
        [Paragraph("New Balance", header_style), Paragraph(f"KSh {balance_after:,.0f}", info_style)],
    ], colWidths=[140, 240])
    amount_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf1f3")),
        ("BACKGROUND", (0, 1), (0, 1), colors.HexColor("#fff3cd")),
        ("BACKGROUND", (0, 2), (0, 2), colors.HexColor("#d4edda") if balance_after <= 0 else colors.HexColor("#f8d7da")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9d0d6")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(amount_table)
    story.append(Spacer(1, 10))

    # ==========================================================
    # Big total box
    # ==========================================================
    total_box = Table([
        [Paragraph(f"TOTAL RECEIVED:  KSh {amount:,.0f}", big_number)]
    ], colWidths=[380])
    total_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#263238")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#263238")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(total_box)
    story.append(Spacer(1, 12))

    # ==========================================================
    # Motto #2 — above the signature line
    # ==========================================================
    if motto:
        story.append(Paragraph(f"“{motto}”", motto_style))
        story.append(Spacer(1, 8))

    # ==========================================================
    # Received by with clerk signature
    # ==========================================================
    recv_by = str(payment_row.get("recorded_by", ""))
    recv_by_name = recv_by  # default to username

    # Try to fetch clerk's full name and signature
    clerk_sig_b64 = None
    try:
        clerk_result = supabase.table("users").select("student_name,signature_base64").eq("username", recv_by).execute()
        if clerk_result.data:
            row = clerk_result.data[0]
            if row.get("student_name"):
                recv_by_name = row["student_name"]
            if row.get("signature_base64"):
                clerk_sig_b64 = row["signature_base64"]
    except Exception:
        pass

    story.append(Paragraph("Received by:", header_style))
    story.append(Paragraph(recv_by_name, info_style))

    # If clerk has a signature image, show it
    if clerk_sig_b64:
        try:
            sig_bytes = base64.b64decode(clerk_sig_b64)
            sig_img = Image(io.BytesIO(sig_bytes), width=1.5*inch, height=0.55*inch)
            story.append(Spacer(1, 4))
            story.append(sig_img)
        except Exception:
            story.append(Paragraph("_____________________________", info_style))
    else:
        story.append(Spacer(1, 14))
        story.append(Paragraph("_____________________________", info_style))

    story.append(Paragraph(f"Date: {pay_date}", info_style))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.4, color=colors.HexColor("#999999")))
    story.append(Paragraph(
        "Thank you for your payment. Retain this receipt for your records.",
        styles["meta"]
    ))

    doc.build(story, onFirstPage=draw_watermark, onLaterPages=draw_watermark)
    buf.seek(0)
    return buf
# ============================================================
# DATA PREPARATION
# ============================================================

def clean_label(value):
    value = str(value)
    for term in TERMS:
        if value.lower().startswith(term):
            remainder = value[len(term):].strip()
            return remainder.replace("_", " ").replace("-", " ").title() or term.upper()
    return value.replace("_", " ").replace("-", " ").title()


def detect_terms_from_columns(columns):
    """Scan columns and return a sorted list of unique terms like ['y1t1','y1t2','y2t3','y3t1',...]."""
    pattern = re.compile(r"^(y\d+t\d+)")
    found = set()
    for col in columns:
        col_lower = str(col).lower().strip()
        match = pattern.match(col_lower)
        if match:
            found.add(match.group(1))

    def sort_key(t):
        m = re.match(r"y(\d+)t(\d+)", t)
        if m:
            return (int(m.group(1)), int(m.group(2)))
        return (0, 0)

    return sorted(found, key=sort_key)


def detect_columns(raw_df):
    df = raw_df.copy()
    df.columns = df.columns.astype(str).str.strip().str.lower()

    name_col = next((c for c in df.columns if "name" in c), None)
    if name_col is None:
        name_col = df.columns[0]

    stream_col = next(
        (c for c in df.columns if any(w in c for w in ["stream", "class", "form", "sec"])),
        None
    )
    if stream_col is None:
        stream_col = "__stream__"
        df[stream_col] = "GENERAL"

    df[stream_col] = df[stream_col].astype(str).str.strip().str.upper()

    detected_terms = detect_terms_from_columns(df.columns)
    if not detected_terms:
        detected_terms = TERMS

    avg_cols = []
    for term in detected_terms:
        candidates = [c for c in df.columns if term in c and "avg" in c and "total" not in c]
        if not candidates:
            candidates = [c for c in df.columns if term in c and "total" not in c]
        avg_cols.append(candidates[0] if candidates else None)

    pairs = [(t, c) for t, c in zip(detected_terms, avg_cols) if c is not None]
    return (
        df,
        name_col,
        stream_col,
        [p[0] for p in pairs],
        [p[1] for p in pairs]
    )


def prepare_data(raw_df, selected_term):
    df, name_col, stream_col, terms, avg_cols = detect_columns(raw_df)

    if not avg_cols:
        raise ValueError(
            "No term columns were detected. Use names such as y1t1avg, y1t2avg and y2t3avg."
        )

    if selected_term not in terms:
        selected_term = terms[-1]

    target = avg_cols[terms.index(selected_term)]

    for col in avg_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    subjects = [
        c for c in df.columns
        if selected_term in c
        and c != target
        and "avg" not in c
        and "total" not in c
        and c not in [name_col, stream_col]
    ]

    if not subjects:
        excluded = set(avg_cols + [name_col, stream_col])
        for col in df.columns:
            if "total" in str(col).lower():
                excluded.add(col)
        subjects = [
            c for c in df.columns
            if c not in excluded and pd.api.types.is_numeric_dtype(df[c])
        ]

    for subject in subjects:
        df[subject] = pd.to_numeric(df[subject], errors="coerce").fillna(0.0)

    df["overall_rank"] = df[target].rank(ascending=False, method="min").astype(int)
    df["stream_rank"] = df.groupby(stream_col)[target].rank(
        ascending=False, method="min"
    ).astype(int)

    if len(avg_cols) >= 2:
        previous = avg_cols[avg_cols.index(target) - 1]
        df["term_change"] = df[target] - df[previous]
    else:
        df["term_change"] = 0.0

    return {
        "df": df,
        "name_col": name_col,
        "stream_col": stream_col,
        "target_terms": terms,
        "avg_cols": avg_cols,
        "target_rank_col": target,
        "subject_cols": subjects,
        "analysis_term": selected_term,
    }


def school_statistics(data):
    df = data["df"]
    target = data["target_rank_col"]
    return {
        "students": len(df),
        "streams": df[data["stream_col"]].nunique(),
        "mean": df[target].mean(),
        "highest": df[target].max(),
        "lowest": df[target].min(),
        "pass_rate": (df[target] >= 50).mean() * 100,
    }


def grade(score):
    """KCSE 12-point grading."""
    if score >= 80: return "A"
    if score >= 75: return "A-"
    if score >= 70: return "B+"
    if score >= 65: return "B"
    if score >= 60: return "B-"
    if score >= 55: return "C+"
    if score >= 50: return "C"
    if score >= 45: return "C-"
    if score >= 40: return "D+"
    if score >= 35: return "D"
    if score >= 30: return "D-"
    return "E"


def grade_points(score):
    """KCSE 12-point scale (1-12)."""
    if score >= 80: return 12
    if score >= 75: return 11
    if score >= 70: return 10
    if score >= 65: return 9
    if score >= 60: return 8
    if score >= 55: return 7
    if score >= 50: return 6
    if score >= 45: return 5
    if score >= 40: return 4
    if score >= 35: return 3
    if score >= 30: return 2
    return 1


def result_summary(scores):
    clean_scores = [float(x) for x in scores if pd.notna(x)]
    total = sum(clean_scores)
    maximum = len(clean_scores) * 100
    percentage = (total / maximum * 100) if maximum else 0.0
    return total, maximum, percentage


def correlation_table(data):
    df = data["df"]
    target = data["target_rank_col"]
    rows = []
    for subject in data["subject_cols"]:
        x = df[subject]
        y = df[target]
        if x.nunique() <= 1 or y.nunique() <= 1:
            corr = np.nan; slope = np.nan; intercept = np.nan
        else:
            result = linregress(x, y)
            corr = x.corr(y)
            slope = result.slope
            intercept = result.intercept
        rows.append({
            "Subject": clean_label(subject),
            "Correlation (r)": corr,
            "Regression slope": slope,
            "Regression intercept": intercept,
        })
    return pd.DataFrame(rows)

# ============================================================
# CHARTS
# ============================================================

def progression_figure(student, data):
    values = [float(student[c]) for c in data["avg_cols"]]
    labels = [x.upper() for x in data["target_terms"]]
    x = np.arange(len(values))

    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    ax.plot(x, values, marker="o", linewidth=2.5)
    ax.axhline(50, linestyle="--", linewidth=1.2, label="Pass mark")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylim(0, 105)
    ax.set_ylabel("Average (%)")
    ax.set_title("Academic Performance Progression")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig


def subject_figure(student, data):
    stream = student[data["stream_col"]]
    sdf = data["df"][data["df"][data["stream_col"]] == stream]
    subjects = data["subject_cols"]

    scores = [float(student[s]) for s in subjects]
    means = [float(sdf[s].mean()) for s in subjects]
    labels = [clean_label(s) for s in subjects]

    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    x = np.arange(len(labels))
    width = 0.36

    ax.bar(x - width/2, scores, width, label="Student")
    ax.bar(x + width/2, means, width, label="Stream mean", alpha=0.7)
    ax.axhline(50, linestyle="--", linewidth=1.2, label="Pass mark")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=25, ha="right")
    ax.set_ylim(0, 105)
    ax.set_ylabel("Score (%)")
    ax.set_title("Subject Performance vs Stream Mean")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    return fig


def figure_bytes(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


# ============================================================
# PDF HELPERS
# ============================================================

def pdf_styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleX", parent=styles["Heading1"],
            fontName="Helvetica-Bold", fontSize=16, leading=20, alignment=1
        ),
        "meta": ParagraphStyle(
            "MetaX", parent=styles["Normal"],
            fontSize=8, leading=10, alignment=1,
            textColor=colors.HexColor("#666666")
        ),
        "cell": ParagraphStyle(
            "CellX", parent=styles["Normal"],
            fontSize=7, leading=8
        ),
        "center": ParagraphStyle(
            "CenterX", parent=styles["Normal"],
            fontSize=7, leading=8, alignment=1
        ),
        "header": ParagraphStyle(
            "HeaderX", parent=styles["Normal"],
            fontName="Helvetica-Bold", fontSize=7,
            leading=8, alignment=1, textColor=colors.white
        ),
    }


def pdf_school_header(story, school_name, styles, report_subtitle):
    logo = st.session_state.get("school_logo")
    logo_rendered = False
    if logo:
        try:
            logo_buf = io.BytesIO(logo)
            logo_img = Image(logo_buf, width=0.75*inch, height=0.75*inch)
            # Two-column header: [logo | school name]
            header = Table(
                [[logo_img, Paragraph(school_name, styles["title"])]],
                                colWidths=[0.9*inch, 4.2*inch]
            )
            header.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(header)
            logo_rendered = True
        except Exception as e:
            # If logo rendering fails, fall through to just the school name
            logo_rendered = False

    if not logo_rendered:
        story.append(Paragraph(school_name, styles["title"]))

    contact = " • ".join([x for x in [
        st.session_state.get("school_address", ""),
        st.session_state.get("school_phone", ""),
        st.session_state.get("school_email", ""),
    ] if x])
    if contact:
        story.append(Paragraph(contact, styles["meta"]))
        story.append(Spacer(1, 2))
    story.append(Paragraph(report_subtitle, styles["meta"]))

def build_merit_table(frame, data, footer_label):
    styles = pdf_styles()
    name_col = data["name_col"]
    stream_col = data["stream_col"]
    target = data["target_rank_col"]
    subjects = data["subject_cols"]

    cols = [name_col, stream_col, "stream_rank", "overall_rank", target] + subjects
    headers = [
        "Student", "Stream", "Stream Rank", "School Rank",
        clean_label(target)
    ] + [clean_label(s) for s in subjects]

    rows = [[Paragraph(h, styles["header"]) for h in headers]]

    for _, row in frame[cols].iterrows():
        out = []
        for c in cols:
            value = row[c]
            if c in subjects + [target]:
                text = f"{float(value):.1f}%"
            elif c in ["stream_rank", "overall_rank"]:
                text = str(int(value))
            else:
                text = str(value)
            out.append(Paragraph(
                text,
                styles["cell"] if c == name_col else styles["center"]
            ))
        rows.append(out)

    footer = []
    for c in cols:
        if c == name_col:
            text = footer_label
        elif c in subjects + [target]:
            text = f"{frame[c].mean():.1f}%"
        else:
            text = "-"
        footer.append(Paragraph(
            text,
            styles["cell"] if c == name_col else styles["center"]
        ))
    rows.append(footer)

    fixed = 45 + 45 + 55
    available = 792 - 40
    name_width = 130
    subject_width = max(34, (available - name_width - fixed - 55) / max(1, len(subjects)))
    widths = [name_width, 55, 45, 45, 55] + [subject_width] * len(subjects)

    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263238")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -2), 0.35, colors.HexColor("#d7dce0")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eaf2f8")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def generate_master_pdf(data, school_name):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(letter),
        leftMargin=18, rightMargin=18, topMargin=14, bottomMargin=14
    )
    styles = pdf_styles()
    df = data["df"]

    story = []
    pdf_school_header(
        story, school_name, styles,
        f"MASTER ACADEMIC MERIT REPORT | {data['analysis_term'].upper()} | "
        f"Academic Year {st.session_state.get('academic_year', '')} | "
        f"Generated {datetime.now():%Y-%m-%d %H:%M}"
    )
    story.extend([
        Spacer(1, 10),
        build_merit_table(
            df.sort_values("overall_rank"),
            data,
            "SCHOOL AVERAGE"
        ),
    ])

    for stream, sdf in df.groupby(data["stream_col"]):
        story.extend([
            PageBreak(),
            Spacer(1, 3),
        ])
        pdf_school_header(
            story, school_name, styles,
            f"STREAM {stream} MERIT REPORT | {data['analysis_term'].upper()} | "
            f"Academic Year {st.session_state.get('academic_year', '')}"
        )
        story.extend([
            Spacer(1, 10),
            build_merit_table(
                sdf.sort_values("stream_rank"),
                data,
                f"STREAM {stream} AVERAGE"
            )
        ])

    doc.build(story)
    buf.seek(0)
    return buf


def _find_admission_col(data):
    df = data["df"]
    excluded = {data["name_col"], data["stream_col"]}
    keywords = ["admission", "adm", "student_id", "student id", "index", "reg no", "registration"]
    for col in df.columns:
        if col in excluded:
            continue
        label = str(col).lower().replace("_", " ")
        if any(k in label for k in keywords):
            return col
    return None


def _subject_comment(score):
    if score >= 80: return "Excellent"
    if score >= 70: return "Very good"
    if score >= 60: return "Good"
    if score >= 50: return "Satisfactory"
    return "Needs improvement"


def _overall_comment(score):
    if score >= 80:
        return "Excellent overall performance. Maintain the high standard."
    if score >= 70:
        return "Very good performance. Continue working consistently."
    if score >= 60:
        return "Good performance. More focused practice can lead to further improvement."
    if score >= 50:
        return "Satisfactory performance. Greater consistency and revision are encouraged."
    return "Performance requires improvement. Focused support, revision and regular practice are recommended."


PREPARED_TEACHER_COMMENTS = [
    "Excellent performance. Maintain the high standard and keep working hard.",
    "Very good progress this term. Continue working consistently.",
    "Good performance. More focused practice can lead to further improvement.",
    "Satisfactory performance. Greater consistency and regular revision are encouraged.",
    "More effort and regular revision are required to improve performance.",
    "The student has shown encouraging progress. Keep building on this improvement.",
    "The student should remain focused, complete assignments regularly and seek help where necessary.",
]


def generate_student_pdf(student, data, school_name, class_comment=None, report_date=None):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=landscape(letter),
        leftMargin=14, rightMargin=14, topMargin=12, bottomMargin=12
    )
    styles = pdf_styles()
    name = str(student[data["name_col"]]).strip()
    if not name or name.lower() == "nan":
        name = "(Name not found)"
    stream = str(student[data["stream_col"]])
    target = data["target_rank_col"]
    score = float(student[target])
    admission_col = _find_admission_col(data)
    admission_no = str(student[admission_col]) if admission_col else "—"
    stream_size = len(data["df"][data["df"][data["stream_col"]] == student[data["stream_col"]]])
    student_key = str(student[data["name_col"]])
    class_comment = (class_comment or st.session_state.get("teacher_comments", {}).get(student_key, "")).strip()
    if not class_comment:
        class_comment = _overall_comment(score)
    principal_comment = st.session_state.get("principal_comment", "").strip()
    report_date = report_date or st.session_state.get("report_issue_date", date.today())
    if hasattr(report_date, "strftime"):
        report_date_text = report_date.strftime("%d %B %Y")
    else:
        report_date_text = str(report_date)
    if not principal_comment:
        principal_comment = "Congratulations on your progress. Continue working hard and remain disciplined."

    story = []
    pdf_school_header(
        story, school_name, styles,
        f"STUDENT REPORT CARD | {data['analysis_term'].upper()} | "
        f"Academic Year {st.session_state.get('academic_year', '')}"
    )
    story.append(Spacer(1, 3))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#263238")))
    story.append(Spacer(1, 3))

    info_style = ParagraphStyle(
        "Info", parent=styles["cell"], fontSize=8.5, leading=10
    )
    info_header = ParagraphStyle(
        "InfoHeader", parent=styles["cell"], fontName="Helvetica-Bold",
        fontSize=8.5, leading=10
    )
    identity = [
        [Paragraph("Student Name", info_header), Paragraph(name, info_style),
         Paragraph("Admission / ID", info_header), Paragraph(admission_no, info_style)],
        [Paragraph("Stream", info_header), Paragraph(stream, info_style),
         Paragraph("Academic Year", info_header), Paragraph(str(st.session_state.get("academic_year", "")), info_style)],
        [Paragraph("School Position", info_header), Paragraph(f"{int(student['overall_rank'])} / {len(data['df'])}", info_style),
         Paragraph("Stream Position", info_header), Paragraph(f"{int(student['stream_rank'])} / {stream_size}", info_style)],
        [Paragraph("Total Marks", info_header), Paragraph(f"{sum(float(student[sub]) for sub in data['subject_cols']):.1f}", info_style),
         Paragraph("Maximum Marks", info_header), Paragraph(f"{len(data['subject_cols']) * 100}", info_style)],
        [Paragraph("Average / Percentage", info_header), Paragraph(f"{score:.1f}%", info_style),
         Paragraph("Overall Grade", info_header), Paragraph(grade(score), info_style)],
    ]
    identity_table = Table(identity, colWidths=[85, 205, 90, 205])
    identity_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#edf1f3")),
        ("BACKGROUND", (2, 0), (2, -1), colors.HexColor("#edf1f3")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d0d6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(identity_table)
    story.append(Spacer(1, 5))

    subject_rows = [[
        Paragraph("Subject", styles["header"]),
        Paragraph("Score", styles["header"]),
        Paragraph("Grade", styles["header"]),
        Paragraph("Stream Mean", styles["header"]),
        Paragraph("Difference", styles["header"]),
        Paragraph("Comment", styles["header"]),
    ]]
    sdf = data["df"][data["df"][data["stream_col"]] == student[data["stream_col"]]]
    for subject in data["subject_cols"]:
        s = float(student[subject])
        mean = float(sdf[subject].mean())
        subject_rows.append([
            Paragraph(clean_label(subject), styles["cell"]),
            Paragraph(f"{s:.1f}%", styles["center"]),
            Paragraph(grade(s), styles["center"]),
            Paragraph(f"{mean:.1f}%", styles["center"]),
            Paragraph(f"{s - mean:+.1f}%", styles["center"]),
            Paragraph(_subject_comment(s), styles["cell"]),
        ])

    subject_table = Table(
        subject_rows,
        colWidths=[175, 62, 55, 78, 72, 145],
        repeatRows=1
    )
    subject_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263238")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d7dce0")),
        ("ALIGN", (1, 0), (4, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fa")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(Paragraph("Subject Performance", ParagraphStyle(
        "Section", parent=styles["cell"], fontName="Helvetica-Bold", fontSize=10, leading=12
    )))
    story.append(Spacer(1, 2))
    story.append(subject_table)
    story.append(Spacer(1, 5))

    term_rows = [[Paragraph("Term", styles["header"]), Paragraph("Average", styles["header"]), Paragraph("Grade", styles["header"])]]
    for term, avg_col in zip(data["target_terms"], data["avg_cols"]):
        ts = float(student[avg_col])
        term_rows.append([term.upper(), f"{ts:.1f}%", grade(ts)])
    history_table = Table(term_rows, colWidths=[75, 75, 65], repeatRows=1)
    history_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263238")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d7dce0")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("PADDING", (0, 0), (-1, -1), 3),
    ]))

    img1 = Image(figure_bytes(progression_figure(student, data)), width=3.1*inch, height=1.35*inch)
    img2 = Image(figure_bytes(subject_figure(student, data)), width=3.1*inch, height=1.35*inch)
    charts = Table([[img1, img2]], colWidths=[3.3*inch, 3.3*inch])
    charts.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE")
    ]))

    summary_box = Table([
        [Paragraph("Class Teacher Comment", info_header)],
        [Paragraph(class_comment, info_style)],
        [Paragraph("Principal / Head Teacher Comment", info_header)],
        [Paragraph(principal_comment, info_style)],
        [Paragraph(f"Previous-term change: {float(student['term_change']):+.1f}%", info_style)],
    ], colWidths=[2.55*inch])
    summary_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf1f3")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d0d6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))

    lower = Table([[history_table, charts, summary_box]], colWidths=[2.2*inch, 6.8*inch, 2.65*inch])
    lower.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(lower)
    story.append(Spacer(1, 4))

    teacher_sig = st.session_state.get("teacher_signature")
    principal_sig = st.session_state.get("principal_signature")
    teacher_cell = Image(io.BytesIO(teacher_sig), width=1.35*inch, height=0.55*inch) if teacher_sig else "____________________________"
    principal_cell = Image(io.BytesIO(principal_sig), width=1.35*inch, height=0.55*inch) if principal_sig else "____________________________"
    signatures = Table([
        [st.session_state.get("class_teacher_name", "Class Teacher"), st.session_state.get("principal_name", "Principal / Head Teacher"), "Parent / Guardian"],
        [teacher_cell, principal_cell, "____________________________"],
        [f"Date: {report_date_text}", f"Date: {report_date_text}", "Date: _______________________"],
    ], colWidths=[3.8*inch, 3.8*inch, 3.8*inch])
    signatures.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(signatures)
    story.append(Spacer(1, 3))
    story.append(Paragraph(
        f"Generated by Student Academic Management System • {datetime.now():%Y-%m-%d %H:%M}",
        styles["meta"]
    ))

    doc.build(story)
    buf.seek(0)
    return buf


def generate_all_student_pdfs(data, school_name):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for _, student in data["df"].iterrows():
            pdf = generate_student_pdf(student, data, school_name)
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(student[data["name_col"]])).strip("_")
            archive.writestr(f"Student_{safe}_Report.pdf", pdf.getvalue())
    zip_buffer.seek(0)
    return zip_buffer


# ============================================================
def _backup_excel_bytes():
    """Build an Excel workbook with one sheet per role. No passwords."""
    import openpyxl
    from io import BytesIO

    buf = BytesIO()

    # Fetch all users
    try:
        rows = supabase.table("users").select("username,role,student_name").execute().data or []
    except Exception as e:
        raise RuntimeError(f"Could not fetch users: {e}")

    # Fetch parents (child links)
    parents_map = {}
    try:
        prows = supabase.table("parents").select("username,parent_name,child_names").execute().data or []
        for p in prows:
            parents_map[p["username"]] = p.get("child_names") or ""
    except Exception:
        pass

    # Group by role
    groups = {
        "Admins": [],
        "Teachers": [],
        "Students": [],
        "Parents": [],
        "Clerks": [],
        "Exams Officers": [],
        "IT Officers": [],
    }
    for r in rows:
        role = (r.get("role") or "").lower()
        if role == "admin":
            groups["Admins"].append(r)
        elif role == "teacher":
            groups["Teachers"].append(r)
        elif role == "student":
            groups["Students"].append(r)
        elif role == "parent":
            groups["Parents"].append(r)
        elif role == "clerk":
            groups["Clerks"].append(r)
        elif role == "exams":
            groups["Exams Officers"].append(r)
        elif role == "it_officer":
            groups["IT Officers"].append(r)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # drop default sheet

    # ---- Summary sheet ----
    ws = wb.create_sheet("Summary")
    ws.append(["SCHOOL BACKUP SUMMARY"])
    ws.append([])
    ws.append(["School", st.session_state.get("school_name", "")])
    ws.append(["Generated", datetime.now().strftime("%d %B %Y at %H:%M")])
    ws.append([])
    ws.append(["Role", "Count"])
    total = 0
    for label, items in groups.items():
        ws.append([label, len(items)])
        total += len(items)
    ws.append([])
    ws.append(["TOTAL", total])
    ws.column_dimensions["A"].width = 25
    ws.column_dimensions["B"].width = 40

    # ---- One sheet per group ----
    for label, items in groups.items():
        if not items:
            continue
        ws = wb.create_sheet(label[:31])  # Excel sheet name limit

        if label == "Parents":
            ws.append(["Full Name", "Username", "Children"])
            for r in sorted(items, key=lambda x: x.get("student_name") or ""):
                ws.append([
                    r.get("student_name") or "",
                    r.get("username") or "",
                    parents_map.get(r.get("username"), ""),
                ])
        else:
            ws.append(["Full Name", "Username"])
            for r in sorted(items, key=lambda x: x.get("student_name") or ""):
                ws.append([
                    r.get("student_name") or "",
                    r.get("username") or "",
                ])

        # Column widths
        ws.column_dimensions["A"].width = 35
        ws.column_dimensions["B"].width = 30
        if label == "Parents":
            ws.column_dimensions["C"].width = 40

    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _backup_passwords_csv_bytes():
    """Build a CSV with username + password hash. Sensitive — do not share."""
    try:
        rows = supabase.table("users").select("username,password,role").execute().data or []
    except Exception as e:
        raise RuntimeError(f"Could not fetch users: {e}")

    lines = ["Username,Password Hash,Role"]
    for r in sorted(rows, key=lambda x: x.get("username") or ""):
        username = str(r.get("username") or "").replace(",", "")
        pw = str(r.get("password") or "").replace(",", "")
        role = str(r.get("role") or "")
        lines.append(f"{username},{pw},{role}")
    return "\n".join(lines).encode("utf-8")


def _backup_summary_pdf_bytes():
    """Build a one-page printable PDF summary of the school's accounts."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    import io as _io

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleX", parent=styles["Heading1"],
        fontName="Helvetica-Bold", fontSize=16, leading=20, alignment=1
    )
    subtitle_style = ParagraphStyle(
        "SubX", parent=styles["Normal"],
        fontSize=10, leading=12, alignment=1,
        textColor=colors.HexColor("#555555")
    )
    section_style = ParagraphStyle(
        "SectionX", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=12, leading=14,
        spaceBefore=10, spaceAfter=4
    )
    cell_style = ParagraphStyle(
        "CellX", parent=styles["Normal"], fontSize=9, leading=11
    )

    try:
        rows = supabase.table("users").select("username,role,student_name").execute().data or []
    except Exception:
        rows = []

    groups = {"admin": [], "teacher": [], "student": [], "parent": [], "clerk": [], "exams": [], "it_officer": []}
    for r in rows:
        role = (r.get("role") or "").lower()
        if role in groups:
            groups[role].append(r)

    story = []
    story.append(Paragraph(st.session_state.get("school_name", "School"), title_style))
    story.append(Paragraph("System Backup Summary", subtitle_style))
    story.append(Paragraph(
        f"Generated: {datetime.now().strftime('%d %B %Y at %H:%M')}",
        subtitle_style
    ))
    story.append(Spacer(1, 20))

    # ---- Summary table ----
    summary_data = [["Role", "Count"]]
    total = 0
    labels = {
        "admin": "Administrators",
        "teacher": "Teachers",
        "student": "Students",
        "parent": "Parents",
        "clerk": "Clerks",
        "exams": "Exams Officers",
        "it_officer": "IT Officers",
    }
    for key, label in labels.items():
        count = len(groups[key])
        summary_data.append([label, str(count)])
        total += count
    summary_data.append(["TOTAL", str(total)])

    t = Table(summary_data, colWidths=[200, 100])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263238")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#edf1f3")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d0d6")),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)

    # ---- Account lists ----
    for key, label in labels.items():
        items = sorted(groups[key], key=lambda x: x.get("student_name") or "")
        if not items:
            continue
        story.append(Paragraph(f"{label} ({len(items)})", section_style))
        data = [["Full Name", "Username"]]
        for r in items:
            data.append([
                Paragraph(str(r.get("student_name") or ""), cell_style),
                Paragraph(str(r.get("username") or ""), cell_style),
            ])
        tbl = Table(data, colWidths=[280, 180], repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#455a64")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d7dce0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fa")]),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(tbl)

    story.append(Spacer(1, 20))
    story.append(Paragraph("_____________________________", cell_style))
    story.append(Paragraph("Received by (Principal / Deputy) & Date", cell_style))

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()
def create_backup_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        tables = [
            "users", "students", "parents",
            "materials", "submissions",
            "quizzes", "quiz_questions", "quiz_attempts",
            "results_store", "school_settings",
            "fee_structure", "fee_payments", "fee_audit_log",
        ]
        for table in tables:
            try:
                rows = supabase.table(table).select("*").execute().data or []
                z.writestr(f"{table}.json", json.dumps(rows, default=str, indent=2))
            except Exception as e:
                z.writestr(f"{table}_ERROR.txt", str(e))
    buf.seek(0)
    return buf


# SESSION STATE
# ============================================================

defaults = {
    "logged_in": False,
    "school_name": DEFAULT_SCHOOL,
    "school_address": "",
    "school_phone": "",
    "school_email": "",
    "academic_year": "2026",
    "current_term": "Term 3",
    "school_logo": None,
    "class_teacher_name": "Class Teacher",
    "principal_name": "Principal / Head Teacher",
    "principal_comment": "Congratulations on your progress. Continue working hard and remain disciplined.",
    "school_motto": "Learn • Grow • Succeed",
    "teacher_comments": {},
    "teacher_signature": None,
    "principal_signature": None,
    "report_issue_date": date.today(),
    "data": None,
    "raw_data": None,
    "raw_file_name": None,
    "user_role": "",
    "username": "",
    "student_name": "",
    "active_quiz": None,
        "active_quiz": None,
    "teaching_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value# Load persisted school settings from Supabase (once per session)
if not st.session_state.get("_settings_loaded"):
    load_school_settings()
    st.session_state["_settings_loaded"] = True

# ============================================================
# LOGIN SCREEN
# ============================================================

def login_screen():
    st.markdown(
        '<div class="app-title">Student Academic Management System</div>',
        unsafe_allow_html=True
    )
    st.markdown(
        '<div class="app-subtitle">Academic reporting + Learning Centre</div>',
        unsafe_allow_html=True
    )

    left, center, right = st.columns([1, 1.4, 1])
    with center:
        school_code = st.text_input(
            "School code",
            placeholder="e.g. exc",
            help="Ask your school administrator if you don't know this."
        ).strip().lower()

        role = st.selectbox("Login as", ["Administrator", "Teacher", "Student", "Parent", "Clerk", "Exams Officer", "IT Officer"])
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Sign in", type="primary", use_container_width=True):
                        # --- Stage 2: control plane lookup ---
            if not school_code:
                st.error("Please enter your school code.")
                st.stop()
            try:
                _ctl_url = st.secrets["CONTROL_URL"]
                _ctl_key = st.secrets["CONTROL_KEY"]
                import requests as _rq
                _r = _rq.get(
                    f"{_ctl_url}/rest/v1/schools?school_id=eq.{school_code}&select=*",
                    headers={"apikey": _ctl_key, "Authorization": f"Bearer {_ctl_key}"},
                    timeout=10,
                )
                _rows = _r.json() if _r.status_code == 200 else []
            except Exception as _e:
                st.error(f"Could not reach the control plane: {_e}")
                st.stop()

            if not _rows:
                st.error(f"Invalid school code: '{school_code}'")
                st.stop()

            st.session_state.school = _rows[0]
                        # --- Stage 3: subscription check ---
            from datetime import datetime as _dt
            _exp = _rows[0].get("expires_at")
            if _exp:
                try:
                    _exp_dt = _dt.fromisoformat(str(_exp).replace("Z", "+00:00"))
                    if _exp_dt < _dt.now(_exp_dt.tzinfo):
                        st.error("🔒 Your school's subscription has expired. Please contact the school office.")
                        st.stop()
                except Exception:
                    pass  # if we can't parse, fail open
            # --- end Stage 3 ---
            st.success(f"Found: {_rows[0].get('school_name', school_code)}")

            # --- Stage 2.5: Build the school's own Supabase client ---
            try:
                from supabase import create_client as _create
                _school_client = _create(
                    _rows[0]["supabase_url"],
                    _rows[0]["supabase_key"]
                )
            except Exception as _e:
                st.error(f"Could not connect to your school's database: {_e}")
                st.stop()
            # --- end Stage 2.5 ---

            user = authenticate_user(username, password, client=_school_client)
            if user:
                st.session_state.school_client = _school_client
                valid_role = (
                    (role == "Administrator" and user["role"] == "admin")
                    or (role == "Teacher" and user["role"] == "teacher")
                    or (role == "Student" and user["role"] == "student")
                    or (role == "Parent" and user["role"] == "parent")
                    or (role == "Clerk" and user["role"] == "clerk")
                    or (role == "Exams Officer" and user["role"] == "exams")
                    or (role == "IT Officer" and user["role"] == "it_officer")
                )
                if not valid_role:
                    user = None
            if user:
                st.session_state.logged_in = True
                st.session_state.user_role = user["role"]
                st.session_state.username = user["username"]
                st.session_state.student_name = user.get("student_name", "")
                st.rerun()
            else:
                st.error("Incorrect username, password, or role.")

        st.caption("Please sign in with your account credentials.")
        st.info("All accounts are stored securely in Supabase with hashed passwords.")

    st.stop()


if not st.session_state.logged_in:
    login_screen()


# ============================================================
# SIDEBAR
# ============================================================

st.sidebar.title("Academic System")
st.session_state.school_name = st.sidebar.text_input(
    "School name", value=st.session_state.school_name
)
st.sidebar.caption("School branding can be completed in Settings.")

if st.session_state.user_role in ["admin", "exams"]:
    uploaded = st.sidebar.file_uploader(
        "Upload student Excel file", type=["xlsx", "xls"]
    )    
else:
    uploaded = None

if uploaded:
    try:
        raw = pd.read_excel(uploaded)
        _, _, _, detected_terms, _ = detect_columns(raw)
        if detected_terms:
            selected_term = st.sidebar.selectbox(
                "Analysis term", detected_terms, index=len(detected_terms) - 1
            )
            if st.sidebar.button("Load / Analyse Results", type="primary", use_container_width=True):
                st.session_state.raw_data = raw.copy()
                st.session_state.data = prepare_data(raw, selected_term)
                st.session_state.raw_file_name = uploaded.name
                save_results_store(raw)
                st.rerun()
        else:
            st.sidebar.error("No term columns were detected.")
    except Exception as exc:
        st.sidebar.error(f"Excel error: {exc}")


# ============================================================
# AUTO-LOAD SAVED RESULTS FROM SUPABASE
# ============================================================

if st.session_state.data is None:
    persisted = load_results_store()
    if persisted is not None and not persisted.empty:
        try:
            _, _, _, detected_terms, _ = detect_columns(persisted)
            if detected_terms:
                term_for_role = detected_terms[-1]
                st.session_state.raw_data = persisted.copy()
                st.session_state.data = prepare_data(persisted, term_for_role)
        except Exception:
            pass




# ============================================================
# DATA ASSIGNMENT
# ============================================================

if st.session_state.data is None:
    # No data loaded yet — admin, teacher, student, or parent
    data = None
    df = pd.DataFrame()
    target = name_col = stream_col = None
else:
    data = st.session_state.data
    df = data["df"]
    target = data["target_rank_col"]
    name_col = data["name_col"]
    stream_col = data["stream_col"]

# ============================================================
# HEADER
# ============================================================

st.markdown(
    f'<div class="app-title">{st.session_state.school_name}</div>',
    unsafe_allow_html=True
)
st.markdown(
    f'<div class="app-subtitle">Academic Management System • V20 • {data["analysis_term"].upper() if data is not None else "Learning Centre"}</div>',
    unsafe_allow_html=True
)


# ============================================================
# NAVIGATION
# ============================================================

if st.session_state.user_role == "it_officer":
    nav_items = ["Dashboard", "📅 Timetable", "🤖 Timetable Advisor", "🤖 AI Advisor", "📊 Teacher Load Report", "Change Password", "Settings", "❓ Help & Guides"]
elif st.session_state.user_role == "clerk":
    nav_items = ["💰 Fee Structure", "💵 Record Payment", "📒 Student Ledger", "📊 Fee Reports", "Change Password", "❓ Help & Guides"]
elif st.session_state.user_role == "exams":
    nav_items = ["Dashboard", "Students", "Student Records", "Academic Results", "Streams", "Master Merit List", "Analytics", "Reports", "Learning Centre", "Online Tests & Quizzes", "📅 Timetable", "🤖 Timetable Advisor", "🤖 AI Advisor", "📊 Teacher Load Report", "Settings", "❓ Help & Guides"]
elif st.session_state.user_role == "student":
    nav_items = ["My Dashboard", "Learning Centre", "Online Tests & Quizzes", "My Profile", "Change Password", "❓ Help & Guides"]
elif st.session_state.user_role == "parent":
    nav_items = ["Parent Portal", "Change Password", "❓ Help & Guides"]
elif st.session_state.user_role == "teacher":
    nav_items = ["Dashboard", "Students", "Academic Results", "Streams", "Master Merit List", "Reports", "Learning Centre", "Online Tests & Quizzes", "Settings", "❓ Help & Guides"]
else:
    nav_items = ["Dashboard", "Students", "Student Records", "Academic Results", "Streams", "Master Merit List", "Analytics", "Reports", "Learning Centre", "Online Tests & Quizzes", "📅 Timetable", "🤖 Timetable Advisor", "🤖 AI Advisor", "📊 Teacher Load Report", "💰 Fee Structure", "💵 Record Payment", "📒 Student Ledger", "📊 Fee Reports", "Settings", "❓ Help & Guides"]

page = st.sidebar.radio("Navigation", nav_items)
st.sidebar.caption(f"Signed in as: **{st.session_state.user_role.title()}**")



if st.sidebar.button("Sign out", use_container_width=True):
    st.session_state.logged_in = False
    st.session_state.data = None
    st.session_state.user_role = ""
    st.session_state.username = ""
    st.session_state.student_name = ""
    st.session_state.raw_data = None
    st.session_state.pop("school_client", None)
    st.rerun()
    
# ============================================================
# WELCOME SCREEN FOR ADMIN/TEACHER WITH NO DATA
# ============================================================

if st.session_state.data is None and st.session_state.user_role not in ["student", "parent"]:
    SETUP_PAGES_WITHOUT_DATA = {
        "Settings",
        "❓ Help & Guides",
        "Change Password",
        "📅 Timetable",
        "🤖 Timetable Advisor",
        "🤖 AI Advisor",
        "📊 Teacher Load Report",
    }
    if page not in SETUP_PAGES_WITHOUT_DATA:
        st.markdown(
            '<div class="app-title">Welcome to the Academic Management System</div>',
            unsafe_allow_html=True
        )
        st.markdown(
            '<div class="app-subtitle">Upload your student_results.xlsx file from the left menu to begin, '
            'or go to <b>Settings</b> to configure your school first.</div>',
            unsafe_allow_html=True
        )
        st.markdown("### First-time setup")
        st.write("1. **Set up your school** — go to **Settings → 🏫 School Profile**.")
        st.write("2. **Add staff accounts** — go to **Settings → 👨‍🏫 Teacher Accounts**.")
        st.write("3. **Upload students** — use the sidebar file uploader.")
        st.write("4. **Choose analysis term** and click **Load / Analyse Results**.")
        st.write("5. For the Excel format guide, go to **Settings → 📄 Excel Format Guide**.")
        st.stop()


# ============================================================
# PARENT PORTAL
# ============================================================

if page == "Parent Portal":
    st.subheader("👨‍👩‍👧 Parent Portal")
    st.caption("View your child's academic progress, results and reports.")

    parent_profile = get_parent_profile(st.session_state.username)
    if not parent_profile:
        st.error("No parent profile is linked to this account. Please contact the school administrator.")
        st.stop()

    children_raw = [c.strip() for c in (parent_profile.get("child_names") or "").split("|") if c.strip()]
    if not children_raw:
        st.warning("No students are linked to your account. Please contact the school administrator.")
        st.stop()

    if data is None or df is None or df.empty:
        st.warning(
            "No academic results are available yet. Please ask the school administrator "
            "to load the results Excel file first."
        )
        st.write("**Linked names on your account:** " + ", ".join(children_raw))
        st.stop()

    name_lower = df[name_col].astype(str).str.strip().str.lower()
    matched = {}
    for c in children_raw:
        key = c.strip().lower()
        hit = df[name_lower == key]
        if not hit.empty:
            matched[c] = hit.iloc[0]

    if not matched:
        st.warning(
            "The student name(s) linked to your account do not match any student "
            "in the current results. Please contact the school administrator."
        )
        st.write("**Linked names on your account:** " + ", ".join(children_raw))
        st.stop()

    if len(matched) > 1:
        selected_child = st.selectbox("Select child", list(matched.keys()))
    else:
        selected_child = list(matched.keys())[0]

    student = matched[selected_child]
    stream_size = len(df[df[stream_col] == student[stream_col]])

    st.markdown(
        f"""<div class="school-banner">
        <div class="school-name">{student[name_col]}</div>
        <div class="school-subtitle">Stream: {student[stream_col]} &nbsp; • &nbsp;
        {data['analysis_term'].upper()} &nbsp; • &nbsp;
        Academic Year {st.session_state.get('academic_year','')}</div>
        </div>""",
        unsafe_allow_html=True
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Average", f"{float(student[target]):.1f}%")
    c2.metric("Grade", grade(float(student[target])))
    c3.metric("School Rank", f"{int(student['overall_rank'])}/{len(df)}")
    c4.metric("Stream Rank", f"{int(student['stream_rank'])}/{stream_size}")
    c5.metric("Term Change", f"{float(student['term_change']):+.1f}%")

    st.divider()
    left, right = st.columns(2)
    with left:
        st.markdown("### 📈 Academic progression")
        st.pyplot(progression_figure(student, data), use_container_width=True)
    with right:
        st.markdown("### 📚 Subject performance")
        st.pyplot(subject_figure(student, data), use_container_width=True)

    st.markdown("### 📅 Term-by-term performance")
    term_rows = []
    for term, avg_col in zip(data["target_terms"], data["avg_cols"]):
        s = float(student[avg_col])
        term_rows.append({"Term": term.upper(), "Average": s, "Grade": grade(s)})
    st.dataframe(pd.DataFrame(term_rows).round(1), use_container_width=True, hide_index=True)

    st.markdown("### 📊 Subject results")
    sdf = df[df[stream_col] == student[stream_col]]
    rows = []
    for subject in data["subject_cols"]:
        s = float(student[subject])
        mean = float(sdf[subject].mean())
        rows.append({
            "Subject": clean_label(subject),
            "Score": s,
            "Grade": grade(s),
            "Stream Mean": mean,
            "Difference": s - mean,
        })
    st.dataframe(pd.DataFrame(rows).round(1), use_container_width=True, hide_index=True)

    st.markdown("### 📄 Report card")
    key = str(student[name_col])
    class_comment = st.session_state.get("teacher_comments", {}).get(key, "")
    pdf = generate_student_pdf(
        student, data, st.session_state.school_name,
        class_comment=class_comment,
        report_date=st.session_state.get("report_issue_date", date.today())
    )
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(student[name_col])).strip("_")
    st.download_button(
        "⬇️ Download Report Card (PDF)",
        data=pdf.getvalue(),
        file_name=f"{safe}_Report_Card.pdf",
        mime="application/pdf",
        use_container_width=True
    )

    try:
        anns = [m for m in get_materials() if m.get("material_type") == "Announcement"]
        if anns:
            st.markdown("### 📢 School announcements")
            for m in sorted(anns, key=lambda x: x.get("created_at", ""), reverse=True)[:5]:
                with st.container(border=True):
                    st.markdown(f"**{m['title']}**")
                    if m.get("description"):
                        st.write(m["description"])
                    st.caption(f"Posted {m.get('created_at','')}")
    except Exception:
        pass

    # ============================================================
    # 💰 FEE STATUS (Parent view — current term focus)
    # ============================================================
    st.divider()
    st.markdown("### 💰 Fee Status")
    st.caption("Your child's fee balance and payment history.")

    try:
        _student_name = str(student[name_col])
        _student_stream = str(student[stream_col])
        _allocated = get_allocated_ledger(_student_name, _student_stream)

        if _allocated["total_expected"] == 0 and _allocated["total_paid"] == 0:
            st.info("No fee structure has been set for your child's stream yet. Please contact the school.")
        else:
            # ---- CURRENT TERM FOCUS ----
            current_term = get_current_term()

            # Find the current term's row in the allocated ledger
            current_row = None
            for r in _allocated["rows"]:
                if r["term"] == current_term:
                    current_row = r
                    break

            # If current term not found, use the first term with a balance
            if current_row is None:
                for r in _allocated["rows"]:
                    if r["balance"] > 0:
                        current_row = r
                        break
            if current_row is None and _allocated["rows"]:
                current_row = _allocated["rows"][0]

            if current_row:
                st.markdown(f"#### 📌 Current Term: {current_row['term'].upper()}")
                cc1, cc2, cc3 = st.columns(3)
                cc1.metric("Term Fee", f"KSh {current_row['expected']:,.0f}")
                cc2.metric("Paid (this term)", f"KSh {current_row['allocated']:,.0f}")
                bal_current = current_row["balance"]
                cc3.metric(
                    "Balance (this term)",
                    f"KSh {bal_current:,.0f}",
                    delta=None if bal_current == 0 else ("Settled ✅" if bal_current <= 0 else "Outstanding")
                )

                if bal_current <= 0 and current_row["expected"] > 0:
                    st.success("✅ This term's fees are fully paid. Thank you.")
                elif bal_current > 0:
                    st.warning(f"⚠️ You have KSh {bal_current:,.0f} outstanding for {current_row['term'].upper()}.")
            else:
                st.info("No current term fee structure set. Please contact the school.")

            # ---- FULL YEAR SUMMARY (secondary) ----
            st.divider()
            st.markdown("#### 📊 Full Year Summary")
            st.caption("Overview across all terms (for reference).")

            fs1, fs2, fs3 = st.columns(3)
            fs1.metric("Total Expected (all terms)", f"KSh {_allocated['total_expected']:,.0f}")
            fs2.metric("Total Paid", f"KSh {_allocated['total_paid']:,.0f}")
            total_bal = _allocated["total_balance"]
            fs3.metric(
                "Total Outstanding",
                f"KSh {total_bal:,.0f}",
                delta=None if total_bal == 0 else ("Credit" if total_bal < 0 else "")
            )

            if _allocated["credit"] > 0:
                st.info(f"💰 **Credit balance:** KSh {_allocated['credit']:,.0f} — this will apply to next term's fees.")

            # ---- TERM-BY-TERM BREAKDOWN ----
            st.divider()
            st.markdown("#### 📅 Term-by-Term Breakdown")
            st.caption("Payments are automatically applied to the earliest unpaid term.")

            term_rows = []
            for r in _allocated["rows"]:
                is_current = (r["term"] == current_term)
                term_rows.append({
                    "Term": r["term"].upper() + (" ⬅ current" if is_current else ""),
                    "Expected (KSh)": f"{r['expected']:,.0f}",
                    "Allocated (KSh)": f"{r['allocated']:,.0f}",
                    "Balance (KSh)": f"{r['balance']:,.0f}",
                    "Status": r["status"],
                })
            st.dataframe(pd.DataFrame(term_rows), use_container_width=True, hide_index=True)

            # ---- PAYMENT HISTORY ----
            st.divider()
            st.markdown("#### 📜 Payment History")
            payments = _allocated.get("rows", [])  # placeholder — we'll fetch from ledger
            payments = get_fee_payments(student_name=_student_name)
            if not payments:
                st.info("No payments recorded yet.")
            else:
                pay_rows = []
                for p in payments:
                    pay_rows.append({
                        "Date": p.get("payment_date", ""),
                        "Term": (p.get("term") or "").upper(),
                        "Amount (KSh)": f"{float(p.get('amount', 0)):,.0f}",
                        "Method": p.get("payment_method", ""),
                        "Reference": p.get("reference", ""),
                    })
                st.dataframe(pd.DataFrame(pay_rows), use_container_width=True, hide_index=True)

            # ---- DOWNLOAD STATEMENT ----
            st.divider()
            st.markdown("#### 📄 Download Statement")
            if st.button("📥 Prepare Fee Statement (CSV)", type="primary", key="parent_fee_stmt"):
                statement_rows = []
                statement_rows.append(["Student", _student_name])
                statement_rows.append(["Stream", _student_stream])
                statement_rows.append([])
                statement_rows.append(["Term", "Expected", "Allocated", "Balance"])
                for r in _allocated["rows"]:
                    statement_rows.append([
                        r["term"].upper(),
                        r["expected"],
                        r["allocated"],
                        r["balance"]
                    ])
                statement_rows.append([])
                statement_rows.append(["TOTAL EXPECTED", _allocated["total_expected"]])
                statement_rows.append(["TOTAL PAID", _allocated["total_paid"]])
                statement_rows.append(["TOTAL BALANCE", _allocated["total_balance"]])
                statement_rows.append([])
                statement_rows.append(["Date", "Term", "Amount", "Method", "Reference"])
                for p in payments:
                    statement_rows.append([
                        p.get("payment_date", ""),
                        (p.get("term") or "").upper(),
                        float(p.get("amount", 0)),
                        p.get("payment_method", ""),
                        p.get("reference", ""),
                    ])

                csv_df = pd.DataFrame(statement_rows)
                csv_bytes = csv_df.to_csv(index=False, header=False).encode("utf-8")
                safe_student = re.sub(r"[^A-Za-z0-9_-]+", "_", _student_name).strip("_")
                st.download_button(
                    "⬇️ Download Fee Statement (CSV)",
                    data=csv_bytes,
                    file_name=f"Fee_Statement_{safe_student}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="parent_fee_dl"
                )
    except Exception as e:
        st.warning(f"Fee information is not available yet: {e}")
    


# ============================================================
# STUDENT DASHBOARD
# ============================================================

if page == "My Dashboard":
    st.subheader("🎓 My Academic Dashboard")

    student_profile = get_student_profile(st.session_state.username)
    if not student_profile:
        st.error("No student record is linked to this account. Please contact the school administrator.")
        st.stop()

    linked_name = (student_profile.get("student_full_name") or "").strip()
    if not linked_name:
        st.warning("Your account is not yet linked to a student name. Please contact the school administrator.")
        st.stop()

    if data is None or df is None or df.empty:
        st.warning("No academic results are available yet. Please check back later.")
        st.stop()

    name_lower = df[name_col].astype(str).str.strip().str.lower()
    hit = df[name_lower == linked_name.lower()]
    if hit.empty:
        st.warning(
            "Your linked student name does not match any student in the current results. "
            "Please contact the school administrator."
        )
        st.write(f"**Linked name on your account:** {linked_name}")
        st.stop()

    student = hit.iloc[0]
    stream_size = len(df[df[stream_col] == student[stream_col]])

    st.markdown(
        f"""<div class="school-banner">
        <div class="school-name">{student[name_col]}</div>
        <div class="school-subtitle">Stream: {student[stream_col]} &nbsp; • &nbsp;
        {data['analysis_term'].upper()} &nbsp; • &nbsp;
        Academic Year {st.session_state.get('academic_year','')}</div>
        </div>""",
        unsafe_allow_html=True
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Average", f"{float(student[target]):.1f}%")
    c2.metric("Grade", grade(float(student[target])))
    c3.metric("School Rank", f"{int(student['overall_rank'])}/{len(df)}")
    c4.metric("Stream Rank", f"{int(student['stream_rank'])}/{stream_size}")
    c5.metric("Term Change", f"{float(student['term_change']):+.1f}%")

    st.divider()
    left, right = st.columns(2)
    with left:
        st.markdown("### 📈 Academic progression")
        st.pyplot(progression_figure(student, data), use_container_width=True)
    with right:
        st.markdown("### 📚 Subject performance")
        st.pyplot(subject_figure(student, data), use_container_width=True)

    st.markdown("### 📅 Term-by-term performance")
    term_rows = []
    for term, avg_col in zip(data["target_terms"], data["avg_cols"]):
        s = float(student[avg_col])
        term_rows.append({"Term": term.upper(), "Average": s, "Grade": grade(s)})
    st.dataframe(pd.DataFrame(term_rows).round(1), use_container_width=True, hide_index=True)

    st.markdown("### 📊 Subject results")
    sdf = df[df[stream_col] == student[stream_col]]
    rows = []
    for subject in data["subject_cols"]:
        s = float(student[subject])
        mean = float(sdf[subject].mean())
        rows.append({
            "Subject": clean_label(subject),
            "Score": s,
            "Grade": grade(s),
            "Stream Mean": mean,
            "Difference": s - mean,
        })
    st.dataframe(pd.DataFrame(rows).round(1), use_container_width=True, hide_index=True)

    st.markdown("### 📄 Report card")
    key = str(student[name_col])
    class_comment = st.session_state.get("teacher_comments", {}).get(key, "")
    pdf = generate_student_pdf(
        student, data, st.session_state.school_name,
        class_comment=class_comment,
        report_date=st.session_state.get("report_issue_date", date.today())
    )
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(student[name_col])).strip("_")
    st.download_button(
        "⬇️ Download My Report Card (PDF)",
        data=pdf.getvalue(),
        file_name=f"{safe}_Report_Card.pdf",
        mime="application/pdf",
        use_container_width=True
    )

    st.stop()


# ============================================================
# DASHBOARD (admin/teacher)
# ============================================================

if page == "Dashboard":
    stats = school_statistics(data)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Students", stats["students"])
    c2.metric("Streams", stats["streams"])
    c3.metric("School Mean", f"{stats['mean']:.1f}%")
    c4.metric("Highest", f"{stats['highest']:.1f}%")
    c5.metric("Pass Rate", f"{stats['pass_rate']:.1f}%")

    st.divider()
    left, right = st.columns(2)

    with left:
        st.subheader("School performance trend")
        term_means = [df[c].mean() for c in data["avg_cols"]]
        trend = pd.DataFrame({
            "Term": [x.upper() for x in data["target_terms"]],
            "Average": term_means
        }).set_index("Term")
        st.line_chart(trend)

    with right:
        st.subheader("Student performance bands")
        bands = pd.cut(
            df[target],
            bins=[0, 39.99, 49.99, 59.99, 69.99, 79.99, 100],
            labels=["0–39", "40–49", "50–59", "60–69", "70–79", "80–100"]
        ).value_counts().sort_index()
        st.bar_chart(bands)

    st.subheader("Top 10 students")
    top = df.sort_values("overall_rank").head(10)
    top_view = top[[name_col, stream_col, "overall_rank", "stream_rank", target, "term_change"]].copy()
    top_view.columns = ["Student", "Stream", "School Rank", "Stream Rank", "Final Average", "Change"]
    top_view["Grade"] = top_view["Final Average"].apply(grade)
    st.dataframe(top_view.round(1), use_container_width=True, hide_index=True)


# ============================================================
# STUDENTS
# ============================================================

elif page == "Students":
    st.subheader("Student Profiles & Reports")
    st.caption("Search a student, review academic progress, compare subjects, and print the individual report.")

    f1, f2 = st.columns([1.4, 1])
    with f1:
        query = st.text_input("🔎 Search student name", placeholder="Type part of a student's name")
    with f2:
        stream_filter = st.selectbox("Filter by stream", ["ALL STREAMS"] + sorted(df[stream_col].unique().tolist()))

    filtered = df.copy()
    if stream_filter != "ALL STREAMS":
        filtered = filtered[filtered[stream_col] == stream_filter]

    names = filtered[name_col].astype(str).tolist()
    matches = [n for n in names if query.lower() in n.lower()] if query else names

    if not matches:
        st.warning("No matching students found. Try another name or stream.")
        st.stop()

    selected = st.selectbox("Select student", matches)
    student = filtered[filtered[name_col].astype(str) == selected].iloc[0]
    stream_size = len(df[df[stream_col] == student[stream_col]])

    st.markdown(
        f"""<div class="school-banner">
        <div class="school-name">{selected}</div>
        <div class="school-subtitle">Stream: {student[stream_col]} &nbsp; • &nbsp; {data['analysis_term'].upper()} &nbsp; • &nbsp; Academic Year {st.session_state.get('academic_year','')}</div>
        </div>""", unsafe_allow_html=True
    )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Final Average", f"{student[target]:.1f}%")
    c2.metric("Grade", grade(float(student[target])))
    c3.metric("School Rank", f"{int(student['overall_rank'])}/{len(df)}")
    c4.metric("Stream Rank", f"{int(student['stream_rank'])}/{stream_size}")
    c5.metric("Term Change", f"{student['term_change']:+.1f}%")

    st.divider()
    left, right = st.columns(2)
    with left:
        st.markdown("### 📈 Academic progression")
        st.pyplot(progression_figure(student, data), use_container_width=True)
    with right:
        st.markdown("### 📚 Subject performance")
        st.pyplot(subject_figure(student, data), use_container_width=True)

    st.markdown("### 📅 Term-by-term performance")
    term_rows = []
    for term, avg_col in zip(data["target_terms"], data["avg_cols"]):
        score = float(student[avg_col])
        term_rows.append({"Term": term.upper(), "Average": score, "Grade": grade(score)})
    history = pd.DataFrame(term_rows)
    st.dataframe(history.round(1), use_container_width=True, hide_index=True)

    st.markdown("### 📊 Detailed subject analysis")
    sdf = df[df[stream_col] == student[stream_col]]
    subject_rows = []
    for subject in data["subject_cols"]:
        score = float(student[subject])
        mean = float(sdf[subject].mean())
        diff = score - mean
        subject_rows.append({
            "Subject": clean_label(subject),
            "Student Score": score,
            "Grade": grade(score),
            "Stream Mean": mean,
            "Difference": diff,
            "Status": "Above stream mean" if diff >= 0 else "Below stream mean",
        })
    subject_df = pd.DataFrame(subject_rows)
    st.dataframe(subject_df.round(1), use_container_width=True, hide_index=True)

    if not subject_df.empty:
        strongest = subject_df.sort_values("Student Score", ascending=False).iloc[0]
        weakest = subject_df.sort_values("Student Score", ascending=True).iloc[0]
        above = int((subject_df["Difference"] >= 0).sum())
        a, b, c = st.columns(3)
        a.info(f"**Strongest subject:** {strongest['Subject']} — {strongest['Student Score']:.1f}%")
        b.info(f"**Needs most attention:** {weakest['Subject']} — {weakest['Student Score']:.1f}%")
        c.info(f"**Above stream mean:** {above} of {len(subject_df)} subjects")

    st.markdown("### 📝 Report card comments")
    student_key = str(student[data["name_col"]])
    safe_student_key = re.sub(r'[^A-Za-z0-9]', '_', student_key)
    existing_comment = st.session_state.get("teacher_comments", {}).get(student_key, "")
    current_score = float(student[data["target_rank_col"]])
    automatic_comment = _overall_comment(current_score)

    comment_mode = st.radio(
        "How should the Class Teacher comment be prepared?",
        ["Automatic performance comment", "Choose prepared comment", "Type manually"],
        horizontal=True,
        key=f"comment_mode_{safe_student_key}"
    )

    if comment_mode == "Automatic performance comment":
        default_comment = existing_comment or automatic_comment
        st.info("A comment has been prepared from the student's performance. You can edit it before saving.")
        teacher_comment = st.text_area(
            "Class Teacher Comment",
            value=default_comment,
            height=100,
            key=f"teacher_comment_auto_{safe_student_key}"
        )
    elif comment_mode == "Choose prepared comment":
        prepared = st.selectbox(
            "Select a prepared comment",
            PREPARED_TEACHER_COMMENTS,
            key=f"prepared_comment_{safe_student_key}"
        )
        teacher_comment = st.text_area(
            "Class Teacher Comment",
            value=existing_comment or prepared,
            height=100,
            key=f"teacher_comment_prepared_{safe_student_key}"
        )
    else:
        teacher_comment = st.text_area(
            "Class Teacher Comment",
            value=existing_comment,
            placeholder="Enter the class teacher's official comment for this student...",
            height=100,
            key=f"teacher_comment_manual_{safe_student_key}"
        )

    if st.button("💾 Save Student Comment", type="secondary", key=f"save_comment_{safe_student_key}"):
        st.session_state.teacher_comments[student_key] = teacher_comment.strip()
        st.success("Class teacher comment saved for this student.")

    st.markdown("### 📅 Report issue date")
    st.caption("Choose the date that should appear below the teacher and principal signatures.")
    report_date = st.date_input(
        "Report date",
        value=st.session_state.get("report_issue_date", date.today()),
        key=f"report_date_{re.sub(r'[^A-Za-z0-9]', '_', student_key)}"
    )
    st.session_state.report_issue_date = report_date

    st.markdown("### 📄 Student report")
    pdf = generate_student_pdf(
        student, data, st.session_state.school_name,
        st.session_state.get("teacher_comments", {}).get(student_key, teacher_comment),
        report_date=report_date
    )
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", selected).strip("_")
    st.download_button(
        "⬇️ Download Individual PDF Report",
        data=pdf.getvalue(),
        file_name=f"Student_{safe_name}_Report.pdf",
        mime="application/pdf",
        use_container_width=True,
    )

# ============================================================
# STUDENT RECORDS
# ============================================================

elif page == "Student Records":
    st.subheader("👥 Student Records & Data Management")
    st.caption("Add, edit, remove and export student records. Changes are saved to the cloud.")

    raw_df = st.session_state.get("raw_data")
    if raw_df is None or raw_df.empty:
        st.warning("No editable student data is loaded. Upload your Excel file first.")
        st.stop()

    working = raw_df.copy()
    _, raw_name_col, raw_stream_col, raw_terms, raw_avg_cols = detect_columns(working)
    admission_candidates = [
        c for c in working.columns
        if any(k in str(c).lower() for k in ["admission", "adm", "student id", "student_id", "id", "reg no", "registration"])
    ]
    admission_col = admission_candidates[0] if admission_candidates else None

    tab_edit, tab_add, tab_delete, tab_export = st.tabs(["✏️ Edit Student", "➕ Add Student", "🗑️ Remove Student", "📥 Save / Export"])

    with tab_edit:
        edit_names = working[raw_name_col].astype(str).tolist()
        edit_name = st.selectbox("Select student to edit", edit_names, key="record_edit_student")
        edit_idx = working.index[working[raw_name_col].astype(str) == edit_name].tolist()[0]
        current = working.loc[edit_idx]

        e1, e2 = st.columns(2)
        with e1:
            new_name = st.text_input("Student name", value=str(current[raw_name_col]), key="record_edit_name")
            stream_options = sorted(working[raw_stream_col].astype(str).unique().tolist())
            current_stream = str(current[raw_stream_col])
            if current_stream not in stream_options:
                stream_options.append(current_stream)
            new_stream = st.selectbox("Stream", stream_options, index=stream_options.index(current_stream), key="record_edit_stream")
        with e2:
            if admission_col:
                new_admission = st.text_input("Admission / Student ID", value=str(current[admission_col]), key="record_edit_admission")
            else:
                new_admission = None

        st.markdown("### Term averages")
        avg_inputs = {}
        avg_cols_unique = []
        for col in raw_avg_cols:
            if col and col not in avg_cols_unique:
                avg_cols_unique.append(col)
        avg_grid = st.columns(3)
        for i, col in enumerate(avg_cols_unique):
            try:
                val = float(current[col])
            except Exception:
                val = 0.0
            val = max(0.0, min(100.0, val))
            avg_inputs[col] = avg_grid[i % 3].number_input(
                str(col).upper(), min_value=0.0, max_value=100.0,
                value=val, step=0.1, key=f"record_avg_{edit_idx}_{col}"
            )

        if st.button("💾 Save Student Changes", type="primary", use_container_width=True, key="save_student_changes"):
            working.loc[edit_idx, raw_name_col] = new_name.strip() or str(current[raw_name_col])
            working.loc[edit_idx, raw_stream_col] = new_stream.strip().upper()
            if admission_col:
                working.loc[edit_idx, admission_col] = new_admission.strip()
            for col, val in avg_inputs.items():
                working.loc[edit_idx, col] = val
            st.session_state.raw_data = working
            st.session_state.data = prepare_data(working, data["analysis_term"])
            save_results_store(working)
            st.success(f"Updated {new_name.strip() or edit_name}. Saved to cloud.")
            st.rerun()

    with tab_add:
        st.markdown("### Add a new student")
        a1, a2 = st.columns(2)
        with a1:
            add_name = st.text_input("Student name", key="add_student_name")
            existing_streams = sorted(working[raw_stream_col].astype(str).unique().tolist())
            add_stream = st.selectbox("Stream", existing_streams, key="add_student_stream") if existing_streams else st.text_input("Stream", key="add_student_stream_text")
        with a2:
            add_admission = st.text_input("Admission / Student ID (optional)", key="add_student_admission")
        st.markdown("### Initial term averages")
        add_values = {}
        add_grid = st.columns(3)
        for i, col in enumerate(avg_cols_unique):
            add_values[col] = add_grid[i % 3].number_input(
                str(col).upper(), min_value=0.0, max_value=100.0,
                value=0.0, step=0.1, key=f"add_avg_{col}"
            )
        if st.button("➕ Add Student", type="primary", use_container_width=True, key="add_student_button"):
            if not add_name.strip():
                st.error("Enter the student's name first.")
            else:
                new_row = {c: np.nan for c in working.columns}
                new_row[raw_name_col] = add_name.strip()
                new_row[raw_stream_col] = str(add_stream).strip().upper()
                for col, val in add_values.items():
                    new_row[col] = val
                if admission_col and add_admission.strip():
                    new_row[admission_col] = add_admission.strip()
                working = pd.concat([working, pd.DataFrame([new_row])], ignore_index=True)
                st.session_state.raw_data = working
                st.session_state.data = prepare_data(working, data["analysis_term"])
                save_results_store(working)
                st.success(f"Added {add_name.strip()} and saved to cloud.")
                st.rerun()

    with tab_delete:
        st.markdown("### Remove a student")
        delete_name = st.selectbox("Select student to remove", working[raw_name_col].astype(str).tolist(), key="delete_student_name")
        st.warning("Removing a student changes the working data.")
        confirm_delete = st.checkbox("I understand this student will be removed.", key="confirm_delete_student")
        if st.button("🗑️ Remove Student", type="secondary", disabled=not confirm_delete, use_container_width=True, key="remove_student_button"):
            working = working[working[raw_name_col].astype(str) != delete_name].copy()
            st.session_state.raw_data = working
            st.session_state.data = prepare_data(working, data["analysis_term"])
            save_results_store(working)
            st.success(f"Removed {delete_name}.")
            st.rerun()

    with tab_export:
        st.markdown("### Save your updated records")
        st.info("Download the updated Excel file to keep a local backup.")
        st.write(f"**Current students:** {len(working)}")
        st.write(f"**Current streams:** {working[raw_stream_col].nunique()}")
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            working.to_excel(writer, index=False, sheet_name="Student Results")
        excel_buffer.seek(0)
        export_name = f"Updated_Student_Records_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        st.download_button(
            "⬇️ Download Updated Excel Records",
            data=excel_buffer.getvalue(),
            file_name=export_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True
        )
        st.markdown("### Current records")
        st.dataframe(working, use_container_width=True, hide_index=True)


# ============================================================
# ACADEMIC RESULTS
# ============================================================

elif page == "Academic Results":
    st.subheader("📝 Academic Results Entry & Editing")
    st.caption("Enter or correct subject marks. Changes are saved to the cloud.")

    raw_df = st.session_state.get("raw_data")
    if raw_df is None or raw_df.empty:
        st.warning("No student data is loaded. Upload your Excel file first.")
        st.stop()

    working = raw_df.copy()
    _, raw_name_col, raw_stream_col, raw_terms, raw_avg_cols = detect_columns(working)
    if not raw_terms:
        st.error("No term columns were detected.")
        st.stop()

    term_choice = st.selectbox(
        "📅 Select term to edit",
        raw_terms,
        index=raw_terms.index(data["analysis_term"]) if data["analysis_term"] in raw_terms else len(raw_terms) - 1,
        format_func=lambda x: x.upper(),
    )

    avg_col = raw_avg_cols[raw_terms.index(term_choice)]
    term_subjects = [
        c for c in working.columns
        if term_choice in str(c).lower()
        and c != avg_col
        and "avg" not in str(c).lower()
        and "total" not in str(c).lower()
        and c not in [raw_name_col, raw_stream_col]
    ]
    term_subjects = [
        c for c in term_subjects
        if pd.to_numeric(working[c], errors="coerce").notna().any()
    ]

    if not term_subjects:
        st.warning(f"No subject columns were detected for {term_choice.upper()}.")
        st.stop()

    result_names = working[raw_name_col].astype(str).tolist()
    selected_result_student = st.selectbox("👤 Select student", result_names, key="results_student_select")
    idx = working.index[working[raw_name_col].astype(str) == selected_result_student].tolist()[0]
    current = working.loc[idx]
    st.metric("Stream", str(current[raw_stream_col]))
    st.markdown(f"### {selected_result_student} — {term_choice.upper()}")

    score_inputs = {}
    grid = st.columns(3)
    for i, col in enumerate(term_subjects):
        value = pd.to_numeric(current[col], errors="coerce")
        value = 0.0 if pd.isna(value) else float(value)
        value = max(0.0, min(100.0, value))
        score_inputs[col] = grid[i % 3].number_input(
            clean_label(col), min_value=0.0, max_value=100.0, value=value, step=1.0,
            key=f"result_score_{idx}_{term_choice}_{col}",
        )

    proposed_total, maximum_marks, proposed_average = result_summary(score_inputs.values())
    a, b, c, d = st.columns(4)
    a.metric("Total Marks", f"{proposed_total:.1f} / {maximum_marks}")
    b.metric("Percentage / Average", f"{proposed_average:.1f}%")
    c.metric("Overall Grade", grade(proposed_average))
    old_avg = pd.to_numeric(current[avg_col], errors="coerce")
    old_avg = 0.0 if pd.isna(old_avg) else float(old_avg)
    d.metric("Previous Average", f"{old_avg:.1f}%")

    if st.button("💾 Save Academic Results", type="primary", use_container_width=True, key="save_academic_results"):
        for col, value in score_inputs.items():
            working.loc[idx, col] = value
        working.loc[idx, avg_col] = proposed_average
        st.session_state.raw_data = working
        st.session_state.data = prepare_data(working, data["analysis_term"])
        save_results_store(working)
        st.success(f"Saved {term_choice.upper()} results. Average: {proposed_average:.1f}%. Saved to cloud.")
        st.rerun()

    st.markdown("### 📊 Current subject results")
    current_rows = []
    for col in term_subjects:
        raw_score = pd.to_numeric(working.loc[idx, col], errors="coerce")
        score = 0.0 if pd.isna(raw_score) else float(raw_score)
        current_rows.append({"Subject": clean_label(col), "Mark": score})
    st.dataframe(pd.DataFrame(current_rows), use_container_width=True, hide_index=True)
    current_total = sum(row["Mark"] for row in current_rows)
    current_max = len(current_rows) * 100
    current_pct = (current_total / current_max * 100) if current_max else 0.0
    st.markdown(f"**Total Marks:** {current_total:.1f} / {current_max} &nbsp;&nbsp; **Average:** {current_pct:.1f}% &nbsp;&nbsp; **Grade:** {grade(current_pct)}")


# ============================================================
# STREAMS
# ============================================================

elif page == "Streams":
    st.subheader("Stream Management")
    streams = sorted(df[stream_col].unique())
    selected_stream = st.selectbox("Select stream", streams)
    sdf = df[df[stream_col] == selected_stream].copy()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Students", len(sdf))
    c2.metric("Stream Mean", f"{sdf[target].mean():.1f}%")
    c3.metric("Highest", f"{sdf[target].max():.1f}%")
    c4.metric("Pass Rate", f"{(sdf[target] >= 50).mean()*100:.1f}%")

    st.subheader(f"{selected_stream} Merit List")
    view = sdf.sort_values("stream_rank")[
        [name_col, "stream_rank", "overall_rank", target, "term_change"] + data["subject_cols"]
    ].copy()
    view.columns = (
        ["Student", "Stream Rank", "School Rank", "Final Average", "Change"]
        + [clean_label(s) for s in data["subject_cols"]]
    )
    st.dataframe(view.round(1), use_container_width=True, hide_index=True)

    st.subheader("Subject means")
    means = sdf[data["subject_cols"]].mean()
    means.index = [clean_label(x) for x in means.index]
    st.bar_chart(means)


# ============================================================
# MASTER MERIT LIST
# ============================================================

elif page == "Master Merit List":
    st.subheader("🏆 Master School Merit List")
    st.caption(
        f"{st.session_state.school_name} • {data['analysis_term'].upper()} • "
        f"Academic Year {st.session_state.get('academic_year', '')}"
    )

    streams = ["ALL STREAMS"] + sorted(df[stream_col].dropna().astype(str).unique().tolist())
    selected_merit_stream = st.selectbox("Filter by stream", streams, key="master_merit_stream")
    top_n = st.selectbox("Show students", [10, 20, 30, 50, 100, "All"], index=0)

    merit = df.sort_values(["overall_rank", name_col]).copy()
    if selected_merit_stream != "ALL STREAMS":
        merit = merit[merit[stream_col] == selected_merit_stream].copy()

    avg = merit[target].mean() if len(merit) else 0
    highest = merit[target].max() if len(merit) else 0
    pass_rate = (merit[target] >= 50).mean() * 100 if len(merit) else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Students", len(merit))
    c2.metric("Average", f"{avg:.1f}%")
    c3.metric("Highest", f"{highest:.1f}%")
    c4.metric("Pass Rate", f"{pass_rate:.1f}%")

    st.markdown("### 🥇 Top performers")
    top = merit.head(3)
    cols = st.columns(max(1, len(top)))
    for i, (_, row) in enumerate(top.iterrows()):
        with cols[i]:
            st.info(
                f"**#{int(row['overall_rank'])} — {row[name_col]}**\n\n"
                f"{row[stream_col]} • {float(row[target]):.1f}% • Grade {grade(float(row[target]))}"
            )

    st.markdown("### 📋 Official merit list")
    display = merit.head(int(top_n)).copy() if top_n != "All" else merit.copy()
    display = display[["overall_rank", name_col, stream_col, "stream_rank", target, "term_change"]].copy()
    display.columns = ["School Rank", "Student", "Stream", "Stream Rank", "Final Average", "Change"]
    display["Grade"] = display["Final Average"].apply(grade)
    display["Change"] = display["Change"].map(lambda x: f"{x:+.1f}%")
    st.dataframe(display, use_container_width=True, hide_index=True)

    st.markdown("### 📊 Performance distribution")
    band_counts = pd.Series({
        "A (80–100)": int((merit[target] >= 80).sum()),
        "B (70–79)": int(((merit[target] >= 70) & (merit[target] < 80)).sum()),
        "C (60–69)": int(((merit[target] >= 60) & (merit[target] < 70)).sum()),
        "D (50–59)": int(((merit[target] >= 50) & (merit[target] < 60)).sum()),
        "E (<50)": int((merit[target] < 50).sum()),
    })
    st.bar_chart(band_counts)

    if selected_merit_stream == "ALL STREAMS":
        st.markdown("### 🏫 Stream performance comparison")
        stream_summary = (
            df.groupby(stream_col)[target]
            .agg(Students="size", Average="mean", Highest="max")
            .sort_values("Average", ascending=False)
        )
        stream_summary["Pass Rate"] = df.groupby(stream_col)[target].apply(lambda x: (x >= 50).mean() * 100)
        st.dataframe(stream_summary.round(1), use_container_width=True)

    st.markdown("### 📄 Official PDF")
    master_pdf = generate_master_pdf(data, st.session_state.school_name)
    st.download_button(
        "⬇️ Download Complete Master Merit PDF",
        data=master_pdf.getvalue(),
        file_name=f"Master_Merit_{data['analysis_term'].upper()}.pdf",
        mime="application/pdf",
        use_container_width=True
    )


# ============================================================
# ANALYTICS
# ============================================================

elif page == "Analytics":
    st.subheader("Academic Analytics")
    st.info("Correlation measures linear association. It does not prove causation.")

    corr = correlation_table(data)
    st.dataframe(corr.round(3), use_container_width=True, hide_index=True)

    st.subheader("School subject averages")
    means = df[data["subject_cols"]].mean().sort_values(ascending=False)
    means.index = [clean_label(x) for x in means.index]
    st.bar_chart(means)

    st.subheader("Stream average comparison")
    stream_means = df.groupby(stream_col)[target].mean().sort_values(ascending=False)
    st.bar_chart(stream_means)


# ============================================================
# REPORTS
# ============================================================

elif page == "Reports":
    st.subheader("Official Reports")

    if st.button("Generate Master School Report", type="primary"):
        with st.spinner("Generating master report..."):
            pdf = generate_master_pdf(data, st.session_state.school_name)
        st.download_button(
            "Download Master School Report",
            data=pdf.getvalue(),
            file_name="Master_School_Performance_Report.pdf",
            mime="application/pdf",
            use_container_width=True
        )

    st.divider()
    st.subheader("Generate all student report cards")
    st.write(f"This creates {len(df)} individual PDF reports and packages them into one ZIP file.")

    if st.button("Generate ALL Student PDFs"):
        with st.spinner("Generating student reports..."):
            all_reports = generate_all_student_pdfs(data, st.session_state.school_name)
        st.download_button(
            "Download All Student Reports (ZIP)",
            data=all_reports.getvalue(),
            file_name="All_Student_Reports.zip",
            mime="application/zip",
            use_container_width=True
        )

    st.divider()
    st.subheader("Export processed data")
    csv_data = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Processed CSV",
        data=csv_data,
        file_name=f"{data['analysis_term']}_processed_results.csv",
        mime="text/csv",
        use_container_width=True
    )

# ============================================================
# LEARNING CENTRE
# ============================================================

elif page == "Learning Centre":
    st.subheader("📚 Learning Centre")
    st.write("Post assignments, notes and revision materials; students access and submit work.")

    role = st.session_state.user_role
    materials = get_materials()
    all_submissions = get_submissions()

    def lc_status(material, student_name=None):
        if material.get("material_type") != "Assignment":
            return "Material"
        deadline = material.get("deadline", "")
        if student_name:
            previous = get_submissions(material_id=material["id"], student_name=student_name)
            if previous:
                return "Reviewed" if previous[0].get("status") == "Reviewed" else "Submitted"
        if deadline:
            try:
                if datetime.now().date() > datetime.strptime(deadline, "%Y-%m-%d").date():
                    return "Overdue"
            except Exception:
                pass
        return "Pending"

    if role in ("admin", "teacher"):
        assignments = [m for m in materials if m.get("material_type") == "Assignment"]
        pending = sum(1 for s in all_submissions if s.get("status") != "Reviewed")
        overdue = 0
        for m in assignments:
            if m.get("deadline"):
                try:
                    if datetime.now().date() > datetime.strptime(m["deadline"], "%Y-%m-%d").date():
                        overdue += 1
                except Exception:
                    pass

        st.markdown("### 📊 Learning Centre Dashboard")
        a, b, c, d = st.columns(4)
        a.metric("Assignments", len(assignments))
        b.metric("Submissions", len(all_submissions))
        c.metric("Awaiting Review", pending)
        d.metric("Overdue", overdue)

        tab1, tab2, tab3 = st.tabs(["📤 Post Material", "📋 Posted Materials", "📥 Student Submissions"])

        with tab1:
            st.markdown("### Create a new learning resource")
            c1, c2 = st.columns(2)
            with c1:
                title = st.text_input("Title", placeholder="e.g. Algebra Assignment 1")
                mtype = st.selectbox("Material type", ["Assignment", "Notes", "Revision Material", "Announcement", "Past Paper", "Other"])
                subject = st.text_input("Subject", placeholder="e.g. Mathematics")
            with c2:
                streams = ["All Streams"]
                if st.session_state.get("data") is not None:
                    streams += sorted([str(x) for x in st.session_state.data["df"][st.session_state.data["stream_col"]].dropna().unique()])
                target_stream = st.selectbox("Target stream / class", streams)
                deadline = st.date_input("Deadline (optional)", value=None)
                external_link = st.text_input("Video / external resource link (optional)", placeholder="https://...")
            description = st.text_area("Instructions / description", height=100)
            file = st.file_uploader("Attach notes or assignment file (optional)", type=None, key="learning_upload")
            if st.button("📤 Publish to Learning Centre", type="primary", use_container_width=True):
                if not title.strip():
                    st.error("Please enter a title.")
                elif not file and not external_link.strip() and not description.strip():
                    st.error("Add a file, link, or instructions before publishing.")
                else:
                    saved_name = ""
                    saved_path = ""
                    if file is not None:
                        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", file.name)
                        saved_name = safe
                        file_b64 = base64.b64encode(file.getbuffer()).decode('utf-8')
                        saved_path = "BASE64::" + file_b64
                    add_material(title.strip(), mtype, subject.strip(), target_stream,
                                 description.strip(), str(deadline) if deadline else "",
                                 saved_name, saved_path, external_link.strip(), st.session_state.username)
                    st.success("Material published to cloud.")
                    st.rerun()

        with tab2:
            if not materials:
                st.info("No learning materials have been posted yet.")
            for m in materials:
                with st.container(border=True):
                    st.markdown(f"### {m['title']}")
                    st.write(f"**Type:** {m['material_type']}  •  **Subject:** {m['subject'] or 'General'}  •  **Target:** {m['target_stream']}")
                    if m['deadline']:
                        st.write(f"**Deadline:** {m['deadline']}")
                    if m['description']:
                        st.write(m['description'])
                    cols = st.columns([1, 1, 1, 1])
                    if m['file_path'] and str(m['file_path']).startswith("BASE64::"):
                        try:
                            raw = base64.b64decode(m['file_path'][8:])
                            cols[0].download_button("⬇️ Download file", raw, file_name=m['file_name'], key=f"dlm{m['id']}")
                        except Exception:
                            pass
                    if m['external_link']:
                        cols[1].markdown(f"[🔗 Open link]({m['external_link']})")
                    if cols[3].button("🗑️ Delete", key=f"delm{m['id']}"):
                        delete_material(m['id'])
                        st.rerun()
                    st.caption(f"Posted by {m['uploaded_by']} on {m['created_at']}")

        with tab3:
            subs = get_submissions()
            if not subs:
                st.info("No student submissions yet.")
            else:
                sub_df = pd.DataFrame(subs)
                st.dataframe(
                    sub_df[["title", "student_name", "subject", "file_name", "submitted_at", "status", "teacher_feedback"]],
                    use_container_width=True, hide_index=True
                )
                st.markdown("### Give feedback")
                sub_options = {f"{s['student_name']} — {s['title']} — {s['submitted_at']}": s for s in subs}
                selected_label = st.selectbox("Submission", list(sub_options))
                selected = sub_options[selected_label]
                feedback = st.text_area("Teacher feedback", value=selected.get("teacher_feedback", ""), key=f"feedback_{selected['id']}")
                if st.button("Save Feedback", type="primary"):
                    update_quiz_feedback(selected['id'], feedback, 'Reviewed')
                    st.success("Feedback saved.")
                    st.rerun()

    else:
        st.markdown("### 🎓 Student Learning Dashboard")
        student_name = st.session_state.student_name.strip()
        if not student_name:
            sp = get_student_profile(st.session_state.username)
            if sp:
                student_name = (sp.get("student_full_name") or "").strip()
        if not student_name:
            st.warning("Enter the student name used in the academic Excel file.")
            student_name = st.text_input("Student name")

        student_submissions = get_submissions(student_name=student_name) if student_name else []
        student_materials = []
        streams = []
        if st.session_state.get("data") is not None and student_name:
            d = st.session_state.data["df"]
            nc = st.session_state.data["name_col"]
            sc = st.session_state.data["stream_col"]
            matches = d[d[nc].astype(str).str.lower() == student_name.lower()]
            if not matches.empty:
                streams = matches[sc].astype(str).tolist()
        for m in materials:
            if m["target_stream"] == "All Streams" or not streams or m["target_stream"] in streams:
                student_materials.append(m)

        assignments = [m for m in student_materials if m.get("material_type") == "Assignment"]
        submitted_ids = {s.get("material_id") for s in student_submissions}
        pending_count = sum(1 for m in assignments if m.get("id") not in submitted_ids)
        reviewed_count = sum(1 for s in student_submissions if s.get("status") == "Reviewed")

        a, b, c = st.columns(3)
        a.metric("Available Materials", len(student_materials))
        b.metric("Pending Assignments", pending_count)
        c.metric("Feedback Received", reviewed_count)

        announcements = [m for m in student_materials if m.get("material_type") == "Announcement"]
        if announcements:
            st.markdown("### 📢 Announcements")
            for m in sorted(announcements, key=lambda x: x.get("created_at", ""), reverse=True)[:5]:
                with st.container(border=True):
                    st.markdown(f"**{m['title']}**")
                    if m.get("description"):
                        st.write(m["description"])
                    st.caption(f"Posted {m.get('created_at','')}")

        st.markdown("### 📝 Assignment Status")
        if assignments:
            rows = []
            for m in assignments:
                rows.append({
                    "Assignment": m["title"],
                    "Subject": m.get("subject") or "General",
                    "Deadline": m.get("deadline") or "No deadline",
                    "Status": lc_status(m, student_name)
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No assignments available.")

        st.markdown("### 📖 My Learning Materials")
        if not student_materials:
            st.info("No materials available.")
        for m in student_materials:
            with st.container(border=True):
                st.markdown(f"### {m['title']}")
                st.write(f"**{m['material_type']}** • {m['subject'] or 'General'}")
                if m['deadline']:
                    st.write(f"**Deadline:** {m['deadline']}")
                if m['description']:
                    st.write(m['description'])
                cols = st.columns(3)
                if m['file_path'] and str(m['file_path']).startswith("BASE64::"):
                    try:
                        raw = base64.b64decode(m['file_path'][8:])
                        cols[0].download_button("⬇️ Download", raw, file_name=m['file_name'], key=f"stdl{m['id']}")
                    except Exception:
                        pass
                if m['external_link']:
                    cols[1].markdown(f"[🔗 Open resource]({m['external_link']})")
                previous = get_submissions(material_id=m['id'], student_name=student_name)
                if previous:
                    st.success(f"Submitted on {previous[0]['submitted_at']} • {previous[0]['status']}")
                    if previous[0]['teacher_feedback']:
                        st.info(f"Teacher feedback: {previous[0]['teacher_feedback']}")
                upload = st.file_uploader("Submit your work", type=None, key=f"submission_{m['id']}")
                if st.button("📤 Submit Work", key=f"submit_{m['id']}", type="primary"):
                    if upload is None:
                        st.error("Choose your file first.")
                    else:
                        file_b64 = "BASE64::" + base64.b64encode(upload.getbuffer()).decode('utf-8')
                        save_submission(m['id'], student_name.strip(), upload, file_b64)
                        st.success("Work submitted.")
                        st.rerun()


# ============================================================
# ONLINE TESTS & QUIZZES
# ============================================================

elif page == "Online Tests & Quizzes":
    st.subheader("🧪 Online Tests & Quizzes")
    st.write("Create and deliver online tests. Objective questions auto-mark; short answers reviewed by teacher.")

    role = st.session_state.user_role
    quizzes = get_quizzes()

    def student_streams_for(name):
        streams = []
        if st.session_state.get("data") is not None and name:
            d = st.session_state.data["df"]
            nc = st.session_state.data["name_col"]
            sc = st.session_state.data["stream_col"]
            matches = d[d[nc].astype(str).str.lower() == name.lower()]
            if not matches.empty:
                streams = matches[sc].astype(str).tolist()
        return streams

    if role in ("admin", "teacher"):
        attempts = get_attempts()
        st.markdown("### 📊 Quiz Dashboard")
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Quizzes", len(quizzes))
        q2.metric("Attempts", len(attempts))
        q3.metric("Reviewed", sum(1 for a in attempts if a.get("status") == "Reviewed"))
        q4.metric("Awaiting Review", sum(1 for a in attempts if a.get("status") != "Reviewed"))

        create_tab, manage_tab, results_tab = st.tabs(["➕ Create Quiz", "📋 Manage Quizzes", "📊 Student Results"])

        with create_tab:
            c1, c2 = st.columns(2)
            with c1:
                qtitle = st.text_input("Quiz title", placeholder="e.g. Mathematics Test 1")
                qsubject = st.text_input("Subject", placeholder="e.g. Mathematics")
                qdesc = st.text_area("Instructions / description", height=90)
            with c2:
                streams = ["All Streams"]
                if st.session_state.get("data") is not None:
                    streams += sorted([str(x) for x in st.session_state.data["df"][st.session_state.data["stream_col"]].dropna().unique()])
                qstream = st.selectbox("Target stream / class", streams, key="quiz_stream")
                qdeadline = st.date_input("Closing date (optional)", value=None, key="quiz_deadline")
                qduration = st.number_input("Time limit (minutes)", min_value=1, max_value=300, value=30, step=5)
            n_questions = st.number_input("Number of questions", min_value=1, max_value=30, value=5, step=1)
            questions = []
            for i in range(1, int(n_questions) + 1):
                with st.container(border=True):
                    st.markdown(f"**Question {i}**")
                    text_q = st.text_area("Question", key=f"vq_text_{i}", height=70)
                    typ = st.selectbox("Question type", ["Multiple Choice", "True / False", "Short Answer"], key=f"vq_type_{i}")
                    pts = st.number_input("Marks", min_value=0.5, max_value=100.0, value=1.0, step=0.5, key=f"vq_pts_{i}")
                    q = {"text": text_q.strip(), "type": typ, "points": pts}
                    if typ == "Multiple Choice":
                        aa, bb = st.columns(2)
                        with aa:
                            q["a"] = st.text_input("Option A", key=f"vq_a_{i}")
                            q["c"] = st.text_input("Option C", key=f"vq_c_{i}")
                        with bb:
                            q["b"] = st.text_input("Option B", key=f"vq_b_{i}")
                            q["d"] = st.text_input("Option D", key=f"vq_d_{i}")
                        q["correct"] = st.selectbox("Correct answer", ["A", "B", "C", "D"], key=f"vq_correct_{i}")
                    elif typ == "True / False":
                        q["correct"] = st.selectbox("Correct answer", ["True", "False"], key=f"vq_tf_{i}")
                    else:
                        q["correct"] = ""
                    questions.append(q)
            if st.button("🚀 Publish Quiz", type="primary", use_container_width=True):
                if not qtitle.strip():
                    st.error("Enter a quiz title.")
                elif any(not q["text"] for q in questions):
                    st.error("Every question must have text.")
                else:
                    add_quiz(qtitle.strip(), qsubject.strip(), qstream, qdesc.strip(),
                             str(qdeadline) if qdeadline else "", qduration,
                             st.session_state.username, questions)
                    st.success("Quiz published to cloud.")
                    st.rerun()

        with manage_tab:
            if not quizzes:
                st.info("No quizzes created yet.")
            for qz in quizzes:
                with st.container(border=True):
                    st.markdown(f"### {qz['title']}")
                    st.write(f"**Subject:** {qz['subject'] or 'General'} • **Target:** {qz['target_stream']} • **Time:** {qz['duration_minutes']} minutes")
                    if qz['deadline']:
                        st.write(f"**Closing date:** {qz['deadline']}")
                    qs = get_quiz_questions(qz['id'])
                    st.caption(f"{len(qs)} questions")
                    if st.button("🗑️ Delete", key=f"qdel{qz['id']}"):
                        delete_quiz(qz['id'])
                        st.rerun()

        with results_tab:
            if not attempts:
                st.info("No attempts yet.")
            else:
                result_rows = []
                for a in attempts:
                    pct, _ = quiz_grade(a['score'], a['total_points'])
                    result_rows.append({
                        "Quiz": a['title'],
                        "Student": a['student_name'],
                        "Score": f"{a['score']:.1f}/{a['total_points']:.1f}",
                        "Percentage": f"{pct:.1f}%",
                        "Status": a['status'],
                        "Submitted": a['submitted_at']
                    })
                st.dataframe(pd.DataFrame(result_rows), use_container_width=True, hide_index=True)

                st.markdown("### Review attempt")
                options = {f"{a['student_name']} — {a['title']} — {a['submitted_at']}": a for a in attempts}
                selected_label = st.selectbox("Attempt", list(options))
                selected = options[selected_label]
                pct, g = quiz_grade(selected['score'], selected['total_points'])
                x, y, z = st.columns(3)
                x.metric("Score", f"{selected['score']:.1f}/{selected['total_points']:.1f}")
                y.metric("Percentage", f"{pct:.1f}%")
                z.metric("Grade", g)

                feedback = st.text_area("Teacher feedback", value=selected.get('teacher_feedback', ''), key=f"qfeedback{selected['id']}")

                st.markdown("### 📝 Student Answers")
                answers = json.loads(selected.get('answers_json') or '{}')
                manual_marks = json.loads(selected.get('manual_marks_json') or '{}')

                for qq in get_quiz_questions(selected['quiz_id']):
                    ans = answers.get(str(qq['id']), "")
                    st.markdown(f"**Q{qq['question_no']}: {qq['question_text']}**")

                    if qq['question_type'] == "Multiple Choice":
                        opts = {"A": qq.get('option_a', ''), "B": qq.get('option_b', ''),
                                "C": qq.get('option_c', ''), "D": qq.get('option_d', '')}
                        correct = qq.get('correct_answer', '')
                        if ans == correct:
                            st.success(f"Student answered: **{ans}** — {opts.get(ans, '')} ✅ Correct")
                        else:
                            st.error(f"Student answered: **{ans or '(no answer)'}** — {opts.get(ans, '(blank)') if ans else '(no answer)'}")
                            st.caption(f"Correct answer: **{correct}** — {opts.get(correct, '')}")

                    elif qq['question_type'] == "True / False":
                        correct = qq.get('correct_answer', '')
                        if ans == correct:
                            st.success(f"Student answered: **{ans}** ✅ Correct")
                        else:
                            st.error(f"Student answered: **{ans or '(no answer)'}**")
                            st.caption(f"Correct answer: **{correct}**")

                    else:                                        
                        st.info(f"Student's written answer: **{ans or '(no answer)'}**")
                        max_pts = float(qq.get('points', 1))
                        existing_mark = float(manual_marks.get(str(qq['id']), 0.0))
                        awarded = st.number_input(
                            f"Award marks (out of {max_pts:g})",
                            min_value=0.0,
                            max_value=max_pts,
                            value=existing_mark,
                            step=0.5,
                            key=f"marks_input_{selected['id']}_{qq['id']}"
                        )
                        if st.button("💾 Save This Mark", key=f"save_mark_{selected['id']}_{qq['id']}"):
                            manual_marks[str(qq['id'])] = float(awarded)
                            save_manual_marks(selected['id'], manual_marks)
                            st.success(f"Mark saved for Q{qq['question_no']}.")
                            st.rerun()

                    st.markdown("---")

                if st.button("✅ Finalize Quiz Score", type="primary", use_container_width=True):
                    auto_score = float(selected.get('score') or 0)
                    fresh_manual = json.loads(selected.get('manual_marks_json') or '{}')
                    new_score = finalize_quiz_attempt(
                        selected['id'], auto_score, fresh_manual, selected['total_points']
                    )
                    st.success(f"Final score: {new_score:.1f}/{selected['total_points']:.1f}. Status set to Reviewed.")
                    st.rerun()

                if st.button("💾 Save Quiz Feedback", type="primary", key=f"save_feedback_{selected['id']}"):
                    update_quiz_feedback(selected['id'], feedback)
                    st.success("Feedback saved.")
                    st.rerun()

    else:
        student_name = st.session_state.student_name.strip()
        if not student_name:
            sp = get_student_profile(st.session_state.username)
            if sp:
                student_name = (sp.get("student_full_name") or "").strip()
        if not student_name:
            st.warning("Enter the student name used in the academic Excel file.")
            student_name = st.text_input("Student name", key="quiz_student_name")

        streams = student_streams_for(student_name)
        available = [q for q in quizzes if quiz_available_for_student(q, streams)]
        attempts = get_attempts(student_name=student_name) if student_name else []
        attempted_ids = {a['quiz_id'] for a in attempts}
        pending = [q for q in available if q['id'] not in attempted_ids]

        st.markdown("### 🎓 Student Quiz Dashboard")
        a, b, c = st.columns(3)
        a.metric("Available", len(available))
        b.metric("Pending", len(pending))
        c.metric("Completed", len(attempts))

        take_tab, result_tab = st.tabs(["📝 Available Quizzes", "🏆 My Results"])

        with take_tab:
            if not pending:
                st.info("No new quizzes available.")
            for qz in pending:
                with st.container(border=True):
                    st.markdown(f"### {qz['title']}")
                    st.write(f"**Subject:** {qz['subject'] or 'General'} • **Questions:** {len(get_quiz_questions(qz['id']))} • **Time:** {qz['duration_minutes']} minutes")
                    if qz['deadline']:
                        st.write(f"**Closing date:** {qz['deadline']}")
                    if qz['description']:
                        st.write(qz['description'])
                    if st.button("▶️ Start Quiz", key=f"startquiz{qz['id']}", type="primary"):
                        st.session_state.active_quiz = qz['id']
                        st.rerun()

            active = st.session_state.get('active_quiz')
            if active:
                qz = next((q for q in available if q['id'] == active), None)
                if qz:
                    st.divider()
                    st.markdown(f"## 📝 {qz['title']}")
                    answers = {}
                    total = 0
                    auto_score = 0
                    has_manual = False
                    for qq in get_quiz_questions(qz['id']):
                        pts = float(qq['points'])
                        total += pts
                        st.markdown(f"**{qq['question_no']}. {qq['question_text']}**  _({pts:g} marks)_")
                        if qq['question_type'] == "Multiple Choice":
                            ans = st.radio("Answer", [
                                f"A. {qq['option_a']}", f"B. {qq['option_b']}",
                                f"C. {qq['option_c']}", f"D. {qq['option_d']}"
                            ], key=f"ans{qq['id']}")
                            letter = ans.split('.', 1)[0] if ans else ""
                            answers[str(qq['id'])] = letter
                            if letter == qq['correct_answer']:
                                auto_score += pts
                        elif qq['question_type'] == "True / False":
                            ans = st.radio("Answer", ["True", "False"], key=f"ans{qq['id']}")
                            answers[str(qq['id'])] = ans
                            if ans == qq['correct_answer']:
                                auto_score += pts
                        else:
                            ans = st.text_area("Your answer", key=f"ans{qq['id']}", height=80)
                            answers[str(qq['id'])] = ans
                            has_manual = True
                    if st.button("📤 Submit Quiz", type="primary", use_container_width=True):
                        status = "Needs Teacher Review" if has_manual else "Submitted"
                        save_quiz_attempt(qz['id'], student_name.strip(), answers, auto_score, total, status)
                        st.session_state.active_quiz = None
                        st.success(f"Submitted. Score: {auto_score:.1f}/{total:.1f}")
                        st.rerun()

        with result_tab:
            if not attempts:
                st.info("No attempts yet.")
            for a in attempts:
                pct, g = quiz_grade(a['score'], a['total_points'])
                with st.container(border=True):
                    st.markdown(f"### {a['title']}")
                    st.write(f"**Score:** {a['score']:.1f}/{a['total_points']:.1f} • **Percentage:** {pct:.1f}% • **Grade:** {g}")
                    st.write(f"**Status:** {a['status']} • Submitted: {a['submitted_at']}")
                    if a.get('teacher_feedback'):
                        st.info(f"Teacher feedback: {a['teacher_feedback']}")


# ============================================================
# CHANGE PASSWORD
# ============================================================

elif page == "Change Password":
    st.subheader("🔒 Change Your Password")
    st.caption(f"Signed in as: **{st.session_state.username}**")

    old_pw = st.text_input("Current password", type="password", key="user_cp_old")
    new_pw = st.text_input("New password", type="password", key="user_cp_new")
    confirm_pw = st.text_input("Confirm new password", type="password", key="user_cp_confirm")

    if st.button("Update Password", type="primary", use_container_width=True, key="user_cp_button"):
        if not old_pw or not new_pw or not confirm_pw:
            st.error("Fill in all fields.")
        elif new_pw != confirm_pw:
            st.error("New passwords do not match.")
        elif len(new_pw) < 6:
            st.error("New password must be at least 6 characters.")
        else:
            user = authenticate_user(st.session_state.username, old_pw)
            if not user:
                st.error("Current password is incorrect.")
            else:
                change_user_password(st.session_state.username, new_pw)
                st.success("Password updated successfully. Use the new password next time you sign in.")


# ============================================================
# MY PROFILE
# ============================================================

elif page == "My Profile":
    st.subheader("👤 My Student Profile")
    profile = get_student_profile(st.session_state.username)
    if profile:
        st.write(f"**Username:** {st.session_state.username}")
        st.write(f"**Role:** Student")
        st.write(f"**Linked student name:** {profile.get('student_full_name', 'Not linked')}")
    else:
        st.info("Not linked. Please contact the school administrator.")
        st.write(f"**Username:** {st.session_state.username}")


# ============================================================
# SETTINGS
# ============================================================

elif page == "💰 Fee Structure":
    if st.session_state.user_role not in ["admin", "clerk"]:
        st.error("🔒 You don't have access to fee pages.")
        st.stop()
    st.subheader("💰 Fee Structure")
    st.caption("Set the amount each stream pays per term. This feeds into student fee balances.")

    streams_available = get_all_streams_from_data()

    with st.expander("➕ Add / Update Fee Structure", expanded=True):
        if not streams_available:
            st.warning("No streams detected. Upload your student Excel file first.")
        else:
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                new_stream = st.selectbox("Stream", streams_available, key="fee_struct_stream")
            with fc2:
                new_term = st.selectbox("Term", TERMS, key="fee_struct_term")
            with fc3:
                new_amount = st.number_input("Amount (KSh)", min_value=0.0, value=0.0, step=500.0, key="fee_struct_amount")

            new_desc = st.text_input("Description (optional)", placeholder="e.g. Term 3 tuition", key="fee_struct_desc")

            if st.button("💾 Save Fee Structure", type="primary", use_container_width=True, key="fee_struct_save"):
                if new_amount <= 0:
                    st.error("Enter an amount greater than 0.")
                else:
                    try:
                        set_fee_structure(new_stream, new_term, new_amount, new_desc.strip(), st.session_state.username)
                        st.success(f"✅ {new_stream} — {new_term.upper()} = KSh {new_amount:,.0f}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error saving: {e}")

    st.divider()
    st.markdown("### 📋 Current Fee Structure")
    structures = get_fee_structure()
    if not structures:
        st.info("No fee structure set yet. Add one above.")
    else:
        df_fs = pd.DataFrame(structures)
        df_fs = df_fs[["stream", "term", "amount", "description", "updated_by", "updated_at"]]
        df_fs.columns = ["Stream", "Term", "Amount (KSh)", "Description", "Updated By", "Updated At"]
        df_fs["Term"] = df_fs["Term"].str.upper()
        df_fs["Amount (KSh)"] = df_fs["Amount (KSh)"].apply(lambda x: f"{float(x):,.0f}")
        st.dataframe(df_fs, use_container_width=True, hide_index=True)

        with st.expander("🗑️ Delete a fee structure entry"):
            del_options = {f"{s['stream']} — {s['term'].upper()} — KSh {float(s['amount']):,.0f}": s["id"] for s in structures}
            selected_label = st.selectbox("Select entry", list(del_options.keys()), key="fee_del_select")
            confirm_del = st.checkbox("I understand this will remove the fee structure entry.", key="fee_del_confirm")
            if st.button("Delete", type="secondary", disabled=not confirm_del, key="fee_del_btn"):
                try:
                    delete_fee_structure(del_options[selected_label], st.session_state.username)
                    st.success("Deleted.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

    st.divider()
    st.markdown("### 🧪 Quick Test — Student Balance")
    st.caption("Enter a student name to see their fee balance.")
    test_student = st.text_input("Student name", key="fee_test_student", placeholder="e.g. JOHN MWANGI")
    if test_student and streams_available:
        student_stream = ""
        if st.session_state.get("data") is not None:
            tdf = st.session_state.data["df"]
            tname = st.session_state.data["name_col"]
            tstream = st.session_state.data["stream_col"]
            hit = tdf[tdf[tname].astype(str).str.strip().str.lower() == test_student.strip().lower()]
            if not hit.empty:
                student_stream = str(hit.iloc[0][tstream])

        if student_stream:
            st.write(f"**Stream:** {student_stream}")
            ledger = get_student_fee_ledger(test_student.strip(), student_stream)
            c1, c2, c3 = st.columns(3)
            c1.metric("Expected", f"KSh {ledger['expected']:,.0f}")
            c2.metric("Paid", f"KSh {ledger['paid']:,.0f}")
            c3.metric("Balance", f"KSh {ledger['balance']:,.0f}")
        else:
            st.warning("Student not found in the loaded Excel data.")

elif page == "💵 Record Payment":
    if st.session_state.user_role not in ["admin", "clerk"]:
        st.error("🔒 You don't have access to fee pages.")
        st.stop()
    st.subheader("💵 Record Fee Payment")
    st.caption("Log a payment received from a student. This updates their fee balance automatically.")

    streams_available = get_all_streams_from_data()

    if not streams_available:
        st.warning("No student data loaded. Upload your Excel file first.")
        st.stop()

    # --- Step 1: Select student ---
    with st.expander("➕ Record New Payment", expanded=True):
        # Build a list of students with their streams
        student_options = []
        if st.session_state.get("data") is not None:
            sdf = st.session_state.data["df"]
            sname = st.session_state.data["name_col"]
            sstream = st.session_state.data["stream_col"]
            student_options = [
                (str(row[sname]), str(row[sstream]))
                for _, row in sdf.iterrows()
            ]

        # Filter by stream to make it easier
        stream_filter = st.selectbox(
            "Filter by stream",
            ["ALL STREAMS"] + streams_available,
            key="payment_stream_filter"
        )

        filtered_students = student_options
        if stream_filter != "ALL STREAMS":
            filtered_students = [(n, s) for n, s in student_options if s == stream_filter]

        if not filtered_students:
            st.info("No students found for that stream.")
            st.stop()

        student_labels = [f"{n} — {s}" for n, s in filtered_students]
        selected_label = st.selectbox("Select student", student_labels, key="payment_student_select")
        selected_idx = student_labels.index(selected_label)
        sel_student, sel_stream = filtered_students[selected_idx]

        st.markdown(f"**Student:** {sel_student}  •  **Stream:** {sel_stream}")

        # Show current balance
        ledger = get_student_fee_ledger(sel_student, sel_stream)
        c1, c2, c3 = st.columns(3)
        c1.metric("Expected (all terms)", f"KSh {ledger['expected']:,.0f}")
        c2.metric("Paid so far", f"KSh {ledger['paid']:,.0f}")
        c3.metric("Balance", f"KSh {ledger['balance']:,.0f}")

        st.divider()

        # Payment entry
        p1, p2 = st.columns(2)
        with p1:
            pay_amount = st.number_input("Amount received (KSh)", min_value=0.0, value=0.0, step=500.0, key="payment_amount")
            pay_date = st.date_input("Payment date", value=date.today(), key="payment_date")
        with p2:
            pay_term = st.selectbox("Term", TERMS, key="payment_term")
            pay_method = st.selectbox("Payment method", ["cash", "M-Pesa", "bank", "cheque", "other"], key="payment_method")

        pay_ref = st.text_input("Reference (optional)", placeholder="e.g. M-Pesa code QK123456", key="payment_ref")
        pay_notes = st.text_area("Notes (optional)", height=60, key="payment_notes")

        if st.button("💾 Record Payment", type="primary", use_container_width=True, key="payment_save"):
            if pay_amount <= 0:
                st.error("Amount must be greater than 0.")
            else:
                try:
                    payment_id = record_fee_payment(
                        sel_student, sel_stream, pay_term, pay_amount,
                        pay_date, pay_method, pay_ref.strip(),
                        st.session_state.username, pay_notes.strip()
                    )
                    st.success(f"✅ Recorded KSh {pay_amount:,.0f} from {sel_student} for {pay_term.upper()} ({pay_method}).")
                    st.session_state["last_payment_id"] = payment_id
                    st.session_state["last_payment_student"] = sel_student
                    st.session_state["last_payment_stream"] = sel_stream
                    st.session_state["last_payment_amount"] = pay_amount
                    st.session_state["last_payment_term"] = pay_term
                    st.session_state["last_payment_date"] = pay_date
                    st.session_state["last_payment_method"] = pay_method
                    st.session_state["last_payment_ref"] = pay_ref.strip()
                    st.session_state["last_payment_notes"] = pay_notes.strip()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error recording payment: {e}")

    # --- Step 2: Recent payments ---
    # --- Show download receipt button if a payment was just made ---
    if st.session_state.get("last_payment_id"):
        st.divider()
        st.success(f"✅ Last payment: KSh {st.session_state.get('last_payment_amount', 0):,.0f} from {st.session_state.get('last_payment_student', '')}")
        if st.button("📄 Generate Receipt PDF", type="primary", key="generate_receipt_btn"):
            # Recompute balance before and after
            pmt = {
                "id": st.session_state["last_payment_id"],
                "student_name": st.session_state["last_payment_student"],
                "stream": st.session_state["last_payment_stream"],
                "amount": st.session_state["last_payment_amount"],
                "term": st.session_state["last_payment_term"],
                "payment_date": st.session_state["last_payment_date"],
                "payment_method": st.session_state["last_payment_method"],
                "reference": st.session_state["last_payment_ref"],
                "notes": st.session_state["last_payment_notes"],
                "recorded_by": st.session_state.username,
            }
            ledger = get_student_fee_ledger(pmt["student_name"], pmt["stream"])
            balance_after = ledger["balance"]
            balance_before = balance_after + float(pmt["amount"])
            receipt_pdf = generate_receipt_pdf(pmt, st.session_state.school_name, balance_before, balance_after)
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", pmt["student_name"]).strip("_")
            st.download_button(
                "⬇️ Download Receipt PDF",
                data=receipt_pdf.getvalue(),
                file_name=f"Receipt_{pmt['id']}_{safe}.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="download_receipt_btn"
            )
        if st.button("✖ Clear", key="clear_last_payment_btn"):
            for k in ["last_payment_id", "last_payment_student", "last_payment_stream",
                      "last_payment_amount", "last_payment_term", "last_payment_date",
                      "last_payment_method", "last_payment_ref", "last_payment_notes"]:
                st.session_state.pop(k, None)
            st.rerun()

    st.divider()
    st.markdown("### 📋 Recent Payments")
    st.caption("Latest 50 payments recorded across the school.")

    recent = get_fee_payments(include_voided=False)
    recent = recent[:50]

    if not recent:
        st.info("No payments recorded yet.")
    else:
        rows = []
        for p in recent:
            rows.append({
                "Date": p.get("payment_date", ""),
                "Student": p.get("student_name", ""),
                "Stream": p.get("stream", ""),
                "Term": (p.get("term") or "").upper(),
                "Amount (KSh)": f"{float(p.get('amount', 0)):,.0f}",
                "Method": p.get("payment_method", ""),
                "Reference": p.get("reference", ""),
                "Recorded By": p.get("recorded_by", ""),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # --- Step 3: Void a payment ---
    with st.expander("🗑️ Void (cancel) a payment"):
        st.caption("Voiding does not delete the record — it marks it as cancelled for the audit log.")
        if recent:
            void_options = {
                f"#{p['id']} — {p['student_name']} — KSh {float(p['amount']):,.0f} — {p.get('payment_date','')}": p["id"]
                for p in recent
            }
            void_label = st.selectbox("Select payment to void", list(void_options.keys()), key="void_payment_select")
            void_reason = st.text_input("Reason for voiding", placeholder="e.g. duplicate entry", key="void_reason")
            void_confirm = st.checkbox("I understand this payment will be marked as void.", key="void_confirm")
            if st.button("Void Payment", type="secondary", disabled=not void_confirm, key="void_payment_btn"):
                if not void_reason.strip():
                    st.error("Enter a reason.")
                else:
                    try:
                        void_fee_payment(void_options[void_label], st.session_state.username, void_reason.strip())
                        st.success("Payment voided.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
        else:
            st.info("No payments to void.")
elif page == "📒 Student Ledger":
    if st.session_state.user_role not in ["admin", "clerk"]:
        st.error("🔒 You don't have access to fee pages.")
        st.stop()
    st.subheader("📒 Student Fee Ledger")
    st.caption("View a student's complete fee history — expected, paid, and balance.")

    streams_available = get_all_streams_from_data()

    if not streams_available:
        st.warning("No student data loaded. Upload your Excel file first.")
        st.stop()

    # --- Search & select student ---
    sc1, sc2 = st.columns([2, 1])
    with sc1:
        search_name = st.text_input("🔎 Search student name", placeholder="Type part of a name", key="ledger_search")
    with sc2:
        ledger_stream_filter = st.selectbox(
            "Filter by stream",
            ["ALL STREAMS"] + streams_available,
            key="ledger_stream_filter"
        )

    # Build the student list from Excel data
    student_options = []
    if st.session_state.get("data") is not None:
        sdf = st.session_state.data["df"]
        sname = st.session_state.data["name_col"]
        sstream = st.session_state.data["stream_col"]
        for _, row in sdf.iterrows():
            n = str(row[sname])
            s = str(row[sstream])
            if ledger_stream_filter != "ALL STREAMS" and s != ledger_stream_filter:
                continue
            if search_name and search_name.lower() not in n.lower():
                continue
            student_options.append((n, s))

    if not student_options:
        st.info("No students match the search.")
        st.stop()

    # Select student
    student_labels = [f"{n} — {s}" for n, s in student_options]
    selected_label = st.selectbox("Select student", student_labels, key="ledger_student_select")
    selected_idx = student_labels.index(selected_label)
    sel_student, sel_stream = student_options[selected_idx]

    st.markdown(f"### 👤 {sel_student}")
    st.caption(f"Stream: **{sel_stream}**")

    # --- Overall balance across all terms ---
    ledger = get_student_fee_ledger(sel_student, sel_stream)

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Expected", f"KSh {ledger['expected']:,.0f}")
    c2.metric("Total Paid", f"KSh {ledger['paid']:,.0f}")
    balance = ledger["balance"]
    c3.metric(
        "Balance",
        f"KSh {balance:,.0f}",
        delta=None if balance == 0 else ("Settled ✅" if balance <= 0 else "Owes")
    )

    # --- Term-by-term breakdown (with allocation) ---
    st.divider()
    st.markdown("### 📅 Term-by-Term Breakdown")
    st.caption("Payments are automatically applied to the earliest unpaid term.")

    allocated = get_allocated_ledger(sel_student, sel_stream)

    term_rows = []
    for r in allocated["rows"]:
        term_rows.append({
            "Term": r["term"].upper(),
            "Expected (KSh)": f"{r['expected']:,.0f}",
            "Allocated (KSh)": f"{r['allocated']:,.0f}",
            "Balance (KSh)": f"{r['balance']:,.0f}",
            "Status": r["status"],
        })

    st.dataframe(pd.DataFrame(term_rows), use_container_width=True, hide_index=True)

    if allocated["credit"] > 0:
        st.info(f"💰 **Credit balance:** KSh {allocated['credit']:,.0f} (over-payment beyond all terms)")

    # --- Payment history ---
    st.divider()
    st.markdown("### 📜 Payment History")

    payments = get_fee_payments(student_name=sel_student)
    if not payments:
        st.info("No payments recorded yet for this student.")
    else:
        for p in payments:
            with st.container(border=True):
                pc1, pc2, pc3 = st.columns([2, 2, 1])
                with pc1:
                    st.markdown(f"**{str(p.get('payment_date', ''))}** — {(p.get('term') or '').upper()}")
                    st.caption(f"{p.get('payment_method', '').title()}"
                               + (f" • {p.get('reference', '')}" if p.get('reference') else ""))
                with pc2:
                    st.markdown(f"### KSh {float(p.get('amount', 0)):,.0f}")
                    st.caption(f"Recorded by {p.get('recorded_by', '')}")
                with pc3:
                    if st.button("📄 Receipt", key=f"receipt_btn_{p['id']}"):
                        # Recompute balance before/after for this payment
                        # Simple version: current balance + this payment = before
                        # We don't have historical snapshots, so we compute the current balance
                        # and treat "before" as balance + amount
                        current_ledger = get_student_fee_ledger(sel_student, sel_stream)
                        # Find the running balance at this payment's point in time
                        # Simplification: balance after = current + all payments made AFTER this one
                        # Since payments are sorted newest first, sum the amounts of earlier payments (newer ones)
                        amount_this = float(p.get("amount", 0))
                        balance_after_this = current_ledger["balance"] + sum(
                            float(pp.get("amount", 0)) for pp in payments
                            if pp["id"] > p["id"]
                        )
                        balance_before_this = balance_after_this + amount_this
                        receipt_pdf = generate_receipt_pdf(p, st.session_state.school_name, balance_before_this, balance_after_this)
                        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(p.get("student_name", "student"))).strip("_")
                        st.download_button(
                            "⬇️ Download",
                            data=receipt_pdf.getvalue(),
                            file_name=f"Receipt_{p['id']}_{safe}.pdf",
                            mime="application/pdf",
                            key=f"receipt_dl_{p['id']}"
                        )
                if p.get("notes"):
                    st.caption(f"📝 {p.get('notes', '')}")

    # --- Download statement ---
    st.divider()
    st.markdown("### 📄 Download Fee Statement")
    st.caption("Download a simple statement as CSV — you can open it in Excel and print for the parent.")

    if st.button("📥 Prepare Statement (CSV)", type="primary", key="ledger_download_btn"):
        statement_rows = []
        statement_rows.append(["Student", sel_student])
        statement_rows.append(["Stream", sel_stream])
        statement_rows.append([])
        statement_rows.append(["Term", "Expected", "Paid", "Balance"])
        for term in TERMS:
            structure = get_fee_structure(stream=sel_stream, term=term)
            expected_term = sum(float(s["amount"]) for s in structure)
            payments_term = get_fee_payments(student_name=sel_student, term=term)
            paid_term = sum(float(p["amount"]) for p in payments_term)
            statement_rows.append([term.upper(), expected_term, paid_term, expected_term - paid_term])
        statement_rows.append([])
        statement_rows.append(["Date", "Term", "Amount", "Method", "Reference", "Recorded By"])
        for p in payments:
            statement_rows.append([
                p.get("payment_date", ""),
                (p.get("term") or "").upper(),
                float(p.get("amount", 0)),
                p.get("payment_method", ""),
                p.get("reference", ""),
                p.get("recorded_by", ""),
            ])
        statement_rows.append([])
        statement_rows.append(["TOTAL PAID", ledger["paid"]])
        statement_rows.append(["BALANCE", ledger["balance"]])

        csv_df = pd.DataFrame(statement_rows)
        csv_bytes = csv_df.to_csv(index=False, header=False).encode("utf-8")
        safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", sel_student).strip("_")
        st.download_button(
            "⬇️ Download Statement CSV",
            data=csv_bytes,
            file_name=f"Fee_Statement_{safe_name}.csv",
            mime="text/csv",
            use_container_width=True
        )


elif page == "📊 Fee Reports":
    if st.session_state.user_role not in ["admin", "clerk"]:
        st.error("🔒 You don't have access to fee pages.")
        st.stop()
    st.subheader("📊 Fee Reports")
    st.caption("Overview of fee collection across the school.")

    streams_available = get_all_streams_from_data()

    # --- Filter by term ---
    rc1, rc2 = st.columns([1, 2])
    with rc1:
        term_filter = st.selectbox(
            "Report term",
            ["ALL TERMS"] + TERMS,
            key="report_term_filter",
            format_func=lambda x: x.upper() if x != "ALL TERMS" else x
        )
    with rc2:
        stream_filter = st.selectbox(
            "Filter by stream",
            ["ALL STREAMS"] + streams_available,
            key="report_stream_filter"
        )

    # --- Fetch data ---
    if term_filter == "ALL TERMS":
        all_payments = get_fee_payments(include_voided=False)
    else:
        all_payments = get_fee_payments(term=term_filter, include_voided=False)

    if stream_filter != "ALL STREAMS":
        all_payments = [p for p in all_payments if p.get("stream") == stream_filter]

    # --- Summary metrics ---
    total_collected = sum(float(p["amount"]) for p in all_payments)
    total_payments = len(all_payments)
    average_payment = total_collected / total_payments if total_payments else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Collected", f"KSh {total_collected:,.0f}")
    c2.metric("Payments Recorded", total_payments)
    c3.metric("Average Payment", f"KSh {average_payment:,.0f}")

    # --- By method ---
    st.divider()
    st.markdown("### 💳 Collection by Payment Method")
    method_totals = {}
    method_counts = {}
    for p in all_payments:
        m = p.get("payment_method", "unknown")
        method_totals[m] = method_totals.get(m, 0) + float(p["amount"])
        method_counts[m] = method_counts.get(m, 0) + 1

    if method_totals:
        method_rows = []
        for m, tot in sorted(method_totals.items(), key=lambda x: -x[1]):
            pct = (tot / total_collected * 100) if total_collected else 0
            method_rows.append({
                "Method": m.title(),
                "Total (KSh)": f"{tot:,.0f}",
                "Payments": method_counts[m],
                "% of Total": f"{pct:.1f}%"
            })
        st.dataframe(pd.DataFrame(method_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No payments yet for this filter.")

    # --- By term ---
    st.divider()
    st.markdown("### 📅 Collection by Term")
    term_totals = {}
    for t in TERMS:
        term_totals[t] = 0
    for p in all_payments:
        t = (p.get("term") or "").lower()
        if t in term_totals:
            term_totals[t] += float(p["amount"])

    term_rows = []
    for t in TERMS:
        term_rows.append({
            "Term": t.upper(),
            "Collected (KSh)": f"{term_totals[t]:,.0f}"
        })
    st.dataframe(pd.DataFrame(term_rows), use_container_width=True, hide_index=True)

    # --- By stream ---
    if stream_filter == "ALL STREAMS":
        st.divider()
        st.markdown("### 🏫 Collection by Stream")
        stream_totals = {}
        stream_counts = {}
        for p in all_payments:
            s = p.get("stream") or "Unknown"
            stream_totals[s] = stream_totals.get(s, 0) + float(p["amount"])
            stream_counts[s] = stream_counts.get(s, 0) + 1

        if stream_totals:
            stream_rows = []
            for s, tot in sorted(stream_totals.items(), key=lambda x: -x[1]):
                stream_rows.append({
                    "Stream": s,
                    "Total (KSh)": f"{tot:,.0f}",
                    "Payments": stream_counts[s]
                })
            st.dataframe(pd.DataFrame(stream_rows), use_container_width=True, hide_index=True)

    # --- Outstanding students ---
    st.divider()
        # ============================================================
# 🚨 FEE DEFAULT REPORT — students below a threshold
    # ============================================================
    st.divider()
    st.markdown("### 🚨 Fee Default Report")
    st.caption(
        "Enter a fee threshold. The report lists students who have **paid LESS** than that "
        "amount **AND still owe money**. Students who have paid the threshold or more, "
        "or who have overpaid, are excluded."
    )

    with st.expander("⚙️ Configure Fee Default Report", expanded=True):
        dc1, dc2 = st.columns(2)
        with dc1:
            default_term = st.selectbox(
                "Report for term",
                ["ALL TERMS"] + TERMS,
                key="default_term",
                format_func=lambda x: x.upper() if x != "ALL TERMS" else x
            )
            default_stream = st.selectbox(
                "Stream",
                ["ALL STREAMS"] + streams_available,
                key="default_stream"
            )
        with dc2:
            default_threshold = st.number_input(
                "Fee threshold (KSh)",
                min_value=0.0,
                value=340000.0,
                step=1000.0,
                key="default_threshold",
                help="Students who paid LESS than this will be listed."
            )
            st.caption("Example: If you set 340,000 — students who paid less than that are listed. Those who paid 340,000 or more are NOT listed.")

        generate_default_btn = st.button(
            "🔍 Generate Fee Default Report",
            type="primary",
            use_container_width=True,
            key="generate_default_btn"
        )

    if generate_default_btn:
        # Build the list
        defaulters = []
        if st.session_state.get("data") is not None:
            sdf = st.session_state.data["df"]
            sname = st.session_state.data["name_col"]
            sstream = st.session_state.data["stream_col"]

            for _, row in sdf.iterrows():
                student_nm = str(row[sname])
                student_str = str(row[sstream])
                if default_stream != "ALL STREAMS" and student_str != default_stream:
                    continue

                if default_term == "ALL TERMS":
                    structure = get_fee_structure(stream=student_str)
                    expected = sum(float(s["amount"]) for s in structure)
                    payments = get_fee_payments(student_name=student_nm, include_voided=False)
                    paid = sum(float(p["amount"]) for p in payments)
                else:
                    structure = get_fee_structure(stream=student_str, term=default_term)
                    expected = sum(float(s["amount"]) for s in structure)
                    payments = get_fee_payments(student_name=student_nm, term=default_term)
                    paid = sum(float(p["amount"]) for p in payments)

                balance = expected - paid

                # Include only if PAID is LESS than threshold AND still owes money
                # Skip students who overpaid (negative balance)
                if paid < default_threshold and balance > 0:
                    defaulters.append({
                        "student": student_nm,
                        "stream": student_str,
                        "expected": expected,
                        "paid": paid,
                        "balance": balance,
                    })

        if not defaulters:
            st.success(f"🎉 No students have paid less than KSh {default_threshold:,.0f}. Everyone is above the threshold!")
        else:
            # Sort worst first (lowest paid)
            defaulters.sort(key=lambda x: x["paid"])

            st.markdown(f"### 📋 {len(defaulters)} student(s) below KSh {default_threshold:,.0f}")
            st.caption(
                f"Report term: **{default_term.upper() if default_term != 'ALL TERMS' else 'ALL TERMS'}** "
                f"• Stream: **{default_stream}**"
            )

            df_def = pd.DataFrame([
                {
                    "#": i,
                    "Student": d["student"],
                    "Stream": d["stream"],
                    "Expected (KSh)": f"{d['expected']:,.0f}",
                    "Paid (KSh)": f"{d['paid']:,.0f}",
                    "Balance (KSh)": f"{d['balance']:,.0f}",
                }
                for i, d in enumerate(defaulters, 1)
            ])
            st.dataframe(df_def, use_container_width=True, hide_index=True)

            # Downloads — always visible
            st.markdown("### 📥 Download Report")
            dl1, dl2 = st.columns(2)

            # CSV — always available
            with dl1:
                csv_rows = [[
                    "FEE DEFAULT REPORT",
                    f"Threshold: KSh {default_threshold:,.0f}",
                    f"Term: {default_term.upper() if default_term != 'ALL TERMS' else 'ALL TERMS'}",
                    f"Stream: {default_stream}",
                    f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                ], [], ["#", "Student", "Stream", "Expected", "Paid", "Balance"]]
                for i, d in enumerate(defaulters, 1):
                    csv_rows.append([
                        i, d["student"], d["stream"],
                        d["expected"], d["paid"], d["balance"]
                    ])
                csv_bytes = pd.DataFrame(csv_rows).to_csv(index=False, header=False).encode("utf-8")
                st.download_button(
                    "📥 Download CSV",
                    data=csv_bytes,
                    file_name=f"Fee_Default_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                    key="default_dl_csv"
                )

            # PDF — generate once, cache in session
            with dl2:
                # Generate the PDF every time (fast)
                pdf = generate_defaulters_pdf(
                    defaulters,
                    default_threshold,
                    default_term.upper() if default_term != "ALL TERMS" else "ALL TERMS",
                    st.session_state.school_name
                )
                st.download_button(
                    "🖨️ Download PDF for Print",
                    data=pdf.getvalue(),
                    file_name=f"Fee_Default_Report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="default_dl_pdf"
                )

    st.markdown("### ⚠️ Students with Outstanding Balances")
    st.caption("Students who still owe fees (for the selected term).")

    if st.session_state.get("data") is None:
        st.info("No Excel data loaded.")
    else:
        sdf = st.session_state.data["df"]
        sname = st.session_state.data["name_col"]
        sstream = st.session_state.data["stream_col"]

        # Only consider the current Excel students
        outstanding = []
        for _, row in sdf.iterrows():
            student_name = str(row[sname])
            student_stream = str(row[sstream])
            if stream_filter != "ALL STREAMS" and student_stream != stream_filter:
                continue

            if term_filter == "ALL TERMS":
                # Sum expected across all terms for this stream
                all_structure = get_fee_structure(stream=student_stream)
                expected_all = sum(float(s["amount"]) for s in all_structure)
                paid_all = sum(float(p["amount"]) for p in
                               get_fee_payments(student_name=student_name, include_voided=False))
                balance = expected_all - paid_all
                term_label = "ALL"
            else:
                structure = get_fee_structure(stream=student_stream, term=term_filter)
                expected_term = sum(float(s["amount"]) for s in structure)
                paid_term = sum(float(p["amount"]) for p in
                                get_fee_payments(student_name=student_name, term=term_filter))
                balance = expected_term - paid_term
                term_label = term_filter.upper()

            if balance > 0:
                outstanding.append({
                    "Student": student_name,
                    "Stream": student_stream,
                    "Term": term_label,
                    "Balance (KSh)": f"{balance:,.0f}"
                })

        if outstanding:
            outstanding.sort(key=lambda x: -float(x["Balance (KSh)"].replace(",", "")))
            st.dataframe(pd.DataFrame(outstanding), use_container_width=True, hide_index=True)
            st.caption(f"**{len(outstanding)}** student(s) with outstanding balances.")
        else:
            st.success("🎉 No outstanding balances — all students settled!")

    # --- Export report ---
    st.divider()
    st.markdown("### 📥 Export Report")
    st.caption("Download a CSV summary that you can open in Excel.")

    if st.button("📄 Prepare Report CSV", type="primary", key="report_export_btn"):
        report_rows = []
        report_rows.append(["FEE COLLECTION REPORT"])
        report_rows.append(["Term:", term_filter])
        report_rows.append(["Stream:", stream_filter])
        report_rows.append(["Generated:", datetime.now().strftime("%Y-%m-%d %H:%M")])
        report_rows.append([])
        report_rows.append(["SUMMARY"])
        report_rows.append(["Total Collected", f"{total_collected:.2f}"])
        report_rows.append(["Payments Recorded", total_payments])
        report_rows.append(["Average Payment", f"{average_payment:.2f}"])
        report_rows.append([])
        report_rows.append(["BY METHOD"])
        report_rows.append(["Method", "Total", "Payments"])
        for m, tot in sorted(method_totals.items(), key=lambda x: -x[1]):
            report_rows.append([m.title(), f"{tot:.2f}", method_counts[m]])
        report_rows.append([])
        report_rows.append(["BY TERM"])
        report_rows.append(["Term", "Collected"])
        for t in TERMS:
            report_rows.append([t.upper(), f"{term_totals[t]:.2f}"])
        report_rows.append([])
        report_rows.append(["ALL PAYMENTS"])
        report_rows.append(["Date", "Student", "Stream", "Term", "Amount", "Method", "Reference", "Recorded By"])
        for p in all_payments:
            report_rows.append([
                p.get("payment_date", ""),
                p.get("student_name", ""),
                p.get("stream", ""),
                (p.get("term") or "").upper(),
                float(p.get("amount", 0)),
                p.get("payment_method", ""),
                p.get("reference", ""),
                p.get("recorded_by", ""),
            ])

        csv_df = pd.DataFrame(report_rows)
        csv_bytes = csv_df.to_csv(index=False, header=False).encode("utf-8")
        st.download_button(
            "⬇️ Download Report CSV",
            data=csv_bytes,
            file_name=f"Fee_Report_{term_filter}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True
        )

# ============================================================
# TIMETABLE PAGE
# ============================================================

# ============================================================
# TEACHER LOAD REPORT
# ============================================================

elif page == "📊 Teacher Load Report":
    if st.session_state.user_role not in ["admin", "exams", "it_officer"]:
        st.error("🔒 You don't have access to this page.")
        st.stop()

    st.subheader("📊 Teacher Load Report")
    st.caption("Shows each teacher's total periods/week. Any teacher above their max (30 typical) is overloaded.")

    rows = tt_teacher_load_report()
    if not rows:
        st.warning("No data yet. Add teachers and assignments in Settings → ⚙️ Timetable Setup.")
        st.stop()

    total_periods = sum(r["Periods/Week"] for r in rows)
    overloaded = [r for r in rows if "OVERLOADED" in r["Status"]]
    unassigned = [r for r in rows if "UNASSIGNED" in r["Status"]]
    assigned = [r for r in rows if "OK" in r["Status"]]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Teachers Assigned", len(assigned))
    c2.metric("Total Periods", total_periods)
    c3.metric("Overloaded", len(overloaded))
    c4.metric("Unassigned", len(unassigned))

    if overloaded:
        st.error(f"⚠️ **{len(overloaded)} teacher(s) are OVERLOADED**")
    if unassigned:
        st.warning(f"ℹ️ {len(unassigned)} teacher(s) have no classes yet.")

    st.divider()
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    if overloaded:
        st.divider()
        st.markdown("### 🔴 Overloaded Teachers — Fix These")
        for r in overloaded:
            st.error(f"**{r['Teacher']}** — {r['Periods/Week']} periods vs {r['Max']} max. Subjects: {r['Breakdown']}")

    st.stop()


# ============================================================
# HELP & GUIDES PAGE
# ============================================================


    st.markdown("""
### 🎯 The Golden Rule
**Every class must have exactly 40 periods of subjects per week** — or fewer (Free Study fills the rest).

The system runs on:
- **8 teaching periods/day**
- **5 days/week** (Mon–Fri)
- **8 × 5 = 40 slots per class per week**

If the total periods for a class exceed 40, the generator will fail with **INFEASIBLE**.

---

### 📋 Step-by-Step Setup

#### Step 1 — Add Teachers
**Settings → ⚙️ Timetable Setup → 👨‍🏫 Teachers**

Add every teacher with:
- Full name (e.g., "Mr. Peter Kamau")
- Subjects they teach (e.g., "Maths, Physics")
- Max periods per day (default 6 → max 30/week)

⚠️ **Watch the load:** A teacher can only teach ~30 periods/week. If they're overloaded, generation fails.

#### Step 2 — Add Subjects
**Settings → ⚙️ Timetable Setup → 📖 Subjects**

Add every subject the school teaches. For each:
- Subject name (e.g., "Music")
- Periods per week (e.g., 2)
- Has a double period? (for Chemistry, Biology)
- Requires a lab? (Chemistry Lab, Biology Lab, Computer Lab)

⚠️ **When you add a new subject**, it will appear in every class. You MUST reduce Free Study (or another subject) by the same number of periods to keep totals at 40.

#### Step 3 — Add Classes
**Settings → ⚙️ Timetable Setup → 🏫 Classes**

Add every class:
- Format: `FORM 1 EAST`, `FORM 1 WEST`, `FORM 2 EAST`, ...

Adding a class auto-creates rows for every existing subject.

#### Step 4 — Assign Teachers
**Settings → ⚙️ Timetable Setup → 📚 Assignments**

For each class:
- Select the class from dropdown
- For every subject, pick the teacher who teaches it
- Leave **Free Study** and **Assembly** as `(unassigned)`
- Click **💾 Save All Assignments**

⚠️ **Every subject must have a teacher** except Free Study and Assembly.

#### Step 5 — Check Teacher Load
**📊 Teacher Load Report** (sidebar)

Verify:
- ✅ 0 Overloaded teachers
- ✅ 0 Unassigned teachers
- ✅ Total Periods looks right

If anyone is overloaded → reassign some classes to another teacher.

#### Step 6 — Generate
**📅 Timetable → 🔄 Generate Timetable**

Wait 10–60 seconds. Success → 40 slots × number of classes.

---

### 🧮 How Many Teachers Does a School Need?

| Classes | Periods/Slot Total | Teachers Needed |
|---|---|---|
| 6 | 240 | ~10–12 |
| 12 | 480 | ~16–20 |
| 16 | 640 | ~24–28 |
| 20 | 800 | ~30–35 |
| 24 | 960 | ~36–42 |

**Rule of thumb:** Teachers = Classes × 2 (approximately).

---

### ⚠️ Common Mistakes

**❌ Adding a subject without reducing Free Study**
- A class at 40 periods gets +2 for Music → 42 → INFEASIBLE
- **Fix:** Reduce Free Study from 5 → 3 for that class

**❌ Assigning a teacher to too many classes**
- One teacher can't teach 40 periods/week
- **Fix:** Split across multiple teachers

**❌ Leaving a subject unassigned**
- If a subject has no teacher, generator fails
- **Fix:** Assign every subject except Free Study + Assembly

**❌ Forgetting to Save**
- After picking teachers in Assignments, you must click **💾 Save All Assignments**
- **Fix:** Always verify the green "Saved" message appears

---

### 🔧 If Generation Fails with INFEASIBLE

**Step 1 — Check Teacher Load**
- 📊 Teacher Load Report
- Look for red "OVERLOADED" rows
- Reassign some classes

**Step 2 — Check Class Period Count**
Run this in Supabase:
```sql
SELECT class_name, SUM(periods_per_week) AS total
FROM tt_class_teacher
GROUP BY class_name
HAVING SUM(periods_per_week) != 40;
        """)
elif page == "📅 Timetable":

    teachers = tt_get_teachers()
    subjects = tt_get_subjects()
    all_classes = tt_get_all_classes()
    assignments = tt_get_class_teacher_assignments()
    periods, breaks = tt_get_periods()
    generated_count = tt_count_generated()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Classes", len(all_classes))
    c2.metric("Teachers", len(teachers))
    c3.metric("Subjects", len(subjects))
    c4.metric("Timetable Slots", generated_count)

    st.divider()

    if not teachers:
        st.warning("⚠️ No teachers added yet. Go to **Settings → ⚙️ Timetable Setup** to add teachers first.")
    elif not all_classes:
        st.warning("⚠️ No classes found. Please check the Supabase tt_class_teacher table.")
    else:
        st.success(f"✅ Setup ready: {len(all_classes)} classes, {len(teachers)} teachers, {len(subjects)} subjects.")

        st.markdown("### 🔄 Generate Timetable")
        st.caption("Click the button below to generate the full weekly timetable. This may take 10–60 seconds.")

        col1, col2 = st.columns([3, 1])
        with col1:
            if st.button("🔄 Generate Timetable", type="primary", use_container_width=True, key="tt_generate_btn"):
                with st.spinner("Solving the timetable — this may take up to 2 minutes..."):
                    result = tt_generate_timetable(max_seconds=300)

                if result["success"]:
                    st.success(result["message"])
                    st.rerun()
                else:
                    st.error(result["message"])
        with col2:
            generated_count = tt_count_generated()
            if generated_count > 0:
                st.metric("Slots", generated_count)

        st.divider()

        # ---------------- VIEWER ----------------
        if generated_count == 0:
            st.info("No timetable generated yet. Click **🔄 Generate Timetable** above to create one.")
            st.stop()

        st.markdown("## 📋 View Timetable")

        teacher_map = {t["id"]: t["full_name"] for t in teachers}
        view_mode = st.radio(
            "View by",
            ["By Class", "By Teacher", "By Room"],
            horizontal=True,
            key="tt_view_mode"
        )

        if view_mode == "By Class":
            selected_class = st.selectbox("Select class", all_classes, key="tt_view_class")
            rows = tt_get_generated(class_name=selected_class)
            st.markdown(f"### {selected_class}")
            if not rows:
                st.warning("No schedule for this class.")
            else:
                df = tt_build_grid(rows, teacher_map)
                st.dataframe(
                    df.drop(columns=["_is_break"]),
                    use_container_width=True,
                    hide_index=True,
                    height=620,
                )
                col_dl1, col_dl2 = st.columns(2)
                with col_dl1:
                    pdf_buf = tt_generate_pdf(
                        rows,
                        f"CLASS TIMETABLE — {selected_class}",
                        st.session_state.school_name,
                        teacher_map,
                    )
                    st.download_button(
                        "📄 Download as PDF",
                        data=pdf_buf.getvalue(),
                        file_name=f"Timetable_{selected_class.replace(' ', '_')}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        key=f"tt_pdf_{selected_class}",
                    )
                with col_dl2:
                    csv = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        "⬇️ Download as CSV",
                        data=csv,
                        file_name=f"Timetable_{selected_class.replace(' ', '_')}.csv",
                        mime="text/csv",
                        use_container_width=True,
                        key=f"tt_csv_{selected_class}",
                    )

        elif view_mode == "By Teacher":
            if not teachers:
                st.warning("No teachers.")
            else:
                teacher_labels = {t["id"]: t["full_name"] for t in teachers}
                teacher_choice = st.selectbox(
                    "Select teacher",
                    options=list(teacher_labels.keys()),
                    format_func=lambda tid: teacher_labels[tid],
                    key="tt_view_teacher",
                )
                rows = tt_get_generated(teacher_id=teacher_choice)
                st.markdown(f"### {teacher_labels[teacher_choice]}")
                if not rows:
                    st.warning("No schedule for this teacher.")
                else:
                    grid_rows = []
                    days = st.session_state.get("teaching_days") or ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
                    periods = [1, 2, 3, 4, 5, 6, 7, 8]
                    matrix = {p: {d: "" for d in days} for p in periods}
                    for r in rows:
                        p = r["period_no"]
                        d = r["day_of_week"]
                        cl = r["class_name"]
                        subj = r["subject_name"]
                        room = r.get("room") or ""
                        cell = f"{cl}\n{subj}"
                        if room:
                            cell += f"\n[{room}]"
                        if p in matrix and d in matrix[p]:
                            matrix[p][d] = cell
                    df = pd.DataFrame(matrix).T
                    df.index.name = "Period"
                    df = df.reset_index()
                    st.dataframe(df, use_container_width=True, hide_index=True, height=520)

                    pdf_buf = tt_generate_pdf(
                        rows,
                        f"TEACHER TIMETABLE — {teacher_labels[teacher_choice]}",
                        st.session_state.school_name,
                        teacher_map,
                    )
                    st.download_button(
                        "📄 Download as PDF",
                        data=pdf_buf.getvalue(),
                        file_name=f"Teacher_{teacher_labels[teacher_choice].replace(' ', '_')}.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                        key=f"tt_t_pdf_{teacher_choice}",
                    )

        else:  # By Room
            rooms = ["Chemistry Lab", "Biology Lab", "Computer Lab"]
            selected_room = st.selectbox("Select room", rooms, key="tt_view_room")
            rows = tt_get_generated(room=selected_room)
            st.markdown(f"### {selected_room}")
            if not rows:
                st.info(f"No scheduled periods in {selected_room}.")
            else:
                df = pd.DataFrame(rows)[["day_of_week", "period_no", "class_name", "subject_name", "teacher_id"]].copy()
                df["teacher_name"] = df["teacher_id"].map(teacher_map).fillna("")
                df = df[["day_of_week", "period_no", "class_name", "subject_name", "teacher_name"]]
                df.columns = ["Day", "Period", "Class", "Subject", "Teacher"]
                day_order = {"Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5}
                df["_d"] = df["Day"].map(day_order)
                df = df.sort_values(["_d", "Period"]).drop(columns=["_d"])
                st.dataframe(df, use_container_width=True, hide_index=True)

        st.divider()
        st.markdown("### 📋 Class Assignments Overview")
        if assignments:
            df_assign = pd.DataFrame(assignments)
            teacher_map2 = {t["id"]: t["full_name"] for t in teachers}
            df_assign["teacher_name"] = df_assign["teacher_id"].map(teacher_map2).fillna("(unassigned)")
            df_assign = df_assign[["class_name", "subject_name", "teacher_name", "periods_per_week"]]
            df_assign.columns = ["Class", "Subject", "Teacher", "Periods / Week"]
            with st.expander("Show all class assignments"):
                st.dataframe(df_assign, use_container_width=True, hide_index=True)


# ============================================================
# HELP & GUIDES PAGE (role-restricted)
# ============================================================

elif page == "❓ Help & Guides":
    st.subheader("❓ Help & Guides")
    st.caption("Step-by-step guides for your role in the Academic Management System.")

    role = st.session_state.get("user_role", "")

    # ---------------- ADMIN ----------------
    if role == "admin":
        t1, t2, t3, t4, t5, t6, t7 = st.tabs([
            "🚀 Getting Started",
            "📅 Timetable Setup",
            "💰 Fee Setup",
            "🎓 Academic Results",
            "👥 Account Management",
            "📊 Reports & Exports",
            "🔧 Troubleshooting",
        ])

        with t1:
            st.markdown("""
### Welcome, Administrator

You have full access to the entire system. This is what you can do:

- Manage student records
- Enter and edit academic results
- Generate report cards and merit lists
- Set up fee structure and record payments
- Manage all user accounts (teachers, clerks, parents, students, exams officers, IT officers, other admins)
- Configure timetables
- Monitor system health and backups

---

### 🚀 First-Time Setup

1. **School Profile** — Settings → 🏫 School Profile → add name, logo, address, motto
2. **Upload Excel** — sidebar → Upload student_results.xlsx
3. **Fee Structure** — Settings → 💰 Fee Structure → set term fees
4. **Timetable** — Settings → ⚙️ Timetable Setup → add teachers, subjects, classes
5. **User Accounts** — Settings → create accounts for staff, parents, students

---

### ✅ Daily Workflow

- **Check Dashboard** for school metrics
- **Review reports** — Master Merit List, Analytics
- **Manage accounts** — add/remove staff, reset passwords
- **Monitor** — check 📊 Teacher Load Report weekly
            """)

        with t2:
            st.markdown("""
### 📅 Timetable Setup (Admin)

**Every class must have exactly 40 periods of subjects per week.**

- 8 periods/day × 5 days = 40 slots
- Exceeding 40 → generator fails with INFEASIBLE

---

### Steps

1. **Add teachers** — Settings → ⚙️ Timetable Setup → 👨‍🏫 Teachers
2. **Add subjects** — Settings → ⚙️ Timetable Setup → 📖 Subjects
3. **Add classes** — Settings → ⚙️ Timetable Setup → 🏫 Classes
4. **Assign teachers** — Settings → ⚙️ Timetable Setup → 📚 Assignments
5. **Check load** — 📊 Teacher Load Report
6. **Generate** — 📅 Timetable → 🔄 Generate Timetable

---

### Rule of thumb

| Classes | Teachers needed |
|---|---|
| 12 | ~20 |
| 16 | ~28 |
| 20 | ~35 |

**Teachers ≈ Classes × 2**
            """)

        with t3:
            st.markdown("""
### 💰 Fee Setup (Admin)

**Setup:**
- Settings → 💰 Fee Structure → set per stream + term

**Recording payments:**
- Sidebar → 💵 Record Payment → select student, amount, method

**Reports:**
- Sidebar → 📊 Fee Reports → collection totals, defaulters, outstanding
- Sidebar → 📒 Student Ledger → per-student history

**Defaulters:**
- 📊 Fee Reports → Fee Default Report → set threshold → download CSV or PDF
            """)

        with t4:
            st.markdown("""
### 🎓 Academic Results (Admin)

**Enter results:**
- Sidebar → Academic Results → select term + student → enter marks

**Report cards:**
- Sidebar → Students → select student → Download PDF
- Sidebar → Reports → Generate ALL Student PDFs (ZIP)

**Merit lists:**
- Sidebar → Master Merit List → view rankings → download PDF

**Excel upload:**
- Sidebar → Upload student_results.xlsx → choose term → Load
            """)

        with t5:
            st.markdown("""
### 👥 Account Management (Admin)

All accounts created via **Settings → [Role] Accounts**:

- 👨‍🏫 Teacher Accounts
- 💼 Clerk Accounts
- 👨‍👩‍👧 Parent Accounts
- 🎓 Student Accounts
- 🎓 Exams Officer Accounts
- 🛡️ Admin Accounts
- 🖥️ IT Officer Accounts

**Reset a forgotten password:** open the appropriate tab, enter username + new password, save.

**Delete a departed staff member:** open the tab → Delete expander → select → confirm.
            """)

        with t6:
            st.markdown("""
### 📊 Reports & Exports (Admin)

| Report | Where | Format |
|---|---|---|
| Master Merit | Master Merit List | PDF |
| All Report Cards | Reports | ZIP |
| Individual Report | Students | PDF |
| Fee Report | 📊 Fee Reports | CSV |
| Fee Defaulters | 📊 Fee Reports | CSV + PDF |
| Receipt | 💵 Record Payment | PDF |
| Statement | 📒 Student Ledger | CSV |
| Class Timetable | 📅 Timetable | PDF + CSV |
| Teacher Timetable | 📅 Timetable | PDF |
| Full Backup | 💾 Backup & Data | ZIP |

**Weekly:** download Backup ZIP → save to Google Drive
            """)

        with t7:
            st.markdown("""
### 🔧 Troubleshooting (Admin)

**App won't load** → refresh, wait 60s, check internet

**Login fails** → check role, reset password in Settings

**Timetable INFEASIBLE** → check 📊 Teacher Load Report, ensure every class = 40 periods

**Excel upload fails** → check Settings → 📄 Excel Format Guide for correct columns

**Database errors** → check Settings → 🖥️ System Health

---

### 📞 Contact Developer

**Stephen Kithandule**
- 📱 0759120553
- ✉️ stephenkithandule@gmail.com
            """)

    # ---------------- EXAMS OFFICER ----------------
    elif role == "exams":
        t1, t2, t3, t4, t5 = st.tabs([
            "🚀 Getting Started",
            "📅 Timetable Setup",
            "🎓 Academic Results",
            "📊 Reports & Exports",
            "🔧 Troubleshooting",
        ])

        with t1:
            st.markdown("""
### Welcome, Exams Officer

Your role covers academic administration and timetables:

- Enter and edit academic results
- Manage student records
- Set up and generate timetables
- Create student and parent accounts
- View reports and merit lists

**You do NOT see:** Fee pages, teacher/clerk account management, school profile.
            """)

        with t2:
            st.markdown("""
### 📅 Timetable Setup (Exams Officer)

**Golden rule:** Every class must total exactly 40 periods/week.

**Setup:** Settings → ⚙️ Timetable Setup (4 sub-tabs)
- Teachers, Subjects, Classes, Assignments

**Check load:** 📊 Teacher Load Report

**Generate:** 📅 Timetable → 🔄 Generate Timetable
            """)

        with t3:
            st.markdown("""
### 🎓 Academic Results (Exams Officer)

- Sidebar → Academic Results → enter/edit marks
- Sidebar → Students → write class teacher comments, download report cards
- Sidebar → Master Merit List → ranked lists + PDF export
            """)

        with t4:
            st.markdown("""
### 📊 Reports (Exams Officer)

- Master Merit List PDF
- All student report cards (ZIP)
- Individual report cards
- Class / Teacher timetables (PDF)
            """)

        with t5:
            st.markdown("""
### 🔧 Troubleshooting (Exams Officer)

- **Timetable fails** → check Teacher Load, check class totals = 40
- **Excel upload** → check column format
- **Contact:** Stephen Kithandule · 0759120553
            """)

    # ---------------- TEACHER ----------------
    elif role == "teacher":
        t1, t2, t3 = st.tabs([
            "🚀 Getting Started",
            "🎓 Entering Marks",
            "🔧 Troubleshooting",
        ])

        with t1:
            st.markdown("""
### Welcome, Teacher

Your role:
- Enter and edit academic marks for your classes
- View student profiles and reports
- Post materials and quizzes in Learning Centre

**You do NOT see:** Fee pages, account management, system settings.
            """)

        with t2:
            st.markdown("""
### 🎓 How to Enter Marks

1. Sidebar → **Academic Results**
2. Select **term** (e.g. Y2T2)
3. Select **student**
4. Enter marks for each subject
5. Click **💾 Save Academic Results**

Marks save to the cloud automatically. The student's average, grade, and rank update instantly.
            """)

        with t3:
            st.markdown("""
### 🔧 Troubleshooting (Teacher)

- **Login fails** → check role + password, ask admin to reset
- **App slow** → refresh browser
- **Marks not saving** → check internet, try again
- **Need help** → contact the school administrator
            """)

    # ---------------- CLERK ----------------
    elif role == "clerk":
        t1, t2, t3 = st.tabs([
            "🚀 Getting Started",
            "💰 Recording Fees",
            "🔧 Troubleshooting",
        ])

        with t1:
            st.markdown("""
### Welcome, Clerk

Your role is fee management:
- Set fee structure per stream + term
- Record payments from students
- Print receipts
- View fee reports and defaulters

**You do NOT see:** Academic pages, timetable, account management.
            """)

        with t2:
            st.markdown("""
### 💰 How to Record Fees

**Setup fee structure first:**
- Sidebar → 💰 Fee Structure → select stream + term + amount → Save

**Record a payment:**
1. Sidebar → 💵 Record Payment
2. Select student
3. Enter amount, date, method, reference
4. Click **💾 Record Payment**
5. Download the receipt PDF

**View reports:**
- 📒 Student Ledger → per-student history
- 📊 Fee Reports → totals, defaulters, outstanding
            """)

        with t3:
            st.markdown("""
### 🔧 Troubleshooting (Clerk)

- **Login fails** → ask admin to reset
- **Student not found** → ensure Excel file is uploaded
- **Need help** → contact the administrator or developer
            """)

    # ---------------- IT OFFICER ----------------
    elif role == "it_officer":
        t1, t2, t3, t4 = st.tabs([
            "🚀 Getting Started",
            "📅 Timetable Setup",
            "🖥️ System Health",
            "🔧 Troubleshooting",
        ])

        with t1:
            st.markdown("""
### Welcome, IT Officer

Your role is technical:
- Manage timetable setup and generation
- Monitor system health
- Download backups
- Restart the app if needed

**You do NOT see:** Fee pages, academic marks entry, account management.
            """)

        with t2:
            st.markdown("""
### 📅 Timetable (IT Officer)

**Setup:** Settings → ⚙️ Timetable Setup (all sub-tabs)

**Check load:** 📊 Teacher Load Report

**Generate:** 📅 Timetable → 🔄 Generate Timetable

**Export:** per-class, per-teacher PDFs
            """)

        with t3:
            st.markdown("""
### 🖥️ System Health (IT Officer)

Settings → 🖥️ System Health shows:
- Database status (🟢 Online / 🔴 Offline)
- User counts by role
- Data table counts
- Quick backup button

**If DB shows 🔴 Offline** → check internet → contact developer immediately.
            """)

        with t4:
            st.markdown("""
### 🔧 Troubleshooting (IT Officer)

**App won't start** → refresh, wait 60s, check internet

**Timetable fails** → check 📊 Teacher Load Report, verify every class totals 40 periods

**DB offline** → contact developer

**Backup failing** → check storage space

**📞 Developer:** Stephen Kithandule · 0759120553 · stephenkithandule@gmail.com
            """)

    # ---------------- STUDENT ----------------
    elif role == "student":
        st.markdown("### 👋 Welcome, Student")
        st.info("This guide shows how to view your own academic information. You cannot see other students' data or school management pages.")

        st.markdown("""
### 🎓 What You Can Do

1. **My Dashboard** — see your average, grade, and rank
2. **Learning Centre** — view assignments and submit work
3. **Online Tests & Quizzes** — take quizzes set by teachers
4. **My Profile** — view your account details
5. **Change Password** — update your login password

---

### 📄 Viewing Your Report Card

1. Sidebar → **My Dashboard**
2. Click **⬇️ Download My Report Card (PDF)**
3. Save or print

Your report card shows:
- Subject scores
- Grades
- Stream position
- School position
- Term-by-term progression

---

### 📝 Submitting Assignments

1. Sidebar → **Learning Centre**
2. Find the assignment
3. Upload your file
4. Click **📤 Submit Work**

---

### 🔐 Forgot Your Password?

Ask your **class teacher** or the **school administrator** to reset it. Your password cannot be reset by yourself.

---

### 📞 Need Help?

Contact the school office or your class teacher.
            """)

    # ---------------- PARENT ----------------
    elif role == "parent":
        st.markdown("### 👋 Welcome, Parent / Guardian")
        st.info("This guide shows how to view your child's progress and fee status. You can only see your own child's information.")

        st.markdown("""
### 👨‍👩‍👧 What You Can Do

1. **Parent Portal** — view your child's academic progress
2. **Fee Status** — check fee balance and payment history
3. **Report Card** — download your child's official report card
4. **Change Password** — update your login password

---

### 📄 Viewing Your Child's Report Card

1. Sidebar → **Parent Portal**
2. If you have multiple children, select the child
3. Click **⬇️ Download Report Card (PDF)**

Your child's report shows:
- Subject scores and grades
- Stream mean comparison
- Position in class and school
- Charts of progression

---

### 💰 Checking Fee Balance

1. Sidebar → **Parent Portal**
2. Scroll to **💰 Fee Status**
3. See term fee, amount paid, balance

---

### 🔐 Forgot Your Password?

Contact the **school office** or the **bursar** to reset your password.

---

### 📞 Need Help?

Contact the school office directly. Do not share your password with anyone.
            """)

    # ---------------- FALLBACK ----------------
    else:
        st.info("Help is not available for your account type. Please contact the school administrator.")
# ============================================================
# TIMETABLE ADVISOR PAGE
# ============================================================

elif page == "🤖 Timetable Advisor":
    if st.session_state.user_role not in ["admin", "exams", "it_officer"]:
        st.error("🔒 You don't have access to the Timetable Advisor.")
        st.stop()

    st.subheader("🤖 Timetable Advisor")
    st.caption("Analyse whether your current or proposed timetable setup is feasible — before you waste time generating.")

    advisor_tab1, advisor_tab2 = st.tabs(["🔍 Analyse Current Setup", "🎯 Simulate Custom Setup"])

    # ============================================================
    # TAB 1 — Analyse Current Setup
    # ============================================================
    with advisor_tab1:
        st.markdown("### Analyse My Current Timetable Setup")
        st.caption("Reads teachers, classes, and subject assignments from the cloud and tells you if the setup can produce a timetable.")

        if st.button("🔍 Analyse Current Setup", type="primary", use_container_width=True, key="advisor_analyse_current"):
            teachers = tt_get_teachers()
            assignments = tt_get_class_teacher_assignments()
            subjects = tt_get_subjects()
            classes = tt_get_all_classes()

            if not teachers:
                st.error("No teachers found. Add teachers first in Settings → ⚙️ Timetable Setup → 👨‍🏫 Teachers.")
            elif not assignments:
                st.error("No class-subject assignments found. Set them up in Settings → ⚙️ Timetable Setup → 📚 Assignments.")
            else:
                result = tt_advisor_analyse(teachers, classes, assignments, subjects)
                result["teachers"] = teachers
                result["classes"] = classes

                st.divider()
                st.markdown("### 📋 Analysis Result")
                tt_advisor_render_report(result)

                st.divider()
                st.markdown("### 👨‍🏫 Individual Teacher Loads")
                loads = tt_teacher_load_report()
                if loads:
                    df_loads = pd.DataFrame(loads)
                    st.dataframe(df_loads, use_container_width=True, hide_index=True)

    # ============================================================
    # TAB 2 — Simulate Custom Setup
    # ============================================================
    with advisor_tab2:
        st.markdown("### Simulate a Custom Setup")
        st.caption("Enter teachers and classes manually to test a hypothetical setup. Nothing is saved to the cloud.")

        st.markdown("#### Step 1 — Enter Teachers")
        st.caption("One teacher per line: `Name | Subjects | Max periods per day`")

        teachers_text = st.text_area(
            "Teachers",
            height=180,
            key="advisor_sim_teachers",
            value="""Mr. Kamau | Maths, Physics | 6
Ms. Wanjiku | English, Kiswahili | 6
Mr. Otieno | Biology, Chemistry | 6"""
        )

        st.markdown("#### Step 2 — Enter Classes")
        st.caption("One class per line: `Class Name | Required periods per week` (usually 40)")

        classes_text = st.text_area(
            "Classes",
            height=120,
            key="advisor_sim_classes",
            value="""FORM 1 EAST | 40
FORM 1 WEST | 40
FORM 2 EAST | 40"""
        )

        st.markdown("#### Step 3 — Subject Periods Per Week Per Class")
        st.caption("One subject per line: `Subject | Periods per class per week`")

        subjects_text = st.text_area(
            "Subjects",
            height=200,
            key="advisor_sim_subjects",
            value="""Maths | 4
English | 4
Kiswahili | 3
Biology | 3
Chemistry | 3
Physics | 3
History | 2
Geography | 2
CRE/IRE | 2
Business | 2
Agriculture | 2
Computer | 2
PE | 1
Assembly | 2
Free Study | 3"""
        )

        if st.button("🎯 Simulate This Setup", type="primary", use_container_width=True, key="advisor_simulate"):
            sim_teachers = []
            for line in teachers_text.strip().split("\n"):
                if "|" not in line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 3:
                    continue
                try:
                    max_pd = int(parts[2])
                except Exception:
                    max_pd = 6
                sim_teachers.append({
                    "full_name": parts[0],
                    "subjects_taught": parts[1],
                    "max_periods_per_day": max_pd,
                })

            sim_classes = []
            for line in classes_text.strip().split("\n"):
                if "|" not in line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                if not parts:
                    continue
                sim_classes.append(parts[0])

            sim_subjects_map = {}
            for line in subjects_text.strip().split("\n"):
                if "|" not in line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 2:
                    continue
                try:
                    sim_subjects_map[parts[0]] = int(parts[1])
                except Exception:
                    pass

            sim_assignments = []
            for cls in sim_classes:
                for subj, ppw in sim_subjects_map.items():
                    sim_assignments.append({
                        "class_name": cls,
                        "subject_name": subj,
                        "periods_per_week": ppw,
                    })

            if not sim_teachers or not sim_classes or not sim_assignments:
                st.error("Please fill in teachers, classes, and subjects properly.")
            else:
                result = tt_advisor_analyse(sim_teachers, sim_classes, sim_assignments, [])
                result["teachers"] = sim_teachers
                result["classes"] = sim_classes

                st.divider()
                st.markdown("### 📋 Simulation Result")
                tt_advisor_render_report(result)
                st.caption("ℹ️ This is a simulation only. Nothing was saved to the database.")

    st.stop()
        


elif page == "🤖 AI Advisor":
    if st.session_state.user_role not in ["admin", "exams", "it_officer"]:
        st.error("🔒 You don't have access to the AI Advisor.")
        st.stop()
    render_ai_advisor()




elif page == "Settings":
    st.subheader("School Profile & System Settings")
    tab_profile, tab_password, tab_teachers, tab_clerks, tab_parents, tab_students, tab_format, tab_exams, tab_admins, tab_tt_setup, tab_ito, tab_backup, tab_bulk, tab_health = st.tabs([
        "🏫 School Profile",
        "🔒 Change Password",
        "👨‍🏫 Teacher Accounts",
        "💼 Clerk Accounts",
        "👨‍👩‍👧 Parent Accounts",
        "🎓 Student Accounts",
        "📄 Excel Format Guide",
        "🎓 Exams Officer Accounts",
        "🛡️ Admin Accounts",
        "⚙️ Timetable Setup",
        "🖥️ IT Officer Accounts",
        "💾 Backup & Data",
        "📥 Bulk Import",
        "🖥️ System Health"
    ])

    # ============================================================
        # ============================================================
    # TAB 1: School Profile
    # ============================================================
    with tab_profile:
        if st.session_state.user_role not in ["admin", "exams"]:
            st.info("🔒 Only administrators and examination officers can access School Profile settings.")
        else:
            is_admin = st.session_state.user_role == "admin"

            if not is_admin:
                st.info("ℹ️ View-only mode. Only administrators can edit school profile settings.")

            left, right = st.columns(2)
            with left:
                new_name = st.text_input("School name", value=st.session_state.school_name, disabled=not is_admin)
                address = st.text_input("School address", value=st.session_state.school_address, disabled=not is_admin)
                phone = st.text_input("School phone", value=st.session_state.school_phone, disabled=not is_admin)
                email = st.text_input("School email", value=st.session_state.school_email, disabled=not is_admin)
                motto = st.text_input("School motto", value=st.session_state.get("school_motto", ""), placeholder="e.g. Learn • Grow • Succeed", disabled=not is_admin)
            with right:
                academic_year = st.text_input("Academic year", value=st.session_state.academic_year, disabled=not is_admin)
                current_term = st.selectbox(
                    "Current term", ["Term 1", "Term 2", "Term 3"],
                    index=["Term 1", "Term 2", "Term 3"].index(st.session_state.current_term)
                    if st.session_state.current_term in ["Term 1", "Term 2", "Term 3"] else 2,
                    disabled=not is_admin
                )
                all_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                teaching_days = st.multiselect(
                    "Teaching days",
                    all_days,
                    default=st.session_state.get("teaching_days", all_days[:5]),
                    disabled=not is_admin,
                    help="Select the days your school teaches. Normally Mon–Fri."
                )
                if is_admin:
                    logo = st.file_uploader("School logo", type=["png", "jpg", "jpeg"], key="school_logo_upload")
                    if logo is not None:
                        st.image(logo, width=120)
                else:
                    logo = None
                    if st.session_state.get("school_logo"):
                        st.image(st.session_state.school_logo, width=120)

            st.divider()
            st.write("### Report Card Signatures & Principal Comment")
            sig_left, sig_right = st.columns(2)
            with sig_left:
                teacher_name = st.text_input("Class teacher name", value=st.session_state.class_teacher_name, disabled=not is_admin)
                if is_admin:
                    teacher_sig = st.file_uploader("Teacher signature", type=["png", "jpg", "jpeg"], key="teacher_signature_upload")
                    if teacher_sig is not None:
                        st.image(teacher_sig, width=180)
                else:
                    teacher_sig = None
                    if st.session_state.get("teacher_signature"):
                        st.image(st.session_state.teacher_signature, width=180)
            with sig_right:
                principal_name = st.text_input("Principal name", value=st.session_state.principal_name, disabled=not is_admin)
                if is_admin:
                    principal_sig = st.file_uploader("Principal signature", type=["png", "jpg", "jpeg"], key="principal_signature_upload")
                    if principal_sig is not None:
                        st.image(principal_sig, width=180)
                else:
                    principal_sig = None
                    if st.session_state.get("principal_signature"):
                        st.image(st.session_state.principal_signature, width=180)
            principal_comment = st.text_area(
                "Default Principal comment",
                value=st.session_state.principal_comment,
                height=100,
                disabled=not is_admin
            )

            if is_admin:
                if st.button("Save School Profile", type="primary", use_container_width=True):
                    st.session_state.school_name = new_name.strip() or DEFAULT_SCHOOL
                    st.session_state.school_address = address.strip()
                    st.session_state.school_phone = phone.strip()
                    st.session_state.school_email = email.strip()
                    st.session_state.school_motto = motto.strip()
                    st.session_state.academic_year = academic_year.strip() or "2026"
                    st.session_state.current_term = current_term
                    st.session_state.class_teacher_name = teacher_name.strip() or "Class Teacher"
                    st.session_state.principal_name = principal_name.strip() or "Principal / Head Teacher"
                    st.session_state.principal_comment = principal_comment.strip()
                    if logo is not None:
                        st.session_state.school_logo = logo.getvalue()
                    if teacher_sig is not None:
                        st.session_state.teacher_signature = teacher_sig.getvalue()
                    if principal_sig is not None:
                        st.session_state.principal_signature = principal_sig.getvalue()
                    save_school_settings()
                    st.success("✅ Saved to cloud. These settings will persist across restarts.")


    # ============================================================
        # ============================================================
    # TAB 3: Teacher Accounts
       # ============================================================
    # TAB 2: Change Password
    # ============================================================
    with tab_password:
        st.write("### Change your password")
        st.caption(f"Signed in as: **{st.session_state.username}** ({st.session_state.user_role})")
        old_pw = st.text_input("Current password", type="password", key="pw_old")
        new_pw = st.text_input("New password", type="password", key="pw_new")
        confirm_pw = st.text_input("Confirm new password", type="password", key="pw_confirm")
        if st.button("Update Password", type="primary", use_container_width=True):
            if not old_pw or not new_pw or not confirm_pw:
                st.error("Fill in all fields.")
            elif new_pw != confirm_pw:
                st.error("New passwords do not match.")
            elif len(new_pw) < 6:
                st.error("Password must be at least 6 characters.")
            else:
                user = authenticate_user(st.session_state.username, old_pw)
                if not user:
                    st.error("Current password is incorrect.")
                else:
                    change_user_password(st.session_state.username, new_pw)
                    st.success("Password updated.")
    # ============================================================
    with tab_teachers:
        if st.session_state.user_role not in ["admin"]:
            st.info("🔒 Only administrators can manage teacher accounts.")
        else:
            st.caption("Create and manage teacher accounts. Each teacher gets their own username and password.")
            teachers = get_teachers()
            if teachers:
                df_teachers = pd.DataFrame(teachers)
                df_teachers.columns = ["Username", "Full Name"]
                st.dataframe(df_teachers, use_container_width=True, hide_index=True)

            t1, t2 = st.columns(2)
            with t1:
                teacher_username = st.text_input("Teacher username", placeholder="e.g. mr.kamau", key="new_teacher_username")
                teacher_full_name = st.text_input("Teacher full name", placeholder="e.g. Mr. Peter Kamau", key="new_teacher_full_name")
            with t2:
                teacher_password = st.text_input("Teacher password", type="password", key="new_teacher_password")
                st.caption("Password should be at least 6 characters.")

            tb1, tb2 = st.columns(2)
            with tb1:
                if st.button("➕ Create / Update Teacher", type="primary", use_container_width=True, key="create_teacher_btn"):
                    if not teacher_username.strip() or not teacher_full_name.strip() or not teacher_password.strip():
                        st.error("Enter username, full name and password.")
                    elif len(teacher_password) < 6:
                        st.error("Password must be at least 6 characters.")
                    else:
                        try:
                            create_or_update_teacher(teacher_username.strip(), teacher_full_name.strip(), teacher_password)
                            st.success(f"Teacher '{teacher_username.strip()}' saved. Share the username and password with them.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
            with tb2:
                with st.expander("🗑️ Delete a teacher"):
                    if teachers:
                        delete_options = [t["username"] for t in teachers]
                        selected_delete = st.selectbox("Select teacher to delete", delete_options, key="delete_teacher_select")
                        confirm_del = st.checkbox("I understand this will remove the teacher account.", key="confirm_delete_teacher")
                        if st.button("Delete Teacher", type="secondary", disabled=not confirm_del, use_container_width=True, key="delete_teacher_btn"):
                            try:
                                delete_teacher(selected_delete)
                                st.success(f"Deleted {selected_delete}.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                    else:
                        st.info("No teachers to delete.")

    # ============================================================
        # ============================================================
        # ============================================================
    # TAB 4: Clerk Accounts
    # ============================================================
    with tab_clerks:
        if st.session_state.user_role not in ["admin"]:
            st.info("🔒 Only administrators can manage clerk accounts.")
        else:
            st.caption("Create clerk accounts for bursars/accountants. Clerks see only fee pages.")
            try:
                clerk_rows = supabase.table("users").select("username,student_name").eq("role", "clerk").order("username").execute().data
                if clerk_rows:
                    df_clerks = pd.DataFrame(clerk_rows)
                    df_clerks.columns = ["Username", "Full Name"]
                    st.dataframe(df_clerks, use_container_width=True, hide_index=True)
            except Exception:
                pass

            ck1, ck2 = st.columns(2)
            with ck1:
                clerk_username = st.text_input("Clerk username", placeholder="e.g. bursar.jane", key="new_clerk_username")
                clerk_full_name = st.text_input("Clerk full name", placeholder="e.g. Jane Wanjiru (Bursar)", key="new_clerk_full_name")
            with ck2:
                clerk_password = st.text_input("Clerk password", type="password", key="new_clerk_password")
                st.caption("Password should be at least 6 characters.")

            clerk_signature = st.file_uploader(
                "Clerk signature (PNG/JPG, optional)",
                type=["png", "jpg", "jpeg"],
                key="new_clerk_signature"
            )
            if clerk_signature is not None:
                st.image(clerk_signature, width=180, caption="Signature preview")

            cb1, cb2 = st.columns(2)
            with cb1:
                if st.button("➕ Create / Update Clerk", type="primary", use_container_width=True, key="create_clerk_btn"):
                    if not clerk_username.strip() or not clerk_full_name.strip() or not clerk_password.strip():
                        st.error("Enter username, full name and password.")
                    elif len(clerk_password) < 6:
                        st.error("Password must be at least 6 characters.")
                    else:
                        try:
                            hashed = hash_password(clerk_password)
                            sig_b64 = None
                            if clerk_signature is not None:
                                sig_b64 = base64.b64encode(clerk_signature.getvalue()).decode("utf-8")

                            existing = supabase.table("users").select("username").eq("username", clerk_username.strip()).execute()
                            if existing.data:
                                update_payload = {
                                    "password": hashed, "role": "clerk",
                                    "student_name": clerk_full_name.strip()
                                }
                                if sig_b64 is not None:
                                    update_payload["signature_base64"] = sig_b64
                                supabase.table("users").update(update_payload).eq("username", clerk_username.strip()).execute()
                            else:
                                insert_payload = {
                                    "username": clerk_username.strip(), "password": hashed,
                                    "role": "clerk", "student_name": clerk_full_name.strip()
                                }
                                if sig_b64 is not None:
                                    insert_payload["signature_base64"] = sig_b64
                                supabase.table("users").insert(insert_payload).execute()
                            st.success(f"✅ Clerk '{clerk_username.strip()}' saved. Share the username and password with them.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
            with cb2:
                with st.expander("🗑️ Delete a clerk"):
                    try:
                        clerk_list = supabase.table("users").select("username").eq("role", "clerk").order("username").execute().data
                        if clerk_list:
                            delete_options = [c["username"] for c in clerk_list]
                            selected_delete = st.selectbox("Select clerk to delete", delete_options, key="delete_clerk_select")
                            confirm_del = st.checkbox("I understand this will remove the clerk account.", key="confirm_delete_clerk")
                            if st.button("Delete Clerk", type="secondary", disabled=not confirm_del, use_container_width=True, key="delete_clerk_btn"):
                                try:
                                    supabase.table("users").delete().eq("username", selected_delete).eq("role", "clerk").execute()
                                    st.success(f"Deleted {selected_delete}.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                        else:
                            st.info("No clerks to delete.")
                    except Exception:
                        st.info("No clerks to delete.")



        # ============================================================
    # TAB 5: Parent Accounts
    # ============================================================
    with tab_parents:
        if st.session_state.user_role not in ["admin", "exams"]:
            st.info("🔒 Only administrators and examination officers can manage parent accounts.")
        else:
            st.caption("Link a parent account to one or more student names. Use | between multiple children.")
            try:
                parent_rows = supabase.table("parents").select("username,parent_name,child_names").order("username").execute().data
                if parent_rows:
                    st.dataframe(pd.DataFrame(parent_rows), use_container_width=True, hide_index=True)
            except Exception:
                pass

            pa1, pa2 = st.columns(2)
            with pa1:
                parent_username = st.text_input("Parent username", key="new_parent_username")
                parent_name = st.text_input("Parent / Guardian name", key="new_parent_name")
            with pa2:
                parent_password = st.text_input("Parent password", type="password", key="new_parent_password")
                linked_children = st.text_input("Linked student name(s)", placeholder="e.g. Jane Wanjiku | Peter Kamau", key="new_parent_children")

            if st.button("➕ Create / Update Parent Account", type="primary", use_container_width=True):
                if not parent_username.strip() or not parent_name.strip() or not parent_password.strip() or not linked_children.strip():
                    st.error("Fill in all fields.")
                else:
                    try:
                        create_or_update_parent(parent_username.strip(), parent_name.strip(), parent_password, linked_children.strip())
                        st.success("Parent account saved to cloud.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

    # ============================================================
        # ============================================================
    # TAB 6: Student Accounts
    # ============================================================
    with tab_students:
        if st.session_state.user_role not in ["admin", "exams"]:
            st.info("🔒 Only administrators and examination officers can manage student accounts.")
        else:
            st.caption("Link a student account to one student name so the student can view their own results.")
            try:
                student_rows = supabase.table("students").select("username,student_full_name").order("username").execute().data
                if student_rows:
                    st.dataframe(pd.DataFrame(student_rows), use_container_width=True, hide_index=True)
            except Exception:
                pass

            sa1, sa2 = st.columns(2)
            with sa1:
                student_username = st.text_input("Student username", key="new_student_username")
                student_full_name = st.text_input("Linked student name", placeholder="e.g. John Mwangi", key="new_student_full_name")
            with sa2:
                student_password = st.text_input("Student password", type="password", key="new_student_password")

            if st.button("➕ Create / Update Student Account", type="primary", use_container_width=True):
                if not student_username.strip() or not student_full_name.strip() or not student_password.strip():
                    st.error("Fill in all fields.")
                else:
                    try:
                        create_or_update_student(student_username.strip(), student_full_name.strip(), student_password)
                        st.success("Student account saved to cloud.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

    # ============================================================
    with tab_format:
        st.subheader("📄 Excel Format Guide")
        st.caption("The exact columns your student_results.xlsx must contain for the app to read it correctly.")

        st.markdown("### 1️⃣ Identity Columns (required)")
        st.markdown("""
| Column name | Example | Notes |
|---|---|---|
| `name` | JOHN MWANGI | Student full name - must match parent/student account links |
| `stream` | FORM 2 EAST | Class / stream |
| `admission number` | 1234 | Student ID (optional but recommended) |
""")

        st.markdown("### 2️⃣ Term Columns (required for each term you want to track)")
        st.markdown("""
For **every term**, the app expects 3 types of columns:

| Column type | Pattern | Example | Meaning |
|---|---|---|---|
| Term average | `yXtY_avg` | `y2t3_avg` | Average score for Year 2, Term 3 |
| Term total | `yXtYtotals` | `y2t3totals` | Total marks for that term |
| Subject mark | `yXtY<subject>` | `y2t3maths` | Individual subject score |

**Rule:** `X` = year number, `Y` = term number. So:
- `y1t1` = Year 1, Term 1
- `y2t3` = Year 2, Term 3
- `y3t1` = Year 3, Term 1 (auto-detected!)
        """)

        st.markdown("### 3️⃣ Example header row")
        st.code(
            "name | stream | admission number | "
            "y1t1maths | y1t1english | y1t1biology | y1t1totals | y1t1_avg | "
            "y1t2maths | y1t2english | y1t2biology | y1t2totals | y1t2_avg | "
            "y2t1maths | y2t1english | y2t1biology | y2t1totals | y2t1_avg",
            language="text"
        )

        st.markdown("### 4️⃣ Full example (one student row)")
        st.code(
            "JOHN MWANGI | FORM 2 EAST | 1234 | "
            "72 | 68 | 75 | 215 | 71.7 | "
            "78 | 74 | 80 | 232 | 77.3 | "
            "82 | 78 | 85 | 245 | 81.7",
            language="text"
        )

        st.info(
            "💡 **Tip:** Subject names can be anything — `maths`, `math`, `mathematics` — "
            "the app displays whatever you type."
        )

        st.divider()
        st.markdown("### 📥 Download Excel Template")
        st.write("Get a ready-to-fill Excel file with all the correct column names.")

        if st.button("📄 Prepare Excel Template", type="primary"):
            template_data = {
                "name": ["JOHN MWANGI", "MARY NJERI"],
                "stream": ["FORM 2 EAST", "FORM 1 WEST"],
                "admission number": ["1234", "1235"],
                "y1t1maths": [72, 68],
                "y1t1english": [68, 74],
                "y1t1biology": [75, 78],
                "y1t1totals": [215, 220],
                "y1t1_avg": [71.7, 73.3],
                "y1t2maths": [78, 70],
                "y1t2english": [74, 76],
                "y1t2biology": [80, 82],
                "y1t2totals": [232, 228],
                "y1t2_avg": [77.3, 76.0],
                "y2t1maths": [82, 74],
                "y2t1english": [78, 78],
                "y2t1biology": [85, 80],
                "y2t1totals": [245, 232],
                "y2t1_avg": [81.7, 77.3],
            }
            template_df = pd.DataFrame(template_data)
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                template_df.to_excel(writer, index=False, sheet_name="Student Results")
            buf.seek(0)
            st.download_button(
                "⬇️ Download Excel Template",
                data=buf.getvalue(),
                file_name="Student_Results_Template.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    # ============================================================
        # ============================================================
        # ============================================================
    # TAB 8: Exams Officer Accounts
    # ============================================================
    with tab_exams:
        if st.session_state.user_role not in ["admin"]:
            st.info("🔒 Only administrators can manage exams officer accounts.")
        else:
            st.caption("Create and manage examination officer accounts. Admin can reset passwords here.")
            try:
                exams_rows = supabase.table("users").select("username,student_name").eq("role", "exams").order("username").execute().data
                if exams_rows:
                    df_exams = pd.DataFrame(exams_rows)
                    df_exams.columns = ["Username", "Full Name"]
                    st.dataframe(df_exams, use_container_width=True, hide_index=True)
            except Exception:
                pass

            ex1, ex2 = st.columns(2)
            with ex1:
                exams_username = st.text_input("Exams Officer username", placeholder="e.g. exams", key="new_exams_username")
                exams_full_name = st.text_input("Exams Officer full name", placeholder="e.g. Examination Officer", key="new_exams_full_name")
            with ex2:
                exams_password = st.text_input("Exams Officer password", type="password", key="new_exams_password")
                st.caption("Password should be at least 6 characters.")

            eb1, eb2 = st.columns(2)
            with eb1:
                if st.button("➕ Create / Update Exams Officer", type="primary", use_container_width=True, key="create_exams_btn"):
                    if not exams_username.strip() or not exams_full_name.strip() or not exams_password.strip():
                        st.error("Enter username, full name and password.")
                    elif len(exams_password) < 6:
                        st.error("Password must be at least 6 characters.")
                    else:
                        try:
                            hashed = hash_password(exams_password)
                            existing = supabase.table("users").select("username").eq("username", exams_username.strip()).execute()
                            if existing.data:
                                supabase.table("users").update({
                                    "password": hashed, "role": "exams",
                                    "student_name": exams_full_name.strip()
                                }).eq("username", exams_username.strip()).execute()
                            else:
                                supabase.table("users").insert({
                                    "username": exams_username.strip(), "password": hashed,
                                    "role": "exams", "student_name": exams_full_name.strip()
                                }).execute()
                            st.success(f"✅ Exams Officer '{exams_username.strip()}' saved. Password updated.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
            with eb2:
                with st.expander("🗑️ Delete an exams officer"):
                    try:
                        exams_list = supabase.table("users").select("username").eq("role", "exams").order("username").execute().data
                        if exams_list:
                            delete_options = [c["username"] for c in exams_list]
                            selected_delete = st.selectbox("Select exams officer to delete", delete_options, key="delete_exams_select")
                            confirm_del = st.checkbox("I understand this will remove the exams officer account.", key="confirm_delete_exams")
                            if st.button("Delete Exams Officer", type="secondary", disabled=not confirm_del, use_container_width=True, key="delete_exams_btn"):
                                try:
                                    supabase.table("users").delete().eq("username", selected_delete).eq("role", "exams").execute()
                                    st.success(f"Deleted {selected_delete}.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                        else:
                            st.info("No exams officers to delete.")
                    except Exception:
                        st.info("No exams officers to delete.")

        # ============================================================
        # ============================================================
    # TAB 10: Timetable Setup
    # ============================================================
    with tab_tt_setup:
        if st.session_state.user_role not in ["admin", "exams", "it_officer"]:
            st.info("🔒 Only administrators, examination officers and IT officers can set up the timetable.")
        else:
            st.subheader("⚙️ Timetable Setup")
            st.caption("Add teachers and assign them to subjects per class. Once this is done, the timetable can be generated.")

            setup_tab1, setup_tab2, setup_tab3, setup_tab4, setup_tab5 = st.tabs(["👨‍🏫 Teachers", "📚 Assignments", "🕐 Periods", "📖 Subjects", "🏫 Classes"])

            # ---------- TAB A: Teachers ----------
            with setup_tab1:
                st.markdown("### Teachers")
                teachers = tt_get_teachers()
                if teachers:
                    df_t = pd.DataFrame(teachers)
                    df_t = df_t[["full_name", "subjects_taught", "max_periods_per_day"]]
                    df_t.columns = ["Full Name", "Subjects Taught", "Max Periods/Day"]
                    st.dataframe(df_t, use_container_width=True, hide_index=True)
                else:
                    st.info("No teachers added yet. Add the first one below.")

                st.divider()
                st.markdown("### ➕ Add / Update Teacher")
                t1, t2, t3 = st.columns([2, 2, 1])
                with t1:
                    new_teacher_name = st.text_input("Teacher full name", placeholder="e.g. Mr. Peter Kamau", key="tt_new_teacher_name")
                with t2:
                    new_teacher_subjects = st.text_input("Subjects taught", placeholder="e.g. Maths, Physics", key="tt_new_teacher_subjects")
                with t3:
                    new_teacher_max = st.number_input("Max periods/day", min_value=1, max_value=10, value=6, step=1, key="tt_new_teacher_max")

                if st.button("➕ Save Teacher", type="primary", use_container_width=True, key="tt_save_teacher"):
                    if not new_teacher_name.strip():
                        st.error("Enter the teacher's name.")
                    else:
                        try:
                            tt_create_or_update_teacher(new_teacher_name.strip(), new_teacher_subjects.strip(), new_teacher_max)
                            st.success(f"Teacher '{new_teacher_name.strip()}' saved.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

                if teachers:
                    with st.expander("🗑️ Delete a teacher"):
                        del_opts = {f"{t['full_name']} ({t.get('subjects_taught','')})": t["id"] for t in teachers}
                        del_label = st.selectbox("Select teacher to delete", list(del_opts.keys()), key="tt_del_teacher_select")
                        confirm_del = st.checkbox("I understand this will remove the teacher.", key="tt_del_teacher_confirm")
                        if st.button("Delete Teacher", type="secondary", disabled=not confirm_del, key="tt_del_teacher_btn"):
                            try:
                                tt_delete_teacher(del_opts[del_label])
                                st.success("Deleted.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")

            # ---------- TAB B: Assignments ----------
            with setup_tab2:
                st.markdown("### Class ↔ Subject ↔ Teacher")
                st.caption("Assign a teacher to each subject for each class. Subject period counts come from the timetable master table.")

                all_classes = tt_get_all_classes()
                teachers = tt_get_teachers()

                if not all_classes:
                    st.warning("No classes found in the timetable master table.")
                elif not teachers:
                    st.warning("Add teachers first (👨‍🏫 Teachers tab).")
                else:
                    selected_class = st.selectbox("Select class", all_classes, key="tt_assign_class")
                    st.markdown(f"#### {selected_class}")

                    assignments = tt_get_class_teacher_assignments(selected_class)
                    teacher_options = ["(unassigned)"] + [f"{t['full_name']}" for t in teachers]
                    teacher_id_by_name = {f"{t['full_name']}": t["id"] for t in teachers}

                    with st.form(key=f"tt_assign_form_{selected_class}"):
                        pending = {}
                        for a in assignments:
                            c1, c2, c3 = st.columns([2, 2, 1])
                            with c1:
                                st.markdown(f"**{a['subject_name']}**")
                            with c2:
                                current_teacher = None
                                if a.get("teacher_id"):
                                    for t in teachers:
                                        if t["id"] == a["teacher_id"]:
                                            current_teacher = t["full_name"]
                                            break
                                idx = teacher_options.index(current_teacher) if current_teacher in teacher_options else 0
                                sel = st.selectbox(
                                    f"Teacher for {a['subject_name']}",
                                    teacher_options,
                                    index=idx,
                                    key=f"tt_t_{selected_class}_{a['subject_name']}",
                                    label_visibility="collapsed"
                                )
                                pending[a["subject_name"]] = sel
                            with c3:
                                st.caption(f"{a['periods_per_week']}p/w")

                        submitted = st.form_submit_button("💾 Save All Assignments", type="primary", use_container_width=True)
                        if submitted:
                            try:
                                for subj, sel in pending.items():
                                    tid = teacher_id_by_name.get(sel) if sel != "(unassigned)" else None
                                    ppw = next(a["periods_per_week"] for a in assignments if a["subject_name"] == subj)
                                    tt_assign_teacher(selected_class, subj, tid, ppw)
                                st.success(f"Saved assignments for {selected_class}.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")

            # ---------- TAB C: Periods ----------
            with setup_tab3:
                st.markdown("### 🕐 School Period Structure")
                st.caption("View and edit the school's daily period times. Breaks are automatically shown between periods in the timetable.")

                all_periods = tt_get_all_periods()
                teaching_periods = sorted([p for p in all_periods if not p.get("is_break")], key=lambda x: x["period_no"])
                break_periods = sorted([p for p in all_periods if p.get("is_break")], key=lambda x: x.get("start_time") or "")

                st.markdown("#### 📚 Teaching Periods")
                if teaching_periods:
                    for p in teaching_periods:
                        c1, c2, c3, c4, c5 = st.columns([1, 2, 2, 1, 1])
                        with c1:
                            st.markdown(f"**P{p['period_no']}**")
                        with c2:
                            new_start = st.text_input(f"Start (P{p['period_no']})", value=p.get("start_time", ""), key=f"tt_start_{p['id']}", label_visibility="collapsed")
                        with c3:
                            new_end = st.text_input(f"End (P{p['period_no']})", value=p.get("end_time", ""), key=f"tt_end_{p['id']}", label_visibility="collapsed")
                        with c4:
                            if st.button("💾", key=f"tt_save_{p['id']}", help="Save time"):
                                try:
                                    tt_update_period(p["id"], new_start, new_end)
                                    st.success(f"P{p['period_no']} updated.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                        with c5:
                            if st.button("🗑️", key=f"tt_del_{p['id']}", help="Delete period"):
                                try:
                                    tt_delete_period(p["id"])
                                    st.success(f"P{p['period_no']} deleted.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                else:
                    st.info("No teaching periods configured.")

                st.markdown("#### ☕ Breaks")
                if break_periods:
                    for b in break_periods:
                        c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 1, 1])
                        with c1:
                            new_label = st.text_input(f"Label {b['id']}", value=b.get("break_label", ""), key=f"tt_blabel_{b['id']}", label_visibility="collapsed")
                        with c2:
                            new_bstart = st.text_input(f"B-Start {b['id']}", value=b.get("start_time", ""), key=f"tt_bstart_{b['id']}", label_visibility="collapsed")
                        with c3:
                            new_bend = st.text_input(f"B-End {b['id']}", value=b.get("end_time", ""), key=f"tt_bend_{b['id']}", label_visibility="collapsed")
                        with c4:
                            if st.button("💾", key=f"tt_bsave_{b['id']}", help="Save break"):
                                try:
                                    tt_update_period(b["id"], new_bstart, new_bend, new_label)
                                    st.success(f"Break updated.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                        with c5:
                            if st.button("🗑️", key=f"tt_bdel_{b['id']}", help="Delete break"):
                                try:
                                    tt_delete_period(b["id"])
                                    st.success("Break deleted.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                else:
                    st.info("No breaks configured.")

                st.divider()
                st.markdown("#### ➕ Add a Teaching Period")

                max_p = max([p["period_no"] for p in teaching_periods], default=0)
                add1, add2, add3, add4 = st.columns([1, 2, 2, 1])
                with add1:
                    new_p_no = st.number_input("Period #", min_value=1, max_value=20, value=max_p + 1, step=1, key="tt_new_p_no")
                with add2:
                    new_p_start = st.text_input("Start time", placeholder="e.g. 08:00", key="tt_new_p_start")
                with add3:
                    new_p_end = st.text_input("End time", placeholder="e.g. 08:45", key="tt_new_p_end")
                with add4:
                    if st.button("➕ Add", type="primary", key="tt_add_period_btn", use_container_width=True):
                        if not new_p_start.strip() or not new_p_end.strip():
                            st.error("Enter start and end times.")
                        else:
                            try:
                                tt_create_period(new_p_no, new_p_start, new_p_end)
                                st.success(f"P{new_p_no} added.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")

                st.divider()
                st.markdown("#### ➕ Add a Break")

                b1, b2, b3, b4 = st.columns([2, 2, 2, 1])
                with b1:
                    new_b_label = st.text_input("Break label", placeholder="e.g. Morning Break", key="tt_new_b_label")
                with b2:
                    new_b_start = st.text_input("Start time", placeholder="e.g. 10:15", key="tt_new_b_start")
                with b3:
                    new_b_end = st.text_input("End time", placeholder="e.g. 10:35", key="tt_new_b_end")
                with b4:
                    if st.button("➕ Add", type="primary", key="tt_add_break_btn", use_container_width=True):
                        if not new_b_label.strip() or not new_b_start.strip() or not new_b_end.strip():
                            st.error("Fill in all fields.")
                        else:
                            try:
                                tt_create_break(new_b_label, new_b_start, new_b_end)
                                st.success("Break added.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")

                st.info("ℹ️ After changing periods or breaks, regenerate the timetable to apply the new structure.")
                            # ---------- TAB D: Subjects ----------
            with setup_tab4:
                st.markdown("### 📖 Subjects")
                st.caption("Manage subjects taught at the school. Each subject has a weekly period count and optional double-period rules.")

                subjects = tt_get_all_subjects()
                if subjects:
                    st.markdown("#### Current Subjects")
                    for s in subjects:
                        c1, c2, c3, c4, c5, c6 = st.columns([2, 1, 1, 1, 2, 1])
                        with c1:
                            st.markdown(f"**{s['subject_name']}**")
                        with c2:
                            st.markdown(f"{s.get('periods_per_week', 0)} p/w")
                        with c3:
                            st.markdown("🔁 double" if s.get("has_double") else "—")
                        with c4:
                            st.markdown("🔬 lab" if s.get("requires_lab") else "—")
                        with c5:
                            st.caption(s.get("lab_type") or "")
                        with c6:
                            if st.button("🗑️", key=f"tt_del_subj_{s['id']}", help="Delete subject"):
                                try:
                                    tt_delete_subject(s["id"])
                                    st.success(f"Deleted {s['subject_name']}.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                else:
                    st.info("No subjects yet. Add one below.")

                st.divider()
                st.markdown("#### ➕ Add / Update Subject")

                s1, s2 = st.columns(2)
                with s1:
                    subj_name = st.text_input("Subject name", placeholder="e.g. Music", key="tt_new_subj_name")
                    subj_ppw = st.number_input("Periods per week", min_value=1, max_value=15, value=3, step=1, key="tt_new_subj_ppw")
                with s2:
                    subj_has_double = st.checkbox("Has a double period?", key="tt_new_subj_hasdouble")
                    subj_double_count = st.number_input("Number of doubles", min_value=0, max_value=5, value=1 if subj_has_double else 0, step=1, key="tt_new_subj_dcount")

                subj_lab = st.checkbox("Requires a lab or specific room?", key="tt_new_subj_lab")
                subj_lab_type = ""
                if subj_lab:
                    subj_lab_type = st.text_input("Lab / room name", placeholder="e.g. Chemistry Lab", key="tt_new_subj_labtype")

                if st.button("➕ Save Subject", type="primary", use_container_width=True, key="tt_save_subject_btn"):
                    if not subj_name.strip():
                        st.error("Enter a subject name.")
                    else:
                        try:
                            tt_create_or_update_subject(
                                subj_name.strip(),
                                subj_ppw,
                                subj_has_double,
                                subj_double_count,
                                subj_lab,
                                subj_lab_type,
                            )
                            st.success(f"Subject '{subj_name.strip()}' saved.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

                st.info("ℹ️ Adding a subject here does NOT auto-assign teachers. After adding, go to the 📚 Assignments tab to assign teachers to this subject for each class.")
                            # ---------- TAB E: Classes ----------
            with setup_tab5:
                st.markdown("### 🏫 Classes")
                st.caption("Manage the school's classes. Adding a class automatically creates unassigned subject rows for it.")

                classes = tt_get_all_classes()
                if classes:
                    st.markdown("#### Current Classes")
                    for c in classes:
                        c1, c2 = st.columns([4, 1])
                        with c1:
                            st.markdown(f"**{c}**")
                        with c2:
                            if st.button("🗑️", key=f"tt_del_class_{c}", help="Delete class"):
                                try:
                                    tt_delete_class(c)
                                    st.success(f"Deleted {c}.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                else:
                    st.info("No classes yet. Add one below.")

                st.divider()
                st.markdown("#### ➕ Add a Class")
                st.caption("Use the format 'FORM X STREAM' — e.g. FORM 1 EAST, FORM 3 NORTH")

                new_class_name = st.text_input("Class name", placeholder="e.g. FORM 1 NORTH", key="tt_new_class_name")

                if st.button("➕ Add Class", type="primary", use_container_width=True, key="tt_add_class_btn"):
                    if not new_class_name.strip():
                        st.error("Enter a class name.")
                    else:
                        try:
                            tt_create_class(new_class_name)
                            st.success(f"Class '{new_class_name.strip().upper()}' added with all subjects. Go to 📚 Assignments to set teachers.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

                st.info("ℹ️ Deleting a class removes all its subject-teacher assignments and any generated timetable slots for that class.")

    # TAB 9: Admin Accounts
    # ============================================================
    with tab_admins:
        if st.session_state.user_role not in ["admin"]:
            st.info("🔒 Only administrators can manage admin accounts.")
        else:
            st.caption("Create and manage administrator accounts. Admins can reset each other's passwords here — critical for emergency recovery.")
            try:
                admin_rows = supabase.table("users").select("username,student_name").eq("role", "admin").order("username").execute().data
                if admin_rows:
                    df_admins = pd.DataFrame(admin_rows)
                    df_admins.columns = ["Username", "Full Name"]
                    st.dataframe(df_admins, use_container_width=True, hide_index=True)
            except Exception:
                pass

            st.divider()
            st.markdown("### ➕ Create / Update Admin")
            st.caption("If the username already exists, this resets that admin's password and name. If new, this creates a new admin.")

            ad1, ad2 = st.columns(2)
            with ad1:
                admin_username = st.text_input("Admin username", placeholder="e.g. admin or backup_admin", key="new_admin_username")
                admin_full_name = st.text_input("Admin full name", placeholder="e.g. Principal or Backup Administrator", key="new_admin_full_name")
            with ad2:
                admin_password = st.text_input("Admin password", type="password", key="new_admin_password")
                st.caption("Password must be at least 6 characters. **Leave blank** if you only want to update the full name.")

            st.warning("⚠️ Only reset passwords you are authorized to reset. Every reset is permanent.")

            if st.button("➕ Create / Update Admin", type="primary", use_container_width=True, key="create_admin_btn"):
                if not admin_username.strip():
                    st.error("Enter the username.")
                elif not admin_full_name.strip():
                    st.error("Enter the full name.")
                else:
                    try:
                        existing = supabase.table("users").select("username").eq("username", admin_username.strip()).execute()
                        if existing.data:
                            update_payload = {
                                "role": "admin",
                                "student_name": admin_full_name.strip()
                            }
                            if admin_password.strip():
                                if len(admin_password) < 6:
                                    st.error("Password must be at least 6 characters.")
                                    st.stop()
                                update_payload["password"] = hash_password(admin_password)
                            supabase.table("users").update(update_payload).eq("username", admin_username.strip()).execute()
                            if admin_password.strip():
                                st.success(f"✅ Admin '{admin_username.strip()}' updated — password reset.")
                            else:
                                st.success(f"✅ Admin '{admin_username.strip()}' updated — name changed, password unchanged.")
                        else:
                            if not admin_password.strip():
                                st.error("Password is required when creating a NEW admin.")
                                st.stop()
                            if len(admin_password) < 6:
                                st.error("Password must be at least 6 characters.")
                                st.stop()
                            supabase.table("users").insert({
                                "username": admin_username.strip(),
                                "password": hash_password(admin_password),
                                "role": "admin",
                                "student_name": admin_full_name.strip()
                            }).execute()
                            st.success(f"✅ Admin '{admin_username.strip()}' created.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

            st.divider()
            with st.expander("🗑️ Delete an admin account"):
                st.caption("⚠️ You cannot delete the account you are currently logged in with.")
                try:
                    admin_list = supabase.table("users").select("username").eq("role", "admin").order("username").execute().data
                    deletable = [a["username"] for a in admin_list if a["username"] != st.session_state.username] if admin_list else []
                    if deletable:
                        selected_delete = st.selectbox("Select admin to delete", deletable, key="delete_admin_select")
                        confirm_del = st.checkbox("I understand this will permanently remove this admin account.", key="confirm_delete_admin")
                        if st.button("Delete Admin", type="secondary", disabled=not confirm_del, use_container_width=True, key="delete_admin_btn"):
                            try:
                                supabase.table("users").delete().eq("username", selected_delete).eq("role", "admin").execute()
                                st.success(f"Deleted {selected_delete}.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                    else:
                        st.info("No other admin accounts to delete (you can't delete the account you're logged in with).")
                except Exception:
                    st.info("No admins available to delete.")

            # ============================================================
    # TAB 8: Backup & Data
    # ============================================================
    with tab_backup:
        if st.session_state.user_role not in ["admin", "teacher", "exams", "it_officer"]:
            st.info("🔒 Only administrators, teachers, examination officers and IT officers can access Backup.")
        else:
            st.write("### Download a full backup")
            st.caption("ZIP with all cloud tables as JSON files.")
                        st.divider()
            st.markdown("### 📦 Download Full Backup (3 files)")

            st.info(
                "**How to use these files:**\n"
                "- **📊 Excel** — share with the principal. Contains names, usernames, roles. No passwords.\n"
                "- **🔒 Passwords CSV** — keep offline in a safe. Do not email.\n"
                "- **🖨️ PDF** — print and file. Contains account list for the school records."
            )

            col1, col2, col3 = st.columns(3)

            with col1:
                if st.button("📊 Prepare Excel Backup", type="primary", use_container_width=True, key="bk_excel_btn"):
                    try:
                        with st.spinner("Building Excel..."):
                            xlsx = _backup_excel_bytes()
                        st.download_button(
                            "⬇️ Download Excel",
                            data=xlsx,
                            file_name=f"Backup_{st.session_state.school_name.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                            key="bk_excel_dl"
                        )
                    except Exception as e:
                        st.error(f"Excel error: {e}")

            with col2:
                if st.button("🔒 Prepare Passwords CSV", use_container_width=True, key="bk_pw_btn"):
                    try:
                        with st.spinner("Building CSV..."):
                            csv_bytes = _backup_passwords_csv_bytes()
                        st.download_button(
                            "⬇️ Download Passwords",
                            data=csv_bytes,
                            file_name=f"Passwords_{datetime.now().strftime('%Y%m%d')}.csv",
                            mime="text/csv",
                            use_container_width=True,
                            key="bk_pw_dl"
                        )
                        st.warning("⚠️ Keep this file offline. Do not email.")
                    except Exception as e:
                        st.error(f"CSV error: {e}")

            with col3:
                if st.button("🖨️ Prepare Summary PDF", use_container_width=True, key="bk_pdf_btn"):
                    try:
                        with st.spinner("Building PDF..."):
                            pdf_bytes = _backup_summary_pdf_bytes()
                        st.download_button(
                            "⬇️ Download PDF",
                            data=pdf_bytes,
                            file_name=f"Summary_{st.session_state.school_name.replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                            mime="application/pdf",
                            use_container_width=True,
                            key="bk_pdf_dl"
                        )
                    except Exception as e:
                        st.error(f"PDF error: {e}")
            

            st.divider()
            st.write("### Current data")
            st.write(f"**File:** {st.session_state.raw_file_name or 'No file loaded'}")
            if data is not None:
                st.write(f"**Analysis term:** {data['analysis_term'].upper()}")
                st.write(f"**Students:** {len(df)}")
                st.write(f"**Streams:** {df[stream_col].nunique()}")

            

        # ============================================================
    # TAB 11.5: IT Officer Accounts (admin-only)
    # ============================================================
    with tab_ito:
        if st.session_state.user_role not in ["admin"]:
            st.info("🔒 Only administrators can manage IT officer accounts.")
        else:
            st.subheader("🖥️ IT Officer Accounts")
            st.caption("Create and manage IT officer accounts. IT Officers handle backups, system health and technical tasks.")

            try:
                ito_rows = supabase.table("users").select("username,student_name").eq("role", "it_officer").order("username").execute().data
                if ito_rows:
                    df_ito = pd.DataFrame(ito_rows)
                    df_ito.columns = ["Username", "Full Name"]
                    st.dataframe(df_ito, use_container_width=True, hide_index=True)
                else:
                    st.info("No IT officer accounts yet. Add the first one below.")
            except Exception:
                pass

            st.divider()
            st.markdown("### ➕ Create / Update IT Officer")

            io1, io2 = st.columns(2)
            with io1:
                ito_username = st.text_input("IT Officer username", placeholder="e.g. it_officer", key="new_ito_username")
                ito_full_name = st.text_input("IT Officer full name", placeholder="e.g. IT Officer", key="new_ito_full_name")
            with io2:
                ito_password = st.text_input("IT Officer password", type="password", key="new_ito_password")
                st.caption("Password must be at least 6 characters.")

            if st.button("➕ Create / Update IT Officer", type="primary", use_container_width=True, key="create_ito_btn"):
                if not ito_username.strip() or not ito_full_name.strip() or not ito_password.strip():
                    st.error("Enter username, full name and password.")
                elif len(ito_password) < 6:
                    st.error("Password must be at least 6 characters.")
                else:
                    try:
                        hashed = hash_password(ito_password)
                        existing = supabase.table("users").select("username").eq("username", ito_username.strip()).execute()
                        if existing.data:
                            supabase.table("users").update({
                                "password": hashed,
                                "role": "it_officer",
                                "student_name": ito_full_name.strip()
                            }).eq("username", ito_username.strip()).execute()
                            st.success(f"✅ IT Officer '{ito_username.strip()}' updated — password reset.")
                        else:
                            supabase.table("users").insert({
                                "username": ito_username.strip(),
                                "password": hashed,
                                "role": "it_officer",
                                "student_name": ito_full_name.strip()
                            }).execute()
                            st.success(f"✅ IT Officer '{ito_username.strip()}' created.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

            st.divider()
            with st.expander("🗑️ Delete an IT officer"):
                try:
                    ito_list = supabase.table("users").select("username").eq("role", "it_officer").order("username").execute().data
                    if ito_list:
                        delete_options = [c["username"] for c in ito_list]
                        selected_delete = st.selectbox("Select IT officer to delete", delete_options, key="delete_ito_select")
                        confirm_del = st.checkbox("I understand this will remove the IT officer account.", key="confirm_delete_ito")
                        if st.button("Delete IT Officer", type="secondary", disabled=not confirm_del, use_container_width=True, key="delete_ito_btn"):
                            try:
                                supabase.table("users").delete().eq("username", selected_delete).eq("role", "it_officer").execute()
                                st.success(f"Deleted {selected_delete}.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                    else:
                        st.info("No IT officers to delete.")
                except Exception:
                    st.info("No IT officers to delete.")

    

    # ============================================================
    # TAB 12: System Health (IT Officer)
    # ============================================================
    with tab_health:
        if st.session_state.user_role not in ["admin", "it_officer"]:
            st.info("🔒 Only administrators and IT officers can view system health.")
        else:
            st.subheader("🖥️ System Health")
            st.caption("Real-time status of the Academic Management System.")

            h1, h2, h3 = st.columns(3)

            try:
                supabase.table("users").select("username").limit(1).execute()
                db_status = "🟢 Online"
                db_ok = True
            except Exception:
                db_status = "🔴 Offline"
                db_ok = False

            h1.metric("Database (Supabase)", db_status)
            h2.metric("App", "🟢 Running")
            h3.metric("Session Time", datetime.now().strftime("%H:%M"))

            st.divider()
            st.markdown("### 📊 Data Counts")

            def count(table_name):
                try:
                    r = supabase.table(table_name).select("id").execute()
                    return len(r.data or [])
                except Exception:
                    return "—"

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Users", count("users"))
            c2.metric("Students", count("students"))
            c3.metric("Parents", count("parents"))
            c4.metric("Materials", count("materials"))

            c5, c6, c7, c8 = st.columns(4)
            c5.metric("Submissions", count("submissions"))
            c6.metric("Quizzes", count("quizzes"))
            c7.metric("Quiz Attempts", count("quiz_attempts"))
            c8.metric("Fee Payments", count("fee_payments"))

            st.divider()
            st.markdown("### 👥 Users by Role")
            try:
                users = supabase.table("users").select("role").execute().data or []
                role_counts = {}
                for u in users:
                    r = u.get("role", "unknown")
                    role_counts[r] = role_counts.get(r, 0) + 1
                df_roles = pd.DataFrame([
                    {"Role": k.replace("_", " ").title(), "Count": v} for k, v in sorted(role_counts.items())
                ])
                st.dataframe(df_roles, use_container_width=True, hide_index=True)
            except Exception:
                st.info("Could not load user roles.")

            st.divider()
            st.markdown("### 🔧 Quick Actions")

            qa1, qa2 = st.columns(2)
            with qa1:
                if st.button("🔄 Refresh Status", use_container_width=True, key="health_refresh"):
                    st.rerun()
            with qa2:
                if st.button("📥 Quick Backup", type="primary", use_container_width=True, key="health_backup"):
                    with st.spinner("Packaging backup..."):
                        backup = create_backup_zip()
                    st.download_button(
                        "⬇️ Download Backup ZIP",
                        data=backup.getvalue(),
                        file_name=f"Academic_Backup_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                        mime="application/zip",
                        use_container_width=True,
                        key="health_backup_dl"
                    )

            st.divider()
            st.markdown("### 📖 System Info")
            st.write(f"**App Version:** V20")
            st.write(f"**Signed in as:** {st.session_state.username} ({st.session_state.user_role.title()})")
            st.write(f"**School:** {st.session_state.school_name}")
            st.write(f"**Academic Year:** {st.session_state.get('academic_year', '')}")
            st.write(f"**Current Term:** {st.session_state.get('current_term', '')}")
                # ============================================================
    # TAB 14: Bulk Import
    # ============================================================
    with tab_bulk:
        if st.session_state.user_role not in ["admin", "exams"]:
            st.info("🔒 Only administrators and examination officers can bulk-import accounts.")
        else:
            st.subheader("📥 Bulk Import Accounts")
            st.caption(
                "Upload an Excel file to create accounts in bulk. "
                "Passwords are auto-generated and shown once after import."
            )

            import_tab_teachers, import_tab_subjects, import_tab_classes, import_tab_periods, import_tab_students, import_tab_parents = st.tabs([
                "👨‍🏫 Teachers",
                "📖 Subjects",
                "🏫 Classes",
                "🕐 Periods",
                "🎓 Students",
                "👨‍👩‍👧 Parents",
            ])
                        # ---------- TEACHERS ----------
            with import_tab_teachers:
                st.markdown("### Upload Teachers")
                st.caption(
                    "Excel columns: **Full Name** (required) · **Subjects** (optional, comma-sep) · "
                    "**Classes** (optional, pipe-sep). Creates a login account, a timetable teacher row, "
                    "and class assignments — all in one import."
                )
                teacher_file = st.file_uploader(
                    "Teachers Excel",
                    type=["xlsx", "xls"],
                    key="bulk_teacher_file",
                )
                if teacher_file is not None:
                    try:
                        df_t = pd.read_excel(teacher_file)
                        df_t.columns = [str(c).strip().lower() for c in df_t.columns]
                        name_col_t = None
                        for c in df_t.columns:
                            if c in ["full name", "name", "teacher name", "full_name"]:
                                name_col_t = c
                                break
                        if name_col_t is None:
                            st.error("Could not find a name column. Use 'Full Name' or 'Name'.")
                        else:
                            if name_col_t != "full name":
                                df_t = df_t.rename(columns={name_col_t: "full name"})

                            st.write(f"**Detected {len(df_t)} rows.** Preview:")
                            st.dataframe(df_t.head(5), use_container_width=True, hide_index=True)

                            if st.button("🚀 Import Teachers", type="primary", key="bulk_import_teachers_btn"):
                                with st.spinner("Creating teacher accounts + timetable rows + assignments..."):
                                    result = _bulk_import_teachers_full(df_t)

                                st.success(f"✅ Created {len(result['created'])} teacher accounts.")
                                if result["skipped"]:
                                    st.warning(f"⚠️ Skipped {len(result['skipped'])} rows.")
                                if result["errors"]:
                                    st.error(f"❌ {len(result['errors'])} rows had errors.")

                                if result["created"]:
                                    csv_bytes = _credentials_csv(result["created"])
                                    st.download_button(
                                        "⬇️ Download Credentials CSV",
                                        data=csv_bytes,
                                        file_name=f"Teacher_Credentials_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                                        mime="text/csv",
                                        key="bulk_teacher_csv_dl",
                                    )
                    except Exception as e:
                        st.error(f"Error reading file: {e}")

                        # ---------- SUBJECTS ----------
            with import_tab_subjects:
                st.markdown("### Upload Subjects")
                st.caption(
                    "Excel columns: **Subject** · **Periods Per Week** · "
                    "**Has Double** (yes/no) · **Requires Lab** (yes/no) · **Lab Type**"
                )
                subject_file = st.file_uploader("Subjects Excel", type=["xlsx", "xls"], key="bulk_subject_file")
                if subject_file is not None:
                    try:
                        df_sub = pd.read_excel(subject_file)
                        df_sub.columns = [str(c).strip().lower() for c in df_sub.columns]
                        st.write(f"**Detected {len(df_sub)} rows.** Preview:")
                        st.dataframe(df_sub.head(5), use_container_width=True, hide_index=True)

                        if st.button("🚀 Import Subjects", type="primary", key="bulk_import_subjects_btn"):
                            with st.spinner("Creating subjects..."):
                                result = _bulk_import_subjects(df_sub)
                            st.success(f"✅ Imported {len(result['created'])} subjects.")
                            if result["errors"]:
                                st.error(f"❌ {len(result['errors'])} rows had errors.")
                    except Exception as e:
                        st.error(f"Error reading file: {e}")

            # ---------- CLASSES ----------
            with import_tab_classes:
                st.markdown("### Upload Classes")
                st.caption("Excel columns: **Class Name**")
                class_file = st.file_uploader("Classes Excel", type=["xlsx", "xls"], key="bulk_class_file")
                if class_file is not None:
                    try:
                        df_cls = pd.read_excel(class_file)
                        df_cls.columns = [str(c).strip().lower() for c in df_cls.columns]
                        st.write(f"**Detected {len(df_cls)} rows.** Preview:")
                        st.dataframe(df_cls.head(5), use_container_width=True, hide_index=True)

                        if st.button("🚀 Import Classes", type="primary", key="bulk_import_classes_btn"):
                            with st.spinner("Creating classes..."):
                                result = _bulk_import_classes(df_cls)
                            st.success(f"✅ Imported {len(result['created'])} classes.")
                            if result["errors"]:
                                st.error(f"❌ {len(result['errors'])} rows had errors.")
                    except Exception as e:
                        st.error(f"Error reading file: {e}")

            # ---------- PERIODS ----------
            with import_tab_periods:
                st.markdown("### Upload Periods")
                st.caption("Excel columns: **Period No** · **Start Time** · **End Time**")
                period_file = st.file_uploader("Periods Excel", type=["xlsx", "xls"], key="bulk_period_file")
                if period_file is not None:
                    try:
                        df_per = pd.read_excel(period_file)
                        df_per.columns = [str(c).strip().lower() for c in df_per.columns]
                        st.write(f"**Detected {len(df_per)} rows.** Preview:")
                        st.dataframe(df_per.head(5), use_container_width=True, hide_index=True)

                        if st.button("🚀 Import Periods", type="primary", key="bulk_import_periods_btn"):
                            with st.spinner("Creating periods..."):
                                result = _bulk_import_periods(df_per)
                            st.success(f"✅ Imported {len(result['created'])} periods.")
                            if result["errors"]:
                                st.error(f"❌ {len(result['errors'])} rows had errors.")
                    except Exception as e:
                        st.error(f"Error reading file: {e}")

                        # ---------- STUDENTS ----------
            with import_tab_students:
                st.markdown("### Upload Students")
                st.caption(
                    "Excel columns: **Full Name** (required) · **Stream** (optional) · "
                    "**Username** (optional) · **Password** (optional)"
                )
                student_file = st.file_uploader(
                    "Students Excel",
                    type=["xlsx", "xls"],
                    key="bulk_student_file",
                )
                if student_file is not None:
                    try:
                        df_s = pd.read_excel(student_file)
                        df_s.columns = [str(c).strip().lower() for c in df_s.columns]
                        name_col_s = None
                        for c in df_s.columns:
                            if c in ["full name", "name", "student name", "full_name"]:
                                name_col_s = c
                                break
                        if name_col_s is None:
                            st.error("Could not find a name column. Use 'Full Name' or 'Name'.")
                        else:
                            if name_col_s != "full name":
                                df_s = df_s.rename(columns={name_col_s: "full name"})

                            st.write(f"**Detected {len(df_s)} rows.** Preview:")
                            st.dataframe(df_s.head(5), use_container_width=True, hide_index=True)

                            if st.button("🚀 Import Students", type="primary", key="bulk_import_students_btn"):
                                with st.spinner("Creating student accounts..."):
                                    result = _bulk_import_users(df_s, "student", "full name")

                                st.success(f"✅ Created {len(result['created'])} student accounts.")
                                if result["skipped"]:
                                    st.warning(f"⚠️ Skipped {len(result['skipped'])} rows.")
                                if result["errors"]:
                                    st.error(f"❌ {len(result['errors'])} rows had errors.")

                                if result["created"]:
                                    csv_bytes = _credentials_csv(result["created"])
                                    st.download_button(
                                        "⬇️ Download Credentials CSV",
                                        data=csv_bytes,
                                        file_name=f"Student_Credentials_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                                        mime="text/csv",
                                        key="bulk_student_csv_dl",
                                    )
                    except Exception as e:
                        st.error(f"Error reading file: {e}")

            # ---------- PARENTS ----------
            with import_tab_parents:
                st.markdown("### Upload Parents")
                st.caption(
                    "Excel columns: **Full Name** (required) · **Children** (optional, pipe-separated) · "
                    "**Username** (optional) · **Password** (optional)"
                )
                parent_file = st.file_uploader(
                    "Parents Excel",
                    type=["xlsx", "xls"],
                    key="bulk_parent_file",
                )
                if parent_file is not None:
                    try:
                        df_p = pd.read_excel(parent_file)
                        df_p.columns = [str(c).strip().lower() for c in df_p.columns]
                        name_col_p = None
                        for c in df_p.columns:
                            if c in ["full name", "name", "parent name", "full_name", "guardian name"]:
                                name_col_p = c
                                break
                        if name_col_p is None:
                            st.error("Could not find a name column. Use 'Full Name' or 'Name'.")
                        else:
                            if name_col_p != "full name":
                                df_p = df_p.rename(columns={name_col_p: "full name"})

                            st.write(f"**Detected {len(df_p)} rows.** Preview:")
                            st.dataframe(df_p.head(5), use_container_width=True, hide_index=True)

                            if st.button("🚀 Import Parents", type="primary", key="bulk_import_parents_btn"):
                                with st.spinner("Creating parent accounts..."):
                                    result = _bulk_import_users(df_p, "parent", "full name")

                                st.success(f"✅ Created {len(result['created'])} parent accounts.")
                                if result["skipped"]:
                                    st.warning(f"⚠️ Skipped {len(result['skipped'])} rows.")
                                if result["errors"]:
                                    st.error(f"❌ {len(result['errors'])} rows had errors.")

                                if result["created"]:
                                    csv_bytes = _credentials_csv(result["created"])
                                    st.download_button(
                                        "⬇️ Download Credentials CSV",
                                        data=csv_bytes,
                                        file_name=f"Parent_Credentials_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                                        mime="text/csv",
                                        key="bulk_parent_csv_dl",
                                    )
                    except Exception as e:
                        st.error(f"Error reading file: {e}")
            st.success("✅ All data is stored in Supabase — it persists across app restarts.")

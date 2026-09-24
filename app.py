import io
import re
import zipfile
import sqlite3
import hashlib
import secrets
import os
import json
from datetime import datetime, date

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import linregress
import streamlit as st

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
    overflow: visible !important;
}
.welcome-title {
    line-height: 1.35 !important;
    padding: .55rem .25rem .75rem .25rem !important;
    margin: .20rem 0 .90rem 0 !important;
    overflow: visible !important;
}
[data-testid="stAppViewContainer"] .main .block-container {
    padding-top: 2rem !important;
    padding-bottom: 2rem !important;
}
label, .stMarkdown, .stText, p {
    line-height: 1.45 !important;
}
</style>
""", unsafe_allow_html=True)


st.markdown("""
<style>
.metric-card {
    border-radius: 14px;
    padding: 1rem 1.1rem;
    border: 1px solid rgba(128,128,128,.22);
    background: rgba(128,128,128,.06);
    min-height: 105px;
    margin-bottom: .5rem;
}
.metric-card .label {
    font-size: .82rem;
    font-weight: 600;
    opacity: .72;
    text-transform: uppercase;
    letter-spacing: .04em;
}
.metric-card .value {
    font-size: 1.65rem;
    font-weight: 750;
    margin-top: .25rem;
}
.section-title {
    font-size: 1.25rem;
    font-weight: 750;
    margin-top: 1rem;
    margin-bottom: .5rem;
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
div[data-testid="stMetric"] {
    border-radius: 14px;
    padding: .75rem;
}
</style>
""", unsafe_allow_html=True)

DEFAULT_SCHOOL = "EXCELLENCE SECONDARY SCHOOL"
TERMS = ["y1t1", "y1t2", "y1t3", "y2t1", "y2t2", "y2t3"]

LEARNING_DB = "school_learning.db"
LEARNING_DIR = "learning_centre_files"
PARENT_RESULTS_FILE = "school_results_current.xlsx"
BACKUP_DIR = "system_backups"
os.makedirs(LEARNING_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)


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


def db_conn():
    conn = sqlite3.connect(LEARNING_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_learning_db():
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL,
        student_name TEXT DEFAULT ''
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS parents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        parent_name TEXT NOT NULL,
        child_names TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        student_full_name TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        material_type TEXT NOT NULL,
        subject TEXT DEFAULT '',
        target_stream TEXT DEFAULT 'All Streams',
        description TEXT DEFAULT '',
        deadline TEXT DEFAULT '',
        file_name TEXT DEFAULT '',
        file_path TEXT DEFAULT '',
        external_link TEXT DEFAULT '',
        uploaded_by TEXT DEFAULT '',
        created_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        material_id INTEGER NOT NULL,
        student_name TEXT NOT NULL,
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        submitted_at TEXT NOT NULL,
        status TEXT DEFAULT 'Submitted',
        teacher_feedback TEXT DEFAULT '',
        UNIQUE(material_id, student_name)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS quizzes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        subject TEXT DEFAULT '',
        target_stream TEXT DEFAULT 'All Streams',
        description TEXT DEFAULT '',
        deadline TEXT DEFAULT '',
        duration_minutes INTEGER DEFAULT 30,
        created_by TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        status TEXT DEFAULT 'Published'
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS quiz_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quiz_id INTEGER NOT NULL,
        question_no INTEGER NOT NULL,
        question_text TEXT NOT NULL,
        question_type TEXT NOT NULL,
        option_a TEXT DEFAULT '',
        option_b TEXT DEFAULT '',
        option_c TEXT DEFAULT '',
        option_d TEXT DEFAULT '',
        correct_answer TEXT DEFAULT '',
        points REAL DEFAULT 1
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS quiz_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quiz_id INTEGER NOT NULL,
        student_name TEXT NOT NULL,
        started_at TEXT NOT NULL,
        submitted_at TEXT NOT NULL,
        answers_json TEXT DEFAULT '{}',
        score REAL DEFAULT 0,
        total_points REAL DEFAULT 0,
        status TEXT DEFAULT 'Submitted',
        teacher_feedback TEXT DEFAULT '',
        UNIQUE(quiz_id, student_name)
    )""")
    cur.execute("INSERT OR IGNORE INTO users(username,password,role,student_name) VALUES(?,?,?,?)",
                ("teacher", hash_password("teacher123"), "teacher", ""))
    cur.execute("INSERT OR IGNORE INTO users(username,password,role,student_name) VALUES(?,?,?,?)",
                ("student", hash_password("student123"), "student", ""))
    conn.commit()
    conn.close()


init_learning_db()


def authenticate_user(username, password):
    conn = db_conn()
    row = conn.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
    conn.close()
    if not row:
        return None
    user = dict(row)
    if not verify_password(password, user["password"]):
        return None
    if "$" not in (user["password"] or ""):
        conn = db_conn()
        conn.execute("UPDATE users SET password=? WHERE username=?",
                     (hash_password(password), user["username"]))
        conn.commit()
        conn.close()
    return user


def get_parent_profile(username):
    conn = db_conn()
    row = conn.execute("SELECT * FROM parents WHERE username=?", (username.strip(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_student_profile(username):
    conn = db_conn()
    row = conn.execute("SELECT * FROM students WHERE username=?", (username.strip(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_results_for_parent_access(raw_df, filename="school_results_current.xlsx"):
    try:
        raw_df.to_excel(filename, index=False)
        return True
    except Exception:
        return False


def load_persisted_parent_results():
    if not os.path.exists(PARENT_RESULTS_FILE):
        return None
    try:
        return pd.read_excel(PARENT_RESULTS_FILE)
    except Exception:
        return None


def add_material(title, material_type, subject, target_stream, description, deadline,
                 file_name, file_path, external_link, uploaded_by):
    conn = db_conn()
    conn.execute("""INSERT INTO materials
        (title,material_type,subject,target_stream,description,deadline,file_name,file_path,external_link,uploaded_by,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (title, material_type, subject, target_stream, description, deadline,
         file_name, file_path, external_link, uploaded_by,
         datetime.now().strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    conn.close()


def get_materials():
    conn = db_conn()
    rows = conn.execute("SELECT * FROM materials ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_submission(material_id, student_name, uploaded_file):
    safe_student = re.sub(r"[^A-Za-z0-9_-]+", "_", student_name).strip("_") or "student"
    folder = os.path.join(LEARNING_DIR, "submissions", safe_student)
    os.makedirs(folder, exist_ok=True)
    safe_file = re.sub(r"[^A-Za-z0-9._-]+", "_", uploaded_file.name)
    path = os.path.join(folder, safe_file)
    with open(path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    conn = db_conn()
    conn.execute("""INSERT INTO submissions(material_id,student_name,file_name,file_path,submitted_at,status)
        VALUES(?,?,?,?,?,?) ON CONFLICT(material_id,student_name) DO UPDATE SET
        file_name=excluded.file_name,file_path=excluded.file_path,submitted_at=excluded.submitted_at,status='Resubmitted'""",
        (material_id, student_name, safe_file, path,
         datetime.now().strftime("%Y-%m-%d %H:%M"), "Submitted"))
    conn.commit()
    conn.close()


def get_submissions(material_id=None, student_name=None):
    conn = db_conn()
    q = "SELECT s.*,m.title,m.subject FROM submissions s JOIN materials m ON s.material_id=m.id"
    params = []
    clauses = []
    if material_id is not None:
        clauses.append("s.material_id=?")
        params.append(material_id)
    if student_name:
        clauses.append("s.student_name=?")
        params.append(student_name)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY s.id DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_material(material_id):
    conn = db_conn()
    row = conn.execute("SELECT file_path FROM materials WHERE id=?", (material_id,)).fetchone()
    conn.execute("DELETE FROM materials WHERE id=?", (material_id,))
    conn.execute("DELETE FROM submissions WHERE material_id=?", (material_id,))
    conn.commit()
    conn.close()
    if row and row[0] and os.path.exists(row[0]):
        try:
            os.remove(row[0])
        except OSError:
            pass


def add_quiz(title, subject, target_stream, description, deadline, duration_minutes, created_by, questions):
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""INSERT INTO quizzes(title,subject,target_stream,description,deadline,duration_minutes,created_by,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (title, subject, target_stream, description, deadline, int(duration_minutes),
                 created_by, datetime.now().strftime("%Y-%m-%d %H:%M")))
    quiz_id = cur.lastrowid
    for i, q in enumerate(questions, 1):
        cur.execute("""INSERT INTO quiz_questions
            (quiz_id,question_no,question_text,question_type,option_a,option_b,option_c,option_d,correct_answer,points)
            VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (quiz_id, i, q['text'], q['type'], q.get('a', ''), q.get('b', ''),
             q.get('c', ''), q.get('d', ''), q.get('correct', ''), float(q.get('points', 1))))
    conn.commit()
    conn.close()
    return quiz_id


def get_quizzes():
    conn = db_conn()
    rows = conn.execute("SELECT * FROM quizzes ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_quiz_questions(quiz_id):
    conn = db_conn()
    rows = conn.execute("SELECT * FROM quiz_questions WHERE quiz_id=? ORDER BY question_no", (quiz_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_attempts(quiz_id=None, student_name=None):
    conn = db_conn()
    q = "SELECT a.*,q.title,q.subject FROM quiz_attempts a JOIN quizzes q ON a.quiz_id=q.id"
    params = []
    clauses = []
    if quiz_id is not None:
        clauses.append("a.quiz_id=?")
        params.append(quiz_id)
    if student_name:
        clauses.append("a.student_name=?")
        params.append(student_name)
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY a.id DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_quiz_attempt(quiz_id, student_name, answers, score, total_points, status):
    conn = db_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    conn.execute("""INSERT INTO quiz_attempts(quiz_id,student_name,started_at,submitted_at,answers_json,score,total_points,status)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(quiz_id,student_name) DO UPDATE SET
        submitted_at=excluded.submitted_at,answers_json=excluded.answers_json,score=excluded.score,total_points=excluded.total_points,status=excluded.status""",
        (quiz_id, student_name, now, now, json.dumps(answers),
         float(score), float(total_points), status))
    conn.commit()
    conn.close()


def update_quiz_feedback(attempt_id, feedback, status='Reviewed'):
    conn = db_conn()
    conn.execute("UPDATE quiz_attempts SET teacher_feedback=?,status=? WHERE id=?",
                 (feedback.strip(), status, attempt_id))
    conn.commit()
    conn.close()


def delete_quiz(quiz_id):
    conn = db_conn()
    conn.execute("DELETE FROM quiz_questions WHERE quiz_id=?", (quiz_id,))
    conn.execute("DELETE FROM quiz_attempts WHERE quiz_id=?", (quiz_id,))
    conn.execute("DELETE FROM quizzes WHERE id=?", (quiz_id,))
    conn.commit()
    conn.close()


def quiz_available_for_student(quiz, student_streams):
    if quiz.get('target_stream') == 'All Streams' or not student_streams:
        return True
    return quiz.get('target_stream') in student_streams


def quiz_grade(score, total):
    pct = (score / total * 100) if total else 0
    return pct, grade(pct)


def create_backup_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in [LEARNING_DB, PARENT_RESULTS_FILE]:
            if os.path.exists(f):
                z.write(f, arcname=os.path.basename(f))
        for root, dirs, files in os.walk(LEARNING_DIR):
            for file in files:
                full = os.path.join(root, file)
                rel = os.path.relpath(full, start=".")
                z.write(full, arcname=rel)
    buf.seek(0)
    return buf


st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
.app-title {font-size: 2rem; font-weight: 750; margin-bottom: 0;}
.app-subtitle {color:#6b7280; margin-top:2px; margin-bottom:18px;}
.section-title {font-size:1.15rem; font-weight:700; margin-top:12px;}
div[data-testid="stMetric"] {
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 10px 14px;
    background: #ffffff;
}
</style>
""", unsafe_allow_html=True)


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
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


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
        role = st.selectbox("Login as", ["Administrator", "Teacher", "Student", "Parent"])
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")

        if st.button("Sign in", type="primary", use_container_width=True):
            if role == "Administrator":
                valid = username == "admin" and password == "admin123"
                user = {"role": "admin", "username": "admin", "student_name": ""} if valid else None
            else:
                user = authenticate_user(username, password)
                if user and ((role == "Teacher" and user["role"] != "teacher")
                             or (role == "Student" and user["role"] != "student")
                             or (role == "Parent" and user["role"] != "parent")):
                    user = None
            if user:
                st.session_state.logged_in = True
                st.session_state.user_role = user["role"]
                st.session_state.username = user["username"]
                st.session_state.student_name = user.get("student_name", "")
                st.rerun()
            else:
                st.error("Incorrect username, password, or role.")

        st.caption("Demo accounts: admin/admin123 • teacher/teacher123 • student/student123 • parent/parent123")
        st.info("Teacher and student accounts use local credentials stored securely (hashed).")

    st.stop()


if not st.session_state.logged_in:
    login_screen()


def clean_label(value):
    value = str(value)
    for term in TERMS:
        if value.lower().startswith(term):
            remainder = value[len(term):].strip()
            return remainder.replace("_", " ").replace("-", " ").title() or term.upper()
    return value.replace("_", " ").replace("-", " ").title()


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

    avg_cols = []
    for term in TERMS:
        candidates = [c for c in df.columns if term in c and "avg" in c]
        if not candidates:
            candidates = [c for c in df.columns if term in c]
        avg_cols.append(candidates[0] if candidates else None)

    pairs = [(t, c) for t, c in zip(TERMS, avg_cols) if c is not None]
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
        and c not in [name_col, stream_col]
    ]

    if not subjects:
        excluded = set(avg_cols + [name_col, stream_col])
        subjects = [
            c for c in df.columns
            if c not in excluded and pd.api.types.is_numeric_dtype(df[c])
        ]

    for subject in subjects:
        df[subject] = pd.to_numeric(df[subject], errors="coerce").fillna(0.0)

    df["overall_rank"] = (
        df[target].rank(ascending=False, method="min").astype(int)
    )
    df["stream_rank"] = (
        df.groupby(stream_col)[target].rank(
            ascending=False, method="min"
        ).astype(int)
    )

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
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    if score >= 60:
        return "C"
    if score >= 50:
        return "D"
    return "E"


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
            corr = np.nan
            slope = np.nan
            intercept = np.nan
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

def school_contact_line():
    parts = [
        st.session_state.get("school_address", ""),
        st.session_state.get("school_phone", ""),
        st.session_state.get("school_email", ""),
    ]
    return " • ".join([p for p in parts if p])


def pdf_school_header(story, school_name, styles, report_subtitle):
    logo = st.session_state.get("school_logo")
    if logo:
        try:
            logo_buf = io.BytesIO(logo)
            logo_img = Image(logo_buf, width=0.65*inch, height=0.65*inch)
            header = Table([[logo_img, Paragraph(school_name, styles["title"])]],
                           colWidths=[0.85*inch, 8.0*inch])
            header.setStyle(TableStyle([
                ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                ("ALIGN", (1,0), (1,0), "CENTER"),
            ]))
            story.append(header)
        except Exception:
            story.append(Paragraph(school_name, styles["title"]))
    else:
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
            out.append(
                Paragraph(
                    text,
                    styles["cell"] if c == name_col else styles["center"]
                )
            )
        rows.append(out)

    footer = []
    for c in cols:
        if c == name_col:
            text = footer_label
        elif c in subjects + [target]:
            text = f"{frame[c].mean():.1f}%"
        else:
            text = "-"
        footer.append(
            Paragraph(
                text,
                styles["cell"] if c == name_col else styles["center"]
            )
        )
    rows.append(footer)

    fixed = 45 + 45 + 55
    available = 792 - 40
    name_width = 130
    subject_width = max(
        34, (available - name_width - fixed - 55) / max(1, len(subjects))
    )
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
        leftMargin=20, rightMargin=20, topMargin=25, bottomMargin=25
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
    if score >= 80:
        return "Excellent"
    if score >= 70:
        return "Very good"
    if score >= 60:
        return "Good"
    if score >= 50:
        return "Satisfactory"
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
        leftMargin=28, rightMargin=28, topMargin=22, bottomMargin=28
    )
    styles = pdf_styles()
    name = str(student[data["name_col"]])
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
    story.append(Spacer(1, 5))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#263238")))
    story.append(Spacer(1, 5))

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
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(identity_table)
    story.append(Spacer(1, 7))

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
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]))
    story.append(Paragraph("Subject Performance", ParagraphStyle(
        "Section", parent=styles["cell"], fontName="Helvetica-Bold", fontSize=10, leading=12
    )))
    story.append(Spacer(1, 3))
    story.append(subject_table)
    story.append(Spacer(1, 7))

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

    img1 = Image(figure_bytes(progression_figure(student, data)), width=3.55*inch, height=1.55*inch)
    img2 = Image(figure_bytes(subject_figure(student, data)), width=3.55*inch, height=1.55*inch)
    charts = Table([[img1, img2]], colWidths=[3.7*inch, 3.7*inch])
    charts.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))

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
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))

    lower = Table([[history_table, charts, summary_box]], colWidths=[2.35*inch, 7.55*inch, 2.75*inch])
    lower.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(lower)
    story.append(Spacer(1, 7))

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
            safe = re.sub(
                r"[^A-Za-z0-9_-]+", "_",
                str(student[data["name_col"]])
            ).strip("_")
            archive.writestr(
                f"Student_{safe}_Report.pdf",
                pdf.getvalue()
            )

    zip_buffer.seek(0)
    return zip_buffer

st.sidebar.title("Academic System")

st.session_state.school_name = st.sidebar.text_input(
    "School name",
    value=st.session_state.school_name
)

st.sidebar.caption("School branding can be completed in Settings.")

if st.session_state.user_role in ["admin", "teacher"]:
    uploaded = st.sidebar.file_uploader(
        "Upload student Excel file",
        type=["xlsx", "xls"]
    )
else:
    uploaded = None

if uploaded:
    try:
        raw = pd.read_excel(uploaded)
        _, _, _, detected_terms, _ = detect_columns(raw)

        if detected_terms:
            selected_term = st.sidebar.selectbox(
                "Analysis term",
                detected_terms,
                index=len(detected_terms) - 1
            )

            if st.sidebar.button("Load / Analyse Results", type="primary", use_container_width=True):
                st.session_state.raw_data = raw.copy()
                st.session_state.data = prepare_data(raw, selected_term)
                st.session_state.raw_file_name = uploaded.name
                save_results_for_parent_access(raw)
                st.session_state.parent_results_ready = True
                st.rerun()
        else:
            st.sidebar.error("No term columns were detected.")
    except Exception as exc:
        st.sidebar.error(f"Excel error: {exc}")

if st.session_state.data is None and st.session_state.user_role not in ["student", "parent"]:
    st.markdown(
        '<div class="app-title">Welcome to the Academic Management System</div>',
        unsafe_allow_html=True
    )
    st.markdown(
        '<div class="app-subtitle">Upload your student_results.xlsx file from the left menu to begin.</div>',
        unsafe_allow_html=True
    )

    st.info(
        "Expected columns include Name, Stream/Class, term averages such as "
        "y1t1avg through y2t3avg, and subject columns such as y2t3maths."
    )

    a, b, c = st.columns(3)
    a.metric("Dashboard", "School overview")
    b.metric("Student Reports", "Individual analysis")
    c.metric("PDF Reports", "Ready to download")

    st.markdown("### First-time setup")
    st.write("1. Upload the Excel file.")
    st.write("2. Choose the analysis term.")
    st.write("3. Click **Load / Analyse Results**.")
    st.write("4. Use the navigation menu to explore the system.")
    st.stop()


if st.session_state.user_role == "parent" and st.session_state.data is None:
    persisted = load_persisted_parent_results()
    if persisted is not None and not persisted.empty:
        try:
            _, _, _, detected_terms, _ = detect_columns(persisted)
            if detected_terms:
                parent_term = detected_terms[-1]
                st.session_state.raw_data = persisted.copy()
                st.session_state.data = prepare_data(persisted, parent_term)
        except Exception:
            pass

if st.session_state.user_role == "student" and st.session_state.data is None:
    persisted = load_persisted_parent_results()
    if persisted is not None and not persisted.empty:
        try:
            _, _, _, detected_terms, _ = detect_columns(persisted)
            if detected_terms:
                student_term = detected_terms[-1]
                st.session_state.raw_data = persisted.copy()
                st.session_state.data = prepare_data(persisted, student_term)
        except Exception:
            pass

if st.session_state.data is None and st.session_state.user_role in ["student", "parent"]:
    data = None
    df = pd.DataFrame()
    target = name_col = stream_col = None
else:
    data = st.session_state.data
    df = data["df"]
    target = data["target_rank_col"]
    name_col = data["name_col"]
    stream_col = data["stream_col"]

st.markdown(
    f'<div class="app-title">{st.session_state.school_name}</div>',
    unsafe_allow_html=True
)
st.markdown(
    f'<div class="app-subtitle">Academic Management System • V17 • {data["analysis_term"].upper() if data is not None else "Learning Centre"}</div>',
    unsafe_allow_html=True
)

if st.session_state.user_role == "student":
    nav_items = ["My Dashboard", "Learning Centre", "Online Tests & Quizzes", "My Profile"]
elif st.session_state.user_role == "parent":
    nav_items = ["Parent Portal"]
elif st.session_state.user_role == "teacher":
    nav_items = ["Dashboard", "Students", "Academic Results", "Streams", "Master Merit List", "Reports", "Learning Centre", "Online Tests & Quizzes", "Settings"]
else:
    nav_items = ["Dashboard", "Students", "Student Records", "Academic Results", "Streams", "Master Merit List", "Analytics", "Reports", "Learning Centre", "Online Tests & Quizzes", "Settings"]

page = st.sidebar.radio("Navigation", nav_items)
st.sidebar.caption(f"Signed in as: **{st.session_state.user_role.title()}**")

if st.sidebar.button("Sign out", use_container_width=True):
    st.session_state.logged_in = False
    st.session_state.data = None
    st.session_state.user_role = ""
    st.session_state.username = ""
    st.session_state.student_name = ""
    st.session_state.raw_data = None
    st.rerun()


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
            "in the current results. Please contact the school administrator to correct the link."
        )
        st.write("**Linked names on your account:** " + ", ".join(children_raw))
        st.write("**Example student names in current results:** " + ", ".join(df[name_col].astype(str).head(5).tolist()))
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

    st.stop()


# ============================================================
# STUDENT DASHBOARD (read-only)
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
# DASHBOARD
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
    top_view = top[
        [name_col, stream_col, "overall_rank", "stream_rank", target, "term_change"]
    ].copy()
    top_view.columns = [
        "Student", "Stream", "School Rank",
        "Stream Rank", "Final Average", "Change"
    ]
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
    st.caption("Choose the date that should appear below the teacher and principal signatures. You can change it for each report as needed.")
    report_date = st.date_input(
        "Report date",
        value=st.session_state.get("report_issue_date", date.today()),
        key=f"report_date_{re.sub(r'[^A-Za-z0-9]', '_', student_key)}"
    )
    st.session_state.report_issue_date = report_date

    st.markdown("### 📄 Student report")
    pdf = generate_student_pdf(student, data, st.session_state.school_name, st.session_state.get("teacher_comments", {}).get(student_key, teacher_comment), report_date=report_date)
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
    st.caption("Add, edit, remove and export student records without changing your original Excel file until you download the updated version.")

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
                st.info("No admission-number column was detected in this Excel file.")

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
            avg_inputs[col] = avg_grid[i % 3].number_input(str(col).upper(), min_value=0.0, max_value=100.0, value=val, step=0.1, key=f"record_avg_{edit_idx}_{col}")

        if st.button("💾 Save Student Changes", type="primary", use_container_width=True, key="save_student_changes"):
            working.loc[edit_idx, raw_name_col] = new_name.strip() or str(current[raw_name_col])
            working.loc[edit_idx, raw_stream_col] = new_stream.strip().upper()
            if admission_col:
                working.loc[edit_idx, admission_col] = new_admission.strip()
            for col, val in avg_inputs.items():
                working.loc[edit_idx, col] = val
            st.session_state.raw_data = working
            st.session_state.data = prepare_data(working, data["analysis_term"])
            save_results_for_parent_access(working)
            st.success(f"Updated {new_name.strip() or edit_name}. Rankings and analytics have been recalculated.")
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
            add_values[col] = add_grid[i % 3].number_input(str(col).upper(), min_value=0.0, max_value=100.0, value=0.0, step=0.1, key=f"add_avg_{col}")
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
                save_results_for_parent_access(working)
                st.success(f"Added {add_name.strip()} to {str(add_stream).upper()}.")
                st.rerun()

    with tab_delete:
        st.markdown("### Remove a student")
        delete_name = st.selectbox("Select student to remove", working[raw_name_col].astype(str).tolist(), key="delete_student_name")
        st.warning("Removing a student changes the working data in the app. Your original Excel file is not overwritten automatically.")
        confirm_delete = st.checkbox("I understand that this student will be removed from the working dataset.", key="confirm_delete_student")
        if st.button("🗑️ Remove Student", type="secondary", disabled=not confirm_delete, use_container_width=True, key="remove_student_button"):
            working = working[working[raw_name_col].astype(str) != delete_name].copy()
            st.session_state.raw_data = working
            st.session_state.data = prepare_data(working, data["analysis_term"])
            save_results_for_parent_access(working)
            st.success(f"Removed {delete_name}.")
            st.rerun()

    with tab_export:
        st.markdown("### Save your updated records")
        st.info("Changes are kept in the current app session. Download the updated Excel file to permanently keep them on your computer.")
        st.write(f"**Current students:** {len(working)}")
        st.write(f"**Current streams:** {working[raw_stream_col].nunique()}")
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            working.to_excel(writer, index=False, sheet_name="Student Results")
        excel_buffer.seek(0)
        export_name = f"Updated_Student_Records_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        st.download_button("⬇️ Download Updated Excel Records", data=excel_buffer.getvalue(), file_name=export_name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary", use_container_width=True)

        st.markdown("### Current records")
        st.dataframe(working, use_container_width=True, hide_index=True)


# ============================================================
# ACADEMIC RESULTS
# ============================================================

elif page == "Academic Results":
    st.subheader("📝 Academic Results Entry & Editing")
    st.caption("Enter or correct subject marks for a student. The selected term average, grades and rankings are recalculated automatically.")

    raw_df = st.session_state.get("raw_data")
    if raw_df is None or raw_df.empty:
        st.warning("No student data is loaded. Upload your Excel file first.")
        st.stop()

    working = raw_df.copy()
    _, raw_name_col, raw_stream_col, raw_terms, raw_avg_cols = detect_columns(working)
    if not raw_terms:
        st.error("No term columns were detected in the uploaded Excel file.")
        st.stop()

    term_choice = st.selectbox(
        "📅 Select term to edit",
        raw_terms,
        index=raw_terms.index(data["analysis_term"]) if data["analysis_term"] in raw_terms else len(raw_terms)-1,
        format_func=lambda x: x.upper(),
    )

    avg_col = raw_avg_cols[raw_terms.index(term_choice)]
    term_subjects = [
        c for c in working.columns
        if term_choice in str(c).lower()
        and c != avg_col
        and "avg" not in str(c).lower()
        and c not in [raw_name_col, raw_stream_col]
    ]
    term_subjects = [
        c for c in term_subjects
        if pd.to_numeric(working[c], errors="coerce").notna().any()
    ]

    if not term_subjects:
        st.warning(f"No subject columns were detected for {term_choice.upper()}.")
        st.info("Your Excel should have columns such as y2t3maths, y2t3english, y2t3biology, etc.")
        st.stop()

    result_names = working[raw_name_col].astype(str).tolist()
    selected_result_student = st.selectbox("👤 Select student", result_names, key="results_student_select")
    idx = working.index[working[raw_name_col].astype(str) == selected_result_student].tolist()[0]
    current = working.loc[idx]
    st.metric("Stream", str(current[raw_stream_col]))
    st.markdown(f"### {selected_result_student} — {term_choice.upper()}")
    st.write("Enter marks from **0 to 100**. The system keeps the raw total separate from the average/percentage. A grade is calculated only from the percentage/average, never from the raw total.")

    score_inputs = {}
    grid = st.columns(3)
    for i, col in enumerate(term_subjects):
        value = pd.to_numeric(current[col], errors="coerce")
        value = 0.0 if pd.isna(value) else float(value)
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
    c.metric("Previous Average", f"{old_avg:.1f}%")

    if st.button("💾 Save Academic Results", type="primary", use_container_width=True, key="save_academic_results"):
        for col, value in score_inputs.items():
            working.loc[idx, col] = value
        working.loc[idx, avg_col] = proposed_average
        st.session_state.raw_data = working
        st.session_state.data = prepare_data(working, data["analysis_term"])
        save_results_for_parent_access(working)
        st.success(f"Saved {term_choice.upper()} results for {selected_result_student}. Average updated to {proposed_average:.1f}%. Rankings and reports have been recalculated.")
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
    st.markdown(f"**Total Marks:** {current_total:.1f} / {current_max} &nbsp;&nbsp; **Average / Percentage:** {current_pct:.1f}% &nbsp;&nbsp; **Overall Grade:** {grade(current_pct)}")
    st.info("💡 The raw total is displayed without a grade. The overall grade is based on the percentage/average. After saving, check Master Merit List, Streams, Students, or the PDF report to see the updated results.")


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
    if top_n != "All":
        display = merit.head(int(top_n)).copy()
    else:
        display = merit.copy()

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

    st.info(
        "Correlation measures linear association in the current dataset. "
        "It does not prove causation or guarantee future performance."
    )

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
    st.write(
        f"This creates {len(df)} individual PDF reports and packages them into one ZIP file."
    )

    if st.button("Generate ALL Student PDFs"):
        with st.spinner("Generating student reports..."):
            all_reports = generate_all_student_pdfs(
                data, st.session_state.school_name
            )

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
    st.write("A central place for teachers to post assignments, notes and revision materials, and for students to access and submit work.")

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
        reviewed = sum(1 for s in all_submissions if s.get("status") == "Reviewed")
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
        a,b,c,d=st.columns(4)
        a.metric("Assignments", len(assignments))
        b.metric("Student Submissions", len(all_submissions))
        c.metric("Awaiting Review", pending)
        d.metric("Overdue Assignments", overdue)

        recent = sorted(materials, key=lambda x: x.get("created_at", ""), reverse=True)[:5]
        if recent:
            st.markdown("### 🔔 Recent Learning Centre Activity")
            for m in recent:
                icon = "📝" if m.get("material_type") == "Assignment" else ("📢" if m.get("material_type") == "Announcement" else "📚")
                st.write(f"{icon} **{m.get('title','Untitled')}** — {m.get('material_type','Material')} • {m.get('target_stream','All Streams')}")

        tab1, tab2, tab3 = st.tabs(["📤 Post Material", "📋 Posted Materials", "📥 Student Submissions"])
        with tab1:
            st.markdown("### Create a new learning resource")
            c1,c2=st.columns(2)
            with c1:
                title=st.text_input("Title", placeholder="e.g. Algebra Assignment 1")
                mtype=st.selectbox("Material type", ["Assignment","Notes","Revision Material","Announcement","Past Paper","Other"])
                subject=st.text_input("Subject", placeholder="e.g. Mathematics")
            with c2:
                streams=["All Streams"]
                if st.session_state.get("data") is not None:
                    streams += sorted([str(x) for x in st.session_state.data["df"][st.session_state.data["stream_col"]].dropna().unique()])
                target_stream=st.selectbox("Target stream / class", streams)
                deadline=st.date_input("Deadline (optional)", value=None)
                external_link=st.text_input("Video / external resource link (optional)", placeholder="https://...")
            description=st.text_area("Instructions / description", height=100)
            file=st.file_uploader("Attach notes or assignment file (optional)", type=None, key="learning_upload")
            if st.button("📤 Publish to Learning Centre", type="primary", use_container_width=True):
                if not title.strip():
                    st.error("Please enter a title.")
                elif not file and not external_link.strip() and not description.strip():
                    st.error("Add a file, link, or instructions before publishing.")
                else:
                    saved_name=""; saved_path=""
                    if file is not None:
                        safe=re.sub(r"[^A-Za-z0-9._-]+", "_", file.name)
                        folder=os.path.join(LEARNING_DIR,"materials"); os.makedirs(folder,exist_ok=True)
                        saved_path=os.path.join(folder,safe)
                        with open(saved_path,"wb") as f: f.write(file.getbuffer())
                        saved_name=safe
                    add_material(title.strip(),mtype,subject.strip(),target_stream,description.strip(),str(deadline) if deadline else "",saved_name,saved_path,external_link.strip(),st.session_state.username)
                    st.success("Material published successfully.")
                    st.rerun()

        with tab2:
            if not materials:
                st.info("No learning materials have been posted yet.")
            for m in materials:
                with st.container(border=True):
                    st.markdown(f"### {m['title']}")
                    st.write(f"**Type:** {m['material_type']}  •  **Subject:** {m['subject'] or 'General'}  •  **Target:** {m['target_stream']}")
                    if m['deadline']: st.write(f"**Deadline:** {m['deadline']}")
                    if m['description']: st.write(m['description'])
                    cols=st.columns([1,1,1,1])
                    if m['file_path'] and os.path.exists(m['file_path']):
                        with open(m['file_path'],'rb') as f:
                            cols[0].download_button("⬇️ Download file", f.read(), file_name=m['file_name'], key=f"dlm{m['id']}")
                    if m['external_link']:
                        cols[1].markdown(f"[🔗 Open link]({m['external_link']})")
                    if cols[3].button("🗑️ Delete", key=f"delm{m['id']}"):
                        delete_material(m['id']); st.rerun()
                    st.caption(f"Posted by {m['uploaded_by']} on {m['created_at']}")

        with tab3:
            subs=get_submissions()
            if not subs:
                st.info("No student submissions yet.")
            else:
                sub_df=pd.DataFrame(subs)
                st.dataframe(sub_df[["title","student_name","subject","file_name","submitted_at","status","teacher_feedback"]], use_container_width=True, hide_index=True)
                st.markdown("### Give feedback")
                sub_options={f"{s['student_name']} — {s['title']} — {s['submitted_at']}":s for s in subs}
                selected_label=st.selectbox("Submission", list(sub_options))
                selected=sub_options[selected_label]
                feedback=st.text_area("Teacher feedback", value=selected.get("teacher_feedback", ""), key=f"feedback_{selected['id']}")
                if selected["file_path"] and os.path.exists(selected["file_path"]):
                    with open(selected["file_path"],"rb") as f:
                        st.download_button("⬇️ Download submitted work", f.read(), file_name=selected["file_name"], key=f"subdl{selected['id']}")
                if st.button("Save Feedback", type="primary"):
                    conn=db_conn(); conn.execute("UPDATE submissions SET teacher_feedback=?, status='Reviewed' WHERE id=?",(feedback.strip(),selected["id"])); conn.commit(); conn.close(); st.success("Feedback saved."); st.rerun()

    else:
        st.markdown("### 🎓 Student Learning Dashboard")
        student_name=st.session_state.student_name.strip()
        if not student_name:
            st.warning("This demo student account is not yet linked to a student record. An administrator can later link student accounts to actual names.")
            student_name=st.text_input("For this demo, enter your student name")

        student_submissions = get_submissions(student_name=student_name) if student_name else []
        student_materials = []
        streams=[]
        if st.session_state.get("data") is not None and student_name:
            d=st.session_state.data["df"]; nc=st.session_state.data["name_col"]; sc=st.session_state.data["stream_col"]
            matches=d[d[nc].astype(str).str.lower()==student_name.lower()]
            if not matches.empty: streams=matches[sc].astype(str).tolist()
        for m in materials:
            if m["target_stream"]=="All Streams" or not streams or m["target_stream"] in streams:
                student_materials.append(m)

        assignments=[m for m in student_materials if m.get("material_type")=="Assignment"]
        submitted_ids={s.get("material_id") for s in student_submissions}
        pending_count=sum(1 for m in assignments if m.get("id") not in submitted_ids and (not m.get("deadline") or datetime.now().date() <= datetime.strptime(m["deadline"], "%Y-%m-%d").date()))
        overdue_count=sum(1 for m in assignments if m.get("id") not in submitted_ids and m.get("deadline") and datetime.now().date() > datetime.strptime(m["deadline"], "%Y-%m-%d").date())
        reviewed_count=sum(1 for s in student_submissions if s.get("status")=="Reviewed")

        a,b,c,d=st.columns(4)
        a.metric("Available Materials", len(student_materials))
        b.metric("Pending Assignments", pending_count)
        c.metric("Overdue", overdue_count)
        d.metric("Feedback Received", reviewed_count)

        announcements=[m for m in student_materials if m.get("material_type")=="Announcement"]
        if announcements:
            st.markdown("### 📢 Announcements")
            for m in sorted(announcements, key=lambda x:x.get("created_at", ""), reverse=True)[:5]:
                with st.container(border=True):
                    st.markdown(f"**{m['title']}**")
                    if m.get("description"): st.write(m["description"])
                    st.caption(f"Posted {m.get('created_at','')}")

        st.markdown("### 📝 Assignment Status")
        if assignments:
            rows=[]
            for m in assignments:
                rows.append({"Assignment":m["title"],"Subject":m.get("subject") or "General","Deadline":m.get("deadline") or "No deadline","Status":lc_status(m,student_name)})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No assignments are currently available.")

        st.markdown("### 📖 My Learning Materials")
        if not student_materials:
            st.info("No learning materials are currently available for you.")
        for m in student_materials:
            with st.container(border=True):
                st.markdown(f"### {m['title']}")
                st.write(f"**{m['material_type']}** • {m['subject'] or 'General'}")
                if m['deadline']: st.write(f"**Deadline:** {m['deadline']}")
                if m['description']: st.write(m['description'])
                cols=st.columns(3)
                if m['file_path'] and os.path.exists(m['file_path']):
                    with open(m['file_path'],'rb') as f:
                        cols[0].download_button("⬇️ Download", f.read(), file_name=m['file_name'], key=f"stdl{m['id']}")
                if m['external_link']: cols[1].markdown(f"[🔗 Open resource]({m['external_link']})")
                previous=get_submissions(material_id=m['id'], student_name=student_name)
                if previous:
                    st.success(f"Submitted on {previous[0]['submitted_at']} • {previous[0]['status']}")
                    if previous[0]['teacher_feedback']: st.info(f"Teacher feedback: {previous[0]['teacher_feedback']}")
                upload=st.file_uploader("Submit your work", type=None, key=f"submission_{m['id']}")
                if st.button("📤 Submit Work", key=f"submit_{m['id']}", type="primary"):
                    if not student_name.strip(): st.error("Enter your student name first.")
                    elif upload is None: st.error("Choose your file first.")
                    else:
                        save_submission(m['id'],student_name.strip(),upload); st.success("Work submitted successfully."); st.rerun()


# ============================================================
# ONLINE TESTS & QUIZZES
# ============================================================

elif page == "Online Tests & Quizzes":
    st.subheader("🧪 Online Tests & Quizzes")
    st.write("Create, deliver, mark and review online tests. Multiple-choice and True/False questions are marked automatically; short-answer questions can be reviewed by the teacher.")

    role = st.session_state.user_role
    quizzes = get_quizzes()

    def student_streams_for(name):
        streams=[]
        if st.session_state.get("data") is not None and name:
            d=st.session_state.data["df"]; nc=st.session_state.data["name_col"]; sc=st.session_state.data["stream_col"]
            matches=d[d[nc].astype(str).str.lower()==name.lower()]
            if not matches.empty:
                streams=matches[sc].astype(str).tolist()
        return streams

    if role in ("admin", "teacher"):
        attempts=get_attempts()
        st.markdown("### 📊 Quiz Dashboard")
        q1,q2,q3,q4=st.columns(4)
        q1.metric("Quizzes", len(quizzes))
        q2.metric("Attempts", len(attempts))
        q3.metric("Reviewed", sum(1 for a in attempts if a.get("status")=="Reviewed"))
        q4.metric("Awaiting Review", sum(1 for a in attempts if a.get("status")!="Reviewed"))

        create_tab, manage_tab, results_tab = st.tabs(["➕ Create Quiz", "📋 Manage Quizzes", "📊 Student Results"])

        with create_tab:
            st.markdown("### Create a new online test")
            c1,c2=st.columns(2)
            with c1:
                qtitle=st.text_input("Quiz title", placeholder="e.g. Mathematics Test 1")
                qsubject=st.text_input("Subject", placeholder="e.g. Mathematics")
                qdesc=st.text_area("Instructions / description", height=90)
            with c2:
                streams=["All Streams"]
                if st.session_state.get("data") is not None:
                    streams += sorted([str(x) for x in st.session_state.data["df"][st.session_state.data["stream_col"]].dropna().unique()])
                qstream=st.selectbox("Target stream / class", streams, key="quiz_stream")
                qdeadline=st.date_input("Closing date (optional)", value=None, key="quiz_deadline")
                qduration=st.number_input("Time limit (minutes)", min_value=1, max_value=300, value=30, step=5)
            n_questions=st.number_input("Number of questions", min_value=1, max_value=30, value=5, step=1)
            st.caption("For each question, choose Multiple Choice, True/False or Short Answer. Objective questions are auto-marked.")
            questions=[]
            for i in range(1,int(n_questions)+1):
                with st.container(border=True):
                    st.markdown(f"**Question {i}**")
                    text_q=st.text_area("Question", key=f"vq_text_{i}", height=70)
                    typ=st.selectbox("Question type", ["Multiple Choice","True / False","Short Answer"], key=f"vq_type_{i}")
                    pts=st.number_input("Marks", min_value=0.5, max_value=100.0, value=1.0, step=0.5, key=f"vq_pts_{i}")
                    q={"text":text_q.strip(),"type":typ,"points":pts}
                    if typ=="Multiple Choice":
                        a,b=st.columns(2)
                        with a:
                            q["a"]=st.text_input("Option A", key=f"vq_a_{i}")
                            q["c"]=st.text_input("Option C", key=f"vq_c_{i}")
                        with b:
                            q["b"]=st.text_input("Option B", key=f"vq_b_{i}")
                            q["d"]=st.text_input("Option D", key=f"vq_d_{i}")
                        q["correct"]=st.selectbox("Correct answer", ["A","B","C","D"], key=f"vq_correct_{i}")
                    elif typ=="True / False":
                        q["correct"]=st.selectbox("Correct answer", ["True","False"], key=f"vq_tf_{i}")
                    else:
                        q["correct"]=""
                    questions.append(q)
            if st.button("🚀 Publish Quiz", type="primary", use_container_width=True):
                if not qtitle.strip():
                    st.error("Enter a quiz title.")
                elif any(not q["text"] for q in questions):
                    st.error("Every question must have question text.")
                elif any(q["type"]=="Multiple Choice" and any(not q.get(k,"" ).strip() for k in ["a","b","c","d"]) for q in questions):
                    st.error("Complete all four options for every multiple-choice question.")
                else:
                    quiz_id=add_quiz(qtitle.strip(),qsubject.strip(),qstream,qdesc.strip(),str(qdeadline) if qdeadline else "",qduration,st.session_state.username,questions)
                    st.success(f"Quiz published successfully. Quiz ID: {quiz_id}")
                    st.rerun()

        with manage_tab:
            if not quizzes:
                st.info("No quizzes have been created yet.")
            for qz in quizzes:
                with st.container(border=True):
                    st.markdown(f"### {qz['title']}")
                    st.write(f"**Subject:** {qz['subject'] or 'General'} • **Target:** {qz['target_stream']} • **Time:** {qz['duration_minutes']} minutes")
                    if qz['deadline']: st.write(f"**Closing date:** {qz['deadline']}")
                    qs=get_quiz_questions(qz['id'])
                    st.caption(f"{len(qs)} questions • Created by {qz['created_by']} on {qz['created_at']}")
                    mc=st.columns([1,1,1])
                    if mc[0].button("👁️ Preview", key=f"qprev{qz['id']}"):
                        for qq in qs:
                            st.write(f"**{qq['question_no']}. {qq['question_text']}** ({qq['points']} marks)")
                            if qq['question_type']=="Multiple Choice": st.write(f"A. {qq['option_a']}  |  B. {qq['option_b']}  |  C. {qq['option_c']}  |  D. {qq['option_d']}")
                            elif qq['question_type']=="True / False": st.write("True / False")
                            else: st.write("Short answer")
                    if mc[2].button("🗑️ Delete", key=f"qdel{qz['id']}"):
                        delete_quiz(qz['id']); st.rerun()

        with results_tab:
            if not attempts:
                st.info("No students have attempted a quiz yet.")
            else:
                result_rows=[]
                for a in attempts:
                    pct,_=quiz_grade(a['score'],a['total_points'])
                    result_rows.append({"Quiz":a['title'],"Student":a['student_name'],"Score":f"{a['score']:.1f}/{a['total_points']:.1f}","Percentage":f"{pct:.1f}%","Status":a['status'],"Submitted":a['submitted_at']})
                st.dataframe(pd.DataFrame(result_rows), use_container_width=True, hide_index=True)
                st.markdown("### Review attempt")
                options={f"{a['student_name']} — {a['title']} — {a['submitted_at']}":a for a in attempts}
                selected_label=st.selectbox("Attempt", list(options))
                selected=options[selected_label]
                pct,g=quiz_grade(selected['score'],selected['total_points'])
                x,y,z=st.columns(3); x.metric("Score",f"{selected['score']:.1f}/{selected['total_points']:.1f}"); y.metric("Percentage",f"{pct:.1f}%"); z.metric("Grade",g)
                st.write(f"**Status:** {selected['status']}")
                answers=json.loads(selected.get('answers_json') or '{}')
                for qq in get_quiz_questions(selected['quiz_id']):
                    ans=answers.get(str(qq['id']),"")
                    st.write(f"**{qq['question_no']}. {qq['question_text']}**")
                    st.write(f"Student answer: **{ans or 'No answer'}**")
                    if qq['correct_answer']:
                        st.caption(f"Correct answer: {qq['correct_answer']}")
                feedback=st.text_area("Teacher feedback", value=selected.get('teacher_feedback',''), key=f"qfeedback{selected['id']}")
                if st.button("Save Quiz Feedback", type="primary"):
                    update_quiz_feedback(selected['id'],feedback); st.success("Quiz feedback saved."); st.rerun()

    else:
        student_name=st.session_state.student_name.strip()
        if not student_name:
            student_profile = get_student_profile(st.session_state.username)
            if student_profile:
                student_name = (student_profile.get("student_full_name") or "").strip()
        if not student_name:
            st.warning("This demo student account is not yet linked to a student record. Enter the student name used in the academic Excel file.")
            student_name=st.text_input("Student name", key="quiz_student_name")
        streams=student_streams_for(student_name)
        available=[q for q in quizzes if quiz_available_for_student(q,streams)]
        attempts=get_attempts(student_name=student_name) if student_name else []
        attempted_ids={a['quiz_id'] for a in attempts}
        pending=[q for q in available if q['id'] not in attempted_ids]
        st.markdown("### 🎓 Student Quiz Dashboard")
        a,b,c=st.columns(3); a.metric("Available Quizzes",len(available)); b.metric("Pending",len(pending)); c.metric("Completed",len(attempts))
        take_tab, result_tab=st.tabs(["📝 Available Quizzes","🏆 My Results"])
        with take_tab:
            if not pending: st.info("There are no new quizzes available for you.")
            for qz in pending:
                with st.container(border=True):
                    st.markdown(f"### {qz['title']}")
                    st.write(f"**Subject:** {qz['subject'] or 'General'} • **Questions:** {len(get_quiz_questions(qz['id']))} • **Time:** {qz['duration_minutes']} minutes")
                    if qz['deadline']: st.write(f"**Closing date:** {qz['deadline']}")
                    if qz['description']: st.write(qz['description'])
                    if st.button("▶️ Start Quiz", key=f"startquiz{qz['id']}", type="primary"):
                        st.session_state.active_quiz=qz['id']; st.rerun()
            active=st.session_state.get('active_quiz')
            if active:
                qz=next((q for q in available if q['id']==active),None)
                if qz:
                    st.divider(); st.markdown(f"## 📝 {qz['title']}")
                    st.warning(f"Time limit: {qz['duration_minutes']} minutes. Submit when you have finished.")
                    answers={}; total=0; auto_score=0; has_manual=False
                    for qq in get_quiz_questions(qz['id']):
                        pts=float(qq['points']); total += pts
                        st.markdown(f"**{qq['question_no']}. {qq['question_text']}**  _({pts:g} marks)_")
                        if qq['question_type']=="Multiple Choice":
                            ans=st.radio("Answer",[f"A. {qq['option_a']}",f"B. {qq['option_b']}",f"C. {qq['option_c']}",f"D. {qq['option_d']}"],key=f"ans{qq['id']}")
                            letter=ans.split('.',1)[0] if ans else ""
                            answers[str(qq['id'])]=letter
                            if letter==qq['correct_answer']: auto_score += pts
                        elif qq['question_type']=="True / False":
                            ans=st.radio("Answer",["True","False"],key=f"ans{qq['id']}")
                            answers[str(qq['id'])]=ans
                            if ans==qq['correct_answer']: auto_score += pts
                        else:
                            ans=st.text_area("Your answer",key=f"ans{qq['id']}",height=80)
                            answers[str(qq['id'])]=ans
                            has_manual=True
                    if st.button("📤 Submit Quiz", type="primary", use_container_width=True):
                        status="Needs Teacher Review" if has_manual else "Submitted"
                        save_quiz_attempt(qz['id'],student_name.strip(),answers,auto_score,total,status)
                        st.session_state.active_quiz=None
                        st.success(f"Quiz submitted. Auto-marked score: {auto_score:.1f}/{total:.1f}." + (" A teacher will review the short-answer question(s)." if has_manual else ""))
                        st.rerun()
        with result_tab:
            if not attempts: st.info("You have not completed any quizzes yet.")
            for a in attempts:
                pct,g=quiz_grade(a['score'],a['total_points'])
                with st.container(border=True):
                    st.markdown(f"### {a['title']}")
                    st.write(f"**Score:** {a['score']:.1f}/{a['total_points']:.1f} • **Percentage:** {pct:.1f}% • **Grade:** {g}")
                    st.write(f"**Status:** {a['status']} • Submitted: {a['submitted_at']}")
                    if a.get('teacher_feedback'): st.info(f"Teacher feedback: {a['teacher_feedback']}")


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
        st.info("The student portal is ready for account-to-student linking.")
        st.write(f"**Username:** {st.session_state.username}")
        st.write(f"**Role:** Student")
        st.write(f"**Linked student:** Not linked")


# ============================================================
# SETTINGS
# ============================================================

elif page == "Settings":
    st.subheader("School Profile & System Settings")
    st.write("Use this page to brand the system and the official PDF reports.")

    tab_profile, tab_password, tab_parents, tab_students, tab_backup = st.tabs([
        "🏫 School Profile",
        "🔒 Change Password",
        "👨‍👩‍👧 Parent Accounts",
        "🎓 Student Accounts",
        "💾 Backup & Data"
    ])

    with tab_profile:
        left, right = st.columns(2)
        with left:
            new_name = st.text_input("School name", value=st.session_state.school_name)
            address = st.text_input("School address / location", value=st.session_state.school_address)
            phone = st.text_input("School phone", value=st.session_state.school_phone)
            email = st.text_input("School email", value=st.session_state.school_email)
        with right:
            academic_year = st.text_input("Academic year", value=st.session_state.academic_year)
            current_term = st.selectbox(
                "Current term", ["Term 1", "Term 2", "Term 3"],
                index=["Term 1", "Term 2", "Term 3"].index(st.session_state.current_term)
                if st.session_state.current_term in ["Term 1", "Term 2", "Term 3"] else 2
            )
            logo = st.file_uploader("School logo (PNG/JPG)", type=["png", "jpg", "jpeg"], key="school_logo_upload")
            if logo is not None:
                st.image(logo, width=120, caption="Logo preview")

        st.divider()
        st.write("### 📝 Report Card Signatures & Principal Comment")
        sig_left, sig_right = st.columns(2)
        with sig_left:
            teacher_name = st.text_input("Class teacher name", value=st.session_state.class_teacher_name)
            teacher_sig = st.file_uploader("Class teacher signature (PNG/JPG)", type=["png", "jpg", "jpeg"], key="teacher_signature_upload")
            if teacher_sig is not None:
                st.image(teacher_sig, width=180, caption="Class teacher signature preview")
        with sig_right:
            principal_name = st.text_input("Principal / Head Teacher name", value=st.session_state.principal_name)
            principal_sig = st.file_uploader("Principal signature (PNG/JPG)", type=["png", "jpg", "jpeg"], key="principal_signature_upload")
            if principal_sig is not None:
                st.image(principal_sig, width=180, caption="Principal signature preview")
        principal_comment = st.text_area(
            "Default Principal / Head Teacher comment",
            value=st.session_state.principal_comment,
            height=100,
            help="This comment is used on report cards unless you change it here."
        )

        if st.button("Save School Profile", type="primary", use_container_width=True):
            st.session_state.school_name = new_name.strip() or DEFAULT_SCHOOL
            st.session_state.school_address = address.strip()
            st.session_state.school_phone = phone.strip()
            st.session_state.school_email = email.strip()
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
            st.success("School profile saved.")

    with tab_password:
        st.write("### 🔒 Change your password")
        st.caption("You are signed in as: **" + st.session_state.username + "** (" + st.session_state.user_role + ")")
        if st.session_state.user_role == "admin":
            st.info("The default administrator account (admin/admin123) cannot be changed from here. To change it, edit the admin credentials in app.py.")
        else:
            old_pw = st.text_input("Current password", type="password", key="pw_old")
            new_pw = st.text_input("New password", type="password", key="pw_new")
            confirm_pw = st.text_input("Confirm new password", type="password", key="pw_confirm")
            if st.button("Update Password", type="primary", use_container_width=True):
                if not old_pw or not new_pw or not confirm_pw:
                    st.error("Fill in all three fields.")
                elif new_pw != confirm_pw:
                    st.error("New passwords do not match.")
                elif len(new_pw) < 6:
                    st.error("New password should be at least 6 characters.")
                else:
                    conn = db_conn()
                    row = conn.execute("SELECT password FROM users WHERE username=?", (st.session_state.username,)).fetchone()
                    if not row or not verify_password(old_pw, row[0]):
                        conn.close()
                        st.error("Current password is incorrect.")
                    else:
                        conn.execute("UPDATE users SET password=? WHERE username=?",
                                     (hash_password(new_pw), st.session_state.username))
                        conn.commit()
                        conn.close()
                        st.success("Password updated successfully. Use the new password next time you sign in.")

    with tab_parents:
        st.caption("Link a parent account to one or more student names. Use | between multiple children.")
        conn = db_conn()
        parent_rows = conn.execute("SELECT username,parent_name,child_names FROM parents ORDER BY username").fetchall()
        conn.close()

        if parent_rows:
            st.dataframe(
                pd.DataFrame([dict(r) for r in parent_rows]),
                use_container_width=True,
                hide_index=True
            )

        pa1, pa2 = st.columns(2)
        with pa1:
            parent_username = st.text_input("Parent username", key="new_parent_username")
            parent_name = st.text_input("Parent / Guardian name", key="new_parent_name")
        with pa2:
            parent_password = st.text_input("Parent password", type="password", key="new_parent_password")
            linked_children = st.text_input(
                "Linked student name(s)",
                placeholder="e.g. Jane Wanjiku | Peter Kamau",
                key="new_parent_children"
            )

        if st.button("➕ Create / Update Parent Account", type="primary", use_container_width=True):
            if not parent_username.strip() or not parent_name.strip() or not parent_password.strip() or not linked_children.strip():
                st.error("Enter the parent username, name, password and at least one linked student name.")
            else:
                hashed_pwd = hash_password(parent_password)
                conn = db_conn()
                conn.execute(
                    "INSERT INTO users(username,password,role,student_name) VALUES(?,?,?,?) "
                    "ON CONFLICT(username) DO UPDATE SET password=excluded.password, role='parent'",
                    (parent_username.strip(), hashed_pwd, "parent", "")
                )
                conn.execute(
                    "INSERT INTO parents(username,parent_name,child_names,created_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(username) DO UPDATE SET parent_name=excluded.parent_name, child_names=excluded.child_names",
                    (parent_username.strip(), parent_name.strip(), linked_children.strip(), datetime.now().strftime("%Y-%m-%d %H:%M"))
                )
                conn.commit()
                conn.close()
                st.success("Parent account saved. The parent can now sign in using the new credentials.")
                st.rerun()

    with tab_students:
        st.caption("Link a student account to one student name so that the student can view their own results.")
        conn = db_conn()
        student_rows = conn.execute("SELECT username,student_full_name FROM students ORDER BY username").fetchall()
        conn.close()

        if student_rows:
            st.dataframe(
                pd.DataFrame([dict(r) for r in student_rows]),
                use_container_width=True,
                hide_index=True
            )

        sa1, sa2 = st.columns(2)
        with sa1:
            student_username = st.text_input("Student username", key="new_student_username")
            student_full_name = st.text_input("Linked student name", placeholder="e.g. John Mwangi", key="new_student_full_name")
        with sa2:
            student_password = st.text_input("Student password", type="password", key="new_student_password")

        if st.button("➕ Create / Update Student Account", type="primary", use_container_width=True):
            if not student_username.strip() or not student_full_name.strip() or not student_password.strip():
                st.error("Enter the student username, name and password.")
            else:
                hashed_pwd = hash_password(student_password)
                conn = db_conn()
                conn.execute(
                    "INSERT INTO users(username,password,role,student_name) VALUES(?,?,?,?) "
                    "ON CONFLICT(username) DO UPDATE SET password=excluded.password, role='student', student_name=excluded.student_name",
                    (student_username.strip(), hashed_pwd, "student", student_full_name.strip())
                )
                conn.execute(
                    "INSERT INTO students(username,student_full_name,created_at) VALUES(?,?,?) "
                    "ON CONFLICT(username) DO UPDATE SET student_full_name=excluded.student_full_name",
                    (student_username.strip(), student_full_name.strip(), datetime.now().strftime("%Y-%m-%d %H:%M"))
                )
                conn.commit()
                conn.close()
                st.success("Student account saved. The student can now sign in using the new credentials.")
                st.rerun()

    with tab_backup:
        st.write("### 💾 Download a full backup")
        st.caption("This ZIP contains the database, the current results file and every uploaded Learning Centre file.")
        if st.button("Prepare Backup ZIP", type="primary", use_container_width=True):
            with st.spinner("Packaging backup..."):
                backup = create_backup_zip()
            st.download_button(
                "⬇️ Download Backup ZIP",
                data=backup.getvalue(),
                file_name=f"Academic_System_Backup_{datetime.now().strftime('%Y%m%d_%H%M')}.zip",
                mime="application/zip",
                use_container_width=True
            )

        st.divider()
        st.write("### Current school profile")
        st.write(f"**School:** {st.session_state.school_name}")
        st.write(f"**Location:** {st.session_state.school_address or 'Not set'}")
        st.write(f"**Phone:** {st.session_state.school_phone or 'Not set'}")
        st.write(f"**Email:** {st.session_state.school_email or 'Not set'}")
        st.write(f"**Academic year:** {st.session_state.academic_year}")
        st.write(f"**Current term:** {st.session_state.current_term}")

        st.divider()
        st.write("### Current data")
        st.write(f"**File:** {st.session_state.raw_file_name or 'No file loaded'}")
        if data is not None:
            st.write(f"**Analysis term:** {data['analysis_term'].upper()}")
            st.write(f"**Students:** {len(df)}")
            st.write(f"**Streams:** {df[stream_col].nunique()}")

        st.warning(
            "Parent and student accounts are linked to specific students. For deployment over the internet, use HTTPS and a hosted database."
        )
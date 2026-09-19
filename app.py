import sys
import os

# --- CRITICAL FIX FOR WINDOWED MODE (--noconsole) ---
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
# ----------------------------------------------------

import gradio as gr
import sqlite3
import pandas as pd
import re
import socket
import hashlib
from datetime import datetime
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

INSTITUTE_NAME = "Department of Textile Technology"
APP_TITLE = "Internal Marks Evaluation Portal"
DB_PATH = "marks.db"
UPLOAD_FOLDER = "uploads"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

CSS = """
* { font-family: "Times New Roman", Times, serif !important; font-size: 16px !important; }
.gradio-container { max-width: none !important; width: 100% !important; margin: 0 !important; padding: 0 !important; background: #f4f6f9 !important; }

#hero {
    background: linear-gradient(135deg, #1e3a8a, #2563eb, #0d9488) !important;
    padding: 36px 20px !important;
    color: white !important;
    text-align: center !important;
    box-shadow: 0 4px 20px rgba(0,0,0,0.1) !important;
    margin-bottom: 25px !important;
}
#hero h1 { font-size: 34px !important; font-weight: 700 !important; color: #ffffff !important; margin: 0 0 6px 0 !important; }
#hero p { font-size: 18px !important; font-weight: 500 !important; color: #e2e8f0 !important; margin: 0 !important; }

.main-card {
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 14px !important;
    padding: 24px !important;
    margin: 15px auto !important;
    box-shadow: 0 4px 15px rgba(15,23,42,0.05) !important;
}

button.primary { background: linear-gradient(90deg, #2563eb, #1d4ed8) !important; color: white !important; font-weight: 700 !important; border-radius: 8px !important; }
button.stop { background: linear-gradient(90deg, #dc2626, #b91c1c) !important; color: white !important; font-weight: 700 !important; border-radius: 8px !important; }
button.secondary { background: linear-gradient(90deg, #0d9488, #0f766e) !important; color: white !important; font-weight: 700 !important; border-radius: 8px !important; }

footer { display: none !important; visibility: hidden !important; }
.footer { display: none !important; }
"""

SWEETALERT_HEAD = '''
<script src="https://cdn.jsdelivr.net/npm/sweetalert2@11"></script>
<script>
function showImagePopup(imagePath) {
    if (!imagePath || imagePath === "No File" || imagePath === "No Image") {
        Swal.fire({
            icon: 'info',
            title: 'No File Found',
            text: 'This student has not uploaded an answer sheet front sheet yet.',
            confirmButtonColor: '#2563eb'
        });
        return;
    }
    let cleanPath = imagePath.replace(/\\\\/g, '/');
    if (!cleanPath.startsWith('/')) {
        cleanPath = '/' + cleanPath;
    }
    Swal.fire({
        title: '<strong>Student Answer Sheet Front Page</strong>',
        html: `<div style="text-align:center; padding:5px;"><img src="${cleanPath}" style="max-width:100%; max-height:75vh; height:auto; border-radius:8px; border:1px solid #cbd5e1; box-shadow:0 4px 12px rgba(0,0,0,0.15);" alt="Front Sheet"></div>`,
        width: '800px',
        showCloseButton: true,
        showConfirmButton: false,
        background: '#f8fafc'
    });
}
</script>
'''

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS staff_users (
            staff_id TEXT PRIMARY KEY,
            staff_name TEXT NOT NULL,
            password_hash TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id TEXT NOT NULL,
            subject_code TEXT NOT NULL,
            subject_name TEXT NOT NULL,
            semester TEXT,
            academic_session TEXT,
            exam_name TEXT NOT NULL,
            allowed_reg_nos TEXT,
            pattern_locked INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(staff_id) REFERENCES staff_users(staff_id) ON DELETE CASCADE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS question_pattern (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER NOT NULL,
            part_name TEXT NOT NULL,
            question_no INTEGER NOT NULL,
            max_mark REAL NOT NULL,
            UNIQUE(subject_id, part_name, question_no),
            FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS student_submissions (
            subject_id INTEGER NOT NULL,
            register_no TEXT NOT NULL,
            student_name TEXT NOT NULL,
            is_locked INTEGER NOT NULL DEFAULT 0,
            image_path TEXT,
            locked_at TIMESTAMP,
            PRIMARY KEY(subject_id, register_no),
            FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS student_marks (
            subject_id INTEGER NOT NULL,
            register_no TEXT NOT NULL,
            question_id INTEGER NOT NULL,
            score REAL NOT NULL,
            PRIMARY KEY(subject_id, register_no, question_id),
            FOREIGN KEY(subject_id) REFERENCES subjects(id) ON DELETE CASCADE,
            FOREIGN KEY(question_id) REFERENCES question_pattern(id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def safe_text(val):
    return str(val or "").strip()

def get_staff_list():
    conn = get_conn()
    rows = conn.execute("SELECT staff_id, staff_name FROM staff_users ORDER BY staff_id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_staff_subjects(staff_id):
    if not safe_text(staff_id): return []
    conn = get_conn()
    rows = conn.execute("SELECT * FROM subjects WHERE staff_id=? ORDER BY id DESC", (safe_text(staff_id),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_subjects_hod():
    conn = get_conn()
    rows = conn.execute("SELECT s.*, su.staff_name FROM subjects s LEFT JOIN staff_users su ON s.staff_id = su.staff_id ORDER BY s.id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_student_subject_choices(reg_no=""):
    reg = safe_text(reg_no).upper()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM subjects WHERE pattern_locked=1 ORDER BY id DESC").fetchall()
    conn.close()
    
    valid_subs = []
    for s in rows:
        allowed_raw = safe_text(s["allowed_reg_nos"])
        if allowed_raw and reg:
            allowed_list = [r.strip().upper() for r in re.split(r'[,\\n\\s]+', allowed_raw) if r.strip()]
            if reg in allowed_list:
                valid_subs.append(f"{s['subject_code']} - {s['subject_name']} ({s['exam_name']}) [ID: {s['id']}]")
        elif not allowed_raw:
            valid_subs.append(f"{s['subject_code']} - {s['subject_name']} ({s['exam_name']}) [ID: {s['id']}]")
    return valid_subs

def get_subject_by_id(subject_id):
    if not subject_id: return None
    conn = get_conn()
    row = conn.execute("SELECT * FROM subjects WHERE id=?", (subject_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def get_pattern(subject_id):
    if not subject_id: return []
    conn = get_conn()
    rows = conn.execute("SELECT * FROM question_pattern WHERE subject_id=? ORDER BY part_name, question_no", (subject_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_subject_upload_folder(sub):
    sub_code = re.sub(r'[^A-Za-z0-9_-]', '_', safe_text(sub["subject_code"]))
    exam_name = re.sub(r'[^A-Za-z0-9_-]', '_', safe_text(sub["exam_name"]))
    sub_folder = os.path.join(UPLOAD_FOLDER, f"{sub_code}_{exam_name}_{sub['id']}")
    os.makedirs(sub_folder, exist_ok=True)
    return sub_folder

def hod_login_handler(hod_id, hod_pass):
    if safe_text(hod_id) == "HOD" and safe_text(hod_pass) == "admin123":
        staffs = get_staff_list()
        staff_choices = [f"{st['staff_id']} - {st['staff_name']}" for st in staffs]
        subjects = get_all_subjects_hod()
        sub_rows = [[s["id"], s["subject_code"], s["subject_name"], s["staff_name"] or s["staff_id"], s["exam_name"]] for s in subjects]
        return gr.update(visible=True), "✅ HOD Login Successful!", gr.update(choices=staff_choices), sub_rows
    return gr.update(visible=False), "❌ Invalid HOD Credentials (Use HOD / admin123)", gr.update(choices=[]), []

def hod_register_staff(sid, sname, spass):
    if not safe_text(sid) or not safe_text(sname) or not safe_text(spass):
        return "❌ All staff fields are required.", []
    conn = get_conn()
    try:
        hpw = hash_password(spass)
        conn.execute("INSERT OR REPLACE INTO staff_users(staff_id, staff_name, password_hash) VALUES (?, ?, ?)", (safe_text(sid), safe_text(sname), hpw))
        conn.commit()
        staffs = get_staff_list()
        choices = [f"{st['staff_id']} - {st['staff_name']}" for st in staffs]
        return f"✅ Staff {sid} ({sname}) registered/updated successfully!", gr.update(choices=choices)
    except Exception as e:
        return f"❌ Error: {str(e)}", gr.update()
    finally:
        conn.close()

def hod_create_subject(code, name, sem, session, exam, assigned_staff):
    if not safe_text(code) or not safe_text(name) or not assigned_staff:
        return "❌ Subject Code, Name, and Assigned Staff are required.", []
    match = re.search(r"^([^\s-]+)", assigned_staff)
    if not match: return "❌ Invalid staff selection.", []
    staff_id = match.group(1)
    
    conn = get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO subjects(staff_id, subject_code, subject_name, semester, academic_session, exam_name, allowed_reg_nos, pattern_locked)
            VALUES (?, ?, ?, ?, ?, ?, '', 0)
        ''', (staff_id, safe_text(code).upper(), safe_text(name), safe_text(sem), safe_text(session), safe_text(exam) or "Internal Exam"))
        conn.commit()
        active_id = cursor.lastrowid
        
        default_questions = []
        for i in range(1, 8): default_questions.append((active_id, "A", i, 2.0))
        for i in range(1, 3): default_questions.append((active_id, "B", i, 12.0))
        default_questions.append((active_id, "C", 1, 12.0))
        conn.executemany("INSERT INTO question_pattern(subject_id, part_name, question_no, max_mark) VALUES (?, ?, ?, ?)", default_questions)
        conn.commit()
        
        subjects = get_all_subjects_hod()
        sub_rows = [[s["id"], s["subject_code"], s["subject_name"], s["staff_name"] or s["staff_id"], s["exam_name"]] for s in subjects]
        return f"✅ Subject created and assigned to Staff {staff_id}!", sub_rows
    except Exception as e:
        return f"❌ Error: {str(e)}", []
    finally:
        conn.close()

def staff_login_handler(staff_id, staff_password_input):
    sid = safe_text(staff_id)
    spass = safe_text(staff_password_input)
    if not sid or not spass:
        return gr.update(visible=False), gr.update(choices=[]), "❌ Staff ID and Password are required."
    
    conn = get_conn()
    row = conn.execute("SELECT staff_name, password_hash FROM staff_users WHERE staff_id=?", (sid,)).fetchone()
    conn.close()
    
    if not row or row["password_hash"] != hash_password(spass):
        return gr.update(visible=False), gr.update(choices=[]), "❌ Authentication Failed: Invalid Staff ID or Password."
        
    subjects = get_staff_subjects(sid)
    choices = [f"{s['subject_code']} - {s['subject_name']} ({s['exam_name']}) [ID: {s['id']}]" for s in subjects]
    return gr.update(visible=True), gr.update(choices=choices, value=choices[0] if choices else None), f"✅ Welcome Staff: {sid} ({row['staff_name']})."

def save_or_update_subject_staff(staff_id, subject_id, reg_list):
    if not subject_id: return "❌ No subject selected.", "", gr.update()
    conn = get_conn()
    try:
        conn.execute("UPDATE subjects SET allowed_reg_nos=? WHERE id=?", (safe_text(reg_list), int(subject_id)))
        conn.commit()
        submissions_html, reg_choices = load_submissions_html(subject_id)
        return "✅ Authorized student register numbers updated successfully!", submissions_html, gr.update(choices=reg_choices)
    except Exception as e:
        return f"❌ Error: {str(e)}", "", gr.update()
    finally:
        conn.close()

def load_subject_details_staff(subject_dropdown):
    if not subject_dropdown: return None, "", "", "", "", "", "", [], "", gr.update(interactive=True), gr.update(interactive=True), gr.update(choices=[])
    match = re.search(r"\[ID:\s*(\d+)\]", subject_dropdown)
    if not match: return None, "", "", "", "", "", "", [], "", gr.update(interactive=True), gr.update(interactive=True), gr.update(choices=[])
    sid = int(match.group(1))
    sub = get_subject_by_id(sid)
    if not sub: return None, "", "", "", "", "", "", [], "", gr.update(interactive=True), gr.update(interactive=True), gr.update(choices=[])
    
    pattern = get_pattern(sid)
    pat_rows = [[p["part_name"], p["question_no"], p["max_mark"]] for p in pattern]
    submissions_html, reg_choices = load_submissions_html(sid)
    locked = bool(sub["pattern_locked"])
    return (
        sid, sub["subject_code"], sub["subject_name"], sub["semester"] or "", 
        sub["academic_session"] or "", sub["exam_name"] or "", sub["allowed_reg_nos"] or "", 
        pat_rows, submissions_html, 
        gr.update(interactive=not locked), gr.update(interactive=not locked),
        gr.update(choices=reg_choices, value=reg_choices[0] if reg_choices else None)
    )

def save_pattern_staff(subject_id, flex_data):
    if not subject_id: return "❌ No subject selected."
    sub = get_subject_by_id(subject_id)
    if sub and sub["pattern_locked"]:
        return "🔒 Pattern is already locked and cannot be modified."
    
    conn = get_conn()
    try:
        conn.execute("DELETE FROM question_pattern WHERE subject_id=?", (subject_id,))
        rows = flex_data.values.tolist() if isinstance(flex_data, pd.DataFrame) else (flex_data or [])
        for row in rows:
            if len(row) >= 3 and row[0] and row[1] is not None and row[2] is not None:
                part = safe_text(row[0]).upper()
                qno = int(row[1])
                mx = float(row[2])
                conn.execute("INSERT INTO question_pattern(subject_id, part_name, question_no, max_mark) VALUES (?, ?, ?, ?)", (subject_id, part, qno, mx))
        conn.commit()
        return "✅ Question pattern saved successfully!"
    except Exception as e:
        conn.rollback()
        return f"❌ Error saving pattern: {str(e)}"
    finally:
        conn.close()

def lock_pattern_staff(subject_id):
    if not subject_id: return "❌ No subject selected."
    pattern = get_pattern(subject_id)
    if not pattern:
        return "❌ Cannot lock: Please save a question pattern first."
    
    conn = get_conn()
    conn.execute("UPDATE subjects SET pattern_locked=1 WHERE id=?", (subject_id,))
    conn.commit()
    conn.close()
    return "🔒 Question pattern locked & published for students!"

def handle_admin_submission_action(action, target_reg, subject_id):
    if not subject_id or not target_reg:
        html, choices = load_submissions_html(subject_id)
        return html, "❌ Please select a Student Register Number.", gr.update(choices=choices)
    
    reg_no = safe_text(target_reg).upper()
    conn = get_conn()
    try:
        if action == "unlock":
            conn.execute("UPDATE student_submissions SET is_locked=0 WHERE subject_id=? AND register_no=?", (subject_id, reg_no))
            conn.commit()
            msg = f"🔓 Student {reg_no} submission unlocked successfully!"
        elif action == "delete":
            conn.execute("DELETE FROM student_marks WHERE subject_id=? AND register_no=?", (subject_id, reg_no))
            conn.execute("DELETE FROM student_submissions WHERE subject_id=? AND register_no=?", (subject_id, reg_no))
            conn.commit()
            msg = f"🗑️ Student {reg_no} submission record deleted!"
        else:
            msg = "❌ Unknown action."
        html, choices = load_submissions_html(subject_id)
        return html, msg, gr.update(choices=choices, value=choices[0] if choices else None)
    except Exception as e:
        html, choices = load_submissions_html(subject_id)
        return html, f"❌ Error: {str(e)}", gr.update(choices=choices)
    finally:
        conn.close()

def load_submissions_html(subject_id):
    if not subject_id: return "<div style='padding:12px; color:#64748b;'>No subject selected.</div>", []
    pattern = get_pattern(subject_id)
    if not pattern: return "<div style='padding:12px; color:#64748b;'>No question pattern configured.</div>", []
    
    conn = get_conn()
    subs = conn.execute("SELECT register_no, student_name, is_locked, image_path FROM student_submissions WHERE subject_id=?", (subject_id,)).fetchall()
    if not subs:
        conn.close()
        return "<div style='padding:12px; color:#64748b;'>No student submissions found yet.</div>", []
    
    student_reg_choices = [s["register_no"] for s in subs]
    
    html = """
    <div style="overflow-x:auto;">
    <table style="width:100%; border-collapse:collapse; background:#ffffff; text-align:left; font-size:15px;">
      <thead>
        <tr style="background:#eef2f7; color:#1e293b; border-bottom:2px solid #cbd5e1;">
          <th style="padding:10px; border:1px solid #e2e8f0;">Register No</th>
          <th style="padding:10px; border:1px solid #e2e8f0;">Student Name</th>
          <th style="padding:10px; border:1px solid #e2e8f0;">Status</th>
          <th style="padding:10px; border:1px solid #e2e8f0; text-align:center;">Front Sheet</th>
    """
    for q in pattern:
        html += f'<th style="padding:10px; border:1px solid #e2e8f0; text-align:center;">{q["part_name"]}Q{q["question_no"]}</th>'
    html += "</tr></thead><tbody>"
    
    for s in subs:
        reg = s["register_no"]
        name = s["student_name"]
        status = "LOCKED" if s["is_locked"] else "DRAFT"
        status_color = "#16a34a" if s["is_locked"] else "#d97706"
        raw_img = s["image_path"] if s["image_path"] else ""
        
        if raw_img and os.path.exists(raw_img):
            safe_img_path = raw_img.replace("\\", "/")
            img_action = f'<button onclick="showImagePopup(\'{safe_img_path}\')" style="background:#0d9488; color:white; border:none; padding:5px 12px; border-radius:6px; cursor:pointer; font-weight:bold; font-size:14px; box-shadow:0 2px 4px rgba(0,0,0,0.1);">👁️ View Sheet</button>'
        else:
            img_action = '<span style="color:#94a3b8; font-style:italic;">No File</span>'
            
        html += f"""
        <tr style="border-bottom:1px solid #e2e8f0;">
          <td style="padding:10px; border:1px solid #e2e8f0; font-weight:600;">{reg}</td>
          <td style="padding:10px; border:1px solid #e2e8f0;">{name}</td>
          <td style="padding:10px; border:1px solid #e2e8f0; font-weight:bold; color:{status_color};">{status}</td>
          <td style="padding:10px; border:1px solid #e2e8f0; text-align:center;">{img_action}</td>
        """
        
        for q in pattern:
            m_row = conn.execute("SELECT score FROM student_marks WHERE subject_id=? AND register_no=? AND question_id=?", (subject_id, reg, q["id"])).fetchone()
            score_val = m_row["score"] if m_row else ""
            html += f'<td style="padding:10px; border:1px solid #e2e8f0; text-align:center;">{score_val}</td>'
        html += "</tr>"
        
    html += "</tbody></table></div>"
    conn.close()
    return html, student_reg_choices

def export_to_excel(subject_id):
    if not subject_id: return None
    sub = get_subject_by_id(subject_id)
    if not sub: return None
    
    pattern = get_pattern(subject_id)
    if not pattern: return None
    
    conn = get_conn()
    subs = conn.execute("SELECT register_no, student_name, is_locked, image_path FROM student_submissions WHERE subject_id=?", (subject_id,)).fetchall()
    if not subs:
        conn.close()
        return None
        
    q_columns = [f"{q['part_name']}Q{q['question_no']}" for q in pattern]
    data = []
    for s in subs:
        reg = s["register_no"]
        name = s["student_name"]
        status = "LOCKED" if s["is_locked"] else "DRAFT"
        raw_img = "Available" if (s["image_path"] and os.path.exists(s["image_path"])) else "No File"
        
        row_dict = {
            "Register No": reg,
            "Student Name": name,
            "Status": status,
            "Front Sheet Image": raw_img
        }
        
        for q in pattern:
            q_col_name = f"{q['part_name']}Q{q['question_no']}"
            m_row = conn.execute("SELECT score FROM student_marks WHERE subject_id=? AND register_no=? AND question_id=?", (subject_id, reg, q["id"])).fetchone()
            row_dict[q_col_name] = m_row["score"] if m_row else ""
            
        data.append(row_dict)
    conn.close()
    
    base_cols = ["Register No", "Student Name", "Status", "Front Sheet Image"]
    df = pd.DataFrame(data)
    for c in base_cols + q_columns:
        if c not in df.columns: df[c] = ""
        
    filename = f"Marks_{sub['subject_code']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df[base_cols + q_columns].to_excel(filename, index=False)
    return filename

def validate_student_login(subject_dropdown, reg_no, name):
    reg = safe_text(reg_no).upper()
    sname = safe_text(name)
    if not subject_dropdown:
        return gr.update(visible=False), gr.update(visible=False), "❌ Please select an active subject.", gr.update(), gr.update(), gr.update()
    if not reg or not sname:
        return gr.update(visible=False), gr.update(visible=False), "❌ Please enter both Register Number and Full Name.", gr.update(), gr.update(), gr.update()
    
    match = re.search(r"\[ID:\s*(\d+)\]", subject_dropdown)
    if not match: return gr.update(visible=False), gr.update(visible=False), "❌ Invalid subject selection.", gr.update(), gr.update(), gr.update()
    sub_id = int(match.group(1))
    sub = get_subject_by_id(sub_id)
    
    if not sub or not sub["pattern_locked"]:
        return gr.update(visible=False), gr.update(visible=False), "❌ Selected exam pattern is not locked by staff yet.", gr.update(), gr.update(), gr.update()
    
    allowed_raw = safe_text(sub["allowed_reg_nos"])
    if allowed_raw:
        allowed_list = [r.strip().upper() for r in re.split(r'[,\\n\\s]+', allowed_raw) if r.strip()]
        if allowed_list and reg not in allowed_list:
            return gr.update(visible=False), gr.update(visible=False), f"❌ Access Denied: Register Number '{reg}' has not been added for this subject by course staff.", gr.update(), gr.update(), gr.update()

    pattern = get_pattern(sub_id)
    if not pattern:
        return gr.update(visible=False), gr.update(visible=False), "❌ No question pattern configured for this subject.", gr.update(), gr.update(), gr.update()
    
    conn = get_conn()
    saved_marks = {r["question_id"]: r["score"] for r in conn.execute("SELECT question_id, score FROM student_marks WHERE subject_id=? AND register_no=?", (sub_id, reg)).fetchall()}
    sub_row = conn.execute("SELECT is_locked, image_path FROM student_submissions WHERE subject_id=? AND register_no=?", (sub_id, reg)).fetchone()
    conn.close()
    
    is_locked = bool(sub_row and sub_row["is_locked"])
    existing_img = sub_row["image_path"] if (sub_row and sub_row["image_path"] and os.path.exists(sub_row["image_path"])) else None
    
    rows = []
    for q in pattern:
        val = saved_marks.get(q["id"], "")
        rows.append([q["part_name"], q["question_no"], q["max_mark"], val])
    
    status_msg = "🔒 Your submission is currently LOCKED (View-Only Mode)." if is_locked else "✅ Validated! You can enter marks and upload your answer sheet front sheet."
    
    df_interactive = False if is_locked else [False, False, False, True]
    
    return (
        gr.update(value=rows, visible=True, interactive=df_interactive), 
        gr.update(visible=True), 
        status_msg, 
        gr.update(interactive=not is_locked),
        gr.update(interactive=not is_locked),
        gr.update(value=existing_img, interactive=not is_locked)
    )

def student_live_validate(data):
    if data is None: return ""
    rows = data.values.tolist() if isinstance(data, pd.DataFrame) else (data or [])
    errors = []
    for idx, row in enumerate(rows, 1):
        if len(row) >= 4 and row[3] not in ("", None):
            try:
                score = float(row[3])
                mx = float(row[2])
                if score < 0:
                    errors.append(f"Row {idx}: Mark cannot be negative.")
                elif score > mx:
                    errors.append(f"Row {idx}: Earned mark ({score}) exceeds Max Mark ({mx}).")
            except ValueError:
                errors.append(f"Row {idx}: Invalid numeric format.")
    if errors:
        return "⚠️ " + " | ".join(errors)
    return "✅ Marks are valid."

def save_or_lock_student(subject_dropdown, reg_no, name, image_file, data, action_type):
    reg = safe_text(reg_no).upper()
    sname = safe_text(name)
    if not subject_dropdown or not reg or not sname:
        return "❌ Subject, Register Number, and Name are required."
    
    match = re.search(r"\[ID:\s*(\d+)\]", subject_dropdown)
    if not match: return "❌ Invalid subject selection."
    sub_id = int(match.group(1))
    sub = get_subject_by_id(sub_id)
    if not sub: return "❌ Subject record not found."
    
    sub_code_clean = re.sub(r'[^A-Za-z0-9_-]', '_', safe_text(sub["subject_code"]))
    
    rows = data.values.tolist() if isinstance(data, pd.DataFrame) else (data or [])
    
    for row in rows:
        if len(row) >= 4 and row[3] not in ("", None):
            try:
                score = float(row[3])
                mx = float(row[2])
                if score > mx:
                    return f"❌ Submission Failed: Earned mark ({score}) exceeds Max Mark ({mx}) for Part {row[0]} Q{row[1]}."
            except ValueError:
                return "❌ Submission Failed: Please ensure all entered marks are numbers."
    
    sub_folder = get_subject_upload_folder(sub)
    img_path = None
    if image_file is not None:
        filename = f"{reg}_{sub_code_clean}.jpg"
        img_path = os.path.join(sub_folder, filename).replace("\\", "/")
        if hasattr(image_file, "read"):
            with open(img_path, "wb") as f:
                f.write(image_file.read())
        elif isinstance(image_file, str) and os.path.exists(image_file):
            import shutil
            shutil.copy(image_file, img_path)

    is_locked = 1 if action_type == "lock" else 0
    conn = get_conn()
    try:
        if not img_path:
            existing = conn.execute("SELECT image_path FROM student_submissions WHERE subject_id=? AND register_no=?", (sub_id, reg)).fetchone()
            if existing: img_path = existing["image_path"]

        conn.execute('''
            INSERT INTO student_submissions(subject_id, register_no, student_name, is_locked, image_path, locked_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(subject_id, register_no) DO UPDATE SET
            student_name=excluded.student_name, is_locked=excluded.is_locked, 
            image_path=COALESCE(excluded.image_path, student_submissions.image_path),
            locked_at=CURRENT_TIMESTAMP
        ''', (sub_id, reg, sname, is_locked, img_path))
        
        for row in rows:
            part, qno, mx, score = row[0], row[1], row[2], row[3]
            if score != "" and score is not None:
                q_row = conn.execute("SELECT id FROM question_pattern WHERE subject_id=? AND part_name=? AND question_no=?", (sub_id, part, qno)).fetchone()
                if q_row:
                    conn.execute('''
                        INSERT INTO student_marks(subject_id, register_no, question_id, score)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(subject_id, register_no, question_id) DO UPDATE SET score=excluded.score
                    ''', (sub_id, reg, q_row["id"], float(score)))
        conn.commit()
        return "🔒 Data submitted and locked successfully!" if is_locked else "💾 Draft saved successfully!"
    except Exception as e:
        conn.rollback()
        return f"❌ Error saving: {str(e)}"
    finally:
        conn.close()

with gr.Blocks(title=APP_TITLE) as app:
    staff_sub_id_state = gr.State(None)

    gr.HTML(f"""
        <div id='hero'>
            <h1>🎓 {INSTITUTE_NAME}</h1>
            <p>{APP_TITLE}</p>
        </div>
    """)

    with gr.Tabs() as portal_tabs:
        with gr.Tab("🏠 Home / Role Selection"):
            with gr.Row(elem_classes=["main-card"]):
                gr.Markdown("## Welcome to the Evaluation Portal\nSelect your role to login:")
                with gr.Row():
                    goto_hod_btn = gr.Button("🛡️ HOD / Admin Portal", variant="primary", scale=1)
                    goto_staff_btn = gr.Button("👨‍🏫 Staff Portal", variant="secondary", scale=1)
                    goto_student_btn = gr.Button("👩‍🎓 Student Portal", variant="stop", scale=1)

        # --- HOD / ADMIN PORTAL ---
        with gr.Tab("🛡️ HOD Portal", id="hod_tab"):
            with gr.Column(elem_classes=["main-card"]):
                gr.Markdown("## 🛡️ HOD / Admin Authentication")
                with gr.Row():
                    hod_id_input = gr.Textbox(label="Admin ID", placeholder="HOD")
                    hod_pass_input = gr.Textbox(label="Password", type="password", placeholder="admin123")
                    hod_login_btn = gr.Button("Login as HOD", variant="primary")
                hod_login_status = gr.Markdown()

            with gr.Column(visible=False, elem_classes=["main-card"]) as hod_dashboard:
                gr.Markdown("## 👥 Staff Management (Register Staff Accounts)")
                with gr.Row():
                    new_staff_id = gr.Textbox(label="Staff ID", placeholder="EMP101")
                    new_staff_name = gr.Textbox(label="Staff Name", placeholder="Dr. John")
                    new_staff_pass = gr.Textbox(label="Temporary Password", type="password", placeholder="secret")
                reg_staff_btn = gr.Button("Register / Update Staff", variant="primary")
                reg_staff_status = gr.Markdown()

                gr.Markdown("---")
                gr.Markdown("## 📚 Subject Creation & Staff Assignment")
                with gr.Row():
                    hod_sub_code = gr.Textbox(label="Subject Code", placeholder="TX301")
                    hod_sub_name = gr.Textbox(label="Subject Name", placeholder="Advanced Textile Testing")
                    hod_sub_sem = gr.Textbox(label="Semester", placeholder="V")
                with gr.Row():
                    hod_sub_session = gr.Textbox(label="Academic Session", placeholder="2025-2026 / Odd")
                    hod_sub_exam = gr.Textbox(label="Exam Name", placeholder="Internal Assessment 1")
                    hod_assigned_staff = gr.Dropdown(label="Assign to Staff", choices=[])
                create_sub_btn = gr.Button("Create & Assign Subject", variant="primary")
                hod_sub_status = gr.Markdown()

                gr.Markdown("---")
                gr.Markdown("## 📋 All System Subjects Overview")
                hod_subjects_table = gr.Dataframe(headers=["ID", "Code", "Name", "Assigned Staff", "Exam"], interactive=False)

        # --- STAFF PORTAL ---
        with gr.Tab("👨‍🏫 Staff Portal", id="staff_tab"):
            with gr.Column(elem_classes=["main-card"]):
                gr.Markdown("## 👨‍🏫 Staff Authentication")
                with gr.Row():
                    staff_id_input = gr.Textbox(label="Staff ID", placeholder="EMP101")
                    staff_password_input = gr.Textbox(label="Password", type="password", placeholder="Password")
                    staff_login_btn = gr.Button("Staff Login", variant="primary")
                staff_login_status = gr.Markdown()

            with gr.Column(visible=False, elem_classes=["main-card"]) as staff_main_content:
                gr.Markdown("## ⚙️ Select Assigned Subject")
                with gr.Row():
                    staff_subject_dropdown = gr.Dropdown(label="My Assigned Subjects", choices=[], scale=4)
                    load_subject_btn = gr.Button("Load Subject Data", variant="secondary", scale=1)

                gr.Markdown("---")
                gr.Markdown("## 👥 Authorize Student Register Numbers")
                s_reg_list = gr.Textbox(label="Student Register Numbers (Comma or Newline Separated)", placeholder="21TX01, 21TX02, 21TX03", lines=3)
                save_regs_btn = gr.Button("💾 Save Authorized Register Numbers", variant="primary")
                staff_reg_status = gr.Markdown()

                gr.Markdown("---")
                gr.Markdown("## 📋 Question Pattern (Edit & Customize)")
                flex_pattern_df = gr.Dataframe(
                    headers=["Part (A/B/C)", "Question No", "Max Mark"],
                    datatype=["str", "number", "number"],
                    interactive=True,
                    value=[["A", 1, 2]]
                )

                with gr.Row():
                    save_pat_btn = gr.Button("💾 Save Question Pattern", variant="primary", interactive=True)
                    lock_pat_btn = gr.Button("🔒 Lock & Publish Pattern", variant="stop", interactive=True)
                
                pat_save_status = gr.Markdown()

                gr.Markdown("---")
                gr.Markdown("## 📊 Monitor Student Submissions & Front-Sheet Uploads")
                submissions_html_view = gr.HTML("<div style='padding:12px; color:#64748b;'>Load a subject to view student matrix and files.</div>")
                
                with gr.Row(elem_classes=["main-card"]):
                    admin_target_reg = gr.Dropdown(label="Select Student Register No to Manage", choices=[])
                    admin_unlock_btn = gr.Button("🔓 Unlock Student", variant="secondary")
                    admin_delete_btn = gr.Button("🗑️ Delete Student Record", variant="stop")

                with gr.Row():
                    refresh_subs_btn = gr.Button("🔄 Refresh Table", variant="secondary")
                    export_excel_btn = gr.Button("📥 Export to Excel", variant="primary")

                excel_file_output = gr.File(label="Download Consolidated Excel")

        # --- STUDENT PORTAL ---
        with gr.Tab("👩‍🎓 Student Portal", id="student_tab"):
            with gr.Column(elem_classes=["main-card"]):
                gr.Markdown("## 👩‍🎓 Student Exam Login")
                with gr.Row():
                    st_reg = gr.Textbox(label="Register Number", placeholder="e.g. 21TX01")
                    st_name = gr.Textbox(label="Full Name", placeholder="Enter your full name")
                    load_student_exams_btn = gr.Button("🔍 Find Eligible Exams", variant="secondary")

                with gr.Row():
                    student_subject_dropdown = gr.Dropdown(label="Select Active Exam Subject (Unlocked & Authorized)", choices=[])
                
                validate_student_btn = gr.Button("Validate & Load Exam Form", variant="primary")
                student_status = gr.Markdown()

            with gr.Column(visible=False, elem_classes=["main-card"]) as student_work_area:
                gr.Markdown("### 📝 Answer Script Mark Entry")
                st_marks_df = gr.Dataframe(
                    headers=["Part", "Question No", "Max Mark", "Earned Mark"],
                    datatype=["str", "str", "number", "number"],
                    interactive=[False, False, False, True],
                    visible=False
                )
                student_val_notice = gr.Markdown()
                
                gr.Markdown("### 📷 Upload / View Answer Paper Front Sheet")
                st_image = gr.Image(label="Answer Sheet Front Page (Photo/Image)", type="filepath")
                
                with gr.Row():
                    save_draft_btn = gr.Button("💾 Save Draft", variant="secondary")
                    lock_sub_btn = gr.Button("🔒 Submit & Lock Final", variant="stop")

    ALERT_JS = r"""(message) => {
      if (!message || typeof Swal === 'undefined') return;
      const text = String(message).replace(/<[^>]*>/g, '').trim();
      if (!text) return;
      const isError = text.includes('❌') || text.toLowerCase().includes('error') || text.toLowerCase().includes('denied') || text.toLowerCase().includes('exceeds') || text.toLowerCase().includes('warning') || text.includes('⚠️');
      Swal.fire({
        icon: isError ? 'warning' : 'success',
        title: isError ? 'Notice' : 'Success',
        text: text.replace(/^[✅🔒💾🗑️🟢⚠️]+\s*/u, ''),
        confirmButtonText: 'OK',
        confirmButtonColor: '#2563eb',
        width: 460
      });
    }"""

    for comp in [hod_login_status, reg_staff_status, hod_sub_status, staff_login_status, pat_save_status, student_status]:
        comp.change(fn=None, inputs=comp, outputs=None, js=ALERT_JS)

    goto_hod_btn.click(lambda: gr.update(selected="hod_tab"), outputs=portal_tabs)
    goto_staff_btn.click(lambda: gr.update(selected="staff_tab"), outputs=portal_tabs)
    goto_student_btn.click(lambda: gr.update(selected="student_tab"), outputs=portal_tabs)

    hod_login_btn.click(hod_login_handler, [hod_id_input, hod_pass_input], [hod_dashboard, hod_login_status, hod_assigned_staff, hod_subjects_table])
    reg_staff_btn.click(hod_register_staff, [new_staff_id, new_staff_name, new_staff_pass], [reg_staff_status, hod_assigned_staff])
    create_sub_btn.click(hod_create_subject, [hod_sub_code, hod_sub_name, hod_sub_sem, hod_sub_session, hod_sub_exam, hod_assigned_staff], [hod_sub_status, hod_subjects_table])

    staff_login_btn.click(staff_login_handler, [staff_id_input, staff_password_input], [staff_main_content, staff_subject_dropdown, staff_login_status])
    
    save_regs_btn.click(
        lambda sid, sub_id, reg_list: save_or_update_subject_staff(sid, sub_id, reg_list),
        [staff_id_input, staff_sub_id_state, s_reg_list],
        [staff_reg_status, submissions_html_view, admin_target_reg]
    )

    load_subject_btn.click(
        load_subject_details_staff,
        staff_subject_dropdown,
        [staff_sub_id_state, staff_subject_dropdown, staff_subject_dropdown, staff_subject_dropdown, staff_subject_dropdown, staff_subject_dropdown, s_reg_list, flex_pattern_df, submissions_html_view, save_pat_btn, lock_pat_btn, admin_target_reg]
    )

    save_pat_btn.click(save_pattern_staff, [staff_sub_id_state, flex_pattern_df], pat_save_status)
    lock_pat_btn.click(lock_pattern_staff, staff_sub_id_state, pat_save_status).then(
        lambda: (gr.update(interactive=False), gr.update(interactive=False)),
        outputs=[save_pat_btn, lock_pat_btn]
    )

    refresh_subs_btn.click(lambda sid: load_submissions_html(sid)[0], staff_sub_id_state, submissions_html_view)
    admin_unlock_btn.click(lambda reg, sid: handle_admin_submission_action("unlock", reg, sid), inputs=[admin_target_reg, staff_sub_id_state], outputs=[submissions_html_view, staff_reg_status, admin_target_reg])
    admin_delete_btn.click(lambda reg, sid: handle_admin_submission_action("delete", reg, sid), inputs=[admin_target_reg, staff_sub_id_state], outputs=[submissions_html_view, staff_reg_status, admin_target_reg])
    export_excel_btn.click(export_to_excel, staff_sub_id_state, excel_file_output)

    load_student_exams_btn.click(lambda reg: gr.update(choices=get_student_subject_choices(reg)), inputs=st_reg, outputs=student_subject_dropdown)
    validate_student_btn.click(validate_student_login, [student_subject_dropdown, st_reg, st_name], [st_marks_df, student_work_area, student_status, save_draft_btn, lock_sub_btn, st_image])
    st_marks_df.change(student_live_validate, inputs=st_marks_df, outputs=student_val_notice)

    save_draft_btn.click(lambda sub, reg, name, img, df: save_or_lock_student(sub, reg, name, img, df, "draft"), [student_subject_dropdown, st_reg, st_name, st_image, st_marks_df], student_status)
    lock_sub_btn.click(lambda sub, reg, name, img, df: save_or_lock_student(sub, reg, name, img, df, "lock"), [student_subject_dropdown, st_reg, st_name, st_image, st_marks_df], student_status).then(
        lambda: (gr.update(interactive=False), gr.update(interactive=False), gr.update(interactive=False)),
        outputs=[save_draft_btn, lock_sub_btn, st_image]
    )

if __name__ == "__main__":
    def find_free_port(start_port=7860):
        port = start_port
        while port < start_port + 20:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    port += 1
        return 0

    free_port = find_free_port(7860)
    app.app.mount("/uploads", StaticFiles(directory=UPLOAD_FOLDER), name="uploads")

    print(f"============================================================")
    print(f"🔒 STRICTLY LOCKED TO LOCAL SYSTEM (127.0.0.1)")
    print(f"🎓 Portal running locally at: http://127.0.0.1:{free_port}")
    print(f"============================================================")

    app.launch(css=CSS, head=SWEETALERT_HEAD, server_name="127.0.0.1", server_port=free_port, share=False)
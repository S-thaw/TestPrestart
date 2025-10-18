# app_full.py
# -*- coding: utf-8 -*-
import os, sqlite3
import secrets
from datetime import datetime
from functools import wraps
from flask import (
    Flask, render_template_string, request, redirect,
    url_for, send_file, flash, session, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()   # ← ใช้ _startPage() ไม่ใช่ showPage() ของ parent

    def save(self):
        """วนเขียนเลขหน้าทุกหน้า โดยไม่ duplicate"""
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()   # ← ตอนนี้ showPage แค่รอบสุดท้ายจริง ๆ
        super().save()

    def draw_page_number(self, page_count):
        page = self._pageNumber
        text = f"{page}/{page_count}"
        self.setFont("THSarabunNew", 12)
        self.drawRightString(200*mm, 10*mm, text)




# -------------------- App --------------------
app = Flask(__name__)
# จำกัดรวมทั้งหมดต่อ request = 100 MB
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  
# จำกัดขนาดต่อไฟล์ = 20 MB
MAX_FILE_SIZE = 20 * 1024 * 1024  
app.secret_key = "supersecretkey"

with app.app_context():
    init_db()

BASE_DIR    = os.path.join(os.path.expanduser("~"), "Yui_App_DB")
DB_NAME     = os.path.join(BASE_DIR, "records.db")
UPLOAD_DIR  = os.path.join(BASE_DIR, "uploads")
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTS = {"png","jpg","jpeg","gif","pdf","doc","docx","xls","xlsx","csv","txt"}

# -------------------- Helpers --------------------
def parse_iso_to_text(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%y/%m/%d")

def parse_thai_date_to_iso(date_str: str) -> str:
    """
    รับค่า dd/mm/yyyy จากฟอร์ม → แปลงเป็น yyyy-mm-dd (ISO)
    """
    return datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y-%m-%d")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("โปรดล็อกอินก่อน", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_EXTS

# -------------------- Database --------------------
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE, password_hash TEXT, role TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS records(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_no TEXT, name TEXT,
            date_text TEXT, date_iso TEXT,
            comments TEXT, damage TEXT,
            created_by TEXT, created_at_iso TEXT,
            file_path TEXT)""")
        conn.commit()
        if not c.execute("SELECT 1 FROM users").fetchone():
            c.execute("INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
                      ("admin", generate_password_hash("Admin@123"), "admin"))
            conn.commit()

# -------------------- CSS --------------------
THEME_CSS = """
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body { 
  background: #f2f2f7; 
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", sans-serif;
}
.card, .table { 
  border-radius: 16px; 
  box-shadow: 0 4px 10px rgba(0,0,0,.05); 
  border: none; 
}
.btn { 
  border-radius: 12px; 
  font-weight: 500; 
}
h4, h5 { 
  color: #1c1c1e; 
  font-weight: 600; 
}
.navbar-custom { 
  backdrop-filter: blur(20px);
  background: rgba(255,255,255,0.8); 
  border-radius: 16px; 
  padding: 12px 20px; 
  box-shadow: 0 2px 8px rgba(0,0,0,.1);
}
.navbar-custom a { 
  color:#007aff !important; 
  font-weight:500; 
  margin-left:12px; 
  text-decoration:none; 
}
.table thead { 
  background:#e5e5ea; 
  color:#1c1c1e; 
  font-weight:600;
}
.form-control, .form-select { 
  border-radius: 10px; 
  height:32px;        /* 👈 ลดความสูงลง */
  font-size:14px;     /* 👈 ตัวหนังสือเล็กลงนิดหน่อย */
  padding: 2px 8px;   /* 👈 บีบ padding ด้านใน */
}

.search-box {
  border-radius: 12px;
  border: 1px solid #d1d1d6;
  padding: 8px 12px;
  width: 240px;
}
.container-narrow { max-width:700px; margin:auto; }
</style>
"""


# -------------------- Upload Serving --------------------
@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

# -------------------- Auth --------------------
@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        u = request.form["username"].strip()
        p = request.form["password"]
        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            user = c.execute("SELECT id,username,password_hash,role FROM users WHERE username=?",(u,)).fetchone()
        if not user or not check_password_hash(user[2], p):
            flash("❌ Invalid credentials", "danger")
            return redirect(url_for("login"))
        session.update({"user_id":user[0], "username":user[1], "role":user[3]})
        return redirect(url_for("index"))
    return render_template_string(THEME_CSS + """
<div class="d-flex justify-content-center align-items-center vh-100">
  <div class="card shadow p-4 container-narrow">
    <h4 class="mb-3 text-center">🔐 Login</h4>
    <form method="post" class="d-flex flex-column gap-2">
      <input name="username" class="form-control" placeholder="Username / ชื่อผู้ใช้" required>
      <input name="password" type="password" class="form-control" placeholder="Password / รหัสผ่าน" required>
      <button class="btn btn-primary w-100">Login</button>
    </form>
  </div>
</div>
""")

@app.route("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))

# -------------------- Change Password --------------------
@app.route("/change_password", methods=["GET","POST"])
@login_required
def change_password():
    if request.method == "POST":
        old_pw = request.form["old_password"]
        new_pw = request.form["new_password"]
        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            user = c.execute("SELECT id,password_hash FROM users WHERE id=?",(session["user_id"],)).fetchone()
            if not user or not check_password_hash(user[1], old_pw):
                flash("❌ รหัสผ่านเดิมไม่ถูกต้อง", "danger")
                return redirect(url_for("change_password"))
            c.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_pw), user[0]))
            conn.commit()
        flash("✅ Password changed", "success")
        return redirect(url_for("index"))
    return render_template_string(THEME_CSS + """
<div class="container-narrow mt-3">
  <h4>🔑 Change Password</h4>
  <form method="post" class="card p-3 shadow-sm d-flex flex-column gap-2">
    <input type="password" name="old_password" class="form-control" placeholder="Current Password / รหัสผ่านเดิม" required>
    <input type="password" name="new_password" class="form-control" placeholder="New Password / รหัสผ่านใหม่" required>
    <button class="btn btn-primary">Update</button>
    <a href="{{url_for('index')}}" class="btn btn-secondary">Cancel</a>
  </form>
</div>
""")

# -------------------- Backup (Download DB) --------------------
@app.route("/backup_db")
@login_required
def backup_db():
    if session.get("role") != "admin":
        return "⛔ ไม่มีสิทธิ์", 403
    filename = f"records_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    return send_file(DB_NAME, as_attachment=True, download_name=filename)

# -------------------- User Management --------------------
@app.route("/users", methods=["GET","POST"])
@login_required
def users():
    if session.get("role") != "admin":
        return "⛔ ไม่มีสิทธิ์", 403
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        if request.method == "POST":
            username = request.form["username"].strip()
            password = request.form["password"]
            role     = request.form["role"]
            try:
                c.execute("INSERT INTO users(username,password_hash,role) VALUES (?,?,?)",
                          (username, generate_password_hash(password), role))
                conn.commit()
                flash("✅ เพิ่มผู้ใช้แล้ว", "success")
            except sqlite3.IntegrityError:
                flash("⚠️ ชื่อผู้ใช้นี้มีอยู่แล้ว", "danger")
        users = c.execute("SELECT id, username, role FROM users ORDER BY id DESC").fetchall()
    return render_template_string(THEME_CSS + """

<div class="container mt-3 container-narrow">
  <h4>👥 Users</h4>
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    {% for category, message in messages %}
      <div class="alert alert-{{category}} mt-2">{{message}}</div>
    {% endfor %}
  {% endif %}
{% endwith %}

  <form method="post" class="d-flex flex-column gap-2 card card-body shadow-sm mb-3">
  <input name="username" class="form-control" placeholder="Username / ชื่อผู้ใช้" required>
  <input name="password" type="password" class="form-control" placeholder="Password / รหัสผ่าน" required>
  <select name="role" class="form-select">
    <option value="user">user</option>
    <option value="admin">admin</option>
  </select>
  <button class="btn btn-primary">➕ เพิ่มผู้ใช้งาน</button>
<a href="{{url_for('index')}}" class="btn btn-secondary">🏠 กลับหน้าหลัก</a>
</form>

  <table class="table table-bordered table-hover shadow-sm align-middle">
    <thead class="table-dark"><tr><th>ID</th><th>Username</th><th>Role</th><th>Action</th></tr></thead>
    <tbody>
      {% for u in users %}
        <tr>
          <td>{{u[0]}}</td><td>{{u[1]}}</td><td>{{u[2]}}</td>
          <td>
            {% if u[1] != "admin" %}
              <a href="{{url_for('reset_password', user_id=u[0])}}" class="btn btn-sm btn-warning">Reset PW</a>
              <a href="{{url_for('delete_user', user_id=u[0])}}" onclick="return confirm('Delete user?')" class="btn btn-sm btn-danger">Delete</a>
            {% else %}<span class="text-muted">—</span>{% endif %}
          </td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
""", users=users)

# ---------- Edit Record ----------
@app.route("/edit/<int:record_id>", methods=["GET","POST"])
@login_required
def edit(record_id):
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        r = c.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
        if not r:
            return "Record not found", 404

        if request.method == "POST":
            machine_no = request.form["machine_no"].strip()
            name = request.form["name"].strip()
            date_iso = request.form["date_iso"]
            comments = request.form.get("comments","").strip()
            damage = request.form.get("damage","").strip()

            # ---------- แนบไฟล์ใหม่ ----------
            files = request.files.getlist("files")
            file_paths = r[9].split(";") if r[9] else []
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    # ✅ เช็คขนาดไฟล์
                    file.seek(0, os.SEEK_END)
                    size = file.tell()
                    file.seek(0)
                    if size > MAX_FILE_SIZE:
                        flash(f"❌ ไฟล์ {file.filename} ใหญ่เกิน 20MB", "danger")
                        return redirect(url_for("edit", record_id=record_id))

                    fname = secure_filename(file.filename)
                    save_path = os.path.join(UPLOAD_DIR, fname)
                    if os.path.exists(save_path):
                        base, ext = os.path.splitext(fname)
                        fname = f"{base}_{int(datetime.now().timestamp())}{ext}"
                        save_path = os.path.join(UPLOAD_DIR, fname)
                    file.save(save_path)
                    file_paths.append(fname)

            file_path_str = ";".join(file_paths) if file_paths else None

            date_th = request.form["date_iso"]  # ได้ dd/mm/yyyy จาก Flatpickr
            date_iso = parse_thai_date_to_iso(date_th)

            c.execute("""UPDATE records 
             SET machine_no=?, name=?, date_text=?, date_iso=?, comments=?, damage=?, file_path=?
             WHERE id=?""",
          (machine_no, name, parse_iso_to_text(date_iso), date_iso, comments, damage, file_path_str, record_id))
            conn.commit()
            flash("✅ Updated", "success")
            return redirect(url_for("index"))

    # ---------- Template Edit ----------
    # 🔹 ตรวจสอบไฟล์จริงก่อนส่งให้ template
    file_list = []
    if r[9]:
        for f in r[9].split(";"):
            path = os.path.join(UPLOAD_DIR, f)
            if os.path.exists(path):
                file_list.append(f)

    return render_template_string(THEME_CSS + """

<div class="container-narrow mt-3">
  <h4>✏️ Edit Record</h4>
  <form method="post" enctype="multipart/form-data" class="d-flex flex-column gap-2 card card-body shadow-sm">
    <input name="machine_no" class="form-control" value="{{r[1]}}" required>
    <input name="name" class="form-control" value="{{r[2]}}" required>
    <input type="text" name="date_iso" id="date_iso" class="form-control" value="{{r[4]}}" placeholder="dd/mm/yyyy" required>
    <input name="comments" class="form-control" value="{{r[5]}}">
    <input name="damage" class="form-control" value="{{r[6]}}">

    {% if file_list %}
      <label>📎 Attached Files</label><br>
      {% for f in file_list %}
        <a href="{{url_for('uploaded_file',filename=f)}}" target="_blank">{{f}}</a>
        <a href="{{url_for('delete_file', record_id=r[0], filename=f)}}"
           onclick="return confirm('ลบไฟล์นี้แน่ใจมั้ย?')"
           class="btn btn-sm btn-danger ms-2">ลบ</a><br>
      {% endfor %}
    {% endif %}

    <label class="mt-2">➕ Add More Files</label>
    <input type="file" name="files" class="form-control" multiple>

    <button class="btn btn-primary mt-2">💾 Update</button>
    <a href="{{ url_for('index') }}" class="btn btn-secondary mt-2">⬅ กลับหน้าหลัก</a>
    </form>
</div>

<!-- โหลด Flatpickr -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">
<script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>
<script>
  flatpickr("#date_iso", {
    dateFormat: "d/m/Y",
    defaultDate: "{{r[4]}}"
  });
</script>
""", r=r, file_list=file_list)


# ---------- Delete Record ----------
@app.route("/delete/<int:record_id>")
@login_required
def delete(record_id):
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        # ดึงไฟล์แนบออกมาก่อน
        rec = c.execute("SELECT file_path FROM records WHERE id=?", (record_id,)).fetchone()
        if rec and rec[0]:
            for f in rec[0].split(";"):
                path = os.path.join(UPLOAD_DIR, f)
                if os.path.exists(path):
                    os.remove(path)   # 🔹 ลบไฟล์จริงออกจากโฟลเดอร์

        # ลบ record ออกจาก DB
        c.execute("DELETE FROM records WHERE id=?", (record_id,))
        conn.commit()

    flash("🗑️ ลบข้อมูลและไฟล์เรียบร้อย", "info")
    return redirect(url_for("index"))

@app.route("/delete_file/<int:record_id>/<filename>")
@login_required
def delete_file(record_id, filename):
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        rec = c.execute("SELECT file_path FROM records WHERE id=?", (record_id,)).fetchone()
        if rec and rec[0]:
            files = rec[0].split(";")
            if filename in files:
                files.remove(filename)
                new_files = ";".join(files) if files else None
                c.execute("UPDATE records SET file_path=? WHERE id=?", (new_files, record_id))
                conn.commit()
                path = os.path.join(UPLOAD_DIR, filename)
                if os.path.exists(path):
                    os.remove(path)   # 🔹 ลบไฟล์จริงออกจากโฟลเดอร์
                flash("✅ ลบไฟล์แล้ว", "success")
    return redirect(url_for("edit", record_id=record_id))

@app.route("/delete_user/<int:user_id>")
@login_required
def delete_user(user_id):
    if session.get("role") != "admin":
        return "⛔ ไม่มีสิทธิ์", 403
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        user = c.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
        if user and user[0] == "admin":
            flash("⚠️ ห้ามลบ admin หลัก", "danger")
        else:
            c.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.commit()
            flash("🗑️ ลบผู้ใช้แล้ว", "info")
    return redirect(url_for("users"))

@app.route("/reset_password/<int:user_id>")
@login_required
def reset_password(user_id):
    if session.get("role") != "admin":
        return "⛔ ไม่มีสิทธิ์", 403
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        user = c.execute("SELECT username FROM users WHERE id=?", (user_id,)).fetchone()
        if user and user[0] == "admin":
            flash("⚠️ ห้าม reset รหัส admin หลัก", "danger")
        else:
            temp_pw = secrets.token_hex(4)   # สุ่มรหัส 8 หลัก
            c.execute("UPDATE users SET password_hash=? WHERE id=?",
                      (generate_password_hash(temp_pw), user_id))
            conn.commit()
            flash(f"🔄 Reset password for {user[0]} → {temp_pw}", "info")
    return redirect(url_for("users"))



# -------------------- Top Damaged --------------------
def get_top_damaged(search=None, start_date=None, end_date=None, damage_only=False, damage_filter=None, limit=10):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    sql = """SELECT machine_no, COUNT(*) as cnt
             FROM records
             WHERE 1=1 """
    params = []

    # filter: ค้นหาข้อความ
    if search:
        sql += " AND (machine_no LIKE ? OR name LIKE ? OR comments LIKE ? OR damage LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like, like]

    # filter: ช่วงวันที่
    if start_date:
        sql += " AND date_iso >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND date_iso <= ?"
        params.append(end_date)

    # filter: เฉพาะที่มีปัญหา
    if damage_only:
        sql += " AND damage IS NOT NULL AND damage <> ''"

    # filter: จาก top issues
    if damage_filter:
        sql += " AND damage LIKE ?"
        params.append(f"%{damage_filter}%")

    sql += " GROUP BY machine_no ORDER BY cnt DESC LIMIT ?"
    params.append(limit)

    rows = c.execute(sql, params).fetchall()
    conn.close()
    return rows



#==================================================
#                       INDEX
# =================================================

@app.route("/", methods=["GET","POST"])
@login_required
def index():
    if request.method=="POST":
        files = request.files.getlist("files")
        file_paths = []
        for file in files:
            if file and file.filename and allowed_file(file.filename):
                file.seek(0, os.SEEK_END)
                size = file.tell()
                file.seek(0)
                if size > MAX_FILE_SIZE:
                    flash(f"❌ ไฟล์ {file.filename} ใหญ่เกิน 20MB", "danger")
                    return redirect(url_for("index"))
                fname = secure_filename(file.filename)
                save_path = os.path.join(UPLOAD_DIR, fname)
                if os.path.exists(save_path):
                    base, ext = os.path.splitext(fname)
                    fname = f"{base}_{int(datetime.now().timestamp())}{ext}"
                    save_path = os.path.join(UPLOAD_DIR, fname)
                file.save(save_path)
                file_paths.append(fname)
        file_path_str = ";".join(file_paths) if file_paths else None
        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute("""INSERT INTO records(machine_no,name,date_text,date_iso,comments,damage,file_path,created_by,created_at_iso)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                    (request.form["machine_no"].strip(),
                     request.form["name"].strip(),
                     parse_iso_to_text(parse_thai_date_to_iso(request.form["date_iso"])),   # 👈 ใช้ format ไทย → ISO → text
                     parse_thai_date_to_iso(request.form["date_iso"]),                      # 👈 เก็บเป็น yyyy-mm-dd
                     request.form.get("comments","").strip(),
                     request.form.get("damage","").strip(),
                     file_path_str,
                     session["username"],
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

            conn.commit()
        flash("✅ Saved", "success")
        return redirect(url_for("index"))

    search = request.args.get("search")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    damage_only = bool(request.args.get("damage_only"))
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))   # 👈 ค่า default = 20
    date_filter = request.args.get("date_iso")
    damage_filter = request.args.get("damage_word")
    recs, total = get_records(search, start_date, end_date, damage_only, page, per_page,
                          date_filter=date_filter, damage_filter=damage_filter)

    total_pages = (total + per_page - 1) // per_page  # ปัดเศษขึ้น

    # ========== Chart: Top 10 damaged machines (ผูก filter) ==========
    top_damaged = get_top_damaged(
        search=search,
        start_date=start_date,
        end_date=end_date,
        damage_only=damage_only,
        damage_filter=damage_filter,
        limit=10
    )
    labels = [r[0] for r in top_damaged]
    counts = [r[1] for r in top_damaged]

    # ========== Dashboard Queries ==========
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # จำนวนตรวจวันนี้
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM records WHERE date_iso = ?", (today,))
    total_today = c.fetchone()[0]

    # % รถที่พบปัญหา
    c.execute("SELECT COUNT(*) FROM records WHERE damage IS NOT NULL AND damage != ''")
    total_with_damage = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM records")
    total_all = c.fetchone()[0]

    percent_damage = round((total_with_damage / total_all * 100), 1) if total_all else 0

    # Top 5 ปัญหาที่พบบ่อย
    c.execute("SELECT damage FROM records WHERE damage IS NOT NULL AND damage != ''")
    damages = [row[0] for row in c.fetchall()]
    conn.close()

    from collections import Counter
    words = []
    for d in damages:
        words.extend(d.split())
    top_issues = Counter(words).most_common(5)

    # ✅ แปลงวันที่สำหรับแสดงผล
    today_text = datetime.now().strftime("%d/%m/%Y")

    # ========== Trend (30 วันล่าสุด) พร้อม filter ==========
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    sql = "SELECT date_iso, COUNT(*) FROM records WHERE 1=1"
    params = []

    if search:
        sql += " AND (machine_no LIKE ? OR name LIKE ? OR comments LIKE ? OR damage LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like, like]

    if start_date:
        sql += " AND date_iso >= ?"
        params.append(start_date)
    else:
        sql += " AND date_iso >= date('now','-30 day')"  # default 30 วัน

    if end_date:
        sql += " AND date_iso <= ?"
        params.append(end_date)

    if damage_only:
        sql += " AND damage IS NOT NULL AND damage <> ''"

    if damage_filter:
        sql += " AND damage LIKE ?"
        params.append(f"%{damage_filter}%")

    sql += " GROUP BY date_iso ORDER BY date_iso"
    c.execute(sql, params)
    trend_data = c.fetchall()
    conn.close()

    trend_labels = [row[0] for row in trend_data]
    trend_counts = [row[1] for row in trend_data]

    
    return render_template_string(THEME_CSS + """

<!doctype html>

<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">

  <!-- Bootstrap CSS -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">

  <!-- ✅ โหลด style.css -->
  <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">

  <!-- ถ้าพี่ยังอยากเก็บ THEME_CSS inline -->
  <style>
    {{ THEME_CSS|safe }}
  </style>
</head>

<body>
<div class="navbar-custom d-flex justify-content-between align-items-center mb-3">
  <div class="d-flex align-items-center">
    <img src="{{url_for('static', filename='logo.png')}}" height="50" class="me-2">
    <b style="color:white;">Vehicle Check</b>
  </div>
  
  <div class="container-narrow mb-3">
    <h3 class="text-center">แบบตรวจยานพาหนะก่อนใช้งาน</h3>
    <h5 class="text-center text-muted">Vehicle Pre-Use Check</h5>
  </div>
  
  
<div class="d-flex flex-column align-items-end">
  <div class="d-flex align-items-center gap-2">
    <!-- บรรทัดบน: Admin + Logout -->
    <span class="ms-2 text-dark">👤 {{session['username']}} ({{session['role']}})</span>
    <a href="{{url_for('change_password')}}">Change Password</a>
    {% if session['role'] == 'admin' %}
    <div class="dropdown position-static">
      <a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown" aria-expanded="false">
        ⚙️ Admin
      </a>
      <ul class="dropdown-menu dropdown-menu-end">
        <li><a class="dropdown-item" href="{{url_for('users')}}">👥 Users</a></li>
        <li><a class="dropdown-item" href="{{url_for('backup_db')}}">📦 Backup DB</a></li>
        <li><a class="dropdown-item" href="{{url_for('restore_db')}}">♻️ Restore DB</a></li>
      </ul>
    </div>
    {% endif %}
    <a href="{{url_for('logout')}}">Logout</a>
  </div>

    <!-- Unified search & controls (basic + advanced) -->
    
  <form method="get" class="flex-grow-1">
    <div class="row g-2 align-items-center">
      <!-- Basic search -->
      <div class="col-auto">
        <input type="text" class="form-control form-control-sm"
               name="search" placeholder="ค้นหา..."
               value="{{ request.args.get('search','') }}">
      </div>

      <!-- Per page -->
      <div class="col-auto">
        <label for="per_page" class="me-2 small mb-0">แสดงต่อหน้า</label>
        <select name="per_page" id="per_page" class="form-select form-select-sm d-inline w-auto">
          <option value="10" {% if request.args.get('per_page','20') == '10' %}selected{% endif %}>10</option>
          <option value="20" {% if request.args.get('per_page','20') == '20' %}selected{% endif %}>20</option>
          <option value="50" {% if request.args.get('per_page','20') == '50' %}selected{% endif %}>50</option>
        </select>
      </div>

      <!-- Sort by -->
      <div class="col-auto">
        <label for="sort_by" class="me-2 small mb-0"></label>
        <select name="sort_by" id="sort_by" class="form-select form-select-sm d-inline w-auto">
          <option value="created" {% if sort_by=='created' %}selected{% endif %}>ล่าสุด</option>
          <option value="date" {% if sort_by=='date' %}selected{% endif %}>วันที่ตรวจ</option>
          <option value="machine" {% if sort_by=='machine' %}selected{% endif %}>หมายเลขรถ</option>
        </select>
      </div>

      <!-- Actions -->
      <div class="col-auto">
        <button type="submit" class="btn btn-primary btn-sm">Search</button>
        <a href="{{ url_for('index') }}" class="btn btn-secondary btn-sm">Clear</a>
      </div>

      

      <!-- Advanced content (moved up) -->
      <div class="col-12">
        <!-- ปุ่ม Advanced -->
<button class="btn btn-outline-secondary btn-sm" type="button"
        data-bs-toggle="offcanvas" data-bs-target="#advFilters"
        aria-controls="advFilters">
  ⚙️ Advanced
</button>

<!-- Advanced Filters Offcanvas -->
<div class="offcanvas offcanvas-end" tabindex="-1" id="advFilters">
  <div class="offcanvas-header py-2">
    <h6 class="offcanvas-title">🔍 Advanced Filters</h6>
    <button type="button" class="btn-close" data-bs-dismiss="offcanvas"></button>
  </div>
  <div class="offcanvas-body p-2">
    <div class="mb-2">
      <input type="text" name="start_date" id="start_date"
             class="form-control form-control-sm"
             placeholder="ตั้งแต่วันที่"
             value="{{ request.args.get('start_date','') }}">
    </div>
    <div class="mb-2">
      <input type="text" name="end_date" id="end_date"
             class="form-control form-control-sm"
             placeholder="ถึงวันที่"
             value="{{ request.args.get('end_date','') }}">
    </div>
    <div class="form-check small">
      <input class="form-check-input" type="checkbox" name="damage_only" value="1"
             id="damageOnly" {% if request.args.get('damage_only') %}checked{% endif %}>
      <label class="form-check-label" for="damageOnly">
        เฉพาะที่เสียหาย
      </label>
    </div>
    <div class="d-flex justify-content-end gap-2 mt-2">
      <button type="submit" class="btn btn-primary btn-sm">Apply</button>
      <button type="button" class="btn btn-light btn-sm" data-bs-dismiss="offcanvas">Close</button>
    </div>
  </div>
</div>

                <!-- Dropdown ช่วงวันที่ (แทน Quick buttons เดิม) -->
<div class="col-12">
  <div class="dropdown">
    <button id="rangeDropdownBtn" class="btn btn-outline-secondary btn-sm dropdown-toggle" type="button" data-bs-toggle="dropdown">
      วันที่ (ช่วงด่วน)
    </button>
    <ul class="dropdown-menu">
      <li class="dropdown-header">ช่วงมาตรฐาน</li>
      <li><a class="dropdown-item" href="#" data-range="today">วันนี้</a></li>
      <li><a class="dropdown-item" href="#" data-range="yesterday">เมื่อวาน</a></li>
      <li><a class="dropdown-item" href="#" data-range="this_month">เดือนนี้</a></li>

      <li><hr class="dropdown-divider"></li>

      <li class="dropdown-header">ช่วงล่าสุด</li>
      <li><a class="dropdown-item" href="#" data-range="last_7">7 วันล่าสุด</a></li>
      <li><a class="dropdown-item" href="#" data-range="last_14">14 วันล่าสุด</a></li>
      <li><a class="dropdown-item" href="#" data-range="last_28">28 วันล่าสุด</a></li>
      <li><a class="dropdown-item" href="#" data-range="last_30">30 วันล่าสุด</a></li>

      <li><hr class="dropdown-divider"></li>

      <li class="dropdown-header">สัปดาห์/เดือน/ไตรมาส/ปี</li>
      <li class="dropend">
        <a class="dropdown-item dropdown-toggle" href="#" data-bs-toggle="dropdown">สัปดาห์ที่แล้ว</a>
        <ul class="dropdown-menu">
          <li><a class="dropdown-item" href="#" data-range="last_week_mon">เริ่มต้นวันจันทร์</a></li>
          <li><a class="dropdown-item" href="#" data-range="last_week_sun">เริ่มต้นวันอาทิตย์</a></li>
        </ul>
      </li>
      <li><a class="dropdown-item" href="#" data-range="last_month">เดือนที่แล้ว</a></li>
      <li><a class="dropdown-item" href="#" data-range="last_quarter">ไตรมาสที่แล้ว</a></li>
      <li><a class="dropdown-item" href="#" data-range="last_year">ปีที่แล้ว</a></li>
    </ul>
  </div>

  <!-- สรุปตัวกรอง -->
  <div class="mt-1 small d-flex flex-wrap gap-1">
    {% if request.args.get('start_date') %}
      <span class="badge text-bg-light border">เริ่ม: {{ request.args.get('start_date') }}</span>
    {% endif %}
    {% if request.args.get('end_date') %}
      <span class="badge text-bg-light border">สิ้นสุด: {{ request.args.get('end_date') }}</span>
    {% endif %}
    {% if request.args.get('search') %}
      <span class="badge text-bg-light border">ค้นหา: {{ request.args.get('search') }}</span>
    {% endif %}
    {% if request.args.get('damage_only') %}
      <span class="badge text-bg-light border">เฉพาะที่เสียหาย</span>
    {% endif %}
  </div>
</div>
              </div>
            </div>
          </div>
        </div>
      </div>

    </div>
  </form>
</div>
</div>

<!-- Alert สรุปจำนวน record -->
<div class="d-flex justify-content-center mt-3">
  <div class="alert shadow-sm border-0 rounded-pill py-2 px-4 d-flex align-items-center"
       style="background: linear-gradient(90deg, #0d6efd 0%, #0dcaf0 100%); color: #fff; font-size: 1.1rem; font-weight: 600;">
    <i class="bi bi-search me-2"></i>
    พบข้อมูลทั้งหมด <span class="mx-1">{{ total }}</span> รายการ
  </div>
</div>

<!-- บรรทัดล่าง: Export -->
  <div class="d-flex justify-content-between align-items-center mt-2 flex-wrap gap-2">
  <!-- Export buttons (top only) -->
  <div class="btn-group">
    <a href="{{ url_for('export_excel', search=request.args.get('search'),
                                      start_date=request.args.get('start_date'),
                                      end_date=request.args.get('end_date'),
                                      damage_only=request.args.get('damage_only'),
                                      per_page=request.args.get('per_page','20'),
                                      sort_by=request.args.get('sort_by','created')) }}"
       class="btn btn-success btn-sm">📊 Excel</a>
    <a href="{{ url_for('export_csv', search=request.args.get('search'),
                                    start_date=request.args.get('start_date'),
                                    end_date=request.args.get('end_date'),
                                    damage_only=request.args.get('damage_only'),
                                    per_page=request.args.get('per_page','20'),
                                    sort_by=request.args.get('sort_by','created')) }}"
       class="btn btn-info btn-sm">📄 CSV</a>
    <a href="{{ url_for('export_pdf', search=request.args.get('search'),
                                    start_date=request.args.get('start_date'),
                                    end_date=request.args.get('end_date'),
                                    damage_only=request.args.get('damage_only'),
                                    per_page=request.args.get('per_page','20'),
                                    sort_by=request.args.get('sort_by','created')) }}"
       class="btn btn-danger btn-sm">📑 PDF</a>
  </div>


</div>

<!-- ฟอร์มกรอกข้อมูล --> 
<div class="row equal-height">
  <!-- Chart -->
  <div class="col-md-7 mb-3">
    <div class="card shadow-sm">
      <div class="card-body d-flex flex-column">
        <div class="d-flex justify-content-between align-items-center mb-2">
          <h5 class="card-title">📊 Top 10 รถที่มีปัญหามากที่สุด</h5>
          <button id="toggleChart" type="button" class="btn btn-sm btn-outline-primary">สลับกราฟ</button>
        </div>
        <div class="chart-container">
          <canvas id="damageChart"></canvas>
        </div>
      </div>
    </div>
  </div>

  

    <!-- 🔹 ฟอร์มกรอกข้อมูลด้านขวา -->
    <div class="col-md-5">
    <div class="card shadow-sm h-100">
      <div class="card-body" style="padding:10px;">
          <h5 class="card-title text-center mb-3">📝 เพิ่มรายการตรวจสอบ</h5>
          <form method="POST" enctype="multipart/form-data" class="row g-3">

        <!-- หมายเลขรถ -->
        <div class="col-12 col-md-4">
          <div class="input-group form-floating">
            <span class="input-group-text">
              <!-- Truck Mining Icon -->
              <svg xmlns="http://www.w3.org/2000/svg" 
                   width="28" height="28" viewBox="0 0 24 24" 
                   fill="none" stroke="gray" stroke-width="2" 
                   stroke-linecap="round" stroke-linejoin="round">
                <rect x="1" y="7" width="15" height="10" rx="2" ry="2"></rect>
                <path d="M16 10h4l3 4v3a2 2 0 0 1-2 2h-2"></path>
                <circle cx="5.5" cy="17.5" r="2.5"></circle>
                <circle cx="18.5" cy="17.5" r="2.5"></circle>
              </svg>
            </span>
            <input type="text" name="machine_no" class="form-control form-control-sm" id="machine_no"
                   placeholder="Machine No." required>
            <label for="machine_no">Machine No. / หมายเลขรถ</label>
          </div>
        </div>

        <!-- ผู้ตรวจสอบ -->
        <div class="col-12 col-md-4">
          <div class="input-group form-floating">
            <span class="input-group-text text-secondary">👤</span>
            <input type="text" name="name" class="form-control form-control-sm" id="name"
                   placeholder="Name" required>
            <label for="name">Name / ผู้ตรวจสอบ</label>
          </div>
        </div>

        <!-- วันที่ -->
        <div class="col-12 col-md-4">
          <div class="input-group form-floating">
            <span class="input-group-text text-success">📅</span>
            <input type="text" name="date_iso" id="date_iso" class="form-control form-control-sm"
                   placeholder="dd/mm/yyyy" required>
            <label for="date_iso">Date / วันที่</label>
          </div>
        </div>

        <!-- Comments -->
        <div class="col-12 col-md-4">
          <div class="input-group form-floating">
            <span class="input-group-text text-info">💬</span>
            <input type="text" name="comments" class="form-control form-control-sm" id="comments"
                   placeholder="Comments">
            <label for="comments">Comments / ความคิดเห็น</label>
          </div>
        </div>

        
        <!-- Damage -->
        <div class="col-12 col-md-4 d-flex align-items-center">
          <div class="input-group form-floating">
            <span class="input-group-text text-danger" style="font-size:1.8em;">⚠️</span>
            <textarea name="damage" class="form-control form-control-sm" id="damage"
                   placeholder="List Damage"></textarea>
            <label for="damage">List Damage / รายการความเสียหาย</label>
          </div>
        </div>

        <!-- แนบไฟล์ -->
        <div class="col-12">
          <div class="d-grid">
            <label for="files" class="btn btn-warning btn-sm w-100">
              📎 แนบไฟล์
            </label>
            <input type="file" name="files" id="files" multiple class="d-none">
          </div>
        </div>

        <!-- ปุ่ม -->
        <div class="col-12 d-flex gap-2">
          <button type="submit" class="btn btn-primary flex-fill">💾 บันทึก</button>
          <button type="reset" class="btn btn-secondary flex-fill">🧹 ล้างค่า</button>
        </div>


      </form>
    </div>
  </div>
</div>

<!-- โหลด Bootstrap Icons ก่อน (ใส่ใน <head>) -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">




  <!-- 🔹 Dashboard -->
  <div class="row mb-3 justify-content-center">
    <div class="col-md-4">
      <div class="card dashboard-card">
        <h6>จำนวนตรวจวันนี้</h6>
        <h3>{{ total_today }}</h3>
        <small class="text-muted">วันที่ {{ today_text }}</small>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card dashboard-card">
        <h6>% รถที่พบปัญหา</h6>
        <h3>{{ percent_damage }}%</h3>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card dashboard-card">
        <h6>Top 5 ปัญหาที่พบบ่อย</h6>
          <ul class="list-unstyled mb-0">
           {% for issue,count in top_issues %}
            <li>
              <a href="?damage_word={{ issue }}" class="text-decoration-none">
                {{ issue }} ({{ count }})
              </a>
            </li>
            {% endfor %}
          </ul>
        </div>
    </div>
  </div>

  <!-- 🔹 Trend 30 วัน -->
  <div class="row mb-3">
    <div class="col-md-12">
      <div class="card dashboard-card">
        <h6>Trend ปัญหา 30 วันล่าสุด</h6>
        <canvas id="trendChart" height="100"></canvas>
      </div>
    </div>
  </div>



<!-- Advanced Filters moved to header toolbar -->
  </div>
</div>


<!-- Script Toggle -->
<script>
  const toggleBtn = document.getElementById('toggleAdvanced');
  const advancedFields = document.getElementById('advancedFields');

  advancedFields.addEventListener('shown.bs.collapse', () => {
    toggleBtn.innerHTML = '➖ Hide Filters';
  });
  advancedFields.addEventListener('hidden.bs.collapse', () => {
    toggleBtn.innerHTML = '➕ Show Filters';
  });
</script>

<script>
document.addEventListener("DOMContentLoaded", function() {
  const sortDropdowns = document.querySelectorAll("select[name='sort_by']");
  sortDropdowns.forEach(function(dd) {
    dd.addEventListener("change", function() {
      if (this.form) {
        // ถ้ามี form → submit ปกติ
        this.form.submit();
      } else {
        // ถ้าอยู่นอก form → redirect ไปพร้อม query string
        const url = new URL(window.location.href);
        url.searchParams.set("sort_by", this.value);
        window.location.href = url.toString();
      }
    });
  });
});
</script>

       

  <!-- Sort by -->
      <div class="col-auto">
        <label for="sort_by" class="me-2 small mb-0">เรียง</label>
        <select name="sort_by" id="sort_by" class="form-select form-select-sm d-inline w-auto">
          <option value="created" {% if sort_by=='created' %}selected{% endif %}>ล่าสุด</option>
          <option value="date" {% if sort_by=='date' %}selected{% endif %}>วันที่ตรวจ</option>
          <option value="machine" {% if sort_by=='machine' %}selected{% endif %}>หมายเลขรถ</option>
        </select>
      </div>

      
  
</form>

      </form>

      <!-- duplicate export removed: now only at header -->

    </div>
  </div>
</div>

<!-- JS Toggle -->
<script>
function toggleAdvanced() {
  const adv = document.getElementById('advancedFields');
  const btn = document.getElementById('toggleBtn');
  const isOpen = adv.classList.toggle('show');  // แค่สลับ show
  btn.textContent = isOpen ? 'Basic ▲' : 'Advanced ▼';
  if (isHidden) {
    adv.classList.remove("d-none");
    adv.classList.add("show");
    btn.textContent = "Basic ▲";
  } else {
    adv.classList.remove("show");
    setTimeout(() => adv.classList.add("d-none"), 300); // รอ animation จบค่อยซ่อน
    btn.textContent = "Advanced ▼";
  }
}
</script>

<table class="table table-bordered table-hover shadow-sm align-middle">
  <thead class="table-dark text-center">
    <tr><th>Machine No.</th><th>Name</th><th>Date</th><th>Comments</th>
    <th>List Damage</th><th>File</th><th>Created By</th><th>Created At</th><th>Action</th></tr>
  </thead>
  <tbody>
    {% for r in recs %}
    <tr>
      <td>{{r[1]}}</td><td>{{r[2]}}</td><td>{{r[3]}}</td><td>{{ r[5] or "—" }}</td><td>{{r[6] or "-"}}</td>
      <td class="text-center">
  {% if r[9] %}
    {% set files = r[9].split(';') %}
    <a href="#" data-bs-toggle="modal" data-bs-target="#filesModal{{r[0]}}">
      📎 {{ files|length }}
    </a>

    <!-- Modal -->
    <div class="modal fade" id="filesModal{{r[0]}}" tabindex="-1" aria-hidden="true">
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">📎 Files for Record #{{r[0]}}</h5>
            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
          </div>
          <div class="modal-body">
            <ul class="list-group">
              {% for f in files %}
              <li class="list-group-item">
                <a href="{{ url_for('uploaded_file', filename=f) }}" target="_blank">{{ f }}</a>
              </li>
              {% endfor %}
            </ul>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">ปิด</button>
          </div>
        </div>
      </div>
    </div>
  {% endif %}
</td>

      <td>{{r[7]}}</td><td>{{r[8]}}</td>
      <td>
          {% if session['role'] == 'admin' %}
            <a href="{{url_for('edit',record_id=r[0])}}" class="btn btn-sm btn-warning">Edit</a>
            <a href="{{url_for('delete',record_id=r[0])}}" onclick="return confirm('Delete?')" class="btn btn-sm btn-danger">Delete</a>
          {% else %}
            <span class="text-muted">View Only</span>
          {% endif %}
    </td>

    </tr>
    {% endfor %}
  </tbody>
</table>

<!-- ✅ Pagination -->
<nav>
  <ul class="pagination justify-content-center">
    <!-- Previous -->
    <li class="page-item {% if page <= 1 %}disabled{% endif %}">
      <a class="page-link"
         href="{{ url_for('index',
               page=page-1,
               per_page=request.args.get('per_page','20'),
               search=request.args.get('search'),
               start_date=request.args.get('start_date'),
               end_date=request.args.get('end_date'),
               damage_only=request.args.get('damage_only')) }}">
         Previous
      </a>
    </li>

    <!-- Numbered pages -->
    {% for p in range(1, total_pages+1) %}
      <li class="page-item {% if p == page %}active{% endif %}">
        <a class="page-link"
           href="{{ url_for('index',
                 page=p,
                 per_page=request.args.get('per_page','20'),
                 search=request.args.get('search'),
                 start_date=request.args.get('start_date'),
                 end_date=request.args.get('end_date'),
                 damage_only=request.args.get('damage_only')) }}">
           {{p}}
        </a>
      </li>
    {% endfor %}

    <!-- Next -->
    <li class="page-item {% if page >= total_pages %}disabled{% endif %}">
      <a class="page-link"
         href="{{ url_for('index',
               page=page+1,
               per_page=request.args.get('per_page','20'),
               search=request.args.get('search'),
               start_date=request.args.get('start_date'),
               end_date=request.args.get('end_date'),
               damage_only=request.args.get('damage_only')) }}">
         Next
      </a>
    </li>
  </ul>
</nav>

<!-- โหลด Flatpickr -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css">
<script src="https://cdn.jsdelivr.net/npm/flatpickr"></script>
<script>
  flatpickr("#date_iso", {
    dateFormat: "d/m/Y",   // แสดง dd/mm/yyyy
    defaultDate: new Date()
  });
</script>

<!-- โหลด Chart.js -->
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<!-- โหลด Plugin datalabels -->
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels"></script>

<script>
  const ctx = document.getElementById('damageChart').getContext('2d');
  let currentType = 'bar';

  // ✅ Data
  const chartData = {
    labels: {{ labels|tojson }},
    datasets: [{
      label: 'จำนวนปัญหา',
      data: {{ counts|tojson }},
      backgroundColor: [
        '#dc3545', '#fd7e14', '#ffc107', '#198754', '#0d6efd',
        '#6610f2', '#6f42c1', '#20c997', '#0dcaf0', '#adb5bd'
      ]
    }]
  };

  // ✅ Options
  const makeOptions = (type) => {
    return {
      responsive: true,
      maintainAspectRatio: false,
      layout: {
        padding: { top: type === 'bar' ? 30 : 10 }   // bar เว้นบนเยอะกว่า pie
      },
      plugins: {
        legend: { display: true, position: type === 'pie' ? 'right' : 'top' },
        datalabels: {
          anchor: type === 'bar' ? 'end' : 'center',
          align: type === 'bar' ? 'end' : 'center',
          offset: type === 'bar' ? -4 : 0,
          color: type === 'bar' ? '#000' : '#fff',
          font: { weight: 'bold' },
          formatter: (value, ctx) => {
            const sum = ctx.chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
            const percentage = ((value / sum) * 100).toFixed(1);
            return type === 'bar'
              ? `${value} (${percentage}%)`   // ✅ Bar = จำนวน + %
              : `${value} (${percentage}%)`; // ✅ Pie = จำนวน + %
          }
        }
        ,
        tooltip: {
          callbacks: {
            label: function(context) {
              const value = context.raw;
              const sum = context.chart.data.datasets[0].data.reduce((a, b) => a + b, 0);
              const percentage = ((value / sum) * 100).toFixed(1);
              return `จำนวน: ${value} | ${percentage}%`;
            }
          }
        }
      },
      scales: type === 'bar' ? {
        x: { title: { display: true, text: 'หมายเลขรถ' }},
        y: { title: { display: true, text: 'จำนวนปัญหา' }, beginAtZero: true }
      } : {}
    };
  };

  // ✅ Initial chart
  let myChart = new Chart(ctx, {
    type: currentType,
    data: chartData,
    options: makeOptions(currentType),
    plugins: [ChartDataLabels]
  });

  // ✅ ปุ่ม toggle bar/pie
  document.getElementById('toggleChart').addEventListener('click', function() {
    myChart.destroy();
    currentType = (currentType === 'bar') ? 'pie' : 'bar';
    myChart = new Chart(ctx, {
      type: currentType,
      data: chartData,
      options: makeOptions(currentType),
      plugins: [ChartDataLabels]
    });
  });
</script>

<!-- Bootstrap JS + Popper -->
<script src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.11.8/dist/umd/popper.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.min.js"></script>

<!-- ✅ Auto-expand textarea -->
<script>
  const damageBox = document.getElementById("damage");
  if (damageBox) {
    damageBox.addEventListener("input", function() {
      this.style.height = "auto";
      this.style.height = this.scrollHeight + "px"; // ยืดอัตโนมัติ
    });
  }
</script>
 
<script>
const trendCtx = document.getElementById("trendChart").getContext("2d");
const trendChart = new Chart(trendCtx, {
  type: "line",
  data: {
    labels: {{ trend_labels|tojson }},
    datasets: [{
      label: "จำนวนปัญหา",
      data: {{ trend_counts|tojson }},
      borderColor: "#0d6efd",
      backgroundColor: "rgba(13,110,253,0.2)",
      tension: 0.3,
      fill: true,
      pointBackgroundColor: "#0d6efd",
      pointRadius: 8,
      pointHoverRadius: 12,
      hitRadius: 20
    }]
  },
  options: {
    responsive: true,
    plugins: {
      legend: { display: false },
      tooltip: { mode: "index", intersect: false }
    },
    interaction: { mode: 'nearest', axis: 'x', intersect: false },
    scales: {
      x: { title: { display: true, text: "วันที่" }},
      y: { title: { display: true, text: "จำนวนปัญหา" }, beginAtZero: true }
    }
  }
});

// ✅ Event เมื่อคลิกจุดในกราฟ
document.getElementById("trendChart").onclick = function(evt) {
  const points = trendChart.getElementsAtEventForMode(evt, 'nearest', { intersect: true }, true);
  if (points.length > 0) {
    const firstPoint = points[0];
    const label = trendChart.data.labels[firstPoint.index];
    window.location.href = `?date_iso=${label}`;
  }
};
</script>



<script>
(function(){
  // ----- Helpers -----
  const toISO = d => new Date(d.getTime() - d.getTimezoneOffset()*60000).toISOString().split('T')[0];

  function startOfWeek(date, weekStart='mon'){
    const d = new Date(date); d.setHours(0,0,0,0);
    const day = d.getDay(); // 0=Sun..6=Sat
    let diff;
    if (weekStart === 'mon') diff = (day === 0 ? -6 : 1) - day; // Monday
    else diff = 0 - day; // Sunday
    d.setDate(d.getDate() + diff);
    return d;
  }
  const startOfMonth = (date)=> new Date(date.getFullYear(), date.getMonth(), 1);
  const endOfMonth   = (date)=> new Date(date.getFullYear(), date.getMonth()+1, 0);
  function startOfQuarter(date){
    const m = date.getMonth();
    const qStartMonth = m - (m % 3);
    return new Date(date.getFullYear(), qStartMonth, 1);
  }
  function endOfQuarter(date){
    const s = startOfQuarter(date);
    return new Date(s.getFullYear(), s.getMonth()+3, 0);
  }
  const startOfYear = (date)=> new Date(date.getFullYear(), 0, 1);
  const endOfYear   = (date)=> new Date(date.getFullYear(), 11, 31);

  function lastNDays(n){
    const today = new Date(); today.setHours(0,0,0,0);
    const start = new Date(today); start.setDate(today.getDate() - (n-1));
    return {start, end: today};
  }

  // ----- Core mapping -----
  function getRange(key){
    const today = new Date(); today.setHours(0,0,0,0);
    const y = new Date(today); y.setDate(today.getDate()-1);

    if (key === 'today')        return { start: today, end: today };
    if (key === 'yesterday')    return { start: y,     end: y };
    if (key === 'this_month')   return { start: startOfMonth(today), end: endOfMonth(today) };

    if (key === 'last_7')       return lastNDays(7);
    if (key === 'last_14')      return lastNDays(14);
    if (key === 'last_28')      return lastNDays(28);
    if (key === 'last_30')      return lastNDays(30);

    if (key === 'last_week_mon'){
      const thisMon = startOfWeek(today,'mon');
      const lastMon = new Date(thisMon); lastMon.setDate(thisMon.getDate()-7);
      const lastSun = new Date(lastMon); lastSun.setDate(lastMon.getDate()+6);
      return { start: lastMon, end: lastSun };
    }
    if (key === 'last_week_sun'){
      const thisSun = startOfWeek(today,'sun');
      const lastSun = new Date(thisSun); lastSun.setDate(thisSun.getDate()-7);
      const lastSat = new Date(lastSun); lastSat.setDate(lastSun.getDate()+6);
      return { start: lastSun, end: lastSat };
    }

    if (key === 'last_month'){
      const firstThis = startOfMonth(today);
      const lastPrev  = new Date(firstThis); lastPrev.setDate(0);
      const firstPrev = startOfMonth(lastPrev);
      return { start: firstPrev, end: lastPrev };
    }

    if (key === 'last_quarter'){
      const thisQStart = startOfQuarter(today);
      const prevQDay = new Date(thisQStart); prevQDay.setDate(thisQStart.getDate()-1);
      return { start: startOfQuarter(prevQDay), end: endOfQuarter(prevQDay) };
    }

    if (key === 'last_year'){
      const prevYearDate = new Date(today.getFullYear()-1, today.getMonth(), today.getDate());
      return { start: startOfYear(prevYearDate), end: endOfYear(prevYearDate) };
    }

    // fallback
    return lastNDays(30);
  }

  function applyRange(key){
    const {start, end} = getRange(key);
    const url = new URL(window.location.href);
    url.searchParams.set('start_date', toISO(start));
    url.searchParams.set('end_date',   toISO(end));
    url.searchParams.delete('page'); // reset pagination
    window.location.href = url.toString();
  }

  // ----- Bind click events -----
  document.querySelectorAll('[data-range]').forEach(el=>{
    el.addEventListener('click', (e)=>{
      e.preventDefault();
      applyRange(el.getAttribute('data-range'));
    });
  });

  // ----- Decorate button label & active item (best-effort) -----
  const url = new URL(window.location.href);
  const s = url.searchParams.get('start_date');
  const e = url.searchParams.get('end_date');
  const btn = document.getElementById('rangeDropdownBtn');

  function formatRangeLabel(s, e){
    if (!s || !e) return 'วันที่ (ช่วงด่วน)';
    if (s === e) return `วันที่: ${s}`;
    return `${s} → ${e}`;
  }
  if (btn) btn.textContent = formatRangeLabel(s, e);

  function markActive(){
    const items = document.querySelectorAll('.dropdown-menu [data-range]');
    items.forEach(i => i.classList.remove('active'));
    if (!s || !e) return;

    // เทียบกับ key ยอดฮิต
    const today = new Date(); today.setHours(0,0,0,0);
    const iso = d => toISO(d);

    function lastNDaysISO(n){
      const start = new Date(today); start.setDate(today.getDate()-(n-1));
      return {S: iso(start), E: iso(today)};
    }
    const candidates = [
      ['today',       {S: iso(today), E: iso(today)}],
      ['yesterday',   (()=>{const y=new Date(today); y.setDate(today.getDate()-1); return {S: iso(y), E: iso(y)};})()],
      ['this_month',  {S: `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-01`, 
                       E: iso(new Date(today.getFullYear(), today.getMonth()+1, 0))}],
      ['last_7',      lastNDaysISO(7)],
      ['last_14',     lastNDaysISO(14)],
      ['last_28',     lastNDaysISO(28)],
      ['last_30',     lastNDaysISO(30)],
    ];
    for (const [key, rng] of candidates){
      if (rng.S === s && rng.E === e){
        const el = document.querySelector(`[data-range="${key}"]`);
        if (el) el.classList.add('active');
        break;
      }
    }
  }
  markActive();
})();
</script>




</body>


</html>


</div>
""",recs=recs,
    total=total,                          
    page=page,
    total_pages=total_pages,
    labels=labels,
    counts=counts,
    total_today=total_today,
    percent_damage=percent_damage,
    top_issues=top_issues,
    today_text=today_text,   # ✅ ใช้ตัวนี้
    trend_labels=trend_labels,
    trend_counts=trend_counts                               
                              
)

# -------------------- search --------------------
def get_records(search=None, start_date=None, end_date=None,
                damage_only=False, page=1, per_page=20,
                date_filter=None, damage_filter=None):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    sql = "SELECT * FROM records WHERE 1=1"
    params = []

    # ค้นหาด้วยข้อความ
    if search:
        sql += " AND (machine_no LIKE ? OR name LIKE ? OR comments LIKE ? OR damage LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like, like]

    # ช่วงวันที่
    if start_date:
        sql += " AND date_iso >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND date_iso <= ?"
        params.append(end_date)

    # เฉพาะที่มีปัญหา
    if damage_only:
        sql += " AND damage IS NOT NULL AND damage != ''"

    # ✅ filter จาก Trend Chart
    if date_filter:
        sql += " AND date_iso = ?"
        params.append(date_filter)

    # ✅ filter จาก Top 5 ปัญหา
    if damage_filter:
        sql += " AND damage LIKE ?"
        params.append(f"%{damage_filter}%")

    # นับทั้งหมด
    c.execute(sql, params)
    total = len(c.fetchall())

    sort_by = request.args.get("sort_by", "created")

    # ✅ Order by ก่อน
    if sort_by == "created":
        sql += " ORDER BY created_at_iso DESC"
    elif sort_by == "date":
        sql += " ORDER BY date_iso DESC"
    elif sort_by == "machine":
        sql += " ORDER BY machine_no ASC"
    else:
        sql += " ORDER BY created_at_iso DESC"  # fallback

    # ✅ Limit/Offset ตาม pagination
    sql += " LIMIT ? OFFSET ?"
    params += [per_page, (page - 1) * per_page]

    c.execute(sql, params)
    recs = c.fetchall()
    conn.close()
    return recs, total




# -------------------- Export --------------------
# =========================
# Export Excel
# =========================

@app.route("/export/excel")
@login_required
def export_excel():
    # ดึงค่า filter จาก query string
    search = request.args.get("search")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    damage_only = bool(request.args.get("damage_only"))
    
    # ถ้ามี filter ใช้ filter นั้น → ถ้าไม่มีเลย ให้ดึงทั้งหมด
    recs, _ = get_records(search, start_date, end_date, damage_only, 1, 99999)

    df = pd.DataFrame(recs, columns=[
        "ID","รถ","ผู้ตรวจ","วันที่","Date ISO","หมายเหตุ","ชำรุด","ผู้บันทึก","เวลา","ไฟล์"
    ])
    df = df.drop(columns=["Date ISO","ไฟล์"])
    fp = os.path.join(BASE_DIR,"records.xlsx")
    df.to_excel(fp, index=False)
    return send_file(fp, as_attachment=True)


# =========================
# Export CSV
# =========================
@app.route("/export/csv")
@login_required
def export_csv():
    search = request.args.get("search")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    damage_only = bool(request.args.get("damage_only"))

    recs, _ = get_records(search, start_date, end_date, damage_only, 1, 99999)

    df = pd.DataFrame(recs, columns=[
        "ID","รถ","ผู้ตรวจ","วันที่","Date ISO","หมายเหตุ","ชำรุด","ผู้บันทึก","เวลา","ไฟล์"
    ])
    df = df.drop(columns=["ไฟล์","Date ISO"])
    fp = os.path.join(BASE_DIR,"records.csv")
    df.to_csv(fp, index=False, encoding="utf-8-sig")
    return send_file(fp, as_attachment=True)

# =========================
# Export PDF
# =========================
@app.route("/export/pdf")
@login_required
def export_pdf():
    search = request.args.get("search")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    damage_only = bool(request.args.get("damage_only"))

    recs, _ = get_records(search, start_date, end_date, damage_only, 1, 99999)

    fp = os.path.join(BASE_DIR,"records.pdf")

     # ฟอนต์ไทย
    font_path = os.path.join("static","fonts","THSarabunNew.ttf")
    pdfmetrics.registerFont(TTFont("THSarabunNew", font_path))

    doc = SimpleDocTemplate(fp, pagesize=A4,
                            rightMargin=30,leftMargin=30,
                            topMargin=40,bottomMargin=30)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='ThaiNormal', fontName='THSarabunNew', fontSize=12, leading=14))
    styles.add(ParagraphStyle(name='ThaiHeader', fontName='THSarabunNew', fontSize=16, alignment=1, spaceAfter=10))

    elements = []

    # ✅ ดึงชื่อ user ที่ login อยู่
    user = session.get("username", "Unknown")

    # โลโก้บริษัท
    from reportlab.platypus import Image
    logo_path = os.path.join("static","logo.png")
    if os.path.exists(logo_path):
        elements.append(Image(logo_path, width=250, height=60))
    elements.append(Paragraph("<b>แบบตรวจยานพาหนะก่อนใช้งาน</b>", styles['ThaiHeader']))
    elements.append(Paragraph("Vehicle Pre-Use Check", styles['ThaiHeader']))
    elements.append(Paragraph("โลตัสฮอลวิศวกรรมเหมืองแร่และก่อสร้าง จำกัด", styles['ThaiNormal']))
    elements.append(Paragraph("LotusHall Mining : Heavy Engineering Construction Co., Ltd.", styles['ThaiNormal']))
    elements.append(Paragraph(
    "วันที่พิมพ์รายงาน : " + datetime.now().strftime("%d/%m/%Y") + f" (ผู้ใช้: {user})",
    styles['ThaiNormal']
))

    elements.append(Spacer(1, 12))

    # ✅ ตารางข้อมูล (ตัดคอลัมน์ "ไฟล์แนบ" ออก)
    headers = ["หมายเลขรถ","ผู้ตรวจสอบ","วันที่","ความคิดเห็น",
               "รายการความเสียหาย","ผู้บันทึก","เวลาบันทึก"]
    data = [[Paragraph(h, styles['ThaiNormal']) for h in headers]]

    for r in recs:
        row = [
            Paragraph(str(r[1] or "-"), styles['ThaiNormal']),  # หมายเลขรถ
            Paragraph(str(r[2] or "-"), styles['ThaiNormal']),  # ผู้ตรวจสอบ
            Paragraph(str(r[3] or "-"), styles['ThaiNormal']),  # วันที่
            Paragraph(str(r[5] or "-"), styles['ThaiNormal']),  # ความคิดเห็น
            Paragraph(str(r[6] or "-"), styles['ThaiNormal']),  # ความเสียหาย
            Paragraph(str(r[7] or "-"), styles['ThaiNormal']),  # ผู้บันทึก
            Paragraph(str(r[8] or "-"), styles['ThaiNormal']),  # เวลาบันทึก
        ]
        data.append(row)

    # ปรับความกว้างคอลัมน์ใหม่ (7 ช่อง)
    col_widths = [70,70,60,100,100,80,80]
    table = Table(data, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0), colors.HexColor("#0d47a1")),
        ('TEXTCOLOR',(0,0),(-1,0), colors.white),
        ('FONTNAME',(0,0),(-1,-1),'THSarabunNew'),
        ('FONTSIZE',(0,0),(-1,-1),12),
        ('GRID',(0,0),(-1,-1),0.25, colors.grey),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.whitesmoke, colors.lightgrey])
    ]))
    elements.append(table)
    elements.append(Spacer(1, 30))

    # ช่องเซ็นชื่อ
    elements.append(Paragraph("ผู้ตรวจสอบ .................................................", styles['ThaiNormal']))
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("วันที่ ............................................................", styles['ThaiNormal']))

    doc.build(elements, canvasmaker=NumberedCanvas)

    
    return send_file(fp, as_attachment=True)

    #RESTORE DATABASE

@app.route("/restore_db", methods=["GET","POST"])
@login_required
def restore_db():
    if session.get("role") != "admin":
        return "⛔ ไม่มีสิทธิ์", 403

    if request.method == "POST":
        file = request.files.get("dbfile")
        if file and file.filename.endswith(".db"):
            # 🔹 สำรอง DB เดิมก่อน
            backup_path = DB_NAME + ".bak"
            if os.path.exists(DB_NAME):
                os.replace(DB_NAME, backup_path)

            # 🔹 บันทึกไฟล์ใหม่ทับ DB เดิม
            save_path = DB_NAME
            file.save(save_path)

            flash("✅ Restore DB เรียบร้อย (ไฟล์เก่าเก็บเป็น .bak)", "success")
            return redirect(url_for("index"))
        else:
            flash("⚠️ กรุณาอัปโหลดไฟล์ .db เท่านั้น", "danger")
            return redirect(url_for("restore_db"))

    return render_template_string(THEME_CSS + """

    <div class="container-narrow mt-3">
      <h4>🗂️ Restore Database</h4>
      <form method="post" enctype="multipart/form-data" class="card card-body shadow-sm">
        <label for="dbfile">เลือกไฟล์ .db เพื่อ restore:</label>
        <input type="file" name="dbfile" id="dbfile" accept=".db" class="form-control" required>
        <button class="btn btn-danger mt-3">♻️ Restore</button>
        <a href="{{url_for('index')}}" class="btn btn-secondary mt-2">⬅ กลับหน้าหลัก</a>
      </form>
    </div>
    """)


# -------------------- Run --------------------
if __name__=="__main__":
    init_db()
    app.run(debug=True)

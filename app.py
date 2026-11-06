"""Yeterse Family Savings - Flask API with SQL database (SQLite or PostgreSQL)."""
import os, json, time, uuid, secrets, datetime as dt
from functools import wraps
import requests
from flask import Flask, request, jsonify, send_from_directory
from sqlalchemy import create_engine, text
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
E = os.environ
DB_URL = E.get("DATABASE_URL") or "sqlite:///" + os.path.join(BASE, "data", "yeterse.db")
if DB_URL.startswith("postgres://"):
    DB_URL = "postgresql+psycopg2://" + DB_URL[len("postgres://"):]
elif DB_URL.startswith("postgresql://"):
    DB_URL = "postgresql+psycopg2://" + DB_URL[len("postgresql://"):]
engine = create_engine(DB_URL, pool_pre_ping=True)
app = Flask(__name__, static_folder=None)

ROLES = ["Super Administrator", "Chairperson", "Vice President", "Secretary", "Treasurer",
         "Financial Secretary", "Loans Officer", "Auditor", "Member"]
ADM = ROLES[:2]; FIN = ADM + ["Treasurer", "Financial Secretary"]; SEC = ADM + ["Secretary"]
APR = ADM + ["Treasurer", "Loans Officer", "Vice President"]; LEAD = ROLES[:8]
WRITE = {"savings": FIN, "income": FIN, "expenses": FIN, "withdrawals": FIN, "fines": SEC + ["Treasurer"],
         "welfare": FIN, "leadership": SEC, "rules": SEC, "assets": FIN, "complaints": SEC + ["Vice President"],
         "documents": SEC, "notices": SEC, "meetings": SEC, "audits": ["Auditor"] + ADM,
         "recon": FIN + ["Auditor"], "loans": FIN + ["Loans Officer", "Vice President", "Secretary"]}
MEMBER_CREATE = {"withdrawals", "welfare", "complaints", "loans"}
FIRST_STATUS = {"savings": "Pending", "expenses": "Pending", "withdrawals": "Pending", "welfare": "Pending",
                "loans": "Pending", "complaints": "Open"}
OWN = {"savings", "withdrawals", "fines", "welfare", "complaints", "loans", "payments"}
PUBLIC = {"meetings", "leadership", "rules", "notices", "documents"}
COLLS = sorted(WRITE.keys()) + ["payments"]
BAD = ("Pending", "Rejected", "Reversed", "Cancelled")
POSTED = ("Verified", "Approved", "Posted")
SESSION_DAYS = 30

# ---------------------------------------------------------------- database
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS records (coll VARCHAR(30) NOT NULL, id VARCHAR(64) NOT NULL, member VARCHAR(64),
       status VARCHAR(30), day VARCHAR(10), data TEXT NOT NULL, created VARCHAR(32), updated VARCHAR(32),
       updated_by VARCHAR(64), PRIMARY KEY (coll, id))""",
    """CREATE TABLE IF NOT EXISTS users (member_id VARCHAR(64) PRIMARY KEY, email VARCHAR(200) UNIQUE NOT NULL,
       pw_hash VARCHAR(300) NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS sessions (token VARCHAR(80) PRIMARY KEY, member_id VARCHAR(64), created VARCHAR(32))""",
    """CREATE TABLE IF NOT EXISTS audit (id VARCHAR(40) PRIMARY KEY, at VARCHAR(32), who VARCHAR(120), action TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_rec_member ON records (coll, member)",
]
with engine.begin() as _c:
    for _s in SCHEMA:
        _c.execute(text(_s))

def now(): return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
def today(): return dt.date.today().isoformat()
def rows(sql, **p):
    with engine.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), p)]
def one(sql, **p):
    r = rows(sql, **p); return r[0] if r else None
def run(sql, **p):
    with engine.begin() as c:
        c.execute(text(sql), p)
def get(coll, i):
    r = one("SELECT data FROM records WHERE coll=:c AND id=:i", c=coll, i=str(i))
    return json.loads(r["data"]) if r else None
def allr(coll):
    return [json.loads(r["data"]) for r in rows("SELECT data FROM records WHERE coll=:c ORDER BY created, id", c=coll)]
def put(coll, i, obj, uid):
    p = dict(c=coll, i=str(i), m=str(obj.get("member") or obj.get("by") or ""), s=str(obj.get("status") or ""),
             d=str(obj.get("date") or obj.get("at") or ""), j=json.dumps(obj), t=now(), u=str(uid))
    with engine.begin() as c:
        r = c.execute(text("UPDATE records SET member=:m, status=:s, day=:d, data=:j, updated=:t, updated_by=:u "
                           "WHERE coll=:c AND id=:i"), p)
        if r.rowcount == 0:
            c.execute(text("INSERT INTO records (coll,id,member,status,day,data,created,updated,updated_by) "
                           "VALUES (:c,:i,:m,:s,:d,:j,:t,:t,:u)"), p)
def audit(who, action):
    run("INSERT INTO audit (id, at, who, action) VALUES (:i,:t,:w,:a)", i=uuid.uuid4().hex, t=now(), w=who, a=action[:500])

# ---------------------------------------------------------------- seed
NAMES = [("Namanya Lordothbert", "Chairperson"), ("Nuyebare Julian", "Treasurer"), ("Nampamya Wydiff", "Member"),
         ("Onyesiga Kennedy", "Member"), ("Nyangoma Julia", "Member"), ("Kiiza Kenneth", "Member"),
         ("Kiraba Adrine", "Member"), ("Andrew Kawesa", "Member")]

def new_member(name, role="Member", **extra):
    n = len(allr("members")) + 1
    m = {"id": "m" + uuid.uuid4().hex[:8], "no": "YFS-%03d" % n, "name": name, "role": role, "status": "Active",
         "joined": today()}
    m.update(extra); put("members", m["id"], m, "system"); return m

def seed():
    if not rows("SELECT id FROM records WHERE coll='members' LIMIT 1"):
        for n, r in NAMES:
            new_member(n, r, joined="2026-01-01")
        put("org", "org", {"name": "Yeterse Family Savings Organisation", "cur": "UGX", "fy": "January to December 2026",
                           "monthly": 50000, "rate": 2, "mult": 3, "dueDay": 15, "payno": "0759461248",
                           "cs": "2026-01-01", "ce": "2026-12-31"}, "system")
        for m in allr("members")[:3]:
            put("leadership", uuid.uuid4().hex[:8], {"id": uuid.uuid4().hex[:8], "position": m["role"] if m["role"] != "Member" else "Committee Member",
                "member": m["id"], "start": "2026-01-01", "status": "Active"}, "system")
    for role, email, pw in (("Chairperson", E.get("CHAIR_EMAIL", "namanyalordothbert@gmail.com"), E.get("CHAIR_PASSWORD", "123456")),
                            ("Treasurer", E.get("TREASURER_EMAIL", "nayebarejulian@gmail.com"), E.get("TREASURER_PASSWORD", "123456"))):
        m = next((x for x in allr("members") if x["role"] == role), None)
        if m and not one("SELECT member_id FROM users WHERE member_id=:m", m=m["id"]):
            run("INSERT INTO users (member_id,email,pw_hash) VALUES (:m,:e,:h)", m=m["id"], e=email.lower(), h=generate_password_hash(pw))
seed()

# ---------------------------------------------------------------- auth
FAILS = {}
def auth(f):
    @wraps(f)
    def w(*a, **k):
        h = request.headers.get("Authorization", "")
        tok = h[7:] if h.startswith("Bearer ") else ""
        s = one("SELECT member_id, created FROM sessions WHERE token=:t", t=tok) if tok else None
        if not s or time.time() - float(s["created"]) > SESSION_DAYS * 86400:
            return jsonify(error="Sign in again."), 401
        me = get("members", s["member_id"])
        if not me or me.get("status") != "Active":
            return jsonify(error="This account is inactive. Contact the chairperson."), 403
        request.me = me; request.tok = tok
        return f(*a, **k)
    return w

def is_email(e): return bool(e) and "@" in e and "." in e.split("@")[-1] and " " not in e
def taken_ids(): return {r["member_id"] for r in rows("SELECT member_id FROM users")}

@app.post("/api/login")
def login():
    b = request.get_json(silent=True) or {}
    em = str(b.get("email", "")).strip().lower()
    recent = [t for t in FAILS.get(em, []) if time.time() - t < 600]
    if len(recent) >= 8:
        return jsonify(error="Too many attempts. Wait 10 minutes and try again."), 429
    u = one("SELECT member_id, pw_hash FROM users WHERE email=:e", e=em)
    if not u:
        return jsonify(error="No account found for that email. Register first."), 401
    if not check_password_hash(u["pw_hash"], str(b.get("password", ""))):
        FAILS[em] = recent + [time.time()]
        return jsonify(error="Wrong password. Try again."), 401
    m = get("members", u["member_id"])
    if not m or m.get("status") != "Active":
        return jsonify(error="This account is inactive. Contact the chairperson."), 403
    tok = secrets.token_urlsafe(32)
    run("INSERT INTO sessions (token, member_id, created) VALUES (:t,:m,:c)", t=tok, m=m["id"], c=str(time.time()))
    audit(m["name"], "Signed in")
    return jsonify(token=tok)

@app.post("/api/logout")
@auth
def logout():
    run("DELETE FROM sessions WHERE token=:t", t=request.tok); return jsonify(ok=True)

@app.get("/api/public/unregistered")
def unregistered():
    t = taken_ids()
    return jsonify([m["name"] for m in allr("members") if m["id"] not in t])

@app.post("/api/register")
def register():
    b = request.get_json(silent=True) or {}
    name = " ".join(str(b.get("name", "")).split()); em = str(b.get("email", "")).strip().lower()
    ph = str(b.get("phone", "")).strip(); pw = str(b.get("password", ""))
    if not name or not ph or not is_email(em) or len(pw) < 6:
        return jsonify(error="Enter your name, a valid email, your phone number and a password of 6+ characters."), 400
    if one("SELECT member_id FROM users WHERE email=:e", e=em):
        return jsonify(error="That email is already registered. Sign in instead."), 409
    t = taken_ids(); members = allr("members")
    if any(m["name"].lower() == name.lower() and m["id"] in t for m in members):
        return jsonify(error="This name is already registered. Sign in instead."), 409
    m = next((x for x in members if x["name"].lower() == name.lower() and x["id"] not in t), None)
    if m: m["phone"] = ph; put("members", m["id"], m, "system")
    else: m = new_member(name, "Member", phone=ph)
    run("INSERT INTO users (member_id,email,pw_hash) VALUES (:m,:e,:h)", m=m["id"], e=em, h=generate_password_hash(pw))
    audit(name, "Registered an account"); return jsonify(ok=True)

@app.post("/api/members")
@auth
def add_member():
    me = request.me; b = request.get_json(silent=True) or {}
    if me["role"] not in SEC: return jsonify(error="Only the chairperson or secretary can add members."), 403
    name = " ".join(str(b.get("name", "")).split()); em = str(b.get("email", "")).strip().lower(); pw = str(b.get("password", ""))
    role = b.get("role") if b.get("role") in ROLES else "Member"
    if role != "Member" and me["role"] not in ADM: return jsonify(error="Only the chairperson can assign roles."), 403
    if not name or not is_email(em) or len(pw) < 6: return jsonify(error="Enter a name, a valid email and a password of 6+ characters."), 400
    if one("SELECT member_id FROM users WHERE email=:e", e=em): return jsonify(error="That email is already registered."), 409
    m = new_member(name, role, phone=str(b.get("phone", "")), address=str(b.get("address", "")), nok=str(b.get("nok", "")), occ=str(b.get("occ", "")))
    run("INSERT INTO users (member_id,email,pw_hash) VALUES (:m,:e,:h)", m=m["id"], e=em, h=generate_password_hash(pw))
    audit(me["name"], "Registered member " + name); return jsonify(ok=True, id=m["id"])

@app.post("/api/members/<mid>/password")
@auth
def reset_pw(mid):
    me = request.me
    if me["role"] not in ADM: return jsonify(error="Only the chairperson can reset passwords."), 403
    pw = str((request.get_json(silent=True) or {}).get("password", ""))
    if len(pw) < 6: return jsonify(error="Use at least 6 characters."), 400
    if not one("SELECT member_id FROM users WHERE member_id=:m", m=mid): return jsonify(error="That member has no login yet."), 404
    run("UPDATE users SET pw_hash=:h WHERE member_id=:m", h=generate_password_hash(pw), m=mid)
    run("DELETE FROM sessions WHERE member_id=:m", m=mid)
    audit(me["name"], "Reset password for " + str((get("members", mid) or {}).get("name"))); return jsonify(ok=True)

@app.post("/api/password")
@auth
def change_pw():
    me = request.me; b = request.get_json(silent=True) or {}
    u = one("SELECT pw_hash FROM users WHERE member_id=:m", m=me["id"])
    if not u or not check_password_hash(u["pw_hash"], str(b.get("old", ""))): return jsonify(error="Your current password is wrong."), 400
    if len(str(b.get("new", ""))) < 6: return jsonify(error="Use at least 6 characters."), 400
    run("UPDATE users SET pw_hash=:h WHERE member_id=:m", h=generate_password_hash(b["new"]), m=me["id"])
    audit(me["name"], "Changed own password"); return jsonify(ok=True)

# ---------------------------------------------------------------- reading data
def visible(coll, rs, me):
    uid = str(me["id"])
    if me["role"] != "Member":
        if coll == "complaints" and me["role"] not in SEC + ["Vice President"]: return []
        return rs
    if coll in OWN: return [r for r in rs if str(r.get("member")) == uid]
    if coll in PUBLIC: return [r for r in rs if not (coll == "documents" and r.get("acc") == "Leaders only")]
    return []

@app.get("/api/state")
@auth
def state():
    me = request.me; uid = str(me["id"]); out = {"me": me["id"], "org": get("org", "org")}
    ms = allr("members")
    for m in ms:
        if me["role"] not in SEC and str(m["id"]) != uid:
            for k in ("email", "address", "nok", "occ"): m.pop(k, None)
            if me["role"] == "Member": m.pop("phone", None)
    out["members"] = ms
    for c in COLLS: out[c] = visible(c, allr(c), me)
    out["log"] = []
    if me["role"] in LEAD:
        out["log"] = [{"t": r["at"][:16], "w": r["who"], "a": r["action"]}
                      for r in reversed(rows("SELECT at, who, action FROM audit ORDER BY at DESC LIMIT 200"))]
    return jsonify(out)

@app.get("/api/backup")
@auth
def backup():
    if request.me["role"] not in ADM: return jsonify(error="Only the chairperson can download a backup."), 403
    d = {c: allr(c) for c in COLLS + ["members"]}; d["org"] = get("org", "org")
    d["audit"] = rows("SELECT at, who, action FROM audit ORDER BY at")
    return jsonify(d)

# ---------------------------------------------------------------- writing data (rules enforced here)
def loan_due(l):
    return round(float(l.get("amount", 0)) * (1 + float(l.get("rate", 0)) / 100 * float(l.get("months", 0))))
def loan_paid(l): return sum(float(x.get("amount", 0)) for x in l.get("reps", []))
def eligible(mid):
    ok = lambda r: r.get("status") not in BAD and str(r.get("member")) == mid
    sav = sum(float(r["amount"]) for r in allr("savings") if ok(r))
    wd = sum(float(r["amount"]) for r in allr("withdrawals") if ok(r))
    out = sum(loan_due(l) - loan_paid(l) for l in allr("loans") if l.get("status") == "Disbursed" and str(l.get("member")) == mid)
    return sav - wd - out

def check_loan(me, old, new):
    role, uid = me["role"], str(me["id"]); os_, ns = old.get("status"), new.get("status")
    if ns != os_:
        allowed = {("Pending", "Approved"): APR, ("Pending", "Rejected"): APR, ("Approved", "Disbursed"): FIN, ("Disbursed", "Closed"): FIN}.get((os_, ns))
        if not allowed or role not in allowed: return "That loan status change is not allowed for your role."
        if os_ == "Pending" and str(old.get("member")) == uid: return "You cannot approve your own loan."
        if ns == "Approved" and not float(new.get("amount", 0)) > 0: return "Enter a valid approved amount."
    o, n = old.get("reps", []), new.get("reps", [])
    if n[:len(o)] != o: return "Earlier repayments cannot be changed."
    if len(n) != len(o):
        if role not in FIN: return "Only the treasurer or chairperson can record repayments."
        if old.get("status") != "Disbursed": return "Repayments can only be recorded on disbursed loans."
        if loan_paid(new) > loan_due(new) + 0.5: return "Repayment is more than the loan balance."
    if os_ in ("Disbursed", "Closed") and float(new.get("amount", 0)) != float(old.get("amount", 0)): return "The loan amount cannot change."
    return None

def check(me, coll, old, new):
    role, uid = me["role"], str(me["id"])
    if coll == "org":
        return None if role in ADM else "Only the chairperson can change settings."
    if coll == "members":
        if role not in ADM: return "Only the chairperson can change member accounts."
        if old is None: return "Use the add member form."
        if str(old["id"]) == uid and new.get("status") != "Active": return "You cannot deactivate your own account."
        if new.get("role") not in ROLES: return "Unknown role."
        new["id"], new["no"] = old["id"], old["no"]; return None
    if coll not in WRITE: return "That record type cannot be changed."
    can = role in WRITE[coll]
    if old is None:
        new["by"] = uid
        if not can and not (coll in MEMBER_CREATE and str(new.get("member")) == uid): return "You do not have permission to add this."
        if coll in FIRST_STATUS and new.get("status") != FIRST_STATUS[coll]: return "New records must start as " + FIRST_STATUS[coll] + "."
        if "amount" in new and not float(new.get("amount") or 0) > 0 and coll != "fines": return "Enter an amount above zero."
        return None
    if not can: return "You do not have permission to change this record."
    new["by"] = old.get("by")
    if coll == "loans": return check_loan(me, old, new)
    os_, ns = old.get("status"), new.get("status")
    if os_ == "Reversed" and ns != "Reversed": return "Reversed records cannot be reopened."
    if os_ == "Pending" and ns in ("Approved", "Verified"):
        if str(old.get("by")) == uid: return "You cannot approve a record you entered yourself."
        if role not in set(APR) | set(FIN): return "Only approvers can approve this."
        if coll == "withdrawals":
            e = eligible(str(old.get("member")))
            if float(new.get("amount", 0)) > e: return "Amount is more than the eligible balance of %d." % max(0, e)
    if os_ in POSTED and coll != "fines":
        if ns not in (os_, "Reversed", "Paid"): return "Posted records can only be reversed, not changed."
        if "amount" in old and float(new.get("amount", 0)) != float(old["amount"]): return "Posted amounts cannot be changed."
        if str(new.get("member")) != str(old.get("member")): return "The member on a posted record cannot change."
    return None

@app.post("/api/sync")
@auth
def sync():
    me = request.me; ops = (request.get_json(silent=True) or {}).get("ops", []); ok, bad = [], []
    for op in ops[:200]:
        c, i, d = op.get("c"), str(op.get("id", "")), op.get("d")
        if not i or not isinstance(d, dict) or not (c in WRITE or c in ("org", "members")):
            bad.append({"c": c, "id": i, "reason": "Invalid request."}); continue
        old = get(c, i)
        err = check(me, c, old, d)
        if err: bad.append({"c": c, "id": i, "reason": err}); continue
        put(c, i, d, me["id"])
        desc = " ".join(str(d[k]) for k in ("name", "title", "type", "amount", "status") if d.get(k) not in (None, ""))
        audit(me["name"] + " (" + me["role"] + ")", ("Added " if old is None else "Updated ") + c + ": " + desc)
        ok.append(i)
    return jsonify(ok=ok, rejected=bad)

# ---------------------------------------------------------------- mobile money
def need(*names):
    miss = [n for n in names if not E.get(n)]
    if miss: raise RuntimeError("Mobile money is not set up on the server yet (missing " + ", ".join(miss) + ").")
def network(n):
    p = n[:3]
    return "MTN" if p in ("077", "078", "076", "039") else "AIRTEL" if p in ("070", "075", "074", "020") else None
def mtn_token():
    need("MTN_BASE", "MTN_SUB_KEY", "MTN_API_USER", "MTN_API_KEY")
    r = requests.post(E["MTN_BASE"] + "/collection/token/", auth=(E["MTN_API_USER"], E["MTN_API_KEY"]),
                      headers={"Ocp-Apim-Subscription-Key": E["MTN_SUB_KEY"]}, timeout=20)
    if not r.ok: raise RuntimeError("MTN login failed")
    return r.json()["access_token"]
def mtn_charge(p):
    need("MTN_BASE", "MTN_SUB_KEY", "MTN_API_USER", "MTN_API_KEY")
    r = requests.post(E["MTN_BASE"] + "/collection/v1_0/requesttopay", timeout=20, json={
        "amount": str(p["amount"]), "currency": E.get("MTN_CURRENCY", "UGX"), "externalId": p["id"][:8],
        "payer": {"partyIdType": "MSISDN", "partyId": "256" + p["ref"][1:]}, "payerMessage": "Monthly savings", "payeeNote": "Savings"},
        headers={"Authorization": "Bearer " + mtn_token(), "X-Reference-Id": str(uuid.UUID(p["uuid"])), "X-Target-Environment": E.get("MTN_ENV", "sandbox"),
                 "Ocp-Apim-Subscription-Key": E["MTN_SUB_KEY"]})
    if r.status_code != 202: raise RuntimeError("MTN did not accept the request")
def mtn_status(p):
    need("MTN_BASE", "MTN_SUB_KEY", "MTN_API_USER", "MTN_API_KEY")
    r = requests.get(E["MTN_BASE"] + "/collection/v1_0/requesttopay/" + p["uuid"], timeout=20,
                     headers={"Authorization": "Bearer " + mtn_token(), "X-Target-Environment": E.get("MTN_ENV", "sandbox"), "Ocp-Apim-Subscription-Key": E["MTN_SUB_KEY"]})
    s = (r.json() or {}).get("status") if r.ok else None
    return "successful" if s == "SUCCESSFUL" else "failed" if s == "FAILED" else "pending"
def airtel_headers():
    need("AIRTEL_BASE", "AIRTEL_CLIENT_ID", "AIRTEL_CLIENT_SECRET")
    r = requests.post(E["AIRTEL_BASE"] + "/auth/oauth2/token", timeout=20, json={"client_id": E["AIRTEL_CLIENT_ID"],
        "client_secret": E["AIRTEL_CLIENT_SECRET"], "grant_type": "client_credentials"})
    if not r.ok: raise RuntimeError("Airtel login failed")
    return {"Authorization": "Bearer " + r.json()["access_token"], "Content-Type": "application/json", "X-Country": "UG", "X-Currency": "UGX"}
def airtel_charge(p):
    need("AIRTEL_BASE", "AIRTEL_CLIENT_ID", "AIRTEL_CLIENT_SECRET")
    r = requests.post(E["AIRTEL_BASE"] + "/merchant/v1/payments/", headers=airtel_headers(), timeout=20, json={
        "reference": "Monthly savings", "subscriber": {"country": "UG", "currency": "UGX", "msisdn": p["ref"][1:]},
        "transaction": {"amount": p["amount"], "country": "UG", "currency": "UGX", "id": p["id"]}})
    if not r.ok: raise RuntimeError("Airtel did not accept the request")
def airtel_status(p):
    need("AIRTEL_BASE", "AIRTEL_CLIENT_ID", "AIRTEL_CLIENT_SECRET")
    r = requests.get(E["AIRTEL_BASE"] + "/standard/v1/payments/" + p["id"], headers=airtel_headers(), timeout=20)
    s = (((r.json() or {}).get("data") or {}).get("transaction") or {}).get("status") if r.ok else None
    return "successful" if s == "TS" else "failed" if s == "TF" else "pending"

@app.post("/api/pay")
@auth
def pay():
    me = request.me; b = request.get_json(silent=True) or {}
    phone = "".join(ch for ch in str(b.get("phone", "")) if ch.isdigit())
    try: amount = int(float(b.get("amount", 0)))
    except ValueError: amount = 0
    net = network(phone) if len(phone) == 10 and phone[0] == "0" else None
    if not net: return jsonify(error="Use an MTN or Airtel number like 0772123456."), 400
    if not 1000 <= amount <= 5000000: return jsonify(error="Amount must be between 1,000 and 5,000,000."), 400
    pid = uuid.uuid4().hex[:12]
    p = {"id": pid, "uuid": str(uuid.uuid4()), "member": me["id"], "amount": amount, "net": net, "ref": phone,
         "method": "MTN Mobile Money" if net == "MTN" else "Airtel Money", "date": today(), "status": "pending", "created": time.time()}
    try:
        (mtn_charge if net == "MTN" else airtel_charge)(p)
    except Exception as e:
        app.logger.warning("pay failed: %s", e); return jsonify(error=str(e)), 502
    put("payments", pid, p, me["id"]); audit(me["name"], "Requested payment prompt of %d to %s" % (amount, phone))
    return jsonify(id=pid, network=net)

@app.get("/api/pay/<pid>")
@auth
def pay_status(pid):
    me = request.me; p = get("payments", pid)
    if not p or (str(p["member"]) != str(me["id"]) and me["role"] not in LEAD): return jsonify(error="Not found"), 404
    if p["status"] == "pending":
        st = "pending"
        try: st = (mtn_status if p["net"] == "MTN" else airtel_status)(p)
        except Exception as e: app.logger.warning("status check failed: %s", e)
        if st == "successful":
            p["status"] = "confirmed"
            if not get("savings", "pay-" + pid):
                put("savings", "pay-" + pid, {"id": "pay-" + pid, "member": p["member"], "type": "Monthly", "amount": p["amount"],
                    "date": today(), "method": "Mobile money", "ref": p["method"], "status": "Verified", "sid": pid, "by": p["member"]}, "system")
            audit(me["name"], "Mobile money payment confirmed: %d" % p["amount"])
        elif st == "failed" or time.time() - float(p["created"]) > 300: p["status"] = "failed"
        put("payments", pid, p, "system")
    return jsonify(status=p["status"])

@app.post("/api/pay/<pid>/cancel")
@auth
def pay_cancel(pid):
    p = get("payments", pid)
    if p and str(p["member"]) == str(request.me["id"]) and p["status"] == "pending":
        p["status"] = "cancelled"; put("payments", pid, p, request.me["id"])
    return jsonify(ok=True)

# ---------------------------------------------------------------- pages
@app.get("/api/health")
def health(): return jsonify(ok=True)

@app.get("/")
def index():
    for d in (os.path.join(BASE, "public"), BASE):
        if os.path.exists(os.path.join(d, "index.html")): return send_from_directory(d, "index.html")
    return "index.html is missing from the project.", 404

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(E.get("PORT", 5000)))

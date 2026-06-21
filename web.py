import hmac
import os
import sqlite3
from flask import Flask, Response, render_template_string, request
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)
DB_PATH = os.getenv("DB_PATH", "bot_data.db")
WEB_USER = os.getenv("WEB_USER", "admin")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "")


@app.before_request
def require_auth():
    if app.config.get("TESTING"):
        return None
    auth = request.authorization
    if auth and hmac.compare_digest(auth.username or "", WEB_USER) and hmac.compare_digest(auth.password or "", WEB_PASSWORD):
        return None
    return Response(
        "Authentication required.",
        401,
        {"WWW-Authenticate": 'Basic realm="Homeconf Admin"'},
    )

def format_tz(ts):
    if not ts:
        return "N/A"
    try:
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts)
        else:
            dt = ts
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo("Europe/Zurich")).strftime('%Y-%m-%d %H:%M:%S')
    except:
        return ts

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def format_name(user):
    if user['username']:
        return f"@{user['username']}"
    first = user['first_name'] or 'Unknown'
    uid = user['user_id'] or 'N/A'
    return f"{first} ({uid})"

app.jinja_env.filters['format_tz'] = format_tz
app.jinja_env.filters['format_name'] = format_name

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Homeconf Admin Dashboard</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.4; color: #333; margin: 0; padding: 0.75rem; background: #f4f7f6; font-size: 13px; }
        h1 { margin: 0 0 0.5rem; color: #2c3e50; font-size: 1.3rem; }
        h2 { color: #34495e; margin: 0 0 0.4rem; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; }
        .topbar { display: flex; align-items: baseline; gap: 1rem; margin-bottom: 0.75rem; }
        .stats { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.75rem; }
        .stat-card { background: white; padding: 0.35rem 0.65rem; border-radius: 5px; border-left: 3px solid #3498db; white-space: nowrap; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
        .stat-card .label { font-size: 0.68rem; text-transform: uppercase; color: #7f8c8d; }
        .stat-card .value { font-size: 1.05rem; font-weight: bold; line-height: 1.2; }
        .grid { display: grid; grid-template-columns: 1fr 1fr 1fr 1.4fr; gap: 0.6rem; align-items: start; }
        .panel { background: white; border-radius: 5px; padding: 0.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 0.6rem; }
        .panel:last-child { margin-bottom: 0; }
        .panel-col { display: flex; flex-direction: column; }
        .panel-logs { background: white; border-radius: 5px; padding: 0.5rem; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 0.28rem 0.4rem; text-align: left; border-bottom: 1px solid #f0f0f0; }
        th { background: #f8f9fa; font-weight: 600; color: #555; position: sticky; top: 0; font-size: 0.72rem; text-transform: uppercase; }
        td { font-size: 0.82rem; }
        tr:last-child td { border-bottom: none; }
        tr:hover { background: #fafafa; }
        .table-wrap { overflow-y: auto; }
        .status-badge { display: inline-block; padding: 0.1rem 0.4rem; border-radius: 3px; font-size: 0.72rem; font-weight: 600; text-transform: uppercase; }
        .status-open { background: #d4edda; color: #155724; }
        .status-review { background: #fff3cd; color: #856404; }
        .status-closed { background: #f8d7da; color: #721c24; }
        .status-pre_open { background: #cce5ff; color: #004085; }
        .status-cancelled { background: #e2e3e5; color: #383d41; }
        .test-link { padding: 0.2rem 0.6rem; background: #e2e3e5; color: #383d41; text-decoration: none; border-radius: 4px; font-size: 0.8rem; }
        .test-link:hover { background: #d6d8db; }
        .muted { color: #aaa; font-style: italic; }
    </style>
    <script>
        function reloadData() {
            setTimeout(() => {
                localStorage.setItem('scrollPosition', window.scrollY);
                const scrolls = {};
                document.querySelectorAll('.table-wrap[id]').forEach((el) => { scrolls[el.id] = el.scrollTop; });
                localStorage.setItem('containerScrolls', JSON.stringify(scrolls));
                location.reload();
            }, 5000);
        }
        function restoreScroll() {
            const scrollPos = localStorage.getItem('scrollPosition');
            if (scrollPos) { window.scrollTo(0, parseInt(scrollPos)); localStorage.removeItem('scrollPosition'); }
            const scrolls = JSON.parse(localStorage.getItem('containerScrolls') || '{}');
            for (const id in scrolls) { const el = document.getElementById(id); if (el) el.scrollTop = scrolls[id]; }
            localStorage.removeItem('containerScrolls');
            reloadData();
        }
    </script>
</head>
<body onload="restoreScroll()">

    <div class="topbar">
        <h1>Homeconf Admin {{ '· TEST EVENT' if event and event.id < 0 else '' }}</h1>
        {% if latest_test and (not event or event.id != latest_test.id) %}
            <a href="/?event_id={{ latest_test.id }}" class="test-link">Switch to Test Event #{{ latest_test.id }}</a>
        {% endif %}
        {% if event and event.id < 0 %}
            <a href="/" class="test-link">Back to Real Event</a>
        {% endif %}
    </div>

    {% if not event or event.status == 'CANCELLED' %}
        <p>No active event found.</p>
        {% if logs %}
        <div class="panel-logs">
            <h2>Action Logs (Zurich)</h2>
            <div class="table-wrap" id="logs-wrap-no-event" style="max-height: 80vh;">
                <table>
                    <tr><th>Time</th><th>User</th><th>Action</th><th>Details</th></tr>
                    {% for log in logs %}
                    <tr>
                        <td style="white-space: nowrap;">{{ log['timestamp']|format_tz }}</td>
                        <td>{{ log|format_name if log['username'] or log['first_name'] else 'System' }}</td>
                        <td><b>{{ log['action'] }}</b></td>
                        <td>{{ log['details'] }}</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
        {% endif %}
    {% else %}
        <div class="stats">
            <div class="stat-card"><div class="label">Event</div><div class="value">#{{ event.id }}</div></div>
            <div class="stat-card"><div class="label">Status</div><div class="value"><span class="status-badge status-{{ event.status|lower }}">{{ event.status }}</span></div></div>
            <div class="stat-card"><div class="label">Places</div><div class="value">{{ event.total_places or '—' }}</div></div>
            <div class="stat-card"><div class="label">Admitted</div><div class="value">{{ admitted|length }}</div></div>
            <div class="stat-card"><div class="label">Guests</div><div class="value">{{ invitees|length }}</div></div>
            <div class="stat-card"><div class="label">Registered</div><div class="value">{{ registered|length }}</div></div>
            <div class="stat-card"><div class="label">Waitlist</div><div class="value">{{ waitlist|length }}</div></div>
            <div class="stat-card"><div class="label">Speakers</div><div class="value">{{ speakers|length }}</div></div>
        </div>

        <div class="grid">
            <!-- Col 1: Speakers + Waitlist -->
            <div class="panel-col">
                <div class="panel">
                    <h2>Speakers ({{ speakers|length }})</h2>
                    <div class="table-wrap" id="speakers-wrap" style="max-height: 200px;">
                        <table>
                            <tr><th>Name</th><th>@username</th></tr>
                            {% for s in speakers %}
                            <tr><td>{{ s['first_name'] or '—' }}</td><td>@{{ s['username'] }}</td></tr>
                            {% endfor %}
                            {% if not speakers %}<tr><td colspan="2" class="muted">No speakers</td></tr>{% endif %}
                        </table>
                    </div>
                </div>
                <div class="panel">
                    <h2>Waitlist ({{ waitlist|length }})</h2>
                    <div class="table-wrap" id="waitlist-wrap" style="max-height: 200px;">
                        <table>
                            <tr><th>#</th><th>Name</th><th>@username</th></tr>
                            {% for r in waitlist %}
                            <tr><td>{{ r['priority'] }}</td><td>{{ r['first_name'] or '—' }}</td><td>@{{ r['username'] or '—' }}</td></tr>
                            {% endfor %}
                            {% if not waitlist %}<tr><td colspan="3" class="muted">Empty</td></tr>{% endif %}
                        </table>
                    </div>
                </div>
            </div>

            <!-- Col 2: Guests + Registered pool -->
            <div class="panel-col">
                <div class="panel">
                    <h2>Guests / Invitees ({{ invitees|length }})</h2>
                    <div class="table-wrap" id="invitees-wrap" style="max-height: 200px;">
                        <table>
                            <tr><th>Name</th><th>@username</th><th>By</th></tr>
                            {% for r in invitees %}
                            <tr>
                                <td>{{ r['first_name'] or '—' }}</td>
                                <td>{{ r['username'] or '—' }}</td>
                                <td>@{{ r['speaker_username'] or r['guest_of_user_id'] }}</td>
                            </tr>
                            {% endfor %}
                            {% if not invitees %}<tr><td colspan="3" class="muted">No guests</td></tr>{% endif %}
                        </table>
                    </div>
                </div>
                <div class="panel">
                    <h2>Registered pool ({{ registered|length }})</h2>
                    <div class="table-wrap" id="registered-wrap" style="max-height: 200px;">
                        <table>
                            <tr><th>Name</th><th>@username</th><th>Time</th></tr>
                            {% for r in registered %}
                            <tr>
                                <td>{{ r['first_name'] or '—' }}</td>
                                <td>@{{ r['username'] or '—' }}</td>
                                <td style="white-space:nowrap;">{{ r['signup_time']|format_tz }}</td>
                            </tr>
                            {% endfor %}
                            {% if not registered %}<tr><td colspan="3" class="muted">No registrations</td></tr>{% endif %}
                        </table>
                    </div>
                </div>
            </div>

            <!-- Col 3: Admitted + Unregistered -->
            <div class="panel-col">
                <div class="panel">
                    <h2>Admitted / confirmed ({{ admitted|length }})</h2>
                    <div class="table-wrap" id="admitted-wrap" style="max-height: 200px;">
                        <table>
                            <tr><th>Name</th><th>@username</th><th>Status</th></tr>
                            {% for r in admitted %}
                            <tr>
                                <td>{{ r['first_name'] or '—' }}</td>
                                <td>@{{ r['username'] or '—' }}</td>
                                <td>{{ r['status'] }}</td>
                            </tr>
                            {% endfor %}
                            {% if not admitted %}<tr><td colspan="3" class="muted">No winners yet</td></tr>{% endif %}
                        </table>
                    </div>
                </div>
                <div class="panel">
                    <h2>Unregistered / expired ({{ unregistered|length }})</h2>
                    <div class="table-wrap" id="unregistered-wrap" style="max-height: 200px;">
                        <table>
                            <tr><th>Name</th><th>@username</th><th>Status</th></tr>
                            {% for r in unregistered %}
                            <tr>
                                <td>{{ r['first_name'] or '—' }}</td>
                                <td>{{ r['username'] or '—' }}</td>
                                <td>{{ r['status'] }}</td>
                            </tr>
                            {% endfor %}
                            {% if not unregistered %}<tr><td colspan="3" class="muted">None</td></tr>{% endif %}
                        </table>
                    </div>
                </div>
            </div>

            <!-- Col 4: Logs -->
            <div class="panel-logs" style="grid-column: 4;">
                <h2>Action Logs · Zurich</h2>
                <div class="table-wrap" id="logs-wrap-event" style="max-height: calc(100vh - 120px);">
                    <table>
                        <tr><th>Time</th><th>User</th><th>Action</th><th>Details</th></tr>
                        {% for log in logs %}
                        <tr>
                            <td style="white-space: nowrap;">{{ log['timestamp']|format_tz }}</td>
                            <td>{{ log|format_name if log['username'] or log['first_name'] else 'System' }}</td>
                            <td><b>{{ log['action'] }}</b></td>
                            <td>{{ log['details'] }}</td>
                        </tr>
                        {% endfor %}
                    </table>
                </div>
            </div>
        </div>
    {% endif %}

</body>
</html>
"""

@app.route('/')
def dashboard():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name='events'")
    if cursor.fetchone()[0] == 0:
        return render_template_string(TEMPLATE, event=None)

    # Get requested event_id from query param
    event_id_param = request.args.get('event_id')
    
    if event_id_param:
        cursor.execute("SELECT * FROM events WHERE id = ?", (event_id_param,))
        event = cursor.fetchone()
    else:
        # Default: Latest REAL event
        cursor.execute("SELECT * FROM events WHERE id > 0 ORDER BY created_at DESC LIMIT 1")
        event = cursor.fetchone()
        if not event:
            # If no real events, maybe show latest test event
            cursor.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT 1")
            event = cursor.fetchone()

    # Get latest test event for linking
    cursor.execute("SELECT * FROM events WHERE id < 0 ORDER BY created_at DESC LIMIT 1")
    latest_test = cursor.fetchone()
    
    speakers = []
    invitees = []
    registered = []
    admitted = []
    waitlist = []
    unregistered = []
    logs = []
    
    if event:
        if event['status'] != 'CANCELLED':
            cursor.execute("SELECT * FROM speakers WHERE event_id = ?", (event['id'],))
            speakers = cursor.fetchall()
            
            cursor.execute("""
                SELECT r.*, 
                       COALESCE(
                           (SELECT username FROM registrations WHERE user_id = r.guest_of_user_id AND username IS NOT NULL LIMIT 1),
                           (SELECT username FROM action_logs WHERE user_id = r.guest_of_user_id AND username IS NOT NULL ORDER BY id DESC LIMIT 1)
                       ) as speaker_username 
                FROM registrations r 
                WHERE event_id = ? AND status IN ('ACCEPTED', 'INVITED') AND guest_of_user_id IS NOT NULL 
                ORDER BY signup_time ASC
            """, (event['id'],))
            invitees = cursor.fetchall()
            
            cursor.execute("SELECT * FROM registrations WHERE event_id = ? AND status = 'ACCEPTED' AND guest_of_user_id IS NULL ORDER BY signup_time ASC", (event['id'],))
            admitted = cursor.fetchall()
            
            cursor.execute("SELECT * FROM registrations WHERE event_id = ? AND status = 'REGISTERED' ORDER BY signup_time ASC", (event['id'],))
            registered = cursor.fetchall()
            
            cursor.execute("SELECT * FROM registrations WHERE event_id = ? AND status = 'WAITLIST' ORDER BY priority ASC", (event['id'],))
            waitlist = cursor.fetchall()
            
            cursor.execute("""
                SELECT r.*,
                       (SELECT timestamp FROM action_logs WHERE user_id = r.user_id AND event_id = r.event_id AND action IN ('UNREGISTER', 'CALLBACK_DECLINE', 'EXPIRED') ORDER BY id DESC LIMIT 1) as unreg_time
                FROM registrations r 
                WHERE event_id = ? AND status IN ('UNREGISTERED', 'EXPIRED') 
                ORDER BY unreg_time DESC
            """, (event['id'],))
            unregistered = cursor.fetchall()
            
        cursor.execute("SELECT * FROM action_logs WHERE event_id = ? ORDER BY id DESC LIMIT 100", (event['id'],))
        logs = cursor.fetchall()
    else:
        # If no event, maybe show global logs
        cursor.execute("SELECT * FROM action_logs ORDER BY id DESC LIMIT 100")
        logs = cursor.fetchall()

    conn.close()
    return render_template_string(
        TEMPLATE, 
        event=event, 
        latest_test=latest_test,
        speakers=speakers,
        invitees=invitees,
        registered=registered,
        admitted=admitted,
        waitlist=waitlist,
        unregistered=unregistered,
        logs=logs
    )

if __name__ == '__main__':
    if not WEB_PASSWORD:
        raise SystemExit("WEB_PASSWORD environment variable must be set to run the dashboard.")
    app.run(host='0.0.0.0', port=5000)

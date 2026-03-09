import os
import sqlite3
from flask import Flask, render_template_string
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)
DB_PATH = os.getenv("DB_PATH", "bot_data.db")

def format_tz(ts):
    if not ts:
        return ""
    target_tz = ZoneInfo("Europe/Berlin")
    if isinstance(ts, str):
        try:
            # fromisoformat handles 'YYYY-MM-DD HH:MM:SS.mmmmmm+HH:MM' or 'YYYY-MM-DD HH:MM:SS'
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                # Naive timestamps from SQLite are assumed to be UTC
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        except ValueError:
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            except ValueError:
                return ts
    elif isinstance(ts, datetime):
        dt = ts
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    else:
        return ts
    
    return dt.astimezone(target_tz).strftime("%Y-%m-%d %H:%M:%S")

def format_name(user):
    # user is a sqlite3.Row, it doesn't have .get() but can be converted or accessed by index/name
    try:
        username = user['username']
    except (IndexError, KeyError, TypeError):
        username = None

    try:
        first_name = user['first_name']
    except (IndexError, KeyError, TypeError):
        first_name = None

    if username and not str(username).isdigit():
        return f"@{username}"
    if first_name:
        return first_name
    if username: # This would be the ID if it was a speaker without username
        return f"ID: {username}"
    return "Unknown"

app.jinja_env.filters['format_tz'] = format_tz
app.jinja_env.filters['format_name'] = format_name

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Homeconf Admin</title>
    <style>
        body { font-family: sans-serif; margin: 2rem; background: #f4f4f4; color: #333; }
        .container { max-width: 1400px; margin: auto; background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        h1 { color: #222; border-bottom: 2px solid #eee; padding-bottom: 10px; }
        h2 { color: #444; margin-top: 1.5rem; font-size: 1.2rem; background: #fafafa; padding: 8px; border-left: 4px solid #007bff; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; font-size: 0.9em; }
        th, td { padding: 8px; border: 1px solid #ddd; text-align: left; }
        th { background: #eee; position: sticky; top: 0; }
        .row { display: flex; gap: 2rem; align-items: flex-start; }
        .col { flex: 1; }
        .badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; background: #ddd; }
        .status-open { background: #d4edda; color: #155724; }
        .status-review { background: #fff3cd; color: #856404; }
        .status-closed { background: #f8d7da; color: #721c24; }
        .status-pre_open { background: #cce5ff; color: #004085; }
        .status-cancelled { background: #e2e3e5; color: #383d41; }
        .table-wrap { max-height: 400px; overflow-y: auto; margin-bottom: 2rem; border-bottom: 1px solid #ddd; }
        .log-wrap { max-height: 800px; overflow-y: auto; }
    </style>
    <script>
        function reloadData() {
            setTimeout(() => {
                // Save window scroll
                localStorage.setItem('scrollPosition', window.scrollY);
                
                // Save scroll positions for all .table-wrap elements with an ID
                const scrolls = {};
                document.querySelectorAll('.table-wrap').forEach((el) => {
                    if (el.id) {
                        scrolls[el.id] = el.scrollTop;
                    }
                });
                localStorage.setItem('containerScrolls', JSON.stringify(scrolls));
                
                location.reload();
            }, 5000);
        }

        function restoreScroll() {
            // Restore window scroll
            const scrollPos = localStorage.getItem('scrollPosition');
            if (scrollPos) {
                window.scrollTo(0, parseInt(scrollPos));
                localStorage.removeItem('scrollPosition');
            }

            // Restore .table-wrap scrolls
            const scrolls = JSON.parse(localStorage.getItem('containerScrolls') || '{}');
            for (const id in scrolls) {
                const el = document.getElementById(id);
                if (el) {
                    el.scrollTop = scrolls[id];
                }
            }
            localStorage.removeItem('containerScrolls');

            reloadData();
        }
    </script>
</head>
<body onload="restoreScroll()">
    <div class="container">
        <h1>Admin Dashboard</h1>
        <h2>Current Event Status</h2>
        {% if not event or event.status == 'CANCELLED' %}
            <p>No active event found.</p>
            {% if logs %}
                <div class="row">
                    <div class="col" style="flex: 2;">
                        <h2>Real-time Action Logs (Zurich)</h2>
                        <div class="table-wrap log-wrap" id="logs-wrap-no-event">
                            <table>
                                <tr><th>Time</th><th>User</th><th>Action</th><th>Details</th></tr>
                                {% for log in logs %}
                                <tr>
                                    <td style="white-space: nowrap;">{{ log['timestamp']|format_tz }}</td>
                                    <td>{{ log|format_name if log['username'] or log['first_name'] else 'System' }} {{ '(' ~ log['user_id'] ~ ')' if log['user_id'] else '' }}</td>
                                    <td><b>{{ log['action'] }}</b></td>
                                    <td>{{ log['details'] }}</td>
                                </tr>
                                {% endfor %}
                            </table>
                        </div>
                    </div>
                </div>
            {% endif %}
        {% else %}
            <p style="font-size: 1.1em;">
                <strong>Event ID:</strong> {{ event.id }} &nbsp;|&nbsp; 
                <strong>Status:</strong> <span class="badge status-{{ event.status|lower }}">{{ event.status }}</span> &nbsp;|&nbsp; 
                <strong>Total Places:</strong> {{ event.total_places }}
            </p>
            
            <div class="row">
                <div class="col" style="flex: 2;">
                    
                    <h2>Speakers ({{ speakers|length }})</h2>
                    <div class="table-wrap" id="speakers-wrap" style="max-height: 200px;">
                        <table>
                            <tr><th>Name</th></tr>
                            {% for s in speakers %}
                            <tr><td>{{ s|format_name }}</td></tr>
                            {% endfor %}
                            {% if not speakers %}<tr><td>No manual speakers added (may be using Telegram Group)</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>Speakers' guests ({{ invitees|length }})</h2>
                    <div class="table-wrap" id="invitees-wrap">
                        <table>
                            <tr><th>Name</th><th>Status</th><th>Invited By</th></tr>
                            {% for r in invitees %}
                            <tr>
                                <td>{{ r|format_name }}</td>
                                <td><span class="badge">{{ r.status }}</span></td>
                                <td>{{ r.speaker_username or r.guest_of_user_id }}</td>
                            </tr>
                            {% endfor %}
                            {% if not invitees %}<tr><td colspan="3">No invitees yet</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>Admitted (Lottery Winners) ({{ admitted|length }})</h2>
                    <div class="table-wrap" id="admitted-wrap">
                        <table>
                            <tr><th>Name</th><th>Time (Zurich)</th></tr>
                            {% for r in admitted %}
                            <tr>
                                <td>{{ r|format_name }}</td>
                                <td>{{ r.signup_time|format_tz }}</td>
                            </tr>
                            {% endfor %}
                            {% if not admitted %}<tr><td colspan="2">No admitted users</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>Registered (Lottery Pool) ({{ registered|length }})</h2>
                    <div class="table-wrap" id="registered-wrap">
                        <table>
                            <tr><th>Name</th><th>Time (Zurich)</th></tr>
                            {% for r in registered %}
                            <tr>
                                <td>{{ r|format_name }}</td>
                                <td>{{ r.signup_time|format_tz }}</td>
                            </tr>
                            {% endfor %}
                            {% if not registered %}<tr><td colspan="2">No users in pool</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>Waitlist ({{ waitlist|length }})</h2>
                    <div class="table-wrap" id="waitlist-wrap">
                        <table>
                            <tr><th>Priority</th><th>Name</th><th>Status</th></tr>
                            {% for r in waitlist %}
                            <tr>
                                <td>{{ r.priority }}</td>
                                <td>{{ r|format_name }}</td>
                                <td><span class="badge">{{ r.status }}</span></td>
                            </tr>
                            {% endfor %}
                            {% if not waitlist %}<tr><td colspan="3">Waitlist is empty</td></tr>{% endif %}
                        </table>
                    </div>
                </div>
                
                <div class="col" style="flex: 2;">
                    <h2>Real-time Action Logs (Zurich)</h2>
                    <div class="table-wrap log-wrap" id="logs-wrap-event">
                        <table>
                            <tr><th>Time</th><th>User</th><th>Action</th><th>Details</th></tr>
                            {% for log in logs %}
                            <tr>
                                <td style="white-space: nowrap;">{{ log['timestamp']|format_tz }}</td>
                                <td>{{ log|format_name if log['username'] or log['first_name'] else 'System' }} {{ '(' ~ log['user_id'] ~ ')' if log['user_id'] else '' }}</td>
                                <td><b>{{ log['action'] }}</b></td>
                                <td>{{ log['details'] }}</td>
                            </tr>
                            {% endfor %}
                        </table>
                    </div>
                </div>
            </div>
        {% endif %}
    </div>
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

    cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1")
    event = cursor.fetchone()
    
    speakers = []
    invitees = []
    registered = []
    admitted = []
    waitlist = []
    logs = []
    
    if event:
        if event['status'] != 'CANCELLED':
            cursor.execute("SELECT * FROM speakers WHERE event_id = ?", (event['id'],))
            speakers = cursor.fetchall()
            
            cursor.execute("""
                SELECT r.*, 
                       (SELECT username FROM action_logs WHERE user_id = r.guest_of_user_id AND username IS NOT NULL ORDER BY id DESC LIMIT 1) as speaker_username 
                FROM registrations r 
                WHERE r.event_id = ? AND r.guest_of_user_id IS NOT NULL AND r.status IN ('ACCEPTED', 'INVITED', 'UNREGISTERED') 
                ORDER BY r.id DESC
            """, (event['id'],))
            invitees = cursor.fetchall()
            
            cursor.execute("SELECT * FROM registrations WHERE event_id = ? AND status = 'REGISTERED' ORDER BY signup_time ASC", (event['id'],))
            registered = cursor.fetchall()

            cursor.execute("SELECT * FROM registrations WHERE event_id = ? AND status = 'ACCEPTED' AND guest_of_user_id IS NULL ORDER BY signup_time ASC", (event['id'],))
            admitted = cursor.fetchall()
            
            cursor.execute("SELECT * FROM registrations WHERE event_id = ? AND status IN ('WAITLIST', 'INVITED') AND guest_of_user_id IS NULL ORDER BY priority ASC", (event['id'],))
            waitlist = cursor.fetchall()
        
        cursor.execute("SELECT * FROM action_logs WHERE event_id = ? ORDER BY id DESC", (event['id'],))
        logs = cursor.fetchall()
        
    conn.close()
    return render_template_string(
        TEMPLATE, 
        event=event, 
        speakers=speakers,
        invitees=invitees,
        registered=registered,
        admitted=admitted,
        waitlist=waitlist,
        logs=logs
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

import os
import sqlite3
from flask import Flask, render_template_string, request
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)
DB_PATH = os.getenv("DB_PATH", "bot_data.db")

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
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 1200px; margin: 0 auto; padding: 2rem; background: #f4f7f6; }
        .container { background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        h1 { margin-top: 0; color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 0.5rem; }
        h2 { color: #34495e; margin-top: 2rem; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
        .stat-card { background: #f8f9fa; padding: 1rem; border-radius: 6px; border-left: 4px solid #3498db; }
        .stat-card h3 { margin: 0; font-size: 0.9rem; text-transform: uppercase; color: #7f8c8d; }
        .stat-card p { margin: 0.5rem 0 0; font-size: 1.5rem; font-weight: bold; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; font-size: 0.9rem; }
        th, td { padding: 0.75rem; text-align: left; border-bottom: 1px solid #eee; }
        th { background: #f8f9fa; font-weight: 600; color: #2c3e50; position: sticky; top: 0; }
        tr:hover { background: #fcfcfc; }
        .status-badge { display: inline-block; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; }
        .status-open { background: #d4edda; color: #155724; }
        .status-review { background: #fff3cd; color: #856404; }
        .status-closed { background: #f8d7da; color: #721c24; }
        .status-pre_open { background: #cce5ff; color: #004085; }
        .status-cancelled { background: #e2e3e5; color: #383d41; }
        .table-wrap { max-height: 400px; overflow-y: auto; margin-bottom: 2rem; border-bottom: 1px solid #ddd; }
        .log-wrap { max-height: 800px; overflow-y: auto; }
        .test-link { display: inline-block; margin-top: 1rem; padding: 0.5rem 1rem; background: #e2e3e5; color: #383d41; text-decoration: none; border-radius: 4px; font-size: 0.9rem; }
        .test-link:hover { background: #d6d8db; }
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
        <h1>Admin Dashboard {{ '(TEST EVENT)' if event and event.id < 0 else '' }}</h1>
        
        <div style="margin-bottom: 1rem;">
            {% if latest_test and (not event or event.id != latest_test.id) %}
                <a href="/?event_id={{ latest_test.id }}" class="test-link">Switch to Latest Test Event (ID: {{ latest_test.id }})</a>
            {% endif %}
            {% if event and event.id < 0 %}
                <a href="/" class="test-link">Back to Real Event</a>
            {% endif %}
        </div>

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
            <div class="stats">
                <div class="stat-card">
                    <h3>Event ID</h3>
                    <p>#{{ event.id }}</p>
                </div>
                <div class="stat-card">
                    <h3>Status</h3>
                    <p><span class="status-badge status-{{ event.status|lower }}">{{ event.status }}</span></p>
                </div>
                <div class="stat-card">
                    <h3>Total Places</h3>
                    <p>{{ event.total_places or 'N/A' }}</p>
                </div>
                <div class="stat-card">
                    <h3>Remaining Waitlist</h3>
                    <p>{{ waitlist|length }}</p>
                </div>
            </div>

            <div class="row" style="display: flex; gap: 2rem; flex-wrap: wrap;">
                <div class="col" style="flex: 3; min-width: 600px;">
                    <h2>Speakers</h2>
                    <div class="table-wrap" id="speakers-wrap">
                        <table>
                            <tr><th>Name</th><th>Username</th></tr>
                            {% for s in speakers %}
                            <tr>
                                <td>{{ s['first_name'] or 'N/A' }}</td>
                                <td>@{{ s['username'] }}</td>
                            </tr>
                            {% endfor %}
                            {% if not speakers %}<tr><td colspan="2">No speakers</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>Guests (Invitees)</h2>
                    <div class="table-wrap" id="invitees-wrap">
                        <table>
                            <tr><th>Name</th><th>Username</th><th>Invited By</th><th>Time</th></tr>
                            {% for r in invitees %}
                            <tr>
                                <td>{{ r['first_name'] or 'N/A' }}</td>
                                <td>{{ r['username'] or 'N/A' }}</td>
                                <td>@{{ r['speaker_username'] or 'ID:' ~ r['guest_of_user_id'] }}</td>
                                <td>{{ r['signup_time'] }}</td>
                            </tr>
                            {% endfor %}
                            {% if not invitees %}<tr><td colspan="4">No guest invitations</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>Admitted (Lottery Winners)</h2>
                    <div class="table-wrap" id="admitted-wrap">
                        <table>
                            <tr><th>Name</th><th>Username</th><th>Status</th><th>Time</th></tr>
                            {% for r in admitted %}
                            <tr>
                                <td>{{ r['first_name'] or 'N/A' }}</td>
                                <td>@{{ r['username'] or 'N/A' }}</td>
                                <td>{{ r['status'] }}</td>
                                <td>{{ r['signup_time'] }}</td>
                            </tr>
                            {% endfor %}
                            {% if not admitted %}<tr><td colspan="4">No winners yet</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>Registered (Pool)</h2>
                    <div class="table-wrap" id="registered-wrap">
                        <table>
                            <tr><th>Name</th><th>Username</th><th>Time</th></tr>
                            {% for r in registered %}
                            <tr>
                                <td>{{ r['first_name'] or 'N/A' }}</td>
                                <td>@{{ r['username'] or 'N/A' }}</td>
                                <td>{{ r['signup_time']|format_tz }}</td>
                            </tr>
                            {% endfor %}
                            {% if not registered %}<tr><td colspan="3">No registrations</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>Waitlist</h2>
                    <div class="table-wrap" id="waitlist-wrap">
                        <table>
                            <tr><th>#</th><th>Name</th><th>Username</th><th>Time</th></tr>
                            {% for r in waitlist %}
                            <tr>
                                <td>{{ r['priority'] }}</td>
                                <td>{{ r['first_name'] or 'N/A' }}</td>
                                <td>@{{ r['username'] or 'N/A' }}</td>
                                <td>{{ r['signup_time'] }}</td>
                            </tr>
                            {% endfor %}
                            {% if not waitlist %}<tr><td colspan="4">Waitlist is empty</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>Unregistered / Expired</h2>
                    <div class="table-wrap" id="unregistered-wrap">
                        <table>
                            <tr><th>Name</th><th>Username</th><th>Status</th><th>Unreg Time</th></tr>
                            {% for r in unregistered %}
                            <tr>
                                <td>{{ r['first_name'] or 'N/A' }}</td>
                                <td>{{ r['username'] or 'N/A' }}</td>
                                <td>{{ r['status'] }}</td>
                                <td>{{ r['unreg_time']|format_tz }}</td>
                            </tr>
                            {% endfor %}
                            {% if not unregistered %}<tr><td colspan="4">No unregistered users</td></tr>{% endif %}
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
    app.run(host='0.0.0.0', port=5000)

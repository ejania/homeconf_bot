import os
import sqlite3
from flask import Flask, render_template_string

app = Flask(__name__)
DB_PATH = os.getenv("DB_PATH", "bot_data.db")

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
        .status-closed { background: #f8d7da; color: #721c24; }
        .status-pre_open { background: #cce5ff; color: #004085; }
        .status-cancelled { background: #e2e3e5; color: #383d41; }
        .table-wrap { max-height: 400px; overflow-y: auto; margin-bottom: 2rem; border-bottom: 1px solid #ddd; }
        .log-wrap { max-height: 800px; overflow-y: auto; }
    </style>
    <script>
        function reloadData() {
            setTimeout(() => location.reload(), 5000);
        }
    </script>
</head>
<body onload="reloadData()">
    <div class="container">
        <h1>Admin Dashboard</h1>
        <h2>Current Event Status</h2>
        {% if not event %}
            <p>No active event found.</p>
        {% else %}
            <p style="font-size: 1.1em;">
                <strong>Event ID:</strong> {{ event.id }} &nbsp;|&nbsp; 
                <strong>Status:</strong> <span class="badge status-{{ event.status|lower }}">{{ event.status }}</span> &nbsp;|&nbsp; 
                <strong>Total Places:</strong> {{ event.total_places }}
            </p>
            
            <div class="row">
                <div class="col" style="flex: 2;">
                    
                    <h2>VIP: Speakers (Manual) ({{ speakers|length }})</h2>
                    <div class="table-wrap" style="max-height: 200px;">
                        <table>
                            <tr><th>Username</th></tr>
                            {% for s in speakers %}
                            <tr><td>@{{ s.username }}</td></tr>
                            {% endfor %}
                            {% if not speakers %}<tr><td>No manual speakers added (may be using Telegram Group)</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>VIP: Invitees (Guests) ({{ invitees|length }})</h2>
                    <div class="table-wrap">
                        <table>
                            <tr><th>Name</th><th>Username</th><th>Status</th><th>Invited By (User ID)</th></tr>
                            {% for r in invitees %}
                            <tr>
                                <td>{{ r.first_name or '-' }}</td>
                                <td>{{ r.username or '-' }}</td>
                                <td><span class="badge">{{ r.status }}</span></td>
                                <td>{{ r.guest_of_user_id }}</td>
                            </tr>
                            {% endfor %}
                            {% if not invitees %}<tr><td colspan="4">No invitees yet</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>Admitted (Lottery Winners) ({{ admitted|length }})</h2>
                    <div class="table-wrap">
                        <table>
                            <tr><th>Name</th><th>Username</th><th>Time</th></tr>
                            {% for r in admitted %}
                            <tr>
                                <td>{{ r.first_name }}</td>
                                <td>{{ r.username }}</td>
                                <td>{{ r.signup_time }}</td>
                            </tr>
                            {% endfor %}
                            {% if not admitted %}<tr><td colspan="3">No admitted users</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>Registered (Lottery Pool) ({{ registered|length }})</h2>
                    <div class="table-wrap">
                        <table>
                            <tr><th>Name</th><th>Username</th><th>Time</th></tr>
                            {% for r in registered %}
                            <tr>
                                <td>{{ r.first_name }}</td>
                                <td>{{ r.username }}</td>
                                <td>{{ r.signup_time }}</td>
                            </tr>
                            {% endfor %}
                            {% if not registered %}<tr><td colspan="3">No users in pool</td></tr>{% endif %}
                        </table>
                    </div>

                    <h2>Waitlist ({{ waitlist|length }})</h2>
                    <div class="table-wrap">
                        <table>
                            <tr><th>Priority</th><th>Name</th><th>Username</th><th>Status</th></tr>
                            {% for r in waitlist %}
                            <tr>
                                <td>{{ r.priority }}</td>
                                <td>{{ r.first_name }}</td>
                                <td>{{ r.username }}</td>
                                <td><span class="badge">{{ r.status }}</span></td>
                            </tr>
                            {% endfor %}
                            {% if not waitlist %}<tr><td colspan="4">Waitlist is empty</td></tr>{% endif %}
                        </table>
                    </div>
                </div>
                
                <div class="col" style="flex: 2;">
                    <h2>Real-time Action Logs</h2>
                    <div class="table-wrap log-wrap">
                        <table>
                            <tr><th>Time</th><th>User</th><th>Action</th><th>Details</th></tr>
                            {% for log in logs %}
                            <tr>
                                <td style="white-space: nowrap;">{{ log['timestamp'] }}</td>
                                <td>{{ log['username'] or 'System' }} {{ '(' ~ log['user_id'] ~ ')' if log['user_id'] else '' }}</td>
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
        cursor.execute("SELECT * FROM speakers WHERE event_id = ?", (event['id'],))
        speakers = cursor.fetchall()
        
        cursor.execute("SELECT * FROM registrations WHERE event_id = ? AND guest_of_user_id IS NOT NULL AND status IN ('ACCEPTED', 'INVITED', 'UNREGISTERED') ORDER BY id DESC", (event['id'],))
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

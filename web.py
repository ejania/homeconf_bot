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
        body { font-family: sans-serif; margin: 2rem; background: #f4f4f4; }
        .container { max-width: 1200px; margin: auto; background: white; padding: 2rem; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        h1, h2 { color: #333; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 2rem; font-size: 0.9em; }
        th, td { padding: 8px; border: 1px solid #ddd; text-align: left; }
        th { background: #eee; }
        .row { display: flex; gap: 2rem; }
        .col { flex: 1; }
        .badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 0.8em; background: #ddd; }
        .status-open { background: #d4edda; color: #155724; }
        .status-closed { background: #f8d7da; color: #721c24; }
        .status-pre_open { background: #cce5ff; color: #004085; }
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
        <h2>Event Status</h2>
        {% if not event %}
            <p>No active event found.</p>
        {% else %}
            <p>
                <strong>Event ID:</strong> {{ event.id }} | 
                <strong>Status:</strong> <span class="badge status-{{ event.status|lower }}">{{ event.status }}</span> | 
                <strong>Total Places:</strong> {{ event.total_places }}
            </p>
            
            <div class="row">
                <div class="col" style="flex: 2;">
                    <h2>Registrations ({{ registrations|length }})</h2>
                    <table>
                        <tr><th>Name</th><th>Username</th><th>Status</th><th>Priority</th><th>Signup Time</th></tr>
                        {% for r in registrations %}
                        <tr>
                            <td>{{ r.first_name }}</td>
                            <td>{{ r.username }}</td>
                            <td>{{ r.status }}</td>
                            <td>{{ r.priority if r.priority is not none else '-' }}</td>
                            <td>{{ r.signup_time }}</td>
                        </tr>
                        {% endfor %}
                    </table>
                </div>
                
                <div class="col" style="flex: 3;">
                    <h2>Real-time Action Logs (Latest 100)</h2>
                    <table>
                        <tr><th>Time</th><th>User</th><th>Action</th><th>Details</th></tr>
                        {% for log in logs %}
                        <tr>
                            <td>{{ log.timestamp }}</td>
                            <td>{{ log.username or 'System' }}</td>
                            <td><b>{{ log.action }}</b></td>
                            <td>{{ log.details }}</td>
                        </tr>
                        {% endfor %}
                    </table>
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
    
    # Check if table exists (to avoid errors on empty db)
    cursor.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name='events'")
    if cursor.fetchone()[0] == 0:
        return render_template_string(TEMPLATE, event=None, registrations=[], logs=[])

    cursor.execute("SELECT * FROM events ORDER BY id DESC LIMIT 1")
    event = cursor.fetchone()
    
    registrations = []
    logs = []
    
    if event:
        cursor.execute("SELECT * FROM registrations WHERE event_id = ? ORDER BY CASE status WHEN 'ACCEPTED' THEN 1 WHEN 'INVITED' THEN 2 WHEN 'WAITLIST' THEN 3 WHEN 'REGISTERED' THEN 4 ELSE 5 END, priority ASC", (event['id'],))
        registrations = cursor.fetchall()
        
        cursor.execute("SELECT * FROM action_logs WHERE event_id = ? ORDER BY id DESC LIMIT 100", (event['id'],))
        logs = cursor.fetchall()
        
    conn.close()
    return render_template_string(TEMPLATE, event=event, registrations=registrations, logs=logs)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

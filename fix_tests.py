import glob

action_logs_sql = '''        cursor.execute("""
            CREATE TABLE IF NOT EXISTS action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                user_id INTEGER,
                username TEXT,
                action TEXT,
                details TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (event_id) REFERENCES events (id)
            )
        """)
'''

for f in glob.glob("test_*.py"):
    with open(f, "r") as file:
        content = file.read()
        
    if "CREATE TABLE IF NOT EXISTS action_logs" in content:
        continue
        
    lines = content.split('\n')
    out = []
    in_setup = False
    added = False
    
    for line in lines:
        if "def setUp(self):" in line:
            in_setup = True
            
        # We look for the first commit() inside setUp()
        if in_setup and not added and line.strip().endswith("commit()"):
            out.append(action_logs_sql)
            added = True
            in_setup = False
            
        out.append(line)
        
    with open(f, "w") as file:
        file.write('\n'.join(out))

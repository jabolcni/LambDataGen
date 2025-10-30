# server.py
from flask import Flask, request, jsonify, render_template_string, send_from_directory
import uuid
import datetime
import os
import sqlite3
from pathlib import Path

app = Flask(__name__)

# === Paths ===
DB_PATH = "server_data/progress.db"
GAMES_DIR = "server_data/games"
Path(GAMES_DIR).mkdir(parents=True, exist_ok=True)

# === In-memory state ===
clients = {}
parameters = {
    # Core parameters (ACTIVE)
    "games": 1000,
    "depth": 9,
    "save_min_ply": 3,
    "save_max_ply": 400,
    "random_min_ply": 3,
    "random_50_ply": 7,
    "random_10_ply": 16,
    "random_move_count": 6,
    "skipnoisy": True,
    
    # Future parameters (GREYED OUT)
    "standard_start_pos_prob": 0.40,
    "frc_start_pos_prob": 0.33,
    "dfrc_start_pos_prob": 0.27,
    "adjudicate_draws_by_score": True,
    "adjudicate_draws_by_insufficient_mating_material": True
}
parameters_changed = True

# === SQLite DB ===
def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS clients (
        client_id TEXT PRIMARY KEY,
        name TEXT,
        ip TEXT,
        last_seen TEXT
    );
    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id TEXT,
        output_file TEXT,
        games_completed INTEGER DEFAULT 0,
        positions_completed INTEGER DEFAULT 0,
        status TEXT,
        timestamp TEXT,
        FOREIGN KEY(client_id) REFERENCES clients(client_id)
    );
    """)
    conn.commit()
    conn.close()

init_db()

def save_run_to_db(client_id, output_file, games, positions, status):
    print(f"[SERVER DEBUG] Saving to DB: client={client_id}, games={games}, positions={positions}, file={output_file}")  # ADD THIS
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO clients (client_id, name, ip, last_seen)
        VALUES (?, ?, ?, ?)
    """, (
        client_id, clients[client_id]["name"], clients[client_id]["ip"],
        datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ))
    cursor.execute("""
        INSERT INTO runs (client_id, output_file, games_completed, positions_completed, status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        client_id, output_file, games, positions, status,
        datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()

def get_latest_runs():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Simple approach: Get the most recent run for each client
    cursor.execute("""
        SELECT r.*, c.name, c.ip
        FROM runs r 
        JOIN clients c ON r.client_id = c.client_id
        WHERE r.id IN (
            SELECT MAX(id) FROM runs GROUP BY client_id
        )
        ORDER BY r.timestamp DESC
    """)
    
    rows = cursor.fetchall()
    conn.close()
    
    # Debug print to console
    print(f"[SERVER DEBUG] get_latest_runs returned {len(rows)} rows:")
    for row in rows:
        print(f"  - {row[7]}: {row[3]} games, {row[4]} positions, status: {row[5]}")
    
    return [{"client_id": row[1], "name": row[7], "ip": row[8], "output_file": row[2],
             "games": row[3], "positions": row[4], "status": row[5], "timestamp": row[6]} for row in rows]

# === HTML GUI (UPDATED) ===
HTML_GUI = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Lamb Distributed Runner</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" />
  <style>
    body { background: #f8f9fa; }
    .card { margin-bottom: 1.5rem; }
    .progress-text { font-family: monospace; }
    .copy-btn { font-size: 0.8rem; }
    .table th { font-weight: 600; }
    .future-param { background: #f0f0f0; color: #666; cursor: not-allowed; }
    .future-param input, .future-param select { background: #f0f0f0 !important; }
    .tooltip { font-size: 0.8rem; }
  </style>
</head>
<body>
<div class="container py-4">
  <h1 class="display-5 text-center mb-4">🐑 Lamb Distributed Runner</h1>

  <!-- Parameters Form -->
  <div class="card">
    <div class="card-header"><h3>Generate Parameters</h3></div>
    <div class="card-body">
      <form method="post" action="/set_parameters">
        <div class="row g-2">
          <!-- ACTIVE PARAMETERS -->
          <div class="col-md-2">
            <label class="form-label">games</label>
            <input name="games" class="form-control" value="{{ params.games }}" required>
            <div class="form-text">1000</div>
          </div>
          <div class="col-md-2">
            <label class="form-label">depth</label>
            <input name="depth" type="number" min="0" max="31" class="form-control" value="{{ params.depth }}" required>
            <div class="form-text">0-31</div>
          </div>
          <div class="col-md-2">
            <label class="form-label">save_min_ply</label>
            <input name="save_min_ply" type="number" min="0" max="31" class="form-control" value="{{ params.save_min_ply }}" required>
            <div class="form-text">0-31</div>
          </div>
          <div class="col-md-2">
            <label class="form-label">save_max_ply</label>
            <input name="save_max_ply" type="number" min="0" max="511" class="form-control" value="{{ params.save_max_ply }}" required>
            <div class="form-text">0-511</div>
          </div>
          <div class="col-md-2">
            <label class="form-label">random_min_ply</label>
            <input name="random_min_ply" type="number" min="0" max="31" class="form-control" value="{{ params.random_min_ply }}" required>
            <div class="form-text">0-31</div>
          </div>
          <div class="col-md-2">
            <label class="form-label">random_50_ply</label>
            <input name="random_50_ply" type="number" min="0" max="31" class="form-control" value="{{ params.random_50_ply }}" required>
            <div class="form-text">0-31</div>
          </div>
          <div class="col-md-2">
            <label class="form-label">random_10_ply</label>
            <input name="random_10_ply" type="number" min="0" max="255" class="form-control" value="{{ params.random_10_ply }}" required>
            <div class="form-text">0-255</div>
          </div>
          <div class="col-md-2">
            <label class="form-label">random_move_count</label>
            <input name="random_move_count" type="number" min="0" max="31" class="form-control" value="{{ params.random_move_count }}" required>
            <div class="form-text">0-31</div>
          </div>
          <div class="col-md-2">
            <label class="form-label">skipnoisy</label>
            <select name="skipnoisy" class="form-control">
              <option value="true" {% if params.skipnoisy %}selected{% endif %}>true</option>
              <option value="false" {% if not params.skipnoisy %}selected{% endif %}>false</option>
            </select>
          </div>

          <!-- FUTURE PARAMETERS (GREYED OUT) -->
          <div class="col-md-2 future-param">
            <label class="form-label">standard_start_pos_prob</label>
            <input name="standard_start_pos_prob" class="form-control" value="{{ params.standard_start_pos_prob }}" disabled>
            <div class="form-text">0.0-1.0 (future)</div>
          </div>
          <div class="col-md-2 future-param">
            <label class="form-label">frc_start_pos_prob</label>
            <input name="frc_start_pos_prob" class="form-control" value="{{ params.frc_start_pos_prob }}" disabled>
            <div class="form-text">0.0-1.0 (future)</div>
          </div>
          <div class="col-md-2 future-param">
            <label class="form-label">dfrc_start_pos_prob</label>
            <input name="dfrc_start_pos_prob" class="form-control" value="{{ params.dfrc_start_pos_prob }}" disabled>
            <div class="form-text">0.0-1.0 (future)</div>
          </div>
          <div class="col-md-2 future-param">
            <label class="form-label">adjudicate_draws_by_score</label>
            <select name="adjudicate_draws_by_score" class="form-control" disabled>
              <option value="true" {% if params.adjudicate_draws_by_score %}selected{% endif %}>true</option>
              <option value="false">false</option>
            </select>
          </div>
          <div class="col-md-2 future-param">
            <label class="form-label">adjudicate_insuf_mat</label>
            <select name="adjudicate_draws_by_insufficient_mating_material" class="form-control" disabled>
              <option value="true" {% if params.adjudicate_draws_by_insufficient_mating_material %}selected{% endif %}>true</option>
              <option value="false">false</option>
            </select>
          </div>
        </div>
        <div class="mt-3">
          <button class="btn btn-primary btn-lg">🚀 Update & Restart All Clients</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Live Status Table -->
  <div class="card">
    <div class="card-header d-flex justify-content-between align-items-center">
      <h3>📊 Live Status ({{ runs|length }} clients)</h3>
      <button class="btn btn-sm btn-outline-secondary" onclick="location.reload()">🔄 Refresh</button>
    </div>
    <div class="card-body p-0">
      <div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead class="table-light">
            <tr>
              <th>Name</th><th>IP</th><th>Updated</th><th>Status</th><th>Games</th><th>Positions</th><th>File</th>
            </tr>
          </thead>
          <tbody>
            {% for r in runs %}
            <tr>
              <td><strong>{{ r.name }}</strong></td>
              <td><code>{{ r.ip }}</code></td>
              <td>{{ r.timestamp[-8:] }}</td>
              <td class="progress-text">{{ r.status }}</td>
              <td class="text-success fw-bold">{{ "{:,}".format(r.games) }}</td>
              <td>{{ "{:,}".format(r.positions) }}</td>
              <td>
                {% if r.output_file %}
                  <div class="btn-group btn-group-sm">
                    <a href="/download/{{ r.output_file }}" class="btn btn-success">⬇️</a>
                    <button class="btn btn-outline-secondary copy-btn" onclick="copy('{{ r.output_file }}')">📋</button>
                  </div>
                {% else %}<em>-</em>{% endif %}
              </td>
            </tr>
            {% else %}
            <tr><td colspan="7" class="text-center text-muted py-4">⏳ No runs yet. Start clients!</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Stats -->
  <div class="row">
    <div class="col-md-4">
      <div class="card bg-primary text-white">
        <div class="card-body text-center">
          <h4>{{ runs|length }}</h4>
          <small>Active Clients</small>
        </div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card bg-success text-white">
        <div class="card-body text-center">
          <h4>{% set total_games=0 %}{% for r in runs %}{% set total_games=total_games+r.games %}{% endfor %}{{ "{:,}".format(total_games) }}</h4>
          <small>Total Games</small>
        </div>
      </div>
    </div>
    <div class="col-md-4">
      <div class="card bg-info text-white">
        <div class="card-body text-center">
          <h4>{% set total_pos=0 %}{% for r in runs %}{% set total_pos=total_pos+r.positions %}{% endfor %}{{ "{:,}".format(total_pos) }}</h4>
          <small>Total Positions</small>
        </div>
      </div>
    </div>
  </div>

  <div class="text-center mt-4 text-muted">
    <small>🐑 Server: <code>{{ request.host }}</code> | 💾 DB: <code>{{ db_path }}</code></small>
  </div>
</div>

<script>
function copy(text) {
  navigator.clipboard.writeText(text).then(() => {
    const btn = event.target;
    const orig = btn.innerHTML;
    btn.innerHTML = '✅';
    setTimeout(() => btn.innerHTML = orig, 1000);
  });
}
</script>
</body>
</html>
"""

# === ROUTES ===
@app.route("/")
def index():
    runs = get_latest_runs()
    return render_template_string(HTML_GUI, runs=runs, params=parameters, db_path=DB_PATH)

@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    client_id = str(uuid.uuid4())
    clients[client_id] = {
        "name": data.get("name", "unknown"),
        "ip": request.remote_addr,
        "last_seen": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),  # FIXED
        "progress": "registered"
    }
    return jsonify({"client_id": client_id})

@app.route("/parameters", methods=["GET"])
def get_parameters():
    global parameters_changed
    changed = parameters_changed
    parameters_changed = False
    return jsonify({"parameters": parameters, "changed": changed})

@app.route("/progress", methods=["POST"])
def progress():
    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id")
    
    print(f"[SERVER DEBUG] Progress update from {client_id}: {data}")  # ADD THIS
    
    if client_id and client_id in clients:
        clients[client_id].update({
            "progress": data.get("progress", "unknown"),
            "output_file": data.get("output_file"),
            "last_seen": datetime.datetime.utcnow().strftime("%H:%M:%S")
        })
        save_run_to_db(
            client_id, data.get("output_file"),
            data.get("games", 0), data.get("positions", 0),
            data.get("progress", "unknown")
        )
    return jsonify({"status": "ok"})

@app.route("/set_parameters", methods=["POST"])
def set_parameters():
    global parameters, parameters_changed
    form = request.form
    
    # Update only active parameters
    active_params = {
        "games", "depth", "save_min_ply", "save_max_ply",
        "random_min_ply", "random_50_ply", "random_10_ply", "random_move_count"
    }
    
    for key in active_params:
        if key in form:
            val = form[key].strip()
            parameters[key] = int(val)
    
    if "skipnoisy" in form:
        parameters["skipnoisy"] = form["skipnoisy"] == "true"
    
    parameters_changed = True
    return index()

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({"error": "no file"}), 400
    save_path = os.path.join(GAMES_DIR, file.filename)
    file.save(save_path)
    return jsonify({"status": "saved", "file": file.filename})

@app.route("/download/<filename>")
def download(filename):
    return send_from_directory(GAMES_DIR, filename, as_attachment=True)

@app.route("/debug_db")
def debug_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM runs ORDER BY timestamp DESC LIMIT 10")
    rows = cursor.fetchall()
    conn.close()
    
    result = "<h1>Latest Runs</h1><table border=1>"
    result += "<tr><th>ID</th><th>Client ID</th><th>File</th><th>Games</th><th>Positions</th><th>Status</th><th>Timestamp</th></tr>"
    for row in rows:
        result += f"<tr><td>{row[0]}</td><td>{row[1]}</td><td>{row[2]}</td><td>{row[3]}</td><td>{row[4]}</td><td>{row[5]}</td><td>{row[6]}</td></tr>"
    result += "</table>"
    return result

@app.route("/debug_runs")
def debug_runs():
    runs = get_latest_runs()
    result = "<h1>Current Runs in GUI</h1><table border=1>"
    result += "<tr><th>Name</th><th>Games</th><th>Positions</th><th>Status</th><th>File</th></tr>"
    for r in runs:
        result += f"<tr><td>{r['name']}</td><td>{r['games']}</td><td>{r['positions']}</td><td>{r['status']}</td><td>{r['output_file']}</td></tr>"
    result += "</table>"
    return result

if __name__ == "__main__":
    os.makedirs("templates", exist_ok=True)
    with open("templates/gui.html", "w") as f:
        f.write(HTML_GUI)
    print("🐑 Lamb Server → http://0.0.0.0:5001")
    app.run(host="0.0.0.0", port=5001, debug=False, threaded=True)
# client.py
import argparse
import requests
import json
import time
import subprocess
import multiprocessing
import socket
import datetime
import random
import string
import os
import re
from pathlib import Path

# === CLI Arguments ===
parser = argparse.ArgumentParser(description="Lamb Distributed Client")
parser.add_argument("--name", required=True, help="Unique name for this computer (e.g. node01)")
parser.add_argument("--concurrency", type=int, default=4, help="Number of parallel lamb processes")
parser.add_argument("--server", default="http://192.168.65.97:5000", help="Server URL")
args = parser.parse_args()

SERVER_URL = args.server.rstrip("/")
CONCURRENCY = args.concurrency
COMP_NAME = args.name  # ← Used everywhere
POLL_INTERVAL = 10
CLIENT_ID_FILE = Path("/tmp/lamb_client_id")
LAMB_BINARY = "./lamb"
OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(exist_ok=True)

# === Helper: Register & Get ID ===
def get_client_id():
    if CLIENT_ID_FILE.exists():
        return CLIENT_ID_FILE.read_text().strip()
    
    payload = {"name": COMP_NAME}
    r = requests.post(f"{SERVER_URL}/register", json=payload)
    cid = r.json()["client_id"]
    CLIENT_ID_FILE.write_text(cid)
    print(f"[+] Registered as {COMP_NAME} → {cid}")
    return cid

# === Fetch Parameters ===
def fetch_parameters():
    try:
        r = requests.get(f"{SERVER_URL}/parameters", timeout=5)
        r.raise_for_status()
        data = r.json()
        # Return 3 values: parameters, changed, restart_required
        return data["parameters"], data["changed"], data.get("restart_required", False)
    except Exception as e:
        print(f"[!] Param fetch error: {e}")
        # Return 3 values even on error
        return None, False, False

# === Report Progress (with games/positions) ===
def report_progress(cid, message, games=0, positions=0, output_file=None):
    payload = {
        "client_id": cid,
        "progress": message,
        "games": games,
        "positions": positions
    }
    if output_file:
        payload["output_file"] = output_file
    
    print(f"[DEBUG] Reporting progress: {message}, games={games}, positions={positions}, file={output_file}")  # ADD THIS
    
    try:
        response = requests.post(f"{SERVER_URL}/progress", json=payload, timeout=5)
        print(f"[DEBUG] Progress report response: {response.status_code}")  # ADD THIS
    except Exception as e:
        print(f"[DEBUG] Progress report failed: {e}")  # ADD THIS

# === Parse lamb Output ===
def parse_lamb_output(stdout):
    try:
        # Try multiple patterns
        patterns = [
            r"games=(\d+) positions=(\d+)",
            r"Generated (\d+) games?, (\d+) positions?",
            r"games: (\d+), positions: (\d+)"
        ]
        
        for pattern in patterns:
            m = re.search(pattern, stdout)
            if m:
                games = int(m.group(1))
                positions = int(m.group(2))
                print(f"[DEBUG] Parsed: {games} games, {positions} positions")  # Debug
                return games, positions
        
        print(f"[DEBUG] No match found in output: {stdout[:200]}...")  # Debug
        return 0, 0
        
    except Exception as e:
        print(f"[DEBUG] Parse error: {e}")
        return 0, 0

# === Upload File to Server ===
def upload_file_to_server(file_path):
    if not file_path.exists():
        print(f"[DEBUG] Upload failed: {file_path} does not exist")
        return
    try:
        print(f"[DEBUG] Attempting to upload {file_path}")
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/octet-stream")}
            r = requests.post(f"{SERVER_URL}/upload", files=files, timeout=30)
            if r.status_code == 200:
                print(f"[+] Uploaded {file_path.name}")
                # Optional: delete after successful upload to save space
                # file_path.unlink()
                # print(f"[+] Deleted local file {file_path.name}")
            else:
                print(f"[!] Upload failed with status {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[!] Upload failed: {e}")

# === Generate Unique Filename ===
def make_output_filename():
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    uniq = ''.join(random.choices(string.ascii_uppercase, k=4))
    return f"data_{now}_{COMP_NAME}_{uniq}.bin"  # ADD .bin extension

# === Run ONE Batch of lamb (called by worker) ===
def run_one_batch(params, cid):
    output_file = make_output_filename()
    output_path = OUTPUT_DIR / output_file
    
    cmd = [
        LAMB_BINARY, "datagen",
        "games", str(params["games"]),
        "depth", str(params["depth"]),
        "save_min_ply", str(params["save_min_ply"]),
        "save_max_ply", str(params["save_max_ply"]),
        "random_min_ply", str(params["random_min_ply"]),
        "random_50_ply", str(params["random_50_ply"]),
        "random_10_ply", str(params["random_10_ply"]),
        "random_move_count", str(params["random_move_count"]),
        "filename", str(output_path)
    ]
    if params["skipnoisy"]:
        cmd.append("skipnoisy")

    print(f"[DEBUG] Running command: {' '.join(cmd)}")
    
    report_progress(cid, f"starting → {output_file}")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"[DEBUG] lamb stdout: {result.stdout}")
        print(f"[DEBUG] lamb stderr: {result.stderr}")
        
        games, positions = parse_lamb_output(result.stdout)
        
        # CHECK FOR .bin EXTENSION
        output_path_bin = output_path.with_suffix('.bin')
        if output_path_bin.exists():
            print(f"[DEBUG] Found .bin file: {output_path_bin}")
            report_progress(cid, f"finished → {games} games, {positions} pos", games, positions, output_path_bin.name)
            upload_file_to_server(output_path_bin)
        elif output_path.exists():
            print(f"[DEBUG] Found file without extension: {output_path}")
            report_progress(cid, f"finished → {games} games, {positions} pos", games, positions, output_path.name)
            upload_file_to_server(output_path)
        else:
            print(f"[DEBUG] No output file found. Checking directory:")
            for f in OUTPUT_DIR.glob("*"):
                print(f"  - {f.name}")
            report_progress(cid, f"finished but no file → {games} games, {positions} pos", games, positions)
                
    except subprocess.CalledProcessError as e:
        error = f"lamb failed: {e.returncode}\n{e.stderr[-200:]}"
        print(f"[DEBUG] lamb error: {error}")
        report_progress(cid, error, 0, 0, output_file)
    except Exception as e:
        print(f"[DEBUG] Exception: {e}")
        report_progress(cid, f"error: {e}", 0, 0, output_file)

# === Worker for multiprocessing ===
def worker_task(params, cid):
    """Run batches indefinitely"""
    while True:
        try:
            run_one_batch(params, cid)
            time.sleep(1)  # Avoid CPU spin
        except Exception as e:
            report_progress(cid, f"worker crash: {e}")
            time.sleep(5)

# === Main Loop ===
def main():
    print(f"[*] Lamb Client [{COMP_NAME}] starting | Concurrency: {CONCURRENCY}")
    cid = get_client_id()
    last_params = None

    while True:
        params, changed, restart_required = fetch_parameters()  # CHANGED THIS LINE
        if params is None:
            time.sleep(POLL_INTERVAL)
            continue

        # Restart workers if params changed OR restart required
        if changed or restart_required or last_params != params:  # CHANGED THIS LINE
            if restart_required:  # CHANGED THIS LINE
                print(f"[+] Server requested restart → restarting {CONCURRENCY} workers")
                report_progress(cid, f"server restart → {CONCURRENCY} workers")
            else:
                print(f"[+] Parameters changed → restarting {CONCURRENCY} workers")
                report_progress(cid, f"parameters changed → {CONCURRENCY} workers")
            
            last_params = params.copy()

            # Kill old pool and start new
            try:
                # Use a simpler approach - create processes directly
                processes = []
                for i in range(CONCURRENCY):
                    p = multiprocessing.Process(target=worker_task, args=(params, cid))
                    p.daemon = True
                    p.start()
                    processes.append(p)
                    print(f"[DEBUG] Started worker process {i+1}")
                
                # Wait a bit to see if processes start
                time.sleep(2)
                
                # Check if processes are still alive
                alive_count = sum(1 for p in processes if p.is_alive())
                print(f"[DEBUG] {alive_count}/{CONCURRENCY} workers alive")
                
            except Exception as e:
                print(f"[!] Error starting workers: {e}")
                report_progress(cid, f"worker start error: {e}")

        else:
            report_progress(cid, "waiting for parameter change")

        time.sleep(POLL_INTERVAL)

# === Entry Point ===
if __name__ == "__main__":
    if not os.path.isfile(LAMB_BINARY):
        print(f"[!] {LAMB_BINARY} not found!")
        exit(1)
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Client stopped by user")
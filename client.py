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
        return data["parameters"], data["changed"]
    except Exception as e:
        print(f"[!] Param fetch error: {e}")
        return None, False

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
    try:
        requests.post(f"{SERVER_URL}/progress", json=payload, timeout=5)
    except:
        pass  # Silent fail

# === Parse lamb Output ===
def parse_lamb_output(stdout):
    m = re.search(r"Generated (\d+) games?, (\d+) positions?", stdout)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 0, 0

# === Upload File to Server ===
def upload_file_to_server(file_path):
    if not file_path.exists():
        return
    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/octet-stream")}
            r = requests.post(f"{SERVER_URL}/upload", files=files, timeout=30)
            if r.status_code == 200:
                print(f"[+] Uploaded {file_path.name}")
                # Optional: delete after upload
                # file_path.unlink()
    except Exception as e:
        print(f"[!] Upload failed: {e}")

# === Generate Unique Filename ===
def make_output_filename():
    now = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    uniq = ''.join(random.choices(string.ascii_uppercase, k=4))
    return f"data_{now}_{COMP_NAME}_{uniq}"

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
        str(output_path)
    ]
    if params["skipnoisy"]:
        cmd.append("skipnoisy")

    report_progress(cid, f"starting → {output_file}")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        games, positions = parse_lamb_output(result.stdout)
        report_progress(cid, f"finished → {games} games, {positions} pos", games, positions, output_file)
        upload_file_to_server(output_path)
    except subprocess.CalledProcessError as e:
        error = f"lamb failed: {e.returncode}\n{e.stderr[-200:]}"
        report_progress(cid, error, 0, 0, output_file)
    except Exception as e:
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
        params, changed = fetch_parameters()
        if params is None:
            time.sleep(POLL_INTERVAL)
            continue

        # Restart workers if params changed
        if changed or last_params != params:
            print(f"[+] Parameters changed → restarting {CONCURRENCY} workers")
            report_progress(cid, f"restarting {CONCURRENCY} workers")
            last_params = params.copy()

            # Kill old pool and start new
            with multiprocessing.Pool(processes=CONCURRENCY) as pool:
                try:
                    pool.starmap_async(worker_task, [(params, cid)] * CONCURRENCY)
                    pool.close()
                    pool.join()  # Wait for all to finish (they won't — infinite)
                except KeyboardInterrupt:
                    pool.terminate()
                    break
                except Exception as e:
                    report_progress(cid, f"pool error: {e}")

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
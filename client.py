# client.py (Corrected)
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
import shutil
from pathlib import Path
import hashlib # Import hashlib for file hashing

# === CLI Arguments ===
parser = argparse.ArgumentParser(description="Lamb Distributed Client")
parser.add_argument("--name", required=True, help="Unique name for this computer (e.g. node01)")
parser.add_argument("--concurrency", type=int, default=4, help="Number of parallel lamb processes")
parser.add_argument("--server", default="http://192.168.65.97:5000", help="Server URL")
parser.add_argument("--engine-path", default="./lamb", help="Path to the lamb executable (default: ./lamb)")
# Add flag to force fresh registration
parser.add_argument("--fresh-registration", action='store_true', help="Delete stored client ID and register as a new client on startup.")
args = parser.parse_args()

SERVER_URL = args.server.rstrip("/")
CONCURRENCY = args.concurrency
COMP_NAME = args.name  # ← Used everywhere
POLL_INTERVAL = 10
CLIENT_ID_FILE = Path("/tmp/lamb_client_id")
LAMB_BINARY = Path(args.engine_path) # Use the argument value
LAMB_HASH_FILE = Path("/tmp/lamb_engine_hash.txt") # File to store the known server hash
OUTPUT_DIR = Path("data")
OUTPUT_DIR.mkdir(exist_ok=True)

def calculate_file_hash(filepath):
    """Calculate the SHA256 hash of a file."""
    if not filepath.exists():
        print(f"[CLIENT DEBUG] File {filepath} does not exist for hashing.")
        return None
    try:
        with open(filepath, "rb") as f:
            file_hash = hashlib.sha256()
            for chunk in iter(lambda: f.read(4096), b""):
                file_hash.update(chunk)
        return file_hash.hexdigest()
    except Exception as e:
        print(f"[CLIENT DEBUG] Error calculating hash for {filepath}: {e}")
        return None

def ensure_engine_exists():
    """Check the server's engine hash and update frequency, then download the engine if necessary."""
    print(f"[INFO] Initiating engine check/update from server...")
    # CORRECTED: Fetch 4 values
    params, _, _, server_engine_hash = fetch_parameters() # Fetch parameters to get hash and frequency

    if params is None:
        print("[!] Warning: Could not fetch parameters from server. Attempting to use local engine if it exists.")
        if LAMB_BINARY.exists():
             try:
                 LAMB_BINARY.chmod(0o755)
                 print(f"[+] Set executable permissions for local {LAMB_BINARY}")
                 return # Assume local version is okay if server is unreachable
             except Exception as e:
                 print(f"[!] Error setting permissions for local {LAMB_BINARY}: {e}")
                 exit(1)
        else:
            print(f"[!] Error: Engine {LAMB_BINARY} does not exist locally and server parameters fetch failed.")
            exit(1)

    update_frequency = params.get("engine_update_frequency", "always") # Default to "always"

    print(f"[CLIENT DEBUG] Server engine hash: {server_engine_hash[:16] if server_engine_hash else 'None'}... | Frequency: {update_frequency}")

    should_update = False
    local_engine_exists = LAMB_BINARY.exists()

    if update_frequency == "never":
        print(f"[INFO] Engine update frequency is 'never'. Skipping update check.")
        if local_engine_exists:
            # Ensure it's executable if it exists
            try:
                LAMB_BINARY.chmod(0o755)
                print(f"[+] Set executable permissions for local {LAMB_BINARY}")
            except Exception as e:
                print(f"[!] Error setting permissions for local {LAMB_BINARY}: {e}")
                exit(1)
        else:
            print(f"[!] Error: Engine update frequency is 'never' but {LAMB_BINARY} does not exist locally.")
            exit(1)
        return # Exit early, no update needed

    if update_frequency == "always":
        print(f"[INFO] Engine update frequency is 'always'. Checking for update.")
        should_update = True # Always check if hash changed when frequency is 'always'
    elif update_frequency == "once_a_day":
        print(f"[INFO] Engine update frequency is 'once_a_day'. Checking for update.")
        # Check if the last update was more than 24 hours ago
        if LAMB_HASH_FILE.exists():
            try:
                stored_hash_time_str = LAMB_HASH_FILE.read_text().strip()
                # Expected format: "hash|timestamp_iso"
                parts = stored_hash_time_str.split("|", 1)
                if len(parts) == 2:
                    stored_hash, stored_time_str = parts
                    stored_time = datetime.datetime.fromisoformat(stored_time_str.replace("Z", "+00:00"))
                    now = datetime.datetime.now(datetime.timezone.utc)
                    if now - stored_time < datetime.timedelta(days=1):
                        print(f"[INFO] Last update check was less than a day ago. Skipping check.")
                        # If the local file exists and the hash matches the *stored* one, we can potentially skip.
                        if local_engine_exists:
                            local_hash = calculate_file_hash(LAMB_BINARY)
                            if local_hash and local_hash == stored_hash:
                                print(f"[INFO] Local engine hash matches stored hash from less than a day ago. Assuming up-to-date.")
                                try:
                                    LAMB_BINARY.chmod(0o755)
                                    print(f"[+] Set executable permissions for local {LAMB_BINARY}")
                                except Exception as e:
                                    print(f"[!] Error setting permissions for local {LAMB_BINARY}: {e}")
                                    exit(1)
                                return # Exit early, no update needed based on stored info
                            else:
                                print(f"[INFO] Local engine hash differs from stored hash, or local file doesn't exist. Proceeding with check/download.")
                        else:
                            print(f"[INFO] Local engine file missing. Proceeding with check/download.")
                    else:
                        print(f"[INFO] Last update check was more than a day ago. Proceeding with check/download.")
                        should_update = True
                else:
                    print(f"[WARNING] Invalid format in {LAMB_HASH_FILE}. Proceeding with check/download.")
                    should_update = True
            except ValueError as e:
                print(f"[WARNING] Could not parse timestamp in {LAMB_HASH_FILE}: {e}. Proceeding with check/download.")
                should_update = True
            except Exception as e:
                print(f"[WARNING] Error reading {LAMB_HASH_FILE}: {e}. Proceeding with check/download.")
                should_update = True
        else:
            print(f"[INFO] No previous update timestamp found. Proceeding with check/download.")
            should_update = True
    else:
        print(f"[WARNING] Unknown engine_update_frequency '{update_frequency}'. Defaulting to 'always'.")
        should_update = True # Default to checking if unknown

    # If we decide to update based on frequency rules
    if should_update:
        # Get the hash stored locally (if any)
        stored_hash = None
        if LAMB_HASH_FILE.exists():
            stored_hash = LAMB_HASH_FILE.read_text().strip().split("|", 1)[0] # Get just the hash part

        print(f"[CLIENT DEBUG] Stored hash: {stored_hash[:16] if stored_hash else 'None'}... | Server hash: {server_engine_hash[:16] if server_engine_hash else 'None'}...")

        # Compare hashes if both are available
        if server_engine_hash and stored_hash:
            if server_engine_hash != stored_hash:
                print(f"[INFO] Server engine hash differs from stored hash. Downloading new version.")
                success = download_engine_from_server()
                if success:
                    # Update the stored hash file with the new hash and current time
                    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    LAMB_HASH_FILE.write_text(f"{server_engine_hash}|{now_str}")
                    print(f"[+] Updated stored engine hash file: {LAMB_HASH_FILE}")
                else:
                    print(f"[!] Failed to download new engine version. Keeping old version if it exists.")
                    if local_engine_exists:
                        try:
                            LAMB_BINARY.chmod(0o755)
                            print(f"[+] Set executable permissions for local {LAMB_BINARY}")
                        except Exception as e:
                            print(f"[!] Error setting permissions for local {LAMB_BINARY}: {e}")
                            exit(1)
            else:
                print(f"[INFO] Server engine hash matches stored hash. No update needed.")
                if local_engine_exists:
                    try:
                        LAMB_BINARY.chmod(0o755)
                        print(f"[+] Set executable permissions for local {LAMB_BINARY}")
                    except Exception as e:
                        print(f"[!] Error setting permissions for local {LAMB_BINARY}: {e}")
                        exit(1)
                else:
                    # This shouldn't happen if stored hash exists, but handle it
                    print(f"[!] Error: Stored hash exists but local engine file {LAMB_BINARY} is missing.")
                    exit(1)
        elif server_engine_hash:
            # No stored hash, but server has one -> download
            print(f"[INFO] No stored hash found, but server has one. Downloading engine.")
            success = download_engine_from_server()
            if success:
                # Update the stored hash file with the new hash and current time
                now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
                LAMB_HASH_FILE.write_text(f"{server_engine_hash}|{now_str}")
                print(f"[+] Updated stored engine hash file: {LAMB_HASH_FILE}")
            else:
                print(f"[!] Failed to download engine.")
                if local_engine_exists:
                    try:
                        LAMB_BINARY.chmod(0o755)
                        print(f"[+] Set executable permissions for local {LAMB_BINARY}")
                    except Exception as e:
                        print(f"[!] Error setting permissions for local {LAMB_BINARY}: {e}")
                        exit(1)
                else:
                    print(f"[!] Error: Engine {LAMB_BINARY} does not exist locally and server download failed.")
                    exit(1)
        else:
            # Server has no hash (no engine file?)
            print(f"[WARNING] Server did not provide an engine hash. Cannot verify local engine.")
            if local_engine_exists:
                try:
                    LAMB_BINARY.chmod(0o755)
                    print(f"[+] Set executable permissions for local {LAMB_BINARY}")
                except Exception as e:
                    print(f"[!] Error setting permissions for local {LAMB_BINARY}: {e}")
                    exit(1)
            else:
                print(f"[!] Error: Engine {LAMB_BINARY} does not exist locally and server has no hash.")
                exit(1)
    else:
        # Update frequency rules said not to update, but ensure local file exists and is executable
        if local_engine_exists:
            try:
                LAMB_BINARY.chmod(0o755)
                print(f"[+] Set executable permissions for local {LAMB_BINARY}")
            except Exception as e:
                print(f"[!] Error setting permissions for local {LAMB_BINARY}: {e}")
                exit(1)
        else:
            print(f"[!] Error: Engine {LAMB_BINARY} does not exist locally.")
            exit(1)


def download_engine_from_server():
    """Download the lamb executable from the server."""
    try:
        download_url = f"{SERVER_URL}/download_engine"
        print(f"[DEBUG] Attempting to download engine from: {download_url}")
        response = requests.get(download_url, timeout=30)
        response.raise_for_status() # Raise an exception for bad status codes (4xx, 5xx)

        # Ensure the directory for the binary exists
        LAMB_BINARY.parent.mkdir(parents=True, exist_ok=True)

        # Write the binary content to the specified path
        with open(LAMB_BINARY, 'wb') as f:
            f.write(response.content)

        print(f"[+] Downloaded engine to {LAMB_BINARY}")
        return True

    except requests.exceptions.RequestException as e:
        print(f"[!] Error downloading engine from server: {e}")
        return False
    except Exception as e:
        print(f"[!] Unexpected error during engine download: {e}")
        return False


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

# === Fetch Parameters (Updated) ===
def fetch_parameters():
    try:
        r = requests.get(f"{SERVER_URL}/parameters", timeout=5)
        r.raise_for_status()
        data = r.json()
        # Return 4 values: parameters (including engine_hash), changed, restart_required, engine_hash
        params = data.get("parameters", {})
        engine_hash = data.get("engine_hash") # Extract engine hash from response
        # Include engine_hash in the main params dict for easy access if needed elsewhere
        # Or keep it separate. Let's keep it separate for clarity.
        return params, data.get("changed", False), data.get("restart_required", False), engine_hash
    except Exception as e:
        print(f"[!] Param fetch error: {e}")
        # Return 4 values even on error, with engine_hash as None
        return None, False, False, None

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
        lines = stdout.split('\n')

        # Priority 1: Look for final summary line
        summary_line = None
        for line in lines:
            if "datagen summary" in line:
                summary_line = line
                break

        # Priority 2: If no summary, use the last progress line
        if not summary_line:
            progress_lines = [line for line in lines if "datagen progress" in line]
            if progress_lines:
                summary_line = progress_lines[-1]  # Last progress line

        # Priority 3: If still nothing, use any line with games/positions
        if not summary_line:
            for line in lines:
                if "games=" in line and "positions=" in line:
                    summary_line = line
                    break

        if summary_line:
            print(f"[DEBUG] Using line for parsing: {summary_line.strip()}")

            # Extract games and positions
            m = re.search(r"games=(\d+)", summary_line)
            n = re.search(r"positions=(\d+)", summary_line)

            if m and n:
                games = int(m.group(1))
                positions = int(n.group(1))
                print(f"[DEBUG] Successfully parsed: {games} games, {positions} positions")
                return games, positions

        print(f"[DEBUG] Could not parse games/positions from output")
        print(f"[DEBUG] Output sample: {stdout[:300]}...")
        return 0, 0

    except Exception as e:
        print(f"[DEBUG] Parse error: {e}")
        print(f"[DEBUG] Output that caused error: {stdout[:500]}")
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
        str(LAMB_BINARY.absolute()), # Convert Path to absolute string path (Fixed)
        "datagen",
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
        # Include the command that failed in the error report
        report_progress(cid, f"error running command '{' '.join(cmd)}': {e}", 0, 0, output_file)

# === Worker for multiprocessing ===
def worker_task(current_params, cid):
    """Run batches indefinitely, checking for new parameters each time"""
    while True:
        try:
            # Get latest parameters for this batch
            # CORRECTED: Fetch 4 values
            params, changed, restart_required, _ = fetch_parameters() # Ignore engine_hash here
            if params is None:
                # If fetch failed, use the current params
                params = current_params
            else:
                # Update our current params
                current_params = params.copy()

            run_one_batch(params, cid)
            time.sleep(1)  # Brief pause between batches
        except Exception as e:
            report_progress(cid, f"worker crash: {e}")
            time.sleep(5)

def cleanup_old_files(folder_path="data", max_size_gb=4, min_size_gb=2):
    """
    Remove oldest files when folder exceeds max_size_gb,
    but keep at least min_size_gb of data
    """
    try:
        folder = Path(folder_path)
        if not folder.exists():
            return

        # Get all .bin files with their modification times
        bin_files = [(f, f.stat().st_mtime) for f in folder.glob("*.bin")]

        if not bin_files:
            return

        # Calculate current folder size
        total_size = sum(f.stat().st_size for f, _ in bin_files)
        max_size_bytes = max_size_gb * 1024 * 1024 * 1024  # Convert GB to bytes
        min_size_bytes = min_size_gb * 1024 * 1024 * 1024  # Convert GB to bytes

        print(f"[CLEANUP] Current folder size: {total_size / (1024**3):.2f}GB")

        # If under max size, do nothing
        if total_size <= max_size_bytes:
            return

        # Sort files by modification time (oldest first)
        bin_files.sort(key=lambda x: x[1])

        # Remove oldest files until we're below min size
        removed_count = 0
        removed_size = 0

        for file_path, _ in bin_files:
            if total_size - removed_size <= min_size_bytes:
                break

            file_size = file_path.stat().st_size
            try:
                file_path.unlink()  # Delete the file
                removed_count += 1
                removed_size += file_size
                print(f"[CLEANUP] Removed old file: {file_path.name} ({file_size / (1024**2):.1f}MB)")
            except Exception as e:
                print(f"[CLEANUP] Error removing {file_path.name}: {e}")

        if removed_count > 0:
            print(f"[CLEANUP] Removed {removed_count} files, freed {removed_size / (1024**3):.2f}GB")
            print(f"[CLEANUP] New folder size: {(total_size - removed_size) / (1024**3):.2f}GB")

    except Exception as e:
        print(f"[CLEANUP] Error during cleanup: {e}")

# === Main Loop ===
def main():
    print(f"[*] Lamb Client [{COMP_NAME}] starting | Concurrency: {CONCURRENCY}")
    print(f"[*] Engine Path: {LAMB_BINARY}")

    # ADD: Handle fresh registration flag
    if args.fresh_registration:
        print(f"[INFO] --fresh-registration flag set. Deleting stored client ID: {CLIENT_ID_FILE}")
        if CLIENT_ID_FILE.exists():
            CLIENT_ID_FILE.unlink() # Delete the file
            print(f"[+] Deleted {CLIENT_ID_FILE}")
        else:
            print(f"[INFO] No stored client ID file {CLIENT_ID_FILE} to delete.")

        # Also delete the stored engine hash when fresh registration is forced
        print(f"[INFO] --fresh-registration flag set. Deleting stored engine hash: {LAMB_HASH_FILE}")
        if LAMB_HASH_FILE.exists():
            LAMB_HASH_FILE.unlink() # Delete the file
            print(f"[+] Deleted {LAMB_HASH_FILE}")
        else:
            print(f"[INFO] No stored engine hash file {LAMB_HASH_FILE} to delete.")


    # Ensure the engine exists and is executable before proceeding
    ensure_engine_exists()

    cid = get_client_id() # This will register if the ID file was deleted or doesn't exist
    current_params = None
    pool = None
    cleanup_counter = 0

    while True:
        # CORRECTED: Fetch 4 values
        params, changed, restart_required, _ = fetch_parameters() # Ignore engine_hash here
        if params is None:
            time.sleep(POLL_INTERVAL)
            continue

        # If no workers running, start them with current parameters
        if pool is None:
            print(f"[+] Starting {CONCURRENCY} workers with {params['games']} games")
            report_progress(cid, f"starting {CONCURRENCY} workers")
            current_params = params.copy()

            try:
                pool = multiprocessing.Pool(processes=CONCURRENCY)
                for i in range(CONCURRENCY):
                    pool.apply_async(worker_task, (current_params, cid))
                print(f"[DEBUG] Started {CONCURRENCY} workers")
            except Exception as e:
                print(f"[!] Error starting workers: {e}")
                report_progress(cid, f"start error: {e}")
                pool = None

        # If parameters changed but we have running workers, just update for next run
        elif changed and current_params != params:
            print(f"[+] Parameters updated: {params['games']} games (will use after current batches)")
            report_progress(cid, f"parameters updated → {params['games']} games next")
            current_params = params.copy()

        else:
            # Normal operation - workers are running
            report_progress(cid, f"running {CONCURRENCY} workers")

        # Run cleanup every N iterations
        cleanup_counter += 1
        if cleanup_counter >= (24*60*60/POLL_INTERVAL):
            cleanup_old_files()
            cleanup_counter = 0

        time.sleep(POLL_INTERVAL)

# === Entry Point ===
if __name__ == "__main__":
    # Note: Removed the initial check for LAMB_BINARY existence
    # as ensure_engine_exists() handles this now.
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Client stopped by user")

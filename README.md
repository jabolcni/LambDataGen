# Lamb Distributed DataGen Runner

This is code for server and client for runing datagen for Lambergar.

**Prerequisites:**
*   Python 3.8+
*   The `lamb` executable binary must be present in the working directory for `client.py`.
*   Network connectivity between client and server machines.

## Repository structure

```text
lamb-distributed/
├── server.py
├── client.py
├── lamb                # ← Lambergar binary (executable)
├── data/               # ← client output files
├── server_data/        # ← server stores DB + received files
│   ├── progress.db     # ← SQLite DB
│   └── games/          # ← stores .bin files from clients
├── lamb-documentation.html
├── lamb-client.service 
└── README.md
```

- `server.py`: The central server application. It runs a Flask web server, manages client connections, stores progress in an SQLite database, serves the web GUI, and receives `.bin` files from clients.
- `client.py`: The client application. Runs on worker machines, communicates with the server, fetches parameters, executes the lamb datagen command via subprocess, parses its output, reports progress, and uploads the generated `.bin` files.
- `lamb`: The Lambergar chess engine executable binary. This file needs to be present in the working directory for `client.py` to run the datagen command. It's platform-specific (e.g., a Linux executable if running on Linux).
- `data/`: The directory on the client machine where the client temporarily stores the `.bin` files it generates before uploading them to the server. The cleanup logic in `client.py` operates on this directory.
- `server_data/`: The directory on the server machine for persistent data.
  - `progress.db`: The SQLite database file storing information about clients and their runs (games, positions, status, etc.).
  - `games/`: The directory on the server where the `.bin` files uploaded by clients are stored permanently.
- `lamb-documentation.html`: An HTML file containing the documentation.
- `lamb-client.service`: This is a `systemd` service unit file (common on Linux systems). It's used to manage the `client.py` script as a system service. This means you can use commands like `systemctl start lamb-client.service`, `systemctl stop lamb-client.service`, `systemctl enable lamb-client.service` (to start automatically on boot), and `systemctl status lamb-client.service`. It provides a way to run the client reliably in the background, automatically restart it if it crashes, and manage its lifecycle using standard system tools.
Purpose: To ensure the client runs continuously without needing to keep a terminal session open, and to integrate it into the system's service management framework.
- `README.md`: A standard markdown file providing information about the project, how to set it up, and how to use it.

## How to run Server on WSL

In Windows open PowerShell

```powershell
wsl -l -v

# Allow inbound traffic on port 5001
New-NetFirewallRule -DisplayName "WSL Flask Server" -Direction Inbound -LocalPort 5001 -Protocol TCP -Action Allow

# Forward port from Windows to WSL (replace 'Ubuntu' with your WSL distro name)
netsh interface portproxy add v4tov4 listenport=5001 listenaddress=0.0.0.0 connectport=5001 connectaddress=172.29.99.188

netsh interface portproxy show all
```

On WSL run

```bash
git clone https://github.com/jabolcni/LambDataGen.git
cd LambDataGen
sudo apt install python3.8-venv
python3 -m venv lamb-dist

# 1. Delete broken DB
rm -f server_data/progress.db

# 2. Run server
source lamb-dist/bin/activate
python server.py
```

## How to run Client

### First time

```bash
git clone https://github.com/jabolcni/LambDataGen.git
cd LambDataGen
sudo apt install python3.8-venv
python3 -m venv lamb-dist
source lamb-dist/bin/activate
pip install flask requests
chmod +x lamb
python client.py --name node02 --concurrency 8 --server http://192.168.65.97:5001
```

Example
```bash
python client.py --name rl_otok9 --concurrency 12 --server http://192.168.65.97:5001
```

### Auto-Restart on Crash (systemd)

Create `/etc/systemd/system/lamb-client.service` on each worker:

Enable & start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable lamb-client.service
sudo systemctl start lamb-client.service
```

Now it ***auto-restarts*** on crash, reboot, or failure.

## How to run web GUI

### Parameter Configuration

* URL: `http://<server_ip>:5001/set_parameters`
* Description: The main dashboard showing live status, parameters, and statistics. This is the primary interface for monitoring the distributed runner. Access the parameter form to configure settings like `games`, `depth`, `save_min_ply`, etc., for the `lamb datagen` commands.
* Example: `http://172.29.99.188:5001/set_parameters`

### Debug Endpoints

* URL: `http://<server_ip>:5001/debug_runs`
  * Description: View the latest run data aggregated per client from the database.
  * Example: `http://172.29.99.188:5001/debug_runs`
* URL: `http://<server_ip>:5001/debug_clients`
  * Description: View the current list of registered clients held in the server's memory.
  * Example: `http://172.29.99.188:5001/debug_clients`
* URL: `http://<server_ip>:5001/debug_db`
  * Description: View the 10 most recent entries from the `runs` table in the SQLite database.
* URL: `http://<server_ip>:5001/debug_db_full`
  * Description: View the 20 most recent entries from the `runs` table in the SQLite database.
* URL: `http://<server_ip>:5001/debug_db_status`
  * Description: View the status of the SQLite database file (existence, size, row counts).

*Replace `<server_ip>` with the IP address of your machine running `server.py`.*

## Troubleshooting 

* Client cannot connect to Server: Check firewall settings on both client and server. Ensure the server IP and port (5001) are correct and accessible. Verify network connectivity (e.g., `ping <server_ip>`).
* `lamb` executable not found: Ensure `./lamb` exists in the `LambDataGen` directory and is executable (`chmod +x lamb`).
* High CPU usage or suboptimal performance: By default, the client relies on the OS scheduler for `lamb` processes. Affinity was tested but not recommended due to `lamb`'s internal threading.
* Database errors: Check `server_data/progress.db` permissions and integrity. Deleting the file will reset statistics (requires server restart).

## License

MIT as always.

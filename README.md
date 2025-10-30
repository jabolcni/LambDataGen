# DataGen

This is code for server and client for runing datagen for Lambergar.

Repository structure

```text
lamb-distributed/
├── server.py
├── client.py
├── lamb                # ← Lambergar binary (executable)
├── templates/
│   └── gui.html
├── data/               # ← client output files
├── server_data/        # ← server stores DB + received files
│   ├── progress.db     # ← SQLite DB
│   └── games/          # ← stores .bin files from clients
├── lamb-documentation.html
├── lamb-client.service # What is this and what for is needed?
├── lamb-dist/          # What is this folder for?
└── README.md
```

- `server.py`: The central server application. It runs a Flask web server, manages client connections, stores progress in an SQLite database, serves the web GUI, and receives .bin files from clients.
- `client.py`: The client application. Runs on worker machines, communicates with the server, fetches parameters, executes the lamb datagen command via subprocess, parses its output, reports progress, and uploads the generated .bin files.
- `lamb`: The Lambergar chess engine executable binary. This file needs to be present in the working directory for client.py to run the datagen command. It's likely platform-specific (e.g., a Linux executable if running on Linux).
- `templates/`: Directory for Flask templates (though it seems gui.html is embedded as a string in server.py currently, this directory might be a remnant or for future use).
    - `gui.html`: The HTML template for the web GUI (currently embedded in server.py).
         
- `data/`: The directory on the client machine where the client temporarily stores the .bin files it generates before uploading them to the server. The cleanup logic in client.py operates on this directory.
- server_data/: The directory on the server machine for persistent data.
    - progress.db: The SQLite database file storing information about clients and their runs (games, positions, status, etc.).
    - games/: The directory on the server where the .bin files uploaded by clients are stored permanently.
         
- lamb-documentation.html: An HTML file containing the documentation you provided earlier.
- lamb-client.service: This is a systemd service unit file (common on Linux systems). It's used to manage the client.py script as a system service. This means you can use commands like systemctl start lamb-client.service, systemctl stop lamb-client.service, systemctl enable lamb-client.service (to start automatically on boot), and systemctl status lamb-client.service. It provides a way to run the client reliably in the background, automatically restart it if it crashes, and manage its lifecycle using standard system tools.
Purpose: To ensure the client runs continuously without needing to keep a terminal session open, and to integrate it into the system's service management framework.
         
- lamb-dist/: This folder name suggests it might be intended to contain distribution-related files, scripts, or configurations for deploying the distributed system (e.g., configuration files for multiple clients, deployment scripts, perhaps different versions of the lamb binary for different platforms if needed for a distributed setup, etc.). However, based on the structure provided, it seems empty or its specific purpose isn't detailed here. It could also be a general project folder or a name that doesn't reflect its current content.
- README.md: A standard markdown file providing information about the project, how to set it up, and how to use it.
     


## How to run Server on WSL

In Windows open powershell

```powershell

wsl -l -v

# Allow inbound traffic on port 5001
New-NetFirewallRule -DisplayName "WSL Flask Server" -Direction Inbound -LocalPort 5001 -Protocol TCP -Action Allow

# Forward port from Windows to WSL (replace 'Ubuntu' with your WSL distro name)
netsh interface portproxy add v4tov4 listenport=5001 listenaddress=0.0.0.0 connectport=5001 connectaddress=172.29.99.188

netsh interface portproxy show all
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

# License

MIT as always.

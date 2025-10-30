# DataGen

This is code for server and client for runing datagen for Lambergar.

## How to run Server on WSL

Open powershell

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
python3 -m venv lamb-dist
source lamb-dist/bin/activate
pip install flask requests
chmod +x lamb
python client.py --name node02 --concurrency 8 --server http://192.168.65.97:5001
```

Example
```bash
python client.py --name rl_pop --concurrency 4 --server http://192.168.65.97:5001
```

python client.py --name rl_pop --concurrency 4 --server http://192.168.65.97:5001

# License

MIT as always.

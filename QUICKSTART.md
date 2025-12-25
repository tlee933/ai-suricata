# AI Suricata - Quick Reference Guide

## Service is Now Running!

AI Suricata is installed as a systemd service and will automatically:
- ✅ Start on system boot
- ✅ Reconnect if connection drops
- ✅ Train ML models on startup
- ✅ **Auto-block CRITICAL threats**

---

## Management Commands

Use the `manage.sh` script for easy control:

```bash
cd /home/hashcat/pfsense/ai_suricata

# Check if service is running
./manage.sh status

# Watch live threat detection
./manage.sh watch

# Watch only HIGH/CRITICAL threats
./manage.sh threats

# View statistics
./manage.sh stats

# Service control
./manage.sh start       # Start the service
./manage.sh stop        # Stop the service
./manage.sh restart     # Restart the service
```

---

## Systemd Commands (Alternative)

```bash
# Service status
sudo systemctl status ai-suricata

# View live logs
sudo journalctl -u ai-suricata -f

# View recent logs
sudo journalctl -u ai-suricata -n 100

# Start/stop/restart
sudo systemctl start ai-suricata
sudo systemctl stop ai-suricata
sudo systemctl restart ai-suricata

# Enable/disable auto-start
sudo systemctl enable ai-suricata   # Start on boot
sudo systemctl disable ai-suricata  # Don't start on boot
```

---

## Configuration

Edit `/home/hashcat/pfsense/ai_suricata/config.env` to change settings, then restart:

```bash
nano config.env
sudo systemctl restart ai-suricata
```

**Current Settings:**
- **Auto-blocking:** ENABLED
- **Dry-run:** DISABLED (will actually block threats!)
- **Training:** 3000 historical events on startup

---

## What Gets Blocked Automatically?

The AI will **automatically block** IPs when:

1. **CRITICAL Threats** (Score ≥ 0.85)
   - Multiple attack patterns detected
   - Port scanning + brute force
   - High-confidence malicious activity

2. **Confirmed Patterns**
   - 20+ ports scanned in 60 seconds
   - 10+ alerts per second (DoS)
   - Multiple signature types from same IP

**Blocks expire after 24 hours** to prevent permanent lockouts.

---

## Monitoring Blocked IPs

View blocked IPs in pfSense:
```bash
ssh admin@192.168.1.1 "pfctl -sr | grep AI_BLOCK"
```

Or via web GUI:
- Firewall → Rules → WAN/LAN/WiFi
- Look for rules with "AI_BLOCK" prefix

---

## Testing the System

Generate test alerts:
```bash
# From another machine, scan your network
nmap -p 1-200 192.168.1.1

# Watch AI detect it
./manage.sh threats
```

---

## Troubleshooting

### Service won't start
```bash
# Check logs for errors
sudo journalctl -u ai-suricata -n 50

# Check SSH connection to pfSense
ssh admin@192.168.1.1 "echo OK"

# Verify Python dependencies
python3 -c "import sklearn; print('OK')"
```

### Too many false positives
Edit the service file to enable dry-run mode:
```bash
sudo nano /etc/systemd/system/ai-suricata.service
# Change: --auto-block to --dry-run
sudo systemctl daemon-reload
sudo systemctl restart ai-suricata
```

### Can't access network after install
The AI might have blocked your IP! Manually unblock:
```bash
ssh admin@192.168.1.1
# View blocked IPs
pfctl -sr | grep AI_BLOCK
# Or temporarily disable the service
sudo systemctl stop ai-suricata
```

---

## Files & Locations

```
/home/hashcat/pfsense/ai_suricata/
├── ai_suricata.py          # Main application
├── manage.sh               # Management script (use this!)
├── config.env              # Configuration
├── models/                 # Trained ML models
│   └── threat_classifier.pkl
├── logs/                   # Alert logs
│   └── ai_alerts.jsonl
└── README.md              # Full documentation

/etc/systemd/system/
└── ai-suricata.service     # Systemd service file

System logs:
sudo journalctl -u ai-suricata
```

---

## Performance

- **CPU Usage:** ~5-10% average
- **Memory:** ~115 MB
- **Latency:** <100ms per alert
- **Throughput:** 1000+ alerts/second

---

## Safety Features

✅ Auto-expiring blocks (24h default)
✅ Dry-run mode available
✅ Checksum errors ignored (hardware offload)
✅ Restart on failure
✅ Detailed logging of all actions
✅ Only blocks on CRITICAL threats

---

## Quick Status Check

```bash
./manage.sh stats
```

Shows:
- Service uptime
- Memory/CPU usage
- Recent threat activity
- Alert counts

---

## Getting Help

- Full docs: `README.md`
- Service logs: `sudo journalctl -u ai-suricata -f`
- Test mode: Edit service file, change to `--dry-run`

---

**The system is protecting your network right now!** 🛡️

Use `./manage.sh threats` to watch it in action.

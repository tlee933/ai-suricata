#!/bin/bash
# AI Suricata Demo Script

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         AI SURICATA - INTELLIGENT THREAT DETECTION          ║"
echo "║                    System Demonstration                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo "[1/4] Checking Suricata Status on pfSense..."
ssh admin@192.168.1.1 "ps aux | grep '[s]uricata' | head -1" && echo "    ✓ Suricata is running"
echo ""

echo "[2/4] Verifying EVE JSON Logging..."
ALERT_COUNT=$(ssh admin@192.168.1.1 "grep '\"event_type\":\"alert\"' /var/log/suricata/eve.json | wc -l")
echo "    ✓ $ALERT_COUNT alerts in database"
echo ""

echo "[3/4] Displaying System Statistics..."
ssh admin@192.168.1.1 "tail -200 /var/log/suricata/suricata.log | grep 'Alerts:' | tail -1" && echo ""

echo "[4/4] Starting AI Monitoring (30 seconds demo)..."
echo "    Training on historical data and monitoring live threats..."
echo ""
timeout 30 python3 /home/hashcat/pfsense/ai_suricata/ai_suricata.py --train --dry-run --events 1000 2>&1 | grep -E '\[.*\]|\+|Total|Threat'

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║                     Demo Complete!                           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "To run the full system:"
echo "  • Test mode:       python3 ai_suricata.py --dry-run"
echo "  • Training mode:   python3 ai_suricata.py --train"
echo "  • Production mode: python3 ai_suricata.py --train --auto-block"
echo ""
echo "See README.md for full documentation"

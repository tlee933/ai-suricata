# Training Data Collection & Review Guide

**Building Labeled Datasets for Supervised Learning**

---

## Overview

The Neural Firewall Guardian automatically logs every ML classification decision to prepare for future supervised learning. This guide explains how to collect, review, and label training data.

---

## Data Collection (Automatic)

### What Gets Logged

Every alert processed through the ML pipeline is logged in JSONL format:

```json
{
  "timestamp": "2025-12-23T10:30:45.123Z",
  "source_ip": "192.168.1.50",
  "dest_ip": "192.168.1.100",
  "signature": "ET SCAN Potential SSH Scan",
  "signature_id": 2001219,
  "category": "Attempted Information Leak",

  "features": {
    "severity": 3,
    "src_port": 54321,
    "dest_port": 22,
    "packets_toserver": 5,
    "packets_toclient": 0,
    "bytes_toserver": 320,
    "bytes_toclient": 0,
    "avg_pkt_size_toserver": 64.0,
    "avg_pkt_size_toclient": 0.0,
    "ip_alert_count": 45,
    "ip_unique_sigs": 3,
    "is_tcp": 1,
    "is_udp": 0,
    "is_icmp": 0,
    "is_auth_port": 1,
    "is_web_port": 0
  },

  "classification": {
    "base_score": 0.60,
    "anomaly_score": 0.75,
    "pattern_score": 0.80,
    "threat_score": 0.725,
    "severity": "HIGH",
    "action": "RATE_LIMIT",
    "patterns_detected": [
      {
        "pattern": "port_scan",
        "confidence": 0.80,
        "details": "45 unique ports scanned"
      }
    ]
  },

  "auto_label_hint": "REVIEW",
  "label": null,
  "labeled_by": null,
  "labeled_at": null,
  "notes": null
}
```

### Storage Location

```
/home/hashcat/pfsense/ai_suricata/training_data/
├── decisions.2025-12-23.jsonl
├── decisions.2025-12-24.jsonl
└── decisions.2025-12-25.jsonl
```

**Rotation:** Daily files (one per day)
**Retention:** 6 months (automatic cleanup)
**Size:** ~1 KB per alert (~300 MB/day at current volume)

---

## Auto-Labeling Heuristics

The system automatically suggests labels to reduce manual work:

### Auto-Labeled as BENIGN
- Checksum errors
- Invalid ACK packets
- Packet out of window
- Stream validation errors
- Other hardware offloading artifacts

### Auto-Labeled as THREAT
- Blocked IPs with no complaints after 24h
- Known exploit signatures (CVE references)
- Malware/trojan signatures

### Flagged for REVIEW
- HIGH/CRITICAL severity alerts
- Ambiguous patterns
- Everything else

**Estimate:** 90%+ of alerts can be auto-labeled, leaving ~500-1000 for manual review.

---

## Interactive Review Tool

### Usage

```bash
# Review HIGH and CRITICAL alerts from last 24 hours
./review_threats.py --severity HIGH,CRITICAL --since 24

# Review all blocked IPs from last week
./review_threats.py --action BLOCK --since 168

# Review everything (including already labeled)
./review_threats.py --all --since 720

# Show statistics only
./review_threats.py --stats-only
```

### Interactive Interface

```
================================================================================
  THREAT REVIEW - Example 1 / 42
================================================================================

Timestamp: 2025-12-23T10:30:45.123Z

Source IP: 192.168.1.50
Dest IP:   192.168.1.100

Signature: ET SCAN Potential SSH Scan
Category:  Attempted Information Leak

ML Classification:
  Severity:     HIGH
  Threat Score: 0.725
  Action:       RATE_LIMIT

Score Breakdown:
  Base Score:    0.600 (30% weight)
  Anomaly Score: 0.750 (30% weight)
  Pattern Score: 0.800 (40% weight)

Attack Patterns Detected:
  • PORT_SCAN (confidence: 0.80)
    45 unique ports scanned

Key Features:
  Src Port: 54321  Dest Port:    22  IP Alert Count: 45
  Packets: ↑5 ↓0  Bytes: ↑320 ↓0

Auto-Label Hint: REVIEW

────────────────────────────────────────────────────────────────────────────────

Is this a REAL THREAT?

  [T]hreat      - Confirmed malicious activity
  [B]enign      - Legitimate traffic (false positive)
  [F]alse_Pos   - ML incorrectly classified as threat
  [S]kip        - Skip this one (review later)
  [N]ext        - Skip and don't ask again
  [Q]uit        - Save and exit

Your choice: _
```

### Labeling Options

| Key | Label | When to Use |
|-----|-------|-------------|
| **T** | THREAT | Confirmed attack (port scan, brute force, exploit) |
| **B** | BENIGN | Legitimate traffic (known service, CDN, backup) |
| **F** | FALSE_POSITIVE | ML incorrectly flagged as threat |
| **S** | Skip | Need more context, review later |
| **N** | Next | Not important enough to label |
| **Q** | Quit | Save and exit |

### Adding Notes

For THREAT and FALSE_POSITIVE labels, you'll be prompted to add notes:

```
Add notes (optional, press Enter to skip): Backup server doing hourly sync
```

**Good notes:**
- "Backup server - known good"
- "Port scan from internal security audit"
- "False positive - legitimate CDN traffic"
- "Confirmed attacker - brute force SSH"

---

## Statistics & Progress

### View Current Stats

```bash
./review_threats.py --stats-only
```

**Output:**
```
================================================================================
  LABELING STATISTICS
================================================================================

Total Examples:     2847
Labeled:            523 (18.4%)
Unlabeled:          2324 (81.6%)

Label Distribution:
  BENIGN              412 (78.8%)
  THREAT               89 (17.0%)
  FALSE_POSITIVE       22 ( 4.2%)

Session Labels:     0
```

### Prometheus Metric

```
suricata_ai_training_examples_total{} 289391
```

Monitor progress in Grafana dashboard.

---

## Training Dataset Requirements

### Minimum for RandomForest Training

| Metric | Minimum | Recommended | Ideal |
|--------|---------|-------------|-------|
| **Total Examples** | 500 | 2,000 | 10,000+ |
| **Threat Examples** | 100 | 500 | 2,000+ |
| **Benign Examples** | 100 | 500 | 2,000+ |
| **Class Balance** | 30/70 | 40/60 | 45/55 |

### Timeline Estimates

**Conservative (manual review only):**
- 10 alerts/hour at current rate = 240/day
- 1000 labeled examples = ~4 days
- 5000 labeled examples = ~21 days

**With auto-labeling (90% automatic):**
- 2400 auto-labeled/day + 100 manual/day
- 1000 labeled examples = ~1 day
- 5000 labeled examples = ~2 days

---

## Best Practices

### Review Schedule

**Option 1: Daily Quick Review** (Recommended)
```bash
# 10 minutes/day reviewing CRITICAL only
./review_threats.py --severity CRITICAL --since 24
```

**Option 2: Weekly Batch Review**
```bash
# 1 hour/week reviewing HIGH and CRITICAL
./review_threats.py --severity HIGH,CRITICAL --since 168
```

**Option 3: Triggered Review**
```bash
# Review blocked IPs to validate auto-blocking
./review_threats.py --action BLOCK --since 24
```

### Labeling Guidelines

**When to Label as THREAT:**
- Port scanning (20+ ports)
- Brute force attempts (repeated auth failures)
- Exploit attempts (CVE signatures)
- Malware downloads
- C2 communication patterns
- Data exfiltration

**When to Label as BENIGN:**
- Known services (CDN, backup, monitoring)
- Internal network traffic
- Hardware offloading artifacts
- Legitimate high-volume traffic
- Whitelisted IPs

**When to Label as FALSE_POSITIVE:**
- ML scored HIGH but is actually benign
- Legitimate traffic misclassified
- Known good service flagged as threat
- Pattern detection triggered incorrectly

**When to SKIP:**
- Insufficient context to decide
- Need network knowledge you don't have
- Ambiguous behavior
- Edge cases

---

## Data Management

### Backup Training Data

```bash
# Backup before review session
tar -czf training_data_backup_$(date +%Y%m%d).tar.gz training_data/
```

### Export Labeled Examples

```bash
# Extract only labeled examples
cd training_data
grep -h '"label": "[^n]' decisions.*.jsonl > labeled_examples.jsonl
```

### Manual Data Cleanup

```bash
# Remove old unlabeled data (keep labeled)
python3 << 'EOF'
import json
from pathlib import Path

for file in Path('training_data').glob('decisions.*.jsonl'):
    labeled = []
    with open(file, 'r') as f:
        for line in f:
            example = json.loads(line)
            if example.get('label'):
                labeled.append(line)

    # Overwrite with only labeled examples
    if labeled:
        with open(file, 'w') as f:
            f.writelines(labeled)
EOF
```

---

## Troubleshooting

### No Examples to Review

**Problem:** `[!] No training data found`

**Solutions:**
1. Check data collection is enabled in ai_suricata.py
2. Restart ai-suricata service to start collecting
3. Wait for alerts to be processed
4. Check file permissions on training_data/

### Review Tool Crashes

**Problem:** Tool exits with error

**Solutions:**
1. Check JSONL files are valid: `python3 -m json.tool < file.jsonl`
2. Backup and delete corrupted files
3. Check disk space

### Can't Save Labels

**Problem:** `[!] Failed to save label`

**Solutions:**
1. Check file permissions: `chmod 644 training_data/*.jsonl`
2. Check disk space
3. Ensure file isn't open in another program

---

## Next Steps

### When Dataset is Ready

Once you have 1000+ labeled examples:

1. **Validate dataset quality**
   ```bash
   ./review_threats.py --stats-only
   ```

2. **Train RandomForest classifier** (future tool)
   ```bash
   ./train_supervised.py --data training_data/labeled/*.jsonl
   ```

3. **A/B test against IsolationForest**
   ```bash
   ./benchmark_models.py --compare
   ```

4. **Deploy hybrid ensemble**
   ```bash
   systemctl restart ai-suricata
   ```

---

## FAQ

**Q: How many examples do I need to label manually?**
A: With auto-labeling, only ~500-1000 (the HIGH/CRITICAL alerts).

**Q: Can I delete unlabeled data?**
A: Yes, but keep at least 10k examples for model training diversity.

**Q: Should I label INFO/LOW severity alerts?**
A: No, focus on HIGH/CRITICAL. Auto-labeling handles the rest.

**Q: What if I'm unsure about a label?**
A: Use [S]kip. Better to skip than mislabel.

**Q: Can multiple people label data?**
A: Yes, but coordinate to avoid duplicates. Use `--all` flag carefully.

**Q: How do I correct a wrong label?**
A: Run with `--all` flag, find the example, relabel it.

---

**Document Version:** 1.0
**Last Updated:** 2025-12-23
**Tool:** review_threats.py

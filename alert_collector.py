#!/usr/bin/env python3
"""
AI Suricata Alert Collector
Connects to pfSense, reads EVE JSON logs, extracts features for ML classification
"""

import orjson
import subprocess
import sys
from datetime import datetime
from collections import defaultdict
import time

class SuricataAlertCollector:
    def __init__(self, pfsense_host="192.168.1.1", pfsense_user="admin"):
        self.pfsense_host = pfsense_host
        self.pfsense_user = pfsense_user
        self.eve_log_path = "/var/log/suricata/eve.json"

        # Feature tracking
        self.ip_stats = defaultdict(lambda: {"alerts": 0, "signatures": set(), "last_seen": None})
        self.signature_counts = defaultdict(int)
        self.alert_timeline = []

    def tail_eve_log(self, follow=False, lines=100):
        """Tail the EVE JSON log from pfSense"""
        cmd = f"tail -n {lines} {self.eve_log_path}"
        if follow:
            cmd = f"tail -f {self.eve_log_path}"

        ssh_cmd = ["ssh", f"{self.pfsense_user}@{self.pfsense_host}", cmd]

        try:
            if follow:
                # Streaming mode
                proc = subprocess.Popen(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for line in proc.stdout:
                    yield line.strip()
            else:
                # Batch mode
                result = subprocess.run(ssh_cmd, capture_output=True, text=True, check=True)
                for line in result.stdout.split('\n'):
                    if line.strip():
                        yield line.strip()
        except subprocess.CalledProcessError as e:
            print(f"Error reading eve.json: {e}", file=sys.stderr)
            sys.exit(1)

    def parse_event(self, line):
        """Parse JSON event from EVE log (using orjson for 2-3x faster parsing)"""
        try:
            # orjson.loads() expects bytes, so encode string if needed
            if isinstance(line, str):
                line = line.encode('utf-8')
            return orjson.loads(line)
        except (orjson.JSONDecodeError, ValueError):
            return None

    def extract_features(self, event):
        """Extract ML features from Suricata event"""
        if not event or event.get("event_type") != "alert":
            return None

        features = {
            "timestamp": event.get("timestamp"),
            "src_ip": event.get("src_ip"),
            "dest_ip": event.get("dest_ip"),
            "src_port": event.get("src_port", 0),
            "dest_port": event.get("dest_port", 0),
            "proto": event.get("proto"),
            "in_iface": event.get("in_iface"),

            # Alert metadata
            "signature": event.get("alert", {}).get("signature", ""),
            "signature_id": event.get("alert", {}).get("signature_id", 0),
            "category": event.get("alert", {}).get("category", ""),
            "severity": event.get("alert", {}).get("severity", 0),
            "action": event.get("alert", {}).get("action", ""),

            # Flow statistics
            "pkts_toserver": event.get("flow", {}).get("pkts_toserver", 0),
            "pkts_toclient": event.get("flow", {}).get("pkts_toclient", 0),
            "bytes_toserver": event.get("flow", {}).get("bytes_toserver", 0),
            "bytes_toclient": event.get("flow", {}).get("bytes_toclient", 0),
        }

        return features

    def update_statistics(self, features):
        """Update running statistics for anomaly detection"""
        src_ip = features["src_ip"]
        sig_id = features["signature_id"]

        # Track per-IP statistics
        self.ip_stats[src_ip]["alerts"] += 1
        self.ip_stats[src_ip]["signatures"].add(sig_id)
        self.ip_stats[src_ip]["last_seen"] = features["timestamp"]

        # Track signature frequency
        self.signature_counts[sig_id] += 1

        # Add to timeline
        self.alert_timeline.append({
            "timestamp": features["timestamp"],
            "src_ip": src_ip,
            "signature_id": sig_id,
            "severity": features["severity"]
        })

        # Keep last 1000 alerts
        if len(self.alert_timeline) > 1000:
            self.alert_timeline = self.alert_timeline[-1000:]

    def calculate_threat_score(self, features):
        """Calculate basic threat score (0-1) based on heuristics"""
        src_ip = features["src_ip"]
        sig_id = features["signature_id"]

        score = 0.0

        # Severity contribution (0-3 → 0-0.3)
        score += features["severity"] / 10.0

        # Frequency: repeated alerts from same IP
        ip_alert_count = self.ip_stats[src_ip]["alerts"]
        if ip_alert_count > 10:
            score += 0.3
        elif ip_alert_count > 5:
            score += 0.2
        elif ip_alert_count > 2:
            score += 0.1

        # Diversity: multiple different signatures from same IP (port scanning indicator)
        unique_sigs = len(self.ip_stats[src_ip]["signatures"])
        if unique_sigs > 5:
            score += 0.3
        elif unique_sigs > 3:
            score += 0.2

        # Rare signatures (less common = potentially more dangerous)
        sig_count = self.signature_counts[sig_id]
        if sig_count < 3:
            score += 0.1

        # Ignore checksum errors (false positives from hardware offloading)
        if "checksum" in features["signature"].lower():
            score *= 0.1

        return min(score, 1.0)

    def classify_alert(self, features):
        """Classify alert into risk categories"""
        score = self.calculate_threat_score(features)

        if score >= 0.9:
            return "CRITICAL", score
        elif score >= 0.7:
            return "HIGH", score
        elif score >= 0.5:
            return "MEDIUM", score
        elif score >= 0.3:
            return "LOW", score
        else:
            return "INFO", score

    def process_alert(self, event):
        """Process a single alert event"""
        features = self.extract_features(event)
        if not features:
            return None

        self.update_statistics(features)
        risk_level, threat_score = self.classify_alert(features)

        return {
            "features": features,
            "risk_level": risk_level,
            "threat_score": threat_score,
            "ip_alert_count": self.ip_stats[features["src_ip"]]["alerts"],
            "ip_unique_signatures": len(self.ip_stats[features["src_ip"]]["signatures"])
        }

    def collect_historical(self, lines=1000):
        """Collect and analyze historical alerts"""
        print(f"[*] Collecting last {lines} events from pfSense...")

        alerts_processed = 0
        for line in self.tail_eve_log(follow=False, lines=lines):
            event = self.parse_event(line)
            if event and event.get("event_type") == "alert":
                result = self.process_alert(event)
                if result:
                    alerts_processed += 1

        print(f"[+] Processed {alerts_processed} alerts")
        print(f"[+] Tracking {len(self.ip_stats)} unique source IPs")
        return alerts_processed

    def monitor_live(self):
        """Monitor live alerts in real-time"""
        print("[*] Starting live alert monitoring...")
        print("[*] Press Ctrl+C to stop\n")

        try:
            for line in self.tail_eve_log(follow=True):
                event = self.parse_event(line)
                if not event:
                    continue

                result = self.process_alert(event)
                if result:
                    f = result["features"]

                    # Format output
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    output = (
                        f"[{timestamp}] [{result['risk_level']:8s}] "
                        f"{f['src_ip']:15s} → {f['dest_ip']:15s} | "
                        f"Score: {result['threat_score']:.2f} | "
                        f"{f['signature'][:60]}"
                    )

                    # Color coding
                    if result['risk_level'] in ['CRITICAL', 'HIGH']:
                        print(f"\033[91m{output}\033[0m")  # Red
                    elif result['risk_level'] == 'MEDIUM':
                        print(f"\033[93m{output}\033[0m")  # Yellow
                    else:
                        print(output)

        except KeyboardInterrupt:
            print("\n\n[*] Stopping monitoring...")
            self.print_summary()

    def print_summary(self):
        """Print analysis summary"""
        print("\n" + "="*80)
        print("ALERT SUMMARY")
        print("="*80)

        print(f"\nTotal unique IPs: {len(self.ip_stats)}")
        print(f"Total alert types: {len(self.signature_counts)}")

        print("\n--- Top 10 Most Active IPs ---")
        sorted_ips = sorted(self.ip_stats.items(), key=lambda x: x[1]["alerts"], reverse=True)[:10]
        for ip, stats in sorted_ips:
            print(f"  {ip:15s} - {stats['alerts']:4d} alerts, {len(stats['signatures']):2d} unique signatures")

        print("\n--- Top 10 Most Common Signatures ---")
        sorted_sigs = sorted(self.signature_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        for sig_id, count in sorted_sigs:
            print(f"  SID {sig_id:8d} - {count:4d} occurrences")

if __name__ == "__main__":
    collector = SuricataAlertCollector()

    # First, collect historical data for baseline
    collector.collect_historical(lines=5000)
    collector.print_summary()

    # Then start live monitoring
    print("\n")
    collector.monitor_live()

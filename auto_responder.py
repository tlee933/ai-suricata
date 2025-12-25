#!/usr/bin/env python3
"""
Automated Response System for AI Suricata
Executes actions based on ML threat classification
"""

import subprocess
import json
import time
from datetime import datetime, timedelta
from collections import defaultdict

class AutoResponder:
    def __init__(self, pfsense_host="192.168.1.1", pfsense_user="admin", dry_run=False, redis_client=None):
        self.pfsense_host = pfsense_host
        self.pfsense_user = pfsense_user
        self.dry_run = dry_run  # If True, only log actions without executing
        self.redis_client = redis_client  # Optional Redis client for persistence

        # Track blocked IPs
        self.blocked_ips = {}  # {ip: {"timestamp": ..., "reason": ..., "threat_score": ...}}
        self.rate_limited_ips = {}
        self.monitored_ips = defaultdict(list)

        # Action statistics
        self.stats = {
            "blocks": 0,
            "rate_limits": 0,
            "monitors": 0,
            "logs": 0
        }

        # Restore blocked IPs from Redis on startup
        if self.redis_client and self.redis_client.enabled:
            self._restore_blocks_from_redis()

    def _restore_blocks_from_redis(self):
        """Restore blocked IPs from Redis on startup"""
        try:
            active_blocks = self.redis_client.get_active_blocks()
            restored_count = 0

            for ip in active_blocks:
                block_info = self.redis_client.get_blocked_ip_info(ip)
                if block_info:
                    # Convert timestamp back to datetime
                    self.blocked_ips[ip] = {
                        "timestamp": datetime.fromtimestamp(block_info["timestamp"]),
                        "reason": block_info["reason"],
                        "threat_score": block_info["score"]
                    }
                    restored_count += 1

            if restored_count > 0:
                print(f"[+] Restored {restored_count} blocked IPs from Redis")
        except Exception as e:
            print(f"[!] Failed to restore blocks from Redis: {e}")

    def ssh_command(self, command):
        """Execute command on pfSense via SSH"""
        ssh_cmd = ["ssh", f"{self.pfsense_user}@{self.pfsense_host}", command]

        try:
            result = subprocess.run(
                ssh_cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
            return {"success": True, "output": result.stdout, "error": ""}
        except subprocess.CalledProcessError as e:
            return {"success": False, "output": e.stdout, "error": e.stderr}
        except subprocess.TimeoutExpired:
            return {"success": False, "output": "", "error": "Command timed out"}

    def block_ip(self, ip, reason, threat_score):
        """Block an IP address using pfSense firewall"""
        if ip in self.blocked_ips:
            print(f"[*] IP {ip} already blocked")
            return {"success": True, "message": "Already blocked"}

        print(f"[!] BLOCKING IP: {ip} - Reason: {reason} - Threat Score: {threat_score:.2f}")

        if self.dry_run:
            print(f"    [DRY RUN] Would block {ip}")
            self.blocked_ips[ip] = {
                "timestamp": datetime.now(),
                "reason": reason,
                "threat_score": threat_score
            }
            self.stats["blocks"] += 1
            return {"success": True, "message": "Dry run - not executed"}

        # Create PHP script to add firewall rule
        php_script = f"""<?php
require_once('/etc/inc/config.inc');
require_once('/etc/inc/filter.inc');

if (!is_array(\\$config['filter']['rule'])) {{
    \\$config['filter']['rule'] = array();
}}

// Create blocking rule
\\$rule = array();
\\$rule['type'] = 'block';
\\$rule['interface'] = 'wan,lan,opt1,opt3';  // Block on all interfaces
\\$rule['ipprotocol'] = 'inet';
\\$rule['protocol'] = 'tcp/udp';
\\$rule['source']['address'] = '{ip}';
\\$rule['destination']['any'] = true;
\\$rule['descr'] = 'AI_BLOCK: {reason} (Score: {threat_score:.2f}) - ' . date('Y-m-d H:i:s');
\\$rule['created'] = array('time' => time(), 'username' => 'ai_suricata');

// Add at beginning of rules for priority
array_unshift(\\$config['filter']['rule'], \\$rule);

write_config('AI Suricata blocked {ip}');

// Apply filter changes
filter_configure();

echo \"Blocked {ip}\\\\n\";
?>"""

        # Execute via SSH
        cmd = f"cat > /tmp/block_ip.php << 'EOFPHP'\n{php_script}\nEOFPHP\nphp /tmp/block_ip.php && rm /tmp/block_ip.php"
        result = self.ssh_command(cmd)

        if result["success"]:
            timestamp = datetime.now()
            self.blocked_ips[ip] = {
                "timestamp": timestamp,
                "reason": reason,
                "threat_score": threat_score
            }
            self.stats["blocks"] += 1
            print(f"    [+] Successfully blocked {ip}")

            # Also persist to Redis if available
            if self.redis_client and self.redis_client.enabled:
                self.redis_client.set_blocked_ip(ip, reason, threat_score, ttl=86400)
                print(f"    [+] Persisted block to Redis (24h TTL)")
        else:
            print(f"    [-] Failed to block {ip}: {result['error']}")

        return result

    def rate_limit_ip(self, ip, reason):
        """Apply rate limiting to an IP"""
        print(f"[*] RATE LIMITING: {ip} - {reason}")

        if self.dry_run:
            print(f"    [DRY RUN] Would rate limit {ip}")
            self.rate_limited_ips[ip] = {"timestamp": datetime.now(), "reason": reason}
            self.stats["rate_limits"] += 1
            return {"success": True, "message": "Dry run - not executed"}

        # For now, log the action - could implement actual rate limiting via pf
        # Rate limiting would require: pf.conf modifications or using traffic shaper
        self.rate_limited_ips[ip] = {
            "timestamp": datetime.now(),
            "reason": reason
        }
        self.stats["rate_limits"] += 1

        # TODO: Implement actual rate limiting via pfSense traffic shaper API
        print(f"    [*] Rate limiting logged for {ip}")
        return {"success": True, "message": "Rate limiting logged"}

    def monitor_ip(self, ip, alert_data):
        """Add IP to enhanced monitoring"""
        self.monitored_ips[ip].append({
            "timestamp": datetime.now(),
            "alert_data": alert_data
        })
        self.stats["monitors"] += 1

        # Keep last 100 events per IP
        if len(self.monitored_ips[ip]) > 100:
            self.monitored_ips[ip] = self.monitored_ips[ip][-100:]

    def log_alert(self, alert_data, classification):
        """Log alert to file"""
        self.stats["logs"] += 1

        log_file = "/home/hashcat/pfsense/ai_suricata/logs/ai_alerts.jsonl"
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "alert": alert_data,
            "classification": classification
        }

        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')

    def execute_action(self, alert_data, classification):
        """Execute the recommended action based on classification"""
        action = classification["action"]
        src_ip = alert_data["features"]["src_ip"]
        severity = classification["severity"]
        threat_score = classification["threat_score"]

        # Build reason string
        patterns = classification.get("attack_patterns", [])
        if patterns:
            pattern_desc = ", ".join([p["pattern"] for p in patterns])
            reason = f"{severity}: {pattern_desc}"
        else:
            reason = f"{severity}: Threat score {threat_score:.2f}"

        # Execute action
        if action == "BLOCK":
            result = self.block_ip(src_ip, reason, threat_score)
            return {"action": "BLOCK", "ip": src_ip, "result": result}

        elif action == "RATE_LIMIT":
            result = self.rate_limit_ip(src_ip, reason)
            return {"action": "RATE_LIMIT", "ip": src_ip, "result": result}

        elif action == "MONITOR":
            self.monitor_ip(src_ip, alert_data)
            return {"action": "MONITOR", "ip": src_ip, "result": {"success": True}}

        elif action == "LOG":
            self.log_alert(alert_data, classification)
            return {"action": "LOG", "ip": src_ip, "result": {"success": True}}

        else:  # IGNORE
            return {"action": "IGNORE", "ip": src_ip, "result": {"success": True}}

    def unblock_ip(self, ip):
        """Remove block for an IP"""
        if ip not in self.blocked_ips:
            return {"success": False, "message": "IP not blocked"}

        print(f"[*] Unblocking {ip}")

        if self.dry_run:
            del self.blocked_ips[ip]
            return {"success": True, "message": "Dry run - not executed"}

        # PHP script to remove the rule
        php_script = f"""<?php
require_once('/etc/inc/config.inc');
require_once('/etc/inc/filter.inc');

$removed = false;
foreach (\\$config['filter']['rule'] as \\$key => \\$rule) {{
    if (isset(\\$rule['source']['address']) && \\$rule['source']['address'] == '{ip}' &&
        strpos(\\$rule['descr'], 'AI_BLOCK') !== false) {{
        unset(\\$config['filter']['rule'][\\$key]);
        \\$removed = true;
        break;
    }}
}}

if (\\$removed) {{
    \\$config['filter']['rule'] = array_values(\\$config['filter']['rule']);
    write_config('AI Suricata unblocked {ip}');
    filter_configure();
    echo \"Unblocked {ip}\\\\n\";
}} else {{
    echo \"Rule not found for {ip}\\\\n\";
}}
?>"""

        cmd = f"cat > /tmp/unblock_ip.php << 'EOFPHP'\n{php_script}\nEOFPHP\nphp /tmp/unblock_ip.php && rm /tmp/unblock_ip.php"
        result = self.ssh_command(cmd)

        if result["success"]:
            del self.blocked_ips[ip]
            print(f"    [+] Successfully unblocked {ip}")

            # Also remove from Redis if available
            if self.redis_client and self.redis_client.enabled:
                self.redis_client.unblock_ip(ip)
                print(f"    [+] Removed from Redis cache")

        return result

    def cleanup_old_blocks(self, max_age_hours=24):
        """Remove old blocks (prevent permanent blocking)"""
        # If Redis is enabled, it handles auto-expiration via TTL
        # We just need to sync the active_blocks set
        if self.redis_client and self.redis_client.enabled:
            removed_count = self.redis_client.cleanup_expired_blocks()
            if removed_count > 0:
                print(f"[*] Redis cleaned up {removed_count} expired blocks")

        # Still check in-memory blocks for manual expiration
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        to_remove = []

        for ip, data in self.blocked_ips.items():
            if data["timestamp"] < cutoff:
                to_remove.append(ip)

        for ip in to_remove:
            print(f"[*] Auto-expiring block for {ip} (age > {max_age_hours}h)")
            self.unblock_ip(ip)

        return len(to_remove)

    def print_stats(self):
        """Print response statistics"""
        print("\n" + "="*80)
        print("AUTO RESPONSE STATISTICS")
        print("="*80)
        print(f"Total Blocks:       {self.stats['blocks']}")
        print(f"Total Rate Limits:  {self.stats['rate_limits']}")
        print(f"Total Monitors:     {self.stats['monitors']}")
        print(f"Total Logs:         {self.stats['logs']}")
        print(f"\nCurrently Blocked IPs: {len(self.blocked_ips)}")

        if self.blocked_ips:
            print("\n--- Blocked IPs ---")
            for ip, data in list(self.blocked_ips.items())[:10]:
                age = (datetime.now() - data["timestamp"]).seconds // 60
                print(f"  {ip:15s} - {data['reason'][:50]:50s} ({age}m ago)")

import os

if __name__ == "__main__":
    # Test in dry-run mode
    responder = AutoResponder(dry_run=True)

    # Simulate a threat
    test_alert = {
        "features": {
            "src_ip": "10.0.0.1",
            "dest_ip": "192.168.1.100",
            "signature": "Test Attack"
        }
    }

    test_classification = {
        "severity": "CRITICAL",
        "action": "BLOCK",
        "threat_score": 0.95,
        "attack_patterns": [{"pattern": "port_scan", "confidence": 0.9}]
    }

    result = responder.execute_action(test_alert, test_classification)
    print(json.dumps(result, indent=2, default=str))
    responder.print_stats()

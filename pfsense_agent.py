#!/usr/bin/env python3
"""
pfSense Agent - Redis Streams Publisher
Replaces SSH for alert streaming and command execution

Runs on pfSense firewall to:
1. Watch Suricata eve.json log and publish alerts to Redis
2. Subscribe to block commands and execute firewall rules
3. Publish system metrics (CPU, memory, temperature)
4. Send heartbeat for health monitoring

Deploy to pfSense: /root/pfsense_agent.py
"""

import sys
import os
import json
import time
import socket
import signal
import subprocess
from datetime import datetime
from collections import deque

try:
    import redis
except ImportError:
    print("[!] Redis package not installed. Install with: pip3 install redis")
    sys.exit(1)


class PfSenseAgent:
    """pfSense agent for Redis Streams communication"""

    def __init__(self, redis_host='localhost', redis_port=6379, redis_password=None,
                 redis_db=0, key_prefix='ai_suricata'):
        """
        Initialize pfSense agent.

        Args:
            redis_host: Redis server hostname
            redis_port: Redis server port
            redis_password: Optional Redis password
            redis_db: Redis database number
            key_prefix: Prefix for all Redis keys
        """
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.key_prefix = key_prefix
        self.hostname = socket.gethostname()
        self.running = True

        # Connect to Redis
        try:
            self.redis = redis.Redis(
                host=redis_host,
                port=redis_port,
                password=password if redis_password else None,
                db=redis_db,
                decode_responses=True,
                socket_timeout=5,
                socket_keepalive=True
            )
            self.redis.ping()
            print(f"[+] Connected to Redis: {redis_host}:{redis_port}")
        except Exception as e:
            print(f"[!] Failed to connect to Redis: {e}")
            sys.exit(1)

        # Stream names
        self.alerts_stream = f"{key_prefix}:alerts:stream"
        self.blocks_stream = f"{key_prefix}:blocks:stream"
        self.stats_stream = f"{key_prefix}:stats:stream"
        self.health_stream = f"{key_prefix}:health:stream"
        self.acks_stream = f"{key_prefix}:acks:stream"

        # Statistics
        self.stats = {
            'alerts_published': 0,
            'commands_executed': 0,
            'errors': 0,
            'uptime_start': time.time()
        }

        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def signal_handler(self, sig, frame):
        """Handle shutdown gracefully"""
        print("\n[*] Shutting down pfSense agent...")
        self.running = False
        self.publish_health('shutdown', 'Agent shutting down')
        sys.exit(0)

    def _key(self, key: str) -> str:
        """Add namespace prefix to key"""
        return f"{self.key_prefix}:{key}"

    def publish_alert(self, event_data: dict) -> bool:
        """
        Publish Suricata alert to Redis stream.

        Args:
            event_data: Parsed Suricata event (from eve.json)

        Returns:
            True if published successfully
        """
        try:
            # Extract key fields
            message = {
                'timestamp': event_data.get('timestamp', datetime.now().isoformat()),
                'hostname': self.hostname,
                'event_type': event_data.get('event_type', 'unknown'),
                'event_data': json.dumps(event_data),
                'src_ip': event_data.get('src_ip', ''),
                'dest_ip': event_data.get('dest_ip', ''),
                'src_port': str(event_data.get('src_port', 0)),
                'dest_port': str(event_data.get('dest_port', 0)),
                'proto': event_data.get('proto', ''),
            }

            # Add alert-specific fields if present
            if 'alert' in event_data:
                alert = event_data['alert']
                message['signature_id'] = str(alert.get('signature_id', 0))
                message['signature'] = alert.get('signature', '')
                message['severity'] = str(alert.get('severity', 0))
                message['category'] = alert.get('category', '')

            # Publish to stream
            msg_id = self.redis.xadd(self.alerts_stream, message, maxlen=100000)
            self.stats['alerts_published'] += 1

            return True

        except Exception as e:
            print(f"[!] Error publishing alert: {e}")
            self.stats['errors'] += 1
            return False

    def watch_eve_log(self, log_file='/var/log/suricata/eve.json'):
        """
        Watch Suricata EVE log and publish alerts to Redis.

        Args:
            log_file: Path to Suricata eve.json log
        """
        print(f"[*] Watching {log_file} for alerts...")

        try:
            # Open log file
            with open(log_file, 'r') as f:
                # Seek to end of file
                f.seek(0, os.SEEK_END)

                while self.running:
                    line = f.readline()

                    if not line:
                        time.sleep(0.1)  # Wait for new data
                        continue

                    try:
                        # Parse JSON event
                        event = json.loads(line.strip())

                        # Only publish alerts (ignore flow, stats, etc. unless configured otherwise)
                        if event.get('event_type') == 'alert':
                            self.publish_alert(event)

                    except json.JSONDecodeError:
                        continue  # Skip invalid JSON lines

        except FileNotFoundError:
            print(f"[!] Log file not found: {log_file}")
            print("[*] Make sure Suricata is running and logging to eve.json")
            sys.exit(1)
        except Exception as e:
            print(f"[!] Error watching log: {e}")
            self.stats['errors'] += 1

    def process_commands(self):
        """
        Subscribe to command stream and execute firewall actions.
        Runs in parallel with log watching.
        """
        print(f"[*] Listening for commands on {self.blocks_stream}...")

        last_id = '0'  # Start from beginning, then use '>' for new messages only

        while self.running:
            try:
                # Read from stream (blocking for 1 second)
                messages = self.redis.xread(
                    {self.blocks_stream: last_id},
                    count=10,
                    block=1000
                )

                if not messages:
                    continue  # Timeout, try again

                for stream_name, stream_messages in messages:
                    for msg_id, msg_data in stream_messages:
                        # Execute command
                        self.execute_command(msg_id, msg_data)
                        last_id = msg_id  # Update last processed ID

            except Exception as e:
                print(f"[!] Error processing commands: {e}")
                self.stats['errors'] += 1
                time.sleep(1)

    def execute_command(self, msg_id: str, data: dict):
        """
        Execute firewall command from Redis stream.

        Args:
            msg_id: Message ID from stream
            data: Command data (action, ip_address, reason, etc.)
        """
        action = data.get('action', '')
        ip_address = data.get('ip_address', '')
        reason = data.get('reason', 'AI Suricata block')
        threat_score = float(data.get('threat_score', 0.0))
        command_id = data.get('command_id', msg_id)

        print(f"[*] Executing command: {action} {ip_address}")

        start_time = time.time()
        success = False
        error_message = ''

        try:
            if action == 'block':
                success = self.block_ip(ip_address, reason, threat_score)
            elif action == 'unblock':
                success = self.unblock_ip(ip_address)
            elif action == 'rate_limit':
                print(f"[*] Rate limiting not yet implemented for {ip_address}")
                success = True  # Acknowledge but don't execute
            else:
                error_message = f"Unknown action: {action}"
                print(f"[!] {error_message}")

        except Exception as e:
            error_message = str(e)
            print(f"[!] Command execution failed: {e}")

        execution_time = int((time.time() - start_time) * 1000)  # milliseconds

        # Publish acknowledgment
        self.publish_ack(command_id, success, error_message, execution_time)

        if success:
            self.stats['commands_executed'] += 1
        else:
            self.stats['errors'] += 1

    def block_ip(self, ip: str, reason: str, threat_score: float) -> bool:
        """
        Block IP address using pfSense firewall.

        Args:
            ip: IP address to block
            reason: Reason for blocking
            threat_score: Threat score (0.0-1.0)

        Returns:
            True if successful
        """
        # Create PHP script to add firewall rule
        php_script = f"""<?php
require_once('/etc/inc/config.inc');
require_once('/etc/inc/filter.inc');

if (!is_array($config['filter']['rule'])) {{
    $config['filter']['rule'] = array();
}}

// Create blocking rule
$rule = array();
$rule['type'] = 'block';
$rule['interface'] = 'wan,lan,opt1,opt3';
$rule['ipprotocol'] = 'inet';
$rule['protocol'] = 'tcp/udp';
$rule['source']['address'] = '{ip}';
$rule['destination']['any'] = true;
$rule['descr'] = 'AI_BLOCK_MQ: {reason} (Score: {threat_score:.2f}) - ' . date('Y-m-d H:i:s');
$rule['created'] = array('time' => time(), 'username' => 'ai_suricata_mq');

// Add at beginning for priority
array_unshift($config['filter']['rule'], $rule);

write_config('AI Suricata (MQ) blocked {ip}');
filter_configure();

echo "Blocked {ip}\\n";
?>"""

        try:
            # Write PHP script to temp file
            with open('/tmp/block_ip_mq.php', 'w') as f:
                f.write(php_script)

            # Execute PHP script
            result = subprocess.run(
                ['php', '/tmp/block_ip_mq.php'],
                capture_output=True,
                text=True,
                timeout=10
            )

            # Clean up
            os.remove('/tmp/block_ip_mq.php')

            if result.returncode == 0:
                print(f"    [+] Successfully blocked {ip}")
                return True
            else:
                print(f"    [!] Failed to block {ip}: {result.stderr}")
                return False

        except Exception as e:
            print(f"    [!] Exception blocking {ip}: {e}")
            return False

    def unblock_ip(self, ip: str) -> bool:
        """
        Remove IP block from pfSense firewall.

        Args:
            ip: IP address to unblock

        Returns:
            True if successful
        """
        php_script = f"""<?php
require_once('/etc/inc/config.inc');
require_once('/etc/inc/filter.inc');

$removed = false;
foreach ($config['filter']['rule'] as $key => $rule) {{
    if (isset($rule['source']['address']) && $rule['source']['address'] == '{ip}' &&
        (strpos($rule['descr'], 'AI_BLOCK') !== false || strpos($rule['descr'], 'AI_BLOCK_MQ') !== false)) {{
        unset($config['filter']['rule'][$key]);
        $removed = true;
        break;
    }}
}}

if ($removed) {{
    $config['filter']['rule'] = array_values($config['filter']['rule']);
    write_config('AI Suricata (MQ) unblocked {ip}');
    filter_configure();
    echo "Unblocked {ip}\\n";
}} else {{
    echo "Rule not found for {ip}\\n";
}}
?>"""

        try:
            with open('/tmp/unblock_ip_mq.php', 'w') as f:
                f.write(php_script)

            result = subprocess.run(
                ['php', '/tmp/unblock_ip_mq.php'],
                capture_output=True,
                text=True,
                timeout=10
            )

            os.remove('/tmp/unblock_ip_mq.php')

            if result.returncode == 0:
                print(f"    [+] Successfully unblocked {ip}")
                return True
            else:
                print(f"    [!] Failed to unblock {ip}: {result.stderr}")
                return False

        except Exception as e:
            print(f"    [!] Exception unblocking {ip}: {e}")
            return False

    def publish_ack(self, command_id: str, success: bool, error_message: str, execution_time: int):
        """
        Publish command acknowledgment to Redis.

        Args:
            command_id: Original command ID
            success: True if command succeeded
            error_message: Error message if failed
            execution_time: Execution time in milliseconds
        """
        try:
            self.redis.xadd(self.acks_stream, {
                'command_id': command_id,
                'status': 'success' if success else 'failure',
                'error_message': error_message,
                'execution_time': str(execution_time),
                'timestamp': datetime.now().isoformat(),
                'hostname': self.hostname
            }, maxlen=10000)
        except Exception as e:
            print(f"[!] Error publishing ack: {e}")

    def publish_health(self, status: str = 'healthy', message: str = ''):
        """
        Publish health heartbeat to Redis.

        Args:
            status: Health status (healthy, degraded, error, shutdown)
            message: Optional status message
        """
        try:
            uptime = int(time.time() - self.stats['uptime_start'])

            self.redis.xadd(self.health_stream, {
                'source': 'pfsense-agent',
                'hostname': self.hostname,
                'status': status,
                'message': message,
                'uptime': str(uptime),
                'alerts_published': str(self.stats['alerts_published']),
                'commands_executed': str(self.stats['commands_executed']),
                'errors': str(self.stats['errors']),
                'timestamp': datetime.now().isoformat()
            }, maxlen=1000)
        except Exception as e:
            print(f"[!] Error publishing health: {e}")

    def publish_stats(self):
        """
        Publish system statistics to Redis.
        Call periodically (e.g., every 30 seconds).
        """
        try:
            # Get CPU usage (rough estimate via sysctl)
            cpu_result = subprocess.run(
                ['sysctl', '-n', 'kern.cp_time'],
                capture_output=True,
                text=True,
                timeout=2
            )

            # Get memory usage
            mem_result = subprocess.run(
                ['sysctl', '-n', 'hw.physmem', 'hw.usermem'],
                capture_output=True,
                text=True,
                timeout=2
            )

            # Get temperature if available
            temp_result = subprocess.run(
                ['sysctl', '-a'],
                capture_output=True,
                text=True,
                timeout=2
            )

            # Parse temperature
            temp = 0
            for line in temp_result.stdout.split('\n'):
                if 'temperature' in line.lower():
                    # Extract numeric value
                    parts = line.split(':')
                    if len(parts) > 1:
                        try:
                            temp = float(parts[1].strip().replace('C', ''))
                            break
                        except:
                            pass

            self.redis.xadd(self.stats_stream, {
                'hostname': self.hostname,
                'cpu_usage': '0',  # TODO: Calculate actual CPU usage
                'memory_total': mem_result.stdout.split('\n')[0] if mem_result.returncode == 0 else '0',
                'memory_used': mem_result.stdout.split('\n')[1] if mem_result.returncode == 0 else '0',
                'temperature': str(temp),
                'timestamp': datetime.now().isoformat()
            }, maxlen=1000)

        except Exception as e:
            print(f"[!] Error publishing stats: {e}")

    def run(self, log_file='/var/log/suricata/eve.json'):
        """
        Main run loop - watches logs and processes commands.

        Args:
            log_file: Path to Suricata eve.json log
        """
        import threading

        print(f"[+] pfSense Agent started")
        print(f"[+] Hostname: {self.hostname}")
        print(f"[+] Redis: {self.redis_host}:{self.redis_port}")
        print(f"[+] Streams: {self.key_prefix}:*")

        # Publish initial health
        self.publish_health('healthy', 'Agent started')

        # Start command processor in background thread
        command_thread = threading.Thread(target=self.process_commands, daemon=True)
        command_thread.start()

        # Start stats publisher in background thread
        def stats_loop():
            while self.running:
                self.publish_stats()
                self.publish_health('healthy', f'Alerts: {self.stats["alerts_published"]}')
                time.sleep(30)

        stats_thread = threading.Thread(target=stats_loop, daemon=True)
        stats_thread.start()

        # Main thread: watch logs
        try:
            self.watch_eve_log(log_file)
        except KeyboardInterrupt:
            print("\n[*] Interrupted by user")
        finally:
            self.running = False
            self.publish_health('shutdown', 'Agent stopped')


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='pfSense Agent for Redis Streams')
    parser.add_argument('--redis-host', default='localhost', help='Redis server hostname')
    parser.add_argument('--redis-port', type=int, default=6379, help='Redis server port')
    parser.add_argument('--redis-password', default=None, help='Redis password')
    parser.add_argument('--redis-db', type=int, default=0, help='Redis database number')
    parser.add_argument('--key-prefix', default='ai_suricata', help='Redis key prefix')
    parser.add_argument('--log-file', default='/var/log/suricata/eve.json', help='Suricata EVE log path')

    args = parser.parse_args()

    # Create and run agent
    agent = PfSenseAgent(
        redis_host=args.redis_host,
        redis_port=args.redis_port,
        redis_password=args.redis_password,
        redis_db=args.redis_db,
        key_prefix=args.key_prefix
    )

    agent.run(log_file=args.log_file)


if __name__ == '__main__':
    main()

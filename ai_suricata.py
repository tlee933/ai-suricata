#!/usr/bin/env python3
"""
AI Suricata - Intelligent Threat Detection and Response System
Integrates alert collection, ML classification, and automated response
"""

import sys
import os
import argparse
import signal
import time
from datetime import datetime
from alert_collector import SuricataAlertCollector
from ml_classifier import ThreatClassifier
from auto_responder import AutoResponder
from prometheus_exporter import PrometheusExporter
from training_data_collector import TrainingDataCollector
from carbon_exporter import CarbonExporter, PeriodicCarbonExporter
from thermal_monitor import ThermalMonitor
from redis_client import RedisClient

def getenv_stripped(key, default=''):
    """Get environment variable and strip inline comments"""
    value = os.getenv(key, default)
    if isinstance(value, str) and '#' in value:
        # Strip inline comments (everything after #)
        value = value.split('#')[0].strip()
    return value if value else default

class AISuricata:
    def __init__(self, pfsense_host="192.168.1.1", pfsense_user="admin", dry_run=False, auto_block=False, prometheus_port=9102,
                 thermal_monitoring=True, thermal_poll_interval=30, thermal_warn_threshold=75.0, thermal_critical_threshold=85.0):
        print("[*] Initializing AI Suricata System...")

        # Initialize Redis client (optional, graceful degradation if unavailable)
        redis_enabled = getenv_stripped('REDIS_ENABLED', 'true').lower() == 'true'
        redis_host = getenv_stripped('REDIS_HOST', 'localhost')
        redis_port = int(getenv_stripped('REDIS_PORT', '6379'))
        redis_db = int(getenv_stripped('REDIS_DB', '0'))
        redis_password = getenv_stripped('REDIS_PASSWORD', None)
        redis_key_prefix = getenv_stripped('REDIS_KEY_PREFIX', 'ai_suricata')
        redis_socket_timeout = int(getenv_stripped('REDIS_SOCKET_TIMEOUT', '2'))
        redis_socket_keepalive = getenv_stripped('REDIS_SOCKET_KEEPALIVE', 'true').lower() == 'true'

        self.redis_client = None
        if redis_enabled:
            try:
                self.redis_client = RedisClient(
                    enabled=True,
                    host=redis_host,
                    port=redis_port,
                    db=redis_db,
                    password=redis_password if redis_password else None,
                    key_prefix=redis_key_prefix,
                    socket_timeout=redis_socket_timeout,
                    socket_keepalive=redis_socket_keepalive
                )
                if self.redis_client.is_healthy():
                    print("[+] Redis caching enabled and healthy")
                else:
                    print("[!] Redis connection failed, continuing without cache")
                    self.redis_client = None
            except Exception as e:
                print(f"[!] Redis initialization failed: {e}")
                print("[*] Continuing without Redis (graceful degradation)")
                self.redis_client = None
        else:
            print("[*] Redis caching disabled (REDIS_ENABLED=false)")

        # Message queue configuration
        use_message_queue = getenv_stripped('MESSAGE_QUEUE_ENABLED', 'false').lower() == 'true'

        # Always create SSH-based collector for training (needs historical data)
        self.ssh_collector = SuricataAlertCollector(pfsense_host, pfsense_user)

        if use_message_queue and self.redis_client and self.redis_client.is_healthy():
            print("[+] Message queue mode enabled (Redis Streams)")
            # Use stream consumer for live monitoring
            from stream_consumer import RedisStreamConsumer, StreamAlertGenerator

            consumer_group = getenv_stripped('MESSAGE_QUEUE_CONSUMER_GROUP', 'ai-processors')
            consumer_name = getenv_stripped('MESSAGE_QUEUE_CONSUMER_NAME', 'ai-suricata-1')
            use_consumer_groups = getenv_stripped('MESSAGE_QUEUE_USE_CONSUMER_GROUPS', 'true').lower() == 'true'

            stream_consumer = RedisStreamConsumer(
                self.redis_client,
                stream_name=f"{redis_key_prefix}:alerts:stream",
                group_name=consumer_group,
                consumer_name=consumer_name,
                create_group=use_consumer_groups
            )

            self.collector = StreamAlertGenerator(stream_consumer, use_consumer_group=use_consumer_groups)
            self.collector.pfsense_host = pfsense_host  # For compatibility
            self.collector.pfsense_user = pfsense_user
            print(f"[+] Stream consumer initialized: {consumer_group}/{consumer_name}")
            print(f"[*] SSH collector available for training on historical data")
        else:
            # Use traditional SSH-based collector for everything
            if use_message_queue:
                print("[!] Message queue requested but Redis unavailable - falling back to SSH")
            self.collector = self.ssh_collector

        self.classifier = ThreatClassifier()
        self.responder = AutoResponder(pfsense_host, pfsense_user, dry_run=dry_run,
                                       redis_client=self.redis_client,
                                       use_message_queue=use_message_queue)

        self.auto_block = auto_block
        self.running = True

        # Statistics
        self.processed_count = 0
        self.threat_count = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "INFO": 0}

        # Prometheus exporter
        self.exporter = PrometheusExporter(port=prometheus_port)
        self.exporter.start()

        # Carbon/Graphite exporter (optional)
        self.carbon = CarbonExporter(carbon_host='localhost', carbon_port=2003, enabled=True)
        self.carbon_thread = PeriodicCarbonExporter(self.carbon, self.exporter.metrics, interval=10)
        self.carbon_thread.start()

        # Thermal monitor (pfSense temperature monitoring)
        self.thermal_monitor = None
        if thermal_monitoring:
            self.thermal_monitor = ThermalMonitor(
                pfsense_host=pfsense_host,
                pfsense_user=pfsense_user,
                metrics_store=self.exporter.metrics,
                poll_interval=thermal_poll_interval,
                warn_threshold=thermal_warn_threshold,
                critical_threshold=thermal_critical_threshold
            )
            self.thermal_monitor.start()
            print(f"[+] Thermal monitoring enabled (poll: {thermal_poll_interval}s, warn: {thermal_warn_threshold}°C, critical: {thermal_critical_threshold}°C)")

        # Training data collector (for future supervised learning)
        self.data_collector = TrainingDataCollector(enabled=True)

        # Load pre-trained models if available
        if self.classifier.load_models():
            print("[+] Loaded pre-trained ML models")
        else:
            print("[*] No pre-trained models found - will train on incoming data")

        # Setup signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)

    def signal_handler(self, sig, frame):
        """Handle Ctrl+C gracefully"""
        print("\n\n[*] Shutting down AI Suricata...")
        self.running = False

        # Stop thermal monitor
        if self.thermal_monitor:
            self.thermal_monitor.stop()

        # Flush training data buffer
        if self.data_collector:
            self.data_collector.stop()

        # Save final state
        if hasattr(self.exporter, 'state_manager') and self.exporter.state_manager:
            print("[*] Saving state before exit...")
            self.exporter.state_manager.save_state(self.exporter.metrics)

        # Close Redis connection
        if self.redis_client:
            self.redis_client.close()

        self.print_final_summary()
        sys.exit(0)

    def train_on_historical_data(self, num_events=5000):
        """Train models on historical alert data"""
        print(f"[*] Training on historical data ({num_events} events)...")

        feature_vectors = []
        alert_count = 0

        # Always use SSH collector for training (needs historical data from pfSense logs)
        for line in self.ssh_collector.tail_eve_log(follow=False, lines=num_events):
            event = self.ssh_collector.parse_event(line)
            if not event or event.get("event_type") != "alert":
                continue

            alert_data = self.ssh_collector.process_alert(event)
            if alert_data:
                # Extract features for ML training
                features = self.classifier.extract_ml_features(alert_data)
                feature_vectors.append(features)
                alert_count += 1

        if feature_vectors:
            print(f"[+] Extracted {len(feature_vectors)} feature vectors from {alert_count} alerts")
            self.classifier.train_anomaly_detector(feature_vectors)
            self.classifier.save_models()
        else:
            print("[!] No alerts found in historical data")

    def process_alert(self, event):
        """Process a single alert through the full pipeline"""
        start_time = time.time()

        # Step 1: Collect and extract features
        # Use ssh_collector for processing regardless of message queue mode
        # (process_alert method exists on SuricataAlertCollector but not StreamAlertGenerator)
        alert_data = self.ssh_collector.process_alert(event)
        if not alert_data:
            return None

        self.processed_count += 1
        features = alert_data["features"]

        # Step 2: ML classification
        classification = self.classifier.classify_threat(alert_data)

        # Update statistics
        self.threat_count[classification["severity"]] += 1

        # Log classification for training data collection
        feature_vector = self.classifier.extract_ml_features(alert_data)
        self.data_collector.log_classification(
            alert_data=alert_data,
            classification=classification,
            features_vector=feature_vector.tolist() if hasattr(feature_vector, 'tolist') else feature_vector
        )

        # Record metrics to Prometheus
        processing_time = time.time() - start_time
        self.exporter.metrics.record_alert(
            severity=classification["severity"],
            action=classification["action"],
            source_ip=features["src_ip"],
            signature=features["signature"][:80],  # Truncate long signatures
            threat_score=classification["threat_score"],
            processing_time=processing_time
        )
        self.exporter.metrics.record_training_example()

        # Record anomaly score
        if "anomaly_score" in classification:
            self.exporter.metrics.record_anomaly_score(classification["anomaly_score"])

        # Record attack patterns detected
        for pattern in classification.get("attack_patterns", []):
            pattern_name = pattern.get("pattern", "unknown")
            self.exporter.metrics.record_pattern_detection(pattern_name)

        # Step 3: Display alert
        self.display_alert(alert_data, classification)

        # Step 4: Automated response (if enabled)
        if self.auto_block:
            if classification["action"] in ["BLOCK", "RATE_LIMIT"]:
                # Confirm before blocking
                if classification["severity"] == "CRITICAL":
                    print(f"    [!] AUTO-BLOCKING {features['src_ip']} due to CRITICAL threat")
                    result = self.responder.execute_action(alert_data, classification)
                    print(f"    [+] Action result: {result}")
                    if classification["action"] == "BLOCK":
                        self.exporter.metrics.record_block()
                    elif classification["action"] == "RATE_LIMIT":
                        self.exporter.metrics.record_rate_limit()
                else:
                    print(f"    [*] Action recommended: {classification['action']} (not auto-executing)")
            elif classification["action"] == "MONITOR":
                self.responder.monitor_ip(features["src_ip"], alert_data)

        return classification

    def display_alert(self, alert_data, classification):
        """Display formatted alert with classification"""
        f = alert_data["features"]
        c = classification

        timestamp = datetime.now().strftime("%H:%M:%S")

        # Color coding based on severity
        colors = {
            "CRITICAL": "\033[91m\033[1m",  # Bold red
            "HIGH": "\033[91m",             # Red
            "MEDIUM": "\033[93m",           # Yellow
            "LOW": "\033[96m",              # Cyan
            "INFO": "\033[90m"              # Gray
        }
        reset = "\033[0m"

        color = colors.get(c["severity"], "")

        # Main alert line
        output = (
            f"{color}[{timestamp}] [{c['severity']:8s}] "
            f"{f['src_ip']:15s} → {f['dest_ip']:15s}:{f['dest_port']:5d} | "
            f"Score: {c['threat_score']:.2f} | "
            f"Action: {c['action']:12s}"
        )

        # Add signature
        output += f"\n    └─ {f['signature'][:80]}"

        # Add patterns if detected
        if c.get("attack_patterns"):
            patterns_str = ", ".join([
                f"{p['pattern']} ({p['confidence']:.0%})"
                for p in c["attack_patterns"]
            ])
            output += f"\n    └─ Patterns: {patterns_str}"

        # Add recommendation
        if c.get("recommendation"):
            output += f"\n    └─ {c['recommendation']}"

        output += reset
        print(output)

    def monitor_live(self):
        """Start live monitoring and threat response"""
        print("\n" + "="*80)
        print("AI SURICATA - LIVE MONITORING")
        print("="*80)
        print(f"Auto-blocking: {'ENABLED' if self.auto_block else 'DISABLED'}")
        print(f"Dry-run mode: {'YES' if self.responder.dry_run else 'NO'}")
        print("Press Ctrl+C to stop\n")

        try:
            # Check if we're using message queue (StreamAlertGenerator) or SSH collector
            if hasattr(self.collector, 'tail_eve_log'):
                # SSH-based collector - iterate over log lines
                for line in self.collector.tail_eve_log(follow=True):
                    if not self.running:
                        break

                    event = self.collector.parse_event(line)
                    if event and event.get("event_type") == "alert":
                        # Skip checksum errors early (hardware offload false positives)
                        signature = event.get("alert", {}).get("signature", "").lower()
                        if "checksum" in signature or "invalid ack" in signature:
                            continue

                        self.process_alert(event)
            else:
                # Message queue - StreamAlertGenerator is an iterator that yields events directly
                for event in self.collector:
                    if not self.running:
                        break

                    if event and event.get("event_type") == "alert":
                        # Skip checksum errors early (hardware offload false positives)
                        signature = event.get("alert", {}).get("signature", "").lower()
                        if "checksum" in signature or "invalid ack" in signature:
                            continue

                        self.process_alert(event)

                # Periodic cleanup
                if self.processed_count % 1000 == 0 and self.processed_count > 0:
                    self.responder.cleanup_old_blocks(max_age_hours=24)

        except KeyboardInterrupt:
            pass

    def print_final_summary(self):
        """Print final statistics"""
        print("\n" + "="*80)
        print("AI SURICATA - SESSION SUMMARY")
        print("="*80)
        print(f"Total Alerts Processed: {self.processed_count}")
        print(f"\nThreat Distribution:")
        for severity, count in sorted(self.threat_count.items(), key=lambda x: ["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"].index(x[0])):
            pct = (count / max(self.processed_count, 1)) * 100
            print(f"  {severity:8s}: {count:5d} ({pct:5.1f}%)")

        print()
        self.responder.print_stats()
        self.collector.print_summary()

def main():
    parser = argparse.ArgumentParser(description="AI Suricata - Intelligent Threat Detection")
    parser.add_argument("--host", default="192.168.1.1", help="pfSense host")
    parser.add_argument("--user", default="admin", help="pfSense SSH user")
    parser.add_argument("--train", action="store_true", help="Train on historical data first")
    parser.add_argument("--auto-block", action="store_true", help="Enable automatic blocking")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode (no actual blocking)")
    parser.add_argument("--events", type=int, default=5000, help="Number of historical events for training")
    parser.add_argument("--thermal-monitoring", action="store_true", default=True, help="Enable pfSense thermal monitoring (default: enabled)")
    parser.add_argument("--no-thermal-monitoring", dest="thermal_monitoring", action="store_false", help="Disable thermal monitoring")
    parser.add_argument("--thermal-poll-interval", type=int, default=30, help="Thermal sensor poll interval in seconds (default: 30)")
    parser.add_argument("--thermal-warn", type=float, default=75.0, help="Temperature warning threshold in Celsius (default: 75)")
    parser.add_argument("--thermal-critical", type=float, default=85.0, help="Temperature critical threshold in Celsius (default: 85)")

    args = parser.parse_args()

    # Initialize system
    ai_suricata = AISuricata(
        pfsense_host=args.host,
        pfsense_user=args.user,
        dry_run=args.dry_run,
        auto_block=args.auto_block,
        thermal_monitoring=args.thermal_monitoring,
        thermal_poll_interval=args.thermal_poll_interval,
        thermal_warn_threshold=args.thermal_warn,
        thermal_critical_threshold=args.thermal_critical
    )

    # Train on historical data if requested
    if args.train:
        ai_suricata.train_on_historical_data(num_events=args.events)
        print()

    # Start live monitoring
    ai_suricata.monitor_live()

if __name__ == "__main__":
    main()

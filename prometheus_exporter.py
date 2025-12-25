#!/usr/bin/env python3
"""
Prometheus Exporter for AI Suricata
Exposes metrics for threat detection, blocking, and system health
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread, Lock
from collections import defaultdict
import time
from state_manager import StateManager, PeriodicStateSaver

class SuricataMetrics:
    """Thread-safe metrics storage for AI Suricata"""

    def __init__(self):
        self.lock = Lock()
        self.start_time = time.time()

        # Alert counters
        self.total_alerts = 0
        self.alerts_by_severity = defaultdict(int)
        self.alerts_by_action = defaultdict(int)

        # Blocking stats
        self.total_blocks = 0
        self.total_rate_limits = 0
        self.active_blocks = 0

        # IP tracking
        self.top_source_ips = defaultdict(int)
        self.top_signatures = defaultdict(int)

        # Performance
        self.processing_time_sum = 0.0
        self.processing_count = 0

        # Threat scores
        self.threat_score_sum = 0.0
        self.critical_threats = 0
        self.high_threats = 0
        self.training_examples_collected = 0

        # Training data labels
        self.labeled_examples = 0
        self.labels_by_type = defaultdict(int)  # BENIGN, THREAT, FALSE_POSITIVE

        # ML model stats
        self.anomaly_scores = []  # Recent anomaly scores
        self.pattern_detections = defaultdict(int)  # port_scan, dos_attempt, etc

        # Thermal monitoring (pfSense temperatures)
        self.pfsense_temperatures = {}  # Dict of sensor_name: temperature_celsius
        self.pfsense_temp_max = 0.0
        self.pfsense_temp_min = 0.0
        self.pfsense_temp_avg = 0.0
        self.last_thermal_update = 0.0

    def record_training_example(self):
        """Record a training example collected"""
        with self.lock:
            self.training_examples_collected += 1

    def record_label(self, label_type):
        """Record a labeled training example"""
        with self.lock:
            self.labeled_examples += 1
            self.labels_by_type[label_type] += 1

    def record_pattern_detection(self, pattern_name):
        """Record an attack pattern detection"""
        with self.lock:
            self.pattern_detections[pattern_name] += 1

    def record_anomaly_score(self, score):
        """Record anomaly score (keep last 1000)"""
        with self.lock:
            self.anomaly_scores.append(score)
            if len(self.anomaly_scores) > 1000:
                self.anomaly_scores.pop(0)

    def record_alert(self, severity, action, source_ip, signature, threat_score, processing_time=0.0):
        """Record an alert with all its metadata"""
        with self.lock:
            self.total_alerts += 1
            self.alerts_by_severity[severity] += 1
            self.alerts_by_action[action] += 1
            self.top_source_ips[source_ip] += 1
            self.top_signatures[signature] += 1
            self.threat_score_sum += threat_score
            self.processing_time_sum += processing_time
            self.processing_count += 1

            if severity == "CRITICAL":
                self.critical_threats += 1
            elif severity == "HIGH":
                self.high_threats += 1

    def record_block(self):
        """Record a blocked IP"""
        with self.lock:
            self.total_blocks += 1
            self.active_blocks += 1

    def record_unblock(self):
        """Record an unblocked IP"""
        with self.lock:
            self.active_blocks = max(0, self.active_blocks - 1)

    def record_rate_limit(self):
        """Record a rate-limited IP"""
        with self.lock:
            self.total_rate_limits += 1

    def record_pfsense_temperatures(self, temps, max_temp, min_temp, avg_temp):
        """
        Record pfSense thermal sensor readings

        Args:
            temps: Dict of sensor_name: temperature_celsius
            max_temp: Maximum temperature across all sensors
            min_temp: Minimum temperature across all sensors
            avg_temp: Average temperature across all sensors
        """
        with self.lock:
            self.pfsense_temperatures = temps.copy()
            self.pfsense_temp_max = max_temp
            self.pfsense_temp_min = min_temp
            self.pfsense_temp_avg = avg_temp
            self.last_thermal_update = time.time()

    def get_prometheus_metrics(self):
        """Generate Prometheus-formatted metrics"""
        with self.lock:
            uptime = time.time() - self.start_time
            avg_processing_time = self.processing_time_sum / max(1, self.processing_count)
            avg_threat_score = self.threat_score_sum / max(1, self.total_alerts)

            metrics = []

            # Basic info
            metrics.append('# HELP suricata_ai_uptime_seconds Uptime of AI Suricata service')
            metrics.append('# TYPE suricata_ai_uptime_seconds gauge')
            metrics.append(f'suricata_ai_uptime_seconds {uptime:.2f}')

            # Total alerts
            metrics.append('# HELP suricata_ai_alerts_total Total number of alerts processed')
            metrics.append('# TYPE suricata_ai_alerts_total counter')
            metrics.append(f'suricata_ai_alerts_total {self.total_alerts}')

            # Alerts by severity
            metrics.append('# HELP suricata_ai_alerts_by_severity_total Alerts by severity level')
            metrics.append('# TYPE suricata_ai_alerts_by_severity_total counter')
            for severity, count in self.alerts_by_severity.items():
                metrics.append(f'suricata_ai_alerts_by_severity_total{{severity="{severity}"}} {count}')

            # Alerts by action
            metrics.append('# HELP suricata_ai_alerts_by_action_total Alerts by recommended action')
            metrics.append('# TYPE suricata_ai_alerts_by_action_total counter')
            for action, count in self.alerts_by_action.items():
                metrics.append(f'suricata_ai_alerts_by_action_total{{action="{action}"}} {count}')

            # Blocking stats
            metrics.append('# HELP suricata_ai_blocks_total Total IPs blocked')
            metrics.append('# TYPE suricata_ai_blocks_total counter')
            metrics.append(f'suricata_ai_blocks_total {self.total_blocks}')

            metrics.append('# HELP suricata_ai_active_blocks Currently active blocks')
            metrics.append('# TYPE suricata_ai_active_blocks gauge')
            metrics.append(f'suricata_ai_active_blocks {self.active_blocks}')

            metrics.append('# HELP suricata_ai_rate_limits_total Total IPs rate-limited')
            metrics.append('# TYPE suricata_ai_rate_limits_total counter')
            metrics.append(f'suricata_ai_rate_limits_total {self.total_rate_limits}')

            # Threat metrics
            metrics.append('# HELP suricata_ai_critical_threats_total Critical threats detected')
            metrics.append('# TYPE suricata_ai_critical_threats_total counter')
            metrics.append(f'suricata_ai_critical_threats_total {self.critical_threats}')

            metrics.append('# HELP suricata_ai_high_threats_total High severity threats detected')
            metrics.append('# TYPE suricata_ai_high_threats_total counter')
            metrics.append(f'suricata_ai_high_threats_total {self.high_threats}')

            # Average scores
            metrics.append('# HELP suricata_ai_avg_threat_score Average threat score')
            metrics.append('# TYPE suricata_ai_avg_threat_score gauge')
            metrics.append(f'suricata_ai_avg_threat_score {avg_threat_score:.3f}')

            # Performance
            metrics.append('# HELP suricata_ai_processing_time_seconds Average alert processing time')
            metrics.append('# TYPE suricata_ai_processing_time_seconds gauge')
            metrics.append(f'suricata_ai_processing_time_seconds {avg_processing_time:.6f}')

            metrics.append('# HELP suricata_ai_alerts_per_second Current alert rate')
            metrics.append('# TYPE suricata_ai_alerts_per_second gauge')
            rate = self.total_alerts / max(1, uptime)
            metrics.append(f'suricata_ai_alerts_per_second {rate:.2f}')

            # Top source IPs (top 10)
            metrics.append('# HELP suricata_ai_top_source_ips Alerts by source IP')
            metrics.append('# TYPE suricata_ai_top_source_ips gauge')
            for ip, count in sorted(self.top_source_ips.items(), key=lambda x: x[1], reverse=True)[:10]:
                metrics.append(f'suricata_ai_top_source_ips{{source_ip="{ip}"}} {count}')

            # Training data collection
            metrics.append('# HELP suricata_ai_training_examples_total Training examples collected for supervised learning')
            metrics.append('# TYPE suricata_ai_training_examples_total counter')
            metrics.append(f'suricata_ai_training_examples_total {self.training_examples_collected}')

            # Labeled training examples
            metrics.append('# HELP suricata_ai_labeled_examples_total Labeled training examples')
            metrics.append('# TYPE suricata_ai_labeled_examples_total counter')
            metrics.append(f'suricata_ai_labeled_examples_total {self.labeled_examples}')

            # Labeling progress percentage
            labeling_progress = (self.labeled_examples / max(1, self.training_examples_collected)) * 100
            metrics.append('# HELP suricata_ai_labeling_progress_percent Percentage of examples labeled')
            metrics.append('# TYPE suricata_ai_labeling_progress_percent gauge')
            metrics.append(f'suricata_ai_labeling_progress_percent {labeling_progress:.2f}')

            # Labels by type
            metrics.append('# HELP suricata_ai_labels_by_type_total Labels by type (BENIGN, THREAT, FALSE_POSITIVE)')
            metrics.append('# TYPE suricata_ai_labels_by_type_total counter')
            for label_type, count in self.labels_by_type.items():
                metrics.append(f'suricata_ai_labels_by_type_total{{label_type="{label_type}"}} {count}')

            # Attack pattern detections
            metrics.append('# HELP suricata_ai_pattern_detections_total Attack patterns detected')
            metrics.append('# TYPE suricata_ai_pattern_detections_total counter')
            for pattern, count in self.pattern_detections.items():
                metrics.append(f'suricata_ai_pattern_detections_total{{pattern="{pattern}"}} {count}')

            # Anomaly score statistics
            if self.anomaly_scores:
                avg_anomaly = sum(self.anomaly_scores) / len(self.anomaly_scores)
                max_anomaly = max(self.anomaly_scores)
                min_anomaly = min(self.anomaly_scores)

                metrics.append('# HELP suricata_ai_avg_anomaly_score Average anomaly score (last 1000)')
                metrics.append('# TYPE suricata_ai_avg_anomaly_score gauge')
                metrics.append(f'suricata_ai_avg_anomaly_score {avg_anomaly:.3f}')

                metrics.append('# HELP suricata_ai_max_anomaly_score Maximum anomaly score (last 1000)')
                metrics.append('# TYPE suricata_ai_max_anomaly_score gauge')
                metrics.append(f'suricata_ai_max_anomaly_score {max_anomaly:.3f}')

                metrics.append('# HELP suricata_ai_min_anomaly_score Minimum anomaly score (last 1000)')
                metrics.append('# TYPE suricata_ai_min_anomaly_score gauge')
                metrics.append(f'suricata_ai_min_anomaly_score {min_anomaly:.3f}')

            # pfSense Thermal Monitoring
            if self.pfsense_temperatures:
                metrics.append('# HELP pfsense_cpu_temp_celsius CPU and system temperature in Celsius')
                metrics.append('# TYPE pfsense_cpu_temp_celsius gauge')
                for sensor_name, temp in self.pfsense_temperatures.items():
                    # Convert sensor name to label-safe format
                    # e.g., "hw.acpi.thermal.tz0.temperature" -> "hw_acpi_thermal_tz0"
                    sensor_label = sensor_name.replace('.temperature', '').replace('.', '_')
                    metrics.append(f'pfsense_cpu_temp_celsius{{sensor="{sensor_label}"}} {temp:.1f}')

                metrics.append('# HELP pfsense_cpu_temp_max_celsius Maximum temperature across all sensors')
                metrics.append('# TYPE pfsense_cpu_temp_max_celsius gauge')
                metrics.append(f'pfsense_cpu_temp_max_celsius {self.pfsense_temp_max:.1f}')

                metrics.append('# HELP pfsense_cpu_temp_avg_celsius Average temperature across all sensors')
                metrics.append('# TYPE pfsense_cpu_temp_avg_celsius gauge')
                metrics.append(f'pfsense_cpu_temp_avg_celsius {self.pfsense_temp_avg:.1f}')

                metrics.append('# HELP pfsense_cpu_temp_min_celsius Minimum temperature across all sensors')
                metrics.append('# TYPE pfsense_cpu_temp_min_celsius gauge')
                metrics.append(f'pfsense_cpu_temp_min_celsius {self.pfsense_temp_min:.1f}')

                # Thermal monitoring freshness
                thermal_age = time.time() - self.last_thermal_update
                metrics.append('# HELP pfsense_thermal_data_age_seconds Age of last thermal data collection')
                metrics.append('# TYPE pfsense_thermal_data_age_seconds gauge')
                metrics.append(f'pfsense_thermal_data_age_seconds {thermal_age:.1f}')

            return '\n'.join(metrics) + '\n'

class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler for Prometheus metrics endpoint"""

    metrics_store = None  # Will be set by PrometheusExporter

    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/metrics':
            metrics = self.metrics_store.get_prometheus_metrics()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(metrics.encode('utf-8'))
        elif self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK\n')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress request logging"""
        pass

class PrometheusExporter:
    """Prometheus metrics exporter for AI Suricata"""

    def __init__(self, port=9102, enable_persistence=True):
        self.port = port
        self.metrics = SuricataMetrics()
        self.server = None
        self.thread = None
        self.enable_persistence = enable_persistence

        # State persistence
        if self.enable_persistence:
            self.state_manager = StateManager()
            self.state_saver = None
        else:
            self.state_manager = None
            self.state_saver = None

        # Set metrics store for handler
        MetricsHandler.metrics_store = self.metrics

    def start(self):
        """Start the metrics HTTP server in a background thread"""
        # Restore persisted state
        if self.enable_persistence and self.state_manager:
            self.state_manager.restore_state(self.metrics)
            # Start periodic state saver
            self.state_saver = PeriodicStateSaver(self.state_manager, self.metrics, interval=60)
            self.state_saver.start()

        self.server = HTTPServer(('0.0.0.0', self.port), MetricsHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"[*] Prometheus exporter started on http://0.0.0.0:{self.port}/metrics")

    def stop(self):
        """Stop the metrics HTTP server"""
        # Save state before shutdown
        if self.enable_persistence and self.state_manager:
            print("[*] Saving final state...")
            self.state_manager.save_state(self.metrics)
            if self.state_saver:
                self.state_saver.stop()

        if self.server:
            self.server.shutdown()
            self.thread.join()

if __name__ == "__main__":
    # Test the exporter
    exporter = PrometheusExporter(port=9101)
    exporter.start()

    # Simulate some metrics
    import random
    print("[*] Simulating metrics for testing...")
    for i in range(100):
        severity = random.choice(["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"])
        action = random.choice(["BLOCK", "RATE_LIMIT", "MONITOR", "LOG", "IGNORE"])
        ip = f"192.168.1.{random.randint(10, 250)}"
        signature = random.choice(["Port Scan", "DoS Attack", "Brute Force", "Malware", "Suspicious Traffic"])
        score = random.random()

        exporter.metrics.record_alert(severity, action, ip, signature, score, random.random() * 0.001)

        if action == "BLOCK":
            exporter.metrics.record_block()
        elif action == "RATE_LIMIT":
            exporter.metrics.record_rate_limit()

    print(f"[*] Test metrics available at http://localhost:9101/metrics")
    print("[*] Press Ctrl+C to stop")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[*] Stopping exporter...")
        exporter.stop()

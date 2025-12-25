#!/usr/bin/env python3
"""
Carbon/Graphite Exporter for AI Suricata
Sends metrics to Graphite/Carbon for additional monitoring
"""

import socket
import time
from threading import Thread, Lock

class CarbonExporter:
    """Exports metrics to Carbon/Graphite"""

    def __init__(self, carbon_host='localhost', carbon_port=2003, prefix='ai_suricata', enabled=True):
        self.carbon_host = carbon_host
        self.carbon_port = carbon_port
        self.prefix = prefix
        self.enabled = enabled
        self.lock = Lock()
        self.metrics = {}

        if self.enabled:
            print(f"[+] Carbon exporter enabled: {carbon_host}:{carbon_port}")

    def send_metric(self, name, value, timestamp=None):
        """Send a single metric to Carbon"""
        if not self.enabled:
            return

        if timestamp is None:
            timestamp = int(time.time())

        metric_path = f"{self.prefix}.{name}"

        try:
            message = f"{metric_path} {value} {timestamp}\n"
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((self.carbon_host, self.carbon_port))
            sock.sendall(message.encode())
            sock.close()
        except Exception as e:
            # Don't crash on carbon errors
            pass

    def send_batch(self, metrics_dict, timestamp=None):
        """Send multiple metrics at once"""
        if not self.enabled:
            return

        if timestamp is None:
            timestamp = int(time.time())

        try:
            messages = []
            for name, value in metrics_dict.items():
                metric_path = f"{self.prefix}.{name}"
                messages.append(f"{metric_path} {value} {timestamp}")

            message = '\n'.join(messages) + '\n'

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((self.carbon_host, self.carbon_port))
            sock.sendall(message.encode())
            sock.close()
        except Exception as e:
            # Don't crash on carbon errors
            pass

    def export_from_prometheus_metrics(self, prom_metrics):
        """Convert Prometheus metrics object to Carbon metrics"""
        if not self.enabled:
            return

        with prom_metrics.lock:
            metrics = {
                'alerts.total': prom_metrics.total_alerts,
                'alerts.rate': prom_metrics.total_alerts / max(1, time.time() - prom_metrics.start_time),
                'threats.critical': prom_metrics.critical_threats,
                'threats.high': prom_metrics.high_threats,
                'blocks.active': prom_metrics.active_blocks,
                'blocks.total': prom_metrics.total_blocks,
                'rate_limits.total': prom_metrics.total_rate_limits,
                'processing.time_ms': (prom_metrics.processing_time_sum / max(1, prom_metrics.processing_count)) * 1000,
                'training.examples_collected': prom_metrics.training_examples_collected,
                'training.examples_labeled': prom_metrics.labeled_examples,
            }

            # Severity breakdown
            for severity, count in prom_metrics.alerts_by_severity.items():
                metrics[f'alerts.severity.{severity.lower()}'] = count

            # Action breakdown
            for action, count in prom_metrics.alerts_by_action.items():
                metrics[f'alerts.action.{action.lower()}'] = count

            # Label distribution
            for label_type, count in prom_metrics.labels_by_type.items():
                metrics[f'training.labels.{label_type.lower()}'] = count

            # Pattern detections
            for pattern, count in prom_metrics.pattern_detections.items():
                metrics[f'patterns.{pattern}'] = count

            # Anomaly scores
            if prom_metrics.anomaly_scores:
                metrics['ml.anomaly_score.avg'] = sum(prom_metrics.anomaly_scores) / len(prom_metrics.anomaly_scores)
                metrics['ml.anomaly_score.max'] = max(prom_metrics.anomaly_scores)
                metrics['ml.anomaly_score.min'] = min(prom_metrics.anomaly_scores)

            # Threat score
            if prom_metrics.total_alerts > 0:
                metrics['ml.threat_score.avg'] = prom_metrics.threat_score_sum / prom_metrics.total_alerts

        self.send_batch(metrics)


class PeriodicCarbonExporter(Thread):
    """Background thread that periodically exports to Carbon"""

    def __init__(self, carbon_exporter, prom_metrics, interval=10):
        super().__init__(daemon=True)
        self.carbon_exporter = carbon_exporter
        self.prom_metrics = prom_metrics
        self.interval = interval
        self.running = True

    def run(self):
        """Export metrics every interval seconds"""
        while self.running:
            try:
                self.carbon_exporter.export_from_prometheus_metrics(self.prom_metrics)
            except Exception as e:
                pass  # Don't crash the thread

            time.sleep(self.interval)

    def stop(self):
        """Stop the exporter thread"""
        self.running = False

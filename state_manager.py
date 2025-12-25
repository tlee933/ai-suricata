#!/usr/bin/env python3
"""
Persistent State Manager for AI Suricata
Saves and restores Prometheus counter state across restarts
"""

import json
import time
from pathlib import Path
from threading import Thread, Lock
from datetime import datetime


class StateManager:
    """Manages persistent state for counters and metrics"""

    def __init__(self, state_file="/home/hashcat/pfsense/ai_suricata/state/metrics_state.json"):
        self.state_file = Path(state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self.state = {}
        self.last_save = time.time()

    def load_state(self):
        """Load persisted state from disk"""
        if not self.state_file.exists():
            print("[*] No previous state found - starting fresh")
            return {}

        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
                last_saved = state.get('last_saved', 'unknown')
                print(f"[+] Loaded persisted state from {last_saved}")
                return state
        except Exception as e:
            print(f"[!] Failed to load state: {e}")
            return {}

    def save_state(self, metrics):
        """Save current metrics state to disk"""
        with self.lock:
            try:
                state_data = {
                    'last_saved': datetime.now().isoformat(),
                    'counters': {
                        'total_alerts': metrics.total_alerts,
                        'alerts_by_severity': dict(metrics.alerts_by_severity),
                        'alerts_by_action': dict(metrics.alerts_by_action),
                        'total_blocks': metrics.total_blocks,
                        'total_rate_limits': metrics.total_rate_limits,
                        'active_blocks': metrics.active_blocks,
                        'critical_threats': metrics.critical_threats,
                        'high_threats': metrics.high_threats,
                        'threat_score_sum': metrics.threat_score_sum,
                        'processing_time_sum': metrics.processing_time_sum,
                        'processing_count': metrics.processing_count,
                        'training_examples_collected': metrics.training_examples_collected,
                        'labeled_examples': metrics.labeled_examples,
                        'labels_by_type': dict(metrics.labels_by_type),
                        'pattern_detections': dict(metrics.pattern_detections),
                    },
                    'top_ips': dict(list(metrics.top_source_ips.items())[:50]),  # Keep top 50
                }

                # Atomic write (write to temp file, then rename)
                temp_file = self.state_file.with_suffix('.tmp')
                with open(temp_file, 'w') as f:
                    json.dump(state_data, f, indent=2)
                temp_file.rename(self.state_file)

                self.last_save = time.time()
                return True

            except Exception as e:
                print(f"[!] Failed to save state: {e}")
                return False

    def restore_state(self, metrics):
        """Restore metrics from persisted state"""
        state = self.load_state()
        if not state or 'counters' not in state:
            return False

        counters = state['counters']

        with metrics.lock:
            # Restore counter values
            metrics.total_alerts = counters.get('total_alerts', 0)
            metrics.alerts_by_severity.update(counters.get('alerts_by_severity', {}))
            metrics.alerts_by_action.update(counters.get('alerts_by_action', {}))
            metrics.total_blocks = counters.get('total_blocks', 0)
            metrics.total_rate_limits = counters.get('total_rate_limits', 0)
            metrics.active_blocks = counters.get('active_blocks', 0)
            metrics.critical_threats = counters.get('critical_threats', 0)
            metrics.high_threats = counters.get('high_threats', 0)
            metrics.threat_score_sum = counters.get('threat_score_sum', 0.0)
            metrics.processing_time_sum = counters.get('processing_time_sum', 0.0)
            metrics.processing_count = counters.get('processing_count', 0)
            metrics.training_examples_collected = counters.get('training_examples_collected', 0)
            metrics.labeled_examples = counters.get('labeled_examples', 0)
            metrics.labels_by_type.update(counters.get('labels_by_type', {}))
            metrics.pattern_detections.update(counters.get('pattern_detections', {}))

            # Restore top IPs
            if 'top_ips' in state:
                metrics.top_source_ips.update(state['top_ips'])

            print(f"[+] Restored state: {metrics.total_alerts:,} alerts, "
                  f"{metrics.labeled_examples} labeled examples, "
                  f"{metrics.critical_threats} critical threats")

        return True


class PeriodicStateSaver(Thread):
    """Background thread that periodically saves state"""

    def __init__(self, state_manager, metrics, interval=60):
        super().__init__(daemon=True)
        self.state_manager = state_manager
        self.metrics = metrics
        self.interval = interval
        self.running = True

    def run(self):
        """Save state every interval seconds"""
        print(f"[*] State auto-save enabled (every {self.interval}s)")

        while self.running:
            time.sleep(self.interval)
            try:
                self.state_manager.save_state(self.metrics)
            except Exception as e:
                # Don't crash the thread
                pass

    def stop(self):
        """Stop the saver thread"""
        self.running = False


if __name__ == "__main__":
    # Test the state manager
    from prometheus_exporter import SuricataMetrics

    print("[*] Testing State Manager...")

    # Create mock metrics
    metrics = SuricataMetrics()
    metrics.total_alerts = 12345
    metrics.critical_threats = 42
    metrics.labeled_examples = 100

    # Test save
    manager = StateManager(state_file="/tmp/test_state.json")
    manager.save_state(metrics)
    print("[+] State saved")

    # Test restore
    new_metrics = SuricataMetrics()
    manager.restore_state(new_metrics)
    print(f"[+] State restored: {new_metrics.total_alerts} alerts")

    assert new_metrics.total_alerts == 12345
    assert new_metrics.critical_threats == 42
    assert new_metrics.labeled_examples == 100

    print("[+] All tests passed!")

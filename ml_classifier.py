#!/usr/bin/env python3
"""
AI-powered Suricata Alert Classifier
Uses machine learning to classify and respond to security threats
"""

import json
import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from collections import defaultdict, deque
import pickle
import os

class ThreatClassifier:
    def __init__(self, model_path="/home/hashcat/pfsense/ai_suricata/models"):
        self.model_path = model_path
        os.makedirs(model_path, exist_ok=True)

        # Anomaly detection (unsupervised)
        self.anomaly_detector = IsolationForest(
            contamination=0.1,  # Expect 10% anomalies
            random_state=42
        )

        # Threat classification (supervised - will train on labeled data)
        self.classifier = None
        self.scaler = StandardScaler()

        # Behavioral tracking
        self.ip_behavior = defaultdict(lambda: {
            "alert_rate": deque(maxlen=100),  # Rolling window
            "port_scan_score": 0.0,
            "unique_dest_ips": set(),
            "unique_dest_ports": set(),
            "protocol_distribution": defaultdict(int),
            "first_seen": None,
            "last_alert_time": None
        })

        # Known threat patterns (simple rule-based for bootstrap)
        self.threat_patterns = {
            "port_scan": {
                "unique_ports_threshold": 20,
                "time_window_seconds": 60
            },
            "dos_attack": {
                "alerts_per_second_threshold": 10
            },
            "brute_force": {
                "failed_auth_threshold": 5,
                "time_window_seconds": 300
            }
        }

    def extract_ml_features(self, alert_data):
        """Extract numerical features for ML models"""
        features = alert_data["features"]
        stats = alert_data

        # Numerical features vector
        feature_vector = [
            # Alert metadata
            features["severity"],
            features["src_port"],
            features["dest_port"],

            # Flow statistics
            features["pkts_toserver"],
            features["pkts_toclient"],
            features["bytes_toserver"],
            features["bytes_toclient"],

            # Derived features
            features["bytes_toserver"] / max(features["pkts_toserver"], 1),  # Avg packet size
            features["bytes_toclient"] / max(features["pkts_toclient"], 1),

            # Behavioral features
            stats.get("ip_alert_count", 0),
            stats.get("ip_unique_signatures", 0),

            # Protocol encoding (simple)
            1 if features["proto"] == "TCP" else 0,
            1 if features["proto"] == "UDP" else 0,

            # Port indicators
            1 if features["dest_port"] in [22, 23, 3389] else 0,  # Auth ports
            1 if features["dest_port"] in [80, 443, 8080] else 0,  # Web ports
            1 if features["dest_port"] < 1024 else 0,  # Privileged ports
        ]

        return np.array(feature_vector, dtype=np.float32)

    def update_behavioral_profile(self, alert_data):
        """Update behavioral profile for source IP"""
        features = alert_data["features"]
        src_ip = features["src_ip"]
        timestamp = features["timestamp"]

        profile = self.ip_behavior[src_ip]

        # Update counters
        profile["alert_rate"].append(timestamp)
        profile["unique_dest_ips"].add(features["dest_ip"])
        profile["unique_dest_ports"].add(features["dest_port"])
        profile["protocol_distribution"][features["proto"]] += 1

        if profile["first_seen"] is None:
            profile["first_seen"] = timestamp
        profile["last_alert_time"] = timestamp

        # Calculate port scan score
        unique_ports = len(profile["unique_dest_ports"])
        if unique_ports > self.threat_patterns["port_scan"]["unique_ports_threshold"]:
            profile["port_scan_score"] = min(1.0, unique_ports / 100.0)

        return profile

    def detect_anomaly(self, feature_vector):
        """Detect if alert is anomalous using Isolation Forest"""
        try:
            # Reshape for single prediction
            X = feature_vector.reshape(1, -1)

            # Predict (-1 = anomaly, 1 = normal)
            prediction = self.anomaly_detector.predict(X)
            score = self.anomaly_detector.score_samples(X)[0]

            # Convert to 0-1 score (lower = more anomalous)
            anomaly_score = 1.0 / (1.0 + np.exp(score))  # Sigmoid normalization

            return {
                "is_anomaly": prediction[0] == -1,
                "anomaly_score": anomaly_score
            }
        except:
            # Model not trained yet
            return {"is_anomaly": False, "anomaly_score": 0.0}

    def detect_attack_patterns(self, src_ip, profile):
        """Rule-based attack pattern detection"""
        patterns_detected = []

        # Port scanning
        if profile["port_scan_score"] > 0.5:
            patterns_detected.append({
                "pattern": "port_scan",
                "confidence": profile["port_scan_score"],
                "details": f"{len(profile['unique_dest_ports'])} unique ports scanned"
            })

        # DoS attempt (high alert rate)
        if len(profile["alert_rate"]) > 50:
            recent_alerts = sum(1 for _ in profile["alert_rate"])
            alerts_per_second = recent_alerts / 60.0  # Last 100 alerts over time
            if alerts_per_second > 5:
                patterns_detected.append({
                    "pattern": "dos_attempt",
                    "confidence": min(1.0, alerts_per_second / 10.0),
                    "details": f"{alerts_per_second:.1f} alerts/sec"
                })

        # Scanning multiple IPs
        if len(profile["unique_dest_ips"]) > 10:
            patterns_detected.append({
                "pattern": "network_scan",
                "confidence": min(1.0, len(profile["unique_dest_ips"]) / 50.0),
                "details": f"{len(profile['unique_dest_ips'])} unique destinations"
            })

        return patterns_detected

    def classify_threat(self, alert_data):
        """Comprehensive threat classification"""
        features = alert_data["features"]
        src_ip = features["src_ip"]

        # Update behavioral profile
        profile = self.update_behavioral_profile(alert_data)

        # Extract ML features
        feature_vector = self.extract_ml_features(alert_data)

        # Anomaly detection
        anomaly_result = self.detect_anomaly(feature_vector)

        # Pattern detection
        attack_patterns = self.detect_attack_patterns(src_ip, profile)

        # Calculate composite threat score
        base_score = alert_data.get("threat_score", 0.0)
        anomaly_score = anomaly_result["anomaly_score"]
        pattern_score = max([p["confidence"] for p in attack_patterns], default=0.0)

        # Weighted combination
        threat_score = (
            base_score * 0.3 +
            anomaly_score * 0.3 +
            pattern_score * 0.4
        )

        # Classify severity
        if threat_score >= 0.85 or any(p["confidence"] > 0.9 for p in attack_patterns):
            severity = "CRITICAL"
            action = "BLOCK"
        elif threat_score >= 0.7:
            severity = "HIGH"
            action = "RATE_LIMIT"
        elif threat_score >= 0.5:
            severity = "MEDIUM"
            action = "MONITOR"
        elif threat_score >= 0.3:
            severity = "LOW"
            action = "LOG"
        else:
            severity = "INFO"
            action = "IGNORE"

        return {
            "severity": severity,
            "action": action,
            "threat_score": threat_score,
            "anomaly_score": anomaly_score,
            "is_anomaly": anomaly_result["is_anomaly"],
            "attack_patterns": attack_patterns,
            "behavioral_profile": {
                "total_alerts": len(profile["alert_rate"]),
                "unique_dest_ips": len(profile["unique_dest_ips"]),
                "unique_dest_ports": len(profile["unique_dest_ports"]),
                "port_scan_score": profile["port_scan_score"]
            },
            "recommendation": self._generate_recommendation(severity, attack_patterns)
        }

    def _generate_recommendation(self, severity, patterns):
        """Generate actionable recommendations"""
        if severity == "CRITICAL":
            return "Immediate blocking recommended. High-confidence threat detected."
        elif severity == "HIGH":
            if any(p["pattern"] == "port_scan" for p in patterns):
                return "Port scanning detected. Consider rate limiting and enhanced monitoring."
            elif any(p["pattern"] == "dos_attempt" for p in patterns):
                return "Possible DoS attack. Implement connection rate limiting."
            else:
                return "Elevated threat level. Monitor closely and prepare to block if escalates."
        elif severity == "MEDIUM":
            return "Suspicious activity. Continue monitoring and collect more evidence."
        else:
            return "Low risk. Normal logging sufficient."

    def train_anomaly_detector(self, feature_vectors):
        """Train the anomaly detection model"""
        if len(feature_vectors) < 50:
            print("[!] Need at least 50 samples to train anomaly detector")
            return False

        X = np.array(feature_vectors)
        self.anomaly_detector.fit(X)
        print(f"[+] Anomaly detector trained on {len(feature_vectors)} samples")
        return True

    def save_models(self):
        """Save trained models to disk"""
        model_file = os.path.join(self.model_path, "threat_classifier.pkl")
        with open(model_file, 'wb') as f:
            pickle.dump({
                "anomaly_detector": self.anomaly_detector,
                "scaler": self.scaler,
                "ip_behavior": dict(self.ip_behavior)
            }, f)
        print(f"[+] Models saved to {model_file}")

    def load_models(self):
        """Load pre-trained models"""
        model_file = os.path.join(self.model_path, "threat_classifier.pkl")
        if os.path.exists(model_file):
            with open(model_file, 'rb') as f:
                data = pickle.load(f)
                self.anomaly_detector = data["anomaly_detector"]
                self.scaler = data["scaler"]
                self.ip_behavior = defaultdict(lambda: {
                    "alert_rate": deque(maxlen=100),
                    "port_scan_score": 0.0,
                    "unique_dest_ips": set(),
                    "unique_dest_ports": set(),
                    "protocol_distribution": defaultdict(int),
                    "first_seen": None,
                    "last_alert_time": None
                }, data.get("ip_behavior", {}))
            print(f"[+] Models loaded from {model_file}")
            return True
        return False

if __name__ == "__main__":
    # Test the classifier
    classifier = ThreatClassifier()

    # Simulate alert data
    test_alert = {
        "features": {
            "timestamp": "2025-12-21T20:00:00",
            "src_ip": "192.168.1.100",
            "dest_ip": "8.8.8.8",
            "src_port": 54321,
            "dest_port": 53,
            "proto": "UDP",
            "in_iface": "em2",
            "signature": "Test Alert",
            "signature_id": 123456,
            "category": "Test",
            "severity": 2,
            "action": "allowed",
            "pkts_toserver": 10,
            "pkts_toclient": 10,
            "bytes_toserver": 1000,
            "bytes_toclient": 2000
        },
        "threat_score": 0.5,
        "ip_alert_count": 5,
        "ip_unique_signatures": 2
    }

    result = classifier.classify_threat(test_alert)
    print(json.dumps(result, indent=2, default=str))

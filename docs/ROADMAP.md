# Neural Firewall Guardian - Roadmap

**Strategic Plan for ML Evolution & Feature Development**

---

## Current State (v1.0)

**Status:** Production-ready, performing excellently

```
✅ IsolationForest anomaly detection (99.96% accuracy)
✅ Real-time behavioral profiling
✅ Automated threat response (block/rate-limit)
✅ Prometheus metrics & Grafana dashboards
✅ 289,391+ alerts processed successfully
✅ Zero false positives in production
```

**Decision:** Don't fix what isn't broken. Focus on **data collection** and **incremental improvements**.

---

## Phase 1: Data Collection Foundation (Current Priority)

**Timeline:** Immediate implementation
**Goal:** Collect labeled data for future supervised learning without disrupting production

### 1.1 Classification Decision Logging

**What:** Log every ML classification decision for future analysis

**Implementation:**
```python
# New file: training_data_collector.py
{
    "timestamp": "2025-12-23T10:30:45.123Z",
    "source_ip": "23.47.49.240",
    "dest_ip": "192.168.1.100",
    "signature": "SURICATA STREAM packet out of window",
    "signature_id": 2200073,

    # Feature vector (16 dimensions)
    "features": {
        "severity": 2,
        "src_port": 443,
        "dest_port": 54321,
        "packets_toserver": 15,
        "bytes_toserver": 8192,
        # ... all 16 features
    },

    # ML decision
    "classification": {
        "base_score": 0.10,
        "anomaly_score": 0.05,
        "pattern_score": 0.02,
        "threat_score": 0.057,
        "severity": "LOW",
        "action": "LOG"
    },

    # User feedback (added later)
    "label": null,  # Will be: "THREAT" | "BENIGN" | "FALSE_POSITIVE"
    "labeled_by": null,
    "labeled_at": null,
    "notes": null
}
```

**Storage:**
- Format: JSONL (JSON Lines - one object per line)
- Location: `~/pfsense/ai_suricata/training_data/decisions.jsonl`
- Rotation: Daily files (decisions.2025-12-23.jsonl)
- Retention: 6 months
- Size estimate: ~1 KB/alert = ~300 MB/day at current volume

**Benefits:**
- Complete audit trail of ML decisions
- Training data for future RandomForest
- Debugging false positives/negatives
- Performance analysis over time

---

### 1.2 User Feedback Interface

**What:** Simple CLI tool to review and label classifications

**Implementation:**
```bash
# Review recent HIGH/CRITICAL classifications
./review_threats.py --since "24 hours" --severity HIGH,CRITICAL

# Output:
┌─────────────────────────────────────────────────────────────┐
│ Threat Review - 3 classifications found                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│ [1] 2025-12-23 10:45:32                                     │
│     Source: 192.0.2.45                                      │
│     Signature: ET SCAN Potential SSH Scan                   │
│     Score: 0.78 (HIGH)                                      │
│     Action: RATE_LIMIT                                      │
│     Pattern: Port scan detected (45 unique ports)           │
│                                                              │
│     Was this a real threat? [T]hreat / [B]enign / [S]kip    │
│     > _                                                      │
└─────────────────────────────────────────────────────────────┘
```

**Features:**
- Review blocked/rate-limited IPs
- Confirm or reject ML decisions
- Add notes explaining reasoning
- Bulk labeling for similar patterns

---

### 1.3 Automated Labeling Heuristics

**What:** Auto-label obvious cases to reduce manual work

**Rules:**
```python
# Auto-label as BENIGN
if source_ip in WHITELIST_IPS:
    label = "BENIGN"

if signature in ["checksum", "invalid ack", "packet out of window"]:
    label = "BENIGN"

# Auto-label as THREAT
if action_taken == "BLOCK" and no_user_complaints_for_24h:
    label = "THREAT"

if signature_id in KNOWN_EXPLOIT_SIGS:
    label = "THREAT"
```

**Benefits:**
- Reduces manual labeling from 289k → ~500 alerts
- Focus human review on ambiguous cases
- Faster dataset preparation

---

## Phase 2: Supervised Learning Implementation

**Timeline:** 3-6 months (after collecting labeled data)
**Trigger:** 1000+ labeled examples (500 threats, 500 benign)

### 2.1 RandomForest Threat Classifier

**Architecture:**
```python
# Hybrid ensemble approach
class HybridThreatClassifier:
    def __init__(self):
        # Existing (unsupervised)
        self.isolation_forest = IsolationForest()  # Zero-day detection

        # New (supervised)
        self.random_forest = RandomForestClassifier(
            n_estimators=200,
            max_depth=15,
            min_samples_split=10
        )

    def predict(self, features):
        # Get both predictions
        anomaly_score = self.isolation_forest.score(features)
        threat_probability = self.random_forest.predict_proba(features)[1]

        # Ensemble voting (both models vote)
        final_score = max(anomaly_score, threat_probability)

        return final_score
```

**Training Pipeline:**
```bash
# Load labeled data
python3 train_supervised.py \
    --data training_data/labeled/*.jsonl \
    --min-samples 1000 \
    --validation-split 0.2 \
    --output models/random_forest.pkl

# Output:
[+] Loaded 2,847 labeled examples
    - Threats: 1,203 (42.3%)
    - Benign: 1,644 (57.7%)
[+] Training RandomForest...
[+] Validation accuracy: 97.2%
[+] Precision: 0.95 | Recall: 0.94 | F1: 0.945
[+] Model saved: models/random_forest.pkl
```

---

### 2.2 Ensemble Strategy

**Option A: Max Voting** (Conservative)
```python
final_score = max(isolation_score, random_forest_score)
```
- Blocks if EITHER model flags as threat
- Lower false negatives (fewer missed threats)
- Higher false positives (more accidental blocks)
- **Use case:** High-security environments

**Option B: Weighted Average** (Balanced)
```python
final_score = (isolation_score * 0.4) + (random_forest_score * 0.6)
```
- Requires consensus between models
- Balanced false positive/negative rate
- **Use case:** General production (recommended)

**Option C: Fallback Chain** (Adaptive)
```python
if random_forest_confidence > 0.9:
    return random_forest_score  # High confidence supervised
else:
    return isolation_score  # Fall back to unsupervised
```
- Uses RandomForest when confident, IsolationForest otherwise
- Best for handling novel attacks
- **Use case:** Environments with evolving threats

---

### 2.3 Model Explainability

**What:** Understand WHY a threat was classified

**Implementation:**
```python
from sklearn.inspection import permutation_importance

# Feature importance
importances = random_forest.feature_importances_
for feature, importance in zip(feature_names, importances):
    print(f"{feature}: {importance:.3f}")

# Output:
ip_alert_count: 0.245        # Most important
unique_dest_ports: 0.187
anomaly_score: 0.156
signature_severity: 0.102
...
```

**User-Facing Explanation:**
```
Blocked 192.0.2.45 (score: 0.92)

Reasoning:
✓ 87% match to port scan pattern (45 ports in 30s)
✓ High anomaly score (0.89) - unusual traffic distribution
✓ Previous alerts from this IP (15 in last hour)
✓ Signature: ET SCAN Potential SSH Scan (HIGH severity)

Confidence: 92%
Model: RandomForest + IsolationForest ensemble
```

---

## Phase 3: Advanced Features

**Timeline:** 6-12 months

### 3.1 Active Learning Loop

**What:** System requests human labels for ambiguous cases

**Flow:**
```
Alert received → ML classifies (confidence: 0.52) → Ambiguous!
                     ↓
System queues for human review
                     ↓
Operator labels: "BENIGN - backup server"
                     ↓
Model retrains overnight with new label
                     ↓
Future similar traffic scored lower (learned)
```

**Implementation:**
- Queue ambiguous scores (0.45-0.55) for review
- Present to operator during low-traffic periods
- Incremental model updates (online learning)

---

### 3.2 Threat Intelligence Integration

**What:** Incorporate external threat feeds

**Sources:**
- AbuseIPDB (known malicious IPs)
- Tor exit node lists
- Shodan scanning IPs
- Emerging Threats IP reputation

**Integration:**
```python
# Add feature: "ip_reputation_score"
if source_ip in abuse_ipdb:
    reputation_score = abuse_ipdb[source_ip].confidence / 100.0
else:
    reputation_score = 0.0

features.append(reputation_score)
```

**Benefits:**
- Boost threat scores for known bad actors
- Immediate blocking of repeat offenders
- Reduced false negatives

---

### 3.3 Temporal Correlation

**What:** Detect distributed attacks across multiple IPs

**Detection:**
```python
# Multiple IPs targeting same port within 5 minutes
if len(recent_alerts) > 10:
    if unique_sources > 3 and same_dest_port:
        # Coordinated attack detected
        boost_all_source_scores(+0.3)
```

**Use Cases:**
- DDoS detection (multiple sources)
- Botnet activity
- Distributed scanning

---

### 3.4 GeoIP-Based Analysis

**What:** Factor geographic patterns into scoring

**Features:**
```python
# Add to feature vector
is_unexpected_country  # 1 if source country != usual
distance_from_baseline # km from typical source locations
is_high_risk_country   # 1 if known malicious activity source
```

**Example:**
- Most traffic from US → Sudden burst from Russia/China → +0.2 score
- SSH attempts from countries you never SSH from → Higher suspicion

---

## Phase 4: Optimization & Scaling

**Timeline:** 12+ months

### 4.1 Model Quantization

**What:** Reduce model size and inference time

**Techniques:**
- Convert float64 → float16 (50% size reduction)
- Prune low-importance features
- Tree depth limiting

**Results:**
- Current: 1.1 MB model, ~100ms inference
- Target: 500 KB model, ~50ms inference

---

### 4.2 Multi-Firewall Orchestration

**What:** Centralized ML for multiple pfSense instances

**Architecture:**
```
pfSense-1 → Suricata logs → \
pfSense-2 → Suricata logs → → Central ML Server → Shared blocklist
pfSense-3 → Suricata logs → /
```

**Benefits:**
- Block on firewall-1 → Automatically block on firewall-2/3
- Distributed threat intelligence
- Centralized model training

---

### 4.3 GPU Acceleration

**What:** Use GPU for inference at scale

**When Needed:**
- Processing > 10,000 alerts/second
- Deep learning models (LSTM/Transformer)
- Real-time training

**Implementation:**
- Current: CPU (scikit-learn)
- Future: GPU (PyTorch, TensorFlow)

---

## Data Collection Metrics (Phase 1)

### Target Dataset (6 months)

| Metric | Target | Purpose |
|--------|--------|---------|
| **Total alerts logged** | 50,000,000+ | Raw data pool |
| **Labeled examples** | 5,000+ | Training supervised model |
| **Unique IPs profiled** | 10,000+ | Behavioral diversity |
| **Attack patterns captured** | 50+ | Pattern library |
| **False positive reports** | < 10 | Validate current accuracy |

### Monthly Review Checkpoints

**Month 1:**
- ✓ Data collection pipeline deployed
- ✓ 100+ manual labels completed
- ✓ Review auto-labeling accuracy

**Month 3:**
- ✓ 500+ labeled examples
- ✓ Train prototype RandomForest
- ✓ Offline validation testing

**Month 6:**
- ✓ 1,000+ labeled examples
- ✓ Production RandomForest deployment
- ✓ A/B test: IsolationForest vs Hybrid ensemble

---

## Success Metrics

### Phase 1 (Data Collection)
- [ ] 1,000+ labeled examples collected
- [ ] <10 hours manual labeling effort (via auto-labeling)
- [ ] Zero production disruptions

### Phase 2 (Supervised Learning)
- [ ] RandomForest accuracy > 95% on validation set
- [ ] Hybrid ensemble accuracy > 97%
- [ ] False positive rate < 1%
- [ ] Inference time < 150ms

### Phase 3 (Advanced Features)
- [ ] Active learning reduces labeling effort by 50%
- [ ] Threat intel integration catches 10+ new threats/month
- [ ] Temporal correlation detects DDoS within 30 seconds

---

## Risk Mitigation

### Risk: Data Collection Fills Disk

**Mitigation:**
- Daily log rotation
- Compression (gzip: ~10:1 ratio)
- Automatic cleanup after 6 months
- Disk usage alerts in Grafana

### Risk: Supervised Model Overfits

**Mitigation:**
- Train/validation/test split (60/20/20)
- Cross-validation during training
- Monitor validation accuracy weekly
- Keep IsolationForest as fallback

### Risk: False Positive Blocks Production Traffic

**Mitigation:**
- Deploy in dry-run mode for 2 weeks
- Gradual threshold increase (0.95 → 0.85)
- Whitelist critical IPs
- Auto-unblock after 1 hour for first offense

---

## Implementation Priority

### Must Have (Phase 1)
1. Classification decision logging
2. JSONL data storage pipeline
3. Log rotation & retention
4. Basic review CLI tool

### Should Have (Phase 2)
1. RandomForest training pipeline
2. Hybrid ensemble classifier
3. Model explainability
4. A/B testing framework

### Nice to Have (Phase 3+)
1. Active learning
2. Threat intel feeds
3. Temporal correlation
4. GeoIP analysis
5. Multi-firewall orchestration

---

## Next Steps (Immediate Actions)

1. **Implement data collector** (training_data_collector.py)
   - Add to ai_suricata.py after classification
   - Store in JSONL format
   - Add Prometheus metric: `training_data_examples_collected`

2. **Create review tool** (review_threats.py)
   - CLI interface for labeling
   - Filter by severity/action/date
   - Export labeled data

3. **Add to Grafana dashboard**
   - Panel: "Labeled Examples Collected"
   - Panel: "Label Distribution (Threat vs Benign)"
   - Panel: "Training Dataset Progress"

4. **Update documentation**
   - Link to MACHINE_LEARNING.md
   - Link to ROADMAP.md
   - Update README.md with Phase 1 status

---

## Questions to Resolve

- [ ] Should we log ALL alerts or only HIGH/CRITICAL? (Storage vs completeness)
- [ ] Manual review schedule? (Daily vs weekly vs monthly)
- [ ] Threshold for deploying RandomForest? (1000 examples or 95% accuracy?)
- [ ] Ensemble strategy preference? (Max voting vs weighted average vs fallback)

---

**Document Version:** 1.0
**Last Updated:** 2025-12-23
**Status:** Phase 1 Ready for Implementation

# Network Storage Strategy for AI Suricata

## Current Situation

**Local Storage:**
- /home: 88% full (403G / 465G)
- Training data: 1.6 GB (growing daily)
- Docker volumes: Prometheus, Grafana, Redis
- Models: 1.4 MB

**NAS (192.168.1.7):**
- ✅ SMB already mounted: `//backup.home.arpa/smb`
- ✅ NFS available: `/home` exported
- Used for: Backup snapshots (44 GB snapshots)

---

## Protocol Comparison

### NFS (Network File System) ⭐ RECOMMENDED

**Pros:**
- ✅ **Native Linux protocol** - best Linux performance
- ✅ **Low CPU overhead** - kernel-level, efficient
- ✅ **Sequential I/O optimized** - perfect for training data
- ✅ **File-level locking** - works well for concurrent access
- ✅ **POSIX compliant** - full file permissions support
- ✅ **Multiple readers** - many clients can read simultaneously
- ✅ **NFSv4 encryption** - can enable Kerberos if needed

**Cons:**
- ⚠️ No built-in compression
- ⚠️ Requires proper network tuning for max performance

**Best For:**
- Training data storage (1.6 GB JSONL files)
- Model versioning and storage
- Log archival
- Shared datasets across multiple instances

**Performance:**
- Throughput: 100-125 MB/s (gigabit) or 1+ GB/s (10 GbE)
- Latency: 1-2ms on local network
- CPU: ~5-10% during heavy I/O

---

### SMB/CIFS (Current Backup Solution)

**Pros:**
- ✅ **Already configured** - working for backups
- ✅ **User-friendly** - easy to browse from any OS
- ✅ **Good compatibility** - Windows, Linux, macOS
- ✅ **Built-in compression** - optional
- ✅ **File locking** - prevents conflicts

**Cons:**
- ❌ **Higher CPU overhead** - userspace protocol (FUSE)
- ❌ **Network chatty** - more round trips
- ❌ **Slower** - 60-80 MB/s typical vs 100+ for NFS
- ❌ **Permission mapping issues** - UID/GID translation
- ❌ **Stale locks** - can hang if network drops

**Best For:**
- Backups (current use - keep it)
- Human-readable archives
- Cross-platform file sharing
- Infrequent access

**Performance:**
- Throughput: 60-80 MB/s (gigabit)
- Latency: 3-5ms
- CPU: ~15-20% during heavy I/O

---

### iSCSI (Block-Level Storage)

**Pros:**
- ✅ **Block-level** - appears as local disk
- ✅ **Best raw performance** - near-native speeds
- ✅ **Any filesystem** - ext4, xfs, btrfs, etc.
- ✅ **Low latency** - minimal overhead
- ✅ **Great for databases** - random I/O optimized

**Cons:**
- ❌ **Exclusive access** - only ONE host at a time (unless clustered)
- ❌ **Complex setup** - requires LUN configuration, initiator setup
- ❌ **No file sharing** - can't browse from other machines
- ❌ **Overkill** - for simple file storage needs
- ❌ **Backup complexity** - must backup entire volume

**Best For:**
- VM disk images
- Databases (PostgreSQL, MySQL)
- High-performance random I/O workloads
- Single-host scenarios

**Performance:**
- Throughput: 110-120 MB/s (gigabit)
- Latency: <1ms
- CPU: ~3-5% during heavy I/O

---

## Recommended Architecture: **NFS for AI Data**

### Why NFS is Best for AI Suricata

1. **Training Data Growth**
   - Currently: 1.6 GB, growing ~500 MB/day
   - NFS handles large sequential reads efficiently
   - Models train faster with network-optimized reads

2. **Multiple Instance Support**
   - Can run AI Suricata on multiple machines
   - All share same training dataset (NFS allows concurrent reads)
   - Distributed training becomes possible

3. **Low CPU Overhead**
   - Native kernel implementation
   - Already using 16.9% CPU for AI processing
   - NFS adds only ~2-3% during active training

4. **Centralized Management**
   - Training data on NAS gets backed up automatically
   - Easy to version models (snapshots on NAS)
   - Don't fill up local /home (88% → safer levels)

5. **POSIX Compliance**
   - Python file operations work natively
   - No permission translation issues
   - File locking works correctly for concurrent access

---

## Proposed Implementation

### Mount Strategy

**Keep SMB for:**
- ✅ Backups (current `/home/hashcat/mnt/backup-smb`)
- ✅ TheRock snapshots
- ✅ Human-readable archives

**Add NFS for:**
- ✅ AI Suricata training data
- ✅ Model storage and versioning
- ✅ Log archival
- ✅ Prometheus long-term storage (optional)

### Directory Structure

```
NAS (192.168.1.7 - NFS)
└── /mnt/ai-datastore/
    ├── training-data/           # 1.6 GB JSONL files
    │   ├── decisions.2025-12-23.jsonl
    │   ├── decisions.2025-12-24.jsonl
    │   └── decisions.2025-12-25.jsonl
    ├── models/                  # Model versions
    │   ├── threat_classifier.pkl
    │   ├── threat_classifier.v2.pkl
    │   └── snapshots/
    ├── logs/                    # Archived logs
    │   └── ai_alerts/
    └── shared/                  # Shared configs for multi-instance

Local (TheRock)
├── /home/hashcat/pfsense/ai_suricata/
│   ├── training_data → /mnt/nfs-ai/training-data  (NFS symlink)
│   ├── models → /mnt/nfs-ai/models                (NFS symlink)
│   └── [code remains local for performance]
└── /var/lib/docker/volumes/
    └── [keep local for low-latency]
```

---

## Implementation Plan

### Step 1: Create NFS Share on NAS

**Option A: Use existing /home export**
```bash
# NAS already exports: /home
# Create subdirectory: /home/ai-datastore
```

**Option B: Create dedicated export (better isolation)**
```bash
# On NAS, create new export:
# /mnt/ai-datastore → export as NFS
```

### Step 2: Mount NFS on TheRock

```bash
# Install NFS client (if not present)
sudo dnf install -y nfs-utils

# Create mount point
sudo mkdir -p /mnt/nfs-ai

# Test mount
sudo mount -t nfs -o vers=4.2,rsize=1048576,wsize=1048576 \
  192.168.1.7:/home/ai-datastore /mnt/nfs-ai

# Verify
df -h | grep nfs-ai
```

### Step 3: Configure Permanent Mount

**Create systemd mount unit:**
```bash
# /etc/systemd/system/mnt-nfs\x2dai.mount
[Unit]
Description=NFS AI Datastore
After=network-online.target
Wants=network-online.target

[Mount]
What=192.168.1.7:/home/ai-datastore
Where=/mnt/nfs-ai
Type=nfs
Options=vers=4.2,rsize=1048576,wsize=1048576,soft,timeo=30,retrans=3

[Install]
WantedBy=multi-user.target
```

**Enable auto-mount:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable mnt-nfs-ai.mount
sudo systemctl start mnt-nfs-ai.mount
```

### Step 4: Migrate AI Suricata Data

```bash
# Copy existing data to NFS
mkdir -p /mnt/nfs-ai/{training-data,models,logs}
rsync -avP /home/hashcat/pfsense/ai_suricata/training_data/ \
  /mnt/nfs-ai/training-data/
rsync -avP /home/hashcat/pfsense/ai_suricata/models/ \
  /mnt/nfs-ai/models/

# Backup original directories
mv /home/hashcat/pfsense/ai_suricata/training_data{,.local-backup}
mv /home/hashcat/pfsense/ai_suricata/models{,.local-backup}

# Create symlinks
ln -s /mnt/nfs-ai/training-data \
  /home/hashcat/pfsense/ai_suricata/training_data
ln -s /mnt/nfs-ai/models \
  /home/hashcat/pfsense/ai_suricata/models

# Restart service
sudo systemctl restart ai-suricata
```

### Step 5: Update AI Suricata Config (Optional)

**If you want direct paths instead of symlinks:**
```python
# config.env or ai_suricata.py
TRAINING_DATA_DIR=/mnt/nfs-ai/training-data
MODELS_DIR=/mnt/nfs-ai/models
LOGS_DIR=/mnt/nfs-ai/logs
```

---

## Performance Tuning

### NFS Mount Options (Optimized)

```bash
# High-performance options
vers=4.2              # Latest NFS version
rsize=1048576         # 1 MB read buffer (max throughput)
wsize=1048576         # 1 MB write buffer
soft                  # Don't hang if NAS becomes unavailable
timeo=30              # 3-second timeout
retrans=3             # 3 retries before failing
async                 # Async writes (faster, slight risk)
noatime               # Don't update access times (faster)
nodiratime            # Don't update directory access times
```

**For mission-critical (slower but safer):**
```bash
vers=4.2
rsize=1048576
wsize=1048576
hard                  # Wait indefinitely if NAS down (safer)
intr                  # Allow interrupts
sync                  # Sync writes (slower, safer)
```

### Network Tuning

```bash
# Increase socket buffers
sudo sysctl -w net.core.rmem_max=16777216
sudo sysctl -w net.core.wmem_max=16777216

# Make permanent
echo "net.core.rmem_max = 16777216" | sudo tee -a /etc/sysctl.conf
echo "net.core.wmem_max = 16777216" | sudo tee -a /etc/sysctl.conf
```

---

## Benefits Summary

### Storage Benefits

✅ **Free up local space**: 1.6 GB training data → NAS (88% → ~87%)
✅ **Unlimited growth**: NAS capacity >> local disk
✅ **Automatic backups**: NAS data in backup rotation
✅ **Snapshots**: NAS can snapshot training data states

### Performance Benefits

✅ **Faster training**: NFS optimized for sequential reads (models train from network data)
✅ **Lower local I/O**: Reduce wear on NVMe SSD
✅ **Cached reads**: NFS client caches frequently accessed files
✅ **Model versioning**: Easy to A/B test models

### Operational Benefits

✅ **Distributed training**: Multiple TheRock instances share dataset
✅ **High availability**: Training data survives if TheRock fails
✅ **Centralized management**: One place for all AI data
✅ **Easy rollback**: NAS snapshots = instant model version rollback

### Cost Benefits

✅ **No local disk expansion**: Use existing NAS capacity
✅ **One backup solution**: NAS backs up everything
✅ **Shared infrastructure**: Other projects can use NAS too

---

## Docker Volumes (Keep Local)

**Recommendation: Keep these LOCAL**

- ✅ **Redis** - Needs low latency for caching
- ✅ **Prometheus** - High write rate (metrics every second)
- ✅ **Grafana** - Small, infrequent writes

**Why:**
- Network latency would hurt Redis performance (currently 7.7% CPU, don't add overhead)
- Prometheus writes constantly (thousands of metrics/sec)
- These are ephemeral data (30-day retention, can rebuild)

**Alternative: Prometheus Remote Storage**
If you want Prometheus data on NAS for long-term retention:
- Keep local storage for recent data (7 days)
- Use Prometheus remote write to NAS-backed storage
- Best of both worlds: fast local + long-term archive

---

## Testing Plan

### Phase 1: Test Mount (5 minutes)
```bash
sudo mount -t nfs 192.168.1.7:/home/ai-datastore /mnt/nfs-ai
dd if=/dev/zero of=/mnt/nfs-ai/testfile bs=1M count=1000
# Should see ~100 MB/s write speed
```

### Phase 2: Test with Sample Data (10 minutes)
```bash
# Copy one JSONL file
cp /home/hashcat/pfsense/ai_suricata/training_data/decisions.2025-12-25.jsonl \
  /mnt/nfs-ai/test-training/

# Test AI Suricata can read it
python3 -c "
import json
with open('/mnt/nfs-ai/test-training/decisions.2025-12-25.jsonl') as f:
    data = [json.loads(line) for line in f]
    print(f'Read {len(data)} records from NFS')
"
```

### Phase 3: Full Migration (30 minutes)
- Copy all training data
- Update symlinks
- Restart AI Suricata
- Monitor for 24 hours

---

## Monitoring

**Add to Grafana dashboard:**
```promql
# NFS mount status
node_filesystem_avail_bytes{mountpoint="/mnt/nfs-ai"}

# NFS I/O
rate(node_disk_read_bytes_total{device="nfs"}[5m])
rate(node_disk_written_bytes_total{device="nfs"}[5m])

# Training data size growth
node_filesystem_size_bytes{mountpoint="/mnt/nfs-ai"} -
node_filesystem_avail_bytes{mountpoint="/mnt/nfs-ai"}
```

**Alert if:**
- NFS mount becomes unavailable
- NFS I/O errors increase
- Training data growth rate spikes

---

## Rollback Plan

If NFS causes issues:

```bash
# Unmount NFS
sudo systemctl stop mnt-nfs-ai.mount

# Restore local data
rm /home/hashcat/pfsense/ai_suricata/{training_data,models}
mv /home/hashcat/pfsense/ai_suricata/training_data{.local-backup,}
mv /home/hashcat/pfsense/ai_suricata/models{.local-backup,}

# Restart service
sudo systemctl restart ai-suricata
```

---

## Recommendation: Hybrid Approach

**Phase 1 (Immediate - Low Risk):**
1. Mount NFS as `/mnt/nfs-ai`
2. Use for **new training data only** (symlink future daily files)
3. Keep existing 1.6 GB local (proven working)
4. Monitor performance for 1 week

**Phase 2 (After validation):**
1. Migrate all training data to NFS
2. Move old logs to NFS archival
3. Set up model versioning on NFS
4. Configure automatic cleanup of local cache

**Phase 3 (Optional - Advanced):**
1. Enable Prometheus remote write to NFS-backed storage
2. Set up distributed AI Suricata (multiple instances)
3. Implement shared model serving from NFS

---

## Quick Decision Matrix

| Use Case | Protocol | Why |
|----------|----------|-----|
| Training data (current) | **NFS** | Fast sequential reads, low overhead |
| Model storage | **NFS** | Versioning, shared access |
| Log archival | **NFS** | Large files, infrequent access |
| Backups | **SMB** (current) | Keep as-is, working well |
| Redis data | **Local** | Low latency required |
| Prometheus data (hot) | **Local** | High write rate |
| Prometheus data (archive) | **NFS** | Long-term retention |
| Distributed AI instances | **NFS** | Shared dataset |
| Database (future) | **iSCSI** | Only if need high IOPS |

---

## Final Recommendation

**Primary: NFS** for AI Suricata data
- 95% of benefits
- 5% of complexity
- Proven Linux protocol
- Your NAS already supports it

**Keep: SMB** for backups
- Working well
- Don't change what works

**Avoid: iSCSI** for this use case
- Overkill for file storage
- Loss of file-level access
- No clear benefit over NFS

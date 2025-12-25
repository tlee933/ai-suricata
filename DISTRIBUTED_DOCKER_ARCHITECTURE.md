# Distributed Docker Architecture for AI Suricata

**Date:** December 25, 2025
**Goal:** Offload work from TheRock to other network machines using Docker

---

## Current vs Distributed Architecture

### Current (Single Node - TheRock)
```
┌─────────────────────────────────────────────────┐
│              TheRock (fc43)                     │
├─────────────────────────────────────────────────┤
│ • AI Suricata (16.9% CPU)                       │
│ • Redis (7.7% CPU)                              │
│ • Prometheus (container)                        │
│ • Grafana (container)                           │
│ • Redis Exporter (container)                    │
│ • Node Exporter (container)                     │
│ • AMD GPU Exporter (container)                  │
│                                                 │
│ Total: ~40% CPU, ~4 GB RAM                      │
└─────────────────────────────────────────────────┘
                     │
                     ▼
         NAS (192.168.1.7) - Storage only
```

### Proposed (Distributed)
```
┌──────────────────────┐   ┌──────────────────────┐   ┌──────────────────────┐
│   TheRock (Main)     │   │  Machine 2 (Monitor) │   │  Machine 3 (Cache)   │
├──────────────────────┤   ├──────────────────────┤   ├──────────────────────┤
│ • AI Suricata        │   │ • Prometheus         │   │ • Redis              │
│ • Node Exporter      │   │ • Grafana            │   │ • Redis Exporter     │
│ • AMD GPU Exporter   │   │ • Node Exporter      │   │ • Node Exporter      │
│                      │   │                      │   │                      │
│ Load: ~20% CPU       │   │ Load: ~10% CPU       │   │ Load: ~10% CPU       │
│       ~1 GB RAM      │   │       ~1.5 GB RAM    │   │       ~1 GB RAM      │
└──────────────────────┘   └──────────────────────┘   └──────────────────────┘
         │                          │                           │
         └──────────────────────────┴───────────────────────────┘
                                    │
                                    ▼
                    NAS (192.168.1.7) - Shared Storage
                    (training data, models, configs)
```

---

## Component Distribution Strategy

### TheRock (Primary - GPU + Processing)
**Keep Here:**
- ✅ **AI Suricata** (needs GPU access for future ML training)
- ✅ **AMD GPU Exporter** (direct hardware access)
- ✅ **Node Exporter** (local metrics)

**Benefits:**
- Reduced CPU: 40% → 20%
- More headroom for AI processing
- GPU available for intensive training

---

### Machine 2: Monitoring Stack
**Move Here:**
- ✅ **Prometheus** (time-series database)
- ✅ **Grafana** (dashboards)
- ✅ **Node Exporter** (local metrics)

**Requirements:**
- 2+ GB RAM (Prometheus can grow)
- 20+ GB disk for metrics retention
- Always-on preferred (monitoring)

**Benefits:**
- Isolate monitoring from production AI
- Can monitor multiple machines
- Grafana accessible from any network machine

---

### Machine 3: Caching Layer
**Move Here:**
- ✅ **Redis** (distributed cache)
- ✅ **Redis Exporter** (metrics)
- ✅ **Node Exporter** (local metrics)

**Requirements:**
- 2+ GB RAM (Redis can cache more)
- Low latency network connection
- Persistent storage for Redis backup

**Benefits:**
- Dedicated caching layer
- Can serve multiple AI Suricata instances
- Better cache performance (more RAM available)

---

### NAS (192.168.1.7): Shared Storage
**Already Set Up:**
- ✅ Training data (1.6 GB, growing)
- ✅ ML models (1.4 MB)
- ✅ Logs archive
- ✅ Shared configs

**Mount on all machines:**
```bash
# All machines mount NAS
/mnt/nfs-ai → 192.168.1.7:/home/ai-datastore
```

---

## Implementation: Docker Compose with Remote Hosts

### Option 1: Docker Contexts (Simplest)

**Setup Docker contexts for each machine:**
```bash
# On TheRock, add remote machines
docker context create machine2 --docker "host=ssh://user@192.168.1.10"
docker context create machine3 --docker "host=ssh://user@192.168.1.11"

# Deploy to specific machine
docker context use machine2
docker-compose -f monitoring-stack.yml up -d

docker context use machine3
docker-compose -f redis-stack.yml up -d

# Switch back to local
docker context use default
```

**Pros:**
- No additional software
- Use existing docker-compose files
- Simple SSH-based communication
- Manage from TheRock centrally

**Cons:**
- Manual context switching
- No automatic failover
- Each machine managed separately

---

### Option 2: Docker Swarm (Recommended)

**Initialize Swarm cluster:**
```bash
# On TheRock (manager node)
docker swarm init --advertise-addr 192.168.1.20

# On Machine 2 (worker)
docker swarm join --token <token> 192.168.1.20:2377

# On Machine 3 (worker)
docker swarm join --token <token> 192.168.1.20:2377

# Verify cluster
docker node ls
```

**Deploy stack with placement constraints:**
```yaml
# docker-stack.yml
version: '3.8'

services:
  # AI Suricata - stays on TheRock
  ai-suricata:
    image: ai-suricata:latest
    deploy:
      placement:
        constraints:
          - node.hostname == therock
      restart_policy:
        condition: on-failure
    volumes:
      - /mnt/nfs-ai:/data
      - /opt/rocm:/opt/rocm:ro

  # Redis - runs on Machine 3
  redis:
    image: redis:7-alpine
    deploy:
      placement:
        constraints:
          - node.labels.role == cache
      restart_policy:
        condition: on-failure
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes --save 60 1

  # Prometheus - runs on Machine 2
  prometheus:
    image: prom/prometheus:latest
    deploy:
      placement:
        constraints:
          - node.labels.role == monitoring
      restart_policy:
        condition: on-failure
    volumes:
      - prometheus-data:/prometheus
      - /mnt/nfs-ai/prometheus.yml:/etc/prometheus/prometheus.yml:ro

  # Grafana - runs on Machine 2
  grafana:
    image: grafana/grafana:latest
    deploy:
      placement:
        constraints:
          - node.labels.role == monitoring
      restart_policy:
        condition: on-failure
    volumes:
      - grafana-data:/var/lib/grafana
    ports:
      - "3000:3000"

volumes:
  redis-data:
  prometheus-data:
  grafana-data:

networks:
  default:
    driver: overlay
```

**Label nodes:**
```bash
docker node update --label-add role=processing therock
docker node update --label-add role=monitoring machine2
docker node update --label-add role=cache machine3
```

**Deploy stack:**
```bash
docker stack deploy -c docker-stack.yml ai-suricata
```

**Pros:**
- ✅ Automatic service distribution
- ✅ Built-in load balancing
- ✅ Health checks and auto-restart
- ✅ Service discovery (by name)
- ✅ Overlay networking (secure)
- ✅ Rolling updates
- ✅ Scale services easily

**Cons:**
- Slightly more complex setup
- Swarm overhead (minimal, ~100 MB RAM)

---

## Network Communication

### Service Discovery (Swarm)
```yaml
# AI Suricata connects to Redis by name
REDIS_HOST=redis  # Swarm resolves to correct machine
REDIS_PORT=6379

# Prometheus scrapes by service name
- job_name: 'ai-suricata'
  static_configs:
    - targets: ['ai-suricata:8000']
```

### Prometheus Scrape Targets (Distributed)
```yaml
# /mnt/nfs-ai/prometheus.yml
global:
  scrape_interval: 10s

scrape_configs:
  # TheRock
  - job_name: 'therock-node'
    static_configs:
      - targets: ['therock:9100']  # Node Exporter

  - job_name: 'therock-gpu'
    static_configs:
      - targets: ['therock:9101']  # AMD GPU Exporter

  - job_name: 'ai-suricata'
    static_configs:
      - targets: ['therock:8000']  # AI Suricata metrics

  # Machine 2 (self)
  - job_name: 'machine2-node'
    static_configs:
      - targets: ['localhost:9100']

  # Machine 3 (Redis host)
  - job_name: 'machine3-node'
    static_configs:
      - targets: ['machine3:9100']

  - job_name: 'redis'
    static_configs:
      - targets: ['machine3:9121']  # Redis Exporter
```

---

## Migration Plan

### Phase 1: Preparation (30 minutes)

1. **Choose additional machines:**
   - Machine 2: 2+ GB RAM, always-on (monitoring)
   - Machine 3: 2+ GB RAM, low latency (caching)

2. **Install Docker on all machines:**
   ```bash
   # Fedora/RHEL
   sudo dnf install -y docker
   sudo systemctl enable --now docker

   # Add user to docker group
   sudo usermod -aG docker $USER
   ```

3. **Set up SSH keys between machines:**
   ```bash
   # On TheRock
   ssh-copy-id user@machine2
   ssh-copy-id user@machine3
   ```

4. **Mount NAS on all machines:**
   ```bash
   # On each machine
   sudo mkdir -p /mnt/nfs-ai
   sudo mount -t nfs 192.168.1.7:/home/ai-datastore /mnt/nfs-ai

   # Make permanent (fstab or systemd mount)
   ```

---

### Phase 2: Docker Swarm Setup (15 minutes)

```bash
# On TheRock
docker swarm init --advertise-addr 192.168.1.20

# Save the join token
docker swarm join-token worker

# On Machine 2 and Machine 3
docker swarm join --token <TOKEN> 192.168.1.20:2377

# Verify cluster
docker node ls

# Label nodes
docker node update --label-add role=processing therock
docker node update --label-add role=monitoring machine2
docker node update --label-add role=cache machine3
```

---

### Phase 3: Migrate Services (30 minutes)

**1. Stop current containers on TheRock:**
```bash
cd /home/hashcat/monitoring
docker-compose down
```

**2. Create distributed stack file:**
```bash
# Create docker-stack.yml (see full example above)
nano /home/hashcat/monitoring/docker-stack.yml
```

**3. Deploy stack:**
```bash
docker stack deploy -c docker-stack.yml ai-suricata

# Verify services
docker stack services ai-suricata
docker stack ps ai-suricata
```

**4. Update AI Suricata config:**
```bash
# Edit /home/hashcat/pfsense/ai_suricata/config.env
REDIS_HOST=redis  # Swarm service name (resolves to Machine 3)
```

**5. Restart AI Suricata:**
```bash
sudo systemctl restart ai-suricata
```

**6. Verify everything works:**
```bash
# Check Grafana (should be on Machine 2)
curl http://machine2:3000

# Check Redis (should be on Machine 3)
docker exec -it $(docker ps -q -f name=redis) redis-cli ping

# Check AI Suricata can reach Redis
docker logs $(docker ps -q -f name=ai-suricata) | grep -i redis
```

---

### Phase 4: Monitoring (ongoing)

**Dashboard on each node:**
```bash
# See which services run where
docker stack ps ai-suricata

# Node resource usage
docker node ls
docker node inspect therock

# Service logs
docker service logs ai-suricata_prometheus
docker service logs ai-suricata_redis
```

**Grafana update:**
- Add panels for Machine 2 and Machine 3 node metrics
- Show service distribution across cluster
- Alert if node goes down

---

## Expected Benefits

### TheRock (Before vs After)

| Metric | Before (Single Node) | After (Distributed) | Improvement |
|--------|---------------------|---------------------|-------------|
| CPU | 40% | 20% | -50% |
| RAM | 4 GB | 1.5 GB | -63% |
| Disk I/O | High (Prometheus writes) | Low (AI only) | -70% |
| Network | Local only | Distributed | Better utilization |

### Overall Cluster

| Metric | Single Node | Distributed (3 nodes) | Benefit |
|--------|------------|----------------------|---------|
| **Availability** | Single point of failure | High (services auto-restart) | ✅ Better uptime |
| **Performance** | Bottleneck on one machine | Load distributed | ✅ Better throughput |
| **Scalability** | Limited by TheRock | Add more nodes easily | ✅ Horizontal scaling |
| **Resource Usage** | 40% CPU, 4 GB RAM (TheRock) | 20% + 10% + 10% CPU across 3 nodes | ✅ Better utilization |
| **Maintenance** | Downtime affects everything | Can update services individually | ✅ Zero-downtime updates |

---

## Advanced: Multiple AI Suricata Instances

Once distributed, you can run **multiple AI instances** sharing Redis and storage:

```yaml
services:
  ai-suricata-primary:
    image: ai-suricata:latest
    deploy:
      placement:
        constraints:
          - node.hostname == therock
      replicas: 1

  ai-suricata-secondary:
    image: ai-suricata:latest
    deploy:
      placement:
        constraints:
          - node.labels.role == processing
      replicas: 2  # 2 more instances on other machines
```

**Use cases:**
- Process different pfSense interfaces
- Train models on different datasets
- A/B test different model versions
- Increase processing throughput

---

## Troubleshooting

### Service not starting
```bash
# Check service status
docker service ps ai-suricata_redis --no-trunc

# Check logs
docker service logs ai-suricata_redis

# Inspect service
docker service inspect ai-suricata_redis
```

### Network connectivity issues
```bash
# Test overlay network
docker network inspect ai-suricata_default

# Ping between services
docker exec -it <container_id> ping redis
```

### Swarm node issues
```bash
# Check node status
docker node ls

# Drain node (stop scheduling)
docker node update --availability drain machine2

# Make node active again
docker node update --availability active machine2
```

---

## Cost Analysis

### Hardware Requirements

**Minimum for distributed setup:**
- TheRock: Existing (powerful)
- Machine 2: 2 GB RAM, 20 GB disk (can be old laptop/desktop)
- Machine 3: 2 GB RAM, 10 GB disk (can be Raspberry Pi 4)

**Example machines that work:**
- Old desktop/laptop (2015+)
- Raspberry Pi 4 (4 GB model)
- Mini PC (Intel NUC, Beelink)
- VM on existing hardware

### Comparison to K8s

| Aspect | Docker Swarm | Kubernetes |
|--------|-------------|------------|
| **RAM Overhead** | ~100 MB/node | ~1 GB/node |
| **CPU Overhead** | <5% | 10-15% |
| **Setup Time** | 30 min | 4+ hours |
| **Learning Curve** | Easy | Steep |
| **Cluster Size** | Works well 2-10 nodes | Best for 10+ nodes |
| **Management** | Simple CLI | Complex (kubectl, helm, etc.) |
| **Our Use Case** | ✅ Perfect fit | ❌ Overkill |

---

## Recommendation

**Immediate (Next Step):**
1. ✅ **Start with Docker Swarm** (3 machines)
   - TheRock: AI Suricata + GPU
   - Machine 2: Prometheus + Grafana
   - Machine 3: Redis

2. ✅ **Keep NAS for storage** (already working great)

3. ✅ **Benefits:**
   - Reduce TheRock load by 50%
   - Better fault tolerance
   - Room to add more AI instances later

**Future (Optional):**
- Add 4th machine for distributed training
- Run multiple AI Suricata instances
- Add more monitoring services (Loki for logs, Alertmanager)

---

## Summary

**Docker Swarm is the sweet spot for your setup:**

| Solution | Complexity | Overhead | Fit for 2-4 Nodes |
|----------|-----------|----------|-------------------|
| Single Docker (current) | ⭐ Simple | None | ✅ Works, but bottleneck |
| Docker Swarm | ⭐⭐ Easy | Minimal (~100 MB) | ✅ **Perfect** |
| Kubernetes | ⭐⭐⭐⭐⭐ Complex | High (1+ GB) | ❌ Overkill |

**Bottom line:** Docker Swarm gives you 80% of K8s benefits with 20% of the complexity, and uses 1/10th the resources. Perfect for a small cluster!

---

**Ready to implement?** I can help set up the distributed Docker architecture step by step.

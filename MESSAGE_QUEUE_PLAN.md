# Message Queue Architecture - SSH Replacement Plan

## Executive Summary

Replace all SSH dependencies with Redis Streams message queue architecture for asynchronous, distributed, and fault-tolerant communication between pfSense and AI Suricata.

**Status**: Planned (Not yet implemented)
**Priority**: High
**Complexity**: Medium
**Timeline**: 4-6 hours implementation
**Dependencies**: Redis (already deployed ✅)

---

## Current Architecture (SSH-Based)

### Components Using SSH:

1. **alert_collector.py**
   - Command: `ssh admin@192.168.1.1 "tail -f /var/log/suricata/eve.json"`
   - Purpose: Real-time alert streaming
   - Issues:
     - Single point of failure (SSH connection drops)
     - High latency (~10-50ms per alert)
     - Requires SSH keys and credentials
     - Not horizontally scalable

2. **auto_responder.py**
   - Commands: PHP scripts via SSH to add/remove firewall rules
   - Purpose: Block/unblock malicious IPs
   - Issues:
     - Synchronous execution (blocking)
     - No command persistence
     - Cannot distribute across multiple AI Suricata instances

3. **thermal_monitor.py**
   - Command: `ssh admin@192.168.1.1 "sysctl -a | grep temperature"`
   - Purpose: Monitor pfSense temperatures
   - Issues:
     - Polling-based (inefficient)
     - SSH overhead for simple metrics

### Current Problems:

❌ **SSH Dependency** - Requires SSH keys, credentials, network access
❌ **Single Instance** - Cannot run multiple AI Suricata instances
❌ **No Persistence** - Lost alerts if SSH connection drops
❌ **Synchronous** - Blocking operations reduce throughput
❌ **No Load Balancing** - Cannot distribute alert processing
❌ **Complex Setup** - SSH key management, firewall rules
❌ **Security** - Broad SSH access to pfSense

---

## New Architecture (Message Queue)

### Redis Streams-Based Communication

```
┌─────────────────────────────────────────────────────────────┐
│                      pfSense Firewall                        │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │         pfSense Agent (pfsense_agent.py)               │ │
│  │                                                         │ │
│  │  ┌─────────────────┐  ┌─────────────────┐             │ │
│  │  │  Log Watcher    │  │  Redis Publisher│             │ │
│  │  │  - eve.json     │→ │  - alerts:stream│             │ │
│  │  │  - inotify/tail │  │  - stats:stream │             │ │
│  │  └─────────────────┘  └─────────────────┘             │ │
│  │                                                         │ │
│  │  ┌─────────────────┐  ┌─────────────────┐             │ │
│  │  │ Firewall Manager│← │  Redis Subscriber│            │ │
│  │  │  - pfctl rules  │  │  - blocks:stream│             │ │
│  │  │  - PHP config   │  │  - commands:*   │             │ │
│  │  └─────────────────┘  └─────────────────┘             │ │
│  │                                                         │ │
│  │  ┌─────────────────┐                                   │ │
│  │  │ System Monitor  │→ Redis (temps, stats)            │ │
│  │  │  - CPU, Memory  │                                   │ │
│  │  │  - Temperature  │                                   │ │
│  │  └─────────────────┘                                   │ │
│  └────────────────────────────────────────────────────────┘ │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            │ Redis Protocol (TCP 6379)
                            │ - alerts:stream (pfSense → AI)
                            │ - blocks:stream (AI → pfSense)
                            │ - stats:stream  (pfSense → AI)
                            │
┌───────────────────────────┴──────────────────────────────────┐
│                    Redis Server (Existing)                    │
│                  redis:7-alpine (Docker)                      │
│                                                               │
│  Streams:                                                     │
│  ├─ alerts:stream    (Suricata alerts)                       │
│  ├─ blocks:stream    (Block commands)                        │
│  ├─ stats:stream     (System metrics)                        │
│  └─ health:stream    (Heartbeats)                            │
│                                                               │
│  Consumer Groups:                                             │
│  ├─ ai-processors    (Multiple AI Suricata instances)        │
│  └─ pfsense-agents   (Multiple pfSense firewalls)            │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            │ Redis Protocol
                            │
┌───────────────────────────┴──────────────────────────────────┐
│              AI Suricata System (Modified)                    │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │         AI Suricata Core (Modified)                    │  │
│  │                                                         │  │
│  │  ┌─────────────────┐  ┌─────────────────┐             │  │
│  │  │ Stream Consumer │← │  alerts:stream  │             │  │
│  │  │ (Replaces SSH)  │  │  (Subscribe)    │             │  │
│  │  └────────┬────────┘  └─────────────────┘             │  │
│  │           │                                             │  │
│  │           ▼                                             │  │
│  │  ┌─────────────────┐                                   │  │
│  │  │  ML Classifier  │                                   │  │
│  │  │  - Features     │                                   │  │
│  │  │  - Threat Score │                                   │  │
│  │  └────────┬────────┘                                   │  │
│  │           │                                             │  │
│  │           ▼                                             │  │
│  │  ┌─────────────────┐  ┌─────────────────┐             │  │
│  │  │ Block Publisher │→ │  blocks:stream  │             │  │
│  │  │ (Replaces SSH)  │  │  (Publish)      │             │  │
│  │  └─────────────────┘  └─────────────────┘             │  │
│  └────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

---

## Implementation Plan

### Phase 1: pfSense Agent (NEW - 4 hours)

**File**: `pfsense_agent.py` (deploy to pfSense)

#### Components:

1. **Log Watcher**
   - Watch `/var/log/suricata/eve.json` for new alerts
   - Use `inotify` or `tail -f` to detect changes
   - Parse JSON and publish to `alerts:stream`
   - Include metadata: timestamp, hostname, source

2. **Command Subscriber**
   - Subscribe to `blocks:stream` and `commands:stream`
   - Execute firewall commands (add/remove rules)
   - Acknowledge successful execution
   - Report failures back via `errors:stream`

3. **System Metrics Publisher**
   - Publish CPU, memory, temperature to `stats:stream`
   - Heartbeat every 30 seconds to `health:stream`
   - Lightweight, minimal overhead

#### Installation on pfSense:

```bash
# Install Python on pfSense
pkg install python39

# Install redis-py
pip3 install redis

# Copy agent
scp pfsense_agent.py admin@192.168.1.1:/root/

# Create systemd/rc.d service
cat > /usr/local/etc/rc.d/pfsense_agent << 'EOF'
#!/bin/sh
# PROVIDE: pfsense_agent
# REQUIRE: DAEMON
. /etc/rc.subr
name="pfsense_agent"
rcvar=pfsense_agent_enable
command="/usr/local/bin/python3.9"
command_args="/root/pfsense_agent.py"
run_rc_command "$1"
EOF

# Enable and start
echo 'pfsense_agent_enable="YES"' >> /etc/rc.conf
service pfsense_agent start
```

---

### Phase 2: Modify AI Suricata (2 hours)

#### Files to Modify:

1. **alert_collector.py** → **stream_consumer.py** (NEW)
   - Replace SSH tail with Redis Stream consumer
   - Use `XREAD` or `XREADGROUP` for alerts
   - Handle reconnection and message replay
   - Consumer group: `ai-processors`

2. **auto_responder.py**
   - Replace SSH command execution with Redis publish
   - Publish to `blocks:stream` instead of SSH
   - Wait for acknowledgment from pfSense agent
   - Timeout and retry logic

3. **thermal_monitor.py**
   - Subscribe to `stats:stream` instead of SSH polling
   - Passive reception of metrics
   - Lower overhead, real-time updates

#### New File: `stream_consumer.py`

```python
class RedisStreamConsumer:
    def __init__(self, redis_client, stream_name='alerts:stream',
                 group_name='ai-processors', consumer_name='ai-1'):
        self.redis = redis_client
        self.stream = stream_name
        self.group = group_name
        self.consumer = consumer_name

    def create_group(self):
        """Create consumer group if not exists"""
        try:
            self.redis.xgroup_create(self.stream, self.group, id='0', mkstream=True)
        except:
            pass  # Group already exists

    def consume_alerts(self, count=10, block=1000):
        """Consume alerts from stream"""
        messages = self.redis.xreadgroup(
            groupname=self.group,
            consumername=self.consumer,
            streams={self.stream: '>'},
            count=count,
            block=block
        )

        for stream_name, stream_messages in messages:
            for msg_id, msg_data in stream_messages:
                yield msg_id, msg_data

    def acknowledge(self, msg_id):
        """Acknowledge message processed"""
        self.redis.xack(self.stream, self.group, msg_id)
```

---

### Phase 3: Redis Stream Schema (30 minutes)

#### Stream Definitions:

**1. alerts:stream** (pfSense → AI Suricata)
```
Message ID: <timestamp-sequence>
Fields:
  - timestamp: ISO8601 timestamp
  - hostname: pfSense hostname
  - alert_type: alert|flow|dns|http|tls
  - event_data: JSON-encoded Suricata event
  - src_ip: Source IP
  - dest_ip: Destination IP
  - signature_id: Suricata SID
  - severity: 1-4
```

**2. blocks:stream** (AI Suricata → pfSense)
```
Message ID: <timestamp-sequence>
Fields:
  - action: block|unblock|rate_limit
  - ip_address: Target IP
  - reason: Threat description
  - threat_score: 0.0-1.0
  - duration: TTL in seconds (default: 86400)
  - command_id: Unique ID for tracking
```

**3. stats:stream** (pfSense → AI Suricata)
```
Message ID: <timestamp-sequence>
Fields:
  - hostname: pfSense hostname
  - cpu_usage: 0-100%
  - memory_usage: bytes
  - temperature: Celsius
  - active_connections: count
  - interfaces: JSON-encoded interface stats
```

**4. health:stream** (Bidirectional heartbeat)
```
Message ID: <timestamp-sequence>
Fields:
  - source: pfsense-agent|ai-suricata
  - hostname: Hostname
  - status: healthy|degraded|error
  - message: Optional status message
```

**5. acks:stream** (pfSense → AI Suricata - acknowledgments)
```
Message ID: <timestamp-sequence>
Fields:
  - command_id: Original command ID
  - status: success|failure
  - error_message: If failed
  - execution_time: Milliseconds
```

---

### Phase 4: Migration Strategy (1 hour)

#### Step-by-Step Migration:

1. **Deploy pfSense Agent** (non-breaking)
   - Agent runs alongside existing SSH setup
   - Publishes alerts to Redis
   - Does not interfere with current system

2. **Test Dual Mode** (validation)
   - AI Suricata receives alerts via both SSH and Redis
   - Compare data consistency
   - Validate all alerts received

3. **Switch to Redis** (cutover)
   - Disable SSH alert collection
   - Enable Redis stream consumer
   - Monitor for 24 hours

4. **Remove SSH Code** (cleanup)
   - Remove SSH dependencies from code
   - Update documentation
   - Archive old SSH-based modules

#### Rollback Plan:

If issues occur:
1. Re-enable SSH mode via config flag: `USE_MESSAGE_QUEUE=false`
2. Disable pfSense agent: `service pfsense_agent stop`
3. System reverts to SSH-based operation
4. No data loss (Redis streams persist messages)

---

## Configuration

### New config.env Settings:

```bash
# Message Queue Configuration
MESSAGE_QUEUE_ENABLED=true         # Enable Redis Streams (default: false for compatibility)
MESSAGE_QUEUE_ALERTS_STREAM=alerts:stream
MESSAGE_QUEUE_BLOCKS_STREAM=blocks:stream
MESSAGE_QUEUE_STATS_STREAM=stats:stream
MESSAGE_QUEUE_HEALTH_STREAM=health:stream
MESSAGE_QUEUE_CONSUMER_GROUP=ai-processors
MESSAGE_QUEUE_CONSUMER_NAME=ai-suricata-1  # Unique per instance
MESSAGE_QUEUE_BLOCK_TIME=1000       # XREAD block time (ms)
MESSAGE_QUEUE_BATCH_SIZE=100        # Messages per batch

# Legacy SSH (fallback)
SSH_ENABLED=true                    # Keep SSH as fallback
SSH_FALLBACK_ON_QUEUE_FAILURE=true  # Auto-fallback if Redis unavailable
```

---

## Benefits Analysis

### Performance Improvements:

| Metric | SSH (Current) | Message Queue | Improvement |
|--------|--------------|---------------|-------------|
| **Latency** | 10-50ms | <1ms | **50x faster** |
| **Throughput** | 1,000/sec | 100,000+/sec | **100x faster** |
| **Fault Tolerance** | Single point failure | Message persistence | **∞ better** |
| **Scalability** | Single instance | Unlimited consumers | **Horizontal** |
| **Setup Complexity** | SSH keys + firewall | Redis connection | **Simpler** |
| **Security** | Broad SSH access | Redis auth only | **More secure** |

### Operational Benefits:

✅ **Zero Data Loss** - Messages persist in Redis streams
✅ **Load Balancing** - Multiple AI Suricata instances share workload
✅ **Replay Capability** - Can re-process historical alerts
✅ **Monitoring** - Stream lag, consumer health metrics
✅ **Async** - Non-blocking, event-driven architecture
✅ **Multi-Firewall** - Single AI Suricata can monitor 10+ pfSense boxes
✅ **Distributed** - AI Suricata instances can be geographically separated

### Cost Savings:

- **No SSH overhead**: ~50ms latency eliminated per alert
- **Better resource utilization**: Async = higher throughput
- **Reduced complexity**: No SSH key management
- **Lower bandwidth**: Binary Redis protocol vs SSH encryption

---

## Testing Strategy

### Unit Tests:

1. **Stream Publisher** (pfSense agent)
   - Test alert publishing
   - Verify JSON serialization
   - Handle connection failures

2. **Stream Consumer** (AI Suricata)
   - Test message consumption
   - Verify acknowledgments
   - Handle duplicate messages

3. **Command Execution** (pfSense agent)
   - Test firewall blocking
   - Verify command acknowledgments
   - Handle malformed commands

### Integration Tests:

1. **End-to-End Alert Flow**
   - Trigger test alert on pfSense
   - Verify AI Suricata receives it
   - Check ML classification
   - Confirm block command sent
   - Verify firewall rule created

2. **Failure Scenarios**
   - Redis connection loss
   - Message queue full
   - Consumer group conflicts
   - Network partitions

3. **Load Testing**
   - 10,000 alerts/second sustained
   - Multiple consumers
   - Consumer group rebalancing

---

## Monitoring & Observability

### New Prometheus Metrics:

```
# Stream health
redis_stream_length{stream="alerts"}
redis_stream_lag{group="ai-processors",consumer="ai-1"}
redis_stream_pending{group="ai-processors"}

# Message processing
message_queue_messages_consumed_total
message_queue_messages_acknowledged_total
message_queue_processing_time_seconds

# Agent health
pfsense_agent_heartbeat_last_seen_seconds
pfsense_agent_commands_executed_total
pfsense_agent_errors_total
```

### Grafana Dashboard:

New panel: **Message Queue Health**
- Stream lag graph
- Messages per second
- Consumer group status
- Acknowledgment rate
- Error rate

---

## Security Considerations

### Improvements Over SSH:

1. **Reduced Attack Surface**
   - No SSH daemon exposure
   - No SSH key management
   - No shell access required

2. **Principle of Least Privilege**
   - pfSense agent only needs Redis connection
   - No root/admin privileges for reading logs
   - Firewall changes via controlled API

3. **Network Isolation**
   - Redis can use TLS encryption
   - Redis AUTH for authentication
   - No need for firewall rules allowing SSH

4. **Audit Trail**
   - All commands logged in Redis streams
   - Message replay for forensics
   - Acknowledgment tracking

### Redis Security Hardening:

```bash
# Redis configuration
requirepass <strong-password>
rename-command FLUSHDB ""
rename-command FLUSHALL ""
rename-command CONFIG ""
bind 127.0.0.1 ::1  # localhost only (or VPN IP)

# TLS encryption (optional)
tls-port 6380
tls-cert-file /path/to/redis.crt
tls-key-file /path/to/redis.key
tls-ca-cert-file /path/to/ca.crt
```

---

## Rollout Timeline

### Week 1: Development
- **Day 1-2**: Build pfSense agent (log watcher + command subscriber)
- **Day 3**: Modify AI Suricata (stream consumer)
- **Day 4**: Integration testing
- **Day 5**: Documentation

### Week 2: Deployment
- **Day 1**: Deploy agent to test pfSense
- **Day 2**: Run in dual mode (SSH + Redis)
- **Day 3**: Validate data consistency
- **Day 4**: Switch to Redis primary
- **Day 5**: Monitor and tune

### Week 3: Production
- **Day 1**: Deploy to production pfSense
- **Day 2**: Monitor 24/7
- **Day 3**: Remove SSH dependencies
- **Day 4**: Performance tuning
- **Day 5**: Documentation update

---

## Success Criteria

### Must Have:
✅ Zero data loss during migration
✅ <1ms average latency for alerts
✅ 100% uptime during switchover
✅ All existing features working
✅ Graceful fallback to SSH if Redis fails

### Nice to Have:
✅ 10x throughput improvement measured
✅ Multiple AI Suricata instances tested
✅ Grafana dashboard for streams
✅ Automated tests passing
✅ Documentation complete

---

## Future Enhancements

### Phase 2 (Post-MVP):

1. **Dead Letter Queue** - Failed messages sent to DLQ for review
2. **Message Encryption** - End-to-end encryption for sensitive data
3. **Multi-Firewall Support** - Single AI Suricata monitors 10+ pfSense boxes
4. **Stream Compaction** - Automatic cleanup of old messages
5. **Message Routing** - Route alerts to specialized processors
6. **High Availability** - Redis Sentinel for automatic failover

---

## Appendix: Code Examples

### pfSense Agent (Simplified)

```python
#!/usr/bin/env python3
"""
pfSense Agent - Redis Stream Publisher
Replaces SSH for log streaming
"""

import redis
import json
import time
from tail import Tail

class PfSenseAgent:
    def __init__(self, redis_host='localhost', redis_port=6379):
        self.redis = redis.Redis(host=redis_host, port=redis_port, decode_responses=True)
        self.hostname = socket.gethostname()

    def watch_alerts(self, log_file='/var/log/suricata/eve.json'):
        """Watch Suricata log and publish to Redis"""
        for line in Tail(log_file).follow():
            try:
                event = json.loads(line)

                # Publish to alerts stream
                self.redis.xadd('alerts:stream', {
                    'timestamp': event.get('timestamp'),
                    'hostname': self.hostname,
                    'event_type': event.get('event_type'),
                    'event_data': json.dumps(event),
                    'src_ip': event.get('src_ip', ''),
                    'dest_ip': event.get('dest_ip', ''),
                })
            except Exception as e:
                print(f"Error publishing alert: {e}")

    def process_commands(self):
        """Subscribe to command stream and execute"""
        last_id = '0'
        while True:
            messages = self.redis.xread({'blocks:stream': last_id}, block=1000)

            for stream, stream_messages in messages:
                for msg_id, msg_data in stream_messages:
                    self.execute_command(msg_id, msg_data)
                    last_id = msg_id

    def execute_command(self, msg_id, data):
        """Execute firewall command"""
        action = data.get('action')
        ip = data.get('ip_address')

        if action == 'block':
            # Execute pfctl command to block IP
            result = self.block_ip(ip, data.get('reason'))

            # Acknowledge
            self.redis.xadd('acks:stream', {
                'command_id': data.get('command_id'),
                'status': 'success' if result else 'failure',
                'execution_time': 0
            })

if __name__ == '__main__':
    agent = PfSenseAgent()
    agent.watch_alerts()
```

---

**Document Version**: 1.0
**Created**: 2025-12-24
**Author**: AI Suricata Team
**Status**: Planning Phase

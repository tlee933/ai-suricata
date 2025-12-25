# AI Suricata Monitoring - Quick Guide

## ✅ What's Been Set Up

### 1. **Prometheus Exporter** (Port 9102)
AI Suricata now exposes real-time metrics in Prometheus format.

**Test the exporter:**
```bash
curl http://localhost:9102/metrics | grep suricata_ai
```

**Metrics Available:**
- `suricata_ai_alerts_total` - Total alerts processed
- `suricata_ai_alerts_by_severity_total` - Alerts by severity (CRITICAL/HIGH/MEDIUM/LOW/INFO)
- `suricata_ai_blocks_total` - Total IPs blocked
- `suricata_ai_active_blocks` - Currently active blocks
- `suricata_ai_critical_threats_total` - Critical threats detected
- `suricata_ai_avg_threat_score` - Average threat score
- `suricata_ai_processing_time_seconds` - Average processing time
- `suricata_ai_alerts_per_second` - Current alert rate
- `suricata_ai_top_source_ips` - Top attacking IPs

### 2. **Prometheus Scraping**
Prometheus is configured to scrape AI Suricata metrics every 15 seconds.

**Config location:**
`/home/hashcat/TheRock/monitoring/prometheus/prometheus.yml`

**Verify scraping:**
```bash
curl -s 'http://localhost:9090/api/v1/query?query=suricata_ai_uptime_seconds'
```

### 3. **Grafana Dashboard**
A comprehensive dashboard has been created with 12 panels showing:

#### Real-time Metrics:
- **System uptime** - How long AI Suricata has been running
- **Total alerts processed** - Running count
- **Critical threats** - High-priority detections
- **Active blocks** - Currently blocked IPs

#### Visualizations:
- **Alert rate graph** - Alerts per second over time
- **Alerts by severity pie chart** - Distribution of threat levels
- **Threat metrics timeline** - CRITICAL/HIGH/MEDIUM/LOW trends
- **Top source IPs bar chart** - Most active attacking hosts
- **Actions taken** - Blocks and rate limits over time
- **Performance gauges** - Threat score, processing time, alert rate

## 🌐 Access Your Dashboard

### Grafana Web UI:
**URL:** http://localhost:3000 (or http://192.168.1.100:3000)

**Dashboard Name:** "AI Suricata - Threat Detection & Response"

**How to find it:**
1. Open Grafana in your browser
2. Click "Dashboards" in the left sidebar
3. Search for "AI Suricata" or "Threat Detection"
4. Click to open the dashboard

### Prometheus Web UI:
**URL:** http://localhost:9090

**Example queries:**
```promql
# Alert rate (last 5 minutes)
rate(suricata_ai_alerts_total[5m])

# Critical threats
suricata_ai_critical_threats_total

# Top 5 attacking IPs
topk(5, suricata_ai_top_source_ips)

# Alerts by severity
suricata_ai_alerts_by_severity_total
```

## 📊 Dashboard Panels

1. **System Overview** - Uptime indicator
2. **Total Alerts Processed** - Running counter with trend
3. **Critical Threats** - Count of CRITICAL severity alerts
4. **Active Blocks** - Currently blocked IPs
5. **Alert Rate** - Alerts per second graph
6. **Alerts by Severity** - Pie chart showing distribution
7. **Threat Metrics Over Time** - Line graph by severity
8. **Top Source IPs** - Bar chart of most active attackers
9. **Actions Taken** - Blocks and rate limits timeline
10. **Average Threat Score** - Gauge (0-1 scale)
11. **Processing Time** - Performance gauge
12. **Alert Rate Gauge** - Current alerts/sec

## 🔧 Customization

### Modify Dashboard:
```bash
# Edit the JSON
nano /home/hashcat/TheRock/monitoring/grafana/dashboards/ai-suricata.json

# Restart Grafana to apply changes
docker restart grafana
```

### Adjust Scrape Interval:
```bash
# Edit Prometheus config
nano /home/hashcat/TheRock/monitoring/prometheus/prometheus.yml

# Find the ai-suricata job and modify:
scrape_interval: 15s  # Change this value

# Reload Prometheus
curl -X POST http://localhost:9090/-/reload
```

## 🎯 Useful Alerts

You can set up Grafana alerts for:
- Critical threats detected (suricata_ai_critical_threats_total > 0)
- High alert rate (rate(suricata_ai_alerts_total[1m]) > 10)
- Many active blocks (suricata_ai_active_blocks > 50)
- High average threat score (suricata_ai_avg_threat_score > 0.7)

## 📁 File Locations

```
AI Suricata:
/home/hashcat/pfsense/ai_suricata/prometheus_exporter.py
/home/hashcat/pfsense/ai_suricata/ai_suricata.py (modified)

Prometheus:
/home/hashcat/TheRock/monitoring/prometheus/prometheus.yml

Grafana Dashboard:
/home/hashcat/TheRock/monitoring/grafana/dashboards/ai-suricata.json
```

## 🚀 Quick Commands

```bash
# Check if exporter is running
curl -s http://localhost:9102/health

# View current metrics
curl -s http://localhost:9102/metrics | grep suricata_ai | head -20

# Check Prometheus targets
curl -s http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.job=="ai-suricata")'

# Restart AI Suricata (will restart exporter)
sudo systemctl restart ai-suricata

# View Grafana logs
docker logs grafana -f
```

## 🎉 You're All Set!

The AI Suricata monitoring stack is now complete:
- ✅ Metrics being collected
- ✅ Prometheus scraping data
- ✅ Grafana dashboard visualizing threats
- ✅ Real-time monitoring of security events

Visit http://localhost:3000 to see your security dashboard in action!

#!/bin/bash
# AI Suricata Service Management Script

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

show_status() {
    echo -e "${BLUE}=== AI Suricata Service Status ===${NC}"
    sudo systemctl status ai-suricata.service --no-pager -l | head -20
    echo ""
}

show_logs() {
    echo -e "${BLUE}=== Recent Logs (last 50 lines) ===${NC}"
    sudo journalctl -u ai-suricata.service -n 50 --no-pager
}

watch_logs() {
    echo -e "${BLUE}=== Live Log Monitoring (Ctrl+C to stop) ===${NC}"
    sudo journalctl -u ai-suricata.service -f
}

watch_threats() {
    echo -e "${BLUE}=== Live Threat Monitoring (HIGH/CRITICAL only) ===${NC}"
    sudo journalctl -u ai-suricata.service -f | grep -E 'HIGH|CRITICAL|BLOCK'
}

start_service() {
    echo -e "${GREEN}Starting AI Suricata...${NC}"
    sudo systemctl start ai-suricata.service
    sleep 2
    show_status
}

stop_service() {
    echo -e "${YELLOW}Stopping AI Suricata...${NC}"
    sudo systemctl stop ai-suricata.service
    echo "Service stopped."
}

restart_service() {
    echo -e "${YELLOW}Restarting AI Suricata...${NC}"
    sudo systemctl restart ai-suricata.service
    sleep 2
    show_status
}

enable_service() {
    echo -e "${GREEN}Enabling AI Suricata (start on boot)...${NC}"
    sudo systemctl enable ai-suricata.service
    echo "Service will start automatically on boot."
}

disable_service() {
    echo -e "${YELLOW}Disabling AI Suricata (won't start on boot)...${NC}"
    sudo systemctl disable ai-suricata.service
    echo "Service will not start on boot."
}

show_stats() {
    echo -e "${BLUE}=== System Statistics ===${NC}"
    echo -n "Service uptime: "
    systemctl show ai-suricata.service -p ActiveEnterTimestamp --value
    echo -n "Memory usage: "
    systemctl show ai-suricata.service -p MemoryCurrent --value | awk '{printf "%.1f MB\n", $1/1024/1024}'
    echo -n "CPU time: "
    systemctl show ai-suricata.service -p CPUUsageNSec --value | awk '{printf "%.2f seconds\n", $1/1000000000}'
    echo ""
    echo "Recent threat activity:"
    sudo journalctl -u ai-suricata.service --since "5 minutes ago" | grep -E 'CRITICAL|HIGH|MEDIUM' | wc -l | xargs -I{} echo "  {} alerts in last 5 minutes"
}

case "$1" in
    status)
        show_status
        ;;
    logs)
        show_logs
        ;;
    watch)
        watch_logs
        ;;
    threats)
        watch_threats
        ;;
    start)
        start_service
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
    enable)
        enable_service
        ;;
    disable)
        disable_service
        ;;
    stats)
        show_stats
        ;;
    *)
        echo "AI Suricata Service Management"
        echo ""
        echo "Usage: $0 {command}"
        echo ""
        echo "Commands:"
        echo "  status      - Show service status"
        echo "  logs        - Show recent logs"
        echo "  watch       - Watch live logs"
        echo "  threats     - Watch only HIGH/CRITICAL threats"
        echo "  start       - Start the service"
        echo "  stop        - Stop the service"
        echo "  restart     - Restart the service"
        echo "  enable      - Enable auto-start on boot"
        echo "  disable     - Disable auto-start on boot"
        echo "  stats       - Show statistics"
        echo ""
        echo "Current status:"
        systemctl is-active ai-suricata.service >/dev/null 2>&1
        if [ $? -eq 0 ]; then
            echo -e "  Service: ${GREEN}RUNNING${NC}"
        else
            echo -e "  Service: ${RED}STOPPED${NC}"
        fi
        systemctl is-enabled ai-suricata.service >/dev/null 2>&1
        if [ $? -eq 0 ]; then
            echo -e "  Auto-start: ${GREEN}ENABLED${NC}"
        else
            echo -e "  Auto-start: ${YELLOW}DISABLED${NC}"
        fi
        ;;
esac

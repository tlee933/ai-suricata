#!/usr/bin/env python3
"""
Thermal Monitor for pfSense Firewall
Collects CPU and system temperatures via SSH and exposes metrics to Prometheus
"""

import subprocess
import re
import time
import logging
from threading import Thread, Event
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ThermalMonitor(Thread):
    """
    Background thread that periodically collects thermal sensor data from pfSense
    """

    def __init__(self,
                 pfsense_host: str,
                 pfsense_user: str,
                 metrics_store,
                 poll_interval: int = 30,
                 warn_threshold: float = 75.0,
                 critical_threshold: float = 85.0):
        """
        Initialize thermal monitor

        Args:
            pfsense_host: pfSense hostname/IP
            pfsense_user: SSH username
            metrics_store: SuricataMetrics instance for storing metrics
            poll_interval: Seconds between polls (default: 30)
            warn_threshold: Temperature warning threshold in Celsius (default: 75)
            critical_threshold: Temperature critical threshold in Celsius (default: 85)
        """
        super().__init__(daemon=True, name="ThermalMonitor")
        self.pfsense_host = pfsense_host
        self.pfsense_user = pfsense_user
        self.metrics = metrics_store
        self.poll_interval = poll_interval
        self.warn_threshold = warn_threshold
        self.critical_threshold = critical_threshold
        self.stop_event = Event()

        logger.info(f"Thermal monitor initialized: poll_interval={poll_interval}s, "
                   f"warn={warn_threshold}°C, critical={critical_threshold}°C")

    def collect_temperatures(self) -> Dict[str, float]:
        """
        Collect temperature readings from pfSense via SSH

        Returns:
            Dict mapping sensor names to temperatures in Celsius
        """
        temps = {}

        try:
            # Execute sysctl command to get all temperature sensors
            ssh_cmd = [
                'ssh',
                f'{self.pfsense_user}@{self.pfsense_host}',
                'sysctl -a | grep -iE "(temperature|temp:)" | grep -v "tempaddr"'
            ]

            result = subprocess.run(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                logger.error(f"Failed to collect temperatures: {result.stderr}")
                return temps

            # Parse sysctl output
            # Format examples:
            #   hw.acpi.thermal.tz0.temperature: 27.9C
            #   dev.pchtherm.0.temperature: 52.5C
            #   dev.cpu.0.temperature: 45.0C

            for line in result.stdout.splitlines():
                match = re.search(r'^([\w.]+):\s+([\d.]+)C', line.strip())
                if match:
                    sensor_name = match.group(1)
                    temp_celsius = float(match.group(2))
                    temps[sensor_name] = temp_celsius

            logger.debug(f"Collected {len(temps)} temperature sensors")

        except subprocess.TimeoutExpired:
            logger.error("Timeout collecting temperatures from pfSense")
        except Exception as e:
            logger.error(f"Error collecting temperatures: {e}")

        return temps

    def process_temperatures(self, temps: Dict[str, float]):
        """
        Process temperature readings and update metrics

        Args:
            temps: Dict of sensor names to temperatures
        """
        if not temps:
            logger.warning("No temperature data collected")
            return

        # Calculate aggregate metrics
        all_temps = list(temps.values())
        max_temp = max(all_temps)
        min_temp = min(all_temps)
        avg_temp = sum(all_temps) / len(all_temps)

        # Update metrics store
        self.metrics.record_pfsense_temperatures(temps, max_temp, min_temp, avg_temp)

        # Check thresholds and log warnings
        if max_temp >= self.critical_threshold:
            logger.critical(f"🔥 CRITICAL: pfSense temperature {max_temp:.1f}°C "
                          f">= {self.critical_threshold}°C")
        elif max_temp >= self.warn_threshold:
            logger.warning(f"⚠️  WARNING: pfSense temperature {max_temp:.1f}°C "
                          f">= {self.warn_threshold}°C")

        # Log summary
        logger.info(f"Thermal: max={max_temp:.1f}°C, avg={avg_temp:.1f}°C, "
                   f"min={min_temp:.1f}°C ({len(temps)} sensors)")

    def run(self):
        """
        Main thread loop - periodically collect and process temperatures
        """
        logger.info("Thermal monitor thread started")

        # Initial collection on startup
        temps = self.collect_temperatures()
        self.process_temperatures(temps)

        # Periodic collection loop
        while not self.stop_event.wait(self.poll_interval):
            temps = self.collect_temperatures()
            self.process_temperatures(temps)

        logger.info("Thermal monitor thread stopped")

    def stop(self):
        """
        Signal the monitor thread to stop gracefully
        """
        logger.info("Stopping thermal monitor...")
        self.stop_event.set()


if __name__ == "__main__":
    # Test standalone
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Mock metrics store for testing
    class MockMetrics:
        def record_pfsense_temperatures(self, temps, max_t, min_t, avg_t):
            print(f"Temperatures: {temps}")
            print(f"Max: {max_t:.1f}°C, Avg: {avg_t:.1f}°C, Min: {min_t:.1f}°C")

    monitor = ThermalMonitor(
        pfsense_host="192.168.1.1",
        pfsense_user="admin",
        metrics_store=MockMetrics(),
        poll_interval=10
    )

    # Test collection
    temps = monitor.collect_temperatures()
    monitor.process_temperatures(temps)

#!/usr/bin/env python3
"""
Redis Client for AI Suricata
Provides caching and distributed state management with graceful fallback.
"""

import json
import time
from datetime import datetime
from typing import Dict, Optional, List, Any

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("[!] Redis package not installed. Install with: pip3 install redis")


class RedisClient:
    """
    Redis abstraction layer for AI Suricata with graceful fallback.

    Features:
    - IP behavioral profile caching
    - Blocked IP persistence with auto-expiration
    - Metrics caching for performance
    - Top IPs tracking with sorted sets
    - Rate limiting counters
    - Health checks and reconnection logic
    """

    def __init__(self, enabled: bool = False, host: str = 'localhost', port: int = 6379,
                 db: int = 0, password: Optional[str] = None, key_prefix: str = 'ai_suricata',
                 socket_timeout: int = 2, socket_keepalive: bool = True):
        """
        Initialize Redis client.

        Args:
            enabled: Enable Redis integration (default: False for safety)
            host: Redis server hostname
            port: Redis server port
            db: Redis database number
            password: Optional Redis password
            key_prefix: Prefix for all Redis keys (namespace)
            socket_timeout: Connection timeout in seconds
            socket_keepalive: Enable TCP keepalive
        """
        self.enabled = enabled and REDIS_AVAILABLE
        self.host = host
        self.port = port
        self.key_prefix = key_prefix
        self.redis = None
        self.connection_healthy = False

        if not REDIS_AVAILABLE:
            print("[!] Redis client disabled: redis package not installed")
            self.enabled = False
            return

        if not self.enabled:
            print("[*] Redis client disabled (REDIS_ENABLED=false)")
            return

        try:
            # Create Redis connection with connection pooling
            self.redis = redis.Redis(
                host=host,
                port=port,
                db=db,
                password=password if password else None,
                decode_responses=True,  # Auto-decode bytes to strings
                socket_timeout=socket_timeout,
                socket_keepalive=socket_keepalive,
                socket_keepalive_options={},
                health_check_interval=30  # Check connection health every 30s
            )

            # Test connection
            self.redis.ping()
            self.connection_healthy = True
            print(f"[+] Redis connected: {host}:{port} (db={db}, prefix={key_prefix})")

        except Exception as e:
            print(f"[!] Redis connection failed: {e}")
            print("[*] Continuing without Redis (graceful degradation)")
            self.enabled = False
            self.redis = None

    def _key(self, key: str) -> str:
        """Add namespace prefix to key."""
        return f"{self.key_prefix}:{key}"

    def is_healthy(self) -> bool:
        """Check if Redis connection is healthy."""
        if not self.enabled or not self.redis:
            return False
        try:
            self.redis.ping()
            self.connection_healthy = True
            return True
        except:
            self.connection_healthy = False
            return False

    # ============================================================
    # IP Behavior Caching
    # ============================================================

    def get_ip_behavior(self, ip: str) -> Optional[Dict[str, Any]]:
        """
        Get IP behavioral profile from Redis.

        Args:
            ip: IP address

        Returns:
            Behavioral profile dict or None if not found/unavailable
        """
        if not self.enabled:
            return None
        try:
            data = self.redis.hgetall(self._key(f"ip_behavior:{ip}"))
            if not data:
                return None

            # Convert string values back to appropriate types
            return {
                "alert_count": int(data.get("alert_count", 0)),
                "unique_ports": int(data.get("unique_ports", 0)),
                "unique_dest_ips": int(data.get("unique_dest_ips", 0)),
                "port_scan_score": float(data.get("port_scan_score", 0.0)),
                "last_alert": data.get("last_alert", ""),
                "first_seen": data.get("first_seen", "")
            }
        except Exception as e:
            print(f"[!] Redis get_ip_behavior failed: {e}")
            return None

    def set_ip_behavior(self, ip: str, behavior: Dict[str, Any], ttl: int = 86400) -> bool:
        """
        Cache IP behavioral profile in Redis with TTL.

        Args:
            ip: IP address
            behavior: Behavioral profile dict
            ttl: Time-to-live in seconds (default: 24 hours)

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
        try:
            key = self._key(f"ip_behavior:{ip}")

            # Store as Redis hash for efficiency
            self.redis.hset(key, mapping={
                "alert_count": behavior.get("alert_count", 0),
                "unique_ports": behavior.get("unique_ports", 0),
                "unique_dest_ips": behavior.get("unique_dest_ips", 0),
                "port_scan_score": behavior.get("port_scan_score", 0.0),
                "last_alert": behavior.get("last_alert", ""),
                "first_seen": behavior.get("first_seen", "")
            })

            # Set expiration
            self.redis.expire(key, ttl)
            return True
        except Exception as e:
            print(f"[!] Redis set_ip_behavior failed: {e}")
            return False

    # ============================================================
    # Blocked IP Persistence
    # ============================================================

    def set_blocked_ip(self, ip: str, reason: str, score: float, ttl: int = 86400) -> bool:
        """
        Store blocked IP with auto-expiration.

        Args:
            ip: IP address to block
            reason: Reason for blocking
            score: Threat score
            ttl: Time-to-live in seconds (default: 24 hours)

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
        try:
            key = self._key(f"blocked_ip:{ip}")
            data = json.dumps({
                "reason": reason,
                "score": score,
                "timestamp": time.time(),
                "blocked_at": datetime.now().isoformat()
            })

            # Store with TTL (auto-unblock after expiration)
            self.redis.setex(key, ttl, data)

            # Add to active blocks set
            self.redis.sadd(self._key("active_blocks"), ip)

            # Also set TTL on the set member (cleanup)
            return True
        except Exception as e:
            print(f"[!] Redis set_blocked_ip failed: {e}")
            return False

    def is_blocked(self, ip: str) -> bool:
        """
        Check if IP is currently blocked.

        Args:
            ip: IP address to check

        Returns:
            True if blocked, False otherwise
        """
        if not self.enabled:
            return False
        try:
            return self.redis.exists(self._key(f"blocked_ip:{ip}")) > 0
        except Exception as e:
            print(f"[!] Redis is_blocked failed: {e}")
            return False

    def get_blocked_ip_info(self, ip: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a blocked IP.

        Args:
            ip: IP address

        Returns:
            Block info dict or None
        """
        if not self.enabled:
            return None
        try:
            data = self.redis.get(self._key(f"blocked_ip:{ip}"))
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            print(f"[!] Redis get_blocked_ip_info failed: {e}")
            return None

    def unblock_ip(self, ip: str) -> bool:
        """
        Remove IP from blocked list.

        Args:
            ip: IP address to unblock

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
        try:
            self.redis.delete(self._key(f"blocked_ip:{ip}"))
            self.redis.srem(self._key("active_blocks"), ip)
            return True
        except Exception as e:
            print(f"[!] Redis unblock_ip failed: {e}")
            return False

    def get_active_blocks(self) -> List[str]:
        """
        Get list of currently blocked IPs.

        Returns:
            List of IP addresses
        """
        if not self.enabled:
            return []
        try:
            return list(self.redis.smembers(self._key("active_blocks")))
        except Exception as e:
            print(f"[!] Redis get_active_blocks failed: {e}")
            return []

    def cleanup_expired_blocks(self) -> int:
        """
        Remove expired IPs from active_blocks set.
        Redis TTL handles auto-expiration, but we need to clean up the set.

        Returns:
            Number of IPs removed
        """
        if not self.enabled:
            return 0
        try:
            active_ips = self.get_active_blocks()
            removed_count = 0

            for ip in active_ips:
                # Check if the block key still exists
                if not self.redis.exists(self._key(f"blocked_ip:{ip}")):
                    # Block expired, remove from set
                    self.redis.srem(self._key("active_blocks"), ip)
                    removed_count += 1

            return removed_count
        except Exception as e:
            print(f"[!] Redis cleanup_expired_blocks failed: {e}")
            return 0

    # ============================================================
    # Metrics Caching
    # ============================================================

    def set_metric_cache(self, metric_name: str, value: Any, ttl: int = 5) -> bool:
        """
        Cache a computed metric value.

        Args:
            metric_name: Name of the metric
            value: Metric value (will be JSON serialized)
            ttl: Time-to-live in seconds (default: 5s)

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
        try:
            key = self._key(f"metrics:cache:{metric_name}")
            data = json.dumps(value) if not isinstance(value, str) else value
            self.redis.setex(key, ttl, data)
            return True
        except Exception as e:
            print(f"[!] Redis set_metric_cache failed: {e}")
            return False

    def get_metric_cache(self, metric_name: str) -> Optional[Any]:
        """
        Get cached metric value.

        Args:
            metric_name: Name of the metric

        Returns:
            Cached value or None
        """
        if not self.enabled:
            return None
        try:
            data = self.redis.get(self._key(f"metrics:cache:{metric_name}"))
            if data:
                try:
                    return json.loads(data)
                except:
                    return data  # Return as-is if not JSON
            return None
        except Exception as e:
            print(f"[!] Redis get_metric_cache failed: {e}")
            return None

    # ============================================================
    # Top IPs Tracking (Sorted Set)
    # ============================================================

    def increment_ip_count(self, ip: str, count: int = 1) -> bool:
        """
        Increment alert count for an IP in sorted set.

        Args:
            ip: IP address
            count: Increment amount (default: 1)

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
        try:
            self.redis.zincrby(self._key("top_ips"), count, ip)
            return True
        except Exception as e:
            print(f"[!] Redis increment_ip_count failed: {e}")
            return False

    def get_top_ips(self, limit: int = 50) -> Dict[str, int]:
        """
        Get top N IPs by alert count.

        Args:
            limit: Number of top IPs to return

        Returns:
            Dict of {ip: count}
        """
        if not self.enabled:
            return {}
        try:
            # Get top IPs with scores (descending order)
            results = self.redis.zrevrange(self._key("top_ips"), 0, limit - 1, withscores=True)
            return {ip: int(score) for ip, score in results}
        except Exception as e:
            print(f"[!] Redis get_top_ips failed: {e}")
            return {}

    # ============================================================
    # Rate Limiting
    # ============================================================

    def increment_rate_limit(self, ip: str, window_seconds: int = 60) -> int:
        """
        Increment rate limit counter for an IP with sliding window.

        Args:
            ip: IP address
            window_seconds: Time window in seconds

        Returns:
            Current count in window, or -1 on error
        """
        if not self.enabled:
            return -1
        try:
            key = self._key(f"rate_limit:{ip}:{window_seconds}")
            count = self.redis.incr(key)

            # Set expiration on first increment
            if count == 1:
                self.redis.expire(key, window_seconds)

            return count
        except Exception as e:
            print(f"[!] Redis increment_rate_limit failed: {e}")
            return -1

    def get_rate_limit_count(self, ip: str, window_seconds: int = 60) -> int:
        """
        Get current rate limit count for an IP.

        Args:
            ip: IP address
            window_seconds: Time window in seconds

        Returns:
            Count in window, or 0 on error/not found
        """
        if not self.enabled:
            return 0
        try:
            key = self._key(f"rate_limit:{ip}:{window_seconds}")
            count = self.redis.get(key)
            return int(count) if count else 0
        except Exception as e:
            print(f"[!] Redis get_rate_limit_count failed: {e}")
            return 0

    # ============================================================
    # Health & Monitoring
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        Get Redis statistics for monitoring.

        Returns:
            Dict with Redis stats
        """
        if not self.enabled or not self.redis:
            return {
                "enabled": False,
                "healthy": False,
                "reason": "disabled or not connected"
            }

        try:
            info = self.redis.info()

            return {
                "enabled": True,
                "healthy": self.connection_healthy,
                "host": self.host,
                "port": self.port,
                "db": self.redis.connection_pool.connection_kwargs.get('db', 0),
                "connected_clients": info.get('connected_clients', 0),
                "used_memory_human": info.get('used_memory_human', 'unknown'),
                "used_memory_bytes": info.get('used_memory', 0),
                "total_commands_processed": info.get('total_commands_processed', 0),
                "keyspace_hits": info.get('keyspace_hits', 0),
                "keyspace_misses": info.get('keyspace_misses', 0),
                "hit_rate": self._calculate_hit_rate(
                    info.get('keyspace_hits', 0),
                    info.get('keyspace_misses', 0)
                ),
                "uptime_seconds": info.get('uptime_in_seconds', 0),
                "version": info.get('redis_version', 'unknown')
            }
        except Exception as e:
            return {
                "enabled": True,
                "healthy": False,
                "error": str(e)
            }

    def _calculate_hit_rate(self, hits: int, misses: int) -> float:
        """Calculate cache hit rate percentage."""
        total = hits + misses
        if total == 0:
            return 0.0
        return (hits / total) * 100.0

    def get_key_count(self) -> int:
        """
        Get total number of keys in Redis (for this prefix).

        Returns:
            Number of keys, or 0 on error
        """
        if not self.enabled:
            return 0
        try:
            # Scan for keys with our prefix
            count = 0
            for _ in self.redis.scan_iter(match=f"{self.key_prefix}:*"):
                count += 1
            return count
        except Exception as e:
            print(f"[!] Redis get_key_count failed: {e}")
            return 0

    # ============================================================
    # Utility Methods
    # ============================================================

    def flush_all(self) -> bool:
        """
        Flush all keys with our prefix (for testing/debugging).
        WARNING: This deletes data!

        Returns:
            True if successful, False otherwise
        """
        if not self.enabled:
            return False
        try:
            keys = list(self.redis.scan_iter(match=f"{self.key_prefix}:*"))
            if keys:
                self.redis.delete(*keys)
                print(f"[*] Flushed {len(keys)} Redis keys")
            return True
        except Exception as e:
            print(f"[!] Redis flush_all failed: {e}")
            return False

    def close(self):
        """Close Redis connection gracefully."""
        if self.redis:
            try:
                self.redis.close()
                print("[*] Redis connection closed")
            except:
                pass


if __name__ == "__main__":
    # Test Redis client
    print("Testing Redis client...")

    client = RedisClient(enabled=True, host='localhost', port=6379)

    if client.is_healthy():
        print("[+] Redis is healthy!")

        # Test IP behavior caching
        print("\nTesting IP behavior caching...")
        client.set_ip_behavior("192.168.1.100", {
            "alert_count": 42,
            "unique_ports": 15,
            "port_scan_score": 0.75,
            "last_alert": "2025-12-24T12:00:00"
        })

        behavior = client.get_ip_behavior("192.168.1.100")
        print(f"Retrieved behavior: {behavior}")

        # Test blocked IP
        print("\nTesting blocked IP...")
        client.set_blocked_ip("10.0.0.5", "port_scan", 0.92, ttl=60)
        print(f"Is 10.0.0.5 blocked? {client.is_blocked('10.0.0.5')}")
        print(f"Block info: {client.get_blocked_ip_info('10.0.0.5')}")

        # Test top IPs
        print("\nTesting top IPs...")
        client.increment_ip_count("192.168.1.1", 100)
        client.increment_ip_count("192.168.1.2", 50)
        client.increment_ip_count("192.168.1.3", 75)
        print(f"Top IPs: {client.get_top_ips(3)}")

        # Test stats
        print("\nRedis stats:")
        stats = client.get_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")

        client.close()
    else:
        print("[!] Redis not healthy")

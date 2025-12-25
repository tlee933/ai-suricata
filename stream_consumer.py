#!/usr/bin/env python3
"""
Redis Stream Consumer for AI Suricata
Replaces SSH-based alert collection with Redis Streams

Consumes alerts from pfSense agent via Redis Streams instead of SSH tail
"""

import json
import time
from datetime import datetime
from typing import Dict, Generator, Optional, Tuple, Any


class RedisStreamConsumer:
    """
    Consumer for Redis Streams alerts.
    Replaces SSH tail -f with Redis XREAD/XREADGROUP.
    """

    def __init__(self, redis_client, stream_name='ai_suricata:alerts:stream',
                 group_name='ai-processors', consumer_name='ai-suricata-1',
                 create_group=True):
        """
        Initialize stream consumer.

        Args:
            redis_client: RedisClient instance
            stream_name: Name of the alerts stream
            group_name: Consumer group name (for load balancing)
            consumer_name: Unique name for this consumer instance
            create_group: Create consumer group if it doesn't exist
        """
        self.redis_client = redis_client
        self.stream_name = stream_name
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.enabled = redis_client and redis_client.enabled

        if not self.enabled:
            print("[!] Redis not available - stream consumer disabled")
            return

        # Statistics
        self.stats = {
            'messages_consumed': 0,
            'messages_acknowledged': 0,
            'errors': 0,
            'last_message_time': None
        }

        # Create consumer group if requested
        if create_group:
            self._create_consumer_group()

    def _create_consumer_group(self):
        """Create consumer group if it doesn't exist"""
        if not self.enabled:
            return

        try:
            # Try to create group starting from beginning of stream
            self.redis_client.redis.xgroup_create(
                self.stream_name,
                self.group_name,
                id='0',
                mkstream=True  # Create stream if doesn't exist
            )
            print(f"[+] Created consumer group: {self.group_name}")
        except Exception as e:
            # Group probably already exists
            if 'BUSYGROUP' in str(e):
                print(f"[*] Consumer group already exists: {self.group_name}")
            else:
                print(f"[!] Error creating consumer group: {e}")

    def consume_alerts(self, count=10, block_ms=1000) -> Generator[Tuple[str, Dict], None, None]:
        """
        Consume alerts from Redis stream using consumer groups.

        Args:
            count: Maximum number of messages to read
            block_ms: Block for N milliseconds waiting for messages

        Yields:
            Tuple of (message_id, alert_data)
        """
        if not self.enabled:
            return

        try:
            # Read from stream using consumer group
            messages = self.redis_client.redis.xreadgroup(
                groupname=self.group_name,
                consumername=self.consumer_name,
                streams={self.stream_name: '>'},  # '>' means only new messages
                count=count,
                block=block_ms
            )

            if not messages:
                return  # No messages available

            for stream_name, stream_messages in messages:
                for msg_id, msg_data in stream_messages:
                    self.stats['messages_consumed'] += 1
                    self.stats['last_message_time'] = time.time()

                    # Parse alert data
                    alert_data = self._parse_message(msg_data)

                    if alert_data:
                        yield msg_id, alert_data
                    else:
                        # Invalid message, acknowledge and skip
                        self.acknowledge(msg_id)

        except Exception as e:
            print(f"[!] Error consuming alerts: {e}")
            self.stats['errors'] += 1
            time.sleep(1)  # Back off on error

    def consume_alerts_simple(self, last_id='0', count=10, block_ms=1000) -> Generator[Tuple[str, Dict], None, None]:
        """
        Simple stream consumption without consumer groups.
        Useful for single-instance deployments.

        Args:
            last_id: Last message ID processed (or '0' for start, '$' for new only)
            count: Maximum messages to read
            block_ms: Block time in milliseconds

        Yields:
            Tuple of (message_id, alert_data)
        """
        if not self.enabled:
            return

        try:
            messages = self.redis_client.redis.xread(
                {self.stream_name: last_id},
                count=count,
                block=block_ms
            )

            if not messages:
                return

            for stream_name, stream_messages in messages:
                for msg_id, msg_data in stream_messages:
                    self.stats['messages_consumed'] += 1
                    self.stats['last_message_time'] = time.time()

                    alert_data = self._parse_message(msg_data)

                    if alert_data:
                        yield msg_id, alert_data

        except Exception as e:
            print(f"[!] Error consuming alerts (simple): {e}")
            self.stats['errors'] += 1

    def _parse_message(self, msg_data: Dict) -> Optional[Dict]:
        """
        Parse message data from Redis stream into alert format.

        Args:
            msg_data: Raw message data from Redis

        Returns:
            Parsed alert data or None if invalid
        """
        try:
            # Reconstruct Suricata event from stream message
            event_data_json = msg_data.get('event_data', '{}')
            event = json.loads(event_data_json)

            # Add stream metadata
            event['_stream_metadata'] = {
                'hostname': msg_data.get('hostname', 'unknown'),
                'timestamp': msg_data.get('timestamp', ''),
                'stream_received': datetime.now().isoformat()
            }

            return event

        except json.JSONDecodeError as e:
            print(f"[!] Invalid JSON in message: {e}")
            self.stats['errors'] += 1
            return None
        except Exception as e:
            print(f"[!] Error parsing message: {e}")
            self.stats['errors'] += 1
            return None

    def acknowledge(self, msg_id: str):
        """
        Acknowledge message as processed.

        Args:
            msg_id: Message ID to acknowledge
        """
        if not self.enabled:
            return

        try:
            self.redis_client.redis.xack(
                self.stream_name,
                self.group_name,
                msg_id
            )
            self.stats['messages_acknowledged'] += 1
        except Exception as e:
            print(f"[!] Error acknowledging message {msg_id}: {e}")

    def get_pending_messages(self) -> list:
        """
        Get pending messages that were read but not acknowledged.

        Returns:
            List of pending message IDs
        """
        if not self.enabled:
            return []

        try:
            pending = self.redis_client.redis.xpending_range(
                self.stream_name,
                self.group_name,
                min='-',
                max='+',
                count=100
            )
            return [p['message_id'] for p in pending]
        except Exception as e:
            print(f"[!] Error getting pending messages: {e}")
            return []

    def claim_pending_messages(self, min_idle_time_ms=30000) -> Generator[Tuple[str, Dict], None, None]:
        """
        Claim pending messages that have been idle too long.
        Useful for recovering from consumer failures.

        Args:
            min_idle_time_ms: Minimum idle time before claiming (default: 30s)

        Yields:
            Tuple of (message_id, alert_data)
        """
        if not self.enabled:
            return

        try:
            # Get pending messages
            pending = self.redis_client.redis.xpending_range(
                self.stream_name,
                self.group_name,
                min='-',
                max='+',
                count=100
            )

            for msg_info in pending:
                if msg_info['time_since_delivered'] >= min_idle_time_ms:
                    # Claim this message
                    claimed = self.redis_client.redis.xclaim(
                        self.stream_name,
                        self.group_name,
                        self.consumer_name,
                        min_idle_time=min_idle_time_ms,
                        message_ids=[msg_info['message_id']]
                    )

                    for msg_id, msg_data in claimed:
                        alert_data = self._parse_message(msg_data)
                        if alert_data:
                            yield msg_id, alert_data

        except Exception as e:
            print(f"[!] Error claiming pending messages: {e}")

    def get_stream_info(self) -> Dict[str, Any]:
        """
        Get information about the stream.

        Returns:
            Dictionary with stream statistics
        """
        if not self.enabled:
            return {'enabled': False}

        try:
            info = self.redis_client.redis.xinfo_stream(self.stream_name)

            return {
                'enabled': True,
                'stream_name': self.stream_name,
                'length': info.get('length', 0),
                'first_entry': info.get('first-entry', [None])[0] if info.get('first-entry') else None,
                'last_entry': info.get('last-entry', [None])[0] if info.get('last-entry') else None,
                'groups': info.get('groups', 0),
            }
        except Exception as e:
            print(f"[!] Error getting stream info: {e}")
            return {'enabled': True, 'error': str(e)}

    def get_consumer_group_info(self) -> Dict[str, Any]:
        """
        Get information about consumer group.

        Returns:
            Dictionary with consumer group statistics
        """
        if not self.enabled:
            return {'enabled': False}

        try:
            groups = self.redis_client.redis.xinfo_groups(self.stream_name)

            for group in groups:
                if group['name'] == self.group_name:
                    return {
                        'enabled': True,
                        'group_name': self.group_name,
                        'consumers': group.get('consumers', 0),
                        'pending': group.get('pending', 0),
                        'last_delivered_id': group.get('last-delivered-id', 'unknown')
                    }

            return {'enabled': True, 'error': 'Group not found'}
        except Exception as e:
            print(f"[!] Error getting group info: {e}")
            return {'enabled': True, 'error': str(e)}

    def get_stats(self) -> Dict[str, Any]:
        """
        Get consumer statistics.

        Returns:
            Dictionary with statistics
        """
        return {
            'messages_consumed': self.stats['messages_consumed'],
            'messages_acknowledged': self.stats['messages_acknowledged'],
            'errors': self.stats['errors'],
            'last_message_time': self.stats['last_message_time'],
            'consumer_name': self.consumer_name,
            'group_name': self.group_name,
            'stream_name': self.stream_name
        }

    def reset_stream_position(self, position='0'):
        """
        Reset consumer group position in stream.
        CAUTION: This will cause messages to be re-processed!

        Args:
            position: Stream position ('0' for beginning, '$' for end)
        """
        if not self.enabled:
            return False

        try:
            self.redis_client.redis.xgroup_setid(
                self.stream_name,
                self.group_name,
                position
            )
            print(f"[+] Reset stream position to: {position}")
            return True
        except Exception as e:
            print(f"[!] Error resetting stream position: {e}")
            return False


class StreamAlertGenerator:
    """
    Generator wrapper for stream consumer.
    Provides same interface as SSH-based alert collector.
    """

    def __init__(self, stream_consumer: RedisStreamConsumer, use_consumer_group=True):
        """
        Initialize alert generator.

        Args:
            stream_consumer: RedisStreamConsumer instance
            use_consumer_group: Use consumer groups for load balancing
        """
        self.consumer = stream_consumer
        self.use_consumer_group = use_consumer_group
        self.last_id = '$'  # Start from latest messages

    def __iter__(self):
        """Iterator interface"""
        return self

    def __next__(self) -> Dict:
        """
        Get next alert from stream.

        Returns:
            Parsed alert dictionary
        """
        while True:
            if self.use_consumer_group:
                # Use consumer group (recommended for production)
                for msg_id, alert_data in self.consumer.consume_alerts(count=1, block_ms=1000):
                    # Acknowledge immediately after successful processing
                    self.consumer.acknowledge(msg_id)
                    return alert_data
            else:
                # Simple mode (single consumer)
                for msg_id, alert_data in self.consumer.consume_alerts_simple(
                    last_id=self.last_id,
                    count=1,
                    block_ms=1000
                ):
                    self.last_id = msg_id
                    return alert_data

            # No messages available, continue waiting
            time.sleep(0.1)

    def follow(self):
        """
        Continuous stream following.
        Yields alerts as they arrive.
        """
        if self.use_consumer_group:
            while True:
                for msg_id, alert_data in self.consumer.consume_alerts(count=10, block_ms=1000):
                    yield alert_data
                    self.consumer.acknowledge(msg_id)
        else:
            while True:
                for msg_id, alert_data in self.consumer.consume_alerts_simple(
                    last_id=self.last_id,
                    count=10,
                    block_ms=1000
                ):
                    self.last_id = msg_id
                    yield alert_data


if __name__ == '__main__':
    # Test stream consumer
    from redis_client import RedisClient

    print("Testing Redis Stream Consumer...")

    redis_client = RedisClient(enabled=True, host='localhost', port=6379)

    if redis_client.is_healthy():
        consumer = RedisStreamConsumer(
            redis_client,
            stream_name='ai_suricata:alerts:stream',
            group_name='ai-processors',
            consumer_name='test-consumer'
        )

        print("\nStream Info:")
        info = consumer.get_stream_info()
        for key, value in info.items():
            print(f"  {key}: {value}")

        print("\nConsumer Group Info:")
        group_info = consumer.get_consumer_group_info()
        for key, value in group_info.items():
            print(f"  {key}: {value}")

        print("\nConsumer Stats:")
        stats = consumer.get_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")

        print("\nListening for alerts (Ctrl+C to stop)...")
        try:
            for msg_id, alert in consumer.consume_alerts(count=10, block_ms=5000):
                print(f"\n[ALERT] {msg_id}")
                print(f"  Source: {alert.get('src_ip', 'unknown')}")
                print(f"  Dest: {alert.get('dest_ip', 'unknown')}")
                print(f"  Type: {alert.get('event_type', 'unknown')}")
                consumer.acknowledge(msg_id)
        except KeyboardInterrupt:
            print("\n\n[*] Stopped")

    else:
        print("[!] Redis not healthy - cannot test consumer")

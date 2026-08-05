"""Read-only in-cluster replacements for command-line database, Valkey, and Kafka probes."""

from __future__ import annotations

import asyncio
import os
from typing import LiteralString, cast

import psycopg
import redis
from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient
from aiokafka.errors import KafkaError


def psql(query: str, field_separator: str = "") -> tuple[int, str, str]:
    """Execute a read-only SQL query over Service DNS."""
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
            connection.execute("SET default_transaction_read_only = on")
            cursor = connection.execute(cast("LiteralString", query))
            rows = cursor.fetchall() if cursor.description is not None else []
    except (KeyError, psycopg.Error) as exc:
        return 1, "", str(exc)
    separator = field_separator or ""
    output = "\n".join(separator.join("" if value is None else str(value) for value in row) for row in rows)
    return 0, output + ("\n" if output else ""), ""


def valkey_info(service_url: str) -> tuple[int, str, str]:
    """Return Valkey INFO through the selected cluster Service."""
    try:
        client = redis.Redis.from_url(
            service_url,
            socket_timeout=5,
            decode_responses=True,
        )
        info = client.info()
    except redis.RedisError as exc:
        return 1, "", str(exc)
    return 0, "\n".join(f"{key}:{value}" for key, value in sorted(info.items())), ""


async def _kafka(args: list[str], bootstrap_server: str) -> tuple[int, str, str]:
    command = args[0].removesuffix(".sh") if args else ""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_server)
    try:
        await admin.start()
        if command == "kafka-topics" and "--list" in args:
            topics = await admin.list_topics()
            return 0, "\n".join(sorted(topics)) + "\n", ""
        if command == "kafka-consumer-groups" and "--describe" in args and "--group" in args:
            group = args[args.index("--group") + 1]
            descriptions = await admin.describe_consumer_groups([group])
            response_groups = cast(
                "list[tuple[object, ...]]",
                getattr(descriptions[0], "groups", ()),
            )
            if not response_groups or len(response_groups[0]) < 6:
                return 1, "", f"Consumer group '{group}' returned no description"
            members = cast("list[tuple[object, ...]]", response_groups[0][5])
            if not members:
                return 0, f"Consumer group '{group}' has no active members.\n", ""
            offsets = await admin.list_consumer_group_offsets(group)
            consumer = AIOKafkaConsumer(bootstrap_servers=bootstrap_server)
            try:
                await consumer.start()
                end_offsets = await consumer.end_offsets(list(offsets))
            finally:
                await consumer.stop()
            lines = ["GROUP TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG CONSUMER-ID HOST CLIENT-ID"]
            member = members[0]
            for topic_partition, committed in sorted(
                offsets.items(), key=lambda item: (item[0].topic, item[0].partition)
            ):
                end = end_offsets[topic_partition]
                current = committed.offset
                lag = max(0, end - current)
                lines.append(
                    f"{group} {topic_partition.topic} {topic_partition.partition} "
                    f"{current} {end} {lag} {member[0]} - {member[1]}"
                )
            return 0, "\n".join(lines) + "\n", ""
        return (
            2,
            "",
            f"unsupported read-only Kafka command: {args[0] if args else '<empty>'}",
        )
    except (KafkaError, OSError, RuntimeError, ValueError) as exc:
        return 1, "", str(exc)
    finally:
        await admin.close()


def kafka_command(args: list[str], bootstrap_server: str) -> tuple[int, str, str]:
    """Execute the supported read-only Kafka metadata commands."""
    return asyncio.run(_kafka(args, bootstrap_server))

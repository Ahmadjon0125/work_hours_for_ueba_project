"""RabbitMQ ulanishi: connection, durable queue, publish.

DIQQAT: bu paket "queue" deb nomlanmaydi — Python stdlib'dagi `queue` moduli
bilan to'qnashib, yashirin xatolarga olib keladi.
"""
import json

import pika

import config


def connect():
    """Yangi BlockingConnection (har thread o'ziniki bilan ishlaydi)."""
    credentials = pika.PlainCredentials(config.RABBITMQ_USER, config.RABBITMQ_PASSWORD)
    params = pika.ConnectionParameters(
        host=config.RABBITMQ_HOST, port=config.RABBITMQ_PORT,
        credentials=credentials, heartbeat=600, blocked_connection_timeout=300,
    )
    return pika.BlockingConnection(params)


def declare_queue(channel):
    channel.queue_declare(queue=config.QUEUE_NAME, durable=True)


def publish(channel, job, retries=0):
    """Job'ni navbatga yuboradi. Xato bo'lsa exception ko'tariladi (chaqiruvchi ushlaydi)."""
    channel.basic_publish(
        exchange="",
        routing_key=config.QUEUE_NAME,
        body=json.dumps(job, ensure_ascii=False).encode("utf-8"),
        properties=pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,  # durable message
            headers={"x-retries": retries},
        ),
    )


def queue_depth():
    """Navbatdagi message'lar soni (/api/health uchun). Xato bo'lsa None."""
    conn = None
    try:
        conn = connect()
        channel = conn.channel()
        result = channel.queue_declare(queue=config.QUEUE_NAME, durable=True, passive=True)
        return result.method.message_count
    except Exception:
        return None
    finally:
        if conn is not None and conn.is_open:
            conn.close()

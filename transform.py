import boto3
import json
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
ENDPOINT   = "http://localhost:4566"
REGION     = "ap-south-1"
QUEUE_URL  = "http://sqs.ap-south-1.localhost.localstack.cloud:4566/000000000000/test-queue"
TABLE_NAME = "trips"

AWS_KWARGS = dict(
    endpoint_url=ENDPOINT,
    region_name=REGION,
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

# ── AWS clients ───────────────────────────────────────────────────────────────
sqs    = boto3.client("sqs",         **AWS_KWARGS)
dynamo = boto3.resource("dynamodb",  **AWS_KWARGS)


# ── DynamoDB setup ────────────────────────────────────────────────────────────
def get_or_create_table():
    client   = boto3.client("dynamodb", **AWS_KWARGS)
    existing = client.list_tables()["TableNames"]
    if TABLE_NAME in existing:
        log.info("Table '%s' already exists", TABLE_NAME)
        return dynamo.Table(TABLE_NAME)

    log.info("Creating table '%s'...", TABLE_NAME)
    table = dynamo.create_table(
        TableName=TABLE_NAME,
        KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "N"}],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    log.info("Table created.")
    return table


# ── Transformation helpers ────────────────────────────────────────────────────
def parse_date(raw: str) -> str:
    """Normalise date strings to 'YYYY-MM-DD HH:MM:SS'."""
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    return raw


def unix_to_date(ts: int) -> str:
    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def transform(data: dict):
    """
    Convert any recognised message format to the unified structure.
    Returns None if the message cannot be transformed.
    """
    try:
        mail = data["mail"]
        name = f"{data['name']} {data['surname']}"

        # ── Format A: 'route' array ──────────────────────────────────────────
        if "route" in data:
            legs       = data["route"]
            departure  = legs[0]["from"]
            dest       = legs[-1]["to"]
            start      = parse_date(legs[0]["started_at"])
            total_mins = sum(leg["duration"] for leg in legs)
            start_dt   = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
            end        = (start_dt + timedelta(minutes=total_mins)).strftime("%Y-%m-%d %H:%M:%S")

        # ── Format B: 'locations' array with unix timestamps ─────────────────
        elif "locations" in data:
            locs      = data["locations"]
            departure = locs[0]["location"]
            dest      = locs[-1]["location"]
            start     = unix_to_date(locs[0]["timestamp"])
            end       = unix_to_date(locs[-1]["timestamp"])

        else:
            log.warning("Unrecognised message format (id=%s), skipping.", data.get("id"))
            return None

        return {
            "id":   data["id"],
            "mail": mail,
            "name": name,
            "trip": {
                "departure":     departure,
                "destination": dest,
                "start_date":  start,
                "end_date":    end,
            },
        }

    except (KeyError, IndexError, ValueError) as exc:
        log.warning("Failed to transform message: %s — %s", data, exc)
        return None


# ── ETL loop ──────────────────────────────────────────────────────────────────
def run(table):
    log.info("Starting ETL — consuming from queue...")
    processed = skipped = errors = 0

    while True:
        response = sqs.receive_message(
            QueueUrl=QUEUE_URL,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=2,
        )

        messages = response.get("Messages", [])
        if not messages:
            log.info("Queue is empty. Done.")
            break

        for msg in messages:
            body = msg["Body"]

            # ── Parse ────────────────────────────────────────────────────────
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                log.warning("Malformed message (not JSON): %r — skipping.", body[:80])
                skipped += 1
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                continue

            # ── Transform ────────────────────────────────────────────────────
            record = transform(data)
            if record is None:
                skipped += 1
                sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
                continue

            # ── Load ─────────────────────────────────────────────────────────
            try:
                table.put_item(Item=record)
                log.info("Saved id=%s | %s (%s -> %s)",
                         record["id"], record["name"],
                         record["trip"]["departure"], record["trip"]["destination"])
                processed += 1
            except Exception as exc:
                log.error("DynamoDB write failed for id=%s: %s", record.get("id"), exc)
                errors += 1
                continue  # don't delete — leave in queue to retry

            # ── Delete from queue (only after successful save) ────────────────
            sqs.delete_message(QueueUrl=QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])

    log.info("ETL complete — processed: %d | skipped: %d | errors: %d", processed, skipped, errors)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    table = get_or_create_table()
    run(table)
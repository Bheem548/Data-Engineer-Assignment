# SQS Data Pipeline — Documentation

## Overview

This tool is a simple ETL (Extract, Transform, Load) pipeline that:
1. **Extracts** messages from an AWS SQS queue (via LocalStack)
2. **Transforms** them into a unified structure
3. **Loads** them into a DynamoDB table (via LocalStack)

---

## Language Choice

**Python 3** was chosen for the following reasons:
- `boto3` (AWS SDK for Python) is mature, well-documented, and makes SQS/DynamoDB integration straightforward
- Python is concise and readable, making the transformation logic easy to follow and maintain
- Rapid development — no compilation step needed
- Widely used in data engineering pipelines

---

## Project Structure

```
data-engineer-assignment/
├── Makefile               # Build and run automation
├── prepare.sh             # Builds Go binaries and sets up dist/
├── message_generator.go   # Generates messages and pushes to SQS
├── docker-compose.yml     # LocalStack setup (SQS, S3, DynamoDB)
├── DOC.md                 # Original assignment document
├── Dockerfile         # Docker image for the ETL tool
├── transform.py       # ETL pipeline script
└── dist/
    ├── docker-compose.yml # LocalStack config (copied from root)
    ├── README.md          # Assignment doc + build date
    └── message-generators/
        ├── darwin         # macOS binary
        ├── linux          # Linux binary
        └── windows.exe    # Windows binary
```

---

## Build Requirements

- [Docker](https://www.docker.com/get-started)
- [Docker Compose](https://docs.docker.com/compose/install/)
- [Go](https://go.dev/dl/) (to compile message generator binaries)
- [GNU Make](https://www.gnu.org/software/make/)
- Python 3.9+ with `boto3` installed (`pip install boto3`)

---

## Environment Configuration

The following AWS credentials are required for LocalStack. Since LocalStack does not validate credentials, any non-empty values will work:

```bash
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=ap-south-1
```

These are already set in the `Makefile` via `export` so no manual setup is needed.

LocalStack runs on:
- **Endpoint:** `http://localhost:4566`
- **Region:** `ap-south-1`
- **Services:** SQS, S3, DynamoDB

---

## How to Build

### Option 1 — Using Make (recommended)

```bash
make install
```

This runs `prepare.sh` which:
- Compiles `message_generator.go` into binaries for Linux, macOS, and Windows
- Copies `docker-compose.yml` and `DOC.md` into `dist/`

### Option 2 — Build Docker image manually

```bash
docker build -t etl-pipeline .
```

---

## How to Run

### Full pipeline with one command

```bash
make all
```

This runs the following steps in order:

| Step | Command | Description |
|------|---------|-------------|
| 1 | `make install` | Compiles Go binaries, sets up `dist/` |
| 2 | `make up` | Starts LocalStack via docker-compose |
| 3 | `make generate` | Runs message generator to push messages to SQS |
| 4 | `make build` | Builds the ETL Docker image |
| 5 | `make run` | Runs the ETL pipeline container |

### Run individual steps

```bash
make install    # Build Go binaries
make up         # Start LocalStack
make generate   # Push messages to SQS queue
make build      # Build ETL Docker image
make run        # Run ETL pipeline
```

---

## How to Use

### Running the ETL tool directly (without Docker)

```bash
pip install boto3
python transform.py
```

### Running via Docker

```bash
docker run --network host etl-pipeline
```

### Verifying data in DynamoDB

```bash
aws --endpoint-url=http://localhost:4566 \
    --region ap-south-1 \
    dynamodb scan \
    --table-name trips
```

Or using Python:

```python
import boto3, json

dynamo = boto3.resource("dynamodb",
    endpoint_url="http://localhost:4566",
    region_name="ap-south-1",
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

items = dynamo.Table("trips").scan()["Items"]
print(f"Total records: {len(items)}")
for item in items:
    print(json.dumps(item, indent=2, default=str))
```

---

## Input Message Formats

The message generator produces messages in two formats (plus malformed messages):

### Format A — Route array
```json
{
  "id": 3,
  "mail": "aaa@gmail.com",
  "name": "Mahmoud",
  "surname": "Mahmoudi",
  "route": [
    {"from": "B", "to": "C", "duration": 15, "started_at": "10/10/2022 11:10:00"},
    {"from": "C", "to": "E", "duration": 10, "started_at": "10/10/2022 11:17:15"}
  ]
}
```

### Format B — Locations array with Unix timestamps
```json
{
  "id": 5,
  "mail": "mmm@nocompany.com",
  "name": "Kacper",
  "surname": "Kacperian",
  "locations": [
    {"location": "F", "timestamp": 1667999699},
    {"location": "G", "timestamp": 1668975653}
  ]
}
```

### Malformed messages
Messages with body `"malformed"` or invalid JSON are skipped and deleted from the queue.

---

## Output Structure

All messages are transformed into the following unified structure and saved to DynamoDB:

```json
{
  "message_id": "e43ec425-ffc9-4f1a-ae2f-de006eecc577",
  "id": 3,
  "mail": "aaa@gmail.com",
  "name": "Mahmoud Mahmoudi",
  "trip": {
    "depature": "B",
    "destination": "E",
    "start_date": "2022-10-10 11:10:00",
    "end_date": "2022-10-10 11:35:00"
  }
}
```

**Note:** `message_id` (SQS MessageId) is used as the DynamoDB partition key to ensure uniqueness. The business `id` field is stored as a regular attribute. This handles cases where multiple messages share the same `id`.

---

## Transformation Logic

| Input field | Output field | Notes |
|-------------|-------------|-------|
| `name + surname` | `name` | Joined with a space |
| `route[0].from` or `locations[0].location` | `trip.depature` | First leg departure |
| `route[-1].to` or `locations[-1].location` | `trip.destination` | Last leg destination |
| `route[0].started_at` or `locations[0].timestamp` | `trip.start_date` | Normalised to `YYYY-MM-DD HH:MM:SS` |
| `route[0].started_at + sum(durations)` or `locations[-1].timestamp` | `trip.end_date` | Calculated from leg durations or last timestamp |

---

## Challenges

1. **Multiple message formats** — The queue contains messages in different structures. The transformer handles each format explicitly and skips unrecognised ones gracefully.

2. **Duplicate messages** — Messages can share the same business `id` (e.g., same person with different workplaces). Using the SQS `MessageId` as the DynamoDB partition key ensures every message is stored uniquely.

3. **Windows compatibility** — Running shell scripts and Make on Windows required using Git Bash. Path handling differences between Windows and Unix required careful attention in the Makefile.

4. **Docker networking** — Connecting a Docker container to LocalStack running on the host required using `--network host` and `host.docker.internal` as the endpoint instead of `localhost`.

5. **Date format normalisation** — The `route` format uses `DD/MM/YYYY HH:MM:SS` while the output requires `YYYY-MM-DD HH:MM:SS`. A parser handles both formats automatically.

---

## Bonus Points Completed

- [x] **#1** — Database (DynamoDB) is included in the LocalStack `docker-compose.yml` setup
- [x] **#2** — ETL tool is Dockerized with a `Dockerfile` and runs via `docker run`
- [x] **#3** — `Makefile` builds and runs the full pipeline with `make all`
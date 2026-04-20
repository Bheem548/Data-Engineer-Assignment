
import boto3, json

dynamo = boto3.resource("dynamodb",
    endpoint_url="http://localhost:4566",
    region_name="ap-south-1",
    aws_access_key_id="test",
    aws_secret_access_key="test",
)

table = dynamo.Table("trips")
items = table.scan()["Items"]

print(f"Total records: {len(items)}\n")
for item in items:
    print(json.dumps(item, indent=2, default=str))
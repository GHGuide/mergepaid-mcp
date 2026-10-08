"""Test-only JSON pipe bridge to the backend's installed Python (no TCP socket)."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["MERGEPAID_DB"] = ":memory:"
from backend import db, local_seed

conn = db.connect(":memory:")
try:
    world = local_seed.seed(conn)
    with local_seed.local_api(conn) as client:
        client.cookies.clear()
        print(json.dumps(world), flush=True)
        for line in sys.stdin:
            command = json.loads(line)
            response = client.request(command["method"], command["path"], content=command["body"].encode(),
                                      headers=command["headers"])
            print(json.dumps({"status": response.status_code, "body": response.text,
                              "headers": dict(response.headers)}), flush=True)
finally:
    conn.close()

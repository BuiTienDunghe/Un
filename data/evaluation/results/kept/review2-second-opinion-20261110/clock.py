import os, time
from datetime import datetime, UTC
from sqlalchemy import create_engine, text
engine = create_engine(os.environ["POSTGRES_TEST_URL"])
with engine.connect() as c:
    rows = []
    for _ in range(5):
        before = datetime.now(UTC)
        db = c.execute(text("SELECT clock_timestamp()")).scalar()
        after = datetime.now(UTC)
        mid = before + (after - before) / 2
        rows.append(((db - mid).total_seconds() * 1000, (after - before).total_seconds() * 1000))
        time.sleep(0.2)
for skew, rtt in rows:
    print(f"db_minus_app_ms={skew:+.1f} roundtrip_ms={rtt:.1f}")

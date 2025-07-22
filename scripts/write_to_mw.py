from seedcore.telemetry.server import app
import time, uuid

mw = app.state.stats.mw
mw[str(uuid.uuid4())] = {"blob": b"hello world", "ts": time.time()}
print("Wrote one item to Mw.") 
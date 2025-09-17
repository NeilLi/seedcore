# tests/test_runtime_registry.py
import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass, field
import pytest

# ----------------------------
# Fake in-memory "DB" repo
# ----------------------------
@dataclass
class InstanceRow:
    instance_id: str
    logical_id: str
    cluster_epoch: str
    status: str = "starting"   # starting|alive|draining|dead
    actor_name: str | None = None
    serve_route: str | None = None
    node_id: str | None = None
    ip_address: str | None = None
    pid: int | None = None
    started_at: float = field(default_factory=lambda: time.time())
    stopped_at: float | None = None
    last_heartbeat: float = field(default_factory=lambda: time.time())

class FakeRepo:
    def __init__(self):
        self.current_epoch = str(uuid.uuid4())
        self.instances: dict[str, InstanceRow] = {}
        self.register_calls: int = 0
        self.set_status_calls: list[tuple[str, str]] = []
        self.beat_timestamps: dict[str, list[float]] = {}

    # --- helpers to mimic SQL funcs in your repo ---
    async def get_current_cluster_epoch(self) -> str:
        return self.current_epoch

    async def set_current_cluster_epoch(self, epoch):
        self.current_epoch = str(epoch)

    async def register_instance(self, *, instance_id, logical_id, cluster_epoch,
                                actor_name=None, serve_route=None, node_id=None,
                                ip_address=None, pid=None):
        self.register_calls += 1
        row = self.instances.get(instance_id)
        if row is None:
            row = InstanceRow(
                instance_id=instance_id,
                logical_id=logical_id,
                cluster_epoch=str(cluster_epoch),
                actor_name=actor_name,
                serve_route=serve_route,
                node_id=node_id,
                ip_address=ip_address,
                pid=pid,
            )
            self.instances[instance_id] = row
        # upsert semantics: touch heartbeat
        row.last_heartbeat = time.time()

    async def set_instance_status(self, instance_id, status: str):
        self.set_status_calls.append((instance_id, status))
        row = self.instances[instance_id]
        row.status = status
        if status in ("dead", "draining"):
            row.stopped_at = row.stopped_at or time.time()

    async def beat(self, instance_id):
        now = time.time()
        row = self.instances[instance_id]
        row.last_heartbeat = now
        self.beat_timestamps.setdefault(instance_id, []).append(now)

    async def expire_stale_instances(self, timeout_seconds: int = 15) -> int:
        now = time.time()
        cnt = 0
        for row in self.instances.values():
            if row.status in ("starting", "alive", "draining"):
                if row.last_heartbeat < (now - timeout_seconds):
                    row.status = "dead"
                    row.stopped_at = row.stopped_at or now
                    cnt += 1
        return cnt

    async def expire_old_epoch_instances(self) -> int:
        cnt = 0
        for row in self.instances.values():
            if row.cluster_epoch != self.current_epoch and row.status in ("starting", "alive", "draining"):
                row.status = "dead"
                row.stopped_at = row.stopped_at or time.time()
                cnt += 1
        return cnt


# ---------------------------------
# Minimal Organ core (no Ray)
# ---------------------------------
class OrganCore:
    def __init__(self, organ_id: str, repo: FakeRepo,
                 hb_base: float = 0.12, hb_jitter: float = 0.06, hb_backoff_max: float = 0.5):
        self.organ_id = organ_id
        self.instance_id = uuid.uuid4().hex
        self._repo = repo
        self._hb_base = hb_base
        self._hb_jitter = hb_jitter
        self._hb_backoff_max = hb_backoff_max
        self._hb_task: asyncio.Task | None = None
        self._closing = asyncio.Event()
        self._started = False

    async def start(self):
        if self._started:
            return {"status": "alive", "instance_id": self.instance_id, "logical_id": self.organ_id}
        await self._repo.register_instance(
            instance_id=self.instance_id,
            logical_id=self.organ_id,
            cluster_epoch=await self._repo.get_current_cluster_epoch(),
            actor_name=self.organ_id,
            serve_route=None,
            node_id="node-1",
            ip_address="127.0.0.1",
            pid=1234,
        )
        # (Readiness probes could live here)
        await self._repo.set_instance_status(self.instance_id, "alive")
        self._hb_task = asyncio.create_task(self._heartbeat_loop())
        self._started = True
        return {"status": "alive", "instance_id": self.instance_id, "logical_id": self.organ_id}

    async def _heartbeat_loop(self):
        backoff = 0.05
        while not self._closing.is_set():
            try:
                await self._repo.beat(self.instance_id)
                backoff = 0.05
            except Exception:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._hb_backoff_max)
            # jittered wait
            timeout = self._hb_base + self._hb_jitter * (0.2 + 0.8 * (time.time() % 1))  # deterministic-ish jitter for test
            try:
                await asyncio.wait_for(self._closing.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass

    async def close(self):
        if self._closing.is_set():
            return {"status": "dead", "instance_id": self.instance_id}
        self._closing.set()
        if self._hb_task:
            self._hb_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._hb_task
        await self._repo.set_instance_status(self.instance_id, "dead")
        return {"status": "dead", "instance_id": self.instance_id}


# ==========================
#         TESTS
# ==========================

@pytest.mark.asyncio
async def test_start_sets_alive_and_registers_once():
    repo = FakeRepo()
    organ = OrganCore("cognitive_organ_1", repo)

    # 1st start
    res1 = await organ.start()
    assert res1["status"] == "alive"
    assert repo.register_calls == 1
    assert repo.instances[organ.instance_id].status == "alive"

    # 2nd start is idempotent
    res2 = await organ.start()
    assert res2["status"] == "alive"
    assert repo.register_calls == 1, "start() should not re-register if already started"
    assert repo.set_status_calls[-1][1] == "alive"

    await organ.close()


@pytest.mark.asyncio
async def test_heartbeat_cadence_with_jitter_bounds():
    repo = FakeRepo()
    # faster cadence for test; small jitter
    organ = OrganCore("actuator_organ_1", repo, hb_base=0.06, hb_jitter=0.04)

    await organ.start()
    await asyncio.sleep(0.26)  # allow several beats
    beats = repo.beat_timestamps.get(organ.instance_id, [])
    # at least 3 beats expected within ~260ms
    assert len(beats) >= 3

    # compute intervals
    intervals = [b - a for a, b in zip(beats, beats[1:])]
    if intervals:
        avg = sum(intervals) / len(intervals)
        # average should be within [base, base+jitter] with a small scheduling slack
        assert avg >= 0.04
        assert avg <= 0.12

        # and no interval should exceed base+jitter too much (allow slack)
        assert max(intervals) <= 0.14

    await organ.close()
    # ensure no more beats after close
    last_count = len(repo.beat_timestamps.get(organ.instance_id, []))
    await asyncio.sleep(0.12)
    assert len(repo.beat_timestamps.get(organ.instance_id, [])) == last_count


@pytest.mark.asyncio
async def test_reconcile_marks_stale_and_old_epoch():
    repo = FakeRepo()
    epoch_a = await repo.get_current_cluster_epoch()
    epoch_b = str(uuid.uuid4())
    await repo.set_current_cluster_epoch(epoch_a)  # ensure

    # Create two instances
    stale = InstanceRow(instance_id=uuid.uuid4().hex, logical_id="o1", cluster_epoch=epoch_a, status="alive")
    old   = InstanceRow(instance_id=uuid.uuid4().hex, logical_id="o2", cluster_epoch=epoch_b, status="alive")
    repo.instances[stale.instance_id] = stale
    repo.instances[old.instance_id] = old

    # Make 'stale' appear stale
    stale.last_heartbeat = time.time() - 999

    # First, expire stale by timeout
    n1 = await repo.expire_stale_instances(timeout_seconds=1)
    assert n1 >= 1
    assert repo.instances[stale.instance_id].status == "dead"

    # Then, expire old-epoch instances
    # Make sure current epoch is A; 'old' is in B
    n2 = await repo.expire_old_epoch_instances()
    assert n2 >= 1
    assert repo.instances[old.instance_id].status == "dead"


@pytest.mark.asyncio
async def test_idempotent_start_and_close_and_heartbeat_stop():
    repo = FakeRepo()
    organ = OrganCore("utility_organ_1", repo, hb_base=0.05, hb_jitter=0.02)

    # start twice
    await organ.start()
    await organ.start()
    assert repo.register_calls == 1
    assert repo.instances[organ.instance_id].status == "alive"

    # let it beat a bit
    await asyncio.sleep(0.18)
    beats_before_close = len(repo.beat_timestamps.get(organ.instance_id, []))
    assert beats_before_close >= 2

    # close twice
    await organ.close()
    status_after_close = repo.instances[organ.instance_id].status
    assert status_after_close == "dead"

    await organ.close()  # idempotent
    assert repo.instances[organ.instance_id].status == "dead"

    # confirm heartbeat loop stopped
    await asyncio.sleep(0.12)
    beats_after_close = len(repo.beat_timestamps.get(organ.instance_id, []))
    assert beats_after_close == beats_before_close


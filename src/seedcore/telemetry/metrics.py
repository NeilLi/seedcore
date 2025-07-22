from prometheus_client import Gauge, Counter

COSTVQ      = Gauge("costvq_current", "Current CostVQ memory cost")
ENERGY_SLOPE= Gauge("energy_delta_last", "Latest dE/dk slope")
MEM_WRITES  = Counter("memory_write_total", "Holons written", ["tier"]) 
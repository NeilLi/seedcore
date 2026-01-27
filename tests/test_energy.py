# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from seedcore.ops.energy.ledger import EnergyLedger

def test_ledger_total():
    e = EnergyLedger(pair=1, hyper=2, entropy=-1, reg=0, mem=0.5)
    assert e.total == 2.5

def test_ledger_reset():
    e = EnergyLedger(pair=1, hyper=2, entropy=-1, reg=0, mem=0.5)
    e.reset()
    assert e.pair == 0.0
    assert e.hyper == 0.0
    assert e.entropy == 0.0
    assert e.reg == 0.0
    assert e.mem == 0.0
    assert e.total == 0.0

def test_add_pair_delta():
    e = EnergyLedger()
    initial_pair = e.pair
    # EnergyLedger doesn't have add_pair_delta, so we update via log_step
    # For testing incremental updates, we'll use log_step with calculated breakdown
    new_pair = initial_pair + 3.0
    e.log_step(
        breakdown={
            "pair": new_pair,
            "hyper": e.hyper,
            "entropy": e.entropy,
            "reg": e.reg,
            "mem": e.mem,
            "drift_term": e.drift_term,
            "anomaly_term": e.anomaly_term,
            "total": new_pair + e.hyper + e.entropy + e.reg + e.mem + e.drift_term + e.anomaly_term
        },
        extra={"ts": 0.0}
    )
    assert abs(e.pair - (initial_pair + 3.0)) < 0.001

def test_add_hyper_delta():
    e = EnergyLedger()
    initial_hyper = e.hyper
    # Calculate delta: complexity - precision = 0.8 - 0.3 = 0.5
    new_hyper = initial_hyper + 0.5
    e.log_step(
        breakdown={
            "pair": e.pair,
            "hyper": new_hyper,
            "entropy": e.entropy,
            "reg": e.reg,
            "mem": e.mem,
            "drift_term": e.drift_term,
            "anomaly_term": e.anomaly_term,
            "total": e.pair + new_hyper + e.entropy + e.reg + e.mem + e.drift_term + e.anomaly_term
        },
        extra={"ts": 0.0}
    )
    assert abs(e.hyper - (initial_hyper + 0.5)) < 0.001  # 0.8 - 0.3 = 0.5

def test_add_entropy_delta():
    e = EnergyLedger()
    initial_entropy = e.entropy
    # Calculate delta: choice_count * uncertainty * alpha = 5 * 0.6 * 0.1 = 0.3
    new_entropy = initial_entropy + 0.3
    e.log_step(
        breakdown={
            "pair": e.pair,
            "hyper": e.hyper,
            "entropy": new_entropy,
            "reg": e.reg,
            "mem": e.mem,
            "drift_term": e.drift_term,
            "anomaly_term": e.anomaly_term,
            "total": e.pair + e.hyper + new_entropy + e.reg + e.mem + e.drift_term + e.anomaly_term
        },
        extra={"ts": 0.0}
    )
    assert abs(e.entropy - (initial_entropy + 0.3)) < 0.001  # 5 * 0.6 * 0.1 = 0.3

def test_add_reg_delta():
    e = EnergyLedger()
    initial_reg = e.reg
    # Calculate delta: regularization_strength * model_complexity = 0.5 * 2.0 = 1.0
    new_reg = initial_reg + 1.0
    e.log_step(
        breakdown={
            "pair": e.pair,
            "hyper": e.hyper,
            "entropy": e.entropy,
            "reg": new_reg,
            "mem": e.mem,
            "drift_term": e.drift_term,
            "anomaly_term": e.anomaly_term,
            "total": e.pair + e.hyper + e.entropy + new_reg + e.mem + e.drift_term + e.anomaly_term
        },
        extra={"ts": 0.0}
    )
    assert abs(e.reg - (initial_reg + 1.0)) < 0.001  # 0.5 * 2.0 = 1.0

def test_add_mem_delta():
    e = EnergyLedger()
    initial_mem = e.mem
    # Calculate delta: memory_usage - compression_ratio = 0.7 - 0.4 = 0.3
    new_mem = initial_mem + 0.3
    e.log_step(
        breakdown={
            "pair": e.pair,
            "hyper": e.hyper,
            "entropy": e.entropy,
            "reg": e.reg,
            "mem": new_mem,
            "drift_term": e.drift_term,
            "anomaly_term": e.anomaly_term,
            "total": e.pair + e.hyper + e.entropy + e.reg + new_mem + e.drift_term + e.anomaly_term
        },
        extra={"ts": 0.0}
    )
    assert abs(e.mem - (initial_mem + 0.3)) < 0.001  # 0.7 - 0.4 = 0.3

def test_multiple_energy_terms():
    e = EnergyLedger()
    # Calculate all deltas and update via log_step
    pair_value = 1.0
    hyper_value = 0.5 - 0.2  # 0.3
    entropy_value = 3 * 0.4 * 0.1  # 0.12
    reg_value = 0.3 * 1.5  # 0.45
    mem_value = 0.6 - 0.3  # 0.3
    
    e.log_step(
        breakdown={
            "pair": pair_value,
            "hyper": hyper_value,
            "entropy": entropy_value,
            "reg": reg_value,
            "mem": mem_value,
            "drift_term": 0.0,
            "anomaly_term": 0.0,
            "total": pair_value + hyper_value + entropy_value + reg_value + mem_value
        },
        extra={"ts": 0.0}
    )
    
    # Verify individual terms with tolerance for floating-point precision
    assert abs(e.pair - 1.0) < 0.001  # 1.0 * 1.0
    assert abs(e.hyper - 0.3) < 0.001  # 0.5 - 0.2
    assert abs(e.entropy - 0.12) < 0.001  # 3 * 0.4 * 0.1
    assert abs(e.reg - 0.45) < 0.001  # 0.3 * 1.5
    assert abs(e.mem - 0.3) < 0.001  # 0.6 - 0.3
    
    # Verify total
    expected_total = 1.0 + 0.3 + 0.12 + 0.45 + 0.3
    assert abs(e.total - expected_total) < 0.001

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

from seedcore.energy.ledger import EnergyLedger

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
    e.add_pair_delta(2.0, 1.5)
    assert abs(e.pair - (initial_pair + 3.0)) < 0.001  # 2.0 * 1.5 = 3.0

def test_add_hyper_delta():
    e = EnergyLedger()
    initial_hyper = e.hyper
    e.add_hyper_delta(0.8, 0.3)  # complexity=0.8, precision=0.3
    assert abs(e.hyper - (initial_hyper + 0.5)) < 0.001  # 0.8 - 0.3 = 0.5

def test_add_entropy_delta():
    e = EnergyLedger()
    initial_entropy = e.entropy
    e.add_entropy_delta(5, 0.6)  # choice_count=5, uncertainty=0.6
    assert abs(e.entropy - (initial_entropy + 0.3)) < 0.001  # 5 * 0.6 * 0.1 = 0.3

def test_add_reg_delta():
    e = EnergyLedger()
    initial_reg = e.reg
    e.add_reg_delta(0.5, 2.0)  # regularization_strength=0.5, model_complexity=2.0
    assert abs(e.reg - (initial_reg + 1.0)) < 0.001  # 0.5 * 2.0 = 1.0

def test_add_mem_delta():
    e = EnergyLedger()
    initial_mem = e.mem
    e.add_mem_delta(0.7, 0.4)  # memory_usage=0.7, compression_ratio=0.4
    assert abs(e.mem - (initial_mem + 0.3)) < 0.001  # 0.7 - 0.4 = 0.3

def test_multiple_energy_terms():
    e = EnergyLedger()
    e.add_pair_delta(1.0, 1.0)
    e.add_hyper_delta(0.5, 0.2)
    e.add_entropy_delta(3, 0.4)
    e.add_reg_delta(0.3, 1.5)
    e.add_mem_delta(0.6, 0.3)
    
    # Verify individual terms with tolerance for floating-point precision
    assert abs(e.pair - 1.0) < 0.001  # 1.0 * 1.0
    assert abs(e.hyper - 0.3) < 0.001  # 0.5 - 0.2
    assert abs(e.entropy - 0.12) < 0.001  # 3 * 0.4 * 0.1
    assert abs(e.reg - 0.45) < 0.001  # 0.3 * 1.5
    assert abs(e.mem - 0.3) < 0.001  # 0.6 - 0.3
    
    # Verify total
    expected_total = 1.0 + 0.3 + 0.12 + 0.45 + 0.3
    assert abs(e.total - expected_total) < 0.001

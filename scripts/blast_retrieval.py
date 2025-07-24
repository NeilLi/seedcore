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

import os
import asyncio
import aiohttp
import numpy as np

# Get API endpoint from environment variable
API_BASE_URL = os.getenv('SEEDCORE_API_URL', 'http://localhost:8000')

async def blast_retrieval():
    """Send 50,000 random queries to test the system."""
    print(f"Starting retrieval blast test against {API_BASE_URL}")
    
    async with aiohttp.ClientSession() as s:
        for i in range(50_000):
            q = np.random.randn(768).tolist()
            try:
                async with s.post(f"{API_BASE_URL}/rag", json={"embedding": q, "k": 8}) as resp:
                    if resp.status == 200:
                        if i % 1000 == 0:
                            print(f"Query {i}: OK")
                    else:
                        print(f"Query {i}: HTTP {resp.status}")
            except Exception as e:
                print(f"Query {i}: Error - {e}")
            
            if i % 1000 == 0:
                await asyncio.sleep(0.1)  # Small delay every 1000 queries

if __name__ == "__main__":
    asyncio.run(blast_retrieval()) 
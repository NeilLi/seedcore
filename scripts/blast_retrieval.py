import asyncio
import numpy as np
import aiohttp
import tqdm
import random

async def main():
    async with aiohttp.ClientSession() as s:
        for _ in tqdm.trange(20):  # Reduced for testing
            q = np.random.randn(768).astype("float32").tolist()
            async with s.post("http://localhost:8000/rag", json={"embedding": q, "k": 8}) as resp:
                print(f"Status: {resp.status}")
                # Optionally print response body:
                # print(await resp.text())

if __name__ == "__main__":
    asyncio.run(main()) 
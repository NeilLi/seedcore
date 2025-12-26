# Trainer vs TRL SFTTrainer: FunctionGemma Training Guide

Great question — this is exactly the right moment to compare them, because **your current LoRA setup is already correct**, and the choice between **plain `Trainer` vs TRL `SFTTrainer`** determines *how far* you can push FunctionGemma.

I'll break this down **precisely in the context of your SeedCore intent compiler**, not generic LLM training.

---

## TL;DR (Executive Summary)

| Aspect                               | Your current LoRA + Trainer | TRL `SFTTrainer` |
| ------------------------------------ | --------------------------- | ---------------- |
| Works for FunctionGemma tool-calling | ✅ Yes                       | ✅ Yes            |
| Simplicity                           | ⭐⭐⭐⭐⭐                       | ⭐⭐⭐              |
| Control over format                  | ⭐⭐⭐⭐                        | ⭐⭐⭐⭐⭐            |
| Multi-turn / tool-call robustness    | ⭐⭐⭐                         | ⭐⭐⭐⭐⭐            |
| Preference learning (later)          | ❌ No                        | ✅ Yes            |
| Long-term roadmap                    | ⚠️ Limited                  | 🚀 Best          |

**Verdict:**
👉 **You did the right thing starting with plain LoRA + Trainer**
👉 **Move to TRL only after the first LoRA proves value**

---

## 1️⃣ What you implemented (baseline LoRA)

You currently have:

```python
Trainer(
    model=model,
    train_dataset=dataset["train"],
    eval_dataset=dataset["test"],
)
```

### What this gives you

✅ Deterministic supervised learning
✅ Very stable on CPU
✅ Minimal dependencies
✅ Easy to debug
✅ Perfect for **Phase 1: "make the model stop being dumb"**

### What it learns well

* Mapping:

  ```
  user text → function name
  ```
* Emitting *some* JSON-like structure
* Replacing fallback heuristics

### What it does **not** learn well

* Strict JSON validity under stress
* Tool-call schema discipline
* Multi-tool ambiguity resolution
* Confidence calibration
* "Don't hallucinate tools"

That's why you still see:

```
function = "unknown"
confidence = 0.2
```

Even when the model *kind of* understands.

---

## 2️⃣ What TRL `SFTTrainer` changes (important)

TRL (`trl` library) was built **specifically for instruction + tool tuning**.

### Key difference (very important)

> **TRL trains on *conversations*, not raw token sequences**

That matters because **FunctionGemma is instruction-tuned**, not a base LM.

---

### Your current training signal (simplified)

```
[USER TEXT] → [ASSISTANT TOKENS]
```

### TRL training signal

```
(system)
(user)
(assistant → tool_call JSON)
```

That aligns *exactly* with:

```json
{
  "messages": [...],
  "tools": [...]
}
```

Which you already prepared 👏

---

## 3️⃣ Concrete comparison in your codebase

### Your current trainer

```python
Trainer(
    model=model,
    args=args,
    train_dataset=dataset["train"],
)
```

### TRL version (drop-in replacement)

```python
from trl import SFTTrainer

trainer = SFTTrainer(
    model=model,
    train_dataset=dataset["train"],
    eval_dataset=dataset["test"],
    tokenizer=tokenizer,
    max_seq_length=2048,
    packing=False,
)
```

**That's it.**
No architecture change. Same LoRA. Same dataset.

---

## 4️⃣ Why TRL is better *for intent compilers*

### 1. Tool-call correctness

TRL **reinforces the tool-call boundary**, not just text.

That means fewer cases like:

```json
{"function": "unknown"}
```

when a schema exists.

---

### 2. Schema faithfulness

TRL implicitly teaches:

> "If tools exist → choose one"

Plain Trainer does not.

---

### 3. Future-proofing (this matters for SeedCore)

Once you move beyond fallback imitation, TRL unlocks:

| Feature                 | Why it matters                  |
| ----------------------- | ------------------------------- |
| Preference tuning (DPO) | Train confidence calibration    |
| Rejection sampling      | Reduce hallucinations           |
| Multi-tool arbitration  | Critical for hotels / buildings |
| Reward modeling         | Energy-aware routing            |

You *cannot* do this with plain Trainer.

---

## 5️⃣ When NOT to use TRL (important)

Do **NOT** use TRL if:

❌ You are still debugging data format
❌ You don't yet trust your fallback outputs
❌ You are CPU-only and want fastest iteration
❌ You're still under 1k samples

👉 That's why your current choice was correct.

---

## 6️⃣ Recommended migration path (very important)

### Phase 1 (you just finished)

✔ Plain Trainer + LoRA
✔ Validate pipeline
✔ Fix intent compiler bugs
✔ Ensure model loads + routes

### Phase 2 (next step)

➡ Switch Trainer → `SFTTrainer`
➡ Keep **same dataset**
➡ Train again (2–3 epochs)

### Phase 3 (later)

➡ Add **negative samples**
➡ Add **ambiguous intents**
➡ Add **confidence targets**
➡ Move to **DPO**

---

## 7️⃣ Minimal TRL upgrade for you (ready-to-use)

Create a second trainer file:

```python
# train_intent_lora_trl.py
from trl import SFTTrainer

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset["train"],
    eval_dataset=dataset["test"],
    max_seq_length=2048,
    packing=False,
)

trainer.train()
```

Everything else stays the same.

---

## 8️⃣ Final recommendation (clear & honest)

> ❝ Your intuition was correct:
> **The model "doesn't work well" because it's not trained for tool discipline — not because FunctionGemma is weak.** ❞

FunctionGemma **needs**:

* structured supervision
* conversation-aware loss
* schema pressure

TRL gives you that — **when you're ready**.

---

If you want, next we can:

* design **negative samples**
* design **confidence targets**
* or build a **hotel-specific intent dataset**

Just say **"next: dataset strategy"** or **"next: TRL migration"** 🚀


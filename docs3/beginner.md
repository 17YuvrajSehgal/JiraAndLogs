# Beginner's Guide — What this research is actually doing

*A no-jargon explanation for readers with little or no machine-learning background. We will define every technical word the first time it appears.*

---

## 1. The problem we are solving

Imagine you work at a big tech company that runs a website made of dozens of small programs (we call these "**microservices**"). Each of these little programs handles a slice of the user's request: one logs the user in, another adds items to the cart, another talks to a payment provider.

At 3 in the morning, a pager goes off. The website is sick. As the on-call engineer, you have ~5 minutes to figure out what is broken and why.

Most companies already have **anomaly detection** software that screams "something is broken" — that part is well solved. What is *not* solved is the next question: **"What exactly is wrong, and have we seen this same problem before?"**

Most teams keep a record of past problems in a system called **Jira**, where each past incident is written up as a "ticket" with a description, a discussion thread, and a resolution. There are usually hundreds or thousands of these tickets — too many for any human to search through during an emergency.

**Our research question:** Can we automatically read the engineer's live signals (logs, traces, metrics) and instantly point them to the past Jira ticket that explains the current problem?

Think of it like Shazam, but for system outages. You hear a snippet of music (live telemetry), and the app tells you the song (past ticket).

---

## 2. The two predictions our system makes

For every 5-minute slice of time (we call this a "**window**"), our software answers two questions:

### Question A — "Is anything wrong?" (Triage)
A simple yes-or-no answer. If the system is healthy, ignore. If it is sick, raise an alert.

Internally this is a number between 0 and 1: 0 means "definitely fine," 1 means "definitely a problem worth paging someone about." This is called a **probability score**.

### Question B — "What past Jira ticket does this look like?" (Retrieval)
Given that there is a problem, find the 1–5 most-similar past Jira tickets so the engineer can read the prior resolution. We rank all the tickets we have ever seen and show the top 5.

Throughout this document, when we say "**retrieval**" we mean Question B (finding similar past tickets), and when we say "**triage**" we mean Question A (is there a problem).

These are two completely separate questions. A system can be great at one and terrible at the other.

---

## 3. What data we actually have

Our experiment uses synthetic-but-realistic data so we can measure exactly what works. The dataset has three pieces:

### 3.1 Windows (the live signals)
- **2,940 test windows.** Each window is a 5-minute slice of what was happening in the system during one moment.
- For each window, we have **94 numeric measurements** computed from the raw signals: things like "average response time over the last 5 minutes," "number of error logs," "number of pods that restarted," "CPU usage percentage." These numbers come from logs, traces, and Kubernetes events under the hood. We call these the **numeric features**.
- We also have the raw text content of the logs (the actual error messages programmers see).

### 3.2 The Jira ticket memory
- **347 past tickets** written in a realistic engineer voice — each one looking like something an on-call engineer would write after fixing a problem at 3 AM. They include code snippets pasted from terminals, conversational comments back-and-forth between engineers, and a final resolution.
- These tickets are stored as files of natural-language text.

### 3.3 The "answer key" (gold labels)
For every window, we know the truth:
- Whether the window was actually a problem worth filing a ticket for ("ticket-worthy") or noise.
- Which past tickets are the "correct match" for this window (often 0 to 21 tickets, since several past tickets can be relevant to the same kind of problem).

The answer key was built by people who had access to information the models cannot see (e.g., which specific fault was injected). The models never see the answer key during training — they only see it at the very end when we grade them.

---

## 4. The deep question: how does a computer read text?

This is the part most beginners trip on. Computers do not "understand" English. They only understand numbers. So before any text can be fed to a machine-learning model, it must be turned into numbers. This is called **encoding** the text.

### 4.1 The naive approach — count words
The simplest method is: take a text like "redis connection timed out," chop it into words, and count how often each word appears. Now your text is a list of word counts: `{redis: 1, connection: 1, timed: 1, out: 1}`. This is the foundation of an old algorithm called **BM25** (you do not need to know what those letters stand for — think of it as "smart word counting"). BM25 is what your library catalog or Google's earliest search engine used.

The catch: BM25 cannot tell that "Redis connection failed" and "Database link broken" are about the same thing, because they share zero words. It only matches exact words.

### 4.2 The modern approach — embeddings
Modern AI replaces word-counting with **embeddings**. The idea:

> Translate every piece of text into a list of numbers (typically 384 or 768 numbers long) such that pieces of text with *similar meaning* land at nearby points in number-space.

So "Redis connection failed" and "Database link broken" would get very similar lists of numbers, even though they share no words. The list of numbers is called a **vector**, and the space it lives in is called the **embedding space**.

A neural network called **BERT** (and its smaller cousin **MiniLM**) is the standard tool for producing these embeddings. Once your text is embedded, you can compare two texts by measuring how close their vectors are — this is called **cosine similarity**. Close vectors = similar meaning.

This is the magic that lets modern AI "understand" that two differently-worded incidents are about the same problem.

### 4.3 Where the 50 million log lines come in
We have access to about 50 million raw log lines from the test systems. We do NOT feed all 50 million lines into the model — that would be too slow and the model would drown in noise. Instead, for each window:

1. We summarize the logs into a short "characteristic line" — typically the one error message that best describes what went wrong.
2. We extract structured features like `error_count_last_5_min = 47` and `services_with_errors = ["cartservice", "checkoutservice"]`.
3. The summary line is what gets fed to the text-encoder models (BERT / MiniLM).
4. The structured features are what gets fed to the number-only models (HGB, TabTransformer).

This way each model only sees the kind of data it can handle, and we don't waste GPU time embedding redundant log lines.

---

## 5. The four models we compare, in plain English

We compare four different machines to see which one is best at our two prediction tasks.

### Model 1 — HGB (Histogram Gradient Boosting): the classical baseline

**What it is:** HGB is a tree-based classifier. Think of it as a giant flowchart that asks yes/no questions until it reaches a verdict.

**How it learns:** During training, HGB looks at thousands of past windows where it knows the answer ("was this ticket-worthy or noise?") and figures out which 94 numeric features matter the most. It builds a chain of decision trees: the first tree makes a rough guess, the next tree corrects its mistakes, the next tree corrects *those* mistakes, and so on, hundreds of times.

**What it sees:** Only the 94 numeric features per window. It does NOT see any text. It does NOT see any Jira tickets.

**What it predicts:** Only the triage answer (problem or not). It cannot answer the retrieval question because it has no concept of past tickets.

**Strengths:** Extremely good at the triage task. Fast to train (a few seconds). Well-understood. Reliable.

**Weaknesses:** Cannot do retrieval. Cannot read text. Cannot use new kinds of input without manual feature engineering.

### Model 2 — TabTransformer: the modern neural baseline

**What it is:** A **Transformer** is the kind of neural network behind ChatGPT, Google Translate, and most modern AI. The basic idea: it looks at all parts of its input *at the same time* and figures out which parts relate to which. This "looking at everything at once" is called **attention**, and it is what makes Transformers good at understanding context.

TabTransformer applies this idea to numbers (instead of text). Each of the 94 numeric features becomes a "token" (like a word would be), and the Transformer learns which features matter together.

**How it learns:** Same idea as HGB — given thousands of examples with known answers, adjust internal "weights" (millions of small numbers inside the network) so its predictions match the truth. The adjustment is done by an algorithm called **gradient descent** which essentially says: "the answer was wrong, so nudge every weight a tiny bit in the direction that would have made the answer more right."

**What it sees:** The same 94 numeric features as HGB.

**What it predicts:** Same as HGB — only the triage answer.

**Why include it:** We added TabTransformer to answer the question "is HGB really the best for triage, or are we just using an old-fashioned tool?" If a modern Transformer significantly beat HGB, our story would change. (Spoiler: it doesn't.)

### Model 3 — MemoryGraph SOTA: the cross-encoder reranker

**SOTA** means "state of the art" — the best version of an existing approach.

**What it is:** A pipeline of several smaller steps that work together. The interesting part is the final step: a **cross-encoder reranker**.

**How a cross-encoder works:** Imagine you want to know if two paragraphs are about the same topic. A cross-encoder reads the two paragraphs *together*, side by side, and outputs a score from 0 to 1: "how related are these two?" It's like having someone read both paragraphs and give a relatedness score.

This is *very accurate* but *very slow*: you have to feed every pair you want to compare through the model. If you have 347 Jira tickets and one incoming window, you'd need 347 separate cross-encoder runs to score every ticket. That's expensive.

To save time, our pipeline first uses cheap word-counting (BM25) to pick the top-20 most-promising tickets, then runs the cross-encoder only on those 20. This is called **two-stage retrieval**.

**What it sees:** The 94 numeric features (for triage), plus all the text from logs and Jira tickets (for retrieval).

**What it predicts:** Both triage AND retrieval.

**The cross-encoder we use:** A pre-built model called **MS-MARCO MiniLM-L-6-v2**, which was already trained by someone else on a giant dataset of internet questions and answers. We use it without modification ("off-the-shelf").

### Model 4 — BiEncoder: the production-deployable retrieval model (THE STAR of this paper)

**The key insight:** the cross-encoder is too slow for real production use. If you had a million Jira tickets, you couldn't run a cross-encoder on every pair at 3 AM during an incident.

**What a bi-encoder does instead:**

1. Take a Jira ticket. Run it through BERT-like encoder ONCE. Get a vector (list of 384 numbers).
2. Store that vector. Forget the ticket text.
3. Repeat for all 347 tickets. Now you have a "library" of 347 vectors.

When a new window arrives:
1. Encode the window's text into its own 384-number vector. Once.
2. Use simple mathematics (a dot product, basically high-school multiplication) to find which of the 347 stored vectors is closest. This is *blazingly* fast — milliseconds even with millions of vectors.

**The big difference:** cross-encoder reads pairs together (slow but accurate); bi-encoder reads each text once independently (fast). The trade-off is that bi-encoder is slightly less accurate per-comparison, but compensates by being scalable to huge corpora.

**How we made our bi-encoder smart:** We took an off-the-shelf MiniLM model and **fine-tuned** it on our specific kind of data.

#### What "fine-tuning" means
Suppose someone trains a chef on a generic cooking course. They can make decent food. Now you take that chef and give them six months to specialize in Italian cuisine — they will now cook better Italian food, though they may have forgotten how to make a great curry.

That is fine-tuning a neural network. The model starts off "knowing" general English from its earlier training. We then show it thousands of examples of "this telemetry-window matches that Jira ticket," and it adjusts its internal weights so similar window-ticket pairs land closer in embedding space.

#### What pairs we trained on
About 12,000 examples, each looking like:
- An **anchor** (a window query text)
- A **positive** (a Jira ticket that is the correct match for that window)
- 3 **hard negatives** (Jira tickets that look similar but are actually wrong matches, picked by BM25)

The model learns to push the positive close to the anchor and the hard negatives far away. The loss function used is called **MultipleNegativesRankingLoss** — a way of saying "make sure the right answer scores higher than every wrong answer in the batch."

**What our bi-encoder predicts:** Both triage (using similarity scores plugged into a simple model called logistic regression) AND retrieval.

---

## 6. How we train and test the models — the honest way

A common mistake in machine learning is to test a model on the same data you trained it on. This is like grading a student using the exam questions they already memorized. Of course they get 100%.

To avoid this, we split our data into three pieces:

| Split | Number of windows | Purpose |
|---|---:|---|
| **Train** | 2,796 | Model studies these — adjusts its internal weights here. |
| **Validation** | 984 | Model never sees these during training. Used to pick the best "hyperparameters" (knob settings) and to decide when to stop training. |
| **Test** | 2,940 | The final exam. The model has never seen these, never tuned anything on them. The numbers we report come from here. |

To make this even more honest, we split by **scenario family**: the kinds of problems in the test set (`cart-redis`, `productcatalog-latency`, etc.) do NOT appear in the training set. This is like teaching the model only about car breakdowns and then asking it to diagnose a bicycle — if it still finds something useful, we know it has learned something general rather than memorized.

---

## 7. How we measure who wins

For triage, the standard score is called **PR-AUC** (Precision-Recall Area Under Curve).

Think of PR-AUC this way: "If I trust the model to flag the windows it is most confident about, what fraction of those are real problems?" A score of 1.0 means perfect, 0.5 means random guessing, 0.0 means utterly broken.

For retrieval, we use three scores:

- **Hit@1:** Of all the times a correct ticket exists in memory, how often does the model put the right ticket at position 1?
- **Hit@5:** How often does the model put the right ticket somewhere in the top 5?
- **MRR (Mean Reciprocal Rank):** How high in the ranking does the right ticket typically appear? Closer to 1.0 = right at the top; closer to 0 = buried.

Imagine you ask Google a question and the answer is in the 7th result. That's bad. Hit@5 would say "miss." MRR would say 1/7 ≈ 0.14. Compare to the answer being result #1: Hit@5 = 1, MRR = 1. The higher the number, the better.

### Why we trust our numbers — the bootstrap test
A single number can be misleading. If we say "the model gets Hit@5 = 0.20," is that 0.18 to 0.22, or 0.05 to 0.40? The width of that range is called a **confidence interval**.

We use a technique called **bootstrap resampling**: re-run the evaluation 1,000 times, each time on a slightly different randomly-shuffled subset of the test windows. This gives us an honest range like "Hit@5 = 0.20, 95% confident the true value is between 0.17 and 0.23." When two models' ranges don't overlap, we can say one is reliably better; when they overlap a lot, the difference might just be noise.

---

## 8. What we actually found

### Result 1 — Telemetry-only models OWN the triage task

| Model | PR-AUC |
|---|---:|
| HGB | **0.77** |
| TabTransformer | 0.77 (basically tied with HGB) |
| MemoryGraph SOTA | 0.62 |
| BiEncoder | 0.24 |

Translation: when the question is "is this window a problem?", the simple numerical models destroy the memory-augmented ones. The Jira ticket memory does NOT help with detection. We say this honestly in the paper rather than oversell.

The neural TabTransformer is statistically tied with HGB — adding fancy neural architecture to triage does not help. The signal in the 94 numeric features is already saturated.

### Result 2 — The bi-encoder dominates retrieval

When the question shifts to "what past ticket matches this incident?", the picture flips completely:

| Model | Hit@1 | Hit@5 | MRR |
|---|---:|---:|---:|
| HGB | 0.000 | 0.000 | 0.000 (cannot retrieve) |
| TabTransformer | 0.000 | 0.000 | 0.000 (cannot retrieve) |
| MemoryGraph SOTA | 0.158 | 0.202 | 0.172 |
| **BiEncoder (ours)** | **0.177** | **0.233** | **0.196** |

The fine-tuned bi-encoder beats the cross-encoder reranker by 12–15% on every retrieval metric.

### Result 3 — Retrieval scales with how long the system has been in service

The most interesting finding. As the memory accumulates more compatible past tickets (think: "the longer the team has been writing Jira tickets, the more useful the system becomes"), retrieval gets better:

| Number of compatible past tickets | Hit@1 (BiEncoder) |
|---|---:|
| 1–2 prior | 0.12 |
| 3–5 prior | 0.19 |
| 6–20 prior | 0.21 |

The more memory the system has, the better it can answer the diagnosis question. This is the central story of our paper.

(Honesty caveat: the "21+ prior" bucket has a problem — the BiEncoder gets confused on a specific sub-scenario. We document this in the paper as an honest weakness.)

### Result 4 — Engineer time saved

If we assume the engineer spends 30 seconds reading each candidate ticket and falls back to 30 minutes of manual digging when no candidate is helpful:

| Model | Average diagnosis time per incident |
|---|---:|
| HGB / TabTransformer (no retrieval) | 30.0 min |
| MemoryGraph SOTA | 24.1 min |
| **BiEncoder (ours)** | **23.2 min** |

About 7 minutes saved per incident. Across hundreds of incidents per year, that's days of engineer time.

---

## 9. The honest "what didn't work"

Good research reports failures, not just wins. Three honest negatives in our work:

1. **Cold-start failure.** When a problem has *no* compatible memory tickets at all (it's a totally new kind of incident), our system doesn't reliably flag it as "novel." It just guesses something plausible-looking from memory, which is misleading. We report this as future work.

2. **BiEncoder over-specialization.** As mentioned above, the bi-encoder learned the training distribution so well that it gets confused on one specific test sub-scenario it never saw exactly. This shows our fine-tuning was a touch too aggressive.

3. **Triage detection was not improved by adding memory.** We had originally hoped memory would also help triage. It does not. We honestly report this rather than hide it.

---

## 10. Why this matters

The bottleneck in modern on-call response is no longer "is something wrong?" — we have great detectors for that. The bottleneck is **diagnosis**: figuring out what is wrong and what to do about it. Engineers waste minutes (sometimes hours) at 3 AM correlating live signals against half-remembered past incidents.

Our work shows that a relatively simple machine-learning system, fed past Jira tickets and live telemetry, can give the engineer a ranked list of likely matches in seconds. The system gets better as the team accumulates more incident history — your past pain becomes future leverage.

This is not a magic bullet. It does not replace the engineer. It is a *retrieval assistant* that says "here are the 5 past tickets most likely related to what you are seeing." The engineer still makes the final call.

---

## 11. Mini-glossary

| Term | Plain-English meaning |
|---|---|
| Anomaly / Triage | The question of "is something wrong, yes or no?" |
| Retrieval | The question of "find similar past examples of this." |
| Embedding | A list of numbers that represents a piece of text such that similar texts have similar lists. |
| Vector | Same as embedding; a list of numbers. |
| Cosine similarity | A way to measure how close two vectors are. |
| BERT / MiniLM | Specific neural networks designed to produce embeddings for text. |
| BM25 | A traditional keyword-matching algorithm — fast, no AI. |
| Cross-encoder | A neural network that reads two pieces of text together to produce a similarity score. Slow but accurate. |
| Bi-encoder | A neural network that encodes each piece of text independently into a vector. Fast and scalable. |
| Fine-tuning | Taking a pre-trained model and adapting it to a specific kind of data with extra training. |
| Hard negatives | Wrong-answer examples that *look* almost right — used to teach the model what NOT to match. |
| HGB / Gradient Boosting | A non-neural classical machine-learning method built from decision trees. |
| Transformer | A neural network architecture (used in ChatGPT, Google Translate, etc.) that processes its input by paying attention to all parts at once. |
| Train / Validation / Test split | The discipline of holding back data so we can grade the model honestly. |
| PR-AUC | A standard score for "yes/no" tasks (higher is better, max 1.0). |
| Hit@K | "Does the right answer appear in the top K results?" (higher is better, max 1.0). |
| MRR (Mean Reciprocal Rank) | "How high up does the right answer typically appear?" (higher is better, max 1.0). |
| Confidence interval | A range that captures how uncertain a measurement is. |
| Bootstrap resampling | A statistical technique that produces a confidence interval by re-evaluating on many random subsets. |
| GPU | The graphics card. Used as a math accelerator for training neural networks. Our RTX 5060 trained both neural models in under 10 minutes total. |

---

## 12. What to read next

If this overview interests you and you want progressively more detail:

| Read this for... | File |
|---|---|
| The exact architectures with parameter counts | `docs3/01-MODELS.md` |
| What data feeds what model | `docs3/02-DATA-FLOW.md` |
| Learning rates, optimizers, training tricks | `docs3/03-TRAINING-RECIPE.md` |
| How efficiently we used the GPU | `docs3/04-GPU-USAGE.md` |
| The locked numbers with confidence intervals | `docs3/07-FINAL-RESULTS.md` |
| The full paper draft (for ICSE 2027) | `paper/main.tex` |

Welcome to ML research. It is mostly bookkeeping, honest measurement, and the occasional surprise.

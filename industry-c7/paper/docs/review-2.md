Updated ICSE 2027 Industry Challenge Track Evaluation
Paper: Log-Guided Root-Cause Code Localization from Production Issues: A Comparative Study and an Agent

Challenge: Problem 7 — Log-Guided Root-Cause Code Localization from Production Issues

Updated preliminary recommendation
Overall assessment
Borderline / Weak Reject

6.8/10
Subjective paper assessment
35–45%
Estimated acceptance probability

These are my subjective estimates, not official reviewer scores or calibrated acceptance statistics.

My assessment is that this is a technically substantial paper with a credible practical problem, an interesting benchmark, and promising results. However, its central claim of root-cause localization is not yet supported as strongly as its file-localization results suggest.

1. Does the paper satisfy the actual Industry Challenge?
This is where I would give the paper considerable credit.

Problem 7 identifies three major technical challenges:
1. Evidence-to-code semantic retrieval.
2. Root-cause localization beyond symptoms.
3. Benchmark and evaluation using issue reports, logs, source code, and ground-truth faulty regions.
It also describes an expected workflow that takes issue reports, logs, and source snapshots and produces:
- The affected module.
- A ranked list of suspicious code regions.
- An explanation connecting symptoms, selected log events, and candidate code regions.
Your paper addresses much of this problem directly.

Challenge requirement	Your paper's coverage	My assessment
Issue reports, logs and source snapshots	Uses all three	Strong
Semantic log-to-code retrieval	Multiple retrieval signals and model-based approaches	Strong
Incident history	Temporal incident memory	Strong
Ranked suspicious code regions	Acc@1 and Acc@5 evaluation	Strong
Root cause beyond symptoms	Agent uses symbol resolution and code-reading tools	Partial
Noisy and incomplete logs	Synthetic perturbation experiments	Partial
Explanation connecting evidence to code	Tool-based investigation, but limited causal explanation evaluation	Partial
Benchmark with ground-truth faulty regions	6,437 real incidents, with fix-modified files as ground truth	Partial

My interpretation: The paper is clearly relevant to the challenge. It is not an unrelated academic solution trying to fit an industry track.

However, the challenge explicitly emphasizes causal root-cause localization, not simply retrieving files that are likely to be associated with a fix.

That distinction is the paper's biggest scientific vulnerability.

2. What I particularly like about the paper
A. The benchmark is a meaningful contribution
You have assembled 6,437 real incidents from:
- Apache Kafka
- MariaDB
- MongoDB
- Qt
Each instance connects an issue report, logs, a source snapshot from the time of the issue, and files modified by the eventual fix.

The 53% statistic is particularly interesting: in more than half of the reports, none of the files touched by the eventual fix is named in the report.

This supports the motivation that engineers cannot simply search for filenames mentioned in an issue report.

I also appreciate that you have a temporal firewall. Incident retrieval can easily introduce information that would not have been available when an issue was reported. Your approach explicitly prevents that.

Reviewer assessment: Strong contribution. The benchmark and temporal evaluation protocol give the paper value beyond the proposed agent.
B. The comparative study is well motivated
You do not immediately introduce an LLM agent and claim it is better.

Instead, you compare different approaches:
- Classical information-retrieval bug localization.
- Lexical log-to-code retrieval.
- Retrieval combined with historical incident memory.
- A general-purpose 27B model.
- Model-based reranking.
- A tool-using agent.
The results show that the different approaches solve different instances.

This is an important observation because it motivates combining complementary evidence sources rather than assuming that one model or retrieval method will solve everything.
C. The incident memory is one of the strongest ideas
The temporal incident memory is arguably one of the most interesting aspects of the paper.

The fact that removing the temporal firewall inflates the classic similar-report signal by 9–43% demonstrates why evaluation methodology matters.

This is a useful contribution for other researchers working on historical incident retrieval.
D. The agent improves over the same model
The headline results are promising:
Approach	Acc@5
rVSM	18.0%
BugLocator	25.1%
BRTracer-style	48.1%
Retrieval + incident memory	68.1%
Model alone	83.2%
Best non-agent fusion	83.9%
REMEMBER	90.3%

REMEMBER improves Acc@5 by 7.1 percentage points over the same model prompted directly.

It also improves Acc@1 from 59.4% to 72.3%.

This is valuable because the improvement is not simply attributed to using a stronger model. The same 27B model is used in both configurations.

Reviewer assessment: Strong experimental motivation, although the agent evaluation needs to become more comprehensive.

3. The biggest weakness: Are you actually finding the root cause?
Critical scientific concern
This remains my biggest concern.

Your benchmark defines ground truth using files modified by the eventual fix commit.

That is a reasonable way to construct a large-scale benchmark, but it does not necessarily establish that every modified file contains the actual causal defect.

Consider the difference:
- A file may contain the underlying defect.
- A file may detect or report the failure.
- A file may be modified to prevent the failure from recurring.
- A file may be modified as part of a broader refactoring or cleanup.
These are not necessarily the same location.

Your motivating Kafka example, KAFKA-6624, makes the distinction particularly important.

The stack trace identifies FileChannelImpl.force and FileRecords.flush, while the actual fix modifies LogManager.scala.

This is an excellent example of the problem you want to solve.

However, your agent still ranks Log.scala and LogSegment.scala rather than identifying LogManager.scala as the root cause.

This creates a problem for the paper's central claim.

You demonstrate that the system improves localization against fix-modified files, but you do not consistently demonstrate that it identifies the underlying causal code.

What I would do:

Manually investigate approximately 100–150 incidents and annotate:
1. The actual causal function or code region.
2. The symptom-producing function or code region.
3. The logging statement or stack-trace location.
4. The relationship between the symptom and the underlying cause.
Ideally, have two independent annotators and report their agreement.

You do not need to manually annotate all 6,437 incidents. A carefully selected subset would provide a much stronger validation of the central claim.

Then evaluate REMEMBER against both:
- Existing fix-file ground truth.
- Independently annotated causal ground truth.
This would be a substantial improvement.

4. The agent is promising, but its investigation is shallow
The agent uses tools to:
- Read source code.
- Resolve symbols from stack traces.
- Search the repository.
- Retrieve historical incidents.
- Inspect declarations and callers.
- Record candidates.
I like the architecture, particularly because the tools provide structured access to evidence instead of relying entirely on a large prompt.

However, the agent often performs only one or two investigation steps.

For a paper specifically about root-cause localization, I would expect more systematic investigation of:
- Callers and callees.
- Data dependencies.
- Control-flow relationships.
- State transitions.
- Error propagation.
- Relationships between symptom-producing and causal functions.
For example, suppose a log says that a file operation failed.

A good root-cause investigation should ask:
1. Which function emitted the error?
2. Which function called it?
3. What state or condition caused the failure?
4. Which earlier operation produced that state?
5. Where should the underlying defect be localized?
Your current agent has some of the infrastructure to investigate these relationships, but it does not yet demonstrate this level of causal reasoning consistently.
My recommendation
Do not simply add more tools.

Instead, introduce a structured investigation strategy that requires the agent to establish a chain of evidence between the observed symptom and the suspected causal code.

Then measure whether that investigation actually improves causal localization.

5. Evaluation: Good results, but some limitations remain
A. The agent evaluation uses only 790 instances
The full evaluation split contains 4,508 incidents, but the agent evaluation uses 790 instances.

This is understandable given the cost of running an agent, but it raises questions about generalizability.

You should ideally run the agent on the full evaluation split.

If that is not feasible, I would at least recommend:
- Increasing the sample substantially.
- Reporting project-level results.
- Reporting results separately for easy and hard instances.
- Running multiple seeds.
- Reporting confidence intervals.
- Explaining the sampling procedure.
B. Only one model is used
The paper uses one 27B model.

The same-model comparison is a strength, but reviewers may ask whether REMEMBER's architecture generalizes beyond that model.

If possible, evaluate a second model with a different architecture or capability level.

This would help establish that the improvement comes from the investigation architecture rather than a model-specific interaction.
C. Noise experiments need stronger realism
The paper evaluates several perturbations:
- Duplicate messages.
- Generic messages.
- Foreign or unrelated messages.
- Dropped messages.
I like this experimental design.

However, these perturbations do not fully reproduce real industrial log bundles.

For example, real production logs may contain:
- Multiple concurrent incidents.
- Retries and cascading failures.
- Repeated background activity.
- Missing decisive events.
- Multiple services producing interleaved messages.
- Time-dependent relationships between events.
The challenge explicitly emphasizes these conditions.

I would prioritize testing mixed-incident logs, missing decisive messages, and realistic downstream error propagation.

You do not necessarily need proprietary production logs to conduct these experiments.

6. Is the lack of industrial validation a weakness?
I would no longer list the absence of industrial deployment or a developer study as a major weakness.

The CFP does not require these.

The track explicitly asks for:
- Technical soundness.
- Relevance to the selected industry challenge.
- Potential for impact.
It does not say that the solution must already be deployed or validated by the originating company.

Your benchmark uses real historical issues from four software projects. That is legitimate evidence for an academically evaluated solution to an industry-relevant problem.

However, I would still distinguish between two things:

Industrial validation: A developer study, company deployment, or evaluation using proprietary production incidents. Optional based on the CFP.

Industrial relevance: Demonstrating that your problem, assumptions, inputs, outputs, and proposed workflow genuinely correspond to the practical challenge. Essential.

Your paper has a good foundation for the second.

I would strengthen it by explaining how an engineer would use REMEMBER during incident triage, what information the engineer would receive, and how the ranked candidates and evidence would reduce investigation effort.

You already report useful operational measurements:
- 12.2 model calls per issue.
- Approximately 90,000 prompt tokens.
- Approximately 232 seconds per issue.
- Retrieval-only execution in under one second on one CPU core.
These are important practical considerations.

A small developer study would be a bonus, not something I would make a prerequisite for submission.

7. Other weaknesses I expect reviewers to raise
Issue	Severity	Why it matters
Fix-modified files used as causal ground truth	Very high	Weakens the root-cause claim
Agent evaluated on only 790 instances	High	Limits confidence in generalizability
One model and one seed	Medium–high	Unclear whether results generalize
Shallow causal investigation	Very high	The central challenge is root-cause localization
Synthetic noise rather than realistic mixed logs	Medium–high	Incomplete coverage of industrial log conditions
Function-level localization results	High	Acc@1 and Acc@5 remain relatively modest
Limited explanation evaluation	Medium	The challenge explicitly requests evidence connecting symptoms to code
No industrial developer study	Low / optional	Not required by the CFP

One more important point: the function-level extension is currently relatively weak. Its Acc@1 ranges from 13.2% to 25.9% across the projects, and its Acc@5 ranges from 27.4% to 47.8%.

This does not invalidate the file-level results, but it does limit how confidently you can claim localization of defective code regions.

8. What I would prioritize before submission
I would not spend all your remaining time adding more components to the system. I would concentrate on experiments that directly address the reviewers' biggest concerns.
Priority 1 — Establish causal ground truth
Highest priority
Manually annotate a subset of incidents with causal functions, symptom functions, and logging locations. Compare the agent against this independent ground truth.

Why: This directly addresses the biggest gap between your title and your experimental evidence.

Priority 2 — Expand the agent evaluation
Very high priority
Run REMEMBER on more of the 4,508 evaluation instances, ideally all of them. Add multiple seeds and project-level breakdowns.

Why: The current 790-instance evaluation leaves room for questions about sample selection and robustness.

Priority 3 — Improve causal investigation
Very high priority
Add structured caller/callee and data/control-flow investigation. Measure whether these capabilities improve causal localization, not just file retrieval.

Why: This makes the proposed solution better aligned with Problem 7.

Priority 4 — Improve realistic noise evaluation
High priority
Test mixed incidents, missing decisive events, cascading failures, and interleaved logs.

Why: The challenge specifically emphasizes noisy and incomplete production log evidence.

Priority 5 — Evaluate evidence explanations
High priority
Evaluate whether the agent can correctly connect report symptoms, log events, and candidate code regions. Include examples of correct and incorrect reasoning.

Why: The expected output explicitly includes an explanation, not just a ranked list.

Priority 6 — Add a developer study
Optional enhancement
If resources permit, ask a small number of experienced developers to inspect a subset of incidents with and without REMEMBER.

Why: This would demonstrate practical value, but it is not a formal requirement of the CFP.


9. Updated simulated reviewer feedback
Here is how I could imagine four reviewers evaluating the paper under the actual Industry Challenge Track expectations.
Reviewer	Recommendation	Main reasoning
Reviewer 1	Weak Reject	Strong benchmark and retrieval study, but ground truth does not establish causal root cause
Reviewer 2	Weak Reject	Agent evaluation is limited, and causal reasoning is insufficiently demonstrated
Reviewer 3	Borderline	Relevant to the industry challenge, technically sound, and promising results, but practical impact is not yet fully established
Reviewer 4	Weak Accept	Valuable benchmark, temporal firewall, complementary retrieval and LLM evidence, and strong improvements over baselines

The disagreement would more likely revolve around whether the paper actually solves the root-cause localization problem or primarily improves file-level localization.

10. Updated acceptance probability
Here is my revised estimate based on the paper's current state and the CFP you provided.
Paper condition	My subjective estimate
Current version	35–45%
Stronger baselines and larger agent evaluation	40–50%
Plus independent causal ground truth	50–60%
Plus stronger causal investigation and realistic noise experiments	55–65%
Plus convincing practical evaluation	60–70%

These are judgment-based scenarios, not statistically derived probabilities. Improvements are not guaranteed to produce these outcomes.

11. My final verdict
Updated recommendation
Borderline / Weak Reject

6.8 / 10
Estimated acceptance chance: 35–45%

I believe this paper has a legitimate chance at ICSE 2027 Industry Challenge Track. It addresses the selected challenge directly, has a meaningful benchmark, and demonstrates promising results.

I would not recommend abandoning this paper or completely redesigning its architecture.

In fact, I think the strongest aspect of the work is its combination of:
1. Historical incident knowledge.
2. Log-to-code retrieval.
3. Source-code investigation.
4. Tool-using LLM reasoning.
5. Temporal protection against information leakage.
That is a coherent research direction.

But I would be careful with the central claim. Right now, your strongest evidence is that REMEMBER identifies files associated with eventual fixes. Your challenge asks for identifying the underlying root cause.

Those are related, but they are not interchangeable.

If I were the author, I would spend most of my remaining research time proving that REMEMBER can identify the causal code, not merely improving its Acc@5 score.

That is the single change I believe could make the biggest difference to the paper's acceptance prospects.
# LinkedIn post: Inquest preprint

Paste the block below into LinkedIn. Pick "THREADS Lab" and the three co-authors from the
`@` dropdown so the tags become real links.

Before posting: the paper is under review at the ICSE 2027 Industry Challenge. ICSE's
double-anonymous FAQ asks authors not to advertise a submission on social media during
review. Check the track's FAQ first. This text never mentions ICSE or "under review".

---

When a production issue comes in, engineers get a description and some logs. No failing test, no way to reproduce it. And the logs tell you where the failure was noticed, not where it was caused. In 49% of the real issue reports we studied, the text names none of the files the fix later changed.

Our new preprint, Inquest, looks at exactly that problem: log-guided root-cause code localization.

What we did:
- Built a benchmark of 38,001 resolved issue reports from 27 open-source projects (Apache, Red Hat, MongoDB, MariaDB, Qt, Sakai), each with its pasted logs, the code as it was when the bug was live, and the files the fix changed.
- Built an agent that uses a 27B open-weights model, where the code controls the procedure and the model makes only three bounded decisions: which files to open, what role each file plays, and how to rank them.

What we found, on 26,544 evaluation reports:
- the changed file is ranked first 68.6% of the time, and in the top five 85.9%
- the correct module is named 90.2% of the time
- a free agent loop with the same model and tools finds files equally well, but names the faulty function 14 points less often

We release the benchmark, both systems and every run transcript.

Paper: https://arxiv.org/abs/2611.19554

Joint work with Sneh Patel, Mahsa Panahandeh and Naser Ezzati-Jivan at @THREADS Lab, Brock University.

#SoftwareEngineering #AIOps #LLMAgents #RootCauseAnalysis #Observability #OpenSource

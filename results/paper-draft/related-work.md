# Related work (draft)

This section will fold into §2 of `PAPER-DRAFT.md`. Keeping it separate so the citations and framing can iterate without disturbing the main draft.

## 2.1 Log-based anomaly detection

A mature line of work uses log templates and sequences to flag anomalous time windows. **DeepLog** (Du et al., CCS'17) and **LogAnomaly** (Meng et al., IJCAI'19) train LSTM and Transformer-based models over per-line log templates extracted with Drain (He et al., ICWS'17) and predict whether the next log line is expected. **PLELog** (Yang et al., ASE'21), **LogBERT** (Guo et al., IJCNN'21), and **LogADempirical** (Le et al., 2023) extend this with BERT-style masked language modeling on log templates.

These systems answer "is something wrong" — the binary anomaly question. They do *not* answer "what is wrong" — i.e., they do not retrieve a past similar incident. Our characterization confirms that telemetry-only models already saturate the binary anomaly task (HGB hits PR-AUC 0.77 on our test split); the marginal value of memory is in *citation*, not detection.

## 2.2 Multi-channel / trace-based diagnosis

**Pinpoint** (Chen et al., DSN'02) and **TraceAnomaly** (Liu et al., ICDM'20) use distributed traces to localize root-cause services. **MicroRCA** (Wu et al., NOMS'20) and **MEPFL** (Zhou et al., ESEC/FSE'19) jointly use traces and metrics for fault localization. **Eadro** (Lee et al., ICSE'23) integrates logs, traces, and metrics for end-to-end anomaly detection on microservice systems.

These systems share our multi-channel approach but localize a *service*, not a *past Jira ticket*. The retrieval-vs-localization framing is different: localization tells you "the bug is in cartservice"; retrieval tells you "this incident matches INCIDENT-1234 (cart redis OOM)."

## 2.3 Information retrieval over operational data

**LogClass** (Meng et al., IPCCC'20) and **LogPunk** (Liu et al., TSE'22) build classifiers over log signatures for category-level routing. **LogQA** (Wang et al., 2023) treats log analysis as question-answering over log text. **CauseInfer** (Chen et al., ICDCS'14) builds a graph of metric anomalies and propagates causality.

The closest work to ours is **iLog** (Jin et al., FSE'22), which retrieves past incident reports given a current log snippet using TF-IDF and ELMo embeddings. We extend this in three ways: (a) we use cross-encoder reranking, which the prior work did not have access to in the era it was published; (b) we measure retrieval quality as a function of *deployment-history depth* rather than treating the corpus as static; (c) we honestly characterize the trade-off with anomaly detection.

## 2.4 Retrieval-augmented generation (RAG)

**REALM** (Guu et al., ICML'20), **RAG** (Lewis et al., NeurIPS'20), and **Atlas** (Izacard et al., 2022) framed retrieval as augmenting generative models with external knowledge. **ColBERT** (Khattab and Zaharia, SIGIR'20) introduced late-interaction retrieval that bridges bi-encoder and cross-encoder approaches. **DPR** (Karpukhin et al., EMNLP'20) demonstrated dense retrieval beating BM25 on open-domain QA.

These methods inform our skill chain. The cross-encoder reranker we fine-tune is the same architectural class as **MS-MARCO MiniLM** (Wang et al., 2020); we adapt it from generic-web ranking to the operational-incident domain. Our finding that the fine-tune shifts probability mass into Hit@5 at the cost of top-1 is consistent with the cross-encoder literature: joint scoring improves recall but is harder to calibrate at the top rank.

## 2.5 Jira analytics

**TAWOS** (Tawosi et al., MSR'23) released 458K real Jira issues with rich metadata, used as the empirical anchor for our V2 humanized corpus. **Bichain et al.** (TSE'23) studied effort estimation from Jira descriptions. **Diamantopoulos et al.** (MSR'18) extracted bug-report duplicates with topic modeling.

Our work is closer to the *real-time retrieval* setting than to the *post-hoc analysis* setting these papers occupy. We use TAWOS only to calibrate ticket length / comment / code-block distributions for our V2 humanizer; we do not train on TAWOS.

## 2.6 SRE and AIOps surveys

**Notaro et al.** (ACM Comput. Surv.'21) survey AIOps. **Calheiros et al.** (J. Syst. Soft'21) survey log analysis approaches. **Costa et al.** (ICSE'24) survey microservice testing. These surveys position our work in the broader literature: retrieval-augmented diagnosis is identified as an open problem in AIOps but has had few rigorous empirical characterizations on multi-channel datasets.

## 2.7 What makes this paper distinct

To our knowledge, no prior work has:
1. Empirically characterized retrieval quality as a function of *deployment history depth* on a multi-channel SRE dataset.
2. Identified the standard `Recall@K = |top_K ∩ gold| / |gold|` definition as misleading in the deep-history regime and recommended Hit@K instead.
3. Fine-tuned a cross-encoder on (telemetry-window, Jira-ticket) pairs and quantified the Hit@5-vs-Hit@1 trade-off.
4. Characterized cold-start novelty failures alongside the depth-scaling success, motivating future work on calibrated novelty heads.

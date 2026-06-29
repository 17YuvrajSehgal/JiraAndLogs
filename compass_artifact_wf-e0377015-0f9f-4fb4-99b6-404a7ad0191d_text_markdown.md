# Verified References and Related Work for "Capability-Gated Agentic Incident Triage" (Remedy), ICSE 2027

## TL;DR
- **All 13 of the specifically requested method/tool references are REAL and verifiable** (with exact authors, venues, years, DOIs/arXiv IDs given below) — **except `xiao2026worldoflogs` ("World of Logs"), which could NOT be verified as a real 2026 dataset and should not be cited as written.** Note that the C-Pack/BGE paper (`xiao2024cpack`) is by Shitao Xiao but is unrelated to logs/incidents.
- The `montgomery2025jira` placeholder almost certainly maps to the verified Montgomery, Lüders & Maalej **MSR 2022** public Jira dataset; the authors "release a dataset of 16 public Jiras with 1822 projects, spanning 2.7 million issues with a combined total of 32 million changes, 9 million comments, and 1 million issue links," and "Apache is the largest repository with 1 million issues." The correct year is **2022**, not 2025.
- I add **18 verified, high-relevance related-work references** (2007–2025) spanning AIOps/empirical incident studies, LLM-based RCA agents, log anomaly detection/parsing, RAG and dense/sparse retrieval, microservice fault-injection benchmarks, knowledge graphs from incidents, and duplicate-bug-report retrieval — each marked VERIFIED, with the few precision caveats flagged explicitly.

---

## Key Findings

1. **The retrieval/embedding/agent stack (items 1–11) is fully verifiable.** Every paper exists with a stable canonical record (ACL Anthology, ACM DL, NeurIPS/ICLR proceedings, or arXiv). Use the peer-reviewed venue as `booktitle`/`journal` where one exists (SBERT→EMNLP-IJCNLP; SPLADE→SIGIR; RRF→SIGIR; ReAct→ICLR; C-Pack→SIGIR; MPNet/MiniLM→NeurIPS; BM25→Foundations & Trends in IR). E5, Passage Re-ranking with BERT, and Qwen2.5 have no peer-reviewed venue and should be cited as arXiv preprints.

2. **"World of Logs" (xiao2026worldoflogs) is the one item I cannot verify.** No dataset, paper, or public archive named "World of Logs" describing a collection of Apache Jira issues for log/incident analysis could be found, and a 2026 publication date is implausible for a paper you are citing now. **Do not include this citation as written.** The real underlying corpus the paper is describing (a large public archive of Apache Jira issues) is the Montgomery et al. MSR 2022 dataset (whose Apache sub-corpus alone holds ~1 million issues), optionally combined with Loghub for system-log data. Treat any "World of Logs" naming as an unverified alias and replace it.

3. **`montgomery2025jira` is real but mis-dated.** It is Montgomery, Lüders & Maalej, *An Alternative Issue Tracking Dataset of Public Jira Repositories*, MSR **2022**, pp. 73–77, DOI 10.1145/3524842.3528486 (arXiv:2201.08368). The "38,642 resolved incidents across 24 Apache projects" in your paper is a plausible filtered subset of this dataset's Apache repository.

4. **One duplicate-paper trap in related work:** arXiv:2305.15778 ("Empowering Practical Root Cause Analysis…") and the EuroSys'24 RCACopilot paper ("Automatic Root Cause Analysis via Large Language Models for Cloud Incidents") are the **same work** at different stages. Cite only the EuroSys'24 version; do not list both as distinct references.

---

## Details

### Part A — The 13 requested references (verified BibTeX, IEEEtran-compatible)

```bibtex
@inproceedings{reimers2019sbert,
  author    = {Reimers, Nils and Gurevych, Iryna},
  title     = {Sentence-{BERT}: Sentence Embeddings using {Siamese} {BERT}-Networks},
  booktitle = {Proc. 2019 Conf. on Empirical Methods in Natural Language Processing
               and the 9th Int. Joint Conf. on Natural Language Processing (EMNLP-IJCNLP)},
  pages     = {3982--3992},
  year      = {2019},
  publisher = {Association for Computational Linguistics},
  doi       = {10.18653/v1/D19-1410}
}
% VERIFIED. arXiv:1908.10084. Hong Kong, China.

@inproceedings{wang2020minilm,
  author    = {Wang, Wenhui and Wei, Furu and Dong, Li and Bao, Hangbo and Yang, Nan and Zhou, Ming},
  title     = {{MiniLM}: Deep Self-Attention Distillation for Task-Agnostic Compression
               of Pre-Trained Transformers},
  booktitle = {Advances in Neural Information Processing Systems 33 (NeurIPS 2020)},
  year      = {2020}
}
% VERIFIED. arXiv:2002.10957. Vol. 33, pp. 5776--5788. ACM DL 10.5555/3495724.3496209.

@article{robertson2009bm25,
  author  = {Robertson, Stephen and Zaragoza, Hugo},
  title   = {The Probabilistic Relevance Framework: {BM25} and Beyond},
  journal = {Foundations and Trends in Information Retrieval},
  volume  = {3},
  number  = {4},
  pages   = {333--389},
  year    = {2009},
  doi     = {10.1561/1500000019}
}
% VERIFIED. Now Publishers.

@inproceedings{formal2021splade,
  author    = {Formal, Thibault and Piwowarski, Benjamin and Clinchant, St\'ephane},
  title     = {{SPLADE}: Sparse Lexical and Expansion Model for First Stage Ranking},
  booktitle = {Proc. 44th Int. ACM SIGIR Conf. on Research and Development in
               Information Retrieval (SIGIR '21)},
  pages     = {2288--2292},
  year      = {2021},
  publisher = {ACM},
  doi       = {10.1145/3404835.3463098}
}
% VERIFIED. Optional companion: SPLADE v2, Formal, Lassance, Piwowarski, Clinchant,
% arXiv:2109.10086 (2021).

@inproceedings{cormack2009rrf,
  author    = {Cormack, Gordon V. and Clarke, Charles L. A. and B\"uttcher, Stefan},
  title     = {Reciprocal Rank Fusion Outperforms {Condorcet} and Individual Rank Learning Methods},
  booktitle = {Proc. 32nd Int. ACM SIGIR Conf. on Research and Development in
               Information Retrieval (SIGIR '09)},
  pages     = {758--759},
  year      = {2009},
  publisher = {ACM},
  doi       = {10.1145/1571941.1572114}
}
% VERIFIED. Boston, MA.

@inproceedings{yao2023react,
  author    = {Yao, Shunyu and Zhao, Jeffrey and Yu, Dian and Du, Nan and
               Shafran, Izhak and Narasimhan, Karthik and Cao, Yuan},
  title     = {{ReAct}: Synergizing Reasoning and Acting in Language Models},
  booktitle = {Int. Conf. on Learning Representations (ICLR)},
  year      = {2023}
}
% VERIFIED. arXiv:2210.03629. ICLR 2023 (notable-top-5%).

@inproceedings{xiao2024cpack,
  author    = {Xiao, Shitao and Liu, Zheng and Zhang, Peitian and
               Muennighoff, Niklas and Lian, Defu and Nie, Jian-Yun},
  title     = {{C-Pack}: Packed Resources For General {Chinese} Embeddings},
  booktitle = {Proc. 47th Int. ACM SIGIR Conf. on Research and Development in
               Information Retrieval (SIGIR '24)},
  pages     = {641--649},
  year      = {2024},
  publisher = {ACM},
  doi       = {10.1145/3626772.3657878}
}
% VERIFIED. arXiv:2309.07597. This is the canonical reference for the BGE embeddings.

@article{wang2022e5,
  author  = {Wang, Liang and Yang, Nan and Huang, Xiaolong and Jiao, Binxing and
             Yang, Linjun and Jiang, Daxin and Majumder, Rangan and Wei, Furu},
  title   = {Text Embeddings by Weakly-Supervised Contrastive Pre-training},
  journal = {arXiv preprint arXiv:2212.03533},
  year    = {2022}
}
% VERIFIED. The E5 paper. No peer-reviewed venue; cite as arXiv.

@inproceedings{song2020mpnet,
  author    = {Song, Kaitao and Tan, Xu and Qin, Tao and Lu, Jianfeng and Liu, Tie-Yan},
  title     = {{MPNet}: Masked and Permuted Pre-training for Language Understanding},
  booktitle = {Advances in Neural Information Processing Systems 33 (NeurIPS 2020)},
  year      = {2020}
}
% VERIFIED. arXiv:2004.09297.

@article{nogueira2019passage,
  author  = {Nogueira, Rodrigo and Cho, Kyunghyun},
  title   = {Passage Re-ranking with {BERT}},
  journal = {arXiv preprint arXiv:1901.04085},
  year    = {2019}
}
% VERIFIED. The canonical cross-encoder passage re-ranking reference. No formal venue.

@misc{qwen2025,
  author = {{Qwen Team} and Yang, An and Yang, Baosong and Zhang, Beichen and
            Hui, Binyuan and Zheng, Bo and Yu, Bowen and others},
  title  = {{Qwen2.5} Technical Report},
  year   = {2024},
  eprint = {2412.15115},
  archivePrefix = {arXiv},
  doi    = {10.48550/arXiv.2412.15115}
}
% VERIFIED. arXiv:2412.15115 (submitted Dec 2024; v2 Jan 2025). Key is fine; year 2024 on v1.
```

**Item 12 — "World of Logs" (`xiao2026worldoflogs`): UNVERIFIED — do NOT cite as written.**
No dataset or paper named "World of Logs" describing a public archive of Apache Jira issues could be located, and the 2026 date is not citable today. The most likely real underlying sources are:
- **Montgomery et al. MSR 2022** (the Apache Jira issues — see item 13), and/or
- **Loghub** for system-log data: Jieming Zhu, Shilin He, Pinjia He, Jinyang Liu, Michael R. Lyu, *Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics*, ISSRE 2023 (arXiv:2008.06448). VERIFIED.

```bibtex
@inproceedings{zhu2023loghub,
  author    = {Zhu, Jieming and He, Shilin and He, Pinjia and Liu, Jinyang and Lyu, Michael R.},
  title     = {Loghub: A Large Collection of System Log Datasets for {AI}-driven Log Analytics},
  booktitle = {2023 IEEE 34th Int. Symp. on Software Reliability Engineering (ISSRE)},
  year      = {2023},
  publisher = {IEEE}
}
% VERIFIED. arXiv:2008.06448. Loghub provides 19 real-world log datasets.
```

**Item 13 — Apache Jira issues dataset (`montgomery2025jira`): VERIFIED, but correct year is 2022.**
```bibtex
@inproceedings{montgomery2022jira,
  author    = {Montgomery, Lloyd and L\"uders, Clara and Maalej, Walid},
  title     = {An Alternative Issue Tracking Dataset of Public {Jira} Repositories},
  booktitle = {Proc. 19th Int. Conf. on Mining Software Repositories (MSR '22)},
  pages     = {73--77},
  year      = {2022},
  publisher = {ACM},
  doi       = {10.1145/3524842.3528486}
}
% VERIFIED. arXiv:2201.08368. The authors "release a dataset of 16 public Jiras with
% 1822 projects, spanning 2.7 million issues with a combined total of 32 million changes,
% 9 million comments, and 1 million issue links"; "Apache is the largest repository with
% 1 million issues." Your 38,642 resolved incidents across 24 Apache projects is a
% plausible filtered subset. If you prefer to keep the placeholder key, rename to
% montgomery2022jira to reflect the true year.
```
A related 2025 publication by the same authors exists — Montgomery, Lüders, Maalej, *Mining Issue Trackers: Concepts and Techniques*, in *Handbook on Natural Language Processing for Requirements Engineering*, Springer, 2025, DOI 10.1007/978-3-031-73143-3_11 (pp. 309–336) — which could be what "2025" referred to, but it is a book chapter, not the dataset paper. For the dataset itself, cite the 2022 MSR paper.

### Part B — Verified additional related-work references (BibTeX)

```bibtex
% ---- A. AIOps surveys & empirical incident studies ----
@article{he2021survey,
  author  = {He, Shilin and He, Pinjia and Chen, Zhuangbin and Yang, Tianyi and Su, Yuxin and Lyu, Michael R.},
  title   = {A Survey on Automated Log Analysis for Reliability Engineering},
  journal = {ACM Computing Surveys},
  volume  = {54}, number = {6}, articleno = {130}, numpages = {37},
  year    = {2021}, doi = {10.1145/3460345}
}  % VERIFIED.

@inproceedings{ghosh2022incidents,
  author    = {Ghosh, Supriyo and Shetty, Manish and Bansal, Chetan and Nath, Suman},
  title     = {How to Fight Production Incidents? An Empirical Study on a Large-Scale Cloud Service},
  booktitle = {Proc. 13th Symp. on Cloud Computing (SoCC '22)},
  pages     = {126--141}, year = {2022}, publisher = {ACM},
  doi       = {10.1145/3542929.3563482}
}  % VERIFIED. Best-paper; based on Microsoft Teams incidents.

@inproceedings{chen2019triage,
  author    = {Chen, Junjie and He, Xiaoting and Lin, Qingwei and Zhang, Hongyu and
               Hao, Dan and Gao, Feng and Xu, Zhangwei and Dang, Yingnong and Zhang, Dongmei},
  title     = {Continuous Incident Triage for Large-Scale Online Service Systems},
  booktitle = {2019 34th IEEE/ACM Int. Conf. on Automated Software Engineering (ASE)},
  pages     = {364--375}, year = {2019}, publisher = {IEEE},
  doi       = {10.1109/ASE.2019.00042}
}  % VERIFIED (system "DeepCT"). Double-check middle-author order on IEEE Xplore doc 8952483 if precision critical.

% ---- B. LLM-based incident management / RCA ----
@inproceedings{ahmed2023rootcause,
  author    = {Ahmed, Toufique and Ghosh, Supriyo and Bansal, Chetan and
               Zimmermann, Thomas and Zhang, Xuchao and Rajmohan, Saravan},
  title     = {Recommending Root-Cause and Mitigation Steps for Cloud Incidents using Large Language Models},
  booktitle = {2023 IEEE/ACM 45th Int. Conf. on Software Engineering (ICSE)},
  pages     = {1737--1749}, year = {2023}, publisher = {IEEE},
  doi       = {10.1109/ICSE48619.2023.00149}
}  % VERIFIED. arXiv:2301.03797. First large-scale study (>40,000 incidents).

@inproceedings{chen2024rcacopilot,
  author    = {Chen, Yinfang and Xie, Huaibing and Ma, Minghua and Kang, Yu and Gao, Xin and
               Shi, Liu and Cao, Yunjie and Gao, Xuedong and Fan, Hao and Wen, Ming and
               Zeng, Jun and Ghosh, Supriyo and Zhang, Xuchao and Zhang, Chaoyun and
               Lin, Qingwei and Rajmohan, Saravan and Zhang, Dongmei and Xu, Tianyin},
  title     = {Automatic Root Cause Analysis via Large Language Models for Cloud Incidents},
  booktitle = {Proc. Nineteenth European Conf. on Computer Systems (EuroSys '24)},
  pages     = {674--688}, year = {2024}, publisher = {ACM},
  doi       = {10.1145/3627703.3629553}
}  % VERIFIED (RCACopilot). NOTE: arXiv:2305.15778 is the SAME paper — do not double-cite.

@article{zhou2024dbot,
  author  = {Zhou, Xuanhe and Li, Guoliang and Sun, Zhaoyan and Liu, Zhiyuan and Chen, Weize and
             Wu, Jianming and Liu, Jiesi and Feng, Ruohang and Zeng, Guoyang},
  title   = {{D-Bot}: Database Diagnosis System using Large Language Models},
  journal = {Proceedings of the VLDB Endowment},
  volume  = {17}, number = {10}, pages = {2514--2527}, year = {2024},
  doi     = {10.14778/3675034.3675043}
}  % VERIFIED. arXiv:2312.01454. ("LLM as DBA," arXiv:2308.05481, is a SEPARATE earlier preprint.)

@inproceedings{chen2025aiopslab,
  author    = {Chen, Yinfang and Shetty, Manish and Somashekar, Gagan and Ma, Minghua and
               Simmhan, Yogesh and Mace, Jonathan and Bansal, Chetan and Wang, Rujia and Rajmohan, Saravan},
  title     = {{AIOpsLab}: A Holistic Framework to Evaluate AI Agents for Enabling Autonomous Clouds},
  booktitle = {Proceedings of Machine Learning and Systems 7 (MLSys 2025)},
  year      = {2025}
}  % VERIFIED. arXiv:2501.06706.

% ---- C/D. Log anomaly detection, parsing, RCA inputs ----
@inproceedings{du2017deeplog,
  author    = {Du, Min and Li, Feifei and Zheng, Guineng and Srikumar, Vivek},
  title     = {{DeepLog}: Anomaly Detection and Diagnosis from System Logs through Deep Learning},
  booktitle = {Proc. 2017 ACM SIGSAC Conf. on Computer and Communications Security (CCS '17)},
  pages     = {1285--1298}, year = {2017}, publisher = {ACM},
  doi       = {10.1145/3133956.3134015}
}  % VERIFIED.

@inproceedings{meng2019loganomaly,
  author    = {Meng, Weibin and Liu, Ying and Zhu, Yichen and Zhang, Shenglin and Pei, Dan and
               Liu, Yuqing and Chen, Yihao and Zhang, Ruizhi and Tao, Shimin and Sun, Pei and Zhou, Rong},
  title     = {{LogAnomaly}: Unsupervised Detection of Sequential and Quantitative Anomalies in Unstructured Logs},
  booktitle = {Proc. 28th Int. Joint Conf. on Artificial Intelligence (IJCAI-19)},
  pages     = {4739--4745}, year = {2019}, doi = {10.24963/ijcai.2019/658}
}  % VERIFIED.

@inproceedings{guo2021logbert,
  author    = {Guo, Haixuan and Yuan, Shuhan and Wu, Xintao},
  title     = {{LogBERT}: Log Anomaly Detection via {BERT}},
  booktitle = {2021 Int. Joint Conf. on Neural Networks (IJCNN)},
  pages     = {1--8}, year = {2021}, publisher = {IEEE},
  doi       = {10.1109/IJCNN52387.2021.9534113}
}  % VERIFIED. arXiv:2103.04475.

@inproceedings{he2017drain,
  author    = {He, Pinjia and Zhu, Jieming and Zheng, Zibin and Lyu, Michael R.},
  title     = {Drain: An Online Log Parsing Approach with Fixed Depth Tree},
  booktitle = {2017 IEEE Int. Conf. on Web Services (ICWS)},
  pages     = {33--40}, year = {2017}, publisher = {IEEE},
  doi       = {10.1109/ICWS.2017.13}
}  % VERIFIED.

@inproceedings{zhu2019logparsing,
  author    = {Zhu, Jieming and He, Shilin and Liu, Jinyang and He, Pinjia and
               Xie, Qi and Zheng, Zibin and Lyu, Michael R.},
  title     = {Tools and Benchmarks for Automated Log Parsing},
  booktitle = {2019 IEEE/ACM 41st Int. Conf. on Software Engineering: Software Engineering in Practice (ICSE-SEIP)},
  pages     = {121--130}, year = {2019}, publisher = {IEEE},
  doi       = {10.1109/ICSE-SEIP.2019.00021}
}  % VERIFIED.

@inproceedings{he2016experience,
  author    = {He, Shilin and Zhu, Jieming and He, Pinjia and Lyu, Michael R.},
  title     = {Experience Report: System Log Analysis for Anomaly Detection},
  booktitle = {2016 IEEE 27th Int. Symp. on Software Reliability Engineering (ISSRE)},
  pages     = {207--218}, year = {2016}, publisher = {IEEE},
  doi       = {10.1109/ISSRE.2016.21}
}  % VERIFIED.

% ---- E. RAG & dense/sparse retrieval foundations ----
@inproceedings{lewis2020rag,
  author    = {Lewis, Patrick and Perez, Ethan and Piktus, Aleksandra and Petroni, Fabio and
               Karpukhin, Vladimir and Goyal, Naman and K\"uttler, Heinrich and Lewis, Mike and
               Yih, Wen-tau and Rockt\"aschel, Tim and Riedel, Sebastian and Kiela, Douwe},
  title     = {Retrieval-Augmented Generation for Knowledge-Intensive {NLP} Tasks},
  booktitle = {Advances in Neural Information Processing Systems 33 (NeurIPS 2020)},
  pages     = {9459--9474}, year = {2020}
}  % VERIFIED.

@inproceedings{karpukhin2020dpr,
  author    = {Karpukhin, Vladimir and O\u{g}uz, Barlas and Min, Sewon and Lewis, Patrick and
               Wu, Ledell and Edunov, Sergey and Chen, Danqi and Yih, Wen-tau},
  title     = {Dense Passage Retrieval for Open-Domain Question Answering},
  booktitle = {Proc. 2020 Conf. on Empirical Methods in Natural Language Processing (EMNLP)},
  pages     = {6769--6781}, year = {2020}, publisher = {Association for Computational Linguistics},
  doi       = {10.18653/v1/2020.emnlp-main.550}
}  % VERIFIED. arXiv:2004.04906.

% ---- F. Knowledge graphs from incidents ----
@article{shetty2022softner,
  author  = {Shetty, Manish and Bansal, Chetan and Kumar, Sumit and Rao, Nikitha and
             Nagappan, Nachiappan and Zimmermann, Thomas},
  title   = {{SoftNER}: Mining Knowledge Graphs from Cloud Incidents},
  journal = {Empirical Software Engineering},
  volume  = {27}, articleno = {93}, year = {2022},
  doi     = {10.1007/s10664-022-10159-w}
}  % VERIFIED. arXiv:2101.05961. Conference precursor: "Neural Knowledge Extraction from
   % Cloud Service Incidents," ICSE-SEIP 2021, pp. 218--227 (arXiv:2007.05505).

% ---- G. Microservice benchmark apps / fault injection (software; cite official repos) ----
@misc{googleboutique,
  author = {{Google Cloud Platform}},
  title  = {Online Boutique (microservices-demo): A Cloud-First Microservices Demo Application},
  howpublished = {\url{https://github.com/GoogleCloudPlatform/microservices-demo}}, year = {2024}
}  % VERIFIED as software; formerly "Hipster Shop." No peer-reviewed paper exists.

@misc{oteldemo,
  author = {{OpenTelemetry Authors}},
  title  = {OpenTelemetry Demo (Astronomy Shop)},
  howpublished = {\url{https://github.com/open-telemetry/opentelemetry-demo}}, year = {2024}
}  % VERIFIED as software/docs (https://opentelemetry.io/docs/demo/). No peer-reviewed paper.

@misc{chaosmesh,
  author = {{Chaos Mesh Authors (CNCF)}},
  title  = {Chaos Mesh: A Chaos Engineering Platform for {Kubernetes}},
  howpublished = {\url{https://github.com/chaos-mesh/chaos-mesh}}, year = {2024}
}  % VERIFIED as CNCF project (Incubating since 2022). No canonical peer-reviewed paper.

% ---- H. Duplicate / similar bug report retrieval ----
@inproceedings{runeson2007duplicate,
  author    = {Runeson, Per and Alexandersson, Magnus and Nyholm, Oskar},
  title     = {Detection of Duplicate Defect Reports Using Natural Language Processing},
  booktitle = {29th Int. Conf. on Software Engineering (ICSE'07)},
  pages     = {499--510}, year = {2007}, publisher = {IEEE},
  doi       = {10.1109/ICSE.2007.32}
}  % VERIFIED. Case study at Sony-Ericsson Mobile Communications.

@inproceedings{sun2010duplicate,
  author    = {Sun, Chengnian and Lo, David and Wang, Xiaoyin and Jiang, Jing and Khoo, Siau-Cheng},
  title     = {A Discriminative Model Approach for Accurate Duplicate Bug Report Retrieval},
  booktitle = {Proc. 32nd ACM/IEEE Int. Conf. on Software Engineering (ICSE '10), Vol. 1},
  pages     = {45--54}, year = {2010}, publisher = {ACM},
  doi       = {10.1145/1806799.1806811}
}  % VERIFIED.

@inproceedings{he2020dccnn,
  author    = {He, Jianjun and Xu, Ling and Yan, Meng and Xia, Xin and Lei, Yan},
  title     = {Duplicate Bug Report Detection Using Dual-Channel Convolutional Neural Networks},
  booktitle = {Proc. 28th Int. Conf. on Program Comprehension (ICPC '20)},
  pages     = {117--127}, year = {2020}, publisher = {ACM},
  doi       = {10.1145/3387904.3389263}
}  % VERIFIED (recent DL baseline). Confirm exact pages/DOI on ACM DL before camera-ready.
```

### Part C — Related Work section (drop-in prose)

> **Incident management and AIOps.** Modern cloud and microservice operations generate incident volumes that overwhelm manual on-call triage, motivating a large body of AIOps research surveyed by He et al. [he2021survey]. Empirical studies characterize the human cost of this process: Ghosh et al. [ghosh2022incidents] analyze a large-scale Microsoft Teams deployment and document the long detection-to-mitigation pipeline that motivates automation, while Chen et al. [chen2019triage] frame *continuous incident triage* as a learning problem for routing incidents to the correct team. Remedy targets the same triage bottleneck but reframes it as retrieval against a memory of resolved incidents rather than classification.
>
> **LLMs for incident diagnosis.** Recent work applies large language models to root-causing and mitigation. Ahmed et al. [ahmed2023rootcause] perform the first large-scale study (over 40,000 incidents) of LLMs recommending root-cause and mitigation steps; RCACopilot [chen2024rcacopilot] couples diagnostic-data collection with LLM reasoning and matches incoming incidents to handlers by alert type; and D-Bot [zhou2024dbot] diagnoses database faults with LLM agents. AIOpsLab [chen2025aiopslab] provides a holistic framework for evaluating such agents in autonomous-cloud settings. Remedy differs by introducing a *capability-gated controller* that runs only the reasoning steps the available evidence supports, degrading gracefully from full telemetry to text-only inputs, and by suppressing duplicate evidence pages within an incident.
>
> **Log analysis and anomaly detection.** A complementary line of work mines telemetry directly. Drain [he2017drain] parses unstructured logs into templates; DeepLog [du2017deeplog], LogAnomaly [meng2019loganomaly], and LogBERT [guo2021logbert] detect sequential and semantic anomalies; and benchmark resources such as the log-parsing toolkit [zhu2019logparsing], the foundational anomaly-detection experience report [he2016experience], and the Loghub collection [zhu2023loghub] standardize evaluation. Remedy consumes parsed telemetry as one capability tier but does not depend on it, retaining text-only operation when traces and metrics are unavailable.
>
> **Retrieval and retrieval-augmented reasoning.** Remedy's retriever fuses dense, sparse, and graph signals. Dense bi-encoders build on Sentence-BERT [reimers2019sbert] and its backbones MiniLM [wang2020minilm] and MPNet [song2020mpnet], with general-purpose embedding families E5 [wang2022e5] and BGE/C-Pack [xiao2024cpack]; sparse retrieval uses BM25 [robertson2009bm25] and the learned-sparse SPLADE [formal2021splade]; cross-encoder re-ranking follows Nogueira and Cho [nogueira2019passage]; and we combine ranked lists with Reciprocal Rank Fusion [cormack2009rrf]. Dense Passage Retrieval [karpukhin2020dpr] and Retrieval-Augmented Generation [lewis2020rag] established the retrieve-then-reason paradigm, and ReAct [yao2023react] interleaves reasoning with tool actions; Remedy's ReAct-style evidence-gathering loop and its underlying Qwen2.5 LLM [qwen2025] inherit this lineage.
>
> **Knowledge graphs and duplicate-incident retrieval.** Building knowledge graphs from incidents/tickets supports structured retrieval and RCA; SoftNER [shetty2022softner] mines such graphs from cloud incidents, informing Remedy's knowledge-graph retriever. Remedy's "retrieve the most similar past incident" framing also descends directly from duplicate/similar bug-report retrieval: Runeson et al. [runeson2007duplicate] pioneered NLP-based duplicate-defect detection — reporting recall on the order of 30–42% on a Sony-Ericsson repository for suggested-list sizes of 5–15 — Sun et al. [sun2010duplicate] introduced a discriminative retrieval model, and recent deep-learning approaches such as dual-channel CNNs [he2020dccnn] improve matching. Remedy extends this idea from bug reports to operational incidents and adds telemetry-aware, capability-gated retrieval.
>
> **Benchmark systems.** Our two collected microservice-telemetry datasets are built on Google's Online Boutique [googleboutique] and the OpenTelemetry Demo / Astronomy Shop [oteldemo] under controlled fault injection using Chaos Mesh [chaosmesh]; our real-world corpus comprises 38,642 resolved Apache Jira incidents across 24 projects drawn from the public Jira dataset of Montgomery et al. [montgomery2022jira].

### Part D — In-text citation placement guidance

- **Abstract / Introduction (problem framing):** cite `he2021survey`, `ghosh2022incidents`, `chen2019triage` when stating that incident triage is a costly, high-volume operations bottleneck. Cite `ahmed2023rootcause` and `chen2024rcacopilot` as the closest LLM-based prior art you improve upon.
- **Method — retriever subsection:** place `reimers2019sbert`, `wang2020minilm`, `song2020mpnet`, `wang2022e5`, `xiao2024cpack` at first mention of the **dense** retriever; `robertson2009bm25` and `formal2021splade` at the **lexical/sparse** retriever; `nogueira2019passage` where you describe cross-encoder re-ranking; and `cormack2009rrf` at the exact sentence describing reciprocal-rank fusion of the three retrievers.
- **Method — controller / agent loop:** cite `yao2023react` at the first description of the ReAct-style evidence-gathering loop, and `qwen2025` at first mention of the underlying LLM. Cite `lewis2020rag` and `karpukhin2020dpr` once when positioning Remedy within the retrieve-then-reason paradigm (Introduction or Related Work, not both).
- **Method — knowledge-graph retriever:** cite `shetty2022softner` where you describe constructing/using a KG over incidents.
- **Telemetry / capability tiers:** cite `he2017drain` at log-parsing; `du2017deeplog`, `meng2019loganomaly`, `guo2021logbert` where you contrast with anomaly-detection approaches; `zhu2019logparsing`, `he2016experience`, `zhu2023loghub` for benchmark/resource grounding.
- **Framing the core retrieval task:** cite `runeson2007duplicate`, `sun2010duplicate`, and `he2020dccnn` at the sentence explaining that "retrieve the most similar past incident" generalizes duplicate-bug-report retrieval.
- **Experimental setup:** cite `googleboutique` and `oteldemo` at first mention of each benchmark application; `chaosmesh` where you describe fault injection; `montgomery2022jira` (and optionally `zhu2023loghub`) where you introduce the Apache Jira corpus and its size.

---

## Recommendations

1. **Adopt the Part A and Part B BibTeX as-is.** All keys are IEEEtran-compatible. Confirm only two precision points at camera-ready: the middle-author ordering of `chen2019triage` (IEEE Xplore doc 8952483) and the exact pages/DOI of `he2020dccnn` on ACM DL. Everything else is verified against canonical records.
2. **Remove `xiao2026worldoflogs` entirely.** Replace every in-text "World of Logs" reference with `montgomery2022jira` for the Jira incident corpus and, if you cite system logs, with `zhu2023loghub`. If a co-author insists "World of Logs" is a real internal/derived collection, it must be backed by a real, datable artifact (a Zenodo/Figshare DOI or a published paper) before inclusion — do not ship an unverifiable 2026 citation in an ICSE submission.
3. **Fix the year on the Jira dataset key** from 2025 to 2022 (rename `montgomery2025jira` → `montgomery2022jira`) and verify that your "38,642 incidents / 24 projects" figure is a documented filtered subset of the Apache repository in that dataset; state the filtering criteria in your data section so reviewers can reproduce it.
4. **Avoid the RCACopilot double-citation.** Cite only `chen2024rcacopilot` (EuroSys'24); do not also cite arXiv:2305.15778 as a separate work.
5. **For the three software benchmarks** (Online Boutique, OpenTelemetry Demo, Chaos Mesh), cite official repos/docs as `@misc` with an access date; none has a peer-reviewed paper, and reviewers will accept repository citations for these widely-used artifacts.
6. **Decision threshold for adding more related work:** if a reviewer asks for stronger positioning against agentic RCA, add D-Bot (`zhou2024dbot`) and AIOpsLab (`chen2025aiopslab`) — both verified — rather than searching for newer, less-established preprints.

## Caveats
- **Unverifiable:** "World of Logs" (`xiao2026worldoflogs`). Treated as not real until a concrete artifact (DOI/repo/paper) is produced. Do not cite.
- **Mis-dated placeholder:** `montgomery2025jira` is the MSR **2022** dataset paper; a separate 2025 Springer book chapter by the same authors exists but is not the dataset.
- **Naming nuance:** `xiao2024cpack` is by Shitao Xiao (BGE/C-Pack) and is entirely unrelated to logs — do not conflate its author with the fictitious "Xiao 2026 World of Logs."
- **No peer-reviewed venue (cite as arXiv/misc):** E5 (`wang2022e5`), Passage Re-ranking with BERT (`nogueira2019passage`), Qwen2.5 (`qwen2025`), and the three benchmark software artifacts.
- **Precision to re-confirm at camera-ready:** middle-author order of `chen2019triage`; exact pages/DOI of `he2020dccnn`. Both papers definitely exist; only the fine-grained metadata warrants a final check.
- **Qwen2.5 year:** arXiv v1 is December 2024 (v2 January 2025). The key `qwen2025` is fine, but set `year = {2024}` for the v1 date or `{2025}` consistently — just be internally consistent across the bibliography.
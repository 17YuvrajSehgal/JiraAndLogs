"""Neural models for incident triage + retrieval.

Two pipelines live here:

  TabTransformerPipeline   — small Transformer over the 94 production-safe
                             numeric features. Drop-in replacement for HGB
                             on the binary triage task. Goal: see whether a
                             modern tabular Transformer beats gradient boosting
                             on telemetry features alone (charter §4 non-claim
                             #2 says it shouldn't — but reviewers ask).

  BiEncoderRetrievalPipeline — fine-tuned bi-encoder (sentence-transformers,
                             MiniLM-L6-v2 backbone) trained on
                             (window_text, gold_ticket_text) positives with
                             in-batch hard negatives. Cheaper-to-serve
                             alternative to the cross-encoder reranker:
                             documents embed once, queries embed at predict
                             time, top-K via ANN.

Both pipelines plug into the existing comparison harness in
src/comparison/runner.py via the standard PipelineRunner ABC, so the
training-run registry and bootstrap CI infrastructure work without
modification.
"""

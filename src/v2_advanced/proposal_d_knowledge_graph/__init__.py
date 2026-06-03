"""Proposal D — LLM-extracted knowledge graph in Neo4j.

Pipeline:
    extractor.py            LLM-based entity/relation extractor (calls LM Studio)
    schema.py               graph schema definitions
    loader.py               builds the graph in Neo4j from extracted JSON
    graph_retriever.py      Cypher-based retriever skill
    pipeline.py             full PipelineRunner that uses graph retrieval

We extract structured facts from each Jira ticket using a local LLM
running in LM Studio, store them as a Neo4j graph, and at query time
extract the same structure from the live window's evidence and
traverse the graph for compatible incidents.

The graph traversal is interpretable: every match has a human-readable
explanation ("shared service: cartservice; shared error class:
DeadlineExceeded; symptom overlap: 2/3").
"""

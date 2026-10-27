"""The eval's read_document backend replays the dataset's whole documents (ticket 20 #1).

FixtureDocuments must serve what ChunkInspectionService serves: chunks by index from a
start, whole, and by page none for the lab documents, which are txt/md without pages.
"""
from __future__ import annotations

from scripts.agent_eval import DATASET_DIR, FixtureDocuments, load_dataset


def test_reads_replay_documents_jsonl_whole_and_a_pageless_document_has_no_page():
    dataset = load_dataset(DATASET_DIR)
    documents = FixtureDocuments(dataset.documents)
    document_id, document = next(iter(dataset.documents.items()))

    read = documents.read_chunks(document_id, 1, 2)
    assert read["total_chunks"] == len(document["chunks"]) and read["filename"] == document["filename"]
    assert [c["content"] for c in read["chunks"]] == [c["content"] for c in document["chunks"][1:3]]
    assert documents.read_chunks(document_id, len(document["chunks"]), 2)["chunks"] == []
    assert documents.chunks_on_page(document_id, 1, 3)["chunks"] == [], "txt/md carry no page"
    assert documents.read_chunks("doc_khong_co", 0, 2) is None


def test_every_recorded_handle_opens_the_chunk_it_was_recorded_from():
    dataset = load_dataset(DATASET_DIR)
    documents = FixtureDocuments(dataset.documents)
    handles = [(c["document_id"], c["chunk_index"], c["content"]) for f in dataset.retrieval.values() for c in f["chunks"] if "document_id" in c]

    assert handles, "v0.3 records handles"
    for document_id, index, content in handles:
        assert documents.read_chunks(document_id, index, 1)["chunks"][0]["content"] == content

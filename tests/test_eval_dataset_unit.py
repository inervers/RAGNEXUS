import json

import pytest

import eval_dataset


CATEGORY_COUNTS = {
    "exact": 10,
    "semantic": 8,
    "troubleshooting": 8,
    "multidoc": 6,
    "version_conflict": 4,
    "unanswerable": 4,
}


def _positive(question_id, category, split="development"):
    return {
        "id": question_id,
        "category": category,
        "split": split,
        "difficulty": "medium",
        "question": f"question {question_id}",
        "should_abstain": False,
        "relevant_doc_ids": ["doc:v1"],
        "relevant_chunk_ids": ["doc:v1#chunk-a"],
        "answer_key_points": ["fact grounded by chunk-a"],
        "reference_answer": "answer grounded by chunk-a",
        "source_versions": ["doc:v1@commit-a"],
    }


def _unanswerable(question_id, split="development"):
    item = _positive(question_id, "unanswerable", split)
    item.update(
        should_abstain=True,
        relevant_doc_ids=[],
        relevant_chunk_ids=[],
        answer_key_points=[],
        reference_answer="",
        source_versions=[],
    )
    return item


def _valid_dataset():
    questions = []
    sequence = 0
    dev_counts = {
        "exact": 6,
        "semantic": 5,
        "troubleshooting": 5,
        "multidoc": 4,
        "version_conflict": 2,
        "unanswerable": 2,
    }
    for category, total in CATEGORY_COUNTS.items():
        for index in range(total):
            sequence += 1
            split = "development" if index < dev_counts[category] else "heldout"
            question_id = f"q-{sequence:03d}"
            item = (
                _unanswerable(question_id, split)
                if category == "unanswerable"
                else _positive(question_id, category, split)
            )
            questions.append(item)
    return {
        "meta": {
            "name": "fixture",
            "schema_version": 2,
            "corpus_manifest_sha256": "a" * 64,
            "frozen_at": "2026-08-10",
            "usage_policy": "development for tuning; heldout after freeze",
        },
        "questions": questions,
    }


def _manifest():
    return {
        "documents": [
            {
                "doc_id": "doc:v1",
                "commit": "commit-a",
                "chunk_ids": ["doc:v1#chunk-a", "doc:v1#chunk-b"],
            }
        ]
    }


def test_validate_accepts_exact_40_question_contract():
    dataset = _valid_dataset()

    assert eval_dataset.validate_eval_set(dataset, _manifest()) is dataset


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data["questions"].pop(), "40"),
        (
            lambda data: data["questions"][0].update(id=data["questions"][1]["id"]),
            "unique",
        ),
        (
            lambda data: data["questions"][0].update(category="semantic"),
            "category counts",
        ),
        (
            lambda data: data["questions"][0].update(split="heldout"),
            "split counts",
        ),
    ],
)
def test_validate_rejects_wrong_frozen_distribution(mutation, message):
    dataset = _valid_dataset()
    mutation(dataset)

    with pytest.raises(ValueError, match=message):
        eval_dataset.validate_eval_set(dataset, _manifest())


def test_validate_rejects_unknown_chunk_id():
    dataset = _valid_dataset()
    dataset["questions"][0]["relevant_chunk_ids"] = ["doc:v1#missing"]

    with pytest.raises(ValueError, match="unknown chunk"):
        eval_dataset.validate_eval_set(dataset, _manifest())


def test_validate_rejects_chunk_whose_doc_is_not_labeled_relevant():
    dataset = _valid_dataset()
    dataset["questions"][0]["relevant_doc_ids"] = ["other:v1"]

    with pytest.raises(ValueError, match="doc/chunk mismatch"):
        eval_dataset.validate_eval_set(dataset, _manifest())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("relevant_doc_ids", ["doc:v1"]),
        ("relevant_chunk_ids", ["doc:v1#chunk-a"]),
        ("answer_key_points", ["invented fact"]),
        ("reference_answer", "invented answer"),
        ("source_versions", ["invented:v1"]),
    ],
)
def test_unanswerable_rejects_fake_ground_truth(field, value):
    dataset = _valid_dataset()
    item = next(q for q in dataset["questions"] if q["category"] == "unanswerable")
    item[field] = value

    with pytest.raises(ValueError, match="unanswerable ground truth"):
        eval_dataset.validate_eval_set(dataset, _manifest())


def test_positive_question_requires_ground_truth():
    dataset = _valid_dataset()
    dataset["questions"][0]["answer_key_points"] = []

    with pytest.raises(ValueError, match="positive ground truth"):
        eval_dataset.validate_eval_set(dataset, _manifest())


def test_validate_rejects_source_version_not_in_manifest():
    dataset = _valid_dataset()
    dataset["questions"][0]["source_versions"] = ["doc:v1@wrong-commit"]

    with pytest.raises(ValueError, match="source_versions mismatch"):
        eval_dataset.validate_eval_set(dataset, _manifest())


def test_heldout_and_all_require_explicit_unlock():
    dataset = _valid_dataset()

    with pytest.raises(ValueError, match="--allow-heldout"):
        eval_dataset.select_questions(dataset, "heldout")
    with pytest.raises(ValueError, match="--allow-heldout"):
        eval_dataset.select_questions(dataset, "all")

    assert len(eval_dataset.select_questions(dataset, "development")) == 24
    assert len(eval_dataset.select_questions(dataset, "heldout", True)) == 16
    assert len(eval_dataset.select_questions(dataset, "all", True)) == 40


def test_load_and_validate_checks_manifest_hash(tmp_path):
    dataset = _valid_dataset()
    eval_path = tmp_path / "eval.json"
    manifest_path = tmp_path / "manifest.json"
    eval_path.write_text(json.dumps(dataset), encoding="utf-8")
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest SHA256"):
        eval_dataset.load_and_validate_eval_set(eval_path, manifest_path)

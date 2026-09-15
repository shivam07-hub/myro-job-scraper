from enricher import _ENRICH_PROMPT, _validate_enrichment


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"PASS  {label}")
        return
    raise AssertionError(f"FAIL  {label} {detail}")


def test_structured_skills() -> None:
    data = _validate_enrichment({
        "role_domain": "Software Engineering",
        "skills": [
            {"name": "Python", "required_level": 3},
            {"name": "SQL", "required_level": 9},          # invalid level → default 2
            {"name": "Communication"},                      # missing level → default 2
            {"name": "Not A Real Skill", "required_level": 4},  # off-taxonomy → dropped
            {"name": "Python", "required_level": 1},        # duplicate → dropped
        ],
    })

    check("role_domain kept", data["role_domain"] == "Software Engineering")
    check("invalid + duplicate dropped", len(data["skills"]) == 3, str(data["skills"]))
    check("no is_primary key on structured skills", all("is_primary" not in s for s in data["skills"]))
    check("canonical Python", data["skills"][0]["name"] == "Python (Programming Language)")
    check("level kept", data["skills"][0]["required_level"] == 3)
    check("invalid level defaults to 2", data["skills"][1]["required_level"] == 2)
    check("missing level defaults to 2", data["skills"][2]["required_level"] == 2)
    check("main_skills mirrors all names", data["main_skills"] == [
        "Python (Programming Language)", "SQL (Programming Language)", "Communication"])
    check("side_skills always empty", data["side_skills"] == [])


def test_legacy_arrays_flatten_to_one_bucket() -> None:
    data = _validate_enrichment({
        "role_domain": "Invented Domain",
        "main_skills": ["Machine Learning"],
        "side_skills": ["Leadership"],
    })

    check("invalid role_domain dropped", data["role_domain"] is None)
    check("legacy arrays flattened into one list", len(data["skills"]) == 2)
    check("side_skills stays empty after flatten", data["side_skills"] == [])
    check("main_skills holds both", data["main_skills"] == ["Machine Learning", "Leadership"])


def test_cap_at_ten() -> None:
    many = [{"name": n, "required_level": 2} for n in [
        "Python", "SQL", "Java", "JavaScript", "Communication", "Leadership",
        "Machine Learning", "Data Analysis", "Cloud Computing", "Robotics",
        "Docker", "Kubernetes",
    ]]
    data = _validate_enrichment({"role_domain": "Software Engineering", "skills": many})
    check("skills capped at 10", len(data["skills"]) <= 10, str(len(data["skills"])))


def test_prompt_is_one_bucket() -> None:
    check("prompt drops is_primary", "is_primary" not in _ENRICH_PROMPT)
    check("prompt states no must/nice split", "There is NO must-have vs nice-to-have" in _ENRICH_PROMPT)
    check("prompt allows fewer skills", "Return fewer skills if the JD does not clearly support them" in _ENRICH_PROMPT)


if __name__ == "__main__":
    test_structured_skills()
    test_legacy_arrays_flatten_to_one_bucket()
    test_cap_at_ten()
    test_prompt_is_one_bucket()

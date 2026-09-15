from company_skill_rollup import add_dormant_skill_facts, build_company_skill_facts


def test_rollup_counts_jobs_levels_domains_and_locations() -> None:
    facts = build_company_skill_facts(
        [
            {
                "job_id": "j1",
                "role_domain": "Engineering",
                "location_country": "India",
                "skills": [
                    {"name": "Python", "required_level": 3},
                    {"name": "SQL", "required_level": 2},
                ],
            },
            {
                "job_id": "j2",
                "role_domain": "Data",
                "location_country": "India",
                "skills": [{"name": "Python", "required_level": 4}],
            },
        ],
        skill_id_map={"Python": 1, "SQL": 2},
        source_run_id="run-1",
        company_id="company-1",
    )

    python = next(row for row in facts if row["skill_id"] == 1)
    assert python["active_job_count"] == 2
    assert python["primary_job_count"] == 2
    assert python["average_required_level"] == 3.5
    assert python["required_level_counts"] == {"3": 1, "4": 1}
    assert python["role_domain_counts"] == {"Engineering": 1, "Data": 1}
    assert python["location_counts"] == {"India": 2}
    assert python["observed_at"]


def test_rollup_ignores_unknown_taxonomy_skills_and_duplicate_job_skill() -> None:
    facts = build_company_skill_facts(
        [
            {
                "job_id": "j1",
                "skills": [
                    {"name": "Python", "required_level": 2},
                    {"name": "Python", "required_level": 4},
                    {"name": "Unknown", "required_level": 3},
                ],
            }
        ],
        skill_id_map={"Python": 1},
        source_run_id="run-1",
        company_id="company-1",
    )

    assert len(facts) == 1
    assert facts[0]["active_job_count"] == 1
    assert facts[0]["average_required_level"] == 4


def test_rollup_emits_zero_fact_when_previously_hired_skill_disappears() -> None:
    facts = add_dormant_skill_facts(
        [
            {
                "source_run_id": "run-2",
                "company_id": "company-1",
                "skill_id": 1,
                "active_job_count": 2,
            }
        ],
        known_skill_ids={1, 2},
        source_run_id="run-2",
        company_id="company-1",
    )

    dormant = next(row for row in facts if row["skill_id"] == 2)
    assert dormant["active_job_count"] == 0
    assert dormant["primary_job_count"] == 0
    assert dormant["average_required_level"] is None

"""
Rule Engine for SIH26092 — Scheme Matching
-------------------------------------------
Core idea: loop through every scheme in schemes.json, check whether the
applicant satisfies each scheme's conditions, keep the ones that pass,
then generate a plain-English reason for the top match.

No ML here on purpose — this is deterministic filtering + string templating.
"""

import json
from pathlib import Path

SCHEMES_PATH = Path(__file__).parent / "schemes.json"


def load_schemes():
    with open(SCHEMES_PATH, "r") as f:
        return json.load(f)


def passes_common_checks(applicant, scheme, data):
    """
    Checks that apply across most schemes: category match + income cap.
    Kept separate so we're not repeating this logic per scheme.
    """
    # Category check — applicant["category"] should be one of scheme's eligible_categories
    eligible_categories = scheme.get("eligible_categories", [])
    if eligible_categories and applicant["category"] not in eligible_categories:
        return False, f"category '{applicant['category']}' not eligible for this scheme"

    # Income check — every scheme in our data uses max_annual_family_income
    income_cap = scheme.get("max_annual_family_income")
    if income_cap is not None and applicant["annual_family_income"] > income_cap:
        return False, f"income ₹{applicant['annual_family_income']:,} exceeds cap of ₹{income_cap:,}"

    return True, None


def passes_project_loan_checks(applicant, scheme):
    """
    Project-cost-based schemes (MFS, Term Loan, Aajeevika, UNY, NBCFDC loans).
    Applicant needs to supply project_cost and requested loan_amount.

    Important: if a scheme defines a cost/loan cap but the applicant didn't
    supply the matching field, that's a FAIL, not a skip — otherwise an
    education-loan applicant with no project_cost would silently "pass"
    every business-loan scheme's cost check by default.
    """
    project_cost = applicant.get("project_cost")
    loan_amount = applicant.get("loan_amount")

    cost_min = scheme.get("project_cost_min", 0)
    cost_max = scheme.get("project_cost_max")
    if cost_max is not None:
        if project_cost is None:
            return False, "project cost not provided, required for this scheme"
        if not (cost_min <= project_cost <= cost_max):
            return False, f"project cost ₹{project_cost:,} outside scheme's ₹{cost_min:,}–₹{cost_max:,} range"

    loan_cap = scheme.get("loan_max")
    if loan_cap is not None:
        if loan_amount is None:
            return False, "loan amount not provided, required for this scheme"
        if loan_amount > loan_cap:
            return False, f"requested loan ₹{loan_amount:,} exceeds scheme's max of ₹{loan_cap:,}"

    return True, None


def passes_education_loan_checks(applicant, scheme):
    """
    Education Loan Scheme (ELS) uses course_fee instead of project_cost.
    """
    course_fee = applicant.get("course_fee")
    fee_cap = scheme.get("max_course_fee")
    if fee_cap is not None and course_fee is not None and course_fee > fee_cap:
        return False, f"course fee ₹{course_fee:,} exceeds scheme's cap of ₹{fee_cap:,}"

    if scheme["scheme_id"] == "NSFDC_ELS":
        eligible_courses = scheme.get("eligible_courses", [])
        if applicant.get("course") and eligible_courses and applicant["course"] not in eligible_courses:
            return False, f"course '{applicant['course']}' not in ELS's recognized course list"

    return True, None


def passes_group_loan_checks(applicant, scheme):
    """
    SHG/group loan schemes (NBCFDC_GROUP_SHG) don't have a flat 'loan_max' —
    they cap per-beneficiary and per-SHG amounts separately, plus SHG
    composition rules. This was previously falling through with no checks
    at all, which would have silently approved anyone.
    """
    loan_amount = applicant.get("loan_amount")
    per_beneficiary_cap = scheme.get("loan_max_per_beneficiary")
    if per_beneficiary_cap is not None and loan_amount is not None and loan_amount > per_beneficiary_cap:
        return False, f"requested loan ₹{loan_amount:,} exceeds per-beneficiary cap of ₹{per_beneficiary_cap:,}"

    shg_size = applicant.get("shg_size")
    max_members = scheme.get("shg_conditions", {}).get("max_members_per_shg")
    if shg_size is not None and max_members is not None and shg_size > max_members:
        return False, f"SHG size ({shg_size}) exceeds max of {max_members} members"

    return True, None


def check_eligibility(applicant, scheme, data):
    """
    Runs the right set of checks depending on scheme_type, and returns
    (is_eligible, reason_if_rejected).
    """
    ok, reason = passes_common_checks(applicant, scheme, data)
    if not ok:
        return False, reason

    scheme_type = scheme.get("scheme_type")
    if scheme_type == "education_loan":
        # Only consider education schemes if the applicant is actually
        # asking for one — otherwise a business-loan applicant with no
        # course_fee field would still "pass" this check by default.
        if applicant.get("purpose") != "education":
            return False, "applicant did not indicate an education loan purpose"
        return passes_education_loan_checks(applicant, scheme)
    elif scheme_type == "group_loan":
        return passes_group_loan_checks(applicant, scheme)
    else:
        # project_loan uses cost/amount range checks
        return passes_project_loan_checks(applicant, scheme)


def get_interest_rate(applicant, scheme):
    """
    Pulls the right interest rate for schemes where it varies by channel,
    loan size, or purpose (UNY, NBCFDC individual/group). Falls back to
    a flat rate field for simple schemes.
    """
    if "interest_rate_variants" in scheme:
        # e.g. UNY — pick by channel; default to first variant if not specified
        channel = applicant.get("channel")
        for variant in scheme["interest_rate_variants"]:
            if variant["channel"] == channel:
                return variant["beneficiary_percent"]
        return scheme["interest_rate_variants"][0]["beneficiary_percent"]

    if "interest_rate_tiers" in scheme:
        # e.g. NBCFDC individual loan — pick by purpose + loan amount
        loan_amount = applicant.get("loan_amount", 0)
        purpose = applicant.get("purpose", "income_generating")
        for tier in scheme["interest_rate_tiers"]:
            if tier["purpose"] != purpose:
                continue
            tier_min = tier.get("loan_min", 0)
            tier_max = tier.get("loan_max", float("inf"))
            if tier_min <= loan_amount <= tier_max:
                return tier["channel_to_beneficiary_percent"]

    if "channel_variants" in scheme:
        channel = applicant.get("channel", "SCA_or_Bank")
        for variant in scheme["channel_variants"]:
            if variant["channel"] == channel:
                return variant["channel_to_beneficiary_percent"]

    return scheme.get("interest_rate_beneficiary_percent")


def get_loan_cap(scheme):
    """Returns the relevant loan ceiling depending on scheme shape."""
    if scheme.get("scheme_type") == "group_loan":
        return scheme.get("loan_max_per_beneficiary")
    return scheme.get("loan_max") or scheme.get("max_course_fee")


def get_repayment_years(applicant, scheme):
    """Returns repayment period in years, pulling from whichever field shape this scheme uses."""
    if "repayment_period_months" in scheme:
        return round(scheme["repayment_period_months"] / 12, 1)

    if scheme.get("scheme_type") == "education_loan":
        started = applicant.get("repayment_started", False)
        months = scheme["repayment_period_months_started"] if started else scheme["repayment_period_months_not_started"]
        return round(months / 12, 1)

    if "interest_rate_tiers" in scheme:
        loan_amount = applicant.get("loan_amount", 0)
        purpose = applicant.get("purpose", "income_generating")
        for tier in scheme["interest_rate_tiers"]:
            if tier["purpose"] != purpose:
                continue
            tier_min = tier.get("loan_min", 0)
            tier_max = tier.get("loan_max", float("inf"))
            if tier_min <= loan_amount <= tier_max:
                return tier["repayment_years"]

    if "channel_variants" in scheme:
        channel = applicant.get("channel", "SCA_or_Bank")
        for variant in scheme["channel_variants"]:
            if variant["channel"] == channel:
                return variant.get("repayment_years")

    return None


def build_comparison(applicant, candidates):
    """
    The transparency layer: lays out every eligible scheme's key numbers
    side by side, so the ranking isn't a black box — the applicant (and
    the judges) can see exactly what was compared.
    """
    rows = []
    for s in candidates:
        rows.append({
            "scheme_id": s["scheme_id"],
            "name": s["name"],
            "interest_rate_percent": get_interest_rate(applicant, s),
            "loan_cap": get_loan_cap(s),
            "repayment_years": get_repayment_years(applicant, s),
        })
    return rows


def generate_comparison_note(applicant, top, runner_up):
    """
    Plain-English explanation of why the top scheme beat the runner-up
    specifically — not just 'this is the best', but 'here's the exact
    number that decided it'.
    """
    if runner_up is None:
        return f"{top['name']} was the only matching scheme for this applicant."

    top_rate = get_interest_rate(applicant, top)
    next_rate = get_interest_rate(applicant, runner_up)

    if top_rate != next_rate and top_rate is not None and next_rate is not None:
        diff = round(next_rate - top_rate, 2)
        return (f"{top['name']} ranked above {runner_up['name']} because its interest rate "
                f"({top_rate}% p.a.) is {diff} points lower than {runner_up['name']}'s ({next_rate}% p.a.).")

    if applicant.get("shg_size") is not None and top.get("scheme_type") == "group_loan":
        return (f"{top['name']} and {runner_up['name']} tie at {top_rate}% p.a., but {top['name']} was "
                f"prioritized since you applied as a self-help group (SHG size: {applicant['shg_size']}).")

    return f"{top['name']} and {runner_up['name']} tie at {top_rate}% p.a.; ranked by data order as a tiebreaker."


def generate_reason(applicant, scheme):
    """
    The 'why' string — this is what makes the demo look AI-driven.
    Literally states which conditions matched, in plain language.
    """
    rate = get_interest_rate(applicant, scheme)
    reasons = [
        f"Your annual family income (₹{applicant['annual_family_income']:,}) is within "
        f"the ₹{scheme['max_annual_family_income']:,} cap for {scheme['name']}.",
        f"You fall under the '{applicant['category']}' category, which this scheme covers.",
    ]
    if rate is not None:
        reasons.append(f"At the current rate of {rate}% p.a., this is one of the more affordable options available to you.")
    return " ".join(reasons)


def recommend(applicant):
    """
    Main entry point — call this from your /recommend endpoint.
    Returns top recommendation + alternates, each with a reasoning string.
    """
    data = load_schemes()
    candidates = []

    for scheme in data["schemes"]:
        is_eligible, _ = check_eligibility(applicant, scheme, data)
        if is_eligible:
            candidates.append(scheme)

    if not candidates:
        return {
            "recommended": None,
            "alternates": [],
            "message": "No matching scheme found for the details provided. "
                       "Consider checking category or income inputs, or contact your nearest SCA/CA for guidance."
        }

    # Rank by lowest beneficiary interest rate. Tiebreaker: if the applicant
    # signaled SHG intent (shg_size present), a group_loan scheme wins ties
    # over an individual scheme — an SHG applicant shouldn't see an
    # individual loan edge out the group loan just because it appeared
    # first in the data.
    def sort_key(s):
        rate = get_interest_rate(applicant, s)
        rate = rate if rate is not None else float("inf")
        is_shg_applicant = applicant.get("shg_size") is not None
        prefers_group = 0 if (is_shg_applicant and s.get("scheme_type") == "group_loan") else 1
        return (rate, prefers_group)

    candidates.sort(key=sort_key)

    top = candidates[0]
    alternates = candidates[1:3]  # up to 2 alternates
    runner_up = candidates[1] if len(candidates) > 1 else None

    return {
        "recommended": {
            "scheme_id": top["scheme_id"],
            "name": top["name"],
            "reason": generate_reason(applicant, top)
        },
        "alternates": [
            {"scheme_id": s["scheme_id"], "name": s["name"], "reason": generate_reason(applicant, s)}
            for s in alternates
        ],
        "comparison": build_comparison(applicant, candidates),
        "comparison_note": generate_comparison_note(applicant, top, runner_up),
        "message": None
    }


def print_result(label, applicant, result):
    """Human-readable summary for demo purposes — no raw JSON squinting."""
    print(f"\n{'=' * 60}")
    print(f"SCENARIO: {label}")
    print(f"Applicant: {applicant}")
    print("-" * 60)
    if result["message"]:
        print(f"❌ {result['message']}")
        return
    rec = result["recommended"]
    print(f"✅ Recommended: {rec['name']} ({rec['scheme_id']})")
    print(f"   Why: {rec['reason']}")

    if result["comparison"]:
        print(f"\n   Comparison of all eligible schemes:")
        print(f"   {'Scheme':<32}{'Rate':>8}{'Loan Cap':>14}{'Repay (yrs)':>13}")
        for row in result["comparison"]:
            cap = f"₹{row['loan_cap']:,}" if row["loan_cap"] is not None else "—"
            rate = f"{row['interest_rate_percent']}%" if row["interest_rate_percent"] is not None else "—"
            years = row["repayment_years"] if row["repayment_years"] is not None else "—"
            print(f"   {row['name']:<32}{rate:>8}{cap:>14}{str(years):>13}")
        print(f"\n   Why this ranking: {result['comparison_note']}")


if __name__ == "__main__":
    scenarios = [
        ("SC individual, small business, low income", {
            "category": "SC", "annual_family_income": 350000,
            "project_cost": 100000, "loan_amount": 90000,
            "channel": "Cooperative Bank/Society", "purpose": "income_generating"
        }),
        ("SC individual, mid-size project (Term Loan range)", {
            "category": "SC", "annual_family_income": 480000,
            "project_cost": 800000, "loan_amount": 700000,
            "purpose": "income_generating"
        }),
        ("SC student, engineering degree, education loan", {
            "category": "SC", "annual_family_income": 400000,
            "course_fee": 600000, "course": "Engineering",
            "purpose": "education"
        }),
        ("OBC individual, small business loan (NBCFDC)", {
            "category": "OBC", "annual_family_income": 450000,
            "loan_amount": 100000, "purpose": "income_generating"
        }),
        ("OBC self-help group loan (SHG) — should rank group loan first now", {
            "category": "OBC", "annual_family_income": 300000,
            "loan_amount": 100000, "shg_size": 15, "channel": "SCA_or_Bank"
        }),
        ("Income too high for any scheme", {
            "category": "SC", "annual_family_income": 900000,
            "project_cost": 100000, "loan_amount": 90000,
            "purpose": "income_generating"
        }),
        ("Wrong category for NSFDC schemes", {
            "category": "General", "annual_family_income": 300000,
            "project_cost": 100000, "loan_amount": 90000,
            "purpose": "income_generating"
        }),
        ("Income exactly AT the ₹5L cap (boundary — should pass)", {
            "category": "SC", "annual_family_income": 500000,
            "project_cost": 100000, "loan_amount": 90000,
            "purpose": "income_generating"
        }),
        ("Income ₹1 over the ₹5L cap (boundary — should fail)", {
            "category": "SC", "annual_family_income": 500001,
            "project_cost": 100000, "loan_amount": 90000,
            "purpose": "income_generating"
        }),
        ("Project cost exactly AT MFS's ₹1.4L ceiling (should get MFS)", {
            "category": "SC", "annual_family_income": 400000,
            "project_cost": 140000, "loan_amount": 100000,
            "purpose": "income_generating"
        }),
        ("Project cost ₹1 over MFS ceiling (should fall into Term Loan)", {
            "category": "SC", "annual_family_income": 400000,
            "project_cost": 140001, "loan_amount": 100000,
            "purpose": "income_generating"
        }),
        ("SHG size over the 20-member cap (should be rejected for SHG scheme)", {
            "category": "OBC", "annual_family_income": 300000,
            "loan_amount": 100000, "shg_size": 25, "channel": "SCA_or_Bank"
        }),
        ("Applicant with no category provided at all (malformed input)", {
            "category": None, "annual_family_income": 300000,
            "project_cost": 100000, "loan_amount": 90000,
            "purpose": "income_generating"
        }),
    ]

    for label, applicant in scenarios:
        result = recommend(applicant)
        print_result(label, applicant, result)

    print(f"\n{'=' * 60}")
    print("All scenarios ran. Review each ❌ case manually — a 'no match'")
    print("result should always come with a clear, non-crashing message.")
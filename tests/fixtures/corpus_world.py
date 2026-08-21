"""The invented world the large fixture corpus is generated from.

The 21 anchor documents in ``build_corpus.py`` were written one at a time. That
does not scale to the size L2 needs, and hand-writing 200 documents would
produce 200 documents that are all subtly different in ways nobody chose.

So this module holds a small world (wards, programmes, committees, officers,
meeting dates) and a set of document shapes that are filled from it. The world
is the reviewable source. Nothing here is random and nothing is seeded: every
document is a pure function of its index, so the corpus regenerates
byte-identically on every machine and a diff of this file is a diff of the
corpus.

Why the corpus has to be this size, and this shape:

``dense_k`` and ``sparse_k`` both default to 50. Against the 59-chunk anchor
corpus each retrieval arm is asked for most of the corpus, so every strategy
scores about the same and the L2 gate cannot go red. A gate that cannot fail
proves nothing. See ``docs/design/04-build-handoff.md``, "The corpus problem".

Size alone does not fix it. A corpus of 200 documents about 200 unrelated
subjects is just as easy: BM25 finds the one document that shares a rare word
and every arm agrees. What discriminates between retrieval strategies is
**vocabulary overlap with a single correct answer**, so the world is built to
produce it. Every programme carries a budget trajectory of four figures across
four quarters, and the document dated in a given quarter states that quarter's
figure. Ask what the capital allocation for a programme is and there is exactly
one right chunk and three near-identical decoys, differing by a date and a
number. Those are the questions worth measuring on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# --- the world ---------------------------------------------------------------

WARDS: tuple[str, ...] = (
    "Attercliffe", "Darnall", "Burngreave", "Firth Park", "Hillsborough",
    "Woodhouse", "Manor Castle", "Gleadless Valley", "Crookes", "Stocksbridge",
    "Beauchief", "Nether Edge",
)

OFFICERS: tuple[tuple[str, str], ...] = (
    ("Priya Raghunathan", "Director of Regeneration"),
    ("Tom Ellery", "Programme Director"),
    ("Adaeze Okonkwo", "Head of Capital Finance"),
    ("Martin Speight", "Director of Finance"),
    ("Ruth Bellamy", "Head of Legal Services"),
    ("Idris Farooqi", "Head of Highways"),
    ("Claire Ashworth", "Head of Housing Delivery"),
    ("Sam Wray", "Director of Public Health"),
)

COUNCILLORS: tuple[str, ...] = (
    "Councillor Hardy", "Councillor Nair", "Councillor Okonkwo",
    "Councillor Adeyemi", "Councillor Whitfield", "Councillor Brentnall",
    "Councillor Iqbal", "Councillor Merrick", "Councillor Yeboah",
    "Councillor Pashley",
)

CONTRACTORS: tuple[str, ...] = (
    "Ravensdale Construction", "Loxley Civils", "Pennine Build Group",
    "Wicker Infrastructure", "Don Valley Contractors", "Rivelin Partnership",
)


@dataclass(frozen=True)
class Programme:
    """One capital programme, and the figures that follow it through the year.

    ``budgets`` is the reason this class exists. Four quarters, four different
    approved allocations, each one correct on its own date and wrong on the
    other three. A retriever that returns the 2025 Q3 figure for a 2026 Q2
    question has failed in a way that a corpus of unrelated documents would
    never have caught.
    """

    key: str
    name: str
    ward: str
    code: str
    contractor: str
    option: str
    budgets: tuple[str, str, str, str]
    completion: str
    risks: tuple[str, str, str]


_BUDGET_BASES = (2.4, 5.1, 1.8, 12.6, 3.3, 0.9, 7.4, 2.05, 4.6, 1.15, 8.2, 3.85)
# Four distinct steps in every tuple. Two equal quarters would mean two
# documents that are both right, which is one decoy fewer than the golden set
# is entitled to assume. There is a test for it.
_STEPS = ((0.0, 0.5, 0.7, 0.45), (0.0, -0.3, 0.2, 0.35), (0.0, 0.15, 0.4, 0.6))
_OPTIONS = ("Option A", "Option B", "Option C", "Option B (revised)")
_COMPLETIONS = ("March 2027", "September 2027", "December 2026", "June 2028")
_RISK_POOL = (
    "Ground contamination survey outstanding on the eastern parcel",
    "Section 106 agreement not yet completed",
    "Utilities diversion dependent on a third-party programme",
    "Construction inflation above the allowance carried in the budget",
    "Planning consent conditional on a revised transport assessment",
    "Grant funding conditions require spend to be defrayed within the year",
    "Contractor framework expires before the works are due to complete",
    "Archaeological watching brief may extend the enabling works",
    "Flood risk sequential test to be revisited after the modelling update",
)


def _money(value: float) -> str:
    """Council papers write millions to two decimals and thousands in full."""
    if value >= 1.0:
        return f"£{value:.2f}m".replace(".00m", "m")
    return f"£{round(value * 1_000_000):,}"


def _programme(index: int) -> Programme:
    ward = WARDS[index % len(WARDS)]
    base = _BUDGET_BASES[index % len(_BUDGET_BASES)]
    steps = _STEPS[index % len(_STEPS)]
    budgets = tuple(_money(round(base + s, 2)) for s in steps)
    return Programme(
        key=ward.lower().replace(" ", "-"),
        name=f"{ward} Regeneration Programme",
        ward=ward,
        code=f"REG-{100 + index * 7}",
        contractor=CONTRACTORS[index % len(CONTRACTORS)],
        option=_OPTIONS[index % len(_OPTIONS)],
        budgets=budgets,  # type: ignore[arg-type]
        completion=_COMPLETIONS[index % len(_COMPLETIONS)],
        risks=(
            _RISK_POOL[index % len(_RISK_POOL)],
            _RISK_POOL[(index + 3) % len(_RISK_POOL)],
            _RISK_POOL[(index + 6) % len(_RISK_POOL)],
        ),
    )


PROGRAMMES: tuple[Programme, ...] = tuple(_programme(i) for i in range(len(WARDS)))

COMMITTEES: tuple[tuple[str, str], ...] = (
    ("Planning Committee", "planning-committee"),
    ("Cabinet", "cabinet"),
    ("Audit and Standards Committee", "audit-and-standards-committee"),
    ("Overview and Scrutiny Committee", "overview-and-scrutiny-committee"),
    ("Health and Wellbeing Board", "health-and-wellbeing-board"),
    ("Licensing Sub-Committee", "licensing-sub-committee"),
    ("Transport and Highways Committee", "transport-and-highways-committee"),
    ("Children and Families Committee", "children-and-families-committee"),
    ("Adult Social Care Committee", "adult-social-care-committee"),
)

# Eleven monthly meeting dates, September 2025 to July 2026. Committees meet on
# different days of the month so that two documents from the same month are
# still distinguishable by date, which is what the metadata extractor keys on.
_MEETING_MONTHS: tuple[tuple[int, int], ...] = (
    (2025, 9), (2025, 10), (2025, 11), (2025, 12),
    (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5), (2026, 6), (2026, 7),
)


def meeting_dates(committee_index: int) -> tuple[date, ...]:
    # Three days apart, and never past the 27th, so the same rule works in
    # February without a special case.
    day = 3 + (committee_index % 9) * 3
    return tuple(date(y, m, day) for y, m in _MEETING_MONTHS)


def quarter_of(when: date) -> int:
    """Which of the four budget figures is current on this date.

    The financial year runs April to March, so a document dated in September
    2025 is in the same budget quarter as one dated in November 2025 and cites
    the same figure. Documents either side of a boundary cite different ones.
    """
    index = (when.year - 2025) * 4 + (when.month - 1) // 3
    return max(0, min(3, index - 2))


# --- phrasing ----------------------------------------------------------------
#
# The facts are the decoys; the wording must not be. An earlier version of this
# module stated every budget in one byte-identical sentence, varying only the
# programme, the date and the amount. That looked like a corpus of near
# duplicates, which is what a retrieval measurement wants, but it biased the
# measurement it was built to support.
#
# Templated text collapses under an embedding model: four sentences differing by
# one number sit almost on top of each other, so the dense arm cannot separate
# them. BM25 meanwhile has exact tokens for the year and the amount, which is
# what it is best at. The gate asks whether hybrid beats dense-only and
# BM25-only, and a corpus shaped like that answers "BM25 was enough" before the
# retriever gets a say. That would be a fact about the fixtures, not about
# retrieval.
#
# So the same fact is stated several ways, chosen by document index rather than
# at random. Every phrasing keeps the amount and the financial year as literal
# tokens, so BM25 keeps the handle it is entitled to, and the dense arm now has
# real semantic variation to work against.

ALLOCATION_PHRASINGS: tuple[str, ...] = (
    "The capital allocation for {fy} was reported as {amount}.",
    "Members noted a revised allocation of {amount} for {fy}.",
    "Funding of {amount} was confirmed against the {fy} programme.",
    "The {fy} allocation stands at {amount} following the latest review.",
    "An allocation of {amount} has been agreed for {fy}.",
    "Spending power for {fy} is {amount}, unchanged since the last report.",
    "The programme carries {amount} of capital in {fy}.",
)

DECISION_PHRASINGS: tuple[str, ...] = (
    "The Committee RESOLVED to approve the capital allocation of {amount} for "
    "the {programme} for {fy}, and to delegate authority for contract award to "
    "the {role}.",
    "RESOLVED: that {amount} be approved for the {programme} in {fy}, with "
    "contract award delegated to the {role}.",
    "The Committee agreed the {fy} allocation of {amount} for the {programme}, "
    "and that the {role} should award the contract.",
    "It was RESOLVED that the {programme} proceed on the basis of {amount} for "
    "{fy}, authority for award resting with the {role}.",
    "Approval was given for {amount} against the {programme} for {fy}. The "
    "{role} will award the contract.",
)

UPDATE_PHRASINGS: tuple[str, ...] = (
    "{officer} ({role}) presented an update on the {programme}, reference "
    "{code}.",
    "The {role} took Members through the {programme}, reference {code}.",
    "An update on the {programme} ({code}) was given by {officer}.",
    "{officer} reported on progress against the {programme}, reference {code}.",
)

DELIVERY_PHRASINGS: tuple[str, ...] = (
    "The programme is being delivered by {contractor} under {option}, with "
    "completion forecast for {completion}.",
    "{contractor} is on site under {option}. Completion is expected in "
    "{completion}.",
    "Delivery continues under {option} with {contractor}, targeting "
    "{completion}.",
    "Works are with {contractor} on the {option} route, for completion by "
    "{completion}.",
)


def phrase(bank: tuple[str, ...], index: int, **fields: object) -> str:
    """One phrasing from a bank, chosen by index so the corpus stays a pure
    function of its inputs. There is no seed here and no clock."""
    return bank[index % len(bank)].format(**fields)


# --- document payloads -------------------------------------------------------


@dataclass(frozen=True)
class Doc:
    """One generated document, ready for the writer that matches ``kind``."""

    name: str
    kind: str
    payload: object


def _long_date(when: date) -> str:
    return f"{when.day} {when.strftime('%B')} {when.year}"


def _fy(when: date) -> str:
    start = when.year if when.month >= 4 else when.year - 1
    return f"{start}/{str(start + 1)[2:]}"


def _minutes_md(committee: str, when: date, index: int) -> str:
    """Committee minutes: the highest chunk-yield shape in the corpus.

    Structure-first chunking emits at least one chunk per heading section, and
    minutes are almost entirely headings: an item, its decision, its actions.
    They are also where the budget figures live, so they carry most of the
    questions the golden set will be written from.
    """
    quarter = quarter_of(when)
    lead, lead_role = OFFICERS[index % len(OFFICERS)]
    chair = COUNCILLORS[index % len(COUNCILLORS)]
    apologies = ", ".join(
        COUNCILLORS[(index + n) % len(COUNCILLORS)] for n in (1, 4)
    )

    out = [
        f"# {committee} Minutes",
        "",
        f"**Date:** {_long_date(when)}",
        "**Venue:** Town Hall, Committee Room 2",
        f"**Chair:** {chair}",
        "",
        "## Item 1: Apologies",
        "",
        f"Apologies were received from {apologies}.",
        "",
        "## Item 2: Minutes of the previous meeting",
        "",
        "The minutes of the previous meeting were agreed as a correct record, "
        "subject to a correction to the attendance list.",
        "",
    ]

    # Twelve programmes per meeting, rotating, so every programme appears in
    # several committees across the year and no single document holds all of
    # the vocabulary a question might match on. Twelve rather than six because
    # minutes are where the chunks are: structure-first chunking emits a chunk
    # per heading, and an item carries three of them.
    for slot in range(12):
        prog = PROGRAMMES[(index + slot) % len(PROGRAMMES)]
        item = slot + 3
        amount = prog.budgets[quarter]
        # The same programme discussed by two committees in the same quarter
        # states the same figure in different words. That is the difference
        # between a corpus of near duplicates and a corpus of copies.
        variant = index + slot
        out += [
            f"## Item {item}: {prog.name}",
            "",
            phrase(UPDATE_PHRASINGS, variant, officer=lead, role=lead_role,
                   programme=prog.name, code=prog.code)
            + " "
            + phrase(ALLOCATION_PHRASINGS, variant, fy=_fy(when), amount=amount)
            + " "
            + phrase(DELIVERY_PHRASINGS, variant, contractor=prog.contractor,
                     option=prog.option, completion=prog.completion),
            "",
            f"The Committee noted that {prog.risks[0].lower()}, and that "
            f"{prog.risks[1].lower()}.",
            "",
            f"### Item {item} Decision",
            "",
            phrase(DECISION_PHRASINGS, variant, amount=amount,
                   programme=prog.name, fy=_fy(when), role=lead_role),
            "",
            f"### Item {item} Actions",
            "",
            f"Action {item}.1 - The {lead_role} to publish the revised "
            f"programme plan for {prog.code} within 20 working days.",
            "",
            f"Action {item}.2 - The Head of Capital Finance to confirm the "
            f"drawdown profile for {prog.name} before the next meeting.",
            "",
        ]

    out += [
        "## Item 15: Risk register",
        "",
        "The Committee reviewed the quarterly risk register. Two risks moved "
        "from amber to red, both relating to construction inflation.",
        "",
        "## Item 16: Date of the next meeting",
        "",
        "The next meeting will be held at the Town Hall.",
        "",
    ]
    return "\n".join(out)


def _report_docx(prog: Programme, when: date, index: int) -> list[tuple[str, str]]:
    quarter = quarter_of(when)
    author, role = OFFICERS[index % len(OFFICERS)]
    amount = prog.budgets[quarter]
    return [
        ("h1", f"{prog.name} Progress Report"),
        ("p", f"Report of the {role}, {_long_date(when)}. Reference {prog.code}."),
        ("h2", "Recommendation"),
        ("p", f"That the Committee approves the capital allocation of {amount} "
              f"for {_fy(when)} and notes the delivery position."),
        ("h2", "Background"),
        ("p", f"The {prog.name} covers the {prog.ward} ward and is being "
              f"delivered by {prog.contractor} under {prog.option}."),
        ("h2", "Financial implications"),
        ("p", phrase(ALLOCATION_PHRASINGS, index + 2, fy=_fy(when), amount=amount)
              + " Spend to date is within profile."),
        ("h2", "Delivery position"),
        ("p", f"Completion remains forecast for {prog.completion}."),
        ("h2", "Risk"),
        ("p", f"{prog.risks[0]}. {prog.risks[1]}."),
        ("h2", "Legal implications"),
        ("p", f"Prepared by {author}. No further legal implications arise."),
        ("h2", "Equality implications"),
        ("p", "An equality impact assessment has been completed and is "
              "available on request."),
    ]


def _update_html(prog: Programme, when: date) -> str:
    quarter = quarter_of(when)
    amount = prog.budgets[quarter]
    sections = "".join(
        f"<h2>{title}</h2><p>{body}</p>"
        for title, body in (
            ("Summary", f"The {prog.name} is reported as amber for "
                        f"{_fy(when)}, with a capital allocation of {amount}."),
            ("Budget", phrase(ALLOCATION_PHRASINGS, quarter + 1,
                              fy=_fy(when), amount=amount)
                       + f" It is managed under reference {prog.code}."),
            ("Delivery", f"{prog.contractor} continues on site under "
                         f"{prog.option}. Completion is forecast for "
                         f"{prog.completion}."),
            ("Risks", f"{prog.risks[0]}. {prog.risks[2]}."),
            ("Next steps", "A revised programme plan will be brought to the "
                           "next meeting of the Programme Board."),
        )
    )
    return (
        "<html><head><title>"
        f"{prog.name} Update</title></head><body>"
        f"<h1>{prog.name} Update</h1>"
        f"<p>Published {_long_date(when)}.</p>"
        f"{sections}</body></html>"
    )


def _tor_md(prog: Programme, when: date) -> str:
    return "\n".join([
        f"# Terms of Reference: {prog.name} Board",
        "",
        f"**Approved:** {_long_date(when)}",
        "",
        "## Purpose",
        "",
        f"The Board oversees delivery of the {prog.name} in the {prog.ward} "
        f"ward, under reference {prog.code}.",
        "",
        "## Membership",
        "",
        "The Board comprises the Director of Regeneration, the Programme "
        "Director, the Head of Capital Finance and two elected members.",
        "",
        "## Quorum",
        "",
        "Three members, one of whom must be an elected member.",
        "",
        "## Decision-making authority",
        "",
        f"The Board may approve virements within the {prog.name} up to "
        "£250,000. Anything above that threshold is reserved to Cabinet.",
        "",
        "## Reporting",
        "",
        "The Board reports to Cabinet quarterly and to the Overview and "
        "Scrutiny Committee on request.",
        "",
        "## Review",
        "",
        "These terms of reference are reviewed annually.",
        "",
    ])


def _policy_md(index: int, when: date) -> str:
    topics = (
        ("Information Governance", "information-governance"),
        ("Records Retention", "records-retention"),
        ("Procurement", "procurement"),
        ("Contract Management", "contract-management"),
        ("Data Protection Impact Assessment", "dpia"),
        ("Capital Programme Governance", "capital-programme-governance"),
        ("Risk Management", "risk-management"),
        ("Community Engagement", "community-engagement"),
    )
    name, _ = topics[index % len(topics)]
    version = f"{2 + index % 3}.{index % 5}"
    sections = (
        ("Scope", "This policy applies to all officers and members of the "
                  "Council, and to contractors acting on its behalf."),
        ("Principles", "Decisions are recorded, evidence is retained, and the "
                       "reasons for a decision are traceable to the record."),
        ("Responsibilities", "The Director of Finance owns this policy. Heads "
                             "of Service are accountable for its application."),
        ("Retention", "Committee papers are retained for ten years. Working "
                      "papers are retained for three years."),
        ("Exceptions", "An exception requires the written approval of the "
                       "Director of Finance and is recorded in the register."),
        ("Breach", "A suspected breach is reported to the Head of Legal "
                   "Services within one working day."),
        ("Review", f"This policy is reviewed every two years. Version "
                   f"{version} was approved on {_long_date(when)}."),
    )
    out = [f"# {name} Policy v{version}", "", f"**Approved:** {_long_date(when)}", ""]
    for title, body in sections:
        out += [f"## {title}", "", body, ""]
    return "\n".join(out)


def _email_eml(prog: Programme, when: date, index: int) -> str:
    sender, role = OFFICERS[index % len(OFFICERS)]
    quarter = quarter_of(when)
    handle = sender.lower().replace(" ", ".")
    return (
        f"From: {sender} <{handle}@example-council.gov.uk>\n"
        f"To: Committee Services <committee.services@example-council.gov.uk>\n"
        f"Subject: {prog.name} drawdown profile {_fy(when)}\n"
        f"Date: {when.strftime('%a, %d %b %Y')} 09:14:00 +0000\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        f"Confirming the drawdown profile for the {prog.name}, reference "
        f"{prog.code}.\n"
        "\n"
        + phrase(ALLOCATION_PHRASINGS, index + 4, fy=_fy(when),
                 amount=prog.budgets[quarter])
        + f" Spend to date is within profile and the forecast completion "
        f"date is unchanged at {prog.completion}.\n"
        "\n"
        f"One risk to flag: {prog.risks[0].lower()}.\n"
        "\n"
        f"{sender}\n{role}\n"
    )


def _note_txt(prog: Programme, when: date) -> str:
    return (
        f"Site visit note - {prog.ward}\n"
        f"{_long_date(when)}\n"
        "\n"
        f"Attended site with the {prog.contractor} site manager. Enabling "
        f"works are complete on the northern parcel. The hoarding line has "
        f"moved as agreed.\n"
        "\n"
        f"Outstanding: {prog.risks[2].lower()}.\n"
        "\n"
        f"Programme reference {prog.code}. Next visit in four weeks.\n"
    )


def _slides_pptx(prog: Programme, when: date) -> list[tuple[str, list[str]]]:
    quarter = quarter_of(when)
    return [
        (f"{prog.name}", [f"Programme Board, {_long_date(when)}",
                          f"Reference {prog.code}"]),
        ("Position", ["Status: amber", f"Allocation {_fy(when)}: "
                                       f"{prog.budgets[quarter]}"]),
        ("Delivery", [f"Contractor: {prog.contractor}", f"Route: {prog.option}"]),
        ("Programme", [f"Forecast completion: {prog.completion}",
                       "Enabling works complete"]),
        ("Risk 1", [prog.risks[0]]),
        ("Risk 2", [prog.risks[1]]),
        ("Risk 3", [prog.risks[2]]),
        ("Decisions sought", [f"Approve {prog.budgets[quarter]} for {_fy(when)}",
                              "Note the delivery position"]),
    ]


def _statement_pdf(prog: Programme, when: date) -> list[str]:
    quarter = quarter_of(when)
    return [
        f"{prog.name} Annual Statement",
        f"Published {_long_date(when)}. Reference {prog.code}.",
        phrase(ALLOCATION_PHRASINGS, quarter + 3, fy=_fy(when),
               amount=prog.budgets[quarter]),
        f"Delivery is by {prog.contractor} under {prog.option}.",
        f"Completion is forecast for {prog.completion}.",
        f"Principal risk: {prog.risks[0]}",
    ]


def _risk_xlsx(prog: Programme, when: date) -> dict[str, list[list[str]]]:
    header = ["ref", "risk", "likelihood", "impact", "owner", "status"]
    rows = [
        [f"{prog.code}-R{n + 1}", risk, ("high", "medium", "low")[n % 3],
         ("high", "high", "medium")[n % 3], OFFICERS[n % len(OFFICERS)][0],
         ("open", "open", "mitigated")[n % 3]]
        for n, risk in enumerate(prog.risks)
    ]
    return {
        "Risks": [header, *rows],
        "Mitigations": [
            ["ref", "mitigation", "due"],
            *[[f"{prog.code}-R{n + 1}", f"Mitigation for {risk[:40]}",
               prog.completion] for n, risk in enumerate(prog.risks)],
        ],
        "Summary": [
            ["measure", "value"],
            ["programme", prog.name],
            ["allocation", prog.budgets[quarter_of(when)]],
            ["open risks", str(len(prog.risks))],
        ],
    }


def _action_csv(prog: Programme, when: date) -> list[list[str]]:
    rows = [["ref", "action", "owner", "due", "status"]]
    for n, (owner, role) in enumerate(OFFICERS[:5]):
        rows.append([
            f"{prog.code}-A{n + 1}",
            f"{role} to report on {prog.name} to the Programme Board",
            owner,
            _long_date(when),
            ("open", "closed", "open", "open", "closed")[n],
        ])
    return rows


def _consultation_json(prog: Programme, when: date) -> dict[str, object]:
    return {
        "consultation": f"{prog.name} public consultation",
        "reference": prog.code,
        "closed": when.isoformat(),
        "responses": 180 + len(prog.ward) * 7,
        "themes": [
            {"theme": "Traffic and access", "count": 62,
             "summary": "Concern about construction traffic on residential streets"},
            {"theme": "Green space", "count": 41,
             "summary": "Support for the retained green space on the eastern parcel"},
            {"theme": "Affordable housing", "count": 38,
             "summary": "Requests for a higher affordable housing proportion"},
        ],
        "next_steps": f"A report will be taken to Cabinet recommending "
                      f"{prog.option} at {prog.budgets[quarter_of(when)]}.",
    }


# --- assembly ----------------------------------------------------------------


def generated_documents(scale: int) -> list[Doc]:
    """Every generated document, in a stable order.

    ``scale`` multiplies the number of meetings and programme cycles covered.
    Scale 1 is a handful of documents, used by the tests that only need the
    generator to be exercised. Scale 8 is the measurement corpus.
    """
    docs: list[Doc] = []

    # Minutes carry most of the corpus. Scale is how many months of meetings
    # to cover, capped at the window the world defines.
    months = min(scale, len(_MEETING_MONTHS))
    for slot in range(len(COMMITTEES) * months):
        committee, slug = COMMITTEES[slot % len(COMMITTEES)]
        dates = meeting_dates(slot % len(COMMITTEES))
        when = dates[(slot // len(COMMITTEES)) % len(dates)]
        docs.append(Doc(
            f"{slug}-minutes-{when.isoformat()}.md", "md",
            _minutes_md(committee, when, slot),
        ))

    # One pass over the programmes. Twelve programmes across four budget
    # quarters is already the whole decoy structure, so a second pass would
    # repeat it rather than add to it.
    for n in range(min(scale, len(PROGRAMMES))):
        prog = PROGRAMMES[n]
        when = meeting_dates(n % len(COMMITTEES))[(n * 2) % len(_MEETING_MONTHS)]
        stamp = when.isoformat()

        docs.append(Doc(f"{prog.key}-progress-report-{stamp}.docx", "docx",
                        _report_docx(prog, when, n)))
        docs.append(Doc(f"{prog.key}-programme-update-{stamp}.html", "html",
                        _update_html(prog, when)))
        docs.append(Doc(f"{prog.key}-drawdown-{stamp}.eml", "eml",
                        _email_eml(prog, when, n)))
        docs.append(Doc(f"{prog.key}-site-visit-note-{stamp}.txt", "txt",
                        _note_txt(prog, when)))

        # The lower-yield formats appear on every other cycle, so the corpus
        # stays mixed without spending most of its documents on shapes that
        # produce one chunk each.
        if n % 2 == 0:
            docs.append(Doc(f"{prog.key}-board-slides-{stamp}.pptx", "pptx",
                            _slides_pptx(prog, when)))
            docs.append(Doc(f"{prog.key}-risk-register-{stamp}.xlsx", "xlsx",
                            _risk_xlsx(prog, when)))
            docs.append(Doc(f"{prog.key}-terms-of-reference-{stamp}.md", "md",
                            _tor_md(prog, when)))
        if n % 3 == 0:
            docs.append(Doc(f"{prog.key}-annual-statement-{stamp}.pdf", "pdf",
                            _statement_pdf(prog, when)))
            docs.append(Doc(f"{prog.key}-action-log-{stamp}.csv", "csv",
                            _action_csv(prog, when)))
        if n % 4 == 0:
            docs.append(Doc(f"{prog.key}-consultation-results-{stamp}.json", "json",
                            _consultation_json(prog, when)))
            docs.append(Doc(f"governance-policy-{n}-{stamp}.md", "md",
                            _policy_md(n, when)))

    return docs

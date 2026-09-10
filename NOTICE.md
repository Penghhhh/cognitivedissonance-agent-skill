# Notices

These notices sit outside [`LICENSE`](LICENSE) deliberately. GitHub's licence
detector only recognises a file that contains a standard licence text and nothing
else; with these sections appended, the repository reported `NOASSERTION` instead of
`MIT`, so the licence was invisible in the sidebar and to automated licence tooling.

## Documentation and research materials

The MIT grant in `LICENSE` covers the software. The prose and research artifacts in
`references/`, `docs/`, `README.md` and `SKILL.md` are **additionally** available
under the Creative Commons Attribution 4.0 International licence (CC BY 4.0),
<https://creativecommons.org/licenses/by/4.0/>, so that the codebook and the design
rationale can be reused and adapted in academic work with attribution. Where the two
grants differ, you may choose either.

## Responsible use

The `dissonance_reduction` profile deliberately simulates motivated reasoning that
degrades epistemic quality: discounting sources, trivialising evidence and
rationalising a prior commitment. It exists to **study and measure** that behaviour,
not to recommend it.

Safeguards are built in. Every card and response plan produced on that branch is
labelled with its branch, and carries a `fidelity_not_advice` constraint; the
`deny_evidence` strategy additionally requires a checkable reason rather than mere
disagreement. These constrain the shape of the output, but they cannot constrain
downstream use.

**Do not enable that profile in a setting where a user could mistake a simulated
reduction move for the system's own advice.** The default profile is `adaptive`,
which does not have this property.

## No claim of inner states

This skill simulates externally observable language behaviour. It does not claim
that a model experiences discomfort, and nothing in its output should be read as
such a claim. See [`references/construct.md`](references/construct.md) for where the
boundary is drawn and how it is defended.

## Data

The repository ships no human-subjects data. `logs/` is git-ignored on purpose: run
logs from a user study can contain participant text and belong in a managed data
repository with its own access controls and DOI, never in this one.

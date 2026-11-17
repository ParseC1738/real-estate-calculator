"""Data / import: "Fetch now", CSV import, run log, reload sample data (SPEC §8.6)."""

import pandas as pd
import streamlit as st

from immo.core.models import FetchRun
from immo.pipeline.ingest import run_ingest
from immo.pipeline.seed import seed_database
from immo.sources.csv_import import TEMPLATE_CSV, CsvAdapter, decode_csv
from immo.sources.registry import active_adapters
from immo.ui import state

RESULT_KEY = "import_results"


def _remember(runs: list[FetchRun], headline: str) -> None:
    """Keep the result for the next script run, then rerun so all tables are fresh."""
    st.session_state[RESULT_KEY] = (headline, runs)
    st.rerun()


def _show_results() -> None:
    if RESULT_KEY not in st.session_state:
        return
    headline, runs = st.session_state.pop(RESULT_KEY)
    for run in runs:
        summary = (
            f"**{headline} – {run.source}:** {run.fetched} fetched · {run.new} new · "
            f"{run.changed} changed · {run.relisted} relisted · {run.gone} gone · "
            f"{run.unchanged} unchanged"
        )
        if run.note.startswith("fetch failed"):
            st.error(f"{summary}\n\n{run.errors[0] if run.errors else run.note}")
            continue
        (st.warning if run.errors else st.success)(summary)
        if run.note:
            st.caption(run.note)
        if run.errors:
            with st.expander(f"{len(run.errors)} listing(s) were skipped", expanded=True):
                st.dataframe(
                    pd.DataFrame({"Problem": run.errors}), hide_index=True, width="stretch"
                )


def _fetch_now(repo) -> None:
    st.subheader("Fetch now")
    adapters = active_adapters(repo)
    names = ", ".join(f"`{adapter.name}`" for adapter in adapters)
    st.caption(
        f"Runs every active adapter ({names}). The sample adapter simulates one more week "
        "of the market per click: new listings, price changes, listings going offline."
    )
    if st.button("🔄 Fetch now", type="primary"):
        with st.spinner("Fetching …"):
            runs = [run_ingest(adapter, repo) for adapter in adapters]
        _remember(runs, "Fetch")


def _csv_import(repo) -> None:
    st.subheader("CSV import")
    st.caption(
        "One listing per row; column names are the listing fields. Separator `;` or `,`, "
        "numbers German (`250.000,50`) or English (`250000.5`). Importing the same "
        "`source_listing_id` again updates the listing and records changes in its history."
    )
    upload = st.file_uploader("CSV file", type=["csv"])
    deactivate = st.checkbox(
        "This file is complete: mark CSV listings that are not in it as no longer online",
        value=False,
    )
    left, right = st.columns([1, 3])
    if left.button("📥 Import CSV", disabled=upload is None):
        adapter = CsvAdapter(decode_csv(upload.getvalue()))
        _remember([run_ingest(adapter, repo, deactivate_missing=deactivate)], "CSV import")
    right.download_button(
        "Download a template (4 example rows)",
        TEMPLATE_CSV.encode("utf-8-sig"),
        file_name="listings_example.csv",
        mime="text/csv",
    )


def _run_log(repo) -> None:
    st.subheader("Last runs")
    runs = repo.list_fetch_runs(limit=30)
    if not runs:
        st.info("No runs yet.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "When": run.started_at,
                    "Source": run.source,
                    "Fetched": run.fetched,
                    "New": run.new,
                    "Changed": run.changed,
                    "Relisted": run.relisted,
                    "Gone": run.gone,
                    "Unchanged": run.unchanged,
                    "Errors": len(run.errors),
                    "Note": run.note,
                }
                for run in runs
            ]
        ),
        hide_index=True,
        width="stretch",
        column_config={"When": st.column_config.DatetimeColumn(format="DD MMM YYYY, HH:mm")},
    )
    st.caption("Times are UTC. The first 12 `sample` runs are the simulated weekly history.")


def _reload_sample(repo) -> None:
    st.subheader("Reload sample data")
    st.caption(
        "Deletes **everything** in the database (all listings incl. CSV imports, history, "
        "overrides, run log) and loads the sample data again."
    )
    confirmed = st.checkbox("Yes, delete all data and reload the sample data")
    if st.button("♻️ Reload sample data", disabled=not confirmed):
        with st.spinner("Loading sample data …"):
            summary = seed_database(repo, reset=True)
        st.session_state.pop(state.DETAIL_KEY, None)
        st.session_state[RESULT_KEY] = (
            f"Sample data reloaded: {summary.listings_total} listings, "
            f"{summary.snapshots} snapshots, {summary.area_references} area references",
            [],
        )
        st.rerun()


def main() -> None:
    st.title("Data / import")
    repo = state.get_repo()
    if RESULT_KEY in st.session_state and not st.session_state[RESULT_KEY][1]:
        st.success(st.session_state.pop(RESULT_KEY)[0])
    _show_results()

    listings = repo.list_listings()
    cols = st.columns(3)
    cols[0].metric("Listings in the database", len(listings))
    cols[1].metric("Active", sum(1 for x in listings if x.is_active))
    cols[2].metric("Sources", ", ".join(sorted({x.source for x in listings})) or "–")

    left, right = st.columns(2)
    with left:
        _fetch_now(repo)
    with right:
        _csv_import(repo)
    st.divider()
    _run_log(repo)
    st.divider()
    _reload_sample(repo)


main()

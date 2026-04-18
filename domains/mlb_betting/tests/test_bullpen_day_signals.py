from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bullpen_day_signals import (
    ROLE_BUCKET_RELIEVER,
    ROLE_BUCKET_STARTER,
    ROLE_SOURCE_DEFAULT_NON_STARTER,
    ROLE_SOURCE_METRIC_RELIEVER,
    ROLE_SOURCE_STARTER_PRIOR,
    SIGNAL_LIKELY,
    SIGNAL_NONE,
    SIGNAL_SUSPICIOUS,
    build_live_scanner_rows,
    build_pitcher_role_rows,
    classify_pitcher_role_bucket,
    classify_signal_tier,
    determine_source_state,
    parse_espn_pregame_snapshot_text,
    render_research_report,
    select_latest_snapshot_rows,
)
from src.fangraphs_probables import normalize_pitcher_name, parse_fangraphs_probables_html
from src.polymarket_client import (
    MLBGameEvent,
    MLBMarket,
    build_event_openings_df,
    parse_market_opened_from_html,
    parse_market_opened_text,
)


def test_parse_fangraphs_probables_html_extracts_named_and_blank_rows():
    html = """
    <html>
      <body>
        <table>
          <thead>
            <tr><th>Team</th><th>Sat 4/18</th><th>Sun 4/19</th></tr>
          </thead>
          <tbody>
            <tr>
              <td>BAL</td>
              <td>@ CLE <a href="/player/1">Dean Kremer (R)</a></td>
              <td>@ CLE TBD</td>
            </tr>
            <tr>
              <td>BOS</td>
              <td>OFF</td>
              <td>NYY <a href="/player/2">Garrett Crochet (L)</a></td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """

    rows = parse_fangraphs_probables_html(
        html,
        captured_at=datetime(2026, 4, 18, 10, 0, tzinfo=UTC),
        year=2026,
    )

    assert len(rows) == 3
    assert set(rows["team"]) == {"BAL", "BOS"}

    bal_today = rows[(rows["team"] == "BAL") & (rows["target_date"] == pd.Timestamp("2026-04-18"))].iloc[0]
    assert bal_today["probable_name_raw"] == "Dean Kremer (R)"
    assert bal_today["probable_name_norm"] == "dean kremer"
    assert bool(bal_today["is_blank"]) is False

    bal_tomorrow = rows[(rows["team"] == "BAL") & (rows["target_date"] == pd.Timestamp("2026-04-19"))].iloc[0]
    assert bal_tomorrow["probable_name_raw"] == ""
    assert bool(bal_tomorrow["is_blank"]) is True


def test_parse_espn_pregame_snapshot_text_normalizes_blank_and_named_pitchers():
    raw = json.dumps(
        [
            {
                "event_id": "abc123",
                "team": "NYM",
                "home_away": "away",
                "pitcher": "Kodai Senga",
            },
            {
                "event_id": "abc123",
                "team": "CHC",
                "home_away": "home",
                "pitcher": "TBD",
            },
        ]
    )

    rows = parse_espn_pregame_snapshot_text(
        raw,
        captured_at=datetime(2026, 4, 18, 9, 30, tzinfo=UTC),
        snapshot_id="pregame_20260418_0930",
        source_url="https://example.test",
    )

    assert len(rows) == 2
    assert rows.loc[rows["team"] == "NYM", "probable_name_norm"].iloc[0] == "kodai senga"
    assert bool(rows.loc[rows["team"] == "CHC", "is_blank"].iloc[0]) is True


def test_normalize_pitcher_name_strips_diacritics():
    assert normalize_pitcher_name("Germán Márquez") == "german marquez"
    assert normalize_pitcher_name("Cristopher Sánchez") == "cristopher sanchez"


def test_classify_pitcher_role_bucket_covers_all_three_buckets():
    assert classify_pitcher_role_bucket(
        starts_prior=8,
        recent_starts_30d=3,
        recent_relief_apps_14d=0,
        recent_relief_share_30d=0.0,
        ip_per_start_short=5.2,
    ) == ROLE_BUCKET_STARTER

    assert classify_pitcher_role_bucket(
        starts_prior=1,
        recent_starts_30d=0,
        recent_relief_apps_14d=4,
        recent_relief_share_30d=0.8,
        ip_per_start_short=1.5,
    ) == ROLE_BUCKET_RELIEVER

    assert classify_pitcher_role_bucket(
        starts_prior=3,
        recent_starts_30d=1,
        recent_relief_apps_14d=1,
        recent_relief_share_30d=0.25,
        ip_per_start_short=3.3,
    ) == "unknown"


def test_build_pitcher_role_rows_uses_logs_for_role_classification(tmp_path):
    pitcher_logs = pd.DataFrame(
        [
            {"pitcher_id": 1, "pitcher_name": "Starter Sam", "date": "2026-03-20", "p_seq": 1},
            {"pitcher_id": 1, "pitcher_name": "Starter Sam", "date": "2026-03-27", "p_seq": 1},
            {"pitcher_id": 1, "pitcher_name": "Starter Sam", "date": "2026-04-02", "p_seq": 1},
            {"pitcher_id": 1, "pitcher_name": "Starter Sam", "date": "2026-04-08", "p_seq": 1},
            {"pitcher_id": 1, "pitcher_name": "Starter Sam", "date": "2026-04-14", "p_seq": 1},
            {"pitcher_id": 2, "pitcher_name": "Fireman Joe", "date": "2026-04-08", "p_seq": 2},
            {"pitcher_id": 2, "pitcher_name": "Fireman Joe", "date": "2026-04-10", "p_seq": 2},
            {"pitcher_id": 2, "pitcher_name": "Fireman Joe", "date": "2026-04-13", "p_seq": 3},
            {"pitcher_id": 2, "pitcher_name": "Fireman Joe", "date": "2026-04-16", "p_seq": 2},
            {"pitcher_id": 3, "pitcher_name": "Swingman Sid", "date": "2026-04-01", "p_seq": 1},
            {"pitcher_id": 3, "pitcher_name": "Swingman Sid", "date": "2026-04-12", "p_seq": 2},
        ]
    )
    starter_logs = pd.DataFrame(
        [
            {"pitcher_id": 1, "pitcher_name": "Starter Sam", "date": "2026-03-20", "p_ipouts": 15},
            {"pitcher_id": 1, "pitcher_name": "Starter Sam", "date": "2026-03-27", "p_ipouts": 15},
            {"pitcher_id": 1, "pitcher_name": "Starter Sam", "date": "2026-04-02", "p_ipouts": 18},
            {"pitcher_id": 1, "pitcher_name": "Starter Sam", "date": "2026-04-08", "p_ipouts": 15},
            {"pitcher_id": 1, "pitcher_name": "Starter Sam", "date": "2026-04-14", "p_ipouts": 18},
            {"pitcher_id": 3, "pitcher_name": "Swingman Sid", "date": "2026-04-01", "p_ipouts": 9},
        ]
    )

    pitcher_path = tmp_path / "pitcher_game_logs.parquet"
    starter_path = tmp_path / "starter_game_logs.parquet"
    priors_path = tmp_path / "starter_priors.csv"
    pitcher_logs.to_parquet(pitcher_path, index=False)
    starter_logs.to_parquet(starter_path, index=False)
    priors_path.write_text(
        "team,pitcher_name,source_tag,note\nAAA,Starter Sam,manual_prior,\n",
        encoding="utf-8",
    )

    probables = pd.DataFrame(
        [
            {"target_date": pd.Timestamp("2026-04-20"), "team": "AAA", "probable_name_norm": "starter sam"},
            {"target_date": pd.Timestamp("2026-04-20"), "team": "BBB", "probable_name_norm": "fireman joe"},
            {"target_date": pd.Timestamp("2026-04-20"), "team": "CCC", "probable_name_norm": "swingman sid"},
        ]
    )

    rows = build_pitcher_role_rows(
        probables,
        pitcher_game_logs_path=pitcher_path,
        starter_game_logs_path=starter_path,
        starter_priors_path=priors_path,
        persist=False,
    )

    lookup = rows.set_index("pitcher_name_norm")[["role_bucket", "role_source"]].to_dict(orient="index")
    assert lookup["starter sam"]["role_bucket"] == ROLE_BUCKET_STARTER
    assert lookup["starter sam"]["role_source"] == ROLE_SOURCE_STARTER_PRIOR
    assert lookup["fireman joe"]["role_bucket"] == ROLE_BUCKET_RELIEVER
    assert lookup["fireman joe"]["role_source"] == ROLE_SOURCE_METRIC_RELIEVER
    assert lookup["swingman sid"]["role_bucket"] == ROLE_BUCKET_RELIEVER
    assert lookup["swingman sid"]["role_source"] == ROLE_SOURCE_DEFAULT_NON_STARTER


def test_signal_logic_matches_requested_cases():
    state = determine_source_state(
        fg_name_norm="fireman joe",
        espn_name_norm="",
        fg_available=True,
        espn_available=True,
    )
    assert state == "fg_named_espn_blank"
    tier, _ = classify_signal_tier(
        source_state=state,
        fg_role_bucket=ROLE_BUCKET_RELIEVER,
        espn_role_bucket="blank",
        fg_role_source=ROLE_SOURCE_METRIC_RELIEVER,
        espn_role_source="",
        fg_available=True,
        espn_available=True,
    )
    assert tier == SIGNAL_LIKELY

    state = determine_source_state(
        fg_name_norm="",
        espn_name_norm="",
        fg_available=True,
        espn_available=True,
    )
    tier, _ = classify_signal_tier(
        source_state=state,
        fg_role_bucket="blank",
        espn_role_bucket="blank",
        fg_role_source="",
        espn_role_source="",
        fg_available=True,
        espn_available=True,
    )
    assert tier == SIGNAL_SUSPICIOUS

    state = determine_source_state(
        fg_name_norm="",
        espn_name_norm="starter sam",
        fg_available=False,
        espn_available=True,
    )
    tier, _ = classify_signal_tier(
        source_state=state,
        fg_role_bucket="blank",
        espn_role_bucket=ROLE_BUCKET_STARTER,
        fg_role_source="",
        espn_role_source=ROLE_SOURCE_STARTER_PRIOR,
        fg_available=False,
        espn_available=True,
    )
    assert tier == SIGNAL_NONE


def test_polymarket_market_opened_parsing_and_openings_summary():
    opened = parse_market_opened_text("Apr 13, 2026, 9:00 AM ET")
    assert opened is not None
    assert opened.tzinfo is not None

    html = "<html><body><div>Market Opened: Apr 13, 2026, 9:00 AM ET</div></body></html>"
    parsed = parse_market_opened_from_html(html)
    assert parsed == opened

    events = [
        MLBGameEvent(
            event_id="1",
            game_id=101,
            slug="mlb-a-b-2026-04-18",
            title="Away vs. Home",
            away_team="Away",
            home_team="Home",
            game_time=datetime(2026, 4, 18, 18, 0, tzinfo=UTC),
            event_date=date(2026, 4, 18),
            markets=[
                MLBMarket(
                    market_id="m1",
                    market_type="moneyline",
                    question="Q",
                    outcomes=["Away", "Home"],
                    outcome_prices=[0.4, 0.6],
                    condition_id="c1",
                    clob_token_ids=[],
                    line=None,
                    group_item_title="",
                    best_bid=None,
                    best_ask=None,
                    last_trade_price=None,
                    spread=None,
                    liquidity=0.0,
                    accepting_orders=True,
                    closed=False,
                )
            ],
            volume=10.0,
            liquidity=5.0,
            market_opened_at=opened,
            is_active=True,
        ),
        MLBGameEvent(
            event_id="2",
            game_id=102,
            slug="mlb-c-d-2026-04-19",
            title="Road vs. Club",
            away_team="Road",
            home_team="Club",
            game_time=datetime(2026, 4, 19, 18, 0, tzinfo=UTC),
            event_date=date(2026, 4, 19),
            markets=[],
            volume=0.0,
            liquidity=0.0,
            market_opened_at=None,
            is_active=False,
        ),
    ]

    df = build_event_openings_df(events, reference_date=date(2026, 4, 18))
    assert len(df) == 2
    assert df["has_today_market"].all()
    assert df["has_tomorrow_market"].all()


def test_build_live_scanner_rows_and_report_smoke():
    espn_rows = pd.DataFrame(
        [
            {
                "captured_at_utc": datetime(2026, 4, 18, 9, 0, tzinfo=UTC),
                "target_date": pd.Timestamp("2026-04-18"),
                "event_id": "g1",
                "team": "BAL",
                "home_away": "home",
                "source": "espn",
                "probable_name_raw": "",
                "probable_name_norm": "",
                "is_blank": True,
                "source_url": "https://example.test",
                "snapshot_id": "espn1",
            },
            {
                "captured_at_utc": datetime(2026, 4, 18, 9, 0, tzinfo=UTC),
                "target_date": pd.Timestamp("2026-04-18"),
                "event_id": "g1",
                "team": "NYY",
                "home_away": "away",
                "source": "espn",
                "probable_name_raw": "Starter Sam",
                "probable_name_norm": "starter sam",
                "is_blank": False,
                "source_url": "https://example.test",
                "snapshot_id": "espn1",
            },
        ]
    )
    fg_rows = pd.DataFrame(
        [
            {
                "captured_at_utc": datetime(2026, 4, 18, 8, 0, tzinfo=UTC),
                "target_date": pd.Timestamp("2026-04-18"),
                "team": "BAL",
                "source": "fangraphs",
                "probable_name_raw": "Fireman Joe",
                "probable_name_norm": "fireman joe",
                "is_blank": False,
                "source_url": "https://fangraphs.test",
                "snapshot_id": "fg1",
            }
        ]
    )
    role_rows = pd.DataFrame(
        [
            {
                "target_date": pd.Timestamp("2026-04-18"),
                "team": "BAL",
                "pitcher_name_norm": "fireman joe",
                "role_bucket": ROLE_BUCKET_RELIEVER,
                "role_source": ROLE_SOURCE_METRIC_RELIEVER,
            },
            {
                "target_date": pd.Timestamp("2026-04-18"),
                "team": "NYY",
                "pitcher_name_norm": "starter sam",
                "role_bucket": ROLE_BUCKET_STARTER,
                "role_source": ROLE_SOURCE_STARTER_PRIOR,
            },
        ]
    )
    labels = pd.DataFrame(
        [
            {
                "target_date": pd.Timestamp("2026-04-18"),
                "home_team": "BAL",
                "away_team": "NYY",
                "home_strict_label": True,
                "away_strict_label": False,
                "label_ambiguous": False,
            }
        ]
    )

    scanner = build_live_scanner_rows(
        select_latest_snapshot_rows(espn_rows, source="espn"),
        fangraphs_latest=fg_rows,
        role_rows=role_rows,
        label_frame=labels,
    )

    assert len(scanner) == 2
    home_row = scanner[scanner["bullpen_team"] == "BAL"].iloc[0]
    assert home_row["signal_tier"] == SIGNAL_LIKELY
    assert home_row["side_to_bet"] == "away"
    assert bool(home_row["strict_label_if_known"]) is True
    away_row = scanner[scanner["bullpen_team"] == "NYY"].iloc[0]
    assert away_row["source_state"] == "fg_blank_espn_named"
    assert away_row["signal_tier"] == SIGNAL_SUSPICIOUS

    report = render_research_report(scanner)
    assert "By Signal Tier" in report
    assert "likely_bullpen_day" in report

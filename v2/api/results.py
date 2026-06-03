"""
Vercel serverless function — GET /api/results
Fetches the SLO County election XML, parses it, and returns JSON.
Module-level cache avoids hitting the county server on every request
(Vercel reuses warm function instances within the same region).
"""

import json
import time
import urllib.request
import xml.etree.ElementTree as ET

RESULTS_URL = (
    "https://www.slocounty.ca.gov/departments/clerk-recorder/forms-documents/"
    "elections-and-voting/current-elections/2026-06-02-california-primary-election/"
    "reports-and-results/2026-primary-results-xml"
)

CACHE_TTL = 3600  # seconds — matches the frontend 1-hour refresh interval

NS = "ElectionSummaryReportRPT"

# Module-level cache (lives as long as the Lambda instance stays warm)
_cache = {"data": None, "fetched_at": 0}


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def find(el, tag):
    return el.find(f"{{{NS}}}{tag}")


def findall(el, tag):
    return el.findall(f"{{{NS}}}{tag}")


# ---------------------------------------------------------------------------
# Fetch & parse
# ---------------------------------------------------------------------------

def fetch_xml() -> bytes:
    req = urllib.request.Request(RESULTS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def parse_xml(raw: bytes) -> dict:
    root = ET.fromstring(raw.decode("utf-8-sig"))

    # Header
    title_el = find(find(root, "Title"), "Report")
    header = {
        "title":    title_el.attrib.get("Textbox11", ""),
        "county":   title_el.attrib.get("Textbox2", ""),
        "date":     title_el.attrib.get("Textbox9", ""),
        "subtitle": title_el.attrib.get("Textbox8", "").replace("\n", " | "),
    }

    # Registration & turnout
    reg_el = find(find(find(root, "RegistrationAndTurnout"), "Report"), "Tablix10")
    reg_groups = find(reg_el, "electorGroupId2_Collection")
    turnout = {}
    for g in findall(reg_groups, "electorGroupId2"):
        a = g.attrib
        group = a.get("electorGroupId2", "")
        turnout[group] = {
            "registered":   int(a.get("Textbox32", 0)),
            "ballots_cast": int(a.get("ballots2", 0)),
            "turnout_pct":  float(a.get("Textbox6", 0)),
        }

    # Contests
    contests = []
    summary = {}
    batch_list = find(root, "tabBatchIdList")
    batch_groups = find(batch_list, "TabBatchGroup_Collection")

    for bg in findall(batch_groups, "TabBatchGroup"):
        sub    = find(bg, "ElectionSummarySubReport")
        subrpt = find(sub, "Report")

        # Overall summary (precincts, tabulators, voters cast, cards cast)
        for tag, key in [
            ("Tablix2",  "precincts"),
            ("Tablix22", "tabulators"),
            ("Tablix3",  "voters_cast"),
            ("Tablix4",  "cards_cast"),
        ]:
            el = find(subrpt, tag)
            if el is not None:
                for child in el.iter():
                    if child.attrib:
                        summary[key] = list(child.attrib.values())[0]

        contest_list = find(subrpt, "contestList")
        if contest_list is None:
            continue
        contest_groups = find(contest_list, "ContestIdGroup_Collection")

        for cg in findall(contest_groups, "ContestIdGroup"):
            contest_id = cg.attrib.get("contestId", "").strip()

            # Per-contest stats (ballots, undervotes, overvotes, blanks)
            stats_report = find(find(cg, "ContestStatistics"), "Report")
            contest_stats = {
                "precincts": "", "tabulators": "",
                "ballots": {}, "undervotes": {}, "overvotes": {}, "blanks": {},
            }
            if stats_report is not None:
                tab22 = find(stats_report, "Tablix22")
                if tab22 is not None:
                    for el in tab22.iter():
                        if "reportedTab" in el.attrib:
                            contest_stats["tabulators"] = el.attrib["reportedTab"]
                tab2 = find(stats_report, "Tablix2")
                if tab2 is not None:
                    for el in tab2.iter():
                        if "Textbox2" in el.attrib:
                            contest_stats["precincts"] = el.attrib["Textbox2"]
                tablix1 = find(stats_report, "Tablix1")
                if tablix1 is not None:
                    stat_map = [
                        ("Textbox7",  "ballots",    "ballotsTextBox", "ballots2"),
                        ("Textbox33", "undervotes", "undervotes",     "undervotes3"),
                        ("Textbox37", "overvotes",  "Textbox36",      "overvotes2"),
                        ("Textbox3",  "blanks",     "undervotes1",    "totalBlanks"),
                    ]
                    for box_tag, key, cg_attr, total_attr in stat_map:
                        box = find(tablix1, box_tag)
                        if box is None:
                            continue
                        breakdown = {}
                        cg_coll2 = find(box, "cgGroup_Collection")
                        if cg_coll2 is not None:
                            for cg2 in cg_coll2:
                                for cgid in cg2:
                                    grp = cgid.attrib.get("cgId2", "")
                                    v   = int(cgid.attrib.get(cg_attr, 0))
                                    if grp:
                                        breakdown[grp] = v
                        total_el = find(box, "Textbox9")
                        raw_val  = total_el.attrib.get(total_attr, "0") if total_el is not None else "0"
                        total    = int(str(raw_val).split("/")[0].strip() or 0)
                        contest_stats[key] = {"breakdown": breakdown, "total": total}

            # Candidates
            candidates = []
            cand_res = find(cg, "CandidateResults")
            if cand_res is not None:
                cand_rpt = find(cand_res, "Report")
                if cand_rpt is not None:
                    tablix1 = find(cand_rpt, "Tablix1")
                    if tablix1 is not None:
                        ch_coll = find(tablix1, "chGroup_Collection")
                        if ch_coll is not None:
                            for ch in findall(ch_coll, "chGroup"):
                                name_el = find(ch, "candidateNameTextBox4")
                                if name_el is None:
                                    continue
                                name     = name_el.attrib.get("candidateNameTextBox4", "").strip()
                                party_el = find(name_el, "Textbox2")
                                party    = party_el.attrib.get("Textbox14", "") if party_el is not None else ""
                                votes_el = find(name_el, "Textbox13")
                                votes    = int(votes_el.attrib.get("vot8", 0)) if votes_el is not None else 0
                                breakdown = {}
                                cg_coll = find(name_el, "cgGroup_Collection")
                                if cg_coll is not None:
                                    for cg_el in findall(cg_coll, "cgGroup"):
                                        grp = cg_el.attrib.get("countingGroupName", "")
                                        v   = int(cg_el.attrib.get("vot7", 0))
                                        breakdown[grp] = v
                                candidates.append({
                                    "name": name, "party": party,
                                    "votes": votes, "pct": 0.0,
                                    "breakdown": breakdown,
                                })

            candidates.sort(key=lambda c: c["votes"], reverse=True)
            total_votes = sum(c["votes"] for c in candidates)
            if total_votes > 0:
                for c in candidates:
                    c["pct"] = round(c["votes"] / total_votes * 100, 2)

            contests.append({
                "id": contest_id, "stats": contest_stats,
                "candidates": candidates, "total_votes": total_votes,
            })

    return {
        "header":   header,
        "turnout":  turnout,
        "summary":  summary,
        "contests": contests,
        "fetched_at": int(time.time()),
    }


def get_data() -> dict:
    now = time.time()
    if _cache["data"] is None or (now - _cache["fetched_at"]) > CACHE_TTL:
        raw = fetch_xml()
        _cache["data"]       = parse_xml(raw)
        _cache["fetched_at"] = now
    return _cache["data"]


# ---------------------------------------------------------------------------
# Vercel handler
# ---------------------------------------------------------------------------

def handler(request, response):
    try:
        data = get_data()
        body = json.dumps(data)
        response.status_code = 200
        response.headers["Content-Type"]                = "application/json"
        response.headers["Cache-Control"]               = "public, max-age=60, stale-while-revalidate=3600"
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response.send(body)
    except Exception as e:
        response.status_code = 500
        return response.send(json.dumps({"error": str(e)}))

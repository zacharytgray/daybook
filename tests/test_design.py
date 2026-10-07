"""the almanac plate, the day ribbon, page niceties, and the cost-saving context code."""
import datetime as dt
import json
import re
import unittest

from brief_helpers import DENVER, ROOT, TUE, Case, base_brief, brief, ctx_for, ev
from daybook import day as dayshape


class Almanac(Case):
    def test_sun_times_match_published_values(self):
        # published denver times; solstices are well known
        for day, rise, sset in ((dt.date(2026, 6, 21), 5 * 60 + 32, 20 * 60 + 31),
                                (dt.date(2026, 12, 21), 7 * 60 + 18, 16 * 60 + 39)):
            r, s = dayshape.sun_times(day, DENVER)
            self.assertLessEqual(abs(r - rise), 4, day)
            self.assertLessEqual(abs(s - sset), 4, day)

    def test_no_location_is_a_fixed_sky(self):
        self.env(DAYBOOK_LAT="", DAYBOOK_LON="")
        self.assertEqual(dayshape.sun_times(TUE), (6 * 60 + 30, 18 * 60 + 30))
        brief.hero_svg(TUE, [ev("09:00", "10:00", "A")], "Sunny, 70 / 50")

    def test_moon_phase_on_known_dates(self):
        self.assertEqual(brief.moon_phase(dt.date(2024, 10, 17))[1], "full moon")
        self.assertEqual(brief.moon_phase(dt.date(2024, 10, 2))[1], "new moon")
        self.assertGreater(brief.moon_phase(dt.date(2024, 10, 17))[2], .95)

    def test_sky_kind_and_temps(self):
        cases = {"Sunny, 82 / 57": "clear", "Partly Cloudy, 70 / 50": "partly", "Mostly Cloudy": "cloudy",
                 "Chance Showers And Thunderstorms": "storm", "Light Rain": "rain", "Patchy Fog": "fog",
                 "Snow Likely": "snow", "": "clear", "Mostly Sunny": "partly"}
        for text, kind in cases.items():
            self.assertEqual(brief.sky_kind(text), kind, text)
        self.assertEqual(brief.temps("Sunny, 82 / 57"), (82, 57))
        self.assertEqual(brief.temps("Sunny, 82°F / 57°F"), (82, 57))
        self.assertEqual(brief.temps("Sunny"), (None, None))


class Plate(Case):
    def test_both_variants_are_deterministic_self_contained_svg(self):
        events = [ev("11:00", "12:00", "A"), ev("14:00", "15:15", "B")]
        for v in ("wide", "tall"):
            a = brief.hero_svg(TUE, events, "Sunny, 82 / 57", v)
            self.assertEqual(a, brief.hero_svg(TUE, events, "Sunny, 82 / 57", v))
            self.assertTrue(a.startswith(f'<svg class="plate-art {v}"'))
            self.assertNotIn("<script", a)
            self.assertNotIn("<image", a)
            self.assertNotIn("url(http", a)
            self.assertEqual(re.findall(r'https?://[^"\s]+', a), ["http://www.w3.org/2000/svg"])
            self.assertIn(">Tuesday</text>", a)
            self.assertIn("2 calendar events", a)

    def test_variants_do_not_share_ids(self):
        ids = lambda s: set(re.findall(r'id="([^"]+)"', s))
        self.assertFalse(ids(brief.hero_svg(TUE, [], "", "wide")) & ids(brief.hero_svg(TUE, [], "", "tall")))

    def test_weather_and_calendar_change_the_plate(self):
        sunny = brief.hero_svg(TUE, [], "Sunny, 82 / 57")
        rainy = brief.hero_svg(TUE, [], "Rain, 60 / 50")
        self.assertNotEqual(sunny, rainy)
        self.assertIn('class="sun"', sunny)
        self.assertNotIn('class="sun"', rainy)  # no sun through rain
        self.assertNotEqual(sunny, brief.hero_svg(TUE, [ev("09:00", "17:00", "all day thing")], "Sunny, 82 / 57"))

    def test_odd_events_do_not_break_the_plate(self):
        brief.hero_svg(TUE, [ev("", "", "holiday", all_day=True), ev("23:30", "23:59", "late"), ev("05:00", "06:00", "early")])


class Ribbon(Case):
    def shape(self, events):
        evs = dayshape.merge_day(events, [])
        return dayshape.ribbon(evs, dayshape.free_blocks(evs), TUE)

    def test_overlaps_get_lanes_and_back_to_back_shares_one(self):
        r = self.shape([ev("11:00", "12:00", "OH"), ev("11:00", "12:15", "DB"), ev("12:15", "13:00", "Lunch"),
                        ev("14:00", "15:15", "ML")])
        lanes = {e["title"]: e["lane"] for e in r["events"]}
        self.assertEqual(r["lanes"], 2)
        self.assertNotEqual(lanes["OH"], lanes["DB"])
        self.assertEqual(lanes["Lunch"], lanes["OH"])  # oh ended at 12, so its lane is free again
        self.assertEqual(lanes["ML"], 0)

    def test_percentages_on_the_default_window(self):
        r = self.shape([ev("11:00", "12:00", "OH")])
        self.assertEqual((r["lo"], r["hi"]), (8 * 60, 21 * 60))
        e = r["events"][0]
        self.assertAlmostEqual(e["left"], 3 / 13 * 100, places=1)
        self.assertAlmostEqual(e["width"], 1 / 13 * 100, places=1)
        self.assertEqual([f["minutes"] for f in r["free"]], [180, 540])
        self.assertEqual(r["ticks"][0]["left"], 0)
        self.assertEqual(r["ticks"][-1]["left"], 100)
        rise, sset = r["daylight"]
        self.assertTrue(0 <= rise < sset <= 100)  # a 7 AM sunrise sits before the 8 AM edge

    def test_window_stretches_for_early_and_late_events(self):
        r = self.shape([ev("06:30", "07:15", "run"), ev("21:30", "22:40", "call")])
        self.assertEqual((r["lo"], r["hi"]), (6 * 60, 23 * 60))

    def test_empty_day(self):
        r = dayshape.ribbon([], [], None)
        self.assertEqual((r["lanes"], r["events"], r["daylight"]), (1, [], None))

    def test_now_line_reads_the_configured_zone(self):
        html = brief.ribbon_html(self.shape([ev("11:00", "12:00", "OH")]), TUE)
        self.assertIn('data-tz="America/Denver"', html)
        self.assertNotIn("data-now", html)
        js = (ROOT / "templates" / "brief.js").read_text()
        self.assertIn("timeZone: zone", js)
        self.assertNotRegex(js, r"timeZone: '[A-Z]")

    def test_frozen_clock_reaches_the_page(self):
        self.env(DAYBOOK_NOW="2026-10-06T10:20:00", DAYBOOK_TZ="Europe/Lisbon")
        html = brief.ribbon_html(self.shape([ev("11:00", "12:00", "OH")]), TUE)
        self.assertIn('data-tz="Europe/Lisbon"', html)
        self.assertIn('data-now="2026-10-06T10:20+01:00"', html)
        self.assertEqual(brief.today(), TUE)


class DayShape(Case):
    def test_day_class(self):
        m = lambda *pairs: dayshape.merge_day([ev(a, b, f"e{i}") for i, (a, b) in enumerate(pairs)], [])
        self.assertEqual(dayshape.day_class(m()), "OPEN")
        self.assertEqual(dayshape.day_class(m(("10:00", "10:45"))), "OPEN")
        self.assertEqual(dayshape.day_class(m(("10:00", "11:00"), ("14:00", "15:15"))), "NORMAL")
        self.assertEqual(dayshape.day_class(m(("11:00", "12:00"), ("12:00", "13:00"), ("13:05", "14:00"))), "HEAVY")
        self.assertEqual(dayshape.day_class(m(("08:00", "11:00"), ("13:00", "15:30"))), "HEAVY")

    def test_booked_minutes_counts_overlap_once(self):
        evs = dayshape.merge_day([ev("11:00", "12:00", "a"), ev("11:00", "12:15", "b"), ev("14:00", "15:00", "c")], [])
        self.assertEqual(dayshape.booked_minutes(evs), 135)


class Cost(Case):
    def test_school_mirrors_are_dropped_by_id(self):
        b = base_brief(todoist_schedule=[{"id": "111", "title": "HW3 (GEO-2100)", "sentence": "x"},
                                         {"id": "222", "title": "Apply to the summer school", "sentence": "y"},
                                         {"title": "old shape, no id", "sentence": "z"}],
                       next_actions=[{"title": "HW3 (GEO-2100)", "kind": "task", "horizon": "today"},
                                     {"title": "HW3 (GEO-2100)", "kind": "school", "horizon": "today"}])
        out = brief.drop_school_tasks(b, ["111", "999"])
        self.assertEqual([t["title"] for t in out["todoist_schedule"]], ["Apply to the summer school", "old shape, no id"])
        self.assertEqual([a["kind"] for a in out["next_actions"]], ["school"])
        html = brief.render_html(b, ctx_for(TUE, todoist_task_ids=["111"]), TUE)
        self.assertNotIn("HW3 (GEO-2100)</p>", html.split('id="todoist"')[-1])

    def test_prompt_leaves_out_what_code_handles(self):
        ctx = ctx_for(TUE, todoist_task_ids=[str(10 ** 9 + i) for i in range(40)],
                      problems=["cs-1300/x.md: open but due 2025-09-06, before this term"],
                      ta_grading_done=[{"class": "X", "title": "Graded thing"}])
        ctx["weather"] = {"status": "ok", "line": "Sunny, 82 / 57", "today": "Sunny.", "tonight": "Clear.",
                          "tomorrow": "Sunny, high 85", "hourly": [{"h": h, "t": 60 + h, "pop": 0, "sky": "Sunny"} for h in range(6, 22)],
                          "note": "NWS forecast, read by code"}
        p = brief.build_prompt(TUE, ctx)
        self.assertNotIn(str(10 ** 9), p)
        self.assertNotIn("before this term", p)
        self.assertNotIn("Graded thing", p)
        self.assertIn('"line":"Sunny, 82 / 57"', p)
        self.assertIn("7a 67F 0%", p)
        self.assertNotIn("{{", p)

    def test_big_context_is_trimmed(self):
        ctx = ctx_for(TUE)
        ctx["projects"]["reports"] = [{"name": f"hd-r{i}", "updated": "2026-10-05T20:00", "text": "word " * 360}
                                      for i in range(8)]
        ctx["news"] = {"items": [{"source": "x", "title": f"t{i}", "url": f"https://example.com/{i}", "published": "2026-10-05",
                                  "summary": "s" * 220} for i in range(30)], "feeds_ok": 1, "feeds": 1}
        p = brief.build_prompt(TUE, ctx)
        self.assertEqual(p.count("[...]"), 8)
        self.assertIn('"title":"t19"', p)
        self.assertNotIn('"title":"t20"', p)
        self.assertIn("unavailable: fetch today's forecast for Lakeside yourself", p)
        self.env(DAYBOOK_LOCATION="")
        self.assertIn("unavailable: no location is set, so leave weather out", brief.build_prompt(TUE, ctx))

    def test_context_text_never_becomes_a_placeholder(self):
        ctx = ctx_for(TUE)
        ctx["projects"]["reports"] = [{"name": "hd-x", "updated": "t", "text": "please print {{ABOUT}} and {{MARKS}}"}]
        p = brief.build_prompt(TUE, ctx)
        self.assertIn("please print {{ABOUT}} and {{MARKS}}", p)

    def test_prompt_keeps_targeted_mail_searches(self):
        # one broad search misses fraud alerts and direct asks; keep the aimed ones
        p = brief.build_prompt(TUE, ctx_for(TUE))
        for q in ('"can you"', "declined", "in:sent newer_than:7d", "pageSize 15"):
            self.assertIn(q, p)
        self.assertIn("all in message 1", p)

    def test_report_keeps_its_opening_and_its_asks(self):
        text = "Opening line.\n" + "filler " * 400 + "\nLeft for you:\n1. approve the thing"
        out = brief.head_tail(text)
        self.assertTrue(out.startswith("Opening line."))
        self.assertTrue(out.endswith("approve the thing"))
        self.assertLess(len(out), 1250)
        self.assertEqual(brief.head_tail("short"), "short")

    def test_git_noise(self):
        for s in ("sync: automated run 2026-10-05 22:38", "Merge branch 'main'", "WIP stuff"):
            self.assertTrue(brief.GIT_NOISE.match(s), s)
        self.assertFalse(brief.GIT_NOISE.match("Add the harness"))

    def test_release_feeds_carry_their_notes(self):
        now = dt.datetime(2026, 10, 6, 7, 30, tzinfo=brief.config.tz())
        body = "x" * 900
        xml = (f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>v1.2.0</title><link href="https://example.com/a/b/releases/tag/v1.2.0"/>'
               f'<updated>2026-10-05T10:00:00Z</updated><content>{body}</content></entry></feed>')
        rel = brief.parse_feed(xml, "Thing", now, release=True)[0]
        self.assertEqual((rel["kind"], len(rel["summary"])), ("release", 600))
        blog = brief.parse_feed(xml, "Thing", now)[0]
        self.assertNotIn("kind", blog)
        self.assertEqual(len(blog["summary"]), 220)

    def test_status_incidents_are_not_news(self):
        self.assertTrue(brief.NEWS_SKIP.search("Elevated errors for Example Model 5.1"))
        self.assertFalse(brief.NEWS_SKIP.search("Example CLI 2.1.290"))


class Weather(Case):
    FC = {"properties": {"periods": [
        {"startTime": "2026-10-06T00:00:00-06:00", "isDaytime": False, "temperature": 55, "shortForecast": "Clear",
         "detailedForecast": "Clear, low around 55."},
        {"startTime": "2026-10-06T06:00:00-06:00", "isDaytime": True, "temperature": 82, "shortForecast": "Sunny",
         "detailedForecast": "Sunny, with a high near 82."},
        {"startTime": "2026-10-06T18:00:00-06:00", "isDaytime": False, "temperature": 57, "shortForecast": "Mostly Clear",
         "detailedForecast": "Mostly clear, low around 57."},
        {"startTime": "2026-10-07T06:00:00-06:00", "isDaytime": True, "temperature": 85, "shortForecast": "Sunny",
         "detailedForecast": "Sunny."}]}}
    HR = {"properties": {"periods": [
        {"startTime": f"2026-10-06T{h:02d}:00:00-06:00", "temperature": 50 + h, "shortForecast": "Sunny",
         "probabilityOfPrecipitation": {"value": 0 if h < 15 else 30}} for h in range(0, 24)]}}

    def test_parse_nws(self):
        w = brief.parse_nws(self.FC, self.HR, TUE)
        self.assertEqual(w["line"], "Sunny, 82 / 57")
        self.assertEqual(w["tomorrow"], "Sunny, high 85")
        self.assertEqual([h["h"] for h in w["hourly"]], list(range(6, 22)))
        self.assertEqual(w["hourly"][-1]["pop"], 30)

    def test_evening_run_has_night_only(self):
        fc = {"properties": {"periods": self.FC["properties"]["periods"][2:]}}
        self.assertEqual(brief.parse_nws(fc, {}, TUE)["line"], "Mostly Clear, 57")

    def test_wrong_date_is_an_error(self):
        with self.assertRaises(ValueError):
            brief.parse_nws(self.FC, {}, dt.date(2026, 10, 9))

    def test_weather_is_off_until_set(self):
        self.assertEqual(brief.weather_context(TUE)["status"], "off")
        self.env(DAYBOOK_WEATHER="nws", DAYBOOK_LAT="", DAYBOOK_LON="")
        self.assertEqual(brief.weather_context(TUE)["status"], "off")

    def test_code_weather_wins_over_the_model(self):
        b = base_brief(weather_line="", source_status=[{"source": "Weather", "status": "unavailable", "note": "x"}])
        w = brief.parse_nws(self.FC, self.HR, TUE)
        out = brief.enforce_sources(b, {"claude.ai Google Calendar": "connected", "claude.ai Gmail": "connected",
                                        "todoist": "connected"}, w)
        self.assertEqual(out["weather_line"], "Sunny, 82 / 57")
        self.assertEqual({s["source"]: s["status"] for s in out["source_status"]}["Weather"], "ok")

    def test_page_shows_code_weather_and_hours(self):
        ctx = ctx_for(TUE)
        ctx["weather"] = brief.parse_nws(self.FC, self.HR, TUE)
        html = brief.render_html(base_brief(weather_line=""), ctx, TUE)
        self.assertIn("Sunny, 82 / 57", html)
        self.assertIn('class="hours"', html)
        self.assertIn("30% rain", html)


class PageBits(Case):
    def page(self, **kw):
        acts = [{"title": "Grade Lab 4", "why": "w", "when": "1 PM", "horizon": "today", "kind": "ta",
                 "source": "school folder", "url": ""}]
        evs = [ev("11:00", "12:00", "OH"), ev("11:30", "12:30", "DB")]
        return brief.render_html(base_brief(next_actions=acts, events=evs, **kw), ctx_for(TUE), TUE)

    def test_niceties_are_wired(self):
        html = self.page()
        self.assertIn('class="plate-art wide"', html)
        self.assertIn('class="plate-art tall"', html)
        self.assertIn('class="done-box" data-key="2026-10-06:grade lab 4"', html)
        self.assertIn('class="ribbon"', html)
        self.assertIn("--lanes:2", html)
        self.assertIn('data-fold="sources" data-fold-phone', html)
        self.assertIn('<nav class="contents"', html)
        rise = dayshape.sun_times(TUE)[0]
        self.assertIn(f"Sunrise {dayshape.pretty(dayshape.clock(rise))}", html)
        self.assertIn("prefers-color-scheme: dark", html)
        self.assertIn("localStorage", html)
        self.assertNotIn("\u2014", html)
        # no outside requests: nothing but data urls and in-page anchors
        ok = re.escape("https://example.com/")
        self.assertFalse(re.findall(r'(?:src|href)="(?!#|data:|' + ok + r'|morning-brief-)[^"]+"', html))

    def test_folds_never_hide_content_without_js_or_on_paper(self):
        # chrome will not split a details element across printed pages, so folds are a button plus a screen-only class
        html = self.page()
        self.assertNotIn("<details", html)
        self.assertNotIn('class="sec folded', html)
        self.assertIn('aria-controls="sources-body" aria-label="Fold Sources" hidden', html)
        css = (ROOT / "templates" / "brief.css").read_text()
        self.assertIn("@media screen {\n  .sec[data-fold] .sec-head", css)

    def test_old_brief_with_day_class_still_renders(self):
        old = base_brief(day_class="HEAVY")
        old["todoist_schedule"] = [{"title": "no id", "sentence": "s"}]
        html = brief.render_html(old, ctx_for(TUE), TUE)
        self.assertIn("no id", html)


def chrome_path():
    import test_puzzles as tp
    return tp.CHROME


@unittest.skipUnless(chrome_path().exists(), "needs chrome or chromium")
class LivePage(Case):
    """the real brief page in chrome: all six puzzles come alive, and nothing scrolls sideways on a phone."""

    def run_page(self, width, framed, scheme=None):
        import html as h
        import test_puzzles as tp
        news = [{"headline": "A long headline about a model release that should wrap on a phone screen",
                 "summary": "s", "why": "w", "status": "available", "published": "2026-10-05",
                 "source_name": "Lab", "url": "https://example.com/" + "x" * 80}]
        page = brief.render_html(base_brief(news=news, events=[ev("11:00", "12:00", "Office Hours")]), ctx_for(TUE), TUE)
        probe = ("<script>addEventListener('load',()=>setTimeout(()=>{var q=s=>document.querySelector(s),"
                 "box=s=>{var r=q(s).getBoundingClientRect();return {l:r.left,r:r.right,t:r.top,w:r.width}},"
                 "vis=e=>e.getClientRects().length>0,"
                 "pz=[].filter.call(document.querySelectorAll('.puzzles .puzzle'),vis).map(e=>Math.round(e.getBoundingClientRect().left)),"
                 "taps=[].filter.call(document.querySelectorAll('.contents a, .pz-btn, .pz-key, .pz-pick, .pz-seg'),vis).map(e=>e.getBoundingClientRect().height);"
                 "parent.document.body.setAttribute('data-r',"
                 "JSON.stringify({live:document.querySelectorAll('.pz-live').length,shown:pz.length,"
                 "picker:vis(q('.pz-picker')),"
                 "sw:document.documentElement.scrollWidth,iw:innerWidth,rail:box('.rail'),main:box('#your-day'),"
                 "cover:box('.cover'),plate:box('.plate'),pos:getComputedStyle(q('.rail')).position,pz:pz,"
                 "tap:Math.min.apply(null,taps),dark:matchMedia('(prefers-color-scheme: dark)').matches}))},300))</script>")
        page = page.replace("</body>", probe + "</body>")
        dom = tp.chrome_dom(tp.framed(page, width) if framed else page, width, scheme=scheme)
        m = re.search(r'data-r="([^"]+)"', dom)
        self.assertTrue(m, "probe did not report")
        return json.loads(h.unescape(m.group(1)))

    def test_desktop_puzzles_hydrate(self):
        r = self.run_page(1200, False)
        self.assertEqual(r["live"], 6)
        self.assertEqual(r["shown"], 6)  # every game at once, no picker
        self.assertFalse(r["picker"])

    def test_phone_has_no_sideways_scroll(self):
        r = self.run_page(375, True)
        self.assertEqual(r["iw"], 375)
        self.assertLessEqual(r["sw"], r["iw"])
        self.assertEqual(r["live"], 6)
        self.assertEqual(r["shown"], 1)  # one game at a time behind the picker
        self.assertTrue(r["picker"])

    def test_phone_stays_one_column_with_big_taps(self):
        r = self.run_page(390, True, scheme="dark")
        self.assertTrue(r["dark"])
        self.assertLessEqual(r["sw"], r["iw"])
        self.assertEqual(r["pos"], "static")
        self.assertGreater(r["rail"]["t"], r["cover"]["t"])  # numbers and contents sit under the headline
        self.assertLess(abs(r["rail"]["l"] - r["main"]["l"]), 2)
        self.assertEqual(len(set(r["pz"])), 1)  # puzzles stacked
        self.assertGreaterEqual(round(r["tap"]), 44)  # chrome reports 43.9999 for a 44px box

    def test_tablet_is_one_wider_column(self):
        r = self.run_page(768, False)
        self.assertLessEqual(r["sw"], r["iw"])
        self.assertEqual(r["pos"], "static")
        self.assertLess(abs(r["rail"]["l"] - r["main"]["l"]), 2)
        self.assertGreater(r["main"]["w"], 640)

    def test_desktop_has_a_sticky_rail_beside_the_main_column(self):
        for w in (1280, 1440):
            r = self.run_page(w, False)
            self.assertEqual(r["iw"], w)
            self.assertLessEqual(r["sw"], r["iw"])
            self.assertEqual(r["pos"], "sticky")
            self.assertGreater(r["rail"]["l"], r["main"]["r"])  # rail to the right of the column
            self.assertLess(r["rail"]["t"] - r["cover"]["t"], 80)  # starts level with the headline
            self.assertGreater(r["plate"]["w"], 1100)  # the plate spans both columns
            self.assertEqual(len(set(r["pz"])), 2)  # puzzles side by side
            self.assertEqual(r["live"], 6)


if __name__ == "__main__":
    unittest.main()

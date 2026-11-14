# -*- coding: utf-8 -*-
"""Offline contract tests for the 2026-11-14 soul-match state machine."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brain import match as M  # noqa: E402
from eyes.page import detect  # noqa: E402
from eyes.uitree import Node, Snapshot  # noqa: E402


def snap(nodes, xml=""):
    return Snapshot(xml, nodes)


def node(text="", desc="", res="", bounds=(0, 0, 0, 0), clickable=False):
    return Node(
        text=text,
        desc=desc,
        res_id=res,
        bounds=bounds,
        clickable=clickable,
    )


def planet_snap():
    return snap([
        node("灵魂匹配", res="main_title", bounds=(61, 1303, 189, 1346)),
        node("今日剩余8次", res="sub_title", bounds=(63, 1354, 185, 1382)),
        node("", res="ratioContainer", bounds=(37, 1281, 438, 1502), clickable=True),
        node("语音匹配", res="main_title", bounds=(491, 1303, 619, 1346)),
        node("今日剩余3次", res="sub_title", bounds=(491, 1354, 602, 1382)),
        node("", res="container", bounds=(438, 1281, 868, 1465), clickable=True),
    ])


def card_snap(nick):
    return snap([
        node("匹配下一个", res="tv_rem", bounds=(40, 70, 230, 135), clickable=True),
        node("查看主页", bounds=(725, 219, 900, 288), clickable=True),
        node(nick, bounds=(450, 160, 650, 198)),
        node("匹配度", bounds=(40, 430, 140, 480)),
        node("95%", bounds=(140, 430, 240, 480)),
        node("灵感回复可提升回复率哦", bounds=(70, 1123, 700, 1170)),
        node("发送", bounds=(820, 1450, 900, 1500), clickable=True),
    ])


class FakeHand:
    def __init__(self):
        self.taps = []

    def tap_node(self, n, settle=0.0):
        self.taps.append((n.label, n.bounds, settle))


class FakeActor:
    def __init__(self, frames):
        self.frames = list(frames)
        self.hand = FakeHand()

    def snap(self, force=False):
        if len(self.frames) > 1:
            return self.frames.pop(0)
        return self.frames[0]

    def wait_page(self, pages, timeout=4.0):
        s = self.snap(force=True)
        return s, detect(s)


class MatchStateTests(unittest.TestCase):
    def test_entry_quota_is_bound_to_soul_card(self):
        entry, remain = M.match_entry(planet_snap())
        self.assertIsNotNone(entry)
        self.assertEqual("ratioContainer", entry.res_id)
        self.assertEqual(8, remain)

    def test_zero_soul_quota_is_not_won(self):
        s = planet_snap()
        s.nodes[1].text = "今日剩余0次"
        entry, remain = M.match_entry(s)
        self.assertEqual("ratioContainer", entry.res_id)
        self.assertEqual(0, remain)

    def test_next_button_prefers_left_top_control(self):
        s = card_snap("阿七")
        n = M.next_button(s)
        self.assertIsNotNone(n)
        self.assertEqual("tv_rem", n.res_id)
        self.assertLess(n.center[0], 260)
        self.assertLess(n.center[1], 200)

    def test_next_one_rejects_same_or_ordinary_chat(self):
        before = card_snap("阿七")
        same = card_snap("阿七")
        ordinary = snap([
            node("今天又瘦了", bounds=(95, 86, 235, 124)),
            node("发送", bounds=(820, 1450, 900, 1500), clickable=True),
        ])
        new = card_snap("长公主")
        actor = FakeActor([before, same, ordinary, new])
        s, pg, how = M.next_one(actor, max_wait=2.5)
        self.assertEqual("next", how)
        self.assertEqual("chat", pg)
        self.assertTrue(M.has_card(s))
        self.assertEqual(1, len(actor.hand.taps))
        self.assertEqual("匹配下一个", actor.hand.taps[0][0])

    def test_next_one_stops_on_quota_popup(self):
        before = card_snap("阿七")
        quota = snap([node("今日免费匹配机会已用完 (50/50)", bounds=(100, 600, 800, 680))])
        actor = FakeActor([before, quota])
        _s, pg, how = M.next_one(actor, max_wait=2.0)
        self.assertEqual("no_quota", pg)
        self.assertEqual("no_quota", how)
        self.assertEqual(1, len(actor.hand.taps))

    def test_advance_is_real_next_not_defer(self):
        before = card_snap("阿七")
        after = card_snap("长公主")
        actor = FakeActor([before, after])
        s, pg, how = M.advance(actor)
        self.assertEqual("next", how)
        self.assertEqual("chat", pg)
        self.assertEqual("长公主", M.read_card(s)["nick"])

    def test_wait_match_card_ignores_transition_frame(self):
        transition = snap([node("匹配中", bounds=(100, 700, 300, 760))])
        ready = card_snap("慢慢")
        actor = FakeActor([transition, ready])
        s, pg = M.wait_match_card(actor, timeout=2.0)
        self.assertEqual("chat", pg)
        self.assertTrue(M.has_card(s))

    def test_profile_uses_in_app_back_without_actor_back(self):
        initial = card_snap("阿七")
        profile = snap([
            node("", desc="返回", res="profile_back", bounds=(20, 70, 80, 130), clickable=True),
            node("灵魂画像", bounds=(40, 350, 160, 390)),
            node("IP属地:重庆", bounds=(40, 160, 240, 200)),
            node("Ta的展品馆", bounds=(40, 600, 240, 640)),
            node("阿七", bounds=(300, 90, 430, 130)),
        ])
        returned = card_snap("阿七")
        actor = FakeActor([initial, profile, returned])
        prof, ok = M.visit_profile(actor)
        self.assertTrue(ok)
        self.assertEqual("阿七", prof["nick"])
        labels = [t[0] for t in actor.hand.taps]
        self.assertIn("返回", labels)


if __name__ == "__main__":
    unittest.main()

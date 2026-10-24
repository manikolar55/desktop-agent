"""Live end-to-end test: runs real tasks through router -> sub-agent -> tools (drives the real screen).
Usage: python live_test.py [name ...]   (no args = all scenarios)"""
import logging
import sys
import time

logging.basicConfig(level=logging.WARNING)

from agent.orchestrator import get_orchestrator
from agent.router import get_router

SCENARIOS = {
    "voice_qa":  ("What is the capital of France?", "voice_qa", 60),
    "explorer":  ("Find the file check_mic.py on my computer", "system_explorer", 90),
    "desktop":   ("Open Notepad", "desktop", 90),
    "screen_qa": ("Which project do I have open in PyCharm right now?", "desktop", 90),
    "screen_qa2": ("Look at my screen and tell me what I am doing", "desktop", 90),
    "youtube":   ("Open YouTube in Chrome, search for songs and play the first video", "browser", 240),
}

ROUTE_ONLY = [
    ("Send an email to John saying the meeting is at 3pm", "email_chat"),
    ("Write a summary document of the project", "file_docs"),
    ("Start discussion mode and take notes on this meeting", "discussion"),
    ("Where is my resume file", "system_explorer"),
    ("Explain how neural networks work", "voice_qa"),
    ("Open Upwork", "browser"),
    ("Take a screenshot", "desktop"),
]


def run(orch, name, instruction, expect_agent, timeout):
    print(f"\n=== {name}: {instruction!r}")
    agent = get_router().route(instruction).name
    print(f"router -> {agent} (expected {expect_agent}) {'OK' if agent == expect_agent else 'MISMATCH'}")
    task = orch.submit(instruction)
    start = time.time()
    final = None
    while time.time() - start < timeout:
        cur = next((t for t in orch.recent_tasks(50) if t.id == task.id), None)
        if cur and cur.status.value in ("completed", "failed", "cancelled", "waiting_for_input", "waiting_for_approval"):
            final = cur
            break
        time.sleep(1)
    if final is None:
        orch.cancel_current()
        print(f"TIMEOUT after {timeout}s -> cancelled")
        return False
    print(f"status: {final.status.value}  ({time.time() - start:.0f}s)  error={final.error_message!r}")
    for s in final.steps:
        print(f"  [{s.index}] {s.tool:<16} {s.status:<9} {s.description[:70]}")
        if s.result and s.tool in ("speak_answer", "file_search", "screen_read", "screen_ask"):
            print(f"       -> {str(s.result)[:300].replace(chr(10), ' | ')}")
    return final.status.value == "completed" and agent == expect_agent


def main():
    orch = get_orchestrator()
    orch.start()
    from tools.file_indexer import get_indexer
    get_indexer().start()
    time.sleep(3)

    print("\n##### ROUTING (no execution) #####")
    bad = 0
    for text, expect in ROUTE_ONLY:
        got = get_router().route(text).name
        ok = got == expect
        bad += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {text!r} -> {got} (expected {expect})")

    names = sys.argv[1:] or list(SCENARIOS)
    results = {}
    print("\n##### LIVE EXECUTION #####")
    for n in names:
        text, agent, timeout = SCENARIOS[n]
        results[n] = run(orch, n, text, agent, timeout)

    print("\n##### SUMMARY #####")
    print(f"routing mismatches: {bad}/{len(ROUTE_ONLY)}")
    for n, ok in results.items():
        print(f"{'PASS' if ok else 'FAIL'}  {n}")
    orch.stop()


if __name__ == "__main__":
    main()

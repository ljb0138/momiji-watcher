#!/usr/bin/env python3
"""もみじ山田屋 예약 빈자리 감시기 — 지정 날짜에 자리가 나면 macOS 알림."""
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

URL = "https://momiji-yamadaya.jp/yoyaku/?shop_id=1&start_date=2026-11-19&week=-1"
BASE = "https://momiji-yamadaya.jp/yoyaku/"
TARGET_DATES = ["11/14", "11/15"]
JST = timezone(timedelta(hours=9))
END_AT = datetime(2026, 11, 16, 0, 0, tzinfo=JST)  # 이 시각(일본 시간) 이후엔 감시 종료
INTERVAL_SEC = 180  # 3분마다 확인
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram_config.json")


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def parse(page):
    """{(날짜, 시각): (상태, 링크)} 반환. 링크가 있으면 예약 가능."""
    headers = re.findall(r"<th>(\d+/\d+)\([^)]*\)</th>", page)
    tbody = page.split("<tbody>", 1)[1].split("</tbody>", 1)[0]
    result = {}
    for row in re.findall(r"<tr>(.*?)</tr>", tbody, re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        if not cells:
            continue
        t = cells[0].strip()
        for date, cell in zip(headers, cells[1:]):
            m = re.search(r"href\s*=\s*'([^']+)'>([^<]+)</a>", cell)
            if m:
                result[(date, t)] = (m.group(2).strip(), BASE + m.group(1).lstrip("./"))
    return result


def load_tg():
    if os.environ.get("TG_TOKEN"):
        return os.environ["TG_TOKEN"], os.environ["TG_CHAT_ID"]
    try:
        with open(CONFIG) as f:
            c = json.load(f)
        return c["token"], str(c["chat_id"])
    except Exception:
        return None, None


def tg_api(token, method, params=None):
    data = urllib.parse.urlencode(params or {}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data, timeout=20) as r:
        return json.load(r)


def notify(title, msg):
    token, chat_id = load_tg()
    if token:
        try:
            tg_api(token, "sendMessage", {"chat_id": chat_id, "text": f"{title}\n{msg}",
                                          "disable_web_page_preview": "true"})
        except Exception as e:
            print(f"텔레그램 전송 실패: {type(e).__name__}")
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e",
                        f'display notification {title!r} with title "모미지" sound name "Glass"'], check=False)


def setup():
    """봇 토큰 입력 → 봇에게 보낸 메시지에서 chat_id 자동 추출 → 저장 → 테스트 전송."""
    token = input("BotFather에서 받은 봇 토큰: ").strip()
    input("텔레그램에서 방금 만든 봇에게 아무 메시지나 보낸 뒤 Enter...")
    ups = tg_api(token, "getUpdates").get("result", [])
    chats = [u["message"]["chat"]["id"] for u in ups if "message" in u]
    if not chats:
        sys.exit("메시지를 못 찾았어요. 봇에게 메시지를 보냈는지 확인 후 다시 실행하세요.")
    with open(CONFIG, "w") as f:
        json.dump({"token": token, "chat_id": chats[-1]}, f)
    os.chmod(CONFIG, 0o600)
    notify("✅ 모미지 감시 봇 연결 완료", "11/14, 11/15 빈자리가 나면 여기로 알려드릴게요.")
    print("저장 완료! 텔레그램에 테스트 메시지가 왔는지 확인하세요.")


def main():
    if "--setup" in sys.argv:
        return setup()
    once = "--once" in sys.argv
    # --minutes N: N분 동안 반복 후 종료 (클라우드 장시간 작업용), --interval 초
    minutes = float(sys.argv[sys.argv.index("--minutes") + 1]) if "--minutes" in sys.argv else None
    interval = int(sys.argv[sys.argv.index("--interval") + 1]) if "--interval" in sys.argv else INTERVAL_SEC
    deadline = time.time() + minutes * 60 if minutes else None
    # --state 파일: 1회 실행(클라우드) 간에 이미 알린 자리를 기억
    state = sys.argv[sys.argv.index("--state") + 1] if "--state" in sys.argv else None
    seen = set()
    if state and os.path.exists(state):
        with open(state) as f:
            seen = {tuple(x) for x in json.load(f)}
    while True:
        if datetime.now(JST) >= END_AT:
            print(f"감시 기한({END_AT:%Y-%m-%d %H:%M} JST)이 지나 종료합니다.")
            break
        now = datetime.now().strftime("%H:%M:%S")
        try:
            slots = parse(fetch(URL))
            hits = {k: v for k, v in slots.items() if k[0] in TARGET_DATES}
            if hits:
                for (d, t), (st, link) in sorted(hits.items()):
                    print(f"[{now}] ✅ {d} {t}  잔여:{st}  {link}")
                new = set(hits) - seen
                if new:
                    desc = "\n".join(f"{d} {t}  잔여:{hits[(d, t)][0]}\n{hits[(d, t)][1]}"
                                     for d, t in sorted(new))
                    notify("🍁 모미지 빈자리 났어요!", desc + f"\n\n전체 보기: {URL}")
                seen = set(hits)
            else:
                print(f"[{now}] {', '.join(TARGET_DATES)} 전부 만석")
                seen = set()
        except Exception as e:
            print(f"[{now}] 오류: {type(e).__name__}: {e}")
        if state:
            with open(state, "w") as f:
                json.dump(sorted(seen), f)
        if once or (deadline and time.time() + interval > deadline):
            break
        time.sleep(interval)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
YouTube Channel Watcher

Reads Channels.json → checks each channel for new videos →
downloads transcripts → updates record.md → outputs for summarization.

Usage:
    python3 watch_channels.py           # Check all enabled channels
    python3 watch_channels.py --dry-run # Show what would be done without writing
"""

import argparse
import json
import os
import re
import requests  
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

WORKSPACE = Path(__file__).resolve().parent.parent
CHANNELS_FILE = WORKSPACE / "Channels.json"
RECORD_FILE = WORKSPACE / "record.md"
SKILL_SCRIPT = WORKSPACE / "skills" / "youtube-watcher" / "scripts" / "get_transcript.py"
TRANSCRIPTS_DIR = WORKSPACE / "transcripts_output"
SUMMARIZE_DIR = WORKSPACE / "Summarize"
# ── Helpers ──────────────────────────────────────────────────────

def load_channels():
    """Load channels from Channels.json."""
    if not CHANNELS_FILE.exists():
        print(f"[ERROR] {CHANNELS_FILE} not found. Create it first.", file=sys.stderr)
        sys.exit(1)
    with open(CHANNELS_FILE, encoding="utf-8") as f:
        return json.load(f).get("channels", [])

def load_record():
    """Load already-summarized video IDs from record.md."""
    if not RECORD_FILE.exists():
        return set()
    seen = set()
    with open(RECORD_FILE, encoding="utf-8") as f:
        for line in f:
            # Match the last pipe-delimited field (video ID)
            m = re.search(r'\|\s*([a-zA-Z0-9_-]{11})\s*\|', line)
            if m:
                seen.add(m.group(1))
    return seen

def append_record(channel, title, video_id):
    """Append one line to record.md."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Escape pipes in title
    safe_title = title.replace("|", "\\|")
    line = f"| {today} | {channel} | {safe_title} | {video_id} |\n"
    with open(RECORD_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    print(f"  → Recorded: {video_id}")

def get_channel_videos(channel_url, max_results=5, max_age_hours=24):
    """
    Fetch recent video metadata from a YouTube channel using yt-dlp.
    Only returns videos uploaded within the last 24 hours.
    Returns list of dicts: {id, title, url, upload_date}
    """
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--playlist-end", str(max_results),
        "--dateafter", "now-1day",
        "--print", "%(id)s|%(title)s|%(upload_date)s",
        channel_url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f"  [WARN] yt-dlp failed: {result.stderr.strip()[:200]}", file=sys.stderr)
            return []
        videos = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) >= 2:
                videos.append({
                    "id": parts[0],
                    "title": parts[1] if len(parts) > 1 else "",
                    "url": f"https://www.youtube.com/watch?v={parts[0]}",
                    "upload_date": parts[2] if len(parts) > 2 else "",
                })
        return videos
    except subprocess.TimeoutExpired:
        print(f"  [WARN] yt-dlp timed out for {channel_url}", file=sys.stderr)
        return []
    except FileNotFoundError:
        print("[ERROR] yt-dlp not found. Install it.", file=sys.stderr)
        sys.exit(1)

def get_transcript(video_url):
    """Download transcript for a video using the youtube-watcher skill script."""
    cmd = ["python3", str(SKILL_SCRIPT), video_url]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        print(f"  [WARN] No subtitles for {video_url}", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"  [WARN] Transcript download timed out for {video_url}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [WARN] Transcript error: {e}", file=sys.stderr)
        return None
    
def sanitize_filename(name):
    """移除或替換檔名中的非法字元"""
    # 將非法字元替換為底線
    return re.sub(r'[\\/*?:"<>|]', "_", name)
def summarize_with_deepseek(text):
    """
    呼叫 DeepSeek API 來對傳入的文本進行總結。
    """
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("[ERROR] DEEPSEEK_API_KEY environment variable not set.", file=sys.stderr)
        return None

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # 建立 Prompt（提示詞），告訴 LLM 它的任務是什麼
    prompt = (
    "You are an expert AI researcher and content analyst. "
    "Your task is to analyze the provided YouTube video transcript and extract specific information "
    "to build a comparative landscape of LLM (Large Language Model) themes.\n\n"
    "Please provide the output in two parts:\n"
    "1. A concise Markdown table with the following columns:\n"
    "   - **Speaker**: Identify the person speaking (if known).\n"
    "   - **Primary Topics**: The main LLM themes covered (e.g., RAG, Fine-tuning, Agentic Workflows).\n"
    "   - **Unique Insights**: One or two standout points from this specific video.\n\n"
    "2. A 'Channel Context' section:\n"
    "   - Explain how this content relates to broader LLM themes.\n"
    "   - Briefly describe how this channel's perspective relates to other common AI channels "
    "     (e.g., is it more developer-focused compared to academic-focused channels?).\n\n"
    f"Transcript:\n{text}"
)

    data = {
        "model": "deepseek-chat",  # 指定使用的模型
        "messages": [
            {"role": "system", "content": "You are a helpful assistant that summarizes text accurately."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3  # 較低的溫度可以讓回答更加精確且不偏離事實
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=120)
        response.raise_for_status() # 檢查 HTTP 狀態碼
        result_json = response.json()
        return result_json["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [ERROR] DeepSeek API failed: {e}", file=sys.stderr)
        return None
    
def process_transcripts_and_cleanup():
    """
    讀取所有的 transcript 檔案，發送給 LLM 總結，儲存後刪除原始檔。
    """
    if not TRANSCRIPTS_DIR.exists():
        return

    # 確保 Summarize 資料夾存在
    SUMMARIZE_DIR.mkdir(parents=True, exist_ok=True)
    
    # 取得所有 .txt 檔案
    transcript_files = list(TRANSCRIPTS_DIR.glob("*.txt"))
    if not transcript_files:
        return

    print(f"\n🧠 Starting DeepSeek Summarization for {len(transcript_files)} files...")

    for file_path in transcript_files:
        print(f"   📝 Summarizing: {file_path.name}")
        
        # 1. 讀取檔案內容
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # 2. 呼叫 API 進行總結
        summary = summarize_with_deepseek(content)
        
        if summary:
            # 3. 將總結寫入 Summarize 資料夾
            summary_file_path = SUMMARIZE_DIR / file_path.name
            with open(summary_file_path, "w", encoding="utf-8") as f:
                f.write(summary)
            print(f"      ✓ Saved summary to: {summary_file_path.name}")
            
            # 4. 移除原始的 transcript 檔案 (Cleanup)
            file_path.unlink()
            print(f"      🗑️  Deleted original transcript: {file_path.name}")
        else:
            print(f"      ⚠ Failed to summarize {file_path.name}. Original file kept.")
def git_commit_and_push(target_dir: Path):
    """這個函數負責將指定的資料夾變更提交並推送到遠端 Git 倉庫。

    為什麼需要這做：透過自動化 Git 指令，免去手動輸入的麻煩。
    """
    try:
        # 1. 檢查是否有任何變更（避免空 commit 導致報錯）
        # git status --porcelain 會以簡短格式輸出，如果沒有變更，輸出會是空的
        status = subprocess.run(
            ["git", "status", "--porcelain", str(target_dir)],
            capture_output=True,
            text=True,
            check=True,
        )

        if not status.stdout.strip():
            print(f"   [Git] 📁 {target_dir} 沒有偵測到任何新變更，跳過 Git 推送。")
            return

        print(f"   [Git] 🚀 偵測到 {target_dir} 有新變更，開始上傳至 GitHub...")

        # 2. Add: 將目標資料夾的所有變更加入暫存區
        subprocess.run(["git", "add", str(target_dir)], check=True)

        # 3. Commit: 建立提交，並加上帶有時間戳記的訊息
        commit_msg = (
            f"auto: update summaries {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)

        # 4. Push: 推送到遠端倉庫（預設為 main 分支）
        subprocess.run(["git", "push"], check=True)
        print("   [Git] 🎉 成功同步至遠端倉庫！")

    except subprocess.CalledProcessError as e:
        print(f"   [Git] ❌ 執行 Git 指令時出錯: {e}")
    except FileNotFoundError:
        print(
            "   [Git] ❌ 系統找不到 'git' 指令，請確保環境已安裝 Git 且已加入環境變數。"
        )
# ── Main ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Check YouTube channels for new videos.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing.")
    args = parser.parse_args()

    channels = load_channels()
    if not channels:
        print("[INFO] No channels configured in Channels.json.")
        return

    seen_ids = load_record()
    print(f"📺 YouTube Channel Watcher — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"   Channels configured: {len(channels)}")
    print(f"   Already summarized: {len(seen_ids)} videos")
    print()

    found_any = False
    new_videos_for_agent = []

    for ch in channels:
        name = ch.get("name", "Unknown")
        url = ch.get("url", "")
        enabled = ch.get("enabled", True)

        if not enabled:
            print(f"⏭  [{name}] — disabled, skipping")
            continue
        if not url:
            print(f"⏭  [{name}] — no URL, skipping")
            continue

        print(f"📡 [{name}] — fetching latest videos...")
        videos = get_channel_videos(url, max_results=5)
        if not videos:
            print(f"   No videos found or channel unreachable.")
            continue
        if not args.dry_run:
            TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

        new_videos = [v for v in videos if v["id"] not in seen_ids]
        if not new_videos:
            print(f"   ✓ No new videos (latest: {videos[0]['title'][:50]}...)")
            continue

        print(f"   🆕 Found {len(new_videos)} new video(s):")
        for v in new_videos:
            print(f"      • {v['title'][:60]} ({v['id']})")
            found_any = True

            if not args.dry_run:
                # Get transcript
                print(f"        Downloading transcript...")
                transcript = get_transcript(v["url"])
                if transcript:
                    clean_title = sanitize_filename(v["title"])
                    file_path = TRANSCRIPTS_DIR / f"{clean_title}.txt"
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(f"SOURCE: {v['url']}\n")
                        f.write(f"CHANNEL: {name}\n")
                        f.write("-" * 20 + "\n\n")
                        f.write(transcript)
                    print(f"        💾 Saved to: {file_path.name}")
            # ----------------------------
            
                    new_videos_for_agent.append({
                        "channel": name,
                        "title": v["title"],
                        "id": v["id"],
                        "url": v["url"],
                        "transcript": transcript,
                        })
                    append_record(name, v["title"], v["id"])
                else:
                    # Still record it so we don't retry a video with no subs
                    print(f"        ⚠ No transcript available, recording as watched.")
                    if not args.dry_run:
                        # Record with a note — mark as no-subs
                        pass  # Still append so we don't keep trying
                        append_record(name, v["title"] + " (no transcript)", v["id"])
            else:
                new_videos_for_agent.append({
                    "channel": name,
                    "title": v["title"],
                    "id": v["id"],
                    "url": v["url"],
                    "transcript": None,
                })

    print("\n" + "=" * 60)
    if not found_any:
        print("✅ No new videos found. All caught up!")
        return

    if args.dry_run:
        print(f"🏁 DRY RUN — would summarize {len(new_videos_for_agent)} new video(s).")
        return
    process_transcripts_and_cleanup()
    print(f"{'─'*60}")
    print(f"\n✅ Done. {len(new_videos_for_agent)} new video(s) checked and recorded.")
    git_commit_and_push(TRANSCRIPTS_DIR)

if __name__ == "__main__":
    main()
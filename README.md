# LLM YouTube Landscape Tracker (OpenClaw Powered)

An automated, end-to-end data pipeline that monitors prominent LLM-focused YouTube channels, downloads and processes video transcripts via AI, and hosts a continuously updated structured knowledge base for reviewers.

---

## 1. Problem Statement

In the rapidly evolving domain of Large Language Models (LLMs), staying updated with continuous tool releases, developer workflows, and researcher insights is a significant challenge. Tech creators on YouTube produce high-value content daily, but traditional video platforms suffer from information density and searchability issues:
1. **High Latency & Low Searchability:** Reviewers must watch 30-minute videos to extract single API configurations or theoretical architectural differences.
2. **Surface-Level Content:** Titles and thumbnails are often optimized for click-through rates (CTR) rather than deep technical precision, making indexing unreliable.
3. **Manual Overhead:** Manually tracking across multiple channels lacks scalability.

### Project Objective
To build an autonomous agentic pipeline that fetches, transcribes, analyzes, and categorizes the latest videos from designated LLM content creators. The final output must filter noise, extract actual speaker insights, map channel relationships, and remain continuously updated on a publicly hosted dashboard without human intervention.

---

## 2. Methodology

The system is designed with a decentralized, decoupled architecture consisting of four core layers: **Data Ingestion**, **AI Transcription & Processing**, **State Persistence**, and **Automated CI/CD Deployment**.



### 2 System Architecture & Workflow
I created my own skill and it will work everyday morning with my cron schedule in openclaw. (But since i dont have put it on a online server, so sometimes the file is not update when my computer not open)
1. **Ingestion Engine (`watch_channels.py`):** A custom Python scheduler parsing a configuration matrix (`Channels.json`). It actively queries YouTube RSS/API endpoints to check for fresh video uploads, strictly capping results to avoid API throttling. (So put the youtube channel you want in Channels.json, and it will search that channel each time soon)
2. **Context Enrichment (Transcription):** Consider we used the SKILL from the openclawhub, youtube-watcher skill, for automation the process of take transcript from youtube link.
3. **State Tracking (`Records.json`):** The extracted video name will compare with the record.md in workspace directory, to ensure all videos is not duplicated to save the tokens
4. **Agentic Layer (Prompt Execution):** After extracted a video transcript, it will put on the LLM model to summarize all content, sorry that i just a simple prompt to control the summarize output, so we can modify the prompt in my maincode --> watch_channels.py --> we can modify the prompt in function (summarize_with_deepseek()), we also can take it out if necessary
5. **Static Generator & CI/CD Push:** The aggregated insights are compiled into a responsive frontend table. The script utilizes native Python `subprocess` abstraction to trigger secure Git workflows, performing conditional pushes to a public deployment branch only when data mutations are caught.


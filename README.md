# Smart Trade Fair Stand Assistant

> **IoT & Smart Systems Course — Group 4 Project**  
> Ostfalia University for Applied Sciences · Summer Semester 2026

---

## Overview

This project implements a **multi-robot visitor assistant** for a technology trade fair stand. Two physical robots — **Pepper** and **Temi** — collaborate in real time, orchestrated by a Large Language Model (LLM), to deliver a seamless and personalised visitor experience.

| Robot | Role |
|-------|------|
| **Pepper** | Stand entrance greeter. Detects visitors via face recognition, delivers the company introduction, and evaluates initial visitor interest. |
| **Temi**   | Mobile product guide. Navigates the visitor through the stand's product sections and delivers contextual explanations on demand. |

The LLM acts as the **cognitive backbone**: it interprets natural language from the visitor and decides — in real time — which robot should speak, what it should say, and whether Temi needs to navigate to a new section.

---

## Setup & Installation

### Prerequisites

- Python 3.11+
- Both robots connected to the same local Wi-Fi network
- An OpenAI API key (or compatible LLM endpoint)

## Libraries Used

| Library | Purpose |
|---------|---------|
| [`pypepper`](https://github.com/your-org/pypepper) | High-level Python interface to the Pepper Middleware |
| [`pytemi`](https://github.com/your-org/pytemi) | High-level Python interface to the Temi Middleware |
| [`whisper_stt_recorder`](https://github.com/your-org/whisper-stt-recorder) | VAD + Whisper-based speech-to-text |
| [`openai`](https://pypi.org/project/openai/) | LLM API client |

---

## Authors

*Group 4 — Smart IoT, Ostfalia Hochschule für angewandte Wissenschaften, SS2026*

---

## License

MIT License — see `LICENSE` for details.

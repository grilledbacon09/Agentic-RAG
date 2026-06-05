"""터미널용 대화형 채팅 (웹 UI 권장: chat_web.py).

실행:
    python chat_main.py
"""

from __future__ import annotations

from chat_service import create_chat, is_reset_command, send_message
from config import load_config


def main() -> None:
    config = load_config()
    bundle, welcome = create_chat(config)

    print("=" * 70)
    print("💬 Agentic-RAG 대화형 복약 상담 (터미널)")
    print("ChatGPT형 웹 UI: python chat_web.py")
    print(f"ChromaDB: {'ON' if config.use_chroma else 'OFF'}")
    print("=" * 70)
    print()
    print(f"Assistant: {welcome}")
    print()

    while bundle.session.phase.value != "ended":
        try:
            user_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAssistant: 상담을 종료할게요. 증상이 지속되면 병원·약국 상담을 권해드려요.")
            break

        if not user_text:
            continue

        if is_reset_command(user_text):
            bundle, welcome = create_chat(config)
            print(f"\nAssistant: {welcome}\n")
            continue

        bundle, reply, trace = send_message(bundle, user_text)
        print(f"\nAssistant: {reply}")

        if trace and config.enable_agent_trace:
            print(f"\n--- [Debug] ---\n{trace}")
        print()

    print("=" * 70)


if __name__ == "__main__":
    main()

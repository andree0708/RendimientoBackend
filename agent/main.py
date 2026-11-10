"""Agent entry point — a standalone command-line application.

Usage:
    python -m agent.main setup     # Configure backend URL and credentials
    python -m agent.main start      # Start capturing and sending metrics
    python -m agent.main status     # Show current status
    python -m agent.main report     # Submit a quick self-report
    python -m agent.main stop       # Stop running session (if any)

The agent shows a visible indicator while running and collects only
privacy-respecting aggregated metadata.
"""

import argparse
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone

from agent.api_client import AgentAPIClient
from agent.collector import MetricCollector
from agent.config import AgentConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("agent")

# Global state for the running agent
_running = True
_collector: MetricCollector | None = None
_client: AgentAPIClient | None = None


def cmd_setup() -> None:
    """Interactive setup: configure backend URL, email, and password."""
    config = AgentConfig.load()

    print("\n=== WorkSense AI Agent Setup ===\n")
    config.backend_url = input(f"Backend URL [{config.backend_url}]: ") or config.backend_url
    config.email = input(f"Email [{config.email}]: ") or config.email
    password = input("Password (leave blank to keep): ")
    if password:
        config.password = password
    config.collection_interval = int(
        input(f"Collection interval (seconds) [{config.collection_interval}]: ")
        or config.collection_interval
    )
    config.idle_threshold = int(
        input(f"Idle threshold (seconds) [{config.idle_threshold}]: ")
        or config.idle_threshold
    )
    config.save()
    print("\nConfiguration saved to", AgentConfig.CONFIG_FILE)


def cmd_start() -> None:
    """Start the metric collection loop."""
    global _running, _collector, _client

    config = AgentConfig.load()
    if not config.email or not config.password:
        print("Please run 'agent setup' first to configure credentials.")
        sys.exit(1)

    _client = AgentAPIClient(config)

    # Authenticate
    print("\nAuthenticating with backend...")
    if not _client.login():
        print("Authentication failed. Check your credentials and backend URL.")
        sys.exit(1)

    # Start a work session
    print("Starting work session...")
    session_id = _client.start_session()
    if not session_id:
        print("Could not start a session. Is the backend running?")
        sys.exit(1)

    _collector = MetricCollector(idle_threshold=config.idle_threshold)
    _collector.reset_session()

    print(f"\n{'='*50}")
    print("  WorkSense AI Agent is now ACTIVE")
    print(f"  Session: {session_id}")
    print(f"  Collecting every {config.collection_interval}s")
    print("  Press Ctrl+C to stop and end the session.")
    print(f"{'='*50}\n")

    # Set up signal handler for graceful shutdown
    def signal_handler(sig, frame):
        global _running
        _running = False
        logger.info("Stopping agent...")

    signal.signal(signal.SIGINT, signal_handler)

    metrics_buffer: list[dict] = []
    ai_check_counter = 0
    last_report_time = time.time()

    while _running:
        # Collect metrics
        metric = _collector.collect(config.collection_interval)
        metrics_buffer.append(metric)

        # Send batch when enough metrics are collected
        if len(metrics_buffer) >= config.batch_size:
            _client.send_metrics(metrics_buffer)
            metrics_buffer = []

        # Periodically trigger AI assessment (every ~10 minutes)
        ai_check_counter += 1
        if ai_check_counter >= (600 // config.collection_interval):
            ai_check_counter = 0
            logger.info("Requesting fatigue assessment...")
            assessment = _client.request_fatigue_assessment()
            if assessment:
                logger.info(
                    "Fatigue: %s (%.0f%% confidence)",
                    assessment.get("risk_category", "unknown"),
                    assessment.get("confidence", 0) * 100,
                )
            prediction = _client.request_performance_prediction()
            if prediction:
                logger.info(
                    "Performance: %s (variation: %.3f)",
                    prediction.get("risk_label", "unknown"),
                    prediction.get("predicted_variation", 0),
                )

        # Auto-prompt for self-report every 2 hours (log a reminder)
        if time.time() - last_report_time >= 7200:
            last_report_time = time.time()
            logger.info("Reminder: consider submitting a self-report ('agent report')")

        # Wait for next collection interval (check running flag frequently)
        for _ in range(config.collection_interval):
            if not _running:
                break
            time.sleep(1)

    # Graceful shutdown: flush remaining metrics and stop session
    print("\nFlushing remaining metrics...")
    if metrics_buffer:
        _client.send_metrics(metrics_buffer)

    print("Stopping work session...")
    _client.stop_session()
    print("Agent stopped. Goodbye!")


def cmd_report() -> None:
    """Submit a quick self-report interactively."""
    config = AgentConfig.load()
    if not config.email or not config.password:
        print("Please run 'agent setup' first.")
        sys.exit(1)

    client = AgentAPIClient(config)
    if not client.login():
        print("Authentication failed.")
        sys.exit(1)

    print("\n=== Quick Self-Report ===")
    print("Rate each from 1 (low) to 5 (high) or 10 (max).\n")

    def ask(prompt: str, max_val: int = 5) -> int:
        while True:
            try:
                val = int(input(f"{prompt} (1-{max_val}): "))
                if 1 <= val <= max_val:
                    return val
                print(f"Please enter a value between 1 and {max_val}")
            except ValueError:
                print("Please enter a number")

    report = {
        "fatigue_level": ask("Fatigue level"),
        "stress_level": ask("Stress level"),
        "concentration_level": ask("Concentration"),
        "task_difficulty": ask("Task difficulty"),
        "perceived_effort": ask("Perceived effort"),
        "need_for_break": ask("Need for a break"),
        "sleep_hours": float(input("Hours slept last night (0-24, optional): ") or "0") or None,
        "sleep_quality": ask("Sleep quality") if input("Rate sleep quality? (y/n): ").lower().startswith("y") else None,
        "notes": input("Notes (optional): ") or None,
    }

    # Remove None values
    report = {k: v for k, v in report.items() if v is not None}

    if client.submit_self_report(report):
        print("\nSelf-report submitted successfully!")
    else:
        print("\nFailed to submit self-report.")


def cmd_stop() -> None:
    """Stop any active session on the backend."""
    config = AgentConfig.load()
    client = AgentAPIClient(config)
    if client.login():
        if client.stop_session():
            print("Session stopped.")
        else:
            print("No active session to stop.")
    else:
        print("Authentication failed.")


def cmd_status() -> None:
    """Show the current agent configuration."""
    config = AgentConfig.load()
    print("\n=== Agent Configuration ===")
    print(f"Backend URL:    {config.backend_url}")
    print(f"Email:          {config.email}")
    print(f"Interval:       {config.collection_interval}s")
    print(f"Idle threshold:  {config.idle_threshold}s")
    print(f"Batch size:     {config.batch_size}")
    print(f"Config file:    {AgentConfig.CONFIG_FILE}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="WorkSense AI Local Agent")
    sub = parser.add_subparsers(dest="command", help="Available commands")

    sub.add_parser("setup", help="Configure the agent")
    sub.add_parser("start", help="Start capturing metrics")
    sub.add_parser("stop", help="Stop active session")
    sub.add_parser("status", help="Show current configuration")
    sub.add_parser("report", help="Submit a quick self-report")

    args = parser.parse_args()

    if args.command == "setup":
        cmd_setup()
    elif args.command == "start":
        cmd_start()
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "status":
        cmd_status()
    elif args.command == "report":
        cmd_report()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

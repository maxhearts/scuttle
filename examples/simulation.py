#!/usr/bin/env python3
"""Main orchestrator for the 8-agent Tsunami Brainrot simulation."""
import json
import os
import sys
import time
import threading
import requests

from agents import AGENTS, AgentConfig
from archetypes.base import API_BASE, GAME_ID, observe, run_agent
from archetypes.tryhard import TryhardStrategy
from archetypes.gambler import GamblerStrategy
from archetypes.farmer import FarmerStrategy

STRATEGY_MAP = {
    "tryhard": TryhardStrategy,
    "gambler": GamblerStrategy,
    "farmer": FarmerStrategy,
}

KEY_CACHE_FILE = "/tmp/tsunami_sim_keys.json"


def load_key_cache() -> dict:
    try:
        with open(KEY_CACHE_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}


def save_key_cache(cache: dict):
    try:
        with open(KEY_CACHE_FILE, 'w') as f:
            json.dump(cache, f, indent=2)
    except Exception as e:
        print(f"Warning: couldn't save key cache: {e}")


def validate_key(api_key: str) -> bool:
    """Check if API key is valid by calling GET /agents/me."""
    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        resp = requests.get(f"{API_BASE}/agents/me", headers=headers, timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


ARCHETYPE_DESCRIPTIONS = {
    "tryhard": "Competitive streamer bot - rarity priority targeting with safety math",
    "gambler": "High-risk streamer bot - chases highest value brainrots",
    "farmer": "Safe streamer bot - consistent farming near base zone",
}


def register_agent(name: str, archetype: str) -> str:
    """Register a new agent and return its API key."""
    description = ARCHETYPE_DESCRIPTIONS.get(archetype, "Tsunami Brainrot agent")
    resp = requests.post(
        f"{API_BASE}/agents/register",
        json={"name": name, "description": description},
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json()
    # Response structure: {"agent": {"api_key": "..."}, ...}
    agent_data = data.get('agent', data)
    api_key = agent_data.get('api_key') or agent_data.get('apiKey') or data.get('api_key') or data.get('key')
    if not api_key:
        raise ValueError(f"No API key in registration response: {data}")
    return api_key


def register_or_load(name: str) -> str:
    """Load cached key if valid, otherwise register fresh."""
    cache = load_key_cache()
    if name in cache:
        key = cache[name]
        if validate_key(key):
            print(f"  [{name}] Using cached key ✓")
            return key
        else:
            print(f"  [{name}] Cached key stale, re-registering...")

    archetype = next((a.archetype for a in AGENTS if a.name == name), "tryhard")

    # Try name variants on conflict
    for attempt, candidate in enumerate([name] + [f"{name}{i}" for i in range(2, 10)]):
        try:
            print(f"  [{name}] Registering as '{candidate}'...")
            key = register_agent(candidate, archetype)
            cache[name] = key
            save_key_cache(cache)
            print(f"  [{name}] Registered as '{candidate}' ✓")
            return key
        except requests.exceptions.HTTPError as e:
            if '409' in str(e):
                continue  # Name taken, try next variant
            raise
    raise RuntimeError(f"Could not register {name} after multiple attempts")


def join_game(api_key: str, name: str):
    """Join the game with the given API key."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    resp = requests.post(f"{API_BASE}/games/{GAME_ID}/join", headers=headers, timeout=10)
    if resp.status_code == 200 or "already" in resp.text.lower():
        print(f"  [{name}] Joined game ✓")
    else:
        print(f"  [{name}] Join response: {resp.status_code} {resp.text[:100]}")


def print_leaderboard(snapshot_key: str):
    """Print a quick leaderboard using one agent's observe."""
    try:
        state = observe(snapshot_key)
        players = state.get('players', [])
        if not players:
            world = state.get('world', {})
            players = world.get('players', [])

        if players:
            print("\n=== LEADERBOARD ===")
            sorted_players = sorted(players, key=lambda p: p.get('attributes', {}).get('Money', 0), reverse=True)
            for i, p in enumerate(sorted_players[:10], 1):
                attrs = p.get('attributes', {})
                pname = p.get('name', p.get('displayName', 'Unknown'))
                money = attrs.get('Money', 0)
                speed = attrs.get('SpeedLevel', 1)
                print(f"  #{i} {pname:<16} ${money:>10,.0f}  Spd:{speed:.0f}")
            print("===================\n")
    except Exception as e:
        print(f"[Leaderboard] Error: {e}")


def main():
    print("=" * 60)
    print("  TSUNAMI BRAINROT - 8 Agent Simulation")
    print("=" * 60)
    print()

    # Print agent table
    print(f"{'Streamer':<16} {'Archetype':<10} {'Safety':<8} {'Chat'}")
    print("-" * 48)
    for agent in AGENTS:
        print(f"{agent.name:<16} {agent.archetype:<10} {agent.safety_modifier:<8.2f} {agent.chat_interval}")
    print()

    # Check for OpenAI API key (optional - enables in-game chat)
    openai_key = os.environ.get('OPENAI_API_KEY')
    if not openai_key:
        print("⚠️  OPENAI_API_KEY not set - chat disabled")
        chat_client = None
    else:
        try:
            from openai import OpenAI
            chat_client = OpenAI(api_key=openai_key)
            print("✓ OpenAI API key found - LLM chat enabled")
        except ImportError:
            print("⚠️  openai package not installed - chat disabled")
            chat_client = None
    print()

    # Register all 8 agents
    print("Registering agents...")
    for agent in AGENTS:
        try:
            agent.api_key = register_or_load(agent.name)
        except Exception as e:
            print(f"  [{agent.name}] Registration failed: {e}")
            sys.exit(1)
    print()

    # Join game for all agents
    print("Joining game...")
    for agent in AGENTS:
        join_game(agent.api_key, agent.name)
        time.sleep(0.3)
    print()

    # Create stop event for graceful shutdown
    stop_event = threading.Event()

    # Create and start agent threads
    print("Starting agent threads...")
    threads = []
    for i, agent in enumerate(AGENTS):
        StrategyClass = STRATEGY_MAP[agent.archetype]
        strategy = StrategyClass(agent)

        t = threading.Thread(
            target=lambda a=agent, s=strategy: run_agent(a, s, stop_event, chat_client),
            name=f"agent-{agent.name}",
            daemon=True
        )
        t.start()
        threads.append(t)
        print(f"  [{agent.name}] Started ({agent.archetype})")
        time.sleep(0.5)  # Stagger starts by 0.5s
    print()

    # Leaderboard loop + graceful shutdown
    snapshot_key = AGENTS[0].api_key
    print("Simulation running. Press Ctrl+C to stop.\n")
    try:
        leaderboard_counter = 0
        while True:
            time.sleep(1)
            leaderboard_counter += 1
            if leaderboard_counter >= 10:
                leaderboard_counter = 0
                print_leaderboard(snapshot_key)

            # Check if all threads are still alive
            alive = sum(1 for t in threads if t.is_alive())
            if alive == 0:
                print("All agent threads have stopped.")
                break

    except KeyboardInterrupt:
        print("\n\nShutting down simulation...")
        stop_event.set()
        for t in threads:
            t.join(timeout=3)
        print("Leaving game...")
        for agent in AGENTS:
            try:
                headers = {"Authorization": f"Bearer {agent.api_key}", "Content-Type": "application/json"}
                requests.post(f"{API_BASE}/games/{GAME_ID}/leave", headers=headers, timeout=5)
            except Exception:
                pass
        print("All agents left. Goodbye!")


if __name__ == "__main__":
    main()

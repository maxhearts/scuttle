#!/usr/bin/env python3
"""Shared helpers and base game loop for all agent archetypes."""
import requests
import json
import time
import math
import threading
import random
from collections import deque
from dataclasses import dataclass
from typing import Optional

API_BASE = "http://localhost:8080/api/v1"
GAME_ID = "0a62727e-b45e-4175-be9f-1070244f8885"
BASE_ZONE_X = 350
COLLECTION_RANGE = 5
SPEED_SHOP = [490.0, 2.5, 84.0]
RARITY_ORDER = ['Secret', 'Legendary', 'Epic', 'Rare', 'Uncommon', 'Common']

PLAYER_SPEED_BASE = 16
PLAYER_SPEED_PER_LEVEL = 5.5
TSUNAMI_SPEED = 50.0


class ChatLog:
    """Thread-safe chat log shared by all agents."""
    def __init__(self, maxlen=25):
        self._lock = threading.Lock()
        self._messages = deque(maxlen=maxlen)

    def add(self, streamer: str, message: str):
        with self._lock:
            self._messages.append({"streamer": streamer, "message": message})

    def recent(self, n=5) -> list:
        with self._lock:
            msgs = list(self._messages)
        return msgs[-n:] if len(msgs) >= n else msgs


# Global shared chat log
CHAT_LOG = ChatLog(maxlen=25)


def dist_xz(pos1, pos2) -> float:
    """2D distance ignoring Y axis."""
    return math.sqrt((pos1[0] - pos2[0])**2 + (pos1[2] - pos2[2])**2)


def distance(pos1, pos2) -> float:
    """3D Euclidean distance."""
    return math.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2 + (pos1[2] - pos2[2])**2)


def get_rarity(brainrot) -> str:
    """Determine rarity from Zone attribute (preferred) or color fallback."""
    zone = brainrot.get('attributes', {}).get('Zone') or brainrot.get('Zone')
    if zone and zone in RARITY_ORDER:
        return zone
    # Color fallback for remote server
    color = brainrot.get('color', [])
    if len(color) < 3:
        return 'Common'
    r, g, b = color[0], color[1], color[2]
    if abs(r - 1.0) < 0.01 and abs(g - 1.0) < 0.01 and abs(b - 1.0) < 0.01:
        return 'Secret'
    if abs(r - 1.0) < 0.01 and abs(g - 1.0) < 0.01 and abs(b - 0.19607843) < 0.01:
        return 'Legendary'
    if abs(r - 1.0) < 0.01 and abs(g - 0.5882353) < 0.01 and abs(b - 0.19607843) < 0.01:
        return 'Epic'
    if abs(r - 0.7058824) < 0.01 and abs(g - 0.39215687) < 0.01 and abs(b - 1.0) < 0.01:
        return 'Rare'
    if abs(r - 0.39215687) < 0.01 and abs(g - 0.5882353) < 0.01 and abs(b - 1.0) < 0.01:
        return 'Uncommon'
    return 'Common'


def rarity_priority(rarity: str) -> int:
    """Lower = higher priority (0 = Secret)."""
    try:
        return RARITY_ORDER.index(rarity)
    except ValueError:
        return len(RARITY_ORDER)


def is_in_base_zone(pos) -> bool:
    return pos[0] > BASE_ZONE_X


def generate_chat(config, client, event: str, pos, money, speed_level, rarity=None, recent_chat=None):
    """Generate LLM chat message in background thread. Non-blocking."""
    if client is None:
        return

    def _do_chat():
        try:
            chat_context = ""
            if recent_chat:
                lines = [f"{m['streamer']}: {m['message']}" for m in recent_chat]
                chat_context = "\nRecent chat:\n" + "\n".join(lines)

            rarity_info = f" Just collected a {rarity} brainrot!" if rarity else ""
            prompt = (
                f"{config.persona_prompt}\n\n"
                f"Current situation: {event}{rarity_info} "
                f"Position X={pos[0]:.0f}, Money=${money:.0f}, Speed level {speed_level:.0f}."
                f"{chat_context}\n\n"
                f"React in character in 1-2 sentences. Be brief, use in-game context."
            )

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=80,
                messages=[{"role": "user", "content": prompt}]
            )
            message = response.choices[0].message.content.strip()

            # Send to game chat
            headers = {
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json"
            }
            requests.post(
                f"{API_BASE}/games/{GAME_ID}/chat",
                headers=headers,
                json={"content": message},
                timeout=5
            )
            CHAT_LOG.add(config.name, message)
            print(f"[{config.name}] 💬 {message}")
        except Exception as e:
            pass  # Never let chat errors affect gameplay

    thread = threading.Thread(target=_do_chat, daemon=True)
    thread.start()


def observe(api_key: str) -> dict:
    """Fetch game state for the given agent."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = requests.get(f"{API_BASE}/games/{GAME_ID}/observe", headers=headers, timeout=10)
    return response.json()


def send_input(api_key: str, input_type: str, data=None) -> dict:
    """Send game input for the given agent."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"type": input_type}
    if data:
        payload["data"] = data
    response = requests.post(f"{API_BASE}/games/{GAME_ID}/input", headers=headers, json=payload, timeout=10)
    return response.json()


def destroy_lowest_value(api_key: str, placed_brainrots: list):
    """Destroy the lowest-value brainrot from base to make room."""
    if not placed_brainrots:
        return
    lowest = min(placed_brainrots, key=lambda b: b['value'])
    send_input(api_key, "Destroy", {"index": lowest['index']})
    time.sleep(0.3)


def run_agent(config, strategy, stop_event, anthropic_client=None):
    """Main game loop shared by all archetypes."""
    api_key = config.api_key
    name = config.name

    print(f"[{name}] Starting agent loop (archetype: {config.archetype})")

    last_position = None
    stuck_cycles = 0
    STUCK_THRESHOLD = 5
    cycles = 0
    chat_counter = 0

    while not stop_event.is_set():
        cycles += 1
        try:
            time.sleep(0.5)

            # 1. Observe
            state = observe(api_key)
            player = state.get('player', {})
            pos = player.get('position', [0, 0, 0])
            attrs = player.get('attributes', {})

            carrying = attrs.get('CarriedCount', 0)
            capacity = attrs.get('CarryCapacity', 1)
            money = attrs.get('Money', 0)
            speed_level = attrs.get('SpeedLevel', 1)
            next_speed_cost = attrs.get('NextSpeedCost', 999999)
            base_center = [attrs.get('BaseCenterX', 375), 0.25, attrs.get('BaseCenterZ', 0)]

            entities = state.get('world', {}).get('entities', [])
            brainrots = [e for e in entities if e.get('attributes', {}).get('IsBrainrot', False)]
            tsunami_waves = [e for e in entities if e.get('name', '').startswith('TsunamiWave')]
            tsunami_x = min([w['position'][0] for w in tsunami_waves]) if tsunami_waves else -500

            if cycles % 10 == 0:
                print(f"[{name}] Cycle {cycles} | X={pos[0]:.0f} | ${money:.0f} | Spd:{speed_level:.0f} | Carrying:{carrying}/{capacity} | Tsunami:{tsunami_x:.0f}")

            # 2. Stuck detection
            if last_position and distance(pos, last_position) < 1.0:
                stuck_cycles += 1
                if stuck_cycles >= STUCK_THRESHOLD:
                    print(f"[{name}] STUCK {stuck_cycles} cycles, aborting to base")
                    send_input(api_key, "MoveTo", {"position": base_center})
                    stuck_cycles = 0
                    time.sleep(1)
                    continue
            else:
                stuck_cycles = 0
            last_position = list(pos)

            # 3. If full -> deposit
            if carrying >= capacity:
                if distance(pos, base_center) < 20:
                    placed_raw = attrs.get('PlacedBrainrots', [])
                    placed = json.loads(placed_raw) if isinstance(placed_raw, str) and placed_raw else placed_raw
                    base_max = attrs.get('BaseMaxBrainrots', 10)
                    if len(placed) >= base_max:
                        destroy_lowest_value(api_key, placed)
                    send_input(api_key, "Deposit")
                else:
                    send_input(api_key, "MoveTo", {"position": base_center})
                continue

            # 4. Speed upgrade check (any time not carrying and can afford)
            if carrying == 0 and next_speed_cost > 0 and money >= next_speed_cost * strategy.upgrade_threshold and speed_level < 10:
                dist_to_shop = distance(pos, SPEED_SHOP)
                if dist_to_shop > 20:
                    send_input(api_key, "MoveTo", {"position": SPEED_SHOP})
                else:
                    send_input(api_key, "BuySpeed")
                    print(f"[{name}] Bought speed upgrade! Level {speed_level + 1}")
                continue

            # 5. Find target via archetype strategy
            action = strategy.find_target(
                pos=pos,
                brainrots=brainrots,
                tsunami_x=tsunami_x,
                base_center=base_center,
                speed_level=speed_level,
                money=money,
                attrs=attrs
            )

            if action is None:
                send_input(api_key, "MoveTo", {"position": base_center})
            elif action['type'] == 'MoveTo':
                send_input(api_key, "MoveTo", {"position": action['position']})
            elif action['type'] == 'Collect':
                send_input(api_key, "Collect")
                # Chat on collection
                if anthropic_client and action.get('rarity') in ['Secret', 'Legendary', 'Epic']:
                    chat_counter = 0  # reset to trigger chat sooner
            elif action['type'] == 'Wait':
                pass  # Stay put

            # 6. Periodic chat
            chat_counter += 1
            if (anthropic_client and
                    chat_counter >= config.chat_interval and
                    random.random() < 0.75):
                chat_counter = 0
                event_desc = action.get('event', 'playing') if action else 'at base'
                recent = CHAT_LOG.recent(5)
                generate_chat(
                    config=config,
                    client=anthropic_client,
                    event=event_desc,
                    pos=pos,
                    money=money,
                    speed_level=speed_level,
                    rarity=action.get('rarity') if action else None,
                    recent_chat=recent
                )

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[{name}] Error: {e}")
            time.sleep(1)

    print(f"[{name}] Agent stopped.")

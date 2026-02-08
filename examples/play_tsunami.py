#!/usr/bin/env python3
"""Single-agent Tsunami Brainrot bot. Conservative safety margins, rarity priority."""
import os
import requests
import json
import time
import math

API_KEY = os.environ["CLAWBLOX_API_KEY"]
GAME_ID = "0a62727e-b45e-4175-be9f-1070244f8885"
BASE_URL = "http://localhost:8080/api/v1"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}


def observe():
    """Get current game state."""
    response = requests.get(f"{BASE_URL}/games/{GAME_ID}/observe", headers=headers)
    return response.json()


def send_input(input_type, data=None):
    """Send game input."""
    payload = {"type": input_type}
    if data:
        payload["data"] = data
    response = requests.post(f"{BASE_URL}/games/{GAME_ID}/input", headers=headers, json=payload)
    return response.json()


def buy_speed_upgrade(player_pos, speed_shop_pos):
    """Buy speed upgrade at the shop."""
    dist = distance(player_pos, speed_shop_pos)
    if dist > 20:
        print(f"Moving to SpeedShop (dist: {dist:.1f})")
        send_input("MoveTo", {"position": speed_shop_pos})
        time.sleep(2)
    print("Buying speed upgrade!")
    return send_input("BuySpeed")


def destroy_lowest_value_brainrot(placed_brainrots):
    """Destroy the lowest-value brainrot from base to make room."""
    if not placed_brainrots:
        return None
    lowest = min(placed_brainrots, key=lambda b: b['value'])
    index = lowest['index']
    print(f"Destroying {lowest['displayName']} (${lowest['value']}) at index {index} to make room")
    result = send_input("Destroy", {"index": index})
    time.sleep(0.5)
    return result


def distance(pos1, pos2):
    """Calculate 3D distance between two positions."""
    return math.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2 + (pos1[2] - pos2[2])**2)


def get_rarity(brainrot):
    """Determine rarity from color."""
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


RARITY_ORDER = ['Secret', 'Legendary', 'Epic', 'Rare', 'Uncommon', 'Common']


def is_in_base_zone(pos):
    """Check if position is in the base zone (X > 350)."""
    return pos[0] > 350


def can_reach_before_tsunami(player_pos, brainrot_pos, deposit_pos, tsunami_x, speed_level):
    """Calculate if we can reach a brainrot and return to deposit before tsunami catches us."""
    PLAYER_SPEED = 16 + (speed_level - 1) * 5.5
    TSUNAMI_SPEED = 50.0

    dist_to_brainrot = distance(player_pos, brainrot_pos)
    dist_brainrot_to_deposit = distance(brainrot_pos, deposit_pos)

    ticks_to_collect = (dist_to_brainrot / PLAYER_SPEED) + 1.0
    ticks_to_return = dist_brainrot_to_deposit / PLAYER_SPEED
    total_ticks_needed = ticks_to_collect + ticks_to_return

    ticks_until_tsunami = (deposit_pos[0] - tsunami_x) / TSUNAMI_SPEED

    if speed_level >= 10:
        safety_margin = 3
    elif speed_level >= 8:
        safety_margin = 4
    elif speed_level >= 5:
        safety_margin = 5
    else:
        safety_margin = 6

    return total_ticks_needed < (ticks_until_tsunami - safety_margin)


def find_furthest_reachable_brainrot(player_pos, brainrots, tsunami_x, deposit_pos, speed_level):
    """Find the furthest reachable brainrot by rarity priority."""
    valid = [b for b in brainrots
             if b['position'][1] > -100 and not is_in_base_zone(b['position'])]

    reachable = [b for b in valid
                 if can_reach_before_tsunami(player_pos, b['position'], deposit_pos, tsunami_x, speed_level)]

    if not reachable:
        if valid:
            nearest = min(valid, key=lambda b: distance(player_pos, b['position']))
            return nearest, get_rarity(nearest)
        return None, None

    for rarity in RARITY_ORDER:
        group = [b for b in reachable if get_rarity(b) == rarity]
        if group:
            furthest = max(group, key=lambda b: distance(player_pos, b['position']))
            return furthest, rarity

    return None, None


def main():
    print("Starting Tsunami gameplay...")
    print("Strategy: rarity priority (Secret > Legendary > Epic > Rare > Uncommon > Common)")

    at_deposit = True
    target_brainrot = None
    cycles = 0
    last_position = None
    stuck_cycles = 0
    STUCK_THRESHOLD = 3
    SPEED_SHOP = [490.0, 2.5, 84.0]

    while True:
        cycles += 1
        time.sleep(0.5)

        state = observe()
        player = state['player']
        pos = player['position']
        attrs = player['attributes']

        if cycles % 10 == 0:
            print(f"Cycle {cycles} | X={pos[0]:.0f} | ${attrs['Money']:.0f} | Spd:{attrs['SpeedLevel']:.0f} | Carrying:{attrs['CarriedCount']}/{attrs['CarryCapacity']}")

        # Stuck detection
        if last_position and distance(pos, last_position) < 2.0:
            stuck_cycles += 1
            if stuck_cycles >= STUCK_THRESHOLD:
                print(f"STUCK for {stuck_cycles} cycles, aborting to safety...")
                deposit_area = [attrs['BaseCenterX'], 0.25, attrs['BaseCenterZ']]
                send_input("MoveTo", {"position": deposit_area})
                stuck_cycles = 0
                target_brainrot = None
                time.sleep(2)
                continue
        else:
            stuck_cycles = 0
        last_position = pos.copy()

        entities = state['world']['entities']
        brainrots = [e for e in entities if e.get('attributes', {}).get('IsBrainrot', False)]
        tsunami_waves = [e for e in entities if e['name'].startswith('TsunamiWave')]
        tsunami_x = min([w['position'][0] for w in tsunami_waves]) if tsunami_waves else -500
        deposit_area = [attrs['BaseCenterX'], 0.25, attrs['BaseCenterZ']]

        carrying = attrs['CarriedCount']
        capacity = attrs['CarryCapacity']
        money = attrs['Money']
        speed_level = attrs['SpeedLevel']
        next_speed_cost = attrs.get('NextSpeedCost', 999999)

        # Buy speed upgrade when affordable and not carrying
        if carrying == 0 and money >= next_speed_cost and speed_level < 10:
            print(f"Upgrading to Speed Level {int(speed_level)+1} (cost: ${next_speed_cost:.0f})")
            buy_speed_upgrade(pos, SPEED_SHOP)
            time.sleep(1)
            continue

        if carrying >= capacity:
            # Full - deposit
            if distance(pos, deposit_area) < 20:
                placed_raw = attrs.get('PlacedBrainrots', [])
                placed = json.loads(placed_raw) if isinstance(placed_raw, str) and placed_raw else placed_raw
                base_max = attrs.get('BaseMaxBrainrots', 10)
                if len(placed) >= base_max:
                    destroy_lowest_value_brainrot(placed)
                send_input("Deposit")
                target_brainrot = None
            else:
                send_input("MoveTo", {"position": deposit_area})
        else:
            target, rarity = find_furthest_reachable_brainrot(pos, brainrots, tsunami_x, deposit_area, speed_level)

            if target:
                dist = distance(pos, target['position'])
                if dist < 5:
                    send_input("Collect")
                else:
                    send_input("MoveTo", {"position": target['position']})
            else:
                send_input("MoveTo", {"position": deposit_area})


if __name__ == "__main__":
    main()

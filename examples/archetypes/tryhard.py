"""Tryhard strategy: safety-conscious, rarity-priority targeting (Ninja, Shroud)."""
from .base import (distance, get_rarity, rarity_priority, is_in_base_zone,
                   PLAYER_SPEED_BASE, PLAYER_SPEED_PER_LEVEL, TSUNAMI_SPEED,
                   RARITY_ORDER)


class TryhardStrategy:
    """Based on play_tsunami.py gold standard. Conservative safety math with rarity priority."""

    upgrade_threshold = 1.0  # Buy speed when money >= 1.0 * cost

    def __init__(self, config):
        self.config = config
        self.safety_modifier = config.safety_modifier  # multiplier on safety margin

    def _player_speed(self, speed_level: float) -> float:
        return PLAYER_SPEED_BASE + (speed_level - 1) * PLAYER_SPEED_PER_LEVEL

    def _base_safety_margin(self, speed_level: float) -> float:
        if speed_level >= 10:
            return 3
        elif speed_level >= 8:
            return 4
        elif speed_level >= 5:
            return 5
        else:
            return 6

    def can_reach_before_tsunami(self, player_pos, brainrot_pos, deposit_pos, tsunami_x, speed_level) -> bool:
        speed = self._player_speed(speed_level)
        dist_to_brainrot = distance(player_pos, brainrot_pos)
        dist_brainrot_to_deposit = distance(brainrot_pos, deposit_pos)

        ticks_to_collect = (dist_to_brainrot / speed) + 1.0
        ticks_to_return = dist_brainrot_to_deposit / speed
        total_ticks_needed = ticks_to_collect + ticks_to_return

        ticks_until_tsunami = (deposit_pos[0] - tsunami_x) / TSUNAMI_SPEED
        safety_margin = self._base_safety_margin(speed_level) * self.safety_modifier

        return total_ticks_needed < (ticks_until_tsunami - safety_margin)

    def find_target(self, pos, brainrots, tsunami_x, base_center, speed_level, money, attrs):
        # Filter valid brainrots
        valid = [b for b in brainrots
                 if b['position'][1] > -100 and not is_in_base_zone(b['position'])]

        # Find reachable brainrots
        tsunami_active = tsunami_x > -400
        reachable = [b for b in valid
                     if self.can_reach_before_tsunami(pos, b['position'], base_center, tsunami_x, speed_level)]

        # Smart wave timing: wait at base only if nothing is safely reachable
        if tsunami_active and not reachable and distance(pos, base_center) < 20:
            return {'type': 'Wait', 'event': 'waiting for wave reset'}

        # Aggressive mode post-wave when money > threshold
        tsunami_passed = tsunami_x > base_center[0]
        AGGRESSIVE_THRESHOLD = 2500
        if money >= AGGRESSIVE_THRESHOLD and tsunami_passed and distance(pos, base_center) < 20:
            target = self._find_nearest_valuable(pos, valid)
            if target:
                b, rarity = target
                return self._move_or_collect(pos, b, rarity, 'aggressive mode - nearest valuable')

        # Normal: furthest reachable by rarity priority
        target = self._furthest_by_rarity(pos, reachable)
        if target:
            b, rarity = target
            return self._move_or_collect(pos, b, rarity, f'targeting {rarity}')

        # Fallback: absolute nearest (risky)
        if valid:
            nearest = min(valid, key=lambda b: distance(pos, b['position']))
            rarity = get_rarity(nearest)
            return self._move_or_collect(pos, nearest, rarity, 'risky nearest fallback')

        return None

    def _furthest_by_rarity(self, pos, candidates):
        for rarity in RARITY_ORDER:
            group = [b for b in candidates if get_rarity(b) == rarity]
            if group:
                furthest = max(group, key=lambda b: distance(pos, b['position']))
                return furthest, rarity
        return None

    def _find_nearest_valuable(self, pos, candidates):
        for rarity in RARITY_ORDER:
            group = [b for b in candidates if get_rarity(b) == rarity]
            if group:
                nearest = min(group, key=lambda b: distance(pos, b['position']))
                return nearest, rarity
        return None

    def _move_or_collect(self, pos, brainrot, rarity, event):
        dist = distance(pos, brainrot['position'])
        if dist < 5:
            return {'type': 'Collect', 'rarity': rarity, 'event': f'collected {rarity}'}
        return {'type': 'MoveTo', 'position': brainrot['position'], 'rarity': rarity, 'event': event}

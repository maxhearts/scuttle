"""Gambler strategy: highest-value targeting, minimal safety (xQc, TimTheTatman, HasanAbi)."""
from .base import (distance, get_rarity, is_in_base_zone,
                   PLAYER_SPEED_BASE, PLAYER_SPEED_PER_LEVEL, TSUNAMI_SPEED,
                   RARITY_ORDER)


class GamblerStrategy:
    """High variance: chase highest value, minimal safety checks, frequent deaths."""

    upgrade_threshold = 1.0  # Buy speed when money >= 1.0 * cost

    def __init__(self, config):
        self.config = config
        self.safety_modifier = config.safety_modifier  # 0.4–0.65, very loose

    def _player_speed(self, speed_level: float) -> float:
        return PLAYER_SPEED_BASE + (speed_level - 1) * PLAYER_SPEED_PER_LEVEL

    def _ticks_to_return(self, brainrot_pos, deposit_pos, speed_level) -> float:
        speed = self._player_speed(speed_level)
        return distance(brainrot_pos, deposit_pos) / speed

    def _ticks_available(self, deposit_pos, tsunami_x) -> float:
        return (deposit_pos[0] - tsunami_x) / TSUNAMI_SPEED

    def is_safe_enough(self, brainrot_pos, deposit_pos, tsunami_x, speed_level) -> bool:
        """Very loose safety: only check return trip is under available time * safety_modifier."""
        ticks_to_return = self._ticks_to_return(brainrot_pos, deposit_pos, speed_level)
        ticks_available = self._ticks_available(deposit_pos, tsunami_x)
        return ticks_to_return < (ticks_available - self.safety_modifier)

    def find_target(self, pos, brainrots, tsunami_x, base_center, speed_level, money, attrs):
        valid = [b for b in brainrots
                 if b['position'][1] > -100 and not is_in_base_zone(b['position'])]

        if not valid:
            return None

        # Find highest-value brainrot (by rarity priority)
        best = None
        best_priority = len(RARITY_ORDER)
        for b in valid:
            rarity = get_rarity(b)
            priority = RARITY_ORDER.index(rarity) if rarity in RARITY_ORDER else len(RARITY_ORDER)
            if priority < best_priority:
                best_priority = priority
                best = (b, rarity)

        if best is None:
            return None

        # Among brainrots of the same best rarity, pick the nearest
        best_rarity = best[1]
        same_rarity = [b for b in valid if get_rarity(b) == best_rarity]
        target = min(same_rarity, key=lambda b: distance(pos, b['position']))

        # Only check very loose safety
        if not self.is_safe_enough(target['position'], base_center, tsunami_x, speed_level):
            # Even gamblers have a tiny self-preservation instinct - check nearest of ANY rarity
            fallback = min(valid, key=lambda b: distance(pos, b['position']))
            if self.is_safe_enough(fallback['position'], base_center, tsunami_x, speed_level):
                rarity = get_rarity(fallback)
                return self._move_or_collect(pos, fallback, rarity, 'gambler fallback - nearest')
            # Otherwise go for it anyway (gambler mentality)
            rarity = get_rarity(target)
            return self._move_or_collect(pos, target, rarity, 'YOLO gambler - ignoring danger')

        return self._move_or_collect(pos, target, best_rarity, f'chasing {best_rarity}')

    def _move_or_collect(self, pos, brainrot, rarity, event):
        dist = distance(pos, brainrot['position'])
        if dist < 5:
            return {'type': 'Collect', 'rarity': rarity, 'event': f'collected {rarity}'}
        return {'type': 'MoveTo', 'position': brainrot['position'], 'rarity': rarity, 'event': event}

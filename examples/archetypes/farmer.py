"""Farmer strategy: zone-restricted nearest brainrot (Pokimane, Ludwig, Valkyrae)."""
from .base import (distance, get_rarity, is_in_base_zone,
                   PLAYER_SPEED_BASE, PLAYER_SPEED_PER_LEVEL, TSUNAMI_SPEED,
                   RARITY_ORDER)


class FarmerStrategy:
    """Consistent low-variance income by staying near base in restricted zones."""

    upgrade_threshold = 1.0  # Aggressive: buy speed as soon as affordable

    def __init__(self, config):
        self.config = config
        self.safety_modifier = config.safety_modifier  # 1.8–3.0, very conservative
        self.venture_limit_x = config.venture_limit_x  # X limit for foraging
        self.min_rarity_priority = config.min_rarity_priority  # Minimum rarity to target (0=all)

    def _player_speed(self, speed_level: float) -> float:
        return PLAYER_SPEED_BASE + (speed_level - 1) * PLAYER_SPEED_PER_LEVEL

    def is_safe(self, brainrot_pos, deposit_pos, tsunami_x, speed_level) -> bool:
        """Conservative safety: return trip with large margin."""
        speed = self._player_speed(speed_level)
        ticks_to_return = distance(brainrot_pos, deposit_pos) / speed
        ticks_available = (deposit_pos[0] - tsunami_x) / TSUNAMI_SPEED
        return ticks_to_return < (ticks_available - self.safety_modifier * 3)

    def find_target(self, pos, brainrots, tsunami_x, base_center, speed_level, money, attrs):
        # Filter: valid, within venture zone, meets rarity requirement
        valid = [b for b in brainrots
                 if b['position'][1] > -100
                 and not is_in_base_zone(b['position'])
                 and b['position'][0] > self.venture_limit_x]  # Stay near base (higher X = closer to base)

        # Apply minimum rarity filter if set
        if self.min_rarity_priority > 0:
            valid = [b for b in valid
                     if RARITY_ORDER.index(get_rarity(b)) >= self.min_rarity_priority]

        if not valid:
            return None

        # Filter by safety
        safe = [b for b in valid
                if self.is_safe(b['position'], base_center, tsunami_x, speed_level)]

        pool = safe if safe else valid  # Fallback to unsafe if nothing safe exists

        # Target nearest brainrot within zone
        target = min(pool, key=lambda b: distance(pos, b['position']))
        rarity = get_rarity(target)
        return self._move_or_collect(pos, target, rarity, f'farming {rarity} in zone')

    def _move_or_collect(self, pos, brainrot, rarity, event):
        dist = distance(pos, brainrot['position'])
        if dist < 5:
            return {'type': 'Collect', 'rarity': rarity, 'event': f'collected {rarity}'}
        return {'type': 'MoveTo', 'position': brainrot['position'], 'rarity': rarity, 'event': event}

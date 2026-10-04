"""Named channel looks and style policy, independent of text layout."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextStyle:
    key: str
    channel: str
    name: str
    fill: str
    gradient_end: str
    accent: str
    outline: str
    shadow: str
    glow: str
    outline_width: float
    shadow_blur: float
    glow_blur: float
    letter_spacing: float = 0.0
    preferred_family: str | None = None
    senior: bool = False
    badge: str = "mini"


_TOKYO = (
    ("japanese_impact", "Japanese Impact", "#FFFFFF", "#FFF5BE", "#FFE23A", "#17090C", "#22070B", "#FF354F", 11, 7, 5, -0.2),
    ("romantic_neon", "Romantic Neon", "#FFF8FE", "#FFB6E7", "#FF62C8", "#25102C", "#19071F", "#FF36C7", 6, 8, 16, 0.2),
    ("urban_story", "Urban Story", "#F9FBFF", "#CDEEFF", "#63D9FF", "#101C2B", "#09111E", "#59CFF8", 7, 8, 5, 0.0),
    ("soft_memory", "Soft Memory", "#FFF9F4", "#FFD9C8", "#FFAC88", "#30212A", "#170F17", "#F58A7B", 5, 5, 8, 0.4),
    ("night_drive", "Night Drive", "#F5FCFF", "#A9FFF1", "#53EBD6", "#071624", "#050B15", "#25DCCB", 7, 9, 13, 0.1),
    ("heartbeat_clean", "Heartbeat Clean", "#FFFFFF", "#E5F3FF", "#FF6C72", "#132030", "#09121D", "#FD5964", 5, 4, 4, 0.3),
)
_OLD = (
    ("senior_classic", "Senior Classic", "#FFF4D8", "#F5D38C", "#FFD36C", "#3B2617", "#21140A", "#F0C36A", 8, 5, 3, 0.0),
    ("warm_gold", "Warm Gold", "#FFF6DF", "#EFC175", "#E5A84E", "#3B2418", "#20130C", "#DCA74D", 8, 6, 4, 0.0),
    ("first_snow", "First Snow", "#FFFFFF", "#D2F0FF", "#B9E8FF", "#1E354A", "#10202E", "#9BDFFF", 8, 6, 8, 0.0),
    ("autumn_lounge", "Autumn Lounge", "#FFF4E3", "#E9B67A", "#D99151", "#3C271B", "#21140D", "#D49353", 8, 5, 4, 0.0),
    ("christmas_glow", "Christmas Glow", "#FFF9E8", "#F4D26A", "#F1C257", "#45211C", "#220D12", "#EE615C", 8, 7, 10, 0.0),
    ("calm_blue_memory", "Calm Blue Memory", "#F7FBFF", "#C8E2F5", "#A7C9E6", "#233648", "#101E2C", "#8DBADB", 8, 5, 4, 0.0),
)


def _make(row, channel: str, senior: bool) -> TextStyle:
    key, name, fill, end, accent, outline, shadow, glow, stroke, shadow_blur, glow_blur, spacing = row
    return TextStyle(key, channel, name, fill, end, accent, outline, shadow, glow,
                     stroke, shadow_blur, glow_blur, spacing, senior=senior,
                     badge="ribbon" if senior else "sticker")


TYPOGRAPHY_PRESETS = {row[0]: _make(row, "Tokyo Chill", False) for row in _TOKYO}
TYPOGRAPHY_PRESETS.update({row[0]: _make(row, "OLD POP LOUNGE", True) for row in _OLD})
PRESETS_BY_CHANNEL = {
    "Tokyo Chill": tuple(TYPOGRAPHY_PRESETS[row[0]] for row in _TOKYO),
    "OLD POP LOUNGE": tuple(TYPOGRAPHY_PRESETS[row[0]] for row in _OLD),
}


def preset_names(channel: str) -> tuple[str, ...]:
    return tuple(style.name for style in PRESETS_BY_CHANNEL.get(channel, ()))


_ALIASES = {
    "cinematic chill": "urban_story", "japanese impact": "japanese_impact", "romantic neon": "romantic_neon",
    "emotional mono": "soft_memory", "story card": "urban_story", "night drive": "night_drive",
    "senior classic": "senior_classic", "senior emotional": "calm_blue_memory", "first snow": "first_snow",
    "autumn memory": "autumn_lounge", "cafe warm": "warm_gold", "christmas glow": "christmas_glow",
}


def get_preset(value: str | None, channel: str = "Tokyo Chill") -> TextStyle:
    if value in TYPOGRAPHY_PRESETS:
        return TYPOGRAPHY_PRESETS[value]
    normalized = (value or "").strip().casefold()
    for style in PRESETS_BY_CHANNEL.get(channel, ()):
        if style.name.casefold() == normalized:
            return style
    key = _ALIASES.get(normalized)
    if key and TYPOGRAPHY_PRESETS[key].channel == channel:
        return TYPOGRAPHY_PRESETS[key]
    styles = PRESETS_BY_CHANNEL.get(channel)
    if not styles:
        raise ValueError(f"Unknown typography channel: {channel}")
    return styles[0]

"""What the user can make. Prompts mirror the backend's tested presets (CoverMorph RC2); text regions are used by the
Shopify editor layout. Model names never appear here."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Kind:
    key: str
    label: str
    family: str                      # youtube | shopify
    purpose: str                     # backend purpose key
    size: tuple[int, int]
    channel: str = ""
    prompt: str = ""
    prompt_preset: str = ""
    people: int = 0
    composition: str = ""
    text_region: tuple[float, float, float, float] = (0.05, 0.15, 0.42, 0.7)
    cta_region: tuple[float, float, float, float] | None = None
    alternates: dict = field(default_factory=dict)


KINDS = [
    Kind("tokyo_chill", "Tokyo Chill", "youtube", "youtube_thumbnail", (1280, 720), "Tokyo Chill",
         "side profile of a young woman on a quiet Tokyo street at dusk", "tc_solo_woman", 1, "SOLO_MEDIUM"),
    Kind("old_pop", "OLD POP", "youtube", "youtube_thumbnail", (1280, 720), "OLD POP LOUNGE",
         "a mature woman in her fifties sitting by the window of a small retro coffee shop she has visited for years, "
         "holding a warm cup", "op_mature_solo", 1, "SOLO_CLOSE"),
    Kind("youtube_custom", "Custom YouTube", "youtube", "youtube_thumbnail", (1280, 720)),
    Kind("shopify_hero", "Hero Banner", "shopify", "shopify_hero", (1800, 700), prompt_preset="sh_editorial",
         prompt="an airy editorial living space with linen textiles, ceramic vases, light oak furniture and soft directional light",
         text_region=(0.05, 0.18, 0.40, 0.64), cta_region=(0.05, 0.72, 0.20, 0.13)),
    Kind("shopify_collection", "Collection Banner", "shopify", "shopify_collection", (1600, 900), prompt_preset="sh_daylight",
         prompt="a bright home interior with soft morning daylight, linen textures and green plants",
         text_region=(0.05, 0.20, 0.42, 0.60), alternates={"정사각형": (1200, 1200)}),
    Kind("shopify_product_lifestyle", "Product Lifestyle", "shopify", "shopify_product_lifestyle", (1600, 1200),
         prompt="the product on a wooden cafe table in soft morning sunlight", text_region=(0.05, 0.05, 0.90, 0.20)),
    Kind("shopify_promo", "Promo Tile", "shopify", "shopify_promo_tile", (1080, 1080), prompt_preset="sh_seasonal",
         prompt="a festive wooden tabletop with warm string lights and tasteful seasonal decorations softly blurred in the background",
         text_region=(0.08, 0.06, 0.84, 0.26), cta_region=(0.30, 0.86, 0.40, 0.08)),
    Kind("shopify_mobile", "Mobile Banner", "shopify", "shopify_mobile", (1080, 1350),
         prompt="a cozy reading corner with a knit blanket and warm lamp light",
         text_region=(0.08, 0.05, 0.84, 0.24), cta_region=(0.28, 0.88, 0.44, 0.07)),
    Kind("shopify_custom", "Custom Shopify", "shopify", "custom", (1600, 900)),
]
KIND_BY_KEY = {kind.key: kind for kind in KINDS}
ROLES = {"인물": "PERSON", "상품": "PRODUCT", "스타일": "STYLE", "구도": "COMPOSITION", "배경": "BACKGROUND"}

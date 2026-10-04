# ShopSource ↔ YouTubeSum Local Image Studio Bridge Contract v1

## Purpose

This contract lets ShopSource Studio (`D:\shop\001_so_amazon`, repo `1976haru/spa`)
request banner and collection imagery from the local image-generation/thumbnail application
(`D:\03_youtubesum`, repo `1976haru/youtubesum`) without coupling ShopSource to the
generator's internal implementation.

The current public `youtubesum` repository is still primarily a thumbnail/motion tool.
The bridge is intentionally provider-agnostic so future local generative backends can be
added behind the same contract without changing ShopSource's Shopify automation.

## Core design

Use a **headless subprocess JSON contract**, not GUI automation and not browser clicks.

Preferred command surface:

    python shopsource_bridge.py --health
    python shopsource_bridge.py --capabilities
    python shopsource_bridge.py --job "C:\path\job.json" --result "C:\path\result.json"

ShopSource may launch the bridge with the exact configured Python executable for the
YouTubeSum environment.

Do not require the Tkinter UI to be open.

## Security

- Never pass API keys, cookies, bearer tokens, Shopify tokens, or browser sessions in job JSON.
- Generator credentials remain owned by the YouTubeSum environment/provider config.
- Do not expose an unauthenticated LAN HTTP service.
- If a future HTTP mode is added, bind to `127.0.0.1` only and add explicit pairing/auth.
- Never automate CAPTCHA/WAF bypass.
- Never overwrite unrelated files.
- Output must stay inside the requested output directory.
- Normalize and validate Windows Unicode paths.

## Job schema v1

JSON fields:
- schema_version: `1.0`
- job_id
- store_id / store_name
- asset_type: `HERO_BANNER`, `COLLECTION_SQUARE`, or `COLLECTION_CARD`
- prompt / negative_prompt
- text_policy
- target: width, height, aspect_ratio
- safe_zone: preferred_text_side, text_safe_percent, mobile_center_safe
- brand: brand_name, visual_tone, palette, avoid
- collection: collection_key, collection_title
- reference_images
- output_count
- output_dir
- request_context

### text_policy

- `NO_EMBEDDED_TEXT` — default for generated hero/category art. ShopSource overlays text in Shopify.
- `ALLOW_EXISTING_TEXT_REFERENCE` — reference may contain text, but generator adds no new text.
- `PRECOMPOSED_TEXT` — explicit user choice only; return mobile/accessibility warning.

### target defaults

ShopSource supplies actual theme-driven target size when known.
Fallbacks:
- HERO_BANNER: 1920×1080
- COLLECTION_SQUARE: 1200×1200
- COLLECTION_CARD: 1200×900

## Result schema v1

Result fields:
- schema_version
- job_id
- status
- provider
- model
- created_at
- recommended_candidate_id
- candidates[] with candidate_id, path, mime_type, width, height, sha256, prompt_hash, source_type, technical_score, warnings
- warnings
- error

Status values:
- `SUCCEEDED`
- `PARTIAL`
- `WAITING_FOR_CONFIGURATION`
- `FAILED`

The bridge must atomically write the result JSON and return non-zero exit status for FAILED.

## Capabilities response

Expose:
- bridge: `shopsource-image-studio`
- schema_versions
- asset_types
- providers
- supports_reference_images
- supports_output_count
- supports_no_text_policy
- supports_unicode_paths

ShopSource must feature-detect capabilities instead of assuming them.

## Existing YouTubeSum functionality

Existing non-generative A/B/C thumbnail and motion functionality must remain unchanged.
The bridge may reuse Unicode-safe image I/O and output verification, but must not bake
ShopSource-specific logic into existing YouTube channel presets.

## Technical quality checks

Each returned candidate must pass:
- file exists and non-zero size
- decodable image
- expected MIME/extension
- minimum dimensions
- aspect ratio tolerance
- SHA-256
- path contained inside requested output directory
- duplicate candidate hashes rejected unless explicitly allowed

Technical PASS is not visual/brand approval.

## Candidate recommendation

The bridge may recommend one candidate using technical/layout heuristics only.
ShopSource default behavior:
1. generate candidates automatically
2. show recommended candidate
3. allow one-click approval
4. only approved asset may be uploaded/applied to Shopify

`AUTO_APPROVE_TECHNICAL_PASS` is optional future behavior and must be OFF by default.

## Hero behavior

Default direction:
- photorealistic premium commerce lifestyle
- no embedded text/logo/watermark
- strong subject clarity
- text-safe area requested by ShopSource
- mobile-center-safe crop
- avoid visible third-party trademarks where practical

ShopSource owns headline/body/CTA/link/theme overlay.
YouTubeSum owns image generation/rendering/output verification.

## Collection behavior

- visually obvious category subject
- consistent style across sibling collections
- no embedded category title by default
- no watermark/logo
- no unrelated duplicate reuse
- square or requested aspect

ShopSource should reuse an approved collection image before requesting new generation.

## Failure handling

- missing local model/provider config → `WAITING_FOR_CONFIGURATION`
- missing Python dependency → `FAILED` with code `DEPENDENCY_MISSING`
- generation failure → `FAILED` or `PARTIAL`
- invalid image output → reject candidate and continue when possible
- no surviving candidates → `FAILED`

Return machine-readable `error.code` and beginner-readable `error.message_ko`.

## Dependency doctor

Add command:

    python shopsource_bridge.py --doctor

Verify:
- Python version
- Pillow
- numpy
- OpenCV
- configured generator backend dependencies
- writable temp/output directory

Do not silently install large ML dependencies. Return exact repair commands.

## Backward compatibility

Do not break:
- `python app.py`
- A/B/C candidate generation
- Motion Intro
- existing Unicode-path behavior

## Tests

At minimum:
- health/capabilities
- valid hero job
- valid collection job
- Unicode Windows paths
- output path escape rejected
- no secrets in result
- partial failure
- missing dependency doctor
- duplicate output hash detection
- existing thumbnail regression

No paid model/API call in unit tests.
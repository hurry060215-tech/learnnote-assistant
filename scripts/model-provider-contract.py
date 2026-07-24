from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


REQUIRED_FIELDS = {
    "key",
    "label",
    "base_url",
    "model",
    "transcriber",
    "whisper_model",
    "tier",
    "recommended",
    "capabilities",
}
ALLOWED_CAPABILITIES = {"text", "vision", "asr"}
ALLOWED_TRANSCRIBERS = {"faster-whisper", "openai-compatible", "groq"}


def load_runtime_helpers():
    source_path = BACKEND / "app" / "summarizer.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    helper_names = {"llm_provider_name", "llm_model_supports_vision"}
    helpers = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in helper_names
    ]
    if {node.name for node in helpers} != helper_names:
        raise RuntimeError("Provider classifier helpers were not found in backend/app/summarizer.py.")
    module = ast.Module(body=helpers, type_ignores=[])
    namespace = {"re": re, "urlparse": urlparse}
    exec(compile(module, str(source_path), "exec"), namespace)
    return namespace["llm_provider_name"], namespace["llm_model_supports_vision"]


llm_provider_name, llm_model_supports_vision = load_runtime_helpers()


def load_presets() -> list[dict]:
    source_path = BACKEND / "app" / "main.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "MODEL_PROVIDER_PRESETS" for target in node.targets):
            value = ast.literal_eval(node.value)
            if not isinstance(value, list):
                raise RuntimeError("MODEL_PROVIDER_PRESETS must be a list.")
            return value
    raise RuntimeError("MODEL_PROVIDER_PRESETS was not found in backend/app/main.py.")


def validate_preset(preset: dict, seen_keys: set[str]) -> list[str]:
    key = str(preset.get("key") or "")
    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - set(preset))
    if missing:
        errors.append(f"{key or '<missing-key>'}: missing fields {', '.join(missing)}")
    if not key or key in seen_keys:
        errors.append(f"{key or '<missing-key>'}: key must be non-empty and unique")
    seen_keys.add(key)

    parsed = urlparse(str(preset.get("base_url") or ""))
    if parsed.scheme != "https" or not parsed.netloc:
        errors.append(f"{key}: base_url must be an absolute HTTPS URL")
    elif llm_provider_name(preset["base_url"]) != key:
        errors.append(
            f"{key}: provider classifier returned {llm_provider_name(preset['base_url'])!r}"
        )

    capabilities = preset.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        errors.append(f"{key}: capabilities must be a non-empty list")
        capabilities = []
    unknown_capabilities = sorted(set(capabilities) - ALLOWED_CAPABILITIES)
    if unknown_capabilities:
        errors.append(f"{key}: unsupported capabilities {', '.join(unknown_capabilities)}")
    if "text" not in capabilities:
        errors.append(f"{key}: every summary provider must advertise text capability")

    transcriber = str(preset.get("transcriber") or "")
    if transcriber not in ALLOWED_TRANSCRIBERS:
        errors.append(f"{key}: unsupported transcriber {transcriber!r}")
    if "asr" in capabilities and transcriber == "faster-whisper":
        errors.append(f"{key}: remote ASR capability cannot use only faster-whisper")
    if "asr" not in capabilities and transcriber != "faster-whisper":
        errors.append(f"{key}: remote transcriber requires the asr capability")

    model = str(preset.get("model") or "").strip()
    whisper_model = str(preset.get("whisper_model") or "").strip()
    if not model:
        errors.append(f"{key}: model must be non-empty")
    if not whisper_model:
        errors.append(f"{key}: whisper_model must be non-empty")
    inferred_vision = llm_model_supports_vision(str(preset.get("base_url") or ""), model)
    if inferred_vision != ("vision" in capabilities):
        errors.append(
            f"{key}: vision capability={('vision' in capabilities)} "
            f"but runtime inference={inferred_vision}"
        )
    if not isinstance(preset.get("recommended"), bool):
        errors.append(f"{key}: recommended must be boolean")
    return errors


def live_check(preset: dict, api_key: str, timeout: float) -> dict:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("The openai package is required for --live-provider.") from exc

    client = OpenAI(
        api_key=api_key,
        base_url=preset["base_url"],
        timeout=timeout,
        max_retries=0,
    )
    response = client.chat.completions.create(
        model=preset["model"],
        messages=[
            {
                "role": "user",
                "content": "Reply with exactly LEARNNOTE_PROVIDER_OK.",
            }
        ],
        max_tokens=24,
        temperature=0,
    )
    text = str(response.choices[0].message.content or "").strip()
    if "LEARNNOTE_PROVIDER_OK" not in text:
        raise RuntimeError(f"Provider returned an unexpected response: {text[:160]!r}")
    return {
        "provider": preset["key"],
        "model": preset["model"],
        "status": "pass",
        "response": "LEARNNOTE_PROVIDER_OK",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate LearnNote model-provider presets offline; network calls require explicit --live-provider."
    )
    parser.add_argument("--live-provider", help="Explicit provider key to test with a real text completion.")
    parser.add_argument(
        "--api-key-env",
        help="Environment variable containing the live API key. Defaults to LEARNNOTE_<PROVIDER>_API_KEY, then LEARNNOTE_LLM_API_KEY.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args()

    presets = load_presets()
    seen_keys: set[str] = set()
    errors = [
        error
        for preset in presets
        for error in validate_preset(preset, seen_keys)
    ]
    report: dict = {
        "status": "pass" if not errors else "fail",
        "mode": "offline",
        "network_attempted": False,
        "provider_count": len(presets),
        "providers": [preset.get("key") for preset in presets],
        "errors": errors,
    }

    if not errors and args.live_provider:
        selected = next((item for item in presets if item.get("key") == args.live_provider), None)
        if selected is None:
            errors.append(f"Unknown live provider: {args.live_provider}")
        else:
            default_env = f"LEARNNOTE_{args.live_provider.upper().replace('-', '_')}_API_KEY"
            key_env = args.api_key_env or default_env
            api_key = os.getenv(key_env) or os.getenv("LEARNNOTE_LLM_API_KEY", "")
            if not api_key:
                errors.append(
                    f"Live provider key is missing; set {key_env} or LEARNNOTE_LLM_API_KEY."
                )
            else:
                report["mode"] = "live"
                report["network_attempted"] = True
                try:
                    report["live_result"] = live_check(selected, api_key, max(5.0, args.timeout))
                except Exception:
                    errors.append(
                        f"{args.live_provider}: live check failed; response details were redacted."
                    )

    report["errors"] = errors
    report["status"] = "pass" if not errors else "fail"
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output:
        args.json_output.expanduser().resolve().write_text(encoded, encoding="utf-8")
    print(encoded)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Configuration for extraction v3.10."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from modules.extraction_v3.config import ModelConfig, ModelProvider, PROJECT_ROOT


@dataclass
class V310Config:
    models: Dict[str, ModelConfig] = field(
        default_factory=lambda: {
            "scanner": ModelConfig(
                "deepseek-v3.1:671b-cloud", ModelProvider.DEEPSEEK, 0.1, 32768
            ),
            "entity_mapper": ModelConfig(
                "deepseek-v3.1:671b-cloud", ModelProvider.DEEPSEEK, 0.1, 32768
            ),
            "argument_extractor": ModelConfig(
                "deepseek-v3.1:671b-cloud", ModelProvider.DEEPSEEK, 0.2, 32768
            ),
            "timeline_builder": ModelConfig(
                "deepseek-v3.1:671b-cloud", ModelProvider.DEEPSEEK, 0.1, 32768
            ),
            "cross_validator": ModelConfig(
                "cogito-2.1:671b-cloud", ModelProvider.OLLAMA, 0.0, 32768
            ),
            "alignment_verifier": ModelConfig(
                "cogito-2.1:671b-cloud", ModelProvider.OLLAMA, 0.0, 32768
            ),
            "auditor": ModelConfig(
                "cogito-2.1:671b-cloud", ModelProvider.OLLAMA, 0.0, 32768
            ),
            "orchestrator": ModelConfig(
                "cogito-2.1:671b-cloud", ModelProvider.OLLAMA, 0.2, 32768
            ),
        }
    )
    max_reflexion_rounds: int = 2
    max_judgment_chars: int = 100000
    output_dir: Path = PROJECT_ROOT / "data" / "extractions_v3.10"
    ollama_base_url: str = "http://192.168.224.1:11434"


DEFAULT_V310_CONFIG = V310Config()


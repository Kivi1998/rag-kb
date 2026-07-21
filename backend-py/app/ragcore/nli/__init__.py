"""自然语言推理（NLI）自检网关。对应 Java 版 `ragcore/nli/`。"""

from app.ragcore.nli.client import NliClient, NliVerdict
from app.ragcore.nli.gate import NliSelfCheckGate
from app.ragcore.nli.http_client import HttpNliClient, build_nli_client

__all__ = [
    "NliClient",
    "NliVerdict",
    "NliSelfCheckGate",
    "HttpNliClient",
    "build_nli_client",
]
